#!/usr/bin/env python3
"""scripts/fork/check.sh 在 DEBUG 版上跑的項目（fork design §F0.4；PLAN-fork-5.0 §8.1 的 5～10）。

對一個已經開著、用暫存 SHIYIN_HOME 的 DEBUG 版跑（check.sh 負責建置、啟動、確認開的是暫存資料庫、結束）：
  f2-record   #5：record-sim 中 `tagspeaker now 甲`、停止，speaker_tags 有這一筆、時間在送出指令時的 elapsed 附近
  f2-apply    #5：讀 f2-atomic-check.py 輸出的 f2-apply.json：說話者 1 套上「甲」、說話者 2（乙、丙矛盾）不套用
  f2-edit     #6：編輯會議（裁頭尾、刪中間、分割、合併）時標記跟著平移，restoreedit 回到原本；.shiyin 封包帶標記
  f3-hint     #7、#8：靜音中選單列圖示、收音提示不出現、快捷鍵有註冊；recordstall 讓電腦聲音停下，muteHint 出現、
              dismiss 收掉；windowshot 提示列
  f4-items    #10：noteitem delete actionItems 0 之後 copysection 的待辦少一條、其他條和別的段落照舊
  shots       #8、#9、#10：示範會議的紀錄、逐字稿分頁、設定「錄音」頁（windowshot、mawindowshot），只拍不判斷
用法：python3 scripts/fork/check-debug.py <項目> <SHIYIN_HOME> <shiyinctl> --out <資料夾> [--fixtures …] [--f2-out …] [--lang zh]
exit 0 通過、1 不符（原因印在最後一行）。只讀寫 <SHIYIN_HOME>；同時只能開一個 DEBUG 版（shiyinctl 是廣播）。
"""
import argparse
import json
import math
import sqlite3
import struct
import subprocess
import sys
import time
import wave
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('item', choices=['f2-record', 'f2-apply', 'f2-edit', 'f3-hint', 'f4-items', 'shots'])
ap.add_argument('home', type=Path)
ap.add_argument('ctl', type=Path)
ap.add_argument('--out', type=Path, required=True)
ap.add_argument('--fixtures', type=Path, default=ROOT / 'shared/golden/fixtures.json')
ap.add_argument('--f2-out', type=Path, help='f2-atomic-check.py 的 --out（f2-apply 用）')
ap.add_argument('--lang', default='zh', help='shots 的檔名後綴（介面語言由啟動參數決定）')
args = ap.parse_args()
HOME, CTL, OUT = args.home.resolve(), args.ctl, args.out
DB = HOME / 'shiyin.sqlite'
OUT.mkdir(parents=True, exist_ok=True)
if HOME == (Path.home() / 'Library/Application Support/Shiyin').resolve():
    sys.exit('不能對正式的資料夾跑')
problems = []


def ctl(*a):
    subprocess.run([str(CTL), *map(str, a)], check=True, stdout=subprocess.DEVNULL)


def wait(pred, timeout=30, what='條件'):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if pred():
                return True
        except (sqlite3.OperationalError, json.JSONDecodeError, KeyError):
            pass
        time.sleep(0.2)
    raise TimeoutError(f'{timeout} 秒內沒等到：{what}')


def query(sql, a=()):
    with sqlite3.connect(DB) as c:
        return c.execute(sql, a).fetchall()


def state():
    path = OUT / 'state-raw.json'
    path.unlink(missing_ok=True)
    ctl('state', path)
    wait(lambda: path.exists() and path.stat().st_size > 0, 15, 'state')
    time.sleep(0.3)
    return json.loads(path.read_text())


def output(cmd, path, *a, timeout=30):
    """會寫檔的 DEBUG 指令：等檔案出現"""
    path.unlink(missing_ok=True)
    ctl(cmd, *a)
    wait(lambda: path.exists() and path.stat().st_size > 0, timeout, f'{cmd} 的輸出')
    time.sleep(0.3)
    return path


def check(ok, message):
    print(('PASS ' if ok else 'FAIL ') + message, flush=True)
    if not ok:
        problems.append(message)


def tone(path, seconds, rate=16000):
    """一直有聲音的測試音（440 Hz）：record-sim 的兩個聲道是同一個檔"""
    frames = b''.join(struct.pack('<h', int(9800 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(seconds * rate))
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(frames)


def start_recording(seconds):
    if query("SELECT count(*) FROM meetings WHERE source='recording' AND audio_file=''")[0][0]:
        raise SystemExit('這個 SHIYIN_HOME 已經有錄音中的會議')
    sim = OUT / f'tone-{seconds}.wav'
    tone(sim, seconds)
    ctl('record-sim', sim, 1, 1)
    wait(lambda: state()['recorder']['recording'] and state()['recorder']['elapsed'] > 1, 30, '開始錄音')


def stop_recording():
    ctl('record', 'stop')
    wait(lambda: not state()['recorder']['recording'], 30, '停止錄音')


# ---------- #5 ----------
def f2_record():
    start_recording(20)
    t0 = state()['recorder']['elapsed']
    ctl('tagspeaker', 'now', '甲')
    time.sleep(1.5)
    s = state()
    t1, mid = s['recorder']['elapsed'], s['recorder']['meetingId']
    time.sleep(2)
    stop_recording()
    rows = []
    wait(lambda: rows.extend(query('SELECT start, "end", name, kind FROM speaker_tags WHERE meeting_id=?', (mid,))) or rows, 15, '標記寫入')
    (OUT / 'f2-record-tags.json').write_text(json.dumps({'meeting': mid, 'sentAt': [t0, t1], 'rows': rows}, ensure_ascii=False, indent=1))
    check(len(rows) == 1 and rows[0][2] == '甲', f'錄音中 tagspeaker now 甲 存成一筆標記：{rows}')
    if rows:
        # 標記的範圍是 SpeakerTagging.nowRange：(max(0, 時間 - nowBefore), 時間 + nowAfter)；從結束時間反推按下的時間
        import re
        src = (ROOT / 'Sources/Shiyin/Fork/SpeakerTags/SpeakerTagging.swift').read_text()
        after = float(re.search(r'nowAfter[^=]*=\s*([0-9.]+)', src).group(1))
        before = float(re.search(r'nowBefore[^=]*=\s*([0-9.]+)', src).group(1))
        at = rows[0][1] - after
        check(t0 - 1 <= at <= t1 + 1 and abs(rows[0][0] - max(0, at - before)) < 0.01,
              f'標記 {rows[0][0]:.2f}～{rows[0][1]:.2f} 對應按下的時間 {at:.2f}，在送出指令時的 elapsed {t0:.2f}～{t1:.2f} 附近')
    # 等這場的錄音檔寫好（轉錄接著在背景跑），之後的錄音才不會跟它搶
    wait(lambda: query('SELECT audio_file FROM meetings WHERE id=?', (mid,))[0][0] != '', 120, '錄音檔')


def f2_apply():
    report = json.loads((args.f2_out / 'f2-apply.json').read_text())
    names = {s['idx']: s['name'] for s in report['speakers']}
    unapplied = sorted(t['name'] for t in report['tags'] if t['unapplied'])
    check(names.get(1) == '甲', f'套用標記：說話者 1 是「甲」（{names}）')
    check(names.get(2) not in ('乙', '丙'), f'說話者 2 有乙又有丙，不套用（{names.get(2)}）')
    check('丙' in unapplied, f'沒套用的標記有「丙」（{unapplied}）')


# ---------- #6（REVIEW-1-merge-5.0 的 debug_validation 的數字，IMPL-2-isolate 搬來） ----------
def tag_rows(mid):
    return sorted(query('SELECT start, "end", name, kind FROM speaker_tags WHERE meeting_id=?', (mid,)))


def tag_check(label, mid, expected):
    expected = sorted(tuple(x) for x in expected)
    try:
        wait(lambda: tag_rows(mid) == expected, 30, label)
    except TimeoutError:
        pass
    actual = tag_rows(mid)
    check(actual == expected, f'{label}：{actual}' + ('' if actual == expected else f' 應該是 {expected}'))
    return actual == expected


def restore(mid, expected, label):
    ctl('restoreedit', mid)
    tag_check(label, mid, expected)
    try:
        wait(lambda: query('SELECT COUNT(*) FROM meeting_edits WHERE meeting_id=?', (mid,))[0][0] == 0, 30, '編輯紀錄清掉')
    except TimeoutError:
        pass
    left = query('SELECT COUNT(*) FROM ma_meeting_edit_tags WHERE meeting_id=?', (mid,))[0][0]
    check(left == 0, f'{label}：ma_meeting_edit_tags 跟著清掉（剩 {left}）')


def seed_two():
    oldmax = query('SELECT coalesce(max(id),0) FROM meetings')[0][0]
    ctl('seedfixtures', args.fixtures, 'zh', 'en')
    wait(lambda: len(query('SELECT id FROM meetings WHERE id>?', (oldmax,))) == 2, 30, 'seedfixtures')
    ids = [x[0] for x in query('SELECT id FROM meetings WHERE id>? ORDER BY id', (oldmax,))]
    with sqlite3.connect(DB) as db:
        for pos, ident in enumerate(ids):
            audio = HOME / 'audio' / f'{ident}.wav'
            audio.parent.mkdir(exist_ok=True)
            with wave.open(str(audio), 'wb') as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b'\x00\x00' * (20 * 16000))
            db.execute('UPDATE meetings SET audio_file=?, duration_seconds=20, created_at=? WHERE id=?',
                       (audio.name, f'2026-01-0{pos + 1}T00:00:00Z', ident))
            db.execute('DELETE FROM segments WHERE meeting_id=?', (ident,))
            for seq in range(10):
                db.execute('INSERT INTO segments(meeting_id,seq,start,end,text,speaker,kind) VALUES(?,?,?,?,?,?,?)',
                           (ident, seq, seq * 2, seq * 2 + 2, f'review segment {seq}', 1, 'final'))
    ctl('reload')
    time.sleep(1)
    return ids


def f2_edit():
    mid, other = seed_two()
    original = [(1, 3, 'A', 'line'), (9, 11, 'Cross', 'line'), (10, 12, 'Right', 'line'), (8, 10, 'Left', 'line'), (17, 19, 'Tail', 'line')]
    for s, e, n, _ in original:
        ctl('tagspeaker', 'add', mid, s, e, n)
    ctl('tagspeaker', 'add', other, 2, 5, 'Other')
    tag_check('原本的標記', mid, original)
    ctl('editmeeting', mid, 'keep=0-20', 'split=10')
    tag_check('分割：左半', mid, [(1, 3, 'A', 'line'), (8, 10, 'Left', 'line'), (9, 10, 'Cross', 'line')])
    split_id = query('SELECT max(id) FROM meetings')[0][0]
    tag_check('分割：右半（新會議，時間減 10）', split_id, [(0, 1, 'Cross', 'line'), (0, 2, 'Right', 'line'), (7, 9, 'Tail', 'line')])
    restore(mid, original, '還原分割')
    ctl('editmeeting', mid, 'keep=0-8,12-20')
    tag_check('刪中間 8～12 秒', mid, [(1, 3, 'A', 'line'), (13, 15, 'Tail', 'line')])
    restore(mid, original, '還原刪中間')
    ctl('editmeeting', mid, 'keep=2-18')
    tag_check('裁掉頭尾各 2 秒', mid, [(0, 1, 'A', 'line'), (7, 9, 'Cross', 'line'), (8, 10, 'Right', 'line'), (6, 8, 'Left', 'line'), (15, 16, 'Tail', 'line')])
    restore(mid, original, '還原裁切')
    ctl('editmeeting', mid, 'keep=0-20', f'merge={other}')
    tag_check('合併：另一場的標記加上 20 秒', mid, original + [(22, 25, 'Other', 'line')])
    tag_check('合併：來源會議的標記保留', other, [(2, 5, 'Other', 'line')])
    restore(mid, original, '還原合併')
    package = OUT / 'tags.shiyin'
    package.unlink(missing_ok=True)
    ctl('export', 'package', 'shiyin', package, 1, 1, mid)
    wait(lambda: package.exists(), 60, '匯出封包')
    time.sleep(1)
    with zipfile.ZipFile(package) as z:
        tagpath = next((n for n in z.namelist() if n.endswith('ma-speaker-tags.json')), None)
        check(tagpath is not None, '.shiyin 封包裡有 ma-speaker-tags.json')
        if tagpath is None:
            return
        data = json.loads(z.read(tagpath))
        packed = sorted((x['start'], x['end'], x['name'], x['kind']) for x in data)
        check(packed == sorted(original), f'封包裡的標記跟會議相同：{packed}')
        content = {n: z.read(n) for n in z.namelist() if not n.endswith('/')}
    before = query('SELECT max(id) FROM meetings')[0][0]
    ctl('import', package)
    wait(lambda: query('SELECT max(id) FROM meetings')[0][0] > before, 60, '匯入封包')
    tag_check('匯入封包：標記一樣', query('SELECT max(id) FROM meetings')[0][0], original)
    legacy = OUT / 'legacy-no-tags.shiyin'
    legacy.unlink(missing_ok=True)
    with zipfile.ZipFile(legacy, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, raw in content.items():
            if name != tagpath:
                z.writestr(name, raw)
    before = query('SELECT max(id) FROM meetings')[0][0]
    ctl('import', legacy)
    wait(lambda: query('SELECT max(id) FROM meetings')[0][0] > before, 60, '匯入舊封包')
    tag_check('匯入沒有標記的舊封包：沒有標記', query('SELECT max(id) FROM meetings')[0][0], [])
    check(query('PRAGMA foreign_key_check') == [] and query('PRAGMA integrity_check') == [('ok',)], '資料庫 foreign_key_check、integrity_check')


# ---------- #7、#8 ----------
def f3_hint():
    start_recording(70)
    ctl('micmute', 'on')
    time.sleep(3)
    s = state()
    r = s['recorder']
    snap = {'muted': s}
    check(r.get('micMuted') is True, f'micmute on 之後 micMuted（{r.get("micMuted")}）')
    check(s.get('menuBarSymbol') == 'mic.slash.circle.fill', f'靜音中選單列圖示是 mic.slash.circle.fill（{s.get("menuBarSymbol")}）')
    check(s['hotkey'].get('muteRegistered') is True, f'both 的錄音中 ⌃⌥⌘M 有註冊（{s["hotkey"].get("muteRegistered")}）')
    check(not r.get('levelCheck', {}).get('hint'), f'靜音中沒有收音提示（levelCheck.hint={r.get("levelCheck", {}).get("hint")!r}）')
    check(not r.get('muteHint'), '電腦聲音照常時不提示「現場好像有人在說話」')
    ctl('recordstall', 32, 1)   # 電腦聲音那一聲道停 32 秒（補 0）：麥克風像說話、電腦聲音沒聲音
    try:
        wait(lambda: state()['recorder'].get('muteHint') is True, 40, 'muteHint')
        shown = True
    except TimeoutError:
        shown = False
    check(shown, '靜音中電腦聲音停下、麥克風有聲音：20 秒左右出現 muteHint')
    s = state()
    snap['hint'] = s
    output('windowshot', OUT / 'f3-hint-main.png', OUT / 'f3-hint-main.png', 'main')
    check(not s['recorder'].get('levelCheck', {}).get('hint') or s['recorder'].get('levelCheck', {}).get('hint') == '',
          f'提示出現時也沒有麥克風的收音提示（levelCheck.hint={s["recorder"].get("levelCheck", {}).get("hint")!r}）')
    ctl('micmute', 'dismiss')
    time.sleep(1.5)
    check(not state()['recorder'].get('muteHint'), 'micmute dismiss 之後提示收掉')
    ctl('recordstall', 'off')
    ctl('micmute', 'off')
    time.sleep(2)
    s = state()
    check(s['recorder'].get('micMuted') is False, '打開麥克風')
    stop_recording()
    time.sleep(1)
    s = state()
    snap['stopped'] = s
    check(s['hotkey'].get('muteRegistered') is False, f'停止後 ⌃⌥⌘M 取消註冊（{s["hotkey"].get("muteRegistered")}）')
    (OUT / 'f3-hint-states.json').write_text(json.dumps(snap, ensure_ascii=False, indent=1))


# ---------- #10 ----------
def demo_meeting(lang='zh'):
    fixtures = {m['key']: m for m in json.loads(args.fixtures.read_text())['meetings']}
    name = fixtures[lang]['meeting']['sourceFilename']
    rows = query('SELECT id FROM meetings WHERE source_filename=? AND language=? ORDER BY id DESC LIMIT 1', (name, lang))
    if not rows:
        ctl('seedfixtures', args.fixtures, lang)
        wait(lambda: query('SELECT id FROM meetings WHERE source_filename=? AND language=?', (name, lang)), 30, 'seedfixtures')
        rows = query('SELECT id FROM meetings WHERE source_filename=? AND language=? ORDER BY id DESC LIMIT 1', (name, lang))
    return rows[0][0]


def f4_items():
    """刪待辦的第一條（示範會議的待辦有 3 條；決議只有 1 條，刪了整段變空）"""
    mid = demo_meeting('zh')
    ctl('select', mid)
    ctl('tab', 'summary')
    time.sleep(2)
    target, rest = 'actionItems', ('summary', 'decisions')
    before = output('copysection', OUT / f'f4-{target}-before.txt', mid, target, OUT / f'f4-{target}-before.txt').read_text()
    others = {sc: output('copysection', OUT / f'f4-{sc}-before.txt', mid, sc, OUT / f'f4-{sc}-before.txt').read_text() for sc in rest}
    lines = [x for x in before.splitlines() if x.strip()]
    check(len(lines) >= 3, f'示範會議的待辦至少 2 條（{len(lines) - 1}）')
    ctl('noteitem', 'delete', target, 0)
    time.sleep(2)
    after = output('copysection', OUT / f'f4-{target}-after.txt', mid, target, OUT / f'f4-{target}-after.txt').read_text()
    left = [x for x in after.splitlines() if x.strip()]
    check(len(left) == len(lines) - 1 and left[0] == lines[0] and left[1:] == lines[2:],
          f'noteitem delete {target} 0：從 {len(lines) - 1} 條變 {len(left) - 1} 條，標題和其他條照舊')
    for sc, text in others.items():
        now = output('copysection', OUT / f'f4-{sc}-after.txt', mid, sc, OUT / f'f4-{sc}-after.txt').read_text()
        check(now == text, f'刪待辦不影響 {sc}')
    output('windowshot', OUT / 'f4-after-delete.png', OUT / 'f4-after-delete.png', 'main')


# ---------- 截圖 ----------
def shots():
    mid = demo_meeting(args.lang if args.lang in ('zh', 'en') else 'zh')
    ctl('select', mid)
    ctl('tab', 'summary')
    time.sleep(3)
    output('windowshot', OUT / f'summary-{args.lang}.png', OUT / f'summary-{args.lang}.png', 'main')
    ctl('tab', 'transcript')
    time.sleep(2)
    output('windowshot', OUT / f'transcript-{args.lang}.png', OUT / f'transcript-{args.lang}.png', 'main')
    ctl('tab', 'summary')
    ctl('preview', 'settings', 'recording', 'height=980')
    time.sleep(5)
    try:
        output('mawindowshot', OUT / f'settings-recording-{args.lang}.png', OUT / f'settings-recording-{args.lang}.png', 'settings-preview')
    finally:
        ctl('closewindow', 'settings-preview')
    print('PASS 截圖：' + ', '.join(sorted(p.name for p in OUT.glob(f'*-{args.lang}.png'))))


try:
    {'f2-record': f2_record, 'f2-apply': f2_apply, 'f2-edit': f2_edit, 'f3-hint': f3_hint,
     'f4-items': f4_items, 'shots': shots}[args.item]()
except (TimeoutError, subprocess.CalledProcessError, StopIteration, AssertionError) as e:
    problems.append(f'{type(e).__name__}: {e}')
if problems:
    print(f'FAIL {args.item}：' + '；'.join(problems))
    sys.exit(1)
print(f'PASS {args.item}')
