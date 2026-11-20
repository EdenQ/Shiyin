#!/usr/bin/env python3
"""F10 定期備份的自動化驗證（fork design §F10.8；REVIEW-F10 P2-1、P2-2、P3-1 的反例、重疊、錄完後到期的檢查）。

對一個已經開著、用暫存 SHIYIN_HOME 的 DEBUG 版跑（check.sh #14）：
  1. mabackup schedule off（不讓啟動後 2 分鐘的檢查插進來）、清掉 <home>/backups/daily
  2. 清理的反例：7 份舊的一般檔備份，加上名稱符合的資料夾（裡面有檔）、名稱符合的符號連結（一份 1999 年、一份 2099 年）、
     時間不合法的檔、ma-daily-notes.txt、ma-daily-my.partial-notes.txt、名稱符合的 .partial 資料夾、migration 前的備份、
     合法的舊暫存檔（.partial 和 -wal、-shm、-journal）。mabackup now 一次：一般檔備份剩 7 份（最舊的刪掉）、
     舊暫存檔清掉、其他全部原樣、lastSuccess 是剛做的那份；新的備份 integrity_check ok、會議數相同。再 mabackup prune 一次，
     非備份的檔照樣在
  3. 重疊：age 成到期、simulate slow 6 後 now；第一份還在寫時 check 和 now 都回 running；第一份 done，只多一份、沒有暫存檔
  4. 錄完後到期的檢查：age 成到期、record-sim 中 check 回 deferredRecording，record stop 後 check 回 done、多一份
  4b. 寫入目的地（REVIEW-F10b P2-3）：這次時間名稱的 .partial 是連結（到含 sentinel 的 SQLite、斷掉的）、資料夾，
     -wal／-shm／-journal 是連結，正式檔名是連結：每種 now 都回 failed、連結和目標不變、正常備份照留
  5. 最後一般檔備份還是 7 份，反例的東西都還在；schedule on、simulate off
用法：python3 scripts/fork/f10-backup-check.py <SHIYIN_HOME> <shiyinctl> --out <資料夾>
只讀寫 <SHIYIN_HOME>/backups 和 --out；同時只能開一個 DEBUG 版（shiyinctl 是廣播）。exit 0 通過、1 不符。
"""
import argparse
import hashlib
import json
import math
import os
import sqlite3
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('home', type=Path)
ap.add_argument('ctl', type=Path)
ap.add_argument('--out', type=Path, required=True)
args = ap.parse_args()
HOME, CTL, OUT = args.home.resolve(), args.ctl, args.out.resolve()
if HOME == (Path.home() / 'Library/Application Support/Shiyin').resolve():
    sys.exit('不能對正式的資料夾跑')
if not (HOME / 'shiyin.sqlite').exists():
    sys.exit(f'{HOME} 沒有 shiyin.sqlite（DEBUG 版要先用這個 SHIYIN_HOME 開著）')
OUT.mkdir(parents=True, exist_ok=True)
BACKUPS = HOME / 'backups'
DAILY = BACKUPS / 'daily'
results = []


def check(name, ok, detail=''):
    results.append({'check': name, 'ok': bool(ok), 'detail': detail})
    print(('PASS ' if ok else 'FAIL ') + name + (f'：{detail}' if detail else ''), flush=True)


def ctl(*a):
    subprocess.run([str(CTL), *map(str, a)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_json(path, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if path.exists() and path.stat().st_size > 0:
            try:
                return json.loads(path.read_text())
            except json.JSONDecodeError:
                pass
        time.sleep(0.2)
    return None


def bk(sub, name, wait=True, timeout=60):
    path = OUT / f'{name}.json'
    path.unlink(missing_ok=True)
    ctl('mabackup', sub, path)
    return wait_json(path, timeout) if wait else path


def status(name='status'):
    return bk('status', name) or {}


def regular_backups():
    """這一層的一般檔、名稱像備份（腳本自己的判斷，只用來核對 app）"""
    return sorted(p.name for p in DAILY.iterdir()
                  if p.name.startswith('ma-daily-') and p.name.endswith('.sqlite') and p.is_file() and not p.is_symlink()
                  and len(p.name) == len('ma-daily-20000101-000000.sqlite') and p.name[9:17].isdigit()
                  and p.name[18:24].isdigit() and p.name[17] == '-' and p.name[13:15] <= '12')


def leftover_partials():
    return sorted(p.name for p in DAILY.iterdir() if p.name.startswith('ma-daily-') and '.partial' in p.name
                  and p.is_file() and not p.is_symlink() and p.name != 'ma-daily-my.partial-notes.txt')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def meetings(db):
    with sqlite3.connect(f'file:{db}?mode=ro', uri=True) as c:
        return c.execute('select count(*) from meetings').fetchone()[0]


def integrity(db):
    with sqlite3.connect(f'file:{db}?mode=ro', uri=True) as c:
        return [r[0] for r in c.execute('pragma integrity_check')]


def wait_recording(want, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        s = status('rec-status')
        # menuEnabled = 沒在備份而且沒在錄音；這時沒在備份，所以 false 就是錄音中
        if s and (s.get('menuEnabled') is False) == want and not s.get('running'):
            return True
        time.sleep(0.5)
    return False


def tone(path, seconds=30):
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(16000)
        frame = b''.join(struct.pack('<hh', v, v) for v in
                         (int(9800 * math.sin(2 * math.pi * 440 * i / 16000)) for i in range(16000)))
        w.writeframes(frame * seconds)


# ---------- 1. 準備 ----------
ctl('mabackup', 'schedule', 'off')
ctl('mabackup', 'simulate', 'off')
time.sleep(0.5)
if DAILY.exists():
    subprocess.run(['rm', '-rf', str(DAILY)], check=True)   # 只在暫存的 SHIYIN_HOME
DAILY.mkdir(parents=True)
TARGET = OUT / 'symlink-target.txt'
TARGET.write_text('symlink target (synthetic)\n')
migration = BACKUPS / 'shiyin-19990101T000000Z-before-f10check.sqlite'
migration.write_bytes(b'synthetic migration backup\n')
old = [f'ma-daily-20000101-00000{i}.sqlite' for i in range(7)]
for name in old:
    (DAILY / name).write_bytes(b'synthetic old backup\n')
folder = DAILY / 'ma-daily-19990101-000000.sqlite'          # 名稱符合的資料夾（P2-1）
folder.mkdir()
(folder / 'important.txt').write_text('user data sentinel (synthetic)\n')
os.symlink(TARGET, DAILY / 'ma-daily-19990101-000001.sqlite')   # 名稱符合的連結（舊）
os.symlink(TARGET, DAILY / 'ma-daily-20991231-235959.sqlite')   # 名稱符合的連結（未來：不能當成上一次成功）
(DAILY / 'ma-daily-20261399-000000.sqlite').write_bytes(b'invalid date\n')   # 時間不合法
(DAILY / 'ma-daily-notes.txt').write_text('notes\n')
(DAILY / 'ma-daily-my.partial-notes.txt').write_text('not a partial\n')    # P3-1
pfolder = DAILY / 'ma-daily-19990101-000003.partial'                      # 名稱符合的 .partial 資料夾
pfolder.mkdir()
(pfolder / 'keep.txt').write_text('keep\n')
stale = [f'ma-daily-19990101-000002.partial{s}' for s in ('', '-wal', '-shm', '-journal')]   # P2-2
for name in stale:
    (DAILY / name).write_bytes(b'abandoned partial\n')
keep = {
    'folder/important.txt': folder / 'important.txt',
    'pfolder/keep.txt': pfolder / 'keep.txt',
    'ma-daily-20261399-000000.sqlite': DAILY / 'ma-daily-20261399-000000.sqlite',
    'ma-daily-notes.txt': DAILY / 'ma-daily-notes.txt',
    'ma-daily-my.partial-notes.txt': DAILY / 'ma-daily-my.partial-notes.txt',
    'migration': migration,
    'symlink-target': TARGET,
}
keep_sha = {k: sha(p) for k, p in keep.items()}
links = [DAILY / 'ma-daily-19990101-000001.sqlite', DAILY / 'ma-daily-20991231-235959.sqlite']


def others_intact(label):
    bad = [k for k, p in keep.items() if not p.is_file() or sha(p) != keep_sha[k]]
    bad += [p.name for p in links if not p.is_symlink() or os.readlink(p) != str(TARGET)]
    bad += [] if folder.is_dir() and pfolder.is_dir() else ['資料夾']
    check(f'{label}：非備份的檔、資料夾、連結和它指到的檔、migration 前的備份都原樣', not bad, '、'.join(bad))


# ---------- 2. 清理的反例 ----------
if meetings(HOME / 'shiyin.sqlite') == 0:   # 沒有會議時先放示範會議，「會議數相同」才有意義
    ctl('seedfixtures', Path(__file__).resolve().parents[2] / 'shared/golden/fixtures.json')
    time.sleep(3)
live_meetings = meetings(HOME / 'shiyin.sqlite')
check('準備：測試資料庫有會議', live_meetings > 0, str(live_meetings))
before = set(regular_backups())
r = bk('now', 'cleanup-now', timeout=120)
after = regular_backups()
new = sorted(set(after) - before)
check('清理：now 回 done', r and r.get('outcome') == 'done', json.dumps(r and r.get('outcome')))
check('清理：多一份新的一般檔備份', len(new) == 1, str(new))
check('清理：一般檔備份剩 7 份、只刪最舊的那份（P2-1）', after == sorted(old[1:] + new), str(after))
check('清理：名稱符合的資料夾和裡面的檔還在（P2-1）', (folder / 'important.txt').is_file())
check('清理：舊暫存檔（.partial、-wal、-shm、-journal）在成功備份後清掉（P2-2）',
      not any((DAILY / n).exists() for n in stale), str([n for n in stale if (DAILY / n).exists()]))
check('清理：app 回報的備份只有一般檔（不含資料夾、連結、時間不合法）', r and r.get('backups') == after, str(r and r.get('backups')))
check('清理：lastSuccess 是剛做的那份，不是 2099 年的連結', r and (r.get('lastSuccess') or '')[:4] not in ('', '2099'),
      str(r and r.get('lastSuccess')))
others_intact('清理')
if new:
    f = DAILY / new[0]
    check('清理：新的備份 integrity_check ok、會議數相同', integrity(f) == ['ok'] and meetings(f) == live_meetings,
          f'{integrity(f)} {meetings(f)}/{live_meetings}')
    header = f.read_bytes()[18:20]
    sidecars = [s for s in ('-wal', '-shm', '-journal') if Path(str(f) + s).exists()]
    check('清理：新的備份是 rollback 模式的單一檔（檔頭 18、19 是 1、沒有旁檔）', header == b'\x01\x01' and not sidecars,
          f'{header.hex()} {sidecars}')
ctl('mabackup', 'prune')
time.sleep(1)
others_intact('prune（沒在備份時）後（P3-1）')
check('prune 後：一般檔備份還是 7 份', regular_backups() == after, str(regular_backups()))

# ---------- 3. 重疊 ----------
ctl('mabackup', 'age', '1.1')
time.sleep(0.5)
before = set(regular_backups())
ctl('mabackup', 'simulate', 'slow', '6')
time.sleep(0.3)
first = bk('now', 'overlap-first', wait=False)
time.sleep(1.5)
second = bk('check', 'overlap-check', timeout=10)
third = bk('now', 'overlap-now', timeout=10)
first_r = wait_json(first, 120)
after = regular_backups()
check('重疊：第一份還在寫時排程的 check 回 running', second and second.get('outcome') == 'running', str(second and second.get('outcome')))
check('重疊：第一份還在寫時 now 回 running', third and third.get('outcome') == 'running', str(third and third.get('outcome')))
check('重疊：第一份 done', first_r and first_r.get('outcome') == 'done', str(first_r and first_r.get('outcome')))
added = sorted(set(after) - before)
check('重疊：只多一份（舊的照份數清）、沒有暫存檔', len(added) == 1 and not leftover_partials() and len(after) == 7,
      f'added={added} partials={leftover_partials()} count={len(after)}')
if added:
    check('重疊：那份 integrity_check ok', integrity(DAILY / added[0]) == ['ok'])

# ---------- 4. 錄完後到期的檢查 ----------
ctl('mabackup', 'age', '1.1')
time.sleep(0.5)
wav = OUT / 'tone.wav'
tone(wav)
before = set(regular_backups())
ctl('record-sim', wav, 1, 1)
recording = wait_recording(True)
check('錄音：開始錄音', recording)
r = bk('check', 'recording-check')
check('錄音中：到期的 check 回 deferredRecording', r and r.get('outcome') == 'deferredRecording', str(r and r.get('outcome')))
check('錄音中：沒有多出備份', set(regular_backups()) == before)
time.sleep(3)
ctl('record', 'stop')
stopped = wait_recording(False)
check('錄音：停止', stopped)
r = bk('check', 'after-recording-check', timeout=120)
added = sorted(set(regular_backups()) - before)
check('錄完後：到期的 check 回 done、多一份', r and r.get('outcome') == 'done' and len(added) == 1,
      f'{r and r.get("outcome")} {added}')

# ---------- 4b. 寫入目的地（REVIEW-F10b P2-3）----------
# 在接下來幾秒會用到的每個時間名稱上放同一種東西，各跑一次 now：要回 failed、連結和目標、資料夾都不變。
# 目標檔全部在 --out（測試資料夾）裡自建，不指向任何真實資料
from datetime import datetime, timedelta


def make_victim(path):
    path.unlink(missing_ok=True)
    with sqlite3.connect(path) as c:
        c.execute('create table important_sentinel(v text)')
        c.execute("insert into important_sentinel values ('KEEP THIS SYNTHETIC DATA')")
    return sha(path)


def victim_ok(path, digest):
    if not path.is_file() or sha(path) != digest:
        return False
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as c:
        return c.execute('select v from important_sentinel').fetchall() == [('KEEP THIS SYNTHETIC DATA',)]


def upcoming_stamps(seconds=8):
    now = datetime.now()
    return [(now + timedelta(seconds=i)).strftime('%Y%m%d-%H%M%S') for i in range(0, seconds)]


def name_free(stamp):
    return not any(os.path.lexists(DAILY / f'ma-daily-{stamp}{s}')
                   for s in ('.sqlite', '.partial', '.partial-wal', '.partial-shm', '.partial-journal'))


def write_case(label, plant, verify):
    """plant(stamp) 在一個時間名稱上放東西、回傳要清掉的路徑；verify() 回傳 (ok, detail)"""
    # 先等到下一秒：不然這次的時間可能跟上一份備份同一秒，先撞到「同名的備份已經存在」，測不到暫存檔那段
    time.sleep(1.1)
    regular_before = regular_backups()
    planted = []
    for stamp in upcoming_stamps():
        if name_free(stamp):   # 已經有東西的名字（剛做的備份）不放，避免測試自己出錯
            planted += plant(stamp)
    r = bk('now', f'write-{label}', timeout=60)
    ok, detail = verify()
    regular_after = regular_backups()
    check(f'寫入目的地 {label}：now 回 failed、沒有假成功', r and r.get('outcome') == 'failed',
          f'{r and r.get("outcome")} {r and r.get("reason")}')
    check(f'寫入目的地 {label}：連結、目標、資料夾都不變（沒有寫穿）', ok, detail)
    check(f'寫入目的地 {label}：正常備份照留、沒有多出備份或暫存檔', regular_after == regular_before and not leftover_partials(),
          f'{len(regular_before)}→{len(regular_after)} partials={leftover_partials()}')
    for path in planted:   # 這些都是這個測試自己放的
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            subprocess.run(['rm', '-rf', str(path)], check=True)


# a. .partial 是指向含 sentinel 的 SQLite 的連結
victim = OUT / 'victim-partial.sqlite'
victim_sha = make_victim(victim)
links_a = []


def plant_a(stamp):
    link = DAILY / f'ma-daily-{stamp}.partial'
    os.symlink(victim, link)
    links_a.append(link)
    return [link]


write_case('.partial 連結到 SQLite', plant_a,
           lambda: (victim_ok(victim, victim_sha) and all(l.is_symlink() and os.readlink(l) == str(victim) for l in links_a),
                    f'victim_ok={victim_ok(victim, victim_sha)}'))

# b. 斷掉的 .partial 連結
missing = OUT / 'missing-target.sqlite'
missing.unlink(missing_ok=True)
links_b = []


def plant_b(stamp):
    link = DAILY / f'ma-daily-{stamp}.partial'
    os.symlink(missing, link)
    links_b.append(link)
    return [link]


write_case('斷掉的 .partial 連結', plant_b,
           lambda: (not missing.exists() and all(l.is_symlink() and os.readlink(l) == str(missing) for l in links_b),
                    f'target_created={missing.exists()}'))

# c. .partial 是資料夾（裡面有檔）
dirs_c = []


def plant_c(stamp):
    d = DAILY / f'ma-daily-{stamp}.partial'
    d.mkdir()
    (d / 'inside.txt').write_text('inside (synthetic)\n')
    dirs_c.append(d)
    return [d]


write_case('.partial 資料夾', plant_c,
           lambda: (all(d.is_dir() and (d / 'inside.txt').read_text() == 'inside (synthetic)\n' and len(list(d.iterdir())) == 1
                        for d in dirs_c), ''))

# d. -wal、-shm、-journal 是指向 sentinel 檔的連結
for suffix in ('-wal', '-shm', '-journal'):
    target = OUT / f'sentinel{suffix}.txt'
    target.write_text(f'sidecar sentinel {suffix} (synthetic)\n')
    target_sha = sha(target)
    links_d = []

    def plant_d(stamp, suffix=suffix, target=target, links_d=links_d):
        link = DAILY / f'ma-daily-{stamp}.partial{suffix}'
        os.symlink(target, link)
        links_d.append(link)
        return [link]

    write_case(f'{suffix} 連結', plant_d,
               lambda target=target, target_sha=target_sha, links_d=links_d:
               (target.is_file() and sha(target) == target_sha
                and all(l.is_symlink() and os.readlink(l) == str(target) for l in links_d), ''))

# e. 正式檔名是連結
victim_final = OUT / 'victim-final.sqlite'
victim_final_sha = make_victim(victim_final)
links_e = []


def plant_e(stamp):
    link = DAILY / f'ma-daily-{stamp}.sqlite'
    os.symlink(victim_final, link)
    links_e.append(link)
    return [link]


write_case('正式檔名是連結', plant_e,
           lambda: (victim_ok(victim_final, victim_final_sha)
                    and all(l.is_symlink() and os.readlink(l) == str(victim_final) for l in links_e), ''))

r = bk('now', 'write-after-cases', timeout=120)
check('寫入目的地：反例清掉後 now 照常 done', r and r.get('outcome') == 'done', str(r and r.get('outcome')))

# ---------- 5. 最後 ----------
final = regular_backups()
check('最後：一般檔備份 7 份', len(final) == 7, str(final))
check('最後：沒有暫存檔', not leftover_partials(), str(leftover_partials()))
others_intact('最後')
ctl('mabackup', 'simulate', 'off')
ctl('mabackup', 'schedule', 'on')
(OUT / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=1))
fails = [x for x in results if not x['ok']]
print(f'{len(results) - len(fails)}/{len(results)} 通過')
sys.exit(1 if fails else 0)
