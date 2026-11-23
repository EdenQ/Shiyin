#!/usr/bin/env python3
"""F2.12「只改這句」的交易檢查（fork design DF8、§F-UP；REVIEW-2 P2-1）。

對一個已經開著、用暫存 SHIYIN_HOME 的 DEBUG 版跑：
  1. 放兩場示範會議（seedfixtures），每場 10 句、說話者 1、2 交替，加標記「甲」「乙」「丙」後 applytags
     （說話者 2 有乙又有丙，丙不套用，留給「只改這句」）
  2. 故障注入：在 speakers 加一個 SQLite trigger，只擋「把名字改成丙」，再按「只改這句」（`tagspeaker only`）。
     新增說話者、改句子、存復原快照要跟著整筆回復：說話者、句子、speaker_undo 跟按之前完全相同才算通過。
     trigger 跑完一定拿掉
  3. 正常路徑：拿掉 trigger 後再按一次「只改這句」、再按復原（undospeaker），輸出存到 --out，
     讓不同版本（例如 5.0.1 和現在）的輸出可以逐位元組比
用法：python3 scripts/fork/f2-atomic-check.py <SHIYIN_HOME> <shiyinctl> --out <資料夾> [--fixtures <fixtures.json>]
只寫 <SHIYIN_HOME> 的資料庫；shiyinctl 會廣播給所有 DEBUG 版，同時只開一個（有別的 DEBUG 版在跑時拒絕）。
exit 0：故障時整筆回復、正常路徑成功；exit 1：留下改了一半的資料或步驟失敗。
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('home', type=Path)
ap.add_argument('ctl', type=Path)
ap.add_argument('--out', type=Path, required=True)
ap.add_argument('--fixtures', type=Path, default=ROOT / 'shared/golden/fixtures.json')
args = ap.parse_args()
HOME, CTL, OUT = args.home.resolve(), args.ctl, args.out
DB = HOME / 'shiyin.sqlite'
OUT.mkdir(parents=True, exist_ok=True)
REAL = Path.home() / 'Library/Application Support/Shiyin'
if HOME == REAL.resolve():
    sys.exit('不能對正式的資料夾跑')
if not DB.exists():
    sys.exit(f'{DB} 不存在：先用這個 SHIYIN_HOME 開 DEBUG 版')


def debug_apps():
    """正在跑、開著這個 home 以外的 DEBUG 版：shiyinctl 是廣播，不能同時有兩個"""
    apps = []
    for line in subprocess.check_output(['ps', '-axo', 'pid=,comm='], text=True).splitlines():
        if not line.endswith('/Contents/MacOS/Shiyin'):
            continue
        path = line.strip().split(None, 1)[1]
        try:
            if b'com.weiwei.shiyin.debug' in Path(path).read_bytes():   # 只有 DEBUG 版有控制通道
                apps.append(path)
        except OSError:
            continue
    return apps


def ctl(*a):
    subprocess.run([str(CTL), *map(str, a)], check=True, stdout=subprocess.DEVNULL)


def wait(pred, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(0.2)
    raise TimeoutError('timeout')


def query(sql, a=()):
    with sqlite3.connect(DB) as c:
        return c.execute(sql, a).fetchall()


def report(label, mid):
    out = OUT / f'{label}.json'
    out.unlink(missing_ok=True)
    ctl('speakertags', mid, out)
    wait(lambda: out.exists() and out.stat().st_size > 0)
    time.sleep(0.2)
    return json.loads(out.read_text())


def snapshot(mid):
    return {'speakers': query('SELECT idx, name, name_source, person_id FROM speakers WHERE meeting_id=? ORDER BY idx', (mid,)),
            'segments': query('SELECT seq, speaker, speaker_manual FROM segments WHERE meeting_id=? ORDER BY seq', (mid,)),
            'undo': query('SELECT meeting_id, label, snapshot FROM speaker_undo WHERE meeting_id=?', (mid,)),
            'voiceprints': query('SELECT count(*) FROM voiceprints WHERE meeting_id=?', (mid,))}


def seed():
    oldmax = query('SELECT coalesce(max(id),0) FROM meetings')[0][0]
    ctl('seedfixtures', args.fixtures, 'zh', 'en')
    wait(lambda: len(query('SELECT id FROM meetings WHERE id>?', (oldmax,))) == 2)
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
            db.execute('DELETE FROM speakers WHERE meeting_id=?', (ident,))
            for seq in range(10):
                db.execute('INSERT INTO segments(meeting_id,seq,start,end,text,speaker,kind) VALUES(?,?,?,?,?,?,?)',
                           (ident, seq, seq * 2, seq * 2 + 2, f'seg {seq}', 1 + seq % 2, 'final'))
            for idx in (1, 2):
                db.execute('INSERT INTO speakers(meeting_id, idx, name, name_source, speech_seconds) VALUES(?,?,?,?,?)',
                           (ident, idx, f'說話者 {idx}', 'default', 10))  # l10n-skip
    ctl('reload')
    time.sleep(1)
    for ident in ids:
        ctl('tagspeaker', 'add', ident, 0.2, 1.8, '甲'); ctl('tagspeaker', 'add', ident, 4.1, 5.9, '甲')
        ctl('tagspeaker', 'add', ident, 2.2, 3.8, '乙')
        ctl('tagspeaker', 'add', ident, 6.2, 7.8, '丙')   # 說話者 2 有乙又有丙：矛盾，不套用
    time.sleep(1)
    return ids


def unapplied(mid, label, name):
    tags = report(label, mid)['tags']
    return next(t for t in tags if t['name'] == name and t['unapplied'])


def main():
    others = debug_apps()
    if len(others) != 1:
        sys.exit(f'要剛好一個 DEBUG 版在跑（shiyinctl 是廣播），現在：{others}')
    mid, other = seed()
    ctl('select', mid); time.sleep(1)
    ctl('applytags', mid); time.sleep(2)
    report('f2-apply', mid)
    result = {'meeting': mid}

    # 2. 故障注入：第二步（命名）失敗
    target = unapplied(mid, 'f2-fault-before', '丙')
    before = snapshot(mid)
    with sqlite3.connect(DB) as db:
        db.execute(f"CREATE TRIGGER ma_f2_atomic_fail BEFORE UPDATE OF name ON speakers WHEN NEW.meeting_id={int(mid)} "
                   "AND NEW.name='丙' BEGIN SELECT RAISE(ABORT, 'f2-atomic-check injected rename failure'); END")
    captured = OUT / 'f2-fault-error.json'
    captured.unlink(missing_ok=True)
    try:
        # 第 3 個參數：DEBUG＋quiet 時錯誤寫進這個檔、errorMessage 還原，不在使用者畫面上跳出「出了一點問題」（fork design §F2.5）
        ctl('tagspeaker', 'only', mid, target['id'], captured)
        time.sleep(2)
        after = snapshot(mid)
    finally:
        with sqlite3.connect(DB) as db:
            db.execute('DROP TRIGGER IF EXISTS ma_f2_atomic_fail')
    assert not query("SELECT name FROM sqlite_master WHERE type='trigger' AND name='ma_f2_atomic_fail'")
    result['fault'] = {'unchanged': before == after,
                       'before': {k: v for k, v in before.items() if k != 'undo'} | {'undo': [r[:2] for r in before['undo']]},
                       'after': {k: v for k, v in after.items() if k != 'undo'} | {'undo': [r[:2] for r in after['undo']]}}
    print('故障時整筆回復：', 'PASS' if before == after else 'FAIL（留下改了一半的資料）', flush=True)
    def captured_done():
        try:
            return 'errorMessageAfter' in json.loads(captured.read_text())
        except (OSError, ValueError):
            return False
    wait(captured_done)
    err = json.loads(captured.read_text())
    ctl('state', OUT / 'f2-fault-state.json')
    wait(lambda: (OUT / 'f2-fault-state.json').exists())
    time.sleep(0.5)
    state_error = json.loads((OUT / 'f2-fault-state.json').read_text()).get('errorMessage', None)
    (OUT / 'f2-fault-state.json').unlink()
    message = err.get('error') or ''
    no_dialog = (err.get('restored') is True and err.get('errorMessageAfter') is None
                 and err.get('sheetVisible') is False and state_error == '')
    expected_error = 'SQLite error 19' in message and 'f2-atomic-check injected rename failure' in message
    result['faultError'] = {'expectedSQLite19': expected_error, 'noDialog': no_dialog, 'stateErrorMessage': state_error,
                            'captured': {k: v for k, v in err.items() if k != 'error'} | {'errorPrefix': message[:80]}}
    print('故障的錯誤是預期的 SQLite 19：', 'PASS' if expected_error else f'FAIL（{message[:80]}）', flush=True)
    print('沒有跳出錯誤對話框（errorMessage 還原、沒有 sheet、state 的 errorMessage 空的）：',
          'PASS' if no_dialog else f'FAIL（{err} state={state_error!r}）', flush=True)

    # 3. 正常路徑、復原
    target = unapplied(mid, 'f2-before-only', '丙')
    ctl('tagspeaker', 'only', mid, target['id'])
    wait(lambda: any(r[1] == '丙' for r in query('SELECT idx, name FROM speakers WHERE meeting_id=?', (mid,))))
    time.sleep(1)
    report('f2-only', mid)
    db_rows = {'speakers': query('SELECT idx, name, name_source, person_id IS NOT NULL FROM speakers WHERE meeting_id=? ORDER BY idx', (mid,)),
               'segments': query('SELECT seq, speaker, speaker_manual FROM segments WHERE meeting_id=? ORDER BY seq', (mid,)),
               'undo': query('SELECT label FROM speaker_undo WHERE meeting_id=?', (mid,))}
    (OUT / 'f2-only-db.json').write_text(json.dumps(db_rows, ensure_ascii=False, indent=1))
    normal_ok = (any(r[1] == '丙' and r[2] == 'manual' for r in db_rows['speakers'])
                 and len(db_rows['undo']) == 1)
    ctl('undospeaker', mid)
    wait(lambda: not query('SELECT 1 FROM speakers WHERE meeting_id=? AND name=?', (mid, '丙')))
    time.sleep(1)
    undo_rows = {'speakers': query('SELECT idx, name, name_source FROM speakers WHERE meeting_id=? ORDER BY idx', (mid,)),
                 'segments': query('SELECT seq, speaker, speaker_manual FROM segments WHERE meeting_id=? ORDER BY seq', (mid,))}
    (OUT / 'f2-after-undo.json').write_text(json.dumps(undo_rows, ensure_ascii=False, indent=1))
    undo_ok = undo_rows['speakers'] == [r[:3] for r in before['speakers']] and undo_rows['segments'] == before['segments']
    result['normal'] = normal_ok
    result['undoRestoresBefore'] = undo_ok
    assert query('PRAGMA integrity_check') == [('ok',)]
    (OUT / 'f2-fault.json').write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print('正常路徑：', 'PASS' if normal_ok else 'FAIL', '；復原回到按之前：', 'PASS' if undo_ok else 'FAIL', flush=True)
    sys.exit(0 if result['fault']['unchanged'] and expected_error and no_dialog and normal_ok and undo_ok else 1)


if __name__ == '__main__':
    main()
