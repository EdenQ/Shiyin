#!/usr/bin/env python3
"""scripts/fork/check.sh 的 #4 F1（名稱、回報問題的網址、圖示；fork design §F0.4、§F1）。

  - repo 的 Resources/AppIcon.icns 的 sha256 等於 manifest F1.iconSha256（合併上游時圖示衝突一律保留 fork 的）
  - repo 的 Info.plist 的 ShiyinIssuesURL 等於 manifest F1.infoPlistKeys
  - 「關於 MA」、更新說明選段落的接點還在（ShiyinApp 的 BrandAboutCommand、ReleaseNotes 的 Brand.names，都標 MA-FORK(F7)）
  - --app：建好的 app 的 icns、ShiyinIssuesURL 也一樣，Info.plist 有 MABrand
  - --update-url：CI 的 vars.SHIYIN_UPDATE_URL（gh variable get）要指到 fork；gh 讀不到就印 SKIP
用法：python3 scripts/fork/check-f1.py [--app <App.app>]… [--update-url]
每一行 PASS／FAIL／SKIP；有 FAIL 時 exit 1。
"""
import argparse
import hashlib
import json
import plistlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('--app', type=Path, action='append', default=[])
ap.add_argument('--update-url', action='store_true')
args = ap.parse_args()
F1 = json.loads((ROOT / 'docs/fork/manifest.json').read_text())['features']['F1']
fails = 0


def check(ok, message):
    global fails
    print(('PASS ' if ok else 'FAIL ') + message)
    fails += not ok


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else '（沒有檔案）'


want_icon = F1.get('iconSha256', '')
check(bool(want_icon) and sha(ROOT / 'Resources/AppIcon.icns') == want_icon,
      f'Resources/AppIcon.icns 的 sha256 = manifest F1.iconSha256（{want_icon[:12]}…）')
plist = plistlib.loads((ROOT / 'Resources/Info.plist').read_bytes())
for key, value in F1['infoPlistKeys'].items():
    check(plist.get(key) == value, f'Resources/Info.plist {key} = {value}（{plist.get(key)}）')
hooks = {
    'Sources/Shiyin/App/ShiyinApp.swift': r'^\s*BrandAboutCommand\(\)\s*// MA-FORK\(F7\)$',
    'Sources/Shiyin/Fork/Brand.swift': r'orderFrontStandardAboutPanel\(options: Brand\.aboutName',
}
for path, pattern in hooks.items():
    text = (ROOT / path).read_text() if (ROOT / path).exists() else ''
    check(re.search(pattern, text, re.M) is not None, f'{path} 有「關於 MA」的接點（/{pattern}/）')
notes = next(ROOT.glob('Sources/Shiyin/*/ReleaseNotes.swift'), None)
count = len(re.findall(r'Brand\.names\(.*// .*MA-FORK\(F7\)', notes.read_text())) if notes else 0
check(count == 2, f'ReleaseNotes 選中文、英文段落的 2 個 MA-FORK(F7) 接點（{count}）')

for app in args.app:
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    check(sha(app / 'Contents/Resources/AppIcon.icns') == want_icon, f'{app.parent.name}：AppIcon.icns 的 sha256 = fork 的')
    for key, value in F1['infoPlistKeys'].items():
        check(info.get(key) == value, f'{app.parent.name}：Info.plist {key} = {value}（{info.get(key)}）')
    check(isinstance(info.get('MABrand'), dict) and bool(info['MABrand']), f'{app.parent.name}：Info.plist 有 MABrand')

if args.update_url:
    try:
        r = subprocess.run(['gh', 'variable', 'get', 'SHIYIN_UPDATE_URL', '-R', 'EdenQ/Shiyin'],
                           capture_output=True, text=True, timeout=20)
        url = r.stdout.strip() if r.returncode == 0 else ''
    except (OSError, subprocess.TimeoutExpired):
        url = ''
    if not url:
        print('SKIP CI 的 SHIYIN_UPDATE_URL：gh 讀不到（沒登入、沒網路或沒權限），發布前在 GitHub 的 Variables 看一眼')
    else:
        check('EdenQ/Shiyin' in url, f'CI 的 SHIYIN_UPDATE_URL 指到 fork（{url}）')
sys.exit(1 if fails else 0)
