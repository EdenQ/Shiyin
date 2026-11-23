#!/usr/bin/env python3
"""isolation-check.py 本身的回歸測試（fork design §F0.3）。

在暫存資料夾建小的 git repo（基準 tag `base`：Sources/Probe.swift、Sources/Keep.swift、scripts/tool.sh），
每個情境改一份複本，用 `isolation-check.py --root <複本> --base base` 跑：
  - 正對照：沒改、只加 fork 的新檔、加了標記的接點 → exit 0
  - 負對照：沒標記的修改、已 stage 的改名（R100）、已 commit 的改名、改名又改內容、刪檔、換成連結（type change）、
    改名的上游腳本 → exit 1
不碰專案的 repo、不改 git 設定（commit 用 -c 帶名字）。用法：python3 scripts/fork/isolation-check-test.py [-v]
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

# ISOLATION_CHECK=<別的版本的 isolation-check.py>：拿舊版跑同樣的情境，看舊版漏掉哪些
CHECK = os.environ.get('ISOLATION_CHECK') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'isolation-check.py')
VERBOSE = '-v' in sys.argv


def git(repo, *args):
    return subprocess.run(['git', '-c', 'user.name=isolation-test', '-c', 'user.email=isolation-test@example.invalid',
                           '-c', 'commit.gpgsign=false', '-c', 'tag.gpgsign=false', *args],
                          cwd=repo, capture_output=True, text=True, check=True).stdout


def mv(repo, src, dst):
    os.makedirs(os.path.dirname(os.path.join(repo, dst)), exist_ok=True)
    git(repo, 'mv', src, dst)


def write(repo, path, text):
    full = os.path.join(repo, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8') as fh:
        fh.write(text)


def make_base(root):
    repo = os.path.join(root, 'base')
    os.makedirs(repo)
    git(repo, 'init', '-q', '-b', 'main')
    write(repo, 'Sources/Probe.swift', 'func probe() {\n    print("keep")\n}\n' + ''.join(f'// line {i}\n' for i in range(20)))
    write(repo, 'Sources/Keep.swift', 'func keep() {}\n')
    write(repo, 'scripts/tool.sh', '#!/bin/sh\necho tool\n')
    manifest = {'upstream': {'base': {'tag': 'base'}}, 'rules': {'upstreamLineBudget': 100},
                'features': {'F2': {'forkFiles': [], 'symbols': [], 'upstreamFiles': [], 'markers': []}}}
    write(repo, 'docs/fork/manifest.json', json.dumps(manifest, indent=2) + '\n')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '-m', 'base')
    git(repo, 'tag', 'base')
    return repo


def run(repo, *extra):
    r = subprocess.run([sys.executable, CHECK, '--root', repo, '--base', 'base', *extra], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def scenario_clean(repo):
    pass


def scenario_new_fork_file(repo):
    write(repo, 'Sources/Shiyin/Fork/New.swift', 'func forkOnly() {}\n')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '-m', 'fork file')


def scenario_marked_hook(repo):
    path = os.path.join(repo, 'Sources/Probe.swift')
    text = open(path, encoding='utf-8').read().replace('    print("keep")\n', '    print("keep")\n    forkHook()   // MA-FORK(F2)\n')
    write(repo, 'Sources/Probe.swift', text)
    run(repo, '--write')   # manifest 的 markers 照程式寫，下一次不加參數的才是檢查


def scenario_unmarked_edit(repo):
    path = os.path.join(repo, 'Sources/Probe.swift')
    write(repo, 'Sources/Probe.swift', open(path, encoding='utf-8').read().replace('print("keep")', 'print("changed")'))


def scenario_staged_rename(repo):
    mv(repo, 'Sources/Probe.swift', 'Sources/Shiyin/Fork/Moved.swift')


def scenario_committed_rename(repo):
    mv(repo, 'Sources/Probe.swift', 'Sources/Shiyin/Fork/Moved.swift')
    git(repo, 'commit', '-q', '-m', 'move')


def scenario_rename_and_edit(repo):
    mv(repo, 'Sources/Probe.swift', 'Sources/Shiyin/Fork/Moved.swift')
    path = os.path.join(repo, 'Sources/Shiyin/Fork/Moved.swift')
    write(repo, 'Sources/Shiyin/Fork/Moved.swift', open(path, encoding='utf-8').read() + 'func extra() {}\n')
    git(repo, 'add', '-A')


def scenario_delete(repo):
    git(repo, 'rm', '-q', 'Sources/Keep.swift')
    git(repo, 'commit', '-q', '-m', 'delete')


def scenario_type_change(repo):
    os.remove(os.path.join(repo, 'Sources/Keep.swift'))
    os.makedirs(os.path.join(repo, 'Sources/Shiyin/Fork'), exist_ok=True)
    write(repo, 'Sources/Shiyin/Fork/Keep.swift', 'func keep() {}\n')
    os.symlink('Shiyin/Fork/Keep.swift', os.path.join(repo, 'Sources/Keep.swift'))
    git(repo, 'add', '-A')


def scenario_script_rename(repo):
    mv(repo, 'scripts/tool.sh', 'scripts/fork/tool.sh')
    git(repo, 'commit', '-q', '-m', 'move script')


UPSTREAM_DEBUG = '''enum DebugControl {
    static func handle(_ args: [String]) {
        guard let name = args.first else { return }
        switch name {
%s
        default: break
        }
    }
}
'''
FORK_DEBUG = '''enum ForkDebug {
    static let commands: Set<String> = [%s]
    static let shadowed: Set<String> = [%s]
    static func intercept(_ args: [String]) -> Bool { commands.contains(args[0]) }
}
'''
FORK_HANDLER = '''enum MuteDebug {
    static func handle(_ args: [String]) -> Bool {
        switch args[0] {
%s
        default: return false
        }
        return true
    }
}
'''


def debug_repo(root, name, upstream, handler='        case "micmute": break', commands=('micmute',), shadowed=()):
    """上游 DebugControl 的 switch 本體是 upstream；fork 加接點、ForkDebug（commands、shadowed）、MuteDebug（handler）"""
    repo = os.path.join(root, name)
    os.makedirs(repo)
    git(repo, 'init', '-q', '-b', 'main')
    write(repo, 'Sources/Shiyin/Debug/DebugControl.swift', UPSTREAM_DEBUG % upstream)
    manifest = {'upstream': {'base': {'tag': 'base'}}, 'rules': {'upstreamLineBudget': 100},
                'features': {'F0': {'forkFiles': [], 'symbols': [], 'upstreamFiles': [], 'markers': [],
                                    'debugCommands': list(commands)}}}
    write(repo, 'docs/fork/manifest.json', json.dumps(manifest, indent=2) + '\n')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '-m', 'base')
    git(repo, 'tag', 'base')
    path = os.path.join(repo, 'Sources/Shiyin/Debug/DebugControl.swift')
    text = open(path, encoding='utf-8').read().replace('else { return }\n', 'else { return }\n        if ForkDebug.intercept(args) { return }   // MA-FORK(F0)\n', 1)
    write(repo, 'Sources/Shiyin/Debug/DebugControl.swift', text)
    quote = lambda xs: ', '.join(f'"{x}"' for x in xs)
    write(repo, 'Sources/Shiyin/Fork/Debug/ForkDebug.swift', FORK_DEBUG % (quote(commands), quote(shadowed)))
    write(repo, 'Sources/Shiyin/Fork/Mute/MuteDebug.swift', FORK_HANDLER % handler)
    run(repo, '--write')
    return repo


# (名稱, 上游 switch 的本體, 其他參數, 預期 exit)
DEBUG_CASES = [
    ('debug-ok', '        case "state": break', {}, 0),
    ('debug-shadowed-ok', '        case "state", "windowshot": break',
     {'handler': '        case "micmute", "windowshot": break', 'commands': ('micmute', 'windowshot'), 'shadowed': ('windowshot',)}, 0),
    ('debug-comment-only', '        // case "micmute": 以前的寫法\n        case "state": break /* "micmute" */', {}, 0),
    ('debug-where-ok', '        case "model" where args.count > 2: break', {}, 0),
    ('clash-spaced', '        case "state", "micmute": break', {}, 1),
    ('clash-compact', '        case "state","micmute": break', {}, 1),
    ('clash-multiline', '        case "state",\n             "micmute": break', {}, 1),
    ('clash-comment-between', '        case "state", /* 舊的 */ "micmute": break', {}, 1),
    ('clash-where', '        case "state", "micmute" where args.count > 1: break', {}, 1),
    ('clash-if-compare', '        case "state":\n            if name == "micmute" { break }', {}, 1),
    ('clash-unknown-pattern', '        case let x where x.hasPrefix("mic"): break', {}, 1),
    # REV-HK-2 P2-2：where 裡的閉包、三元運算不能讓掃描提早結束（Codex 的兩個反例在前兩個）
    ('clash-where-closure-ternary', '        case "state" where [true].contains { $0 ? true : false }: break\n        case "micmute": break', {}, 1),
    ('clash-where-iife-ternary', '        case "state" where { true ? true : false }(): break\n        case "micmute": break', {}, 1),
    ('clash-where-nested-closure', '        case "state" where [[1]].contains { $0.contains { $0 > 0 } }: break\n        case "micmute": break', {}, 1),
    ('clash-where-interpolation', '        case "state" where "\\(args.count > 1 ? 1 : 0)" == "1": break\n        case "micmute": break', {}, 1),
    ('clash-where-ternary-bare', '        case "state" where args.count > 1 ? true : false: break\n        case "micmute": break', {}, 1),
    ('clash-after-body-closure', '        case "state":\n            let f = { (x: Bool) -> Int in x ? 1 : 0 }\n            _ = f(true)\n        case "micmute": break', {}, 1),
    ('where-optional-chaining', '        case "state" where args.first?.isEmpty == false: break', {}, 1),
    ('switch-end-midline', '        case "state": break', {'handler': '        case "micmute":\n            switch args[0] { case "micmute": break; default: break }'}, 1),
    ('body-ternary-ok', '        case "state":\n            let x = args.count > 1 ? 1 : 0\n            _ = x', {}, 0),
    ('body-closure-ok', '        case "state":\n            let f = { (x: Bool) -> Int in x ? 1 : 0 }\n            _ = f(true)\n        case "info": break', {}, 0),
    ('where-dict-ok', '        case "state" where ["a": 1]["a"] == 1: break', {}, 0),
    ('fork-compact-ok', '        case "state": break',
     {'handler': '        case "micmute","tagui": break', 'commands': ('micmute', 'tagui')}, 0),
    ('fork-spaced-unlisted', '        case "state": break', {'handler': '        case "micmute", "state": break'}, 1),
    ('fork-compact-unlisted', '        case "state": break', {'handler': '        case "micmute","state": break'}, 1),
    ('fork-multiline-unlisted', '        case "state": break', {'handler': '        case "micmute",\n             "state": break'}, 1),
    ('fork-unknown-pattern', '        case "state": break', {'handler': '        case "micmute": break\n        case let x where x.hasPrefix("ma"): break'}, 1),
]

CASES = [
    ('clean', scenario_clean, 0),
    ('new-fork-file', scenario_new_fork_file, 0),
    ('marked-hook', scenario_marked_hook, 0),
    ('unmarked-edit', scenario_unmarked_edit, 1),
    ('staged-rename', scenario_staged_rename, 1),
    ('committed-rename', scenario_committed_rename, 1),
    ('rename-and-edit', scenario_rename_and_edit, 1),
    ('delete', scenario_delete, 1),
    ('type-change-symlink', scenario_type_change, 1),
    ('script-rename', scenario_script_rename, 1),
]


def main():
    failures = 0
    with tempfile.TemporaryDirectory(prefix='isolation-check-test-') as root:
        base = make_base(root)
        for name, setup, expected in CASES:
            repo = os.path.join(root, name)
            shutil.copytree(base, repo, symlinks=True)
            setup(repo)
            status = git(repo, 'status', '--porcelain').strip().replace('\n', '; ')
            code, out = run(repo)
            ok = code == expected
            failures += not ok
            print(f'{"ok  " if ok else "FAIL"} {name:<22} exit {code}（預期 {expected}）  git status: {status or "（乾淨）"}')
            if VERBOSE or not ok:
                problems = [l for l in out.splitlines() if l.startswith('  - ')]
                for line in problems or out.splitlines()[-3:]:
                    print('       ' + line)
        for name, upstream, extra, expected in DEBUG_CASES:
            repo = debug_repo(root, name, upstream, **extra)
            code, out = run(repo)
            ok = code == expected
            failures += not ok
            print(f'{"ok  " if ok else "FAIL"} {name:<22} exit {code}（預期 {expected}）')
            if VERBOSE or not ok:
                problems = [l for l in out.splitlines() if l.startswith('  - ')]
                for line in problems or out.splitlines()[-3:]:
                    print('       ' + line)
    total = len(CASES) + len(DEBUG_CASES)
    print(f'\n{total - failures}/{total} 通過')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
