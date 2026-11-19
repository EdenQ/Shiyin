#!/usr/bin/env python3
"""F3 錄音中靜音的錄音檔檢查（fork design §F3；REVIEW-2 P3-1）。

對一個已經開著、用暫存 SHIYIN_HOME 的 DEBUG 版跑：
  1. 產生 40 秒、兩個聲道都一直有聲音的測試音（440 Hz），`record-sim <音檔> 1 1` 模擬錄音
  2. micmute on → hotkey mute（解除）→ hotkey mute（再靜音）→ micmute dismiss → micmute off → record stop；
     每一步後讀 state，記下錄音的 elapsed 和 micMuted（狀態另存，可以跟別的版本逐位元組比）
  3. 用這次錄音的會議 id（state 的 recorder.meetingId）查 meetings.audio_file，精確選那一個檔（壓縮後是 M4A，
     等到檔案寫完），afconvert 解成 16-bit PCM 後自己讀 RIFF（WAVE_FORMAT_EXTENSIBLE 也可以）
  4. assert：兩個聲道；靜音區間（前後各留 0.75 秒）麥克風聲道的峰值 ≤ 4／32768、電腦聲音照常；
     沒靜音的區間兩個聲道都有聲音
用法：python3 scripts/fork/f3-mute-check.py <SHIYIN_HOME> <shiyinctl> --out <資料夾>
只讀寫 <SHIYIN_HOME>；同時只能開一個 DEBUG 版（shiyinctl 是廣播）。exit 0 通過、1 不符。
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
from pathlib import Path

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('home', type=Path)
ap.add_argument('ctl', type=Path)
ap.add_argument('--out', type=Path, required=True)
args = ap.parse_args()
HOME, CTL, OUT = args.home.resolve(), args.ctl, args.out
DB = HOME / 'shiyin.sqlite'
OUT.mkdir(parents=True, exist_ok=True)
if HOME == (Path.home() / 'Library/Application Support/Shiyin').resolve():
    sys.exit('不能對正式的資料夾跑')
MARGIN = 0.75        # 靜音切換的時間點前後不判斷（elapsed 和寫進檔的時間差、AAC 的前後延遲）
SILENT_PEAK = 4      # 靜音時麥克風聲道的峰值上限（AAC 解碼的雜訊是 0～1）
LOUD_PEAK = 1000     # 有聲音的峰值下限（測試音約 9800）


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


def state():
    path = OUT / 'state-raw.json'
    path.unlink(missing_ok=True)
    ctl('state', path)
    wait(lambda: path.exists() and path.stat().st_size > 0)
    time.sleep(0.3)
    return json.loads(path.read_text())


def tone(path, seconds=40, rate=16000):
    frames = b''.join(struct.pack('<h', int(9800 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(seconds * rate))
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(frames)


def read_pcm(path):
    """讀 16-bit PCM 的 WAV（WAVE_FORMAT_PCM 或 EXTENSIBLE）：回傳 (聲道數, 取樣率, [每個聲道的樣本])"""
    data = path.read_bytes()
    assert data[:4] == b'RIFF' and data[8:12] == b'WAVE', 'not a WAV'
    pos, fmt, pcm = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack('<I', data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b'fmt ':
            tag, ch, rate = struct.unpack('<HHI', body[:8])
            bits = struct.unpack('<H', body[14:16])[0]
            if tag == 0xFFFE:   # EXTENSIBLE：子格式的前兩個位元組是真正的格式
                tag = struct.unpack('<H', body[24:26])[0]
            assert tag == 1 and bits == 16, (tag, bits)
            fmt = (ch, rate)
        elif cid == b'data':
            pcm = body
        pos += 8 + size + (size & 1)
    ch, rate = fmt
    samples = struct.unpack(f'<{len(pcm) // 2}h', pcm[:len(pcm) // 2 * 2])
    return ch, rate, [samples[c::ch] for c in range(ch)]


def peak(chan, rate, start, end):
    a, b = max(0, int(start * rate)), min(len(chan), int(end * rate))
    return max((abs(x) for x in chan[a:b]), default=0)


def main():
    if query("SELECT count(*) FROM meetings WHERE source='recording' AND audio_file=''")[0][0]:
        sys.exit('這個 SHIYIN_HOME 已經有錄音中的會議')
    sim = OUT / 'tone.wav'
    tone(sim)
    steps, states = [], {}

    def step(label, *cmd, pause):
        if cmd:
            ctl(*cmd)
        time.sleep(pause)
        s = state()
        r = s['recorder']
        steps.append({'label': label, 'elapsed': r['elapsed'], 'muted': r.get('micMuted'), 'meetingId': r['meetingId']})
        states[label] = {'recording': r['recording'], 'micMuted': r.get('micMuted'), 'muteHint': r.get('muteHint'),
                         'menuBarSymbol': s.get('menuBarSymbol'), 'muteRegistered': s['hotkey'].get('muteRegistered'),
                         'bookmarkRegistered': s['hotkey'].get('bookmarkRegistered')}

    ctl('record-sim', sim, 1, 1)
    wait(lambda: state()['recorder']['recording'] and state()['recorder']['elapsed'] > 1, 30)
    step('0-recording', pause=2)
    step('1-micmute-on', 'micmute', 'on', pause=3)
    step('2-hotkey-off', 'hotkey', 'mute', pause=3)
    step('3-hotkey-on', 'hotkey', 'mute', pause=3)
    step('4-dismiss', 'micmute', 'dismiss', pause=1)
    step('5-off', 'micmute', 'off', pause=3)
    mid = steps[0]['meetingId']
    assert mid > 0 and all(s['meetingId'] == mid for s in steps), steps
    ctl('record', 'stop')
    time.sleep(3)

    # 這次錄音的檔：會議的 audio_file（錄完會壓成 M4A），等它不再變
    def audio():
        rows = query('SELECT audio_file FROM meetings WHERE id=?', (mid,))
        return rows[0] if rows else ('',)
    # 錄音中 audio_file 是空的（source 一直是 recording）；停止後寫上 WAV，轉錄完成後壓成 M4A（設定預設開）再換成 .m4a。
    # 等到 M4A（最多 180 秒）；設定關掉壓縮時就用 WAV。先複製一份再解碼，不跟 app 的壓縮搶檔
    wait(lambda: audio()[0] and (HOME / 'audio' / audio()[0]).exists(), 120)
    try:
        wait(lambda: audio()[0].endswith('.m4a') and (HOME / 'audio' / audio()[0]).exists(), 180)
    except TimeoutError:
        print('注意：180 秒內沒壓成 M4A，用 WAV 檢查')
    time.sleep(2)
    # 停止後的狀態在轉錄、壓縮做完之後讀（選單列的圖示在轉錄中、做完不同，停止後馬上讀會看時機）
    s = state()
    states['6-stopped'] = {'recording': s['recorder']['recording'], 'micMuted': s['recorder'].get('micMuted'),
                           'menuBarSymbol': s.get('menuBarSymbol'), 'muteRegistered': s['hotkey'].get('muteRegistered')}
    (OUT / 'f3-states.json').write_text(json.dumps(states, ensure_ascii=False, indent=1))
    path = HOME / 'audio' / audio()[0]
    copy = OUT / ('recording' + path.suffix)
    copy.write_bytes(path.read_bytes())
    decoded = OUT / 'recording-decoded.wav'
    decoded.unlink(missing_ok=True)
    subprocess.run(['/usr/bin/afconvert', '-f', 'WAVE', '-d', 'LEI16', str(copy), str(decoded)], check=True)
    ch, rate, chans = read_pcm(decoded)
    duration = len(chans[0]) / rate

    # 每一步的狀態從「送出指令」（約是前一步讀到的 elapsed）維持到「下一個指令」（不早於這一步讀到的 elapsed）。
    # 前面多留 0.5 秒給指令生效，前後再各留 MARGIN 給 elapsed 和檔案時間的差、AAC 的延遲
    segments = [(1.0, steps[0]['elapsed'], False)]
    segments += [(steps[i - 1]['elapsed'] + 0.5, steps[i]['elapsed'], bool(steps[i]['muted'])) for i in range(1, len(steps))]
    problems, checks = [], []
    if ch != 2:
        problems.append(f'聲道數 {ch}，應該是 2')
    for a, b, is_muted in segments:
        lo, hi = a + MARGIN, min(b, duration) - MARGIN
        if hi - lo < 0.5:
            continue
        mic = peak(chans[0], rate, lo, hi)
        sysp = peak(chans[1], rate, lo, hi) if ch > 1 else 0
        checks.append({'range': [round(lo, 2), round(hi, 2)], 'expect': 'muted' if is_muted else 'open', 'mic': mic, 'system': sysp})
        if is_muted and mic > SILENT_PEAK:
            problems.append(f'{lo:.2f}～{hi:.2f} 秒應該靜音，麥克風峰值 {mic}')
        if is_muted and sysp < LOUD_PEAK:
            problems.append(f'{lo:.2f}～{hi:.2f} 秒電腦聲音應該照常，峰值 {sysp}')
        if not is_muted and (mic < LOUD_PEAK or sysp < LOUD_PEAK):
            problems.append(f'{lo:.2f}～{hi:.2f} 秒沒靜音，兩個聲道都應該有聲音：麥克風 {mic}、電腦 {sysp}')
    if not any(c['expect'] == 'muted' for c in checks) or not any(c['expect'] == 'open' for c in checks):
        problems.append('靜音、沒靜音的區間不夠長，判斷不了')
    result = {'meeting': mid, 'audioFile': path.name, 'channels': ch, 'rate': rate, 'seconds': round(duration, 2),
              'steps': steps, 'checks': checks, 'problems': problems}
    (OUT / 'f3-audio.json').write_text(json.dumps(result, ensure_ascii=False, indent=1))
    for c in checks:
        print(f"{c['expect']:<6} {c['range'][0]:>6.2f}～{c['range'][1]:<6.2f} 麥克風 {c['mic']:>5}  電腦 {c['system']:>5}")
    print(f'{path.name}：{ch} 聲道、{duration:.2f} 秒')
    if problems:
        print('FAIL：\n  - ' + '\n  - '.join(problems))
        sys.exit(1)
    print('PASS：錄音檔兩個聲道，靜音時麥克風是 0、電腦聲音照常，沒靜音時兩個聲道都有聲音')


if __name__ == '__main__':
    main()
