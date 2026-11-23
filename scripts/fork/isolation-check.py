#!/usr/bin/env python3
"""fork 功能隔離的檢查（fork design §F0.2、§F0.3）。

上游檔（上游 tag 裡就有的檔）裡 fork 改動的每一行都要是接點：
  - 加的每一行同一行要有 `MA-FORK(F#)`（Swift `// MA-FORK(F#)`、腳本 `# MA-FORK(F#)`）；接點的範圍就是那一行。
  - 拿掉或改掉上游的行，同一個 hunk 裡一定要有加上的接點行（換成接點）；只刪不加的 hunk 不行。
  - 上游的程式（Sources/**/*.swift、Package.swift）加的行數合計不超過 manifest 的 rules.upstreamLineBudget。
manifest.json 列的 fork 檔要存在、符號要找得到宣告、markers 要跟程式裡實際的接點一致（多的、少的都算錯）。

用法：
  python3 scripts/fork/isolation-check.py            # 檢查（exit 1 表示有問題）
  python3 scripts/fork/isolation-check.py --write    # 照程式裡實際的接點重寫 manifest 的 markers、upstreamFiles（行號）
  python3 scripts/fork/isolation-check.py --base <ref>   # 預設 refs/upstream-tags/<manifest upstream.base.tag>
  python3 scripts/fork/isolation-check.py --root <repo>  # 檢查別的 repo（isolation-check-test.py 的測試資料用）
上游的檔被搬走、改名、換類型（例如換成連結）都算拿掉：比對一律 --no-renames（改名變成刪舊的、加新的），
另外直接核對基準裡每個在檢查範圍的上游檔現在還在、還是一般檔。
"""
import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
MANIFEST = os.path.join(ROOT, 'docs', 'fork', 'manifest.json')
MARKER = re.compile(r'MA-FORK\((F[0-9]+|DF[0-9]+)\)')
# 上游的程式：算行數、一定要全部是接點
CODE = re.compile(r'^(Sources/.*\.swift|Package\.swift)$')
# 上游的腳本：一定要全部是接點，不算進程式的行數
SCRIPTS = re.compile(r'^scripts/[^/]+\.(sh|swift)$|^scripts/dev/[^/]+\.(sh|swift)$')
# 不檢查的上游檔（理由寫在 fork design §F0.3）：文件、翻譯表、圖示、Info.plist 由 brand.py 管；CLAUDE.md、README 是說明
SKIP_NOTE = '文件、README、CLAUDE.md、翻譯表、Info.plist、圖示、.github 不在檢查範圍（fork design §F0.3）'


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def upstream_files(base):
    return set(git('ls-tree', '-r', '--name-only', base).splitlines())


def changed_files(base):
    # 跟工作目錄比（還沒 commit、已 stage 的改動也算），不含新增的檔（新增的檔都是 fork 自己的）。
    # --no-renames：改名一定變成 D（舊路徑）＋ A，舊路徑才會被檢查；T 是換了類型（一般檔換成連結）
    out = git('diff', '--name-only', '--no-renames', '--diff-filter=MDT', base, '--')
    return [p for p in out.splitlines() if p]


def hunks(base, path):
    """回傳 [(上游的開始行, [(kind, 行號, 內容)])]；kind 是 + 或 -，+ 的行號是現在的檔的行號"""
    out = git('diff', '-U0', '--no-color', '--no-renames', base, '--', path)
    result, cur, new_line = [], None, 0
    for line in out.splitlines():
        m = re.match(r'^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
        if m:
            cur = (int(m.group(1)), [])
            result.append(cur)
            new_line = int(m.group(2))
            continue
        if cur is None or line.startswith(('+++', '---', '\\')):
            continue
        if line.startswith('+'):
            cur[1].append(('+', new_line, line[1:]))
            new_line += 1
        elif line.startswith('-'):
            cur[1].append(('-', None, line[1:]))
    return result


def hook_code(text):
    """接點那一行去掉行尾的接點註解，manifest 用來對照"""
    m = MARKER.search(text)
    code = text[:m.start()] if m else text
    code = re.sub(r'\s*(//|#)\s*(l10n-skip\s*)?$', '', code.rstrip()).strip()
    return code


def analyze(base):
    up = upstream_files(base)
    report, problems, markers = [], [], []
    # 不靠 diff 的偵測：基準裡在檢查範圍的上游檔，每個都要還在、還是一般檔
    gone = set()
    for path in sorted(up):
        if not (CODE.match(path) or SCRIPTS.match(path)):
            continue
        full = os.path.join(ROOT, path)
        if os.path.islink(full) or (os.path.exists(full) and not os.path.isfile(full)):
            problems.append(f'{path}：上游的檔換了類型（不是一般檔了）')
            gone.add(path)
        elif not os.path.exists(full):
            problems.append(f'{path}：上游的檔被刪掉、搬走或改名了')
            gone.add(path)
    for path in sorted(changed_files(base)):
        if path not in up or path in gone:
            continue
        is_code, is_script = bool(CODE.match(path)), bool(SCRIPTS.match(path))
        if not (is_code or is_script):
            continue
        added = deleted = 0
        features = {}
        for start, lines in hunks(base, path):
            plus = [l for l in lines if l[0] == '+']
            minus = [l for l in lines if l[0] == '-']
            added += len(plus)
            deleted += len(minus)
            marked = [l for l in plus if MARKER.search(l[2])]
            for _, n, text in plus:
                m = MARKER.search(text)
                if not m:
                    problems.append(f'{path}:{n}：加的這一行沒有 MA-FORK 標記：{text.strip()[:100]}')
                    continue
                features[m.group(1)] = features.get(m.group(1), 0) + 1
                markers.append({'feature': m.group(1), 'file': path, 'line': n, 'hook': hook_code(text)})
            if minus and not marked:
                problems.append(f'{path}（上游第 {start} 行起）：拿掉、改掉了上游的 {len(minus)} 行，同一處沒有接點：{minus[0][2].strip()[:80]}')
        report.append({'file': path, 'kind': 'code' if is_code else 'script', 'added': added, 'deleted': deleted, 'features': features})
    return report, problems, markers


def declared(symbol, files):
    """符號的宣告找得到（`Type.member` 只看最後一段）"""
    name = re.escape(symbol.split('.')[-1])
    pattern = re.compile(rf'\b(func|var|let|struct|enum|class|protocol|case|typealias|extension)\s+{name}\b|\bstatic\s+(let|var|func)\s+{name}\b')
    for path in files:
        try:
            if pattern.search(open(os.path.join(ROOT, path), encoding='utf-8').read()):
                return True
        except (FileNotFoundError, IsADirectoryError, UnicodeDecodeError):
            continue
    return False


def all_sources():
    out = git('ls-files', 'Sources')
    files = [p for p in out.splitlines() if p.endswith('.swift')]
    # 還沒 add 的新檔也算
    for dirpath, _, names in os.walk(os.path.join(ROOT, 'Sources', 'Shiyin', 'Fork')):
        for n in names:
            if n.endswith('.swift'):
                rel = os.path.relpath(os.path.join(dirpath, n), ROOT)
                if rel not in files:
                    files.append(rel)
    return files


def swift_tokens(text):
    """Swift 的詞彙切分（夠 check_debug_commands 用）：跳過 // 和可巢狀的 /* */ 註解；字串（一般、\"\"\"、#\"…\"#）
    整個當一個 token，值是 None 表示有插值或跳脫字元（不是單純的字面值）。回傳 [(種類, 值, 行號)]，種類是 str、id、p（符號）"""
    toks, i, n, line = [], 0, len(text), 1
    while i < n:
        c = text[i]
        if c == '\n':
            line += 1
            i += 1
        elif c.isspace():
            i += 1
        elif text.startswith('//', i):
            j = text.find('\n', i)
            i = n if j < 0 else j
        elif text.startswith('/*', i):
            depth, j = 1, i + 2
            while j < n and depth:
                if text.startswith('/*', j):
                    depth, j = depth + 1, j + 2
                elif text.startswith('*/', j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            line += text.count('\n', i, j)
            i = j
        elif c == '"' or (c == '#' and re.match(r'#+"', text[i:])):
            start = i
            hashes = len(re.match(r'#*', text[i:]).group(0))
            i += hashes
            multi = text.startswith('"""', i)
            quote = '"""' if multi else '"'
            i += len(quote)
            close = quote + '#' * hashes
            esc = '\\' + '#' * hashes
            plain, body = True, []
            while i < n and not text.startswith(close, i):
                if text.startswith(esc, i):
                    plain = False
                    i += len(esc)
                    if i < n and text[i] == '(':   # 插值：跳過對應的括號（裡面可能有字串）
                        depth, i = 1, i + 1
                        while i < n and depth:
                            if text[i] == '"':
                                j = i + 1
                                while j < n and text[j] != '"':
                                    j += 2 if text[j] == '\\' else 1
                                i = j + 1
                                continue
                            depth += {'(': 1, ')': -1}.get(text[i], 0)
                            i += 1
                    else:
                        i += 1
                elif text[i] == '\n' and not multi:
                    break   # 沒有收尾的字串：當成不是字面值
                else:
                    body.append(text[i])
                    i += 1
            i += len(close)
            line_at = line
            line += text.count('\n', start, i)
            toks.append(('str', ''.join(body) if plain and not multi else None, line_at))
        elif c.isalpha() or c == '_':
            m = re.match(r'[A-Za-z_][A-Za-z0-9_]*', text[i:])
            toks.append(('id', m.group(0), line))
            i += len(m.group(0))
        elif c.isdigit():
            m = re.match(r'[0-9][0-9A-Za-z_.]*', text[i:])
            toks.append(('num', m.group(0), line))
            i += len(m.group(0))
        elif text.startswith('==', i):
            toks.append(('p', '==', line))
            i += 2
        else:
            toks.append(('p', c, line))
            i += 1
    return toks


# 指令名稱所在的運算式：`switch name {`、`switch args[0] {`、`switch args.first {`、`name == "x"`、`args[0] == "x"`
SUBJECTS = [[('id', 'name')], [('id', 'args'), ('p', '['), ('num', '0'), ('p', ']')], [('id', 'args'), ('p', '.'), ('id', 'first')]]
# `case` 前面是這些時，是條件裡的 `if case`、`guard case`、`for case`，不是 switch 的標籤
NOT_LABEL = {'if', 'guard', 'while', 'for', ',', '&&', '||'}


def command_names(path, text):
    """fork design §F0.7：從一個 Swift 檔找出當成 DEBUG 指令名稱比對的字面值。
    - 主旨是 SUBJECTS 的 switch，最外層每個 case 的 pattern（逗號分隔、可跨行、有沒有空白都一樣）
    - SUBJECTS == "字面值"、"字面值" == SUBJECTS（檔裡任何地方）
    最外層的 pattern 只接受字串字面值（可以帶 where，字面值照樣算，寧可多算）；其他寫法（let、運算式、有插值的字串）
    回報成問題要人工核對，不默默少算。回傳 (名稱集合, 問題清單)"""
    toks = swift_tokens(text)
    names, problems = set(), []
    rel = os.path.relpath(path, ROOT)

    def at(i, seq):
        return [(k, v) for k, v, _ in toks[i:i + len(seq)]] == seq

    def subject_len(i):
        for seq in SUBJECTS:
            if at(i, seq):
                return len(seq)
        return 0

    for i, (kind, val, ln) in enumerate(toks):
        if kind == 'p' and val == '==':
            left = next((len(s) for s in SUBJECTS if i >= len(s) and at(i - len(s), s)), 0)
            if left and i + 1 < len(toks) and toks[i + 1][0] == 'str':
                if toks[i + 1][1] is None:
                    problems.append(f'{rel}:{ln}：指令名稱跟不是單純字面值的字串比對，要人工核對（fork design §F0.7）')
                else:
                    names.add(toks[i + 1][1])
            elif i > 0 and toks[i - 1][0] == 'str' and subject_len(i + 1):
                if toks[i - 1][1] is None:
                    problems.append(f'{rel}:{ln}：指令名稱跟不是單純字面值的字串比對，要人工核對（fork design §F0.7）')
                else:
                    names.add(toks[i - 1][1])
        if not (kind == 'id' and val == 'switch'):
            continue
        k = subject_len(i + 1)
        if not k or not at(i + 1 + k, [('p', '{')]):
            continue
        # switch 的本體：大括號深度 1 的 case 是最外層的標籤
        j, depth = i + 2 + k, 1
        while j < len(toks) and depth:
            kind2, val2, ln2 = toks[j]
            if kind2 == 'p' and val2 in '{}':
                depth += 1 if val2 == '{' else -1
                j += 1
                continue
            if depth == 1 and kind2 == 'id' and val2 == 'case' and not (j > 0 and toks[j - 1][1] in NOT_LABEL):
                # 收到同一層的冒號為止（括號、中括號裡的冒號不算）
                items, cur, paren, j = [], [], 0, j + 1
                while j < len(toks):
                    t = toks[j]
                    if t[0] == 'p' and t[1] in '([':
                        paren += 1
                    elif t[0] == 'p' and t[1] in ')]':
                        paren -= 1
                    elif t[0] == 'p' and t[1] in ':,' and paren == 0:
                        items.append(cur)
                        cur = []
                        if t[1] == ':':
                            break
                        j += 1
                        continue
                    cur.append(t)
                    j += 1
                for item in items:
                    ok = item and item[0][0] == 'str' and item[0][1] is not None and (len(item) == 1 or item[1][1] == 'where')
                    if ok:
                        names.add(item[0][1])
                    else:
                        shown = ' '.join('"…"' if t[0] == 'str' else t[1] for t in item)[:60]
                        problems.append(f'{rel}:{ln2}：DEBUG 指令 switch 最外層的 case 不是字串字面值（{shown}），看不出會不會撞名，要人工核對（fork design §F0.7）')
                j += 1
                continue
            j += 1
    return names, problems


def check_debug_commands(manifest):
    """fork design §F0.7：ForkDebug.intercept 在上游 switch 之前接 fork 的指令，名稱不能跟上游撞（shadowed 除外）。
    上游 DebugControl、fork 的 *Debug.swift 用同一套規則（command_names）收集指令名稱。
    沒有 ForkDebug.swift 的 repo（isolation-check-test 的小 repo）不檢查"""
    fork_debug = os.path.join(ROOT, 'Sources', 'Shiyin', 'Fork', 'Debug', 'ForkDebug.swift')
    upstream = os.path.join(ROOT, 'Sources', 'Shiyin', 'Debug', 'DebugControl.swift')
    if not (os.path.isfile(fork_debug) and os.path.isfile(upstream)):
        return []
    problems = []
    src = open(fork_debug, encoding='utf-8').read()

    def literal(name):
        m = re.search(r'static let ' + name + r': Set<String> = \[(.*?)\]', src, re.S)
        if not m:
            return None
        toks = swift_tokens(m.group(1))
        if any(t[0] == 'str' and t[1] is None for t in toks) or any(t[0] not in ('str',) and t[1] != ',' for t in toks):
            return None
        return {t[1] for t in toks if t[0] == 'str'}

    commands, shadowed = literal('commands'), literal('shadowed')
    if commands is None or shadowed is None:
        return ['ForkDebug.swift 找不到 commands 或 shadowed 的清單，或清單裡不是單純的字串字面值（fork design §F0.7）']
    # manifest 的 debugCommands：單字的才是 fork 自己的頂層指令；多字的（「hotkey mute」）是上游指令的子指令，
    # 第一個字（hotkey）是 intercept 會比對、但交給上游的名稱
    all_listed = [c for f in manifest['features'].values() for c in (f.get('debugCommands') or [])]
    listed = {c for c in all_listed if ' ' not in c}
    sub_parents = {c.split()[0] for c in all_listed if ' ' in c}
    if listed != commands:
        problems.append(f'ForkDebug.commands 跟 manifest 的 debugCommands 不同：只在程式 {sorted(commands - listed)}、只在 manifest {sorted(listed - commands)}')
    found = set()
    for dirpath, _, files in os.walk(os.path.join(ROOT, 'Sources', 'Shiyin', 'Fork')):
        for name in sorted(files):
            if name.endswith('Debug.swift'):
                path = os.path.join(dirpath, name)
                got, bad = command_names(path, open(path, encoding='utf-8').read())
                found |= got
                problems += bad
    if found - sub_parents != commands:
        problems.append(f'ForkDebug.commands 跟 Fork/*Debug.swift 比對的指令不同：只在清單 {sorted(commands - found)}、只在程式 {sorted(found - sub_parents - commands)}')
    # fork 的接點行（intercept）不算上游的指令；換成空行，行號照舊
    up_lines = ['' if 'MA-FORK' in l else l for l in open(upstream, encoding='utf-8').read().splitlines()]
    up_cases, bad = command_names(upstream, '\n'.join(up_lines))
    problems += bad
    if not up_cases:
        problems.append('上游 DebugControl 找不到 DEBUG 指令的 switch（switch name／args[0]／args.first），看不出會不會撞名（fork design §F0.7）')
    clash = (commands & up_cases) - shadowed
    if clash:
        problems.append(f'fork 的 DEBUG 指令跟上游 DebugControl 同名（會被 ForkDebug.intercept 先接走）：{sorted(clash)}')
    missing = shadowed - up_cases
    if missing:
        problems.append(f'ForkDebug.shadowed 列的指令上游已經沒有了：{sorted(missing)}（拿掉或改回一般指令）')
    lost = sub_parents - up_cases
    if lost:
        problems.append(f'manifest 的子指令（例如 hotkey mute）所屬的上游指令已經沒有了：{sorted(lost)}')
    return problems


def check_manifest(manifest, markers):
    problems, warnings = [], []
    feats = manifest['features']
    sources = all_sources()
    for fid, f in feats.items():
        for path in f.get('forkFiles', []):
            if not os.path.exists(os.path.join(ROOT, path)):
                problems.append(f'manifest {fid}.forkFiles：{path} 不存在')
        for sym in f.get('symbols', []):
            if not declared(sym, sources):
                problems.append(f'manifest {fid}.symbols：找不到 {sym} 的宣告')
        for path in f.get('upstreamFiles', []):
            if not os.path.exists(os.path.join(ROOT, path)):
                problems.append(f'manifest {fid}.upstreamFiles：{path} 不存在')
    actual = {(m['feature'], m['file'], m['hook']): m['line'] for m in markers}
    listed = {}
    for fid, f in feats.items():
        for m in f.get('markers', []):
            listed[(fid, m['file'], m['hook'])] = m.get('line')
    for key in sorted(set(actual) - set(listed)):
        problems.append(f'程式裡有、manifest 沒列的接點：{key[0]} {key[1]}:{actual[key]} {key[2][:80]}')
    for key in sorted(set(listed) - set(actual)):
        problems.append(f'manifest 列了、程式裡找不到的接點：{key[0]} {key[1]} {key[2][:80]}')
    for key in sorted(set(listed) & set(actual)):
        if listed[key] != actual[key]:
            warnings.append(f'行號變了（--write 更新）：{key[0]} {key[1]} {listed[key]} → {actual[key]}')
    unknown = sorted({m['feature'] for m in markers} - set(feats))
    for fid in unknown:
        problems.append(f'接點標的功能 {fid} 不在 manifest 的 features')
    return problems, warnings


def write_manifest(manifest, markers):
    feats = manifest['features']
    for fid, f in feats.items():
        mine = [m for m in markers if m['feature'] == fid]
        if mine or 'markers' in f:
            f['markers'] = [{'file': m['file'], 'line': m['line'], 'hook': m['hook']} for m in mine]
        files = sorted({m['file'] for m in mine})
        if files:
            # 上游檔：有接點的檔（另外列的資源檔照留）
            others = [p for p in f.get('upstreamFiles', []) if not (CODE.match(p) or SCRIPTS.match(p))]
            f['upstreamFiles'] = files + others
    with open(MANIFEST, 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write('\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base')
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--root')
    args = ap.parse_args()
    if args.root:
        global ROOT, MANIFEST
        ROOT = os.path.abspath(args.root)
        MANIFEST = os.path.join(ROOT, 'docs', 'fork', 'manifest.json')
    manifest = json.load(open(MANIFEST, encoding='utf-8'))
    base = args.base or f"refs/upstream-tags/{manifest['upstream']['base']['tag']}"
    budget = manifest['rules'].get('upstreamLineBudget', 100)
    report, problems, markers = analyze(base)
    if args.write:
        write_manifest(manifest, markers)
        manifest = json.load(open(MANIFEST, encoding='utf-8'))
    mproblems, warnings = check_manifest(manifest, markers)
    problems += mproblems
    problems += check_debug_commands(manifest)

    print(f'基準：{base}')
    print(f'{"上游檔":<48} {"種類":<6} {"加":>4} {"減":>4}  接點（依功能）')
    code_total = 0
    for r in report:
        feats = '、'.join(f'{k} {v}' for k, v in sorted(r['features'].items()))
        print(f'{r["file"]:<48} {r["kind"]:<6} {r["added"]:>4} {r["deleted"]:>4}  {feats}')
        if r['kind'] == 'code':
            code_total += r['added']
    script_total = sum(r['added'] for r in report if r['kind'] == 'script')
    print(f'上游程式裡 fork 的行數：{code_total}（上限 {budget}）；上游腳本：{script_total}')
    print(f'接點：{len(markers)} 個；{SKIP_NOTE}')
    if code_total > budget:
        problems.append(f'上游程式裡 fork 的行數 {code_total} 超過上限 {budget}')
    for w in warnings:
        print('注意：' + w)
    if problems:
        print(f'\n有 {len(problems)} 個問題：')
        for p in problems:
            print('  - ' + p)
        sys.exit(1)
    print('PASS：上游檔裡 fork 的改動都在 MA-FORK 接點上，manifest 的檔、符號、接點都對得上')


if __name__ == '__main__':
    main()
