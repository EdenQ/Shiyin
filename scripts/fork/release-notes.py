#!/usr/bin/env python3
"""app 內更新說明（F13.3，fork design §F13.3）：tag 說明裡「- 基於上游 拾音 X.Y.Z」這類只給 GitHub Release 看的行，
不進 shiyin-update.json 的 notes。

用法：printf '%s' "$SHIYIN_RELEASE_NOTES" | python3 scripts/fork/release-notes.py app
  拿掉符合 fork/brand.json releaseNotes.appDrop 的行，其他行（含空行、段落）原樣輸出。make-dmg.sh 呼叫。
只用 Python 標準函式庫。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def for_app(notes):
    drop = [re.compile(p) for p in json.loads((ROOT / "fork/brand.json").read_text(encoding="utf-8"))["releaseNotes"]["appDrop"]]
    lines = notes.replace("\r\n", "\n").split("\n")
    return "\n".join(line for line in lines if not any(p.search(line.strip()) for p in drop))


def main(argv):
    if argv[:1] == ["app"]:
        sys.stdout.write(for_app(sys.stdin.read()))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
