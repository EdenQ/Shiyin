#!/usr/bin/env python3
"""上游監看（fork design §F0.5；PLAN-fork-5.0 §8.2、階段 3b）：機械式比對上游的新東西會不會跟 fork 衝突、撞名，
有沒有做了跟 fork 相似的功能。只篩選、不判斷；報告只放 GitHub Actions 的 artifact（不開 Issue）。

用法：
  upstream-watch.py [--repo <repo>] [--fork <ref>] [--head <ref>] [--base <ref>] [--merge-base <ref>]
                    [--state <state.json>] [--update-state] [--out-md <檔>] [--out-json <檔>] [--date YYYY-MM-DD]
  預設：--fork main（沒有 main 時 HEAD）、--head upstream/main；base：--base > 狀態檔的 upstreamMain > merge-base(fork, head)
  重播 5.0：--fork v4.7.6 --merge-base 78ceab8 --base 78ceab8 --head refs/upstream-tags/v5.0.0
exit：0 沒有新東西；1 有新東西；2 工具錯誤（失敗一律 2，不能被當成「沒有變化」）
只用 Python 標準函式庫和 git。報告只放兩個公開 repo 的程式碼、文件內容，不放本機路徑。
"""
import argparse
import datetime
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
SCRIPT_ROOT = HERE.parents[2]
# 相似度門檻：中文雙字組＋英文單字的 Jaccard。PLAN 先定 0.2，用 78ceab8..v5.0.0 校正（2026-11-20，IMPL-3b-watch）：
# 上游 57 個新章節 × fork 的 F 段落，最高的五對是 R81 錄音島／F3（0.118）、R75 錄不到電腦聲音／F3（0.118）、
# R92 依人物整理的重點／F4（0.088）、R101 收合／F4（0.086）、R74 裝置一直在變／F3（0.082），都是 5.0 合併時真的要處理的
# （錄音島要顯示靜音、R75 的收音檢查接點、條列頁、DF5）；第六名 0.079 起開始混進不相干的。0.2 一對都抓不到，所以定 0.08。
# 另外「同一節命中同一個功能的關鍵字 ≥ 2 個」也列，兩者其一就是可能相似。
SIMILARITY_THRESHOLD = 0.08
KEYWORD_HITS = 2
CONFLICT_CONTEXT = 20   # 衝突處前後幾行找 MA-FORK 標記
HOOK_NEAR = 3           # 上游 hunk 離 fork 接點的錨點幾行內算「改到接點」
MARKER = re.compile(r'MA-FORK\((F\d+|DF\d+)\)')
VERSION_TAG = re.compile(r'^v(\d+)\.(\d+)\.(\d+)$')


class ToolError(Exception):
    pass


# ---------------------------------------------------------------- git
class Git:
    def __init__(self, repo):
        self.repo = str(repo)

    def run(self, *args, ok=(0,)):
        p = subprocess.run(['git', '-C', self.repo, *args], capture_output=True, text=True, errors='replace')
        if p.returncode not in ok:
            raise ToolError(f'git {" ".join(args[:4])} … exit {p.returncode}：{p.stderr.strip()[:300]}')
        return p.returncode, p.stdout

    def out(self, *args):
        return self.run(*args)[1]

    def rev(self, ref):
        code, out = self.run('rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}', ok=(0, 1))
        return out.strip() if code == 0 else None

    def exists(self, sha):
        return self.run('cat-file', '-e', f'{sha}^{{commit}}', ok=(0, 1, 128))[0] == 0

    def is_ancestor(self, a, b):
        code, _ = self.run('merge-base', '--is-ancestor', a, b, ok=(0, 1))
        return code == 0

    def show(self, ref, path):
        code, out = self.run('show', f'{ref}:{path}', ok=(0, 128))
        return out if code == 0 else None


# ---------------------------------------------------------------- diff 解析
HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


def parse_diff(text):
    """git diff -U0 → {path: [{'old': (a, n), 'new': (c, m), 'added': [(行號, 內容)], 'header': …}]}"""
    files, cur, hunk = {}, None, None
    for line in text.splitlines():
        if line.startswith('diff --git '):
            cur, hunk = None, None
        elif line.startswith('+++ '):
            path = line[4:]
            cur = None if path == '/dev/null' else path[2:] if path.startswith('b/') else path
            if cur is not None:
                files.setdefault(cur, [])
        elif line.startswith('--- '):
            continue
        elif cur is not None and (m := HUNK.match(line)):
            a, n, c, k = int(m[1]), int(m[2] or 1), int(m[3]), int(m[4] or 1)
            hunk = {'old': (a, n), 'new': (c, k), 'added': [], 'header': line.split('@@')[1].strip(), 'next': c}
            files[cur].append(hunk)
        elif hunk is not None and line.startswith('+'):
            hunk['added'].append((hunk['next'], line[1:]))
            hunk['next'] += 1
    return files


def old_span(h):
    a, n = h['old']
    return (a, a + max(n, 1) - 1) if n > 0 else (a, a + 1)   # 純插入：插在 a 之後


# ---------------------------------------------------------------- 1. 新東西
def upstream_tags(git, head):
    """refs/upstream-tags/v*（不看 win-v*）：名稱 → (commit, 說明, 在不在 head 的歷史裡)"""
    fmt = '%(refname:strip=2)%1f%(objectname)%1f%(*objectname)%1f%(contents)%1e'
    tags = {}
    for rec in git.out('for-each-ref', f'--format={fmt}', 'refs/upstream-tags/').split('\x1e'):
        rec = rec.strip('\n')
        if not rec:
            continue
        name, obj, peeled, contents = (rec.split('\x1f') + ['', '', '', ''])[:4]
        if name.startswith('win-'):
            continue
        tags[name] = {'commit': peeled or obj, 'message': contents.strip()}
    return tags


def version_key(name):
    m = VERSION_TAG.match(name)
    return tuple(map(int, m.groups())) if m else None


def section_new(git, a):
    tags = upstream_tags(git, a.head_sha)
    state = a.state_data or {}
    rewritten, moved = None, []
    old_main = state.get('upstreamMain')
    if old_main and not a.explicit_base:
        if not git.exists(old_main) or not git.is_ancestor(old_main, a.head_sha):
            rewritten = old_main
    for name, t in tags.items():
        old = state.get('tags', {}).get(name)
        if old and old != t['commit']:
            moved.append({'tag': name, 'old': old[:10], 'new': t['commit'][:10]})
    new_tags = []
    for name, t in sorted(tags.items(), key=lambda kv: version_key(kv[0]) or (0,)):
        if state.get('tags') is not None and not a.explicit_base:
            is_new = name not in state['tags']
        else:
            is_new = git.is_ancestor(t['commit'], a.head_sha) and not git.is_ancestor(t['commit'], a.base_sha)
        if is_new:
            new_tags.append({'tag': name, 'commit': t['commit'][:10], 'message': t['message'][:2000]})
    commits = []
    for line in git.out('log', '--format=%h%x1f%s', f'{a.base_sha}..{a.head_sha}').splitlines():
        h, _, s = line.partition('\x1f')
        commits.append({'commit': h, 'subject': s})
    reachable = [n for n, t in tags.items() if version_key(n) and git.is_ancestor(t['commit'], a.head_sha)]
    version = max(reachable, key=version_key) if reachable else None
    return {'newTags': new_tags, 'movedTags': moved, 'rewritten': rewritten, 'commits': commits,
            'version': version, 'tags': {n: t['commit'] for n, t in tags.items()}}


# ---------------------------------------------------------------- 2. 試合併
def section_conflicts(git, a, manifest):
    by_file = {}
    for fid, f in manifest['features'].items():
        for path in {m['file'] for m in f.get('markers', [])} | set(f.get('upstreamFiles', [])):
            by_file.setdefault(path, []).append(fid)
    args = ['merge-tree', '--write-tree', '--name-only']
    if a.merge_base_sha:
        args.append(f'--merge-base={a.merge_base_sha}')
    code, out = git.run(*args, a.fork_sha, a.head_sha, ok=(0, 1))
    lines = out.split('\n')
    tree = lines[0].strip()
    files = []
    if code == 1:
        for line in lines[1:]:
            if not line.strip():
                break
            if line not in files:
                files.append(line)
    result = []
    for path in files:
        content = git.show(tree, path)
        blocks, features = 0, {}
        if content is None:   # 一邊刪掉、一邊改：整個檔一處
            blocks = 1
            for f in [f'{fid}（依檔）' for fid in by_file.get(path, [])] or ['品牌／其他']:
                features[f] = features.get(f, 0) + 1
        else:
            text = content.split('\n')
            starts = [i for i, l in enumerate(text) if l.startswith('<<<<<<<')]
            blocks = len(starts) or 1
            for s in starts or [0]:
                e = next((j for j in range(s, len(text)) if text[j].startswith('>>>>>>>')), s)
                window = text[max(0, s - CONFLICT_CONTEXT): e + CONFLICT_CONTEXT + 1]
                found = sorted({m for l in window for m in MARKER.findall(l)})
                # 附近沒有標記：manifest 裡把這個檔列為接點或上游檔的功能（標「依檔」）；都沒有才是品牌／其他
                found = found or [f'{fid}（依檔）' for fid in by_file.get(path, [])] or ['品牌／其他']
                for f in found:
                    features[f] = features.get(f, 0) + 1
        result.append({'file': path, 'blocks': blocks, 'features': features})
    return {'tree': tree, 'clean': code == 0, 'files': result}


# ---------------------------------------------------------------- 3. 改到接點
def section_hooks(git, a, manifest, conflict_files):
    hook_files = sorted({m['file'] for f in manifest['features'].values() for m in f.get('markers', [])})
    up = parse_diff(git.out('diff', '-U0', '--no-renames', a.merge_base_sha, a.head_sha, '--', *hook_files)) if hook_files else {}
    found = []
    for path in hook_files:
        if path in conflict_files or path not in up:
            continue
        fork = parse_diff(git.out('diff', '-U0', '--no-renames', a.merge_base_sha, a.fork_sha, '--', path)).get(path, [])
        anchors = []
        for h in fork:
            feats = sorted({m for _, l in h['added'] for m in MARKER.findall(l)})
            if feats:
                lo, hi = old_span(h)
                anchors.append((lo - HOOK_NEAR, hi + HOOK_NEAR, feats, next(l for _, l in h['added'] if MARKER.search(l)).strip()))
        for h in up[path]:
            lo, hi = old_span(h)
            for alo, ahi, feats, hook in anchors:
                if lo <= ahi and hi >= alo:
                    sample = next((l.strip() for _, l in h['added'] if l.strip()), '')
                    found.append({'file': path, 'hunk': h['header'], 'features': feats, 'hook': hook[:160], 'upstream': sample[:160]})
                    break
    return found


# ---------------------------------------------------------------- 4、5、8. 新增的名稱、SQL
SETTINGS_PATTERNS = [re.compile(r'forKey:\s*"([^"]+)"'), re.compile(r'\b\w*[Kk]ey\s*=\s*"([^"]+)"'),
                     re.compile(r'@AppStorage\(\s*"([^"]+)"')]
CASE_LINE = re.compile(r'^\s*case\s+((?:"[^"]+"\s*,?\s*)+):')
MIGRATION = re.compile(r'registerMigration\(\s*"([^"]+)"')
CREATE_TABLE = re.compile(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["`]?(\w+)', re.I)
DECL = re.compile(r'\b(class|struct|enum|actor|protocol|typealias|func|var|let)\s+([A-Za-z_]\w*)')
TYPE_KINDS = {'class', 'struct', 'enum', 'actor', 'protocol', 'typealias'}
PLIST_KEY = re.compile(r'<key>([^<]+)</key>')
MOVE_SQL = [re.compile(r'UPDATE\s+(segments|bookmarks|speakers|meetings)\s+SET\b.*\b(start|end|time|meeting_id)\b', re.I),
            re.compile(r'INSERT\s+(?:OR\s+\w+\s+)?INTO\s+\w+.*\bSELECT\b', re.I)]
SNAPSHOT_FUNC = re.compile(r'\bfunc\s+(\w*(?:[Ss]napshot|[Rr]estore)\w*)')


def added_lines(diff, pred=lambda p: True):
    for path, hunks in diff.items():
        if not pred(path):
            continue
        for h in hunks:
            for no, line in h['added']:
                yield path, no, line


def swift(p):
    return p.endswith('.swift')


def fork_declared(git, fork):
    """fork 在 Sources/Shiyin/Fork/ 宣告的型別，以及加在上游型別 extension 裡的成員（只看大括號深度 1）"""
    types, members = set(), set()
    files = [p for p in git.out('ls-tree', '-r', '--name-only', fork, '--', 'Sources/Shiyin/Fork').splitlines() if swift(p)]
    texts = {p: git.show(fork, p) or '' for p in files}
    for text in texts.values():
        for kind, name in DECL.findall(text):
            if kind in TYPE_KINDS:
                types.add(name)
    for text in texts.values():
        depth, ext = 0, None
        for line in text.split('\n'):
            code = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line.split('//')[0])
            if depth == 0:
                m = re.match(r'\s*(?:@\w+\s+)*(?:public\s+|private\s+|fileprivate\s+)?extension\s+([A-Za-z_][\w.]*)', code)
                ext = m.group(1) if m else None
            elif depth == 1 and ext and ext.split('.')[0] not in types:
                for kind, name in DECL.findall(code):
                    if kind in ('func', 'var', 'let'):
                        members.add(name)
            depth += code.count('{') - code.count('}')
            depth = max(depth, 0)
    return types, members


def upstream_declared(git, ref):
    """ref 的 Sources 裡已經有的宣告名稱（用來排除「改到既有那一行」的假碰撞）"""
    code, out = git.run('grep', '-h', '-o', '-E', r'\b(class|struct|enum|actor|protocol|typealias|func)[[:space:]]+[A-Za-z_][A-Za-z0-9_]*',
                        ref, '--', 'Sources', ok=(0, 1))
    return {l.split()[-1] for l in out.splitlines() if l.strip()}


def xcstrings_keys(git, ref):
    text = git.show(ref, 'Resources/Localizable.xcstrings')
    if not text:
        return set()
    try:
        return set(json.loads(text).get('strings', {}))
    except json.JSONDecodeError as e:
        raise ToolError(f'{ref} 的翻譯表不是 JSON：{e}')


def fork_names(manifest):
    feats = manifest['features']
    rules = manifest.get('rules', {})
    legacy = rules.get('legacyNames', {})
    names = {'settings': {}, 'debug': {}, 'migrations': {}, 'tables': {}, 'infoPlist': {}}

    def add(kind, value, feature):
        names[kind].setdefault(value, feature)
    for fid, f in feats.items():
        for k in f.get('settingsKeys', []):
            add('settings', k, fid)
        for k in f.get('debugCommands', []):
            if ' ' not in k:   # 「hotkey mute」是上游 hotkey 的子指令，不是 fork 自己的名字
                add('debug', k, fid)
        for k in f.get('migrations', []):
            add('migrations', k, fid)
        for k in f.get('tables', []):
            add('tables', k, fid)
        for k in f.get('infoPlistKeys', {}):
            add('infoPlist', k, fid)
    for k in legacy.get('settingsKeys', []):
        add('settings', k, 'legacy')
    for k in legacy.get('debugCommands', []):
        add('debug', k, 'legacy')
    for k in legacy.get('tables', []):
        add('tables', k, 'legacy')
    return names


def section_names(git, a, manifest, diff, status):
    names = fork_names(manifest)
    collisions, new = [], {'settings': set(), 'debug': set(), 'migrations': set(), 'tables': set(), 'infoPlist': set(),
                           'scriptsDev': [], 'symbols': set()}
    for path, no, line in added_lines(diff, swift):
        for pat in SETTINGS_PATTERNS:
            for k in pat.findall(line):
                new['settings'].add(k)
        if path.startswith('Sources/Shiyin/Debug/') and (m := CASE_LINE.match(line)):
            for k in re.findall(r'"([^"]+)"', m.group(1)):
                new['debug'].add(k)
        for k in MIGRATION.findall(line):
            new['migrations'].add(k)
        for k in CREATE_TABLE.findall(line):
            new['tables'].add(k)
        for kind, name in DECL.findall(line):
            if kind in TYPE_KINDS or kind == 'func':
                new['symbols'].add((name, path, no))
    for path, no, line in added_lines(diff, lambda p: p == 'Resources/Info.plist'):
        for k in PLIST_KEY.findall(line):
            new['infoPlist'].add(k)
    prefix_settings = re.compile('^' + re.escape(manifest.get('rules', {}).get('settingsKeyPrefix', 'ma')) + r'[A-Z]')
    table_prefix = manifest.get('rules', {}).get('tablePrefix', 'ma_')
    mig_prefix = manifest.get('rules', {}).get('migrationPrefix', 'ma_')
    for k in sorted(new['settings']):
        if k in names['settings'] or prefix_settings.match(k):
            collisions.append({'kind': '設定鍵', 'name': k, 'feature': names['settings'].get(k, 'ma 命名空間')})
    for k in sorted(new['debug']):
        if k in names['debug']:
            collisions.append({'kind': 'DEBUG 指令', 'name': k, 'feature': names['debug'][k]})
    for k in sorted(new['migrations']):
        if k in names['migrations'] or k.startswith(mig_prefix):
            collisions.append({'kind': 'migration', 'name': k, 'feature': names['migrations'].get(k, 'ma_ 命名空間')})
    for k in sorted(new['tables']):
        if k in names['tables'] or k.startswith(table_prefix):
            collisions.append({'kind': '資料表', 'name': k, 'feature': names['tables'].get(k, 'ma_ 命名空間')})
    for k in sorted(new['infoPlist']):
        if k in names['infoPlist'] or k.startswith('MA'):
            collisions.append({'kind': 'Info.plist 鍵', 'name': k, 'feature': names['infoPlist'].get(k, 'MA 命名空間')})
    # 翻譯表：上游新增的鍵 ∩ fork 自己加的鍵
    up_new = xcstrings_keys(git, a.head_sha) - xcstrings_keys(git, a.base_sha)
    fork_own = xcstrings_keys(git, a.fork_sha) - xcstrings_keys(git, a.merge_base_sha)
    for k in sorted(up_new & fork_own):
        collisions.append({'kind': '翻譯表的鍵', 'name': k[:120], 'feature': 'fork 加的翻譯'})
    # 型別、函式：上游新宣告的名字 = fork 在 Fork/ 宣告的型別或加進上游型別的成員；merge-base 已經有的不算
    types, members = fork_declared(git, a.fork_sha)
    existing = upstream_declared(git, a.merge_base_sha)
    seen = set()
    for name, path, no in sorted(new['symbols']):
        if name in seen or name in existing:
            continue
        if name in types or name in members:
            seen.add(name)
            collisions.append({'kind': '型別／函式', 'name': name, 'feature': 'Fork/ 的宣告', 'where': f'{path}:{no}'})
    for st, path in status:
        if path.startswith('Sources/Shiyin/Fork/'):
            collisions.append({'kind': 'Fork/ 路徑', 'name': path, 'feature': '上游改到 fork 的資料夾'})
    # ⚪ 新的名字（排除 base 已經有的）：用 base 的原始碼核對字面
    def absent_at_base(word):
        code, _ = git.run('grep', '-q', '-F', f'"{word}"', a.base_sha, '--', 'Sources', ok=(0, 1))
        return code == 1
    fresh = {k: sorted(x for x in new[k] if absent_at_base(x)) for k in ('settings', 'debug', 'migrations')}
    fresh['tables'] = sorted(new['tables'])
    fresh['infoPlist'] = sorted(new['infoPlist'])
    fresh['scriptsDev'] = sorted(p for st, p in status if st.startswith('A') and p.startswith('scripts/dev/'))
    return collisions, fresh


def section_sql(git, a, diff):
    existing = upstream_declared(git, a.base_sha)
    found = []
    for path, no, line in added_lines(diff, swift):
        for pat in MOVE_SQL:
            if pat.search(line):
                found.append({'file': path, 'line': no, 'kind': 'SQL', 'text': line.strip()[:200]})
                break
        for name in SNAPSHOT_FUNC.findall(line):
            if name not in existing:
                found.append({'file': path, 'line': no, 'kind': '快照／還原函式', 'text': line.strip()[:200]})
    return found


# ---------------------------------------------------------------- 6. 相似功能
CJK = re.compile(r'[一-鿿]+')
WORD = re.compile(r'[A-Za-z]{3,}')
STOP = {'the', 'and', 'for', 'with', 'that', 'this', 'are', 'not', 'from', 'when', 'into', 'can', 'will', 'all', 'has', 'have',
        'its', 'use', 'used', 'one', 'two', 'any', 'only', 'also', 'more', 'than', 'then', 'each', 'but', 'was', 'were'}


def tokens(text):
    out = set()
    for run in CJK.findall(text):
        out.update(run[i:i + 2] for i in range(len(run) - 1))
    out.update(w.lower() for w in WORD.findall(text) if w.lower() not in STOP)
    return out


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def split_sections(text, levels=('## ', '### ')):
    sections, title, buf = [], None, []
    for line in text.split('\n'):
        if line.startswith(levels):
            if title is not None:
                sections.append((title, '\n'.join(buf)))
            title, buf = line.strip(), []
        elif title is not None:
            buf.append(line)
    if title is not None:
        sections.append((title, '\n'.join(buf)))
    return sections


def fork_sections(text):
    """docs/fork/requirements.md 的 F 段落：`## F#.` 到下一個 `## `"""
    out = []
    for title, body in split_sections(text, ('## ',)):
        m = re.match(r'##\s+(F\d+|DF\d+)\b', title)
        if m:
            out.append({'feature': m.group(1), 'title': title, 'text': body})
    return out


def keyword_hits(text, kws):
    hits = []
    low = text.lower()
    for k in kws.get('zh', []):
        if k in text:
            hits.append(k)
    for k in kws.get('en', []):
        if re.search(r'(?<![A-Za-z])' + re.escape(k.lower()) + r'(?![A-Za-z])', low):
            hits.append(k)
    return hits


def summary_of(text, n=160):
    flat = ' '.join(l.strip() for l in text.split('\n') if l.strip() and not l.startswith('|---'))
    return flat[:n] + ('…' if len(flat) > n else '')


def section_similar(git, a, manifest, diff, fork_req):
    feats = {fid: f.get('watchKeywords') for fid, f in manifest['features'].items() if f.get('watchKeywords')}
    # 新增行命中的關鍵字（程式、翻譯表、docs）
    scan = lambda p: swift(p) or p == 'Resources/Localizable.xcstrings' or (p.startswith('docs/') and not p.startswith('docs/fork/'))
    line_hits = {}
    for path, no, line in added_lines(diff, scan):
        for fid, kws in feats.items():
            hits = keyword_hits(line, kws)
            if hits:
                h = line_hits.setdefault(fid, {'count': 0, 'keywords': {}, 'samples': []})
                h['count'] += 1
                for k in hits:
                    h['keywords'][k] = h['keywords'].get(k, 0) + 1
                if len(h['samples']) < 5:
                    h['samples'].append(f'{path}:{no}：{line.strip()[:120]}')
    # 上游 requirements 新的章節 vs fork 的 F 段落
    head_req = git.show(a.head_sha, 'docs/requirements.md') or ''
    base_req = git.show(a.base_sha, 'docs/requirements.md') or ''
    base_titles = {t for t, _ in split_sections(base_req)}
    new_sections = [(t, b) for t, b in split_sections(head_req) if t not in base_titles]
    fsecs = fork_sections(fork_req)
    candidates, scores = [], []
    for title, body in new_sections:
        up_tokens = tokens(title + '\n' + body)
        for fs in fsecs:
            score = jaccard(up_tokens, tokens(fs['title'] + '\n' + fs['text']))
            hits = keyword_hits(title + '\n' + body, feats.get(fs['feature'], {}))
            scores.append(score)
            if score >= SIMILARITY_THRESHOLD or len(hits) >= KEYWORD_HITS:
                candidates.append({'upstream': title, 'upstreamSummary': summary_of(body), 'fork': fs['title'],
                                   'forkSummary': summary_of(fs['text']), 'score': round(score, 3), 'keywords': hits})
    candidates.sort(key=lambda c: (-len(c['keywords']), -c['score']))
    top = sorted(scores, reverse=True)[:5]
    return {'lineHits': line_hits, 'newSections': len(new_sections), 'candidates': candidates,
            'topScores': [round(s, 3) for s in top], 'threshold': SIMILARITY_THRESHOLD}


# ---------------------------------------------------------------- 7. 品牌
def load_brand():
    spec = importlib.util.spec_from_file_location('ma_brand', SCRIPT_ROOT / 'scripts/fork/brand.py')
    mod = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(mod)
    return mod


def section_brand(git, a, diff):
    brand = load_brand()
    allow = brand.load_allow()
    unlocalized, localized = [], 0
    for path, hunks in diff.items():
        if not (swift(path) and path.startswith('Sources/')):
            continue
        added = {no for h in hunks for no, _ in h['added']}
        if not added:
            continue
        source = git.show(a.head_sha, path) or ''
        lines = source.split('\n')
        for lit in brand.swift_literals(source):
            if lit.line not in added or not brand.leftover(lit.body):
                continue
            line = lines[lit.line - 1] if lit.line <= len(lines) else ''
            if brand.literal_is_localized(lit, line):
                localized += 1
            elif not any(brand.allow_matches(r, path, lit.body) for r in allow):
                unlocalized.append({'file': path, 'line': lit.line, 'text': lit.body[:120], 'call': lit.call or '（沒有呼叫）'})
    return {'unlocalized': unlocalized, 'localizedCount': localized}


# ---------------------------------------------------------------- 報告
def recommend(r):
    n = r['new']
    if not n['commits'] and not n['newTags'] and not n['rewritten'] and not n['movedTags']:
        return '不用動', '沒有新的上游 commit、tag'
    reasons = []
    if n['rewritten'] or n['movedTags']:
        reasons.append('上游改寫了歷史')
    if r['conflicts']['files']:
        reasons.append(f"{len(r['conflicts']['files'])} 個檔衝突")
    if r['collisions']:
        reasons.append(f"{len(r['collisions'])} 個名稱碰撞")
    if r['brand']['unlocalized']:
        reasons.append(f"{len(r['brand']['unlocalized'])} 個建置時換不到的品牌字")
    if reasons:
        return '先看', '、'.join(reasons)
    majors = [t['tag'] for t in n['newTags'] if (v := version_key(t['tag'])) and v[1] == 0 and v[2] == 0]
    if majors:
        return '先等', f"{'、'.join(majors)} 是大版本，等它的第一個修正版（upstream-sync §2.2）"
    if n['newTags']:
        return '直接跟', '只有修正版、沒有 🔴'
    return '先等', '上游 main 有新 commit，但還沒有新的 tag（跟 tag，不跟 main）'


def md_escape(s):
    return str(s).replace('|', '／').replace('\n', ' ')


def render(r):
    n = r['new']
    ver = n['version'] or '（沒有版本 tag）'
    out = [f"# 上游監看 {r['date']}：上游 {ver}（{len(n['commits'])} 個新 commit）", '']
    out += ['## 1. 摘要', '',
            f"- 比對：fork `{r['refs']['fork']}`、上游 `{r['refs']['head']}`；新東西的起點 `{r['refs']['base']}`（{r['refs']['baseFrom']}）；"
            f"合併基準 `{r['refs']['mergeBase']}`",
            f"- 建議：**{r['recommendation'][0]}**（{r['recommendation'][1]}）"]
    if n['rewritten']:
        out.append(f"- 🔴 **上游改寫了歷史**：上次看過的 `{n['rewritten'][:10]}` 不在現在的上游歷史裡")
    for t in n['movedTags']:
        out.append(f"- 🔴 tag `{t['tag']}` 被移動：`{t['old']}` → `{t['new']}`")
    out.append(f"- 🔴 衝突 {len(r['conflicts']['files'])} 個檔、🔴 名稱碰撞 {len(r['collisions'])}、🟡 改到接點 {len(r['hooks'])}、"
               f"🟡 搬資料的 SQL {len(r['sql'])}、🟡 可能相似 {len(r['similar']['candidates'])}、"
               f"品牌換不到 {len(r['brand']['unlocalized'])}（🔴 計數）")
    if n['newTags']:
        out += ['', '新 tag：', '']
        for t in n['newTags']:
            msg = t['message'].strip().split('\n')
            out.append(f"- `{t['tag']}`（{t['commit']}）：{md_escape(msg[0]) if msg and msg[0] else '（沒有說明）'}")
            for l in msg[1:12]:
                if l.strip():
                    out.append(f"  - {md_escape(l.strip().lstrip('- '))}")
    if n['commits']:
        out += ['', f"新 commit（{len(n['commits'])} 個，最多列 50 個）：", '']
        out += [f"- `{c['commit']}` {md_escape(c['subject'])}" for c in n['commits'][:50]]
    out += ['', '## 2. 🔴 衝突', '']
    if r['conflicts']['files']:
        out += ['| 檔 | 處數 | 歸屬功能 |', '|---|---|---|']
        for f in r['conflicts']['files']:
            feats = '、'.join(f'{k} {v}' for k, v in f['features'].items())
            out.append(f"| `{f['file']}` | {f['blocks']} | {feats} |")
    else:
        out.append('沒有衝突。')
    out += ['', '## 3. 🔴 名稱碰撞', '']
    if r['collisions']:
        out += ['| 種類 | 名稱 | fork 那邊 | 位置 |', '|---|---|---|---|']
        out += [f"| {c['kind']} | `{md_escape(c['name'])}` | {c['feature']} | {c.get('where', '')} |" for c in r['collisions']]
    else:
        out.append('沒有。')
    out += ['', '## 4. 🟡 改到 fork 接點但沒衝突', '']
    if r['hooks']:
        out += ['| 檔 | 上游 hunk | 功能 | fork 的接點 | 上游新增的一行 |', '|---|---|---|---|---|']
        out += [f"| `{h['file']}` | `{md_escape(h['hunk'])}` | {'、'.join(h['features'])} | `{md_escape(h['hook'])}` | `{md_escape(h['upstream'])}` |"
                for h in r['hooks']]
    else:
        out.append('沒有。')
    out += ['', '## 5. 🟡 搬動會議資料的新 SQL（fork 的表要不要跟著處理，fork design §F-DB）', '']
    if r['sql']:
        out += [f"- `{s['file']}:{s['line']}`（{s['kind']}）`{md_escape(s['text'])}`" for s in r['sql']]
    else:
        out.append('沒有。')
    sim = r['similar']
    out += ['', '## 6. 🟡 可能相似的功能（只篩選，要讀兩邊才知道）', '',
            f"上游 requirements 新的章節 {sim['newSections']} 個；相似度門檻 {sim['threshold']}、或同一節命中同一功能的關鍵字 ≥ {KEYWORD_HITS} 個。"
            f"最高的分數：{', '.join(map(str, sim['topScores'])) or '—'}", '']
    if sim['candidates']:
        out += ['| 上游段落 | fork 段落 | 分數 | 命中的關鍵字 | 上游摘要 | fork 摘要 |', '|---|---|---|---|---|---|']
        out += [f"| {md_escape(c['upstream'])} | {md_escape(c['fork'])} | {c['score']} | {'、'.join(c['keywords'])} | "
                f"{md_escape(c['upstreamSummary'])} | {md_escape(c['forkSummary'])} |" for c in sim['candidates']]
    else:
        out.append('沒有候選。')
    if sim['lineHits']:
        out += ['', '上游新增的行命中的關鍵字（程式、翻譯表、docs）：', '']
        for fid, h in sorted(sim['lineHits'].items()):
            kws = '、'.join(f'{k}×{v}' for k, v in sorted(h['keywords'].items(), key=lambda kv: -kv[1]))
            out.append(f"- **{fid}**（{h['count']} 行）：{kws}")
            out += [f"  - `{md_escape(s)}`" for s in h['samples']]
    b = r['brand']
    out += ['', '## 7. ⚪ 品牌', '', f"經過翻譯表的品牌字串（建置時會換）：{b['localizedCount']} 個。", '']
    if b['unlocalized']:
        out.append('🔴 不經過翻譯表、建置時換不到的新字串（加接點或列白名單，fork design §F7.4）：')
        out.append('')
        out += [f"- `{u['file']}:{u['line']}`（{md_escape(u['call'])}）`{md_escape(u['text'])}`" for u in b['unlocalized']]
    else:
        out.append('沒有建置時換不到的新字串。')
    fr = r['fresh']
    out += ['', '## 8. ⚪ 新的 migration、設定鍵、DEBUG 指令、`scripts/dev` 工具（給 CLAUDE.md 補注意事項）', '']
    for label, key in (('migration', 'migrations'), ('設定鍵', 'settings'), ('DEBUG 指令', 'debug'), ('資料表', 'tables'),
                       ('Info.plist 鍵', 'infoPlist'), ('scripts/dev', 'scriptsDev')):
        items = fr.get(key, [])
        out.append(f"- {label}（{len(items)}）：{'、'.join(f'`{md_escape(x)}`' for x in items[:60]) or '—'}" + ('…' if len(items) > 60 else ''))
    return '\n'.join(out) + '\n'


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--repo', default=str(SCRIPT_ROOT))
    ap.add_argument('--fork')
    ap.add_argument('--head', default='upstream/main')
    ap.add_argument('--base')
    ap.add_argument('--merge-base')
    ap.add_argument('--manifest', help='預設：腳本所在 repo 的 docs/fork/manifest.json')
    ap.add_argument('--fork-requirements', help='預設：腳本所在 repo 的 docs/fork/requirements.md')
    ap.add_argument('--state')
    ap.add_argument('--update-state', action='store_true')
    ap.add_argument('--out-md')
    ap.add_argument('--out-json')
    ap.add_argument('--date', default=datetime.date.today().isoformat())
    a = ap.parse_args(argv)
    try:
        git = Git(a.repo)
        manifest = json.loads(Path(a.manifest or SCRIPT_ROOT / 'docs/fork/manifest.json').read_text(encoding='utf-8'))
        fork_req = Path(a.fork_requirements or SCRIPT_ROOT / 'docs/fork/requirements.md').read_text(encoding='utf-8')
        fork_ref = a.fork or ('main' if git.rev('main') else 'HEAD')
        a.fork_sha = git.rev(fork_ref)
        a.head_sha = git.rev(a.head)
        if not a.fork_sha or not a.head_sha:
            raise ToolError(f'找不到 fork（{fork_ref}）或上游（{a.head}）：先 git fetch upstream')
        a.state_data = None
        if a.state and Path(a.state).exists():
            try:
                a.state_data = json.loads(Path(a.state).read_text(encoding='utf-8'))
            except json.JSONDecodeError as e:
                raise ToolError(f'狀態檔不是 JSON：{e}')
        if a.merge_base:
            a.merge_base_sha = git.rev(a.merge_base)
            if not a.merge_base_sha:
                raise ToolError(f'找不到 --merge-base {a.merge_base}')
        else:
            code, out = git.run('merge-base', a.fork_sha, a.head_sha, ok=(0, 1))
            if code == 1 or not out.strip():
                raise ToolError('fork 和上游沒有共同祖先（上游改寫過歷史？）：用 --merge-base 指定')
            a.merge_base_sha = out.strip()
        a.explicit_base = bool(a.base)
        base_from = '指定'
        if a.base:
            a.base_sha = git.rev(a.base)
            if not a.base_sha:
                raise ToolError(f'找不到 --base {a.base}')
        elif a.state_data and a.state_data.get('upstreamMain') and git.exists(a.state_data['upstreamMain']) \
                and git.is_ancestor(a.state_data['upstreamMain'], a.head_sha):
            a.base_sha, base_from = a.state_data['upstreamMain'], '上次看過的'
        else:
            a.base_sha, base_from = a.merge_base_sha, 'fork 已經合進來的'
        r = {'date': a.date, 'refs': {'fork': fork_ref, 'head': a.head, 'base': a.base_sha[:10], 'baseFrom': base_from,
                                      'mergeBase': a.merge_base_sha[:10]}}
        r['new'] = section_new(git, a)
        diff = parse_diff(git.out('diff', '-U0', '--no-renames', a.base_sha, a.head_sha))
        status = []
        for line in git.out('diff', '--name-status', '--no-renames', a.base_sha, a.head_sha).splitlines():
            st, _, path = line.partition('\t')
            status.append((st, path))
        r['conflicts'] = section_conflicts(git, a, manifest)
        conflict_files = {f['file'] for f in r['conflicts']['files']}
        r['hooks'] = section_hooks(git, a, manifest, conflict_files)
        r['collisions'], r['fresh'] = section_names(git, a, manifest, diff, status)
        r['sql'] = section_sql(git, a, diff)
        r['similar'] = section_similar(git, a, manifest, diff, fork_req)
        r['brand'] = section_brand(git, a, diff)
        r['recommendation'] = recommend(r)
        n = r['new']
        changed = bool(n['commits'] or n['newTags'] or n['rewritten'] or n['movedTags'])
        r['changed'] = changed
        md = render(r)
        if a.out_md:
            Path(a.out_md).write_text(md, encoding='utf-8')
        if a.out_json:
            Path(a.out_json).write_text(json.dumps(r, ensure_ascii=False, indent=1, default=list), encoding='utf-8')
        if not a.out_md and not a.out_json:
            sys.stdout.write(md)
        if a.update_state:
            if not a.state:
                raise ToolError('--update-state 要搭配 --state')
            Path(a.state).write_text(json.dumps({'upstreamMain': a.head_sha, 'tags': n['tags'], 'checkedAt': a.date},
                                                ensure_ascii=False, indent=1), encoding='utf-8')
        print(f"上游監看：{'有新東西' if changed else '沒有新東西'}（建議：{r['recommendation'][0]}）", file=sys.stderr)
        return 1 if changed else 0
    except Exception as e:   # 任何沒預期的錯誤都是 2：Python 預設的 exit 1 會被當成「有新東西」
        print(f'上游監看：工具錯誤：{type(e).__name__}: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
