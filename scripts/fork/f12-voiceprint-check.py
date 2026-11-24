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
  8. windowshot：防呆視窗開著的會議頁、人物頁（看一眼）
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


try:
    main()
finally:
    (OUT / 'f12-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
failed = [r for r in results if not r['ok']]
print(f'\n{len(results) - len(failed)}/{len(results)} 通過')
sys.exit(1 if failed or not results else 0)
