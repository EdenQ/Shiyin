#!/usr/bin/env python3
"""fork 的全域快捷鍵 ID 不能跟上游撞號（fork design §F14.1、DF17）。

上游 GlobalHotKey 用同一個 signature（'SHYI'）註冊每一組快捷鍵，ID 是 `static let …ID: UInt32 = N`；
`register` 看到 ID 已經有了就直接回 noErr，所以撞號時後註冊的那組不會成功、也不報錯（5.1 的截圖 ⌃⌥⌘S 用 3，
fork 的 ⌃⌥⌘M 原本也是 3）。fork 的 ID 一律在 0x4D41_0000～0x4D41_FFFF（「MA」）。

用法：python3 scripts/fork/hotkey-id-check.py [--root <repo>]   有問題 exit 1。check.sh 的 I1 一起跑
"""
import re
import sys
from pathlib import Path

FORK_RANGE = range(0x4D41_0000, 0x4D42_0000)
DECL = re.compile(r"static\s+let\s+(\w*[Ii][Dd])\s*:\s*UInt32\s*=\s*(0x[0-9A-Fa-f_]+|[0-9_]+)")


def ids(path):
    return [(name, int(value.replace("_", ""), 0), path) for name, value in DECL.findall(path.read_text(encoding="utf-8"))]


def check(root):
    upstream = ids(root / "Sources/Shiyin/Services/GlobalHotKey.swift")
    fork = [i for p in sorted((root / "Sources/Shiyin/Fork").rglob("*.swift")) for i in ids(p) if "hotKey" in i[0]]
    problems = []
    if not upstream:
        problems.append("Sources/Shiyin/Services/GlobalHotKey.swift 找不到上游的快捷鍵 ID（上游改了寫法，要更新這支檢查）")
    if not fork:
        problems.append("Sources/Shiyin/Fork 找不到 fork 的快捷鍵 ID（hotKeyID）")
    taken = {value: name for name, value, _ in upstream}
    seen = {}
    for name, value, path in fork:
        rel = path.relative_to(root)
        if value in taken:
            problems.append(f"{rel}：{name} = {value} 跟上游的 {taken[value]} 撞號")
        if value not in FORK_RANGE:
            problems.append(f"{rel}：{name} = {value:#x} 不在 fork 的區段 0x4D41_0000～0x4D41_FFFF（DF17）")
        if value in seen:
            problems.append(f"{rel}：{name} = {value:#x} 跟 fork 的 {seen[value]} 重複")
        seen[value] = name
    return upstream, fork, problems


def main(argv):
    root = Path(argv[argv.index("--root") + 1]) if "--root" in argv else Path(__file__).resolve().parents[2]
    upstream, fork, problems = check(root)
    print("上游的快捷鍵 ID：" + "、".join(f"{n}={v}" for n, v, _ in upstream))
    print("fork 的快捷鍵 ID：" + "、".join(f"{n}={v:#x}" for n, v, _ in fork))
    if problems:
        print(f"hotkey-id-check：有 {len(problems)} 個問題")
        for p in problems:
            print("  - " + p)
        return 1
    print("PASS：fork 的快捷鍵 ID 沒有跟上游重複")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
