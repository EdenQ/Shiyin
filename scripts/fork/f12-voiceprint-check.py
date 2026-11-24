#!/usr/bin/env python3
"""F12 說話者聲紋的自動化驗證（fork design §F12.8）。

對一個已經開著、用暫存 SHIYIN_HOME、測試 bundle id 的 DEBUG 版跑（check.sh #16）。不用使用者的真實資料：
  0. seedfixtures 放示範會議（zh、en、ja、yue、ko 各一場），peopledeleteall 清掉示範的聲紋庫
  1. mavoice setvoice 給說話者合成的 256 維向量（正交的基底，相似度照設計好的值），經過上游的 renameSpeaker 建聲紋庫
  2. 防呆：0.95／0.26（requirements F12 的例子）會擋、check 的數字；取消、只改名、仍要存三個選項的結果；沒有樣本的新名字；
     不需要提醒的照常改
  3. 分數：上游 matchVoiceprints 之後，自動帶入的依據、聲紋建議的原因（兩人很像、建議過時）、AI 猜的「依內容猜」，
     文字和數字跟這裡用同樣規則算的一樣
  4. 全部套用：只有該擋的進同一個佇列，「只改名」一次套用到全部
  5. 來源紀錄：manual、suggestion、merge，舊資料「不明」；人物頁的資料（可疑標記、相似度）；刪單份聲紋
  6. §F-DB：分成兩場、合併人、永久刪除會議、刪人之後，沒有指不到聲紋的來源紀錄；foreign_key_check 沒有東西
  7. REV-F12 的反例：聲紋庫快取暖著時分成兩場（只改 meeting_id），自身排除、防呆、人物頁的來源會議照新的；
     改會議語言（en → zh、zh → ja、一般語言 ko → zh）後聲紋的建議照樣認得、用目前的語言顯示；時間空的 AI 建議不當成聲紋
  8. 其他要確認的樣本（F12.11a）：A 跟本人其他不像、B 兩份互相不像、C 跟來源說話者現在的聲音對不上；
     來源說話者不在、會議永久刪除後不比；互相一致的正常樣本不標
  9. 重新轉錄後名字跟著聲音（F12.15）：mavoice retranscribe 模擬（編號對調、聲音對不上、沒聲紋照編號、F2 標記不沿用、
     對不上的存成建議被聲紋比對蓋掉後補回、一鍵套用、舊聲紋刪除與重新學、來源 retranscribe）
  10. windowshot：防呆視窗開著的會議頁、人物頁（看一眼）
用法：python3 scripts/fork/f12-voiceprint-check.py <SHIYIN_HOME> <shiyinctl> --out <資料夾> [--fixtures <fixtures.json>]
只讀寫 --out 和暫存 SHIYIN_HOME 的資料庫；同時只能開一個 DEBUG 版（shiyinctl 是廣播）。exit 0 通過、1 不符。
"""
import argparse
import json
import math
import sqlite3
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('home', type=Path)
ap.add_argument('ctl', type=Path)
ap.add_argument('--out', type=Path, required=True)
ap.add_argument('--fixtures', type=Path, default=ROOT / 'shared/golden/fixtures.json')
ap.add_argument('--phase', choices=('all', 'restart-seed', 'restart-check', 'restart-final'), default='all',
                help='restart-*：check.sh 在中間真的結束、再開同一個 SHIYIN_HOME 的 DEBUG 版（F12.15 的建議不因重啟遺失或復活）')
args = ap.parse_args()
HOME, CTL, OUT = args.home.resolve(), args.ctl, args.out.resolve()
if HOME == (Path.home() / 'Library/Application Support/Shiyin').resolve():
    sys.exit('不能對正式的資料夾跑')
DB = HOME / 'shiyin.sqlite'
if not DB.exists():
    sys.exit(f'{HOME} 沒有 shiyin.sqlite（DEBUG 版要先用這個 SHIYIN_HOME 開著）')
OUT.mkdir(parents=True, exist_ok=True)
results = []
DIM = 256
AUTO, SUGGEST, MARGIN, TARGET = 0.88, 0.65, 0.15, 0.50


def check(name, ok, detail=''):
    results.append({'check': name, 'ok': bool(ok), 'detail': detail})
    print(('PASS ' if ok else 'FAIL ') + name + (f'：{detail}' if detail else ''), flush=True)
    return ok


def ctl(*a):
    subprocess.run([str(CTL), *map(str, a)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def output(*a, name, timeout=15):
    """送一個會寫 JSON 的指令（輸出路徑放最後），等檔案出現"""
    path = OUT / f'{name}.json'
    path.unlink(missing_ok=True)
    ctl(*a, path)
    end = time.time() + timeout
    while time.time() < end:
        if path.exists() and path.stat().st_size > 0:
            time.sleep(0.2)
            try:
                return json.loads(path.read_text())
            except json.JSONDecodeError:
                pass
        time.sleep(0.2)
    raise SystemExit(f'{" ".join(map(str, a))} 沒有寫出 {path.name}（DEBUG 版沒回應或當掉了）')


def settle():
    """指令照順序處理；等一下讓 perform、reload 做完"""
    time.sleep(0.8)


def q(sql, params=()):
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=10)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def write_sql(sql, params=()):
    con = sqlite3.connect(DB, timeout=10)
    try:
        con.execute(sql, params)
        con.commit()
    finally:
        con.close()


# ---------- 向量 ----------

def unit(k):
    v = [0.0] * DIM
    v[k] = 1.0
    return v


def mix(*parts):
    """parts: (係數, 基底編號)；最後補一個正交的分量讓長度是 1"""
    v = [0.0] * DIM
    used = 0.0
    for c, k in parts[:-1]:
        v[k] += c
        used += c * c
    v[parts[-1]] = math.sqrt(max(0.0, 1 - used))
    return v


def f32(v):
    return list(struct.unpack(f'<{len(v)}f', struct.pack(f'<{len(v)}f', *v)))


def cos(a, b):
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def pct(s):
    return max(0, int(math.floor(s * 100 + 0.5)))


def setvoice(meeting, idx, vector, seconds=30):
    path = OUT / f'vec-{meeting}-{idx}.json'
    path.write_text(json.dumps(vector))
    ctl('mavoice', 'setvoice', meeting, idx, seconds, path)
    settle()


def library():
    """跟 app 同樣的規則：每人每份聲紋"""
    rows = q('SELECT v.id, v.person_id, p.name, v.meeting_id, v.speaker_idx, v.embedding FROM voiceprints v JOIN people p ON p.id = v.person_id')
    return [{'id': r[0], 'person': r[1], 'name': r[2], 'meeting': r[3], 'idx': r[4],
             'vec': list(struct.unpack(f'<{len(r[5]) // 4}f', r[5]))} for r in rows]


def rank(vector, prints, exclude=None):
    best = {}
    for p in prints:
        if exclude and p['meeting'] == exclude[0] and p['idx'] == exclude[1]:
            continue
        s = cos(vector, p['vec'])
        if p['person'] not in best or s > best[p['person']][1]:
            best[p['person']] = (p['name'], s)
    return sorted(((n, s) for n, s in best.values()), key=lambda x: (-x[1], x[0]))


PHRASES = {
    'zh': dict(head='聲紋比對：{} {}%（{}）', second='第二像 {} {}%', now='現在最像的是 {} {}%', close='兩人很像，請確認', sep='・',
               levels=('很像', '有點像', '不像'), content='依內容猜：'),
    'en': dict(head='Voice match: {} {}% ({})', second='next {} {}%', now='closest now: {} {}%', close='the two sound alike, please check',
               sep=' · ', levels=('very close', 'possible', 'unlikely'), content='Guessed from what was said: '),
    'ja': dict(head='声の照合：{} {}%（{}）', second='次点 {} {}%', now='今いちばん近いのは {} {}%', close='二人の声が近いので確認してください',
               sep='・', levels=('よく似ている', '似ている', '似ていない'), content='内容から推測：'),
}


def level(p, s):
    return p['levels'][0 if s >= AUTO else 1 if s >= SUGGEST else 2]


def describe(ranked, name, p):
    mine = next((r for r in ranked if r[0].lower() == name.lower()), None)
    top = ranked[0]
    lead = mine or top
    parts = [p['head'].format(lead[0], pct(lead[1]), level(p, lead[1]))]
    if lead[0] == top[0]:
        if len(ranked) > 1:
            parts.append(p['second'].format(ranked[1][0], pct(ranked[1][1])))
            if top[1] - ranked[1][1] < MARGIN:
                parts.append(p['close'])
    else:
        parts.append(p['now'].format(top[0], pct(top[1])))
        if top[1] - lead[1] < MARGIN:
            parts.append(p['close'])
    return p['sep'].join(parts)


def state(name):
    return output('mavoice', 'state', name=name)


def speaker(st, idx):
    return next((s for s in st['speakers'] if s['idx'] == idx), None)


def speaker_row(meeting, idx):
    r = q('SELECT name, name_source, person_id, suggested_name FROM speakers WHERE meeting_id = ? AND idx = ?', (meeting, idx))
    return r[0] if r else None


def prints_of(meeting, idx):
    return q('SELECT v.id, v.person_id, s.source, s.warned FROM voiceprints v LEFT JOIN ma_voiceprint_source s ON s.voiceprint_id = v.id '
             'WHERE v.meeting_id = ? AND v.speaker_idx = ?', (meeting, idx))


def person_id(name):
    r = q('SELECT id FROM people WHERE name = ? COLLATE NOCASE', (name,))
    return r[0][0] if r else None


def shot(name, kind='main'):
    png = OUT / f'{name}.png'
    png.unlink(missing_ok=True)
    if kind == 'main':
        ctl('windowshot', png, 'main')
    else:
        ctl('mawindowshot', png, kind)
    end = time.time() + 10
    while time.time() < end and not png.exists():
        time.sleep(0.3)
    return png.exists() and png.stat().st_size > 0


def main():
    ctl('seedfixtures', args.fixtures, 'zh', 'en', 'ja', 'yue', 'ko')
    time.sleep(3)
    ids = {lang: mid for mid, lang in q("SELECT id, language FROM meetings WHERE deleted_at IS NULL ORDER BY id")}
    if not check('示範會議：zh、en、ja、yue、ko 各一場', all(k in ids for k in ('zh', 'en', 'ja', 'yue', 'ko')), json.dumps(ids)):
        return
    A, B, C, D, E = ids['en'], ids['zh'], ids['ja'], ids['yue'], ids['ko']
    ctl('peopledeleteall')
    settle()
    check('示範的聲紋庫清空', q('SELECT count(*) FROM voiceprints')[0][0] == 0)
    tables = {r[0] for r in q("SELECT name FROM sqlite_master WHERE type = 'table'")}
    check('migration ma_voiceprint_source_v1：兩張表', {'ma_voiceprint_source', 'ma_voiceprint_pending'} <= tables)

    # ---------- 1. 聲紋庫：Amy（e0）、Ben（e1），經過上游的取名 ----------
    AMY, BEN = unit(0), unit(1)
    setvoice(A, 1, AMY)
    setvoice(A, 2, BEN)
    ctl('mavoice', 'rename', A, 1, 'Amy'); settle()
    ctl('mavoice', 'rename', A, 2, 'Ben'); settle()
    amy, ben = person_id('Amy'), person_id('Ben')
    check('取名 Amy、Ben：連到人、各存一份聲紋', amy and ben and len(prints_of(A, 1)) == 1 and len(prints_of(A, 2)) == 1,
          f'Amy={amy} Ben={ben} prints={prints_of(A, 1)} {prints_of(A, 2)}')
    src = prints_of(A, 1)
    check('來源：手動取名記成 manual、沒提醒過', src and src[0][2] == 'manual' and src[0][3] == 0, str(src))

    # ---------- 2. 分數（在防呆的「仍要存」之前：那份是 Amy 的聲音存成 Ben，會讓 Ben 的分數變高） ----------
    C1 = mix((0.97, 0), 6)
    C2 = mix((0.75, 1), (0.62, 0), 7)
    setvoice(C, 1, C1)
    setvoice(C, 2, C2)
    ctl('select', C); settle()
    ctl('mavoice', 'match', C); settle()
    st = state('scores-match')
    lib = library()
    s1, s2 = speaker(st, 1), speaker(st, 2)
    check('上游 matchVoiceprints：說話者 1 自動帶入 Amy、說話者 2 是 Ben 的建議',
          s1 and s1['source'] == 'voiceprint' and s1['name'] == 'Amy' and s2 and s2.get('suggestion', {}).get('name') == 'Ben',
          json.dumps([s1, s2], ensure_ascii=False))
    r1 = rank(f32(C1), lib, (C, 1))
    want = describe(r1, 'Amy', PHRASES['zh'])
    check('自動帶入的依據（介面語言）', s1 and s1['autoBasis'] == want, f'{s1 and s1["autoBasis"]} ／ 預期 {want}')
    r2 = rank(f32(C2), lib, (C, 2))
    want = describe(r2, 'Ben', PHRASES['ja'])
    got = (s2 or {}).get('suggestion', {}).get('reason')
    check('聲紋建議的原因（會議語言 ja）：分數、第二像、兩人很像', got == want and PHRASES['ja']['close'] in want, f'{got} ／ 預期 {want}')

    # 建議過時：另一場有人取名 Amy、聲音跟 C2 一樣 → 現在最像的是 Amy
    setvoice(D, 1, C2)
    ctl('mavoice', 'rename', D, 1, 'Amy'); settle()
    check('取名 Amy（別人只有 0.75，不擋）', speaker_row(D, 1)[0] == 'Amy' and len(prints_of(D, 1)) == 1, str(speaker_row(D, 1)))
    ctl('select', C); settle()
    st = state('scores-stale')
    lib = library()
    r2 = rank(f32(C2), lib, (C, 2))
    want = describe(r2, 'Ben', PHRASES['ja'])
    got = (speaker(st, 2) or {}).get('suggestion', {}).get('reason')
    check('建議過時：寫「現在最像的是 Amy」', got == want and '今いちばん近いのは Amy' in (got or ''), f'{got} ／ 預期 {want}')

    # AI 猜的
    ctl('mavoice', 'suggest', D, 2, '陳小華', '00:01:23', '自我介紹時說了名字'); settle()
    ctl('select', D); settle()
    st = state('scores-content')
    sg = (speaker(st, 2) or {}).get('suggestion', {})
    prefixes = [p['content'] for p in PHRASES.values()]
    check('AI 猜的：前面加「依內容猜」、時間點照舊、沒有分數',
          sg.get('time') == '00:01:23' and any(sg.get('reason', '') == pre + '自我介紹時說了名字' for pre in prefixes), json.dumps(sg, ensure_ascii=False))

    # ---------- 3. 防呆 ----------
    B1 = mix((0.95, 0), (0.26, 1), 3)
    setvoice(B, 1, B1)
    ctl('select', B); settle()
    v = output('mavoice', 'check', B, 1, 'Ben', name='check-b1-ben')
    lib = library()
    want_amy, want_ben = cos(f32(B1), f32(AMY)), cos(f32(B1), f32(BEN))
    check('防呆：0.95／0.26 會擋（別人 Amy、取的 Ben）',
          v['warn'] and v['other'] == 'Amy' and abs(v['otherScore'] - want_amy) < 1e-4 and abs(v['target'] - want_ben) < 1e-4,
          json.dumps(v))
    v2 = output('mavoice', 'check', B, 1, 'Amy', name='check-b1-amy')
    check('防呆：取成很像的 Amy 不擋', not v2['warn'], json.dumps(v2))

    before = speaker_row(B, 1)
    ctl('mavoice', 'rename', B, 1, 'Ben'); settle()
    st = state('guard-held')
    g = st['guard']
    check('防呆：改名先擋下，佇列 1 位、視窗打開',
          len(g) == 1 and g[0]['idx'] == 1 and g[0]['name'] == 'Ben' and g[0]['other'] == 'Amy' and st['guardShowing'], json.dumps(g, ensure_ascii=False))
    check('防呆：擋下時名字、聲紋都沒動', speaker_row(B, 1) == before and not prints_of(B, 1), f'{speaker_row(B, 1)} {prints_of(B, 1)}')
    want_line = f'「{g[0]["current"]}」→ Ben：聲音很像 Amy（{pct(want_amy)}%），跟 Ben 之前的聲音只有 {pct(want_ben)}%。' if g else ''
    check('防呆：視窗的那一列', g and g[0]['line'] == want_line, g[0]['line'] if g else '')
    check('截圖：防呆視窗開著的會議頁', shot('f12-guard-main'))
    shot('f12-guard-sheet', 'Sheet')   # 視窗本身（類別名稱有 Sheet 時才拍得到；看一眼用，不算一項）

    ctl('mavoice', 'choose', 'cancel'); settle()
    st = state('guard-cancel')
    check('取消：佇列清空、名字和聲紋都沒變', not st['guard'] and speaker_row(B, 1) == before and not prints_of(B, 1),
          f'{speaker_row(B, 1)} {prints_of(B, 1)}')

    ctl('mavoice', 'rename', B, 1, 'Ben'); settle()
    ctl('mavoice', 'choose', 'nameonly'); settle()
    row = speaker_row(B, 1)
    check('只改名：名字改成 Ben、連到 Ben、沒有這位的聲紋', row and row[0] == 'Ben' and row[2] == ben and not prints_of(B, 1),
          f'{row} {prints_of(B, 1)}')
    check('只改名：Ben 還是只有原本那一份', q('SELECT count(*) FROM voiceprints WHERE person_id = ?', (ben,))[0][0] == 1)

    setvoice(B, 1, B1)
    ctl('mavoice', 'rename', B, 1, 'Ben'); settle()
    ctl('mavoice', 'choose', 'keep'); settle()
    row, p = speaker_row(B, 1), prints_of(B, 1)
    check('仍要存：名字 Ben、存了這位的聲紋、來源 manual、提醒過',
          row and row[0] == 'Ben' and len(p) == 1 and p[0][1] == ben and p[0][2] == 'manual' and p[0][3] == 1, f'{row} {p}')
    kept = p[0][0] if p else None

    B2 = mix((0.93, 0), 4)
    setvoice(B, 2, B2)
    ctl('mavoice', 'rename', B, 2, 'Zed'); settle()
    st = state('guard-new-name')
    g = st['guard']
    check('防呆：沒有樣本的新名字也擋（Zed，聲音很像 Amy）',
          len(g) == 1 and g[0]['target'] is None and g[0]['line'].endswith('Zed 還沒有聲音樣本。'), json.dumps(g, ensure_ascii=False))
    ctl('mavoice', 'choose', 'cancel'); settle()
    check('取消新名字：沒有建立 Zed', person_id('Zed') is None)

    B3 = unit(5)
    setvoice(B, 3, B3)
    ctl('mavoice', 'rename', B, 3, 'Dan'); settle()
    st = state('guard-none')
    p = prints_of(B, 3)
    check('不需要提醒的照常改：Dan、存聲紋、沒有擋', not st['guard'] and speaker_row(B, 3)[0] == 'Dan' and len(p) == 1 and p[0][3] == 0,
          f'{speaker_row(B, 3)} {p}')

    # 改會議語言（REV-F12 P2-2）：上游存的原因是當時的語言、改語言後不重寫；聲紋的建議仍要認得，用目前的語言重新產生
    def stored_reason():
        r = q('SELECT suggestion_reason FROM speakers WHERE meeting_id = ? AND idx = 2', (C,))
        return r[0][0] if r else None

    def relang(created, shown, want_stored):
        ctl('language', C, created); settle()
        setvoice(C, 2, C2)
        ctl('mavoice', 'match', C); settle()
        stored = stored_reason()
        ctl('language', C, shown); settle()
        st = state(f'lang-{created}-{shown}')
        got = (speaker(st, 2) or {}).get('suggestion', {}).get('reason')
        want = describe(rank(f32(C2), library(), (C, 2)), 'Ben', PHRASES['zh' if shown in ('zh', 'yue') else 'ja' if shown == 'ja' else 'en'])
        check(f'改會議語言 {created} → {shown}：聲紋的建議照樣顯示依據（用 {shown} 重新產生）',
              stored == want_stored and got == want, f'stored={stored} ／ got={got} ／ 預期 {want}')

    relang('en', 'zh', 'Sounds like Ben from earlier meetings')
    relang('zh', 'ja', '聲音跟之前的Ben很像')
    relang('ko', 'zh', '이전 회의의 Ben 님과 목소리가 비슷합니다')
    setvoice(C, 2, C2)
    ctl('mavoice', 'suggest', C, 2, 'Zoe', '', '說了自己的名字'); settle()
    st = state('lang-content-empty-time')
    sg = (speaker(st, 2) or {}).get('suggestion', {})
    check('時間空的 AI 建議不會被當成聲紋的', sg.get('reason') == PHRASES['zh']['content'] + '說了自己的名字', json.dumps(sg, ensure_ascii=False))
    ctl('language', C, 'ja'); settle()

    # ---------- 4. 全部套用 ----------
    E1 = mix((0.95, 0), 9)
    E2 = mix((0.92, 1), 10)
    E3 = unit(11)
    for i, vec in ((1, E1), (2, E2), (3, E3)):
        setvoice(E, i, vec)
    ctl('mavoice', 'suggest', E, 1, 'Dan', '00:00:10', 'x'); settle()
    ctl('mavoice', 'suggest', E, 2, 'Kai', '00:00:20', 'y'); settle()
    ctl('mavoice', 'suggest', E, 3, 'Mia', '00:00:30', 'z'); settle()
    ctl('mavoice', 'applyall', E); settle()
    st = state('batch-held')
    g = st['guard']
    check('全部套用：只有 2 位進同一個佇列（Dan、Kai），Mia 直接改',
          sorted(x['idx'] for x in g) == [1, 2] and st['guardShowing'] and speaker_row(E, 3)[0] == 'Mia', json.dumps(g, ensure_ascii=False))
    p3 = prints_of(E, 3)
    check('Mia 的聲紋來源是 suggestion', len(p3) == 1 and p3[0][2] == 'suggestion' and p3[0][3] == 0, str(p3))
    check('截圖：全部套用時的會議頁', shot('f12-batch-main'))
    shot('f12-batch-sheet', 'Sheet')
    ctl('mavoice', 'choose', 'nameonly'); settle()
    r1, r2 = speaker_row(E, 1), speaker_row(E, 2)
    check('只改名一次套用到全部：Dan、Kai，建議清掉，都沒有聲紋',
          r1[0] == 'Dan' and r2[0] == 'Kai' and r1[3] is None and r2[3] is None and not prints_of(E, 1) and not prints_of(E, 2), f'{r1} {r2}')

    # ---------- 5. 來源、人物頁、刪單份 ----------
    A3 = unit(12)
    setvoice(A, 3, A3)
    ctl('mavoice', 'rename', A, 3, 'Cat'); settle()
    ctl('mergespeaker', A, 3, 2); settle()
    p = prints_of(A, 2)
    check('合併說話者後重新學：來源 merge', len(p) == 1 and p[0][2] == 'merge', str(p))
    write_sql("INSERT INTO voiceprints (person_id, embedding, audio_source, meeting_id, speaker_idx, created_at) VALUES (?, ?, 'mix', NULL, NULL, '2026-01-01T00:00:00Z')",
              (amy, struct.pack(f'<{DIM}f', *AMY)))
    pr = output('mavoice', 'prints', amy, name='prints-amy')['rows']
    check('人物頁：F12 之前的聲紋顯示「不明」、會議已刪除', any(r['source'] is None and r['label'] == '不明' and r['meetingId'] is None for r in pr),
          json.dumps(pr, ensure_ascii=False)[:400])
    pr = output('mavoice', 'prints', ben, name='prints-ben')['rows']
    row = next((r for r in pr if r['id'] == kept), None)
    lib = library()
    ben_prints = [x for x in lib if x['person'] == ben]
    kept_vec = next(x['vec'] for x in lib if x['id'] == kept)
    own = max(cos(kept_vec, x['vec']) for x in ben_prints if x['id'] != kept)
    check('人物頁：仍要存的那份標成可疑（跟 Ben 其他樣本不像、跟 Amy 很像）',
          row and row['suspicious'] and row['other'] == 'Amy' and row['warned'] and abs(row['ownBest'] - own) < 1e-4 and row['label'] == '手動取名',
          json.dumps(row, ensure_ascii=False))
    others = [r for r in pr if r['id'] != kept]
    check('人物頁：其他樣本不可疑', others and not any(r['suspicious'] for r in others), json.dumps(others, ensure_ascii=False)[:300])
    ctl('mavoice', 'person', ben); settle()
    check('截圖：人物頁', shot('f12-person-ben'))
    n_before = q('SELECT count(*) FROM voiceprints')[0][0]
    ctl('mavoice', 'delete', kept); settle()
    check('刪單份：那一份不見、其他聲紋都在、來源紀錄一起刪',
          not q('SELECT 1 FROM voiceprints WHERE id = ?', (kept,)) and q('SELECT count(*) FROM voiceprints')[0][0] == n_before - 1
          and not q('SELECT 1 FROM ma_voiceprint_source WHERE voiceprint_id = ?', (kept,)), f'before={n_before}')
    check('刪單份：會議裡的名字不變、Ben 還在', speaker_row(B, 1)[0] == 'Ben' and person_id('Ben') == ben, str(speaker_row(B, 1)))

    # ---------- 6. §F-DB ----------
    def orphans():
        return q('SELECT count(*) FROM ma_voiceprint_source WHERE voiceprint_id NOT IN (SELECT id FROM voiceprints)')[0][0]

    src_before = q('SELECT count(*) FROM ma_voiceprint_source')[0][0]
    segs = q('SELECT id, speaker FROM segments WHERE meeting_id = ? ORDER BY start', (B,))
    cut = next((sid for sid, spk in segs[1:] if spk == 3), None)
    if cut:
        ctl('splitmeeting', B, cut); settle(); time.sleep(1)
        moved = q('SELECT v.meeting_id, s.source FROM voiceprints v JOIN ma_voiceprint_source s ON s.voiceprint_id = v.id WHERE v.person_id = ?',
                  (person_id('Dan'),))
        check('分成兩場：聲紋的來源紀錄跟著（id 不變）', moved and all(m[1] == 'manual' for m in moved) and orphans() == 0, str(moved))
    else:
        check('分成兩場：找得到切點', False, str(segs[:6]))
    ctl('personrename', person_id('Dan'), 'Amy'); settle()
    check('合併人（Dan → Amy）：來源紀錄還在', q('SELECT count(*) FROM ma_voiceprint_source')[0][0] == src_before and orphans() == 0)
    ctl('purge', E); settle()
    check('永久刪除會議：pending 跟著刪、來源沒有孤兒', not q('SELECT 1 FROM ma_voiceprint_pending WHERE meeting_id = ?', (E,)) and orphans() == 0)
    ctl('purge', A); settle()
    left = q('SELECT count(*) FROM voiceprints v JOIN ma_voiceprint_source s ON s.voiceprint_id = v.id WHERE v.meeting_id IS NULL')[0][0]
    check('永久刪除會議：聲紋留著（meeting_id 是 NULL）、來源也留著', left >= 1, f'{left}')
    ctl('persondelete', person_id('Amy')); settle()
    check('刪人：聲紋和來源紀錄一起刪、沒有孤兒', orphans() == 0 and not q('SELECT 1 FROM voiceprints WHERE person_id = ?', (amy,)))
    check('foreign_key_check 沒有東西', not q('PRAGMA foreign_key_check'), str(q('PRAGMA foreign_key_check')[:5]))
    check('integrity_check ok', q('PRAGMA integrity_check')[0][0] == 'ok')

    # ---------- 7. 分成兩場後的聲紋庫（REV-F12 P2-1）：快取暖著時分割，只改 meeting_id ----------
    meetings = q("SELECT m.id FROM meetings m WHERE m.deleted_at IS NULL AND (SELECT count(*) FROM segments s WHERE s.meeting_id = m.id) > 2 ORDER BY m.id")
    others = q("SELECT id FROM meetings WHERE deleted_at IS NULL ORDER BY id")
    if not check('分割的反例：找得到 3 句以上的會議', meetings and len(others) > 1, str(meetings)):
        return
    PB = meetings[0][0]
    PC = next(m[0] for m in others if m[0] != PB)
    segs = q('SELECT id, start FROM segments WHERE meeting_id = ? ORDER BY start', (PB,))
    cut_id, cut_time = segs[1]
    write_sql('UPDATE segments SET speaker = CASE WHEN start >= ? THEN 1 ELSE 2 END WHERE meeting_id = ?', (cut_time, PB))
    setvoice(PB, 1, unit(40)); ctl('mavoice', 'rename', PB, 1, 'ProbeOwner'); settle()
    setvoice(PC, 1, unit(41)); ctl('mavoice', 'rename', PC, 1, 'ProbeOther'); settle()
    owner = person_id('ProbeOwner')
    ctl('select', PB); settle()
    pre = state('split-cache-before')
    check('分割前（快取暖著）：不算自己那一份', not any(x['name'] == 'ProbeOwner' for x in (speaker(pre, 1) or {}).get('basis', [])),
          json.dumps((speaker(pre, 1) or {}).get('basis'), ensure_ascii=False))
    output('mavoice', 'prints', owner, name='split-prints-before')
    sig_before = q('SELECT count(*), max(id), total(person_id) FROM voiceprints')
    vp = q('SELECT id FROM voiceprints WHERE meeting_id = ? AND speaker_idx = 1', (PB,))[0][0]
    ctl('splitmeeting', PB, cut_id); settle(); time.sleep(1)
    moved = q('SELECT meeting_id FROM voiceprints WHERE id = ?', (vp,))[0][0]
    sig_after = q('SELECT count(*), max(id), total(person_id) FROM voiceprints')
    check('分割：聲紋搬到新的那場，count／max(id)／total(person_id) 都沒變', moved != PB and sig_before == sig_after,
          str([PB, moved, sig_before, sig_after]))
    ctl('select', moved); settle()
    post = state('split-cache-after')
    basis = (speaker(post, 1) or {}).get('basis', [])
    check('分割後：自身排除照新的 meeting_id（不會自己跟自己 100%）', not any(x['name'] == 'ProbeOwner' for x in basis),
          json.dumps(basis, ensure_ascii=False))
    v = output('mavoice', 'check', moved, 1, 'Zed', name='split-guard')
    check('分割後的防呆：自己的樣本不會被當成「另一位」', v['other'] != 'ProbeOwner' and not v['warn'], json.dumps(v))
    rows = output('mavoice', 'prints', owner, name='split-prints-after')['rows']
    check('分割後的人物頁：來源會議是新的那場', rows and rows[0]['meetingId'] == moved, json.dumps(rows, ensure_ascii=False)[:300])

    # ---------- 8. 其他要確認的樣本（F12.11a）：A 跟本人其他不像、B 兩份互相不像、C 跟來源說話者現在的聲音對不上 ----------
    # 前面刪過、分割過會議，再放一次示範會議，只用新的這幾場
    before = q('SELECT coalesce(max(id), 0) FROM meetings')[0][0]
    ctl('seedfixtures', args.fixtures, 'zh', 'en', 'ja', 'yue', 'ko')
    time.sleep(3)
    slots = q("SELECT s.meeting_id, s.idx FROM speakers s JOIN meetings m ON m.id = s.meeting_id WHERE m.deleted_at IS NULL AND m.id > ? "
              "ORDER BY s.meeting_id, s.idx", (before,))
    by_meeting = {}
    for m, i in slots: by_meeting.setdefault(m, []).append(i)
    # 「會議已刪」要一整場只給這一項用：挑最後一場，其他項目從別場挑
    purge_meeting = max(by_meeting)
    free = [(m, i) for m, i in slots if m != purge_meeting]
    if not check('其他要確認的樣本：有足夠的說話者可以用', len(free) >= 10, f'{len(free)} 位'):
        return

    def learn(slot, name, vec):
        setvoice(slot[0], slot[1], vec)
        ctl('mavoice', 'rename', slot[0], slot[1], name); settle()
        st = state(f'flags-{name}-{slot[0]}-{slot[1]}')
        check(f'取名 {name}（{slot[0]}／{slot[1]}）沒有被防呆擋', not st['guard'], json.dumps(st['guard'], ensure_ascii=False))

    def flags_of(person, vp_slot):
        rows = output('mavoice', 'prints', person_id(person), name=f'flags-prints-{person}')['rows']
        vid = q('SELECT id FROM voiceprints WHERE meeting_id IS ? AND speaker_idx IS ? AND person_id = ?',
                (vp_slot[0], vp_slot[1], person_id(person)))
        if not vid: return None, rows
        row = next((r for r in rows if r['id'] == vid[0][0]), None)
        return (row or {}).get('flags'), rows

    pat = free[0:4]
    for k, slot in enumerate(pat[:3]):
        learn(slot, 'Pat', mix((0.95, 20), 26 + k))
    learn(pat[3], 'Pat', unit(21))
    f_odd, rows = flags_of('Pat', pat[3])
    check('A：跟本人其他 3 份（互相一致）都不像的那份標 unlikeOthers', f_odd == ['unlikeOthers'], json.dumps(rows, ensure_ascii=False)[:400])
    normal = [r for r in rows if r['id'] != q('SELECT id FROM voiceprints WHERE meeting_id = ? AND speaker_idx = ?', pat[3])[0][0]]
    check('A：互相一致的 3 份不標', len(normal) == 3 and all(not r['flags'] and not r['suspicious'] for r in normal), json.dumps(normal, ensure_ascii=False)[:400])

    quinn = free[4:6]
    learn(quinn[0], 'Quinn', unit(22))
    learn(quinn[1], 'Quinn', unit(23))
    _, rows = flags_of('Quinn', quinn[0])
    check('B：只有 2 份、互相不像，兩份都標 pairUnlike', len(rows) == 2 and all(r['flags'] == ['pairUnlike'] for r in rows), json.dumps(rows, ensure_ascii=False)[:400])

    # 無效的向量不比（REV-F12b P3-1）：全 0 的聲紋不算一份、不標；Quinn 有效的 2 份照樣互相不像
    zero = free[8]
    learn(zero, 'Quinn', [0.0] * DIM)
    zid = q('SELECT id FROM voiceprints WHERE meeting_id = ? AND speaker_idx = ?', zero)
    _, rows = flags_of('Quinn', quinn[0])
    zrow = next((r for r in rows if zid and r['id'] == zid[0][0]), None)
    valid = [r for r in rows if not zid or r['id'] != zid[0][0]]
    check('無效向量：全 0 的聲紋不標（不當成不像、也不比來源說話者）', zrow is not None and zrow['flags'] == [], json.dumps(zrow, ensure_ascii=False)[:300])
    check('無效向量：B 只數有效的聲紋，Quinn 有效的 2 份照樣標 pairUnlike',
          len(valid) == 2 and all(r['flags'] == ['pairUnlike'] for r in valid), json.dumps(valid, ensure_ascii=False)[:300])

    rae = free[6]
    learn(rae, 'Rae', unit(29))
    f, rows = flags_of('Rae', rae)
    check('C：剛存的聲紋跟來源說話者一致，不標', f == [], json.dumps(rows, ensure_ascii=False)[:300])
    write_sql('UPDATE speakers SET embedding = ? WHERE meeting_id = ? AND idx = ?', (struct.pack(f'<{DIM}f', *unit(30)), rae[0], rae[1]))
    f, rows = flags_of('Rae', rae)
    check('C：來源說話者的聲紋變了（像重新轉錄後），標 staleSpeaker', f == ['staleSpeaker'], json.dumps(rows, ensure_ascii=False)[:300])

    tor = free[7]
    learn(tor, 'Tor', unit(33))
    write_sql('UPDATE speakers SET embedding = ? WHERE meeting_id = ? AND idx = ?', (struct.pack(f'<{DIM}f', *unit(34)), tor[0], tor[1]))
    write_sql('DELETE FROM speakers WHERE meeting_id = ? AND idx = ?', tor)
    f, rows = flags_of('Tor', tor)
    check('C：來源說話者不在了就不比', f == [], json.dumps(rows, ensure_ascii=False)[:300])

    # 混合維度（REV-F12c P3-1）：Wes 的候選（256 維）跟另一份 256 維不像，另外兩份 128 維互相一致 → 候選不能跟那兩份比，不標 A
    small = lambda k: [1.0 if i == k else 0.0 for i in range(128)]
    seeded = q('SELECT coalesce(max(id), 0) FROM meetings')[0][0]
    ctl('seedfixtures', args.fixtures, 'zh', 'en', 'ja', 'yue', 'ko')
    time.sleep(3)
    mixed = q("SELECT s.meeting_id, s.idx FROM speakers s JOIN meetings m ON m.id = s.meeting_id WHERE m.deleted_at IS NULL AND m.id > ? "
              "ORDER BY s.meeting_id, s.idx", (seeded,))[:4]
    if check('混合維度：有 4 位說話者可以用', len(mixed) == 4, f'{len(mixed)}'):
        learn(mixed[0], 'Wes', unit(36))
        learn(mixed[1], 'Wes', unit(37))
        learn(mixed[2], 'Wes', small(5))
        learn(mixed[3], 'Wes', [0.99 if i == 5 else (0.141 if i == 6 else 0.0) for i in range(128)])
        f, rows = flags_of('Wes', mixed[0])
        check('混合維度：候選跟另一份 256 維不像，但 128 維的一致群不算，不標 A；可以比的只有 2 份，標 B',
              f == ['pairUnlike'], json.dumps(rows, ensure_ascii=False)[:400])
        f2, _ = flags_of('Wes', mixed[2])
        check('混合維度：128 維的兩份互相一致，不標', f2 == [], str(f2))

    uma = free[9]
    learn(uma, 'Uma', unit(35))
    write_sql("UPDATE speakers SET embedding = x'' WHERE meeting_id = ? AND idx = ?", uma)
    f, rows = flags_of('Uma', uma)
    check('無效向量：來源說話者的聲紋是空的 BLOB 時不比 C', f == [], json.dumps(rows, ensure_ascii=False)[:300])

    sky = (purge_meeting, by_meeting[purge_meeting][0])
    learn(sky, 'Sky', unit(31))
    write_sql('UPDATE speakers SET embedding = ? WHERE meeting_id = ? AND idx = ?', (struct.pack(f'<{DIM}f', *unit(32)), sky[0], sky[1]))
    ctl('purge', purge_meeting); settle(); time.sleep(1)
    f, rows = flags_of('Sky', (None, sky[1]))
    check('C：會議永久刪除後（meeting_id 是 NULL）不比', rows and all(not r['flags'] for r in rows) and rows[0]['meetingId'] is None,
          json.dumps(rows, ensure_ascii=False)[:300])
    ctl('mavoice', 'person', person_id('Pat')); settle()
    check('截圖：人物頁（要確認的樣本）', shot('f12-person-flags'))

    # ---------- 9. 重新轉錄後名字跟著聲音（F12.15） ----------
    before = q('SELECT coalesce(max(id), 0) FROM meetings')[0][0]
    ctl('seedfixtures', args.fixtures, 'zh', 'en', 'ja', 'yue', 'ko')
    time.sleep(3)
    fresh = {lang: mid for mid, lang in q("SELECT id, language FROM meetings WHERE deleted_at IS NULL AND id > ? ORDER BY id", (before,))}
    Z, EN, JA = fresh.get('zh'), fresh.get('en'), fresh.get('ja')
    if not check('重新轉錄：示範會議', Z and EN and JA, json.dumps(fresh)):
        return

    def retranscribe(meeting, spec, label):
        path = OUT / f'retranscribe-{label}.json'
        path.write_text(json.dumps(spec))
        ctl('mavoice', 'retranscribe', meeting, path); settle(); time.sleep(1)
        ctl('select', meeting); settle()
        return state(f'retranscribe-{label}')

    def sources(meeting, idx):
        return q('SELECT v.id, p.name, s.source FROM voiceprints v JOIN people p ON p.id = v.person_id '
                 'LEFT JOIN ma_voiceprint_source s ON s.voiceprint_id = v.id WHERE v.meeting_id = ? AND v.speaker_idx = ?', (meeting, idx))

    # 情況一：說話者 1、2 的編號對調；說話者 3 說話不到 8 秒（沒有聲紋可比，照編號）
    A1, B1, C1 = unit(60), unit(61), unit(62)
    setvoice(Z, 1, A1); setvoice(Z, 2, B1); setvoice(Z, 3, C1, seconds=5)
    learn((Z, 1), 'Ann2', A1)
    ctl('mavoice', 'suggest', Z, 2, 'Bob2', '00:00:05', 'x'); settle()
    ctl('mavoice', 'apply', Z, 2); settle()
    ctl('mavoice', 'rename', Z, 3, 'Cid'); settle()
    pre = {i: speaker_row(Z, i) for i in (1, 2, 3)}
    check('重新轉錄前：Ann2（手動）、Bob2（套用建議）各有聲紋，Cid 沒有',
          pre[1][0] == 'Ann2' and pre[2][0] == 'Bob2' and pre[2][1] == 'suggestion' and pre[3][0] == 'Cid' and sources(Z, 1) and sources(Z, 2) and not sources(Z, 3),
          str(pre))
    retranscribe(Z, {'map': {'1': 2, '2': 1}}, 'swap')
    post = {i: speaker_row(Z, i) for i in (1, 2, 3)}
    check('名字跟著聲音：Ann2 換到說話者 2、Bob2 換到說話者 1，來源照舊',
          post[2][0] == 'Ann2' and post[2][1] == 'manual' and post[2][2] == person_id('Ann2')
          and post[1][0] == 'Bob2' and post[1][1] == 'suggestion' and post[1][2] == person_id('Bob2'), str(post))
    check('沒有聲紋可比的照編號：Cid 還在說話者 3', post[3][0] == 'Cid', str(post[3]))
    s1, s2 = sources(Z, 1), sources(Z, 2)
    check('舊聲紋刪了，沿用的名字用新聲音重新學（來源 retranscribe）',
          len(s1) == 1 and s1[0][1] == 'Bob2' and s1[0][2] == 'retranscribe' and len(s2) == 1 and s2[0][1] == 'Ann2' and s2[0][2] == 'retranscribe',
          f'{s1} {s2}')
    lib = library()
    check('重新學的聲紋是新說話者的聲音',
          abs(cos(next(x['vec'] for x in lib if x['meeting'] == Z and x['idx'] == 2), f32(A1)) - 1) < 1e-4
          and abs(cos(next(x['vec'] for x in lib if x['meeting'] == Z and x['idx'] == 1), f32(B1)) - 1) < 1e-4)

    # 情況二：說話者 1 的聲音換成別人（對不上）；說話者 3 是 F2 標記的名字（不沿用）；另一場有 Fay 讓聲紋比對想建議她
    D1, E1, X1, T1 = unit(64), unit(65), unit(66), unit(67)
    setvoice(JA, 1, mix((0.75, 66), 68)); learn((JA, 1), 'Fay', mix((0.75, 66), 68))
    setvoice(EN, 1, D1); setvoice(EN, 2, E1); setvoice(EN, 3, T1)
    learn((EN, 1), 'Dee', D1)
    learn((EN, 2), 'Eve', E1)
    write_sql("UPDATE speakers SET name = 'Tgg', name_source = 'tag' WHERE meeting_id = ? AND idx = 3", (EN,))
    st = retranscribe(EN, {'map': {}, 'vectors': {'1': X1}}, 'unmatched')
    r1, r2, r3 = speaker_row(EN, 1), speaker_row(EN, 2), speaker_row(EN, 3)
    check('聲音對不上：說話者 1 回到預設名稱', r1[1] == 'default' and r1[2] is None, str(r1))
    sg = (speaker(st, 1) or {}).get('suggestion', {})
    want_reason = 'Name before re-transcribing: Dee (the voice didn\'t match; please check)'
    check('對不上的名字存成建議（聲紋比對想建議 Fay，補回 Dee），原因不是「依內容猜」也不是聲紋分數',
          sg.get('name') == 'Dee' and sg.get('reason') == want_reason and sg.get('time') == '' and r1[3] == 'Dee',
          json.dumps(sg, ensure_ascii=False) + f' db={r1}')
    check('聲音對得上的照舊：Eve', r2[0] == 'Eve' and r2[1] == 'manual', str(r2))
    check('F2 標記的名字不沿用', r3[1] == 'default', str(r3))
    check('Dee 對不上的舊聲紋刪了', not [x for x in sources(EN, 1) if x[1] == 'Dee'], str(sources(EN, 1)))
    ctl('mavoice', 'apply', EN, 1); settle()
    r1 = speaker_row(EN, 1)
    st = state('retranscribe-applied')
    check('一鍵套用：說話者 1 改回 Dee、建議清掉', r1[0] == 'Dee' and r1[3] is None and not st['guard'], str(r1))
    # 高信心自動帶名（REV-F12c P2-1）：舊名字對不上，新說話者的聲音跟 Other2 一模一樣 → 上游自動帶入 Other2，舊名字照樣當建議問
    K, Y = fresh.get('ko'), fresh.get('yue')
    setvoice(Y, 1, unit(71)); learn((Y, 1), 'Other2', unit(71))
    setvoice(K, 1, unit(70)); learn((K, 1), 'Old2', unit(70))
    st = retranscribe(K, {'map': {}, 'vectors': {'1': unit(71)}}, 'auto')
    rk = speaker_row(K, 1)
    sg = (speaker(st, 1) or {}).get('suggestion', {})
    check('高信心自動帶名：名字是上游自動帶入的 Other2，舊名字 Old2 照樣在建議清單',
          rk[0] == 'Other2' and rk[1] == 'voiceprint' and sg.get('name') == 'Old2' and rk[3] == 'Old2', f'db={rk} suggestion={sg}')
    ctl('mavoice', 'dismiss', K, 1); settle()
    ctl('select', Z); settle(); ctl('select', K); settle()
    st = state('retranscribe-auto-dismissed')
    check('略過之後重開這場，建議不再出現；紀錄刪了',
          not (speaker(st, 1) or {}).get('suggestion') and not q('SELECT 1 FROM ma_retranscribe_suggestion WHERE meeting_id = ?', (K,)),
          json.dumps(speaker(st, 1), ensure_ascii=False)[:300])

    # 存檔回滾（REV-F12c P2-2）：named 寫完 pending 後丟錯，整筆回滾；之後的 afterTranscription 不做事
    before_speakers = [speaker_row(Z, i) for i in (1, 2, 3)]
    before_prints = q('SELECT id, person_id, speaker_idx FROM voiceprints WHERE meeting_id = ? ORDER BY id', (Z,))
    retranscribe(Z, {'map': {'1': 2, '2': 1}, 'failSave': True}, 'rollback')
    check('存檔回滾：說話者、聲紋都沒變，沒有留下待處理的紀錄',
          [speaker_row(Z, i) for i in (1, 2, 3)] == before_speakers
          and q('SELECT id, person_id, speaker_idx FROM voiceprints WHERE meeting_id = ? ORDER BY id', (Z,)) == before_prints
          and not q('SELECT 1 FROM ma_retranscribe_pending WHERE meeting_id = ?', (Z,)), f'{before_speakers} {before_prints}')

    # 學到一半失敗（REV-F12c P2-3）：pending 留著、舊聲紋沒先刪；重試後做完
    retranscribe(Z, {'map': {'1': 2, '2': 1}, 'failLearn': True}, 'learnfail')
    check('學到一半失敗：待處理的紀錄還在', bool(q('SELECT 1 FROM ma_retranscribe_pending WHERE meeting_id = ?', (Z,))))
    ctl('mavoice', 'retranscribe-retry', Z); settle()
    post = {i: speaker_row(Z, i) for i in (1, 2, 3)}
    lib = library()
    ok = not q('SELECT 1 FROM ma_retranscribe_pending WHERE meeting_id = ?', (Z,))
    for idx, name in ((1, 'Ann2'), (2, 'Bob2')):
        mine = [x for x in lib if x['meeting'] == Z and x['idx'] == idx]
        cur = q('SELECT embedding FROM speakers WHERE meeting_id = ? AND idx = ?', (Z, idx))[0][0]
        ok &= post[idx][0] == name and len(mine) == 1 and mine[0]['name'] == name and abs(cos(mine[0]['vec'], list(struct.unpack(f'<{DIM}f', cur))) - 1) < 1e-4
    check('重試後做完：名字跟著聲音換回來、每位一份新聲音的聲紋、待處理的紀錄消耗掉', ok, f'{post} {[(x["name"], x["meeting"], x["idx"]) for x in lib if x["meeting"] == Z]}')

    # 重試前尊重使用者後來的決定（REV2-F12c P2-1）：學到一半失敗 → 使用者改名 → 重試不能把人物改回舊名字
    retranscribe(Z, {'map': {'1': 2, '2': 1}, 'failLearn': True}, 'learnfail-rename')
    pre2 = speaker_row(Z, 2)
    ctl('mavoice', 'rename', Z, 2, 'UserNew'); settle()
    ctl('mavoice', 'retranscribe-retry', Z); settle()
    r2 = speaker_row(Z, 2)
    owners = q('SELECT p.name FROM voiceprints v JOIN people p ON p.id = v.person_id WHERE v.meeting_id = ? AND v.speaker_idx = 2', (Z,))
    check('失敗後使用者改名，重試跳過這一位：名字、人物、聲紋都是 UserNew',
          r2[0] == 'UserNew' and r2[2] == person_id('UserNew') and owners == [('UserNew',)]
          and not q('SELECT 1 FROM ma_retranscribe_pending WHERE meeting_id = ?', (Z,)), f'before={pre2} after={r2} owners={owners}')
    r1 = speaker_row(Z, 1)
    check('同一批沒被改的照樣重新學', r1[2] is not None and q('SELECT 1 FROM voiceprints WHERE meeting_id = ? AND speaker_idx = 1 AND person_id = ?', (Z, r1[2])),
          str(r1))

    check('重新轉錄後：來源表沒有孤兒、foreign_key_check 沒有東西',
          q('SELECT count(*) FROM ma_voiceprint_source WHERE voiceprint_id NOT IN (SELECT id FROM voiceprints)')[0][0] == 0
          and not q('PRAGMA foreign_key_check'))

    edits()


def nameonly_pending(meeting, lib, lib_idx, name_a, name_b, other, va, vb, label):
    """對調說話者、學到一半失敗留下 pending，接著使用者把說話者 2（name_a）同名再存、選「只改名，不記住聲音」"""
    setvoice(meeting, 1, unit(va)); ctl('mavoice', 'rename', meeting, 1, name_a); settle()
    setvoice(meeting, 2, unit(vb)); ctl('mavoice', 'rename', meeting, 2, name_b); settle()
    path = OUT / f'retranscribe-{label}.json'
    path.write_text(json.dumps({'map': {'1': 2, '2': 1}, 'failLearn': True}))
    ctl('mavoice', 'retranscribe', meeting, path); settle(); time.sleep(1)
    check(f'{label}：學到一半失敗，pending 還在', bool(q('SELECT 1 FROM ma_retranscribe_pending WHERE meeting_id = ?', (meeting,))))
    # 另一個人的聲音跟 name_a 一模一樣，同名再存時會跳提醒
    setvoice(lib, lib_idx, unit(va)); ctl('mavoice', 'rename', lib, lib_idx, other); settle()
    ctl('mavoice', 'rename', meeting, 2, name_a); settle()
    st = state(f'{label}-held')
    check(f'{label}：同名再存 {name_a} 跳出提醒', len(st['guard']) == 1 and st['guard'][0]['name'] == name_a, json.dumps(st['guard'], ensure_ascii=False)[:300])
    ctl('mavoice', 'choose', 'nameonly'); settle()
    r = speaker_row(meeting, 2)
    check(f'{label}：只改名後名字是 {name_a}、這場沒有它的聲紋', r[0] == name_a and not q('SELECT 1 FROM voiceprints WHERE meeting_id = ? AND speaker_idx = 2', (meeting,)), str(r))


def segments_of(meeting):
    return q("SELECT start, end, speaker FROM segments WHERE meeting_id = ? AND kind = 'final' ORDER BY start", (meeting,))


def keep_without(meeting, speaker):
    """只留不是這位說話者的句子（給 editmeeting keep=…）"""
    ranges = []
    for start, end, spk in segments_of(meeting):
        if spk == speaker: continue
        if ranges and abs(ranges[-1][1] - start) < 0.01: ranges[-1][1] = end
        else: ranges.append([start, end])
    return ','.join(f'{a:.2f}-{b:.2f}' for a, b in ranges)


def edits():
    """編輯會議（REV2-F12c P2-2）：自動帶名下的舊名字建議跟著裁切、還原、分割；有 pending 時裁切、合併、還原"""
    before = q('SELECT coalesce(max(id), 0) FROM meetings')[0][0]
    ctl('seedfixtures', args.fixtures, 'zh', 'en', 'ja', 'yue', 'ko')
    time.sleep(3)
    fresh = {lang: mid for mid, lang in q("SELECT id, language FROM meetings WHERE deleted_at IS NULL AND id > ? ORDER BY id", (before,))}
    EE, LIB, PZ, OTHER = fresh['en'], fresh['ja'], fresh['zh'], fresh['ko']

    def run_retranscribe(meeting, spec, label):
        path = OUT / f'retranscribe-{label}.json'
        path.write_text(json.dumps(spec))
        ctl('mavoice', 'retranscribe', meeting, path); settle(); time.sleep(1)

    def shown(meeting, idx, label):
        ctl('select', OTHER); settle(); ctl('select', meeting); settle()
        return (speaker(state(label), idx) or {}).get('suggestion', {}).get('name')

    setvoice(LIB, 1, unit(90)); ctl('mavoice', 'rename', LIB, 1, 'Other3'); settle()
    setvoice(EE, 1, unit(91)); ctl('mavoice', 'rename', EE, 1, 'Old3'); settle()
    run_retranscribe(EE, {'map': {}, 'vectors': {'1': unit(90)}}, 'edit-auto')
    r = speaker_row(EE, 1)
    check('編輯前：說話者 1 自動帶入 Other3，舊名字 Old3 是建議', r[0] == 'Other3' and r[1] == 'voiceprint' and shown(EE, 1, 'edit-before') == 'Old3', str(r))

    keep = keep_without(EE, 3)
    ctl('editmeeting', EE, f'keep={keep}'); settle(); time.sleep(1)
    check('裁掉別位說話者：說話者 1 還在，Old3 建議照樣在（說話者自己的聲音雜湊沒變）', shown(EE, 1, 'edit-crop-other') == 'Old3')
    ctl('restoreedit', EE); settle(); time.sleep(1)
    keep = keep_without(EE, 1)
    ctl('editmeeting', EE, f'keep={keep}'); settle(); time.sleep(1)
    gone = not q('SELECT 1 FROM speakers WHERE meeting_id = ? AND idx = 1', (EE,))
    shown(EE, 2, 'edit-crop-self')
    check('裁掉說話者 1：說話者 1 不在了，建議紀錄刪了', gone and not q('SELECT 1 FROM ma_retranscribe_suggestion WHERE meeting_id = ? AND speaker_idx = 1', (EE,)))
    ctl('restoreedit', EE); settle(); time.sleep(1)
    r = speaker_row(EE, 1)
    check('還原編輯：說話者 1 回來，仍是自動帶入的 Other3，Old3 建議也回來（快照放回）',
          r and r[0] == 'Other3' and shown(EE, 1, 'edit-restored') == 'Old3'
          and q('SELECT 1 FROM ma_retranscribe_suggestion WHERE meeting_id = ? AND speaker_idx = 1', (EE,)), str(r))

    segs = [x for x in segments_of(EE) if x[2] == 1]
    cut = segs[-1][0] - 0.01 if segs else None
    end = max(x[1] for x in segments_of(EE))
    if check('分割：說話者 1 在切點之後有說話', cut is not None and cut > 0.5, str(segs[-1:])):
        before_split = q('SELECT coalesce(max(id), 0) FROM meetings')[0][0]
        ctl('editmeeting', EE, f'keep=0-{end:.2f}', f'split={cut:.2f}'); settle(); time.sleep(1.5)
        new = q('SELECT max(id) FROM meetings WHERE id > ?', (before_split,))[0][0]
        rn = speaker_row(new, 1) if new else None
        check('分割：新的那場有說話者 1，Old3 建議跟著到新的那場',
              new and rn and rn[3] == 'Old3' and shown(new, 1, 'edit-split-new') == 'Old3'
              and q('SELECT 1 FROM ma_retranscribe_suggestion WHERE meeting_id = ? AND speaker_idx = 1', (new,)), f'new={new} row={rn}')

    # 有 pending 時：裁切讓 pending 失效、還原放回；合併也讓 pending 失效、還原放回
    A, B = unit(92), unit(93)
    setvoice(PZ, 1, A); ctl('mavoice', 'rename', PZ, 1, 'PenA'); settle()
    setvoice(PZ, 2, B); ctl('mavoice', 'rename', PZ, 2, 'PenB'); settle()
    run_retranscribe(PZ, {'map': {'1': 2, '2': 1}, 'failLearn': True}, 'edit-pending')
    has = lambda: bool(q('SELECT 1 FROM ma_retranscribe_pending WHERE meeting_id = ?', (PZ,)))
    check('有 pending（學到一半失敗）', has())
    whole = max(x[1] for x in segments_of(PZ))
    ctl('editmeeting', PZ, f'keep=0-{whole:.2f}'); settle(); time.sleep(1)
    check('裁切：pending 失效', not has())
    ctl('restoreedit', PZ); settle(); time.sleep(1)
    check('還原：pending 放回', has())
    ctl('editmeeting', PZ, f'keep=0-{whole:.2f}', f'merge={OTHER}'); settle(); time.sleep(1.5)
    check('合併：pending 失效', not has())
    ctl('restoreedit', PZ); settle(); time.sleep(1.5)
    check('合併後還原：pending 放回', has())
    ctl('mavoice', 'retranscribe-retry', PZ); settle()
    check('還原後重試做完：PenA、PenB 跟著聲音、各有新聲音的聲紋',
          not has() and speaker_row(PZ, 2)[0] == 'PenA' and speaker_row(PZ, 1)[0] == 'PenB'
          and q('SELECT count(*) FROM voiceprints WHERE meeting_id = ?', (PZ,))[0][0] == 2,
          f'{speaker_row(PZ, 1)} {speaker_row(PZ, 2)}')

    # 使用者在 pending 期間同名再存（REV3-F12c P2-1）：選「只改名」→ 重試不能學回；選「仍要存」→ 重試不動使用者存的那份
    NV, LIB2 = fresh['yue'], LIB
    nameonly_pending(NV, LIB2, 2, 'NA', 'NB', 'QOther', 94, 95, 'nameonly')
    ctl('mavoice', 'retranscribe-retry', NV); settle()
    check('同名只改名後重試：這一位不學（這場沒有 NA 的聲紋），同批的 NB 照學，pending 消耗',
          not q('SELECT 1 FROM voiceprints WHERE meeting_id = ? AND speaker_idx = 2', (NV,))
          and q("SELECT 1 FROM voiceprints v JOIN people p ON p.id = v.person_id WHERE v.meeting_id = ? AND v.speaker_idx = 1 AND p.name = 'NB'", (NV,))
          and not q('SELECT 1 FROM ma_retranscribe_pending WHERE meeting_id = ?', (NV,)),
          str(q('SELECT speaker_idx, person_id FROM voiceprints WHERE meeting_id = ?', (NV,))))
    # 再對調一次：學到一半失敗 → 使用者同名再存「NB」（沒有提醒，直接記住）→ 重試不換掉使用者存的那份
    path = OUT / 'retranscribe-keep.json'
    path.write_text(json.dumps({'map': {'1': 2, '2': 1}, 'failLearn': True}))
    ctl('mavoice', 'retranscribe', NV, path); settle(); time.sleep(1)
    who = speaker_row(NV, 2)
    ctl('mavoice', 'rename', NV, 2, who[0]); settle()
    user_print = q('SELECT v.id, s.source FROM voiceprints v LEFT JOIN ma_voiceprint_source s ON s.voiceprint_id = v.id WHERE v.meeting_id = ? AND v.speaker_idx = 2', (NV,))
    ctl('mavoice', 'retranscribe-retry', NV); settle()
    after_print = q('SELECT v.id, s.source FROM voiceprints v LEFT JOIN ma_voiceprint_source s ON s.voiceprint_id = v.id WHERE v.meeting_id = ? AND v.speaker_idx = 2', (NV,))
    check(f'同名再存（記住聲音）後重試：使用者存的那份不被換掉（{who[0]}，來源 manual）',
          user_print and user_print == after_print and after_print[0][1] == 'manual' and not q('SELECT 1 FROM ma_retranscribe_pending WHERE meeting_id = ?', (NV,)),
          f'{user_print} → {after_print}')



# ---------- 重啟（check.sh 真的結束、再開同一個 SHIYIN_HOME 的 DEBUG 版） ----------
STATE = OUT / 'restart.json'


def restart_seed():
    """轉錄完、沒打開這場：聲紋比對把舊名字建議換成 Rfay（低信心），記下會議"""
    before = q('SELECT coalesce(max(id), 0) FROM meetings')[0][0]
    ctl('seedfixtures', args.fixtures, 'zh', 'en', 'ja', 'yue', 'ko')
    time.sleep(3)
    fresh = {lang: mid for mid, lang in q("SELECT id, language FROM meetings WHERE deleted_at IS NULL AND id > ? ORDER BY id", (before,))}
    M, L, other = fresh['en'], fresh['ja'], fresh['zh']
    setvoice(L, 1, mix((0.75, 81), 82)); ctl('mavoice', 'rename', L, 1, 'Rfay'); settle()
    setvoice(M, 1, unit(80)); ctl('mavoice', 'rename', M, 1, 'Rold'); settle()
    ctl('select', other); settle()
    path = OUT / 'retranscribe-restart.json'
    path.write_text(json.dumps({'map': {}, 'vectors': {'1': unit(81)}, 'noselect': True}))
    ctl('mavoice', 'retranscribe', M, path); settle(); time.sleep(1)
    row = speaker_row(M, 1)
    check('重啟前：聲紋比對把建議換成 Rfay（還沒打開這場）', row[1] == 'default' and row[3] == 'Rfay', str(row))
    check('重啟前：舊名字建議的紀錄在資料庫', bool(q("SELECT 1 FROM ma_retranscribe_suggestion WHERE meeting_id = ? AND name = 'Rold'", (M,))))
    # 同名只改名後，不在這次 app 裡重試，留給重啟時的 retryAll（REV3-F12c P2-1）
    NV2 = fresh['yue']
    nameonly_pending(NV2, fresh['ko'], 1, 'RA', 'RB', 'ROther', 96, 97, 'restart-nameonly')
    STATE.write_text(json.dumps({'meeting': M, 'other': other, 'nameonly': NV2}))


def restart_check():
    """重啟後打開這場：建議補回 Rold；略過後重開不再出現"""
    st0 = json.loads(STATE.read_text())
    M, other = st0['meeting'], st0['other']
    ctl('select', M); settle()
    st = state('restart-open')
    sg = (speaker(st, 1) or {}).get('suggestion', {})
    check('重啟後打開這場：建議是重新轉錄前的名字 Rold（資料庫也寫回）', sg.get('name') == 'Rold' and speaker_row(M, 1)[3] == 'Rold',
          json.dumps(sg, ensure_ascii=False) + str(speaker_row(M, 1)))
    NV2 = st0['nameonly']
    check('重啟時 retryAll 做完：同名只改名的 RA 沒有學回，同批的 RB 照學，pending 消耗',
          not q('SELECT 1 FROM voiceprints WHERE meeting_id = ? AND speaker_idx = 2', (NV2,))
          and q("SELECT 1 FROM voiceprints v JOIN people p ON p.id = v.person_id WHERE v.meeting_id = ? AND v.speaker_idx = 1 AND p.name = 'RB'", (NV2,))
          and not q('SELECT 1 FROM ma_retranscribe_pending WHERE meeting_id = ?', (NV2,)),
          str(q('SELECT speaker_idx, person_id FROM voiceprints WHERE meeting_id = ?', (NV2,))))
    ctl('mavoice', 'dismiss', M, 1); settle()
    ctl('select', other); settle(); ctl('select', M); settle()
    st = state('restart-dismissed')
    check('略過後重開這場：不再出現', not (speaker(st, 1) or {}).get('suggestion')
          and not q('SELECT 1 FROM ma_retranscribe_suggestion WHERE meeting_id = ?', (M,)))


def restart_final():
    """略過之後再重啟一次：不復活"""
    M = json.loads(STATE.read_text())['meeting']
    ctl('select', M); settle()
    st = state('restart-final')
    check('略過之後再重啟：建議不復活', not (speaker(st, 1) or {}).get('suggestion') and speaker_row(M, 1)[3] is None,
          json.dumps(speaker(st, 1), ensure_ascii=False)[:300])


try:
    {'all': main, 'restart-seed': restart_seed, 'restart-check': restart_check, 'restart-final': restart_final}[args.phase]()
finally:
    (OUT / f'f12-results{"" if args.phase == "all" else "-" + args.phase}.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
failed = [r for r in results if not r['ok']]
print(f'\n{len(results) - len(failed)}/{len(results)} 通過')
sys.exit(1 if failed or not results else 0)
