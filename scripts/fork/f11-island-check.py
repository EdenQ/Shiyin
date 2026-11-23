#!/usr/bin/env python3
"""F11 錄音島放在哪個螢幕的自動化驗證（fork design §F11.6）。

對一個已經開著、用暫存 SHIYIN_HOME、錄音島開著（-recordingIsland YES）而且放在桌面層（-debugIslandBehind YES）的
DEBUG 版跑（check.sh #15）：
  1. 還沒改過設定時 placement 是 builtin（預設）
  2. record-sim 開始錄音，等島出現
  3. 每種情況用 maisland mode／simulate 設好，等 1.2 秒（大於 0.5 秒的 Timer），maisland screens 核對：
     - reason、expected（島該在的螢幕）跟這裡獨立算的一樣
     - 島的 frame 整個在那個螢幕裡、水平置中（有瀏海時在瀏海中間，容許 40 pt）、上緣照上游的規則（有瀏海貼螢幕上緣，
       沒有在選單列下方）
     - 島的 notch 等於那個螢幕的 notch
     情況：builtin（有內建螢幕時在內建螢幕；沒有時退路）、follow（pick 是 null、跟上游同一個螢幕）、mainWindow 主視窗在
     每一個螢幕、主視窗關著用記下的、記下的清掉退到上游、builtin 加模擬沒有內建螢幕（退到主視窗的螢幕、記下的、上游）
  4. mawindowshot 拍島（內建螢幕、外接螢幕各一張，有的話）
  5. simulate off；不停止錄音（停止後的轉錄會下載、編譯說話者辨識的模型，跟 F11 無關），DEBUG 版由 check.sh 結束
注意：fork 還沒帶入上游 4c3a8d3（state 遇到錄音島面板無限大的最大尺寸會讓 DEBUG 版當掉），這裡一律用 maisland screens，
不呼叫 state。
用法：python3 scripts/fork/f11-island-check.py <SHIYIN_HOME> <shiyinctl> --out <資料夾>
只讀寫 --out；同時只能開一個 DEBUG 版（shiyinctl 是廣播）。exit 0 通過、1 不符。
"""
import argparse
import json
import math
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
results = []


def check(name, ok, detail=''):
    results.append({'check': name, 'ok': bool(ok), 'detail': detail})
    print(('PASS ' if ok else 'FAIL ') + name + (f'：{detail}' if detail else ''), flush=True)
    return ok


def ctl(*a):
    subprocess.run([str(CTL), *map(str, a)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def screens(label, timeout=15):
    path = OUT / f'screens-{label}.json'
    path.unlink(missing_ok=True)
    ctl('maisland', 'screens', path)
    end = time.time() + timeout
    while time.time() < end:
        if path.exists() and path.stat().st_size > 0:
            time.sleep(0.2)
            try:
                return json.loads(path.read_text())
            except json.JSONDecodeError:
                pass
        time.sleep(0.2)
    raise SystemExit(f'maisland screens 沒有寫出 {path.name}（DEBUG 版沒回應或當掉了）')


def tone(path, seconds=90, rate=16000):
    frames = b''.join(struct.pack('<h', int(6000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(seconds * rate))
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(frames)


def wait_island(visible, timeout=30):
    end = time.time() + timeout
    s = None
    while time.time() < end:
        s = screens('wait')
        if bool(s['island'].get('visible')) == visible:
            return s
        time.sleep(0.5)
    return s


def verify(label, s, want_index, want_reason):
    """島在 want_index 螢幕、理由是 want_reason；follow 時 pick 是 null、expected 是上游的螢幕"""
    ok = check(f'{label}：理由 {want_reason}', s['reason'] == want_reason, f'reason={s["reason"]}')
    ok &= check(f'{label}：島該在第 {want_index} 個螢幕', s['expected'] == want_index,
                f'expected={s["expected"]} pick={s["pick"]} upstream={s["upstream"]} main={s["main"]}')
    island = s['island']
    frame = island.get('frame') or []
    if not check(f'{label}：島看得到、有 frame', island.get('visible') and len(frame) == 4, json.dumps(island, ensure_ascii=False)):
        return False
    screen = s['screens'][want_index]
    sx, sy, sw, sh = screen['frame']
    x, y, w, h = frame
    inside = x >= sx - 0.5 and y >= sy - 0.5 and x + w <= sx + sw + 0.5 and y + h <= sy + sh + 0.5
    ok &= check(f'{label}：島的 frame 整個在第 {want_index} 個螢幕裡', inside, f'island={frame} screen={screen["frame"]}')
    mid, smid = x + w / 2, sx + sw / 2
    ok &= check(f'{label}：島水平置中', abs(mid - smid) <= (40 if screen['notch'] else 2), f'island.midX={mid} screen.midX={smid}')
    top, stop = y + h, sy + sh
    menu = stop - (screen['visibleFrame'][1] + screen['visibleFrame'][3])
    want_top = stop if screen['notch'] else stop - menu - 6
    ok &= check(f'{label}：上緣照上游的規則（{"貼螢幕上緣" if screen["notch"] else "選單列下方 6 pt"}）', abs(top - want_top) <= 1,
                f'top={top} want={want_top}')
    ok &= check(f'{label}：notch 等於那個螢幕的', bool(island.get('notch')) == bool(screen['notch']),
                f'island.notch={island.get("notch")} screen.notch={screen["notch"]}')
    return ok


def case(label, *commands):
    for cmd in commands:
        ctl('maisland', *cmd)
    time.sleep(1.2)
    return screens(label)


def main():
    s = screens('start')
    n = len(s['screens'])
    builtins = [x['index'] for x in s['screens'] if x['builtin']]
    externals = [x['index'] for x in s['screens'] if not x['builtin']]
    print(f'螢幕 {n} 個：內建 {builtins}、外接 {externals}；NSScreen.main={s["main"]}', flush=True)
    check('還沒改過設定：placement 是 builtin（預設）', s['placement'] == 'builtin', s['placement'])
    check('還沒錄音：島沒出現', not s['island'].get('visible'))

    wav = OUT / 'tone.wav'
    tone(wav)
    ctl('record-sim', wav, 1, 1)
    s = wait_island(True)
    if not check('錄音中：島出現', s and s['island'].get('visible'), json.dumps(s and s['island'], ensure_ascii=False)):
        return   # 記 FAIL 就結束；不停止錄音（同最後一步），錄音中的 DEBUG 版由 check.sh 結束

    def upstream(s):
        return s['upstream']

    # 主視窗的狀態先固定成「關著、沒有記下」，退路才是確定的
    s = case('builtin', ('simulate', 'off'), ('simulate', 'mainscreen', 'closed'), ('simulate', 'remembered', 'none'),
             ('mode', 'builtin'))
    if builtins:
        verify('內建螢幕', s, builtins[0], 'builtin')
    else:
        verify('內建螢幕（這台沒有內建螢幕，主視窗關著、沒記下 → 上游）', s, upstream(s), 'upstream')

    s = case('follow', ('mode', 'follow'))
    check('跟著目前在用的螢幕：pick 是 null（照上游）', s['pick'] is None, str(s['pick']))
    verify('跟著目前在用的螢幕（跟上游相同）', s, upstream(s), 'follow')

    last = None
    for i in range(n):
        s = case(f'mainwindow-{i}', ('mode', 'mainWindow'), ('simulate', 'mainscreen', i))
        verify(f'主視窗所在的螢幕（主視窗在第 {i} 個）', s, i, 'mainWindow')
        last = i
    s = case('mainwindow-closed', ('simulate', 'mainscreen', 'closed'))
    verify(f'主視窗關著：用記下的第 {last} 個', s, last, 'mainWindowRemembered')
    s = case('mainwindow-none', ('simulate', 'remembered', 'none'))
    verify('主視窗關著、沒有記下：照上游', s, upstream(s), 'upstream')

    k = externals[0] if externals else 0
    s = case('nobuiltin-main', ('mode', 'builtin'), ('simulate', 'nobuiltin', 'on'), ('simulate', 'mainscreen', k))
    verify(f'沒有內建螢幕：退到主視窗的第 {k} 個', s, k, 'mainWindow')
    s = case('nobuiltin-remembered', ('simulate', 'mainscreen', 'closed'))
    verify(f'沒有內建螢幕、主視窗關著：用記下的第 {k} 個', s, k, 'mainWindowRemembered')
    s = case('nobuiltin-upstream', ('simulate', 'remembered', 'none'))
    verify('沒有內建螢幕、主視窗關著、沒有記下：照上游', s, upstream(s), 'upstream')
    s = case('builtin-again', ('simulate', 'nobuiltin', 'off'))
    if builtins:
        verify('模擬拿掉後回到內建螢幕', s, builtins[0], 'builtin')

    # 截圖：內建螢幕（有瀏海時接在瀏海兩側）、外接螢幕（膠囊）
    shots = []
    if builtins:
        shots.append(('builtin', [('mode', 'builtin')]))
    if externals:
        shots.append(('external', [('mode', 'mainWindow'), ('simulate', 'mainscreen', externals[0])]))
    for name, cmds in shots:
        case(f'shot-{name}', *cmds)
        png = OUT / f'island-{name}.png'
        png.unlink(missing_ok=True)
        ctl('mawindowshot', png, 'island')
        end = time.time() + 10
        while time.time() < end and not png.exists():
            time.sleep(0.3)
        check(f'截圖：島（{name}）', png.exists() and png.stat().st_size > 0, png.name)

    # 不停止錄音：停止後的轉錄會在暫存的 SHIYIN_HOME 下載、編譯說話者辨識的模型（跟 F11 無關，2026-11-23 在 CoreML 編譯
    # 時當掉過一次）。錄音中的 DEBUG 版由 check.sh 結束，暫存資料夾整個刪掉
    ctl('maisland', 'simulate', 'off')


try:
    main()
finally:
    (OUT / 'f11-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
failed = [r for r in results if not r['ok']]
print(f'\n{len(results) - len(failed)}/{len(results)} 通過')
sys.exit(1 if failed or not results else 0)
