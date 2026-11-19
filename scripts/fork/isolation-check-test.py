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
    print(f'\n{len(CASES) - failures}/{len(CASES)} 通過')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
