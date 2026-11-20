#!/usr/bin/env python3
"""upstream-watch.py 的測試（fork design §F0.5）：在暫存 git repo 造上游、fork 的合成情境，測每一節和 exit code；
另外靜態檢查 .github/workflows/upstream-watch.yml（權限只有 contents: read、沒有 Issue／推送、action 鎖在 SHA、不用 secret）。
用法：python3 scripts/fork/upstream-watch-test.py [-v]。只用暫存資料夾，不碰這個 repo 的 ref、不連網路。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
WATCH = ROOT / 'scripts/fork/upstream-watch.py'
WORKFLOW = ROOT / '.github/workflows/upstream-watch.yml'

MANIFEST = {
    'rules': {'migrationPrefix': 'ma_', 'tablePrefix': 'ma_', 'settingsKeyPrefix': 'ma',
              'legacyNames': {'tables': ['speaker_tags'], 'settingsKeys': ['muteHotKey'], 'debugCommands': ['tagspeaker', 'micmute']}},
    'features': {
        'F2': {'debugCommands': ['tagspeaker', 'applytags'], 'tables': ['speaker_tags'], 'migrations': ['ma_speaker_tags_v1'],
               'markers': [], 'watchKeywords': {'zh': ['說話者標記', '標記說話者'], 'en': ['tag speaker']}},
        'F3': {'settingsKeys': ['muteHotKey'], 'debugCommands': ['micmute', 'hotkey mute'],
               'markers': [{'file': 'Sources/Shiyin/Capture/Recorder.swift', 'line': 10, 'hook': 'x'},
                           {'file': 'Sources/Shiyin/Store/AppModel.swift', 'line': 6, 'hook': 'x'}],
               'upstreamFiles': ['Sources/Shiyin/Views/MenuBar.swift'],
               'watchKeywords': {'zh': ['靜音', '打開麥克風'], 'en': ['mute', 'unmute']}},
        'F1': {'infoPlistKeys': {'ShiyinIssuesURL': 'https://example.invalid/issues'}, 'markers': []},
    },
}
FORK_REQ = textwrap.dedent('''\
    # fork 需求
    ## F3. 錄音中靜音麥克風
    錄音中可以靜音麥克風，麥克風那一聲道變成無聲，電腦聲音照常錄。靜音中現場好像有人說話時提醒打開麥克風。
    ## F2. 錄音中標記說話者
    錄音中按正在說話的人的名字，錄完依時間把名字套到說話者。
    ''')


def numbered(prefix, n=30):
    return ''.join(f'    let {prefix}{i} = {i}\n' for i in range(1, n + 1))


class Repo:
    """暫存 git repo：上游的 base（A）、fork 的 main、上游的新 commit（B）"""

    def __init__(self, root):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'watch test')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'tag.gpgsign', 'false')

    def git(self, *args, check=True):
        p = subprocess.run(['git', '-C', str(self.root), *args], capture_output=True, text=True)
        if check and p.returncode != 0:
            raise RuntimeError(f'git {args}: {p.stderr}')
        return p.stdout.strip()

    def write(self, path, text):
        f = self.root / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding='utf-8')

    def edit(self, path, old, new):
        f = self.root / path
        s = f.read_text(encoding='utf-8')
        assert old in s, (path, old)
        f.write_text(s.replace(old, new, 1), encoding='utf-8')

    def commit(self, msg):
        self.git('add', '-A')
        self.git('commit', '-q', '-m', msg)
        return self.git('rev-parse', 'HEAD')

    def upstream_tag(self, name, commit, msg):
        """上游 tag 放 refs/upstream-tags/（照 Actions、本機的 refspec）"""
        self.git('tag', '-a', name, '-m', msg, commit)
        obj = self.git('rev-parse', f'refs/tags/{name}')
        self.git('update-ref', f'refs/upstream-tags/{name}', obj)
        self.git('tag', '-d', name)


def build(tmp):
    r = Repo(tmp / 'repo')
    # A：上游的 base
    r.write('Sources/Shiyin/Debug/DebugControl.swift', 'switch cmd {\n        case "state":\n            break\n        case "select":\n            break\n}\n')
    r.write('Sources/Shiyin/Capture/Recorder.swift', 'final class Recorder {\n' + numbered('r') + '}\n')
    r.write('Sources/Shiyin/Store/AppModel.swift', 'final class AppModel {\n' + numbered('m') + '}\n')
    r.write('Sources/Shiyin/Views/MenuBar.swift', 'struct MenuBar {\n    let a = 1\n}\n')
    r.write('Resources/Localizable.xcstrings', json.dumps({'sourceLanguage': 'zh-Hant', 'strings': {'開始': {}}}, ensure_ascii=False, indent=2))
    r.write('Resources/Info.plist', '<plist><dict>\n<key>CFBundleName</key><string>Shiyin</string>\n</dict></plist>\n')
    r.write('docs/requirements.md', '# 需求\n## 1. 基本\n錄音、轉錄。\n')
    a = r.commit('A: upstream base')
    r.upstream_tag('v1.0.0', a, '拾音 1.0.0：第一版')
    r.upstream_tag('win-v1.0.0', a, 'Windows 1.0.0')
    # fork：在 A 上加 F3
    r.write('Sources/Shiyin/Fork/Mute/MicMute.swift',
            'enum ForkMute {\n    static func install(_ r: Recorder) {}\n}\nextension Recorder {\n    func toggleMicMute() {}\n    var micMuted: Bool { false }\n}\n')
    r.edit('Sources/Shiyin/Capture/Recorder.swift', '    let r9 = 9\n', '    let r9 = 9\n    ForkMute.install(self)   // MA-FORK(F3)\n')
    r.edit('Sources/Shiyin/Capture/Recorder.swift', '    let r20 = 20\n', '    let r20 = 2000   // MA-FORK(F3)\n')
    r.edit('Sources/Shiyin/Store/AppModel.swift', '    let m5 = 5\n', '    let m5 = 5\n    let fork = ForkMute.self   // MA-FORK(F3)\n')
    r.write('Resources/Localizable.xcstrings', json.dumps({'sourceLanguage': 'zh-Hant', 'strings': {'開始': {}, '麥克風已靜音': {}}},
                                                       ensure_ascii=False, indent=2))
    fork = r.commit('fork: F3 mute')
    # 上游的新 commit B（從 A 開始）
    r.git('checkout', '-q', '-b', 'up', a)
    r.edit('Sources/Shiyin/Debug/DebugControl.swift', '        case "select":\n',
           '        case "tagspeaker":\n            UserDefaults.standard.set(true, forKey: "muteHotKey")\n        case "select":\n')
    r.edit('Sources/Shiyin/Capture/Recorder.swift', '    let r20 = 20\n', '    let r20 = 3000\n')           # 跟 fork 衝突
    r.edit('Sources/Shiyin/Capture/Recorder.swift', '    let r30 = 30\n', '    let r30 = 30\n    func toggleMicMute() {}\n')
    r.edit('Sources/Shiyin/Store/AppModel.swift', '    let m7 = 7\n', '    let m7 = 70\n')                # 離 fork 接點 2 行，沒衝突
    r.write('Sources/Shiyin/Store/Edits.swift', textwrap.dedent('''\
        enum Edits {
            static let sql = "CREATE TABLE IF NOT EXISTS ma_fake (id INTEGER)"
            func run() {
                migrator.registerMigration("ma_fake_v1") { _ in }
                db.execute(sql: "UPDATE segments SET start = MAX(0, start - ?) WHERE meeting_id = ?")
                let label = Text("拾音說明")
                let raw = "拾音測試"
            }
            func restoreSnapshotFoo() {}
        }
        '''))
    r.write('Sources/Shiyin/Fork/Upstream.swift', 'struct UpstreamThing {}\n')
    r.write('Resources/Localizable.xcstrings', json.dumps({'sourceLanguage': 'zh-Hant', 'strings': {'開始': {}, '麥克風已靜音': {}, '新的字': {}}},
                                                       ensure_ascii=False, indent=2))
    r.edit('Resources/Info.plist', '</dict>', '<key>MABrandX</key><string>x</string>\n</dict>')
    r.edit('docs/requirements.md', '錄音、轉錄。\n', '錄音、轉錄。\n### R9 錄音中靜音麥克風\n錄音中可以把麥克風靜音，電腦聲音照常錄，打開麥克風再錄現場。\n')
    r.write('scripts/dev/new-tool.py', 'print(1)\n')
    b = r.commit('B: upstream adds things')
    r.upstream_tag('v1.1.0', b, '拾音 1.1.0：新東西\n- 靜音\n- 標記')
    r.git('update-ref', 'refs/remotes/upstream/main', b)
    r.git('checkout', '-q', 'main')
    return r, a, fork, b


class Watch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='watch-test '))
        self.repo, self.a, self.fork, self.b = build(self.tmp)
        self.manifest = self.tmp / 'manifest.json'
        self.manifest.write_text(json.dumps(MANIFEST, ensure_ascii=False))
        self.req = self.tmp / 'fork-req.md'
        self.req.write_text(FORK_REQ, encoding='utf-8')

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_watch(self, *extra):
        md, js = self.tmp / 'out.md', self.tmp / 'out.json'
        md.unlink(missing_ok=True); js.unlink(missing_ok=True)
        p = subprocess.run([sys.executable, str(WATCH), '--repo', str(self.repo.root), '--manifest', str(self.manifest),
                            '--fork-requirements', str(self.req), '--date', '2026-11-20', '--out-md', str(md), '--out-json', str(js), *extra],
                           capture_output=True, text=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        data = json.loads(js.read_text()) if js.exists() else None
        text = md.read_text() if md.exists() else ''
        return p.returncode, data, text, p.stderr

    def test_full_report(self):
        code, d, md, err = self.run_watch()
        self.assertEqual(code, 1, err)
        self.assertTrue(md.startswith('# 上游監看 2026-11-20：上游 v1.1.0（1 個新 commit）'), md[:80])
        # 1. 新東西：v1.1.0（附說明），不列 win-v*
        self.assertEqual([t['tag'] for t in d['new']['newTags']], ['v1.1.0'])
        self.assertIn('新東西', d['new']['newTags'][0]['message'])
        self.assertIsNone(d['new']['rewritten'])
        # 2. 衝突：Recorder.swift，歸 F3（附近的 MA-FORK 標記）
        conf = {f['file']: f for f in d['conflicts']['files']}
        self.assertIn('Sources/Shiyin/Capture/Recorder.swift', conf)
        self.assertIn('F3', conf['Sources/Shiyin/Capture/Recorder.swift']['features'])
        # 3. 改到接點但沒衝突：AppModel.swift
        self.assertEqual([h['file'] for h in d['hooks']], ['Sources/Shiyin/Store/AppModel.swift'])
        self.assertIn('F3', d['hooks'][0]['features'])
        # 4. 名稱碰撞
        kinds = {(c['kind'], c['name']) for c in d['collisions']}
        for want in (('DEBUG 指令', 'tagspeaker'), ('設定鍵', 'muteHotKey'), ('資料表', 'ma_fake'), ('migration', 'ma_fake_v1'),
                     ('翻譯表的鍵', '麥克風已靜音'), ('Info.plist 鍵', 'MABrandX'), ('型別／函式', 'toggleMicMute'),
                     ('Fork/ 路徑', 'Sources/Shiyin/Fork/Upstream.swift')):
            self.assertIn(want, kinds)
        self.assertNotIn(('翻譯表的鍵', '新的字'), kinds, '上游自己的新鍵不是碰撞')
        self.assertNotIn(('DEBUG 指令', 'hotkey'), kinds)
        # 5. 搬資料的 SQL
        texts = ' '.join(s['text'] for s in d['sql'])
        self.assertIn('UPDATE segments SET start', texts)
        self.assertIn('restoreSnapshotFoo', texts)
        # 6. 相似：R9 對 F3
        pairs = {(c['upstream'], c['fork'].split('.')[0]) for c in d['similar']['candidates']}
        self.assertIn(('### R9 錄音中靜音麥克風', '## F3'), pairs)
        self.assertIn('F3', d['similar']['lineHits'])
        # 7. 品牌：不查表的「拾音測試」標出來，Text 的只計數
        self.assertEqual([u['text'] for u in d['brand']['unlocalized']], ['拾音測試'])
        self.assertGreaterEqual(d['brand']['localizedCount'], 1)
        # 8. 新的東西
        self.assertIn('scripts/dev/new-tool.py', d['fresh']['scriptsDev'])
        self.assertIn('ma_fake_v1', d['fresh']['migrations'])
        # 建議：有衝突、碰撞 → 先看；markdown 有每一節
        self.assertEqual(d['recommendation'][0], '先看')
        for h in ('## 2. 🔴 衝突', '## 3. 🔴 名稱碰撞', '## 4. 🟡', '## 5. 🟡', '## 6. 🟡', '## 7. ⚪', '## 8. ⚪'):
            self.assertIn(h, md)

    def test_state_no_change_and_new_commit(self):
        state = self.tmp / 'state.json'
        code, d, _, err = self.run_watch('--state', str(state), '--update-state')
        self.assertEqual(code, 1, err)
        saved = json.loads(state.read_text())
        self.assertEqual(saved['upstreamMain'], self.b)
        self.assertNotIn('win-v1.0.0', saved['tags'])
        # 同一個狀態再跑：沒有新東西 → 0
        code, d, md, err = self.run_watch('--state', str(state))
        self.assertEqual(code, 0, err)
        self.assertEqual(d['new']['commits'], [])
        self.assertEqual(d['recommendation'][0], '不用動')
        # 上游多一個 commit：起點是上次看過的，只列這一個
        self.repo.git('checkout', '-q', 'up')
        self.repo.write('docs/notes.md', 'x\n')
        c = self.repo.commit('C: more')
        self.repo.git('update-ref', 'refs/remotes/upstream/main', c)
        self.repo.git('checkout', '-q', 'main')
        code, d, _, err = self.run_watch('--state', str(state))
        self.assertEqual(code, 1, err)
        self.assertEqual([x['subject'] for x in d['new']['commits']], ['C: more'])
        self.assertEqual(d['refs']['baseFrom'], '上次看過的')
        # 新的只有 C，但 B 的衝突還沒解（試合併是 fork 對現在的上游），所以還是「先看」；名稱碰撞只看新的那一段
        self.assertEqual(d['recommendation'][0], '先看')
        self.assertIn('衝突', d['recommendation'][1])
        self.assertEqual(d['collisions'], [], 'C 沒有新的名字')

    def test_rewritten_history(self):
        state = self.tmp / 'state.json'
        self.run_watch('--state', str(state), '--update-state')
        # 上游 force-push：main 換成從 A 長出來的另一個 commit，v1.1.0 也搬過去
        self.repo.git('checkout', '-q', '-b', 'rewrite', self.a)
        self.repo.write('docs/other.md', 'rewritten\n')
        b2 = self.repo.commit('B2: rewritten')
        self.repo.git('update-ref', 'refs/remotes/upstream/main', b2)
        self.repo.upstream_tag('v1.1.0-tmp', b2, 'tmp')
        self.repo.git('update-ref', 'refs/upstream-tags/v1.1.0', self.repo.git('rev-parse', 'refs/upstream-tags/v1.1.0-tmp'))
        self.repo.git('update-ref', '-d', 'refs/upstream-tags/v1.1.0-tmp')
        self.repo.git('checkout', '-q', 'main')
        code, d, md, err = self.run_watch('--state', str(state))
        self.assertEqual(code, 1, err)
        self.assertEqual(d['new']['rewritten'], self.b)
        self.assertEqual([t['tag'] for t in d['new']['movedTags']], ['v1.1.0'])
        self.assertIn('🔴 **上游改寫了歷史**', md)
        self.assertEqual(d['recommendation'][0], '先看')

    def test_tool_errors_exit_2(self):
        for extra in (('--head', 'refs/remotes/upstream/nope'), ('--fork', 'no-such-branch'), ('--merge-base', 'nope'),
                      ('--base', 'nope')):
            code, d, _, err = self.run_watch(*extra)
            self.assertEqual(code, 2, f'{extra}：{err}')
            self.assertIn('工具錯誤', err)
        bad = self.tmp / 'bad-state.json'
        bad.write_text('{not json')
        self.assertEqual(self.run_watch('--state', str(bad))[0], 2)
        self.manifest.write_text('{"rules": {}}')   # 沒有 features：沒預期的 KeyError 也要是 2，不能是 1
        self.assertEqual(self.run_watch()[0], 2)
        self.manifest.write_text(json.dumps(MANIFEST))
        # 沒有共同祖先（上游改寫過、沒給 --merge-base）
        self.repo.git('checkout', '-q', '--orphan', 'alien')
        self.repo.write('x.txt', 'alien\n')
        alien = self.repo.commit('alien root')
        self.repo.git('update-ref', 'refs/remotes/upstream/main', alien)
        self.repo.git('checkout', '-q', '-f', 'main')
        code, _, _, err = self.run_watch()
        self.assertEqual(code, 2, err)
        self.assertIn('共同祖先', err)
        self.assertEqual(self.run_watch('--update-state')[0], 2, '--update-state 沒有 --state')

    def test_explicit_replay_range(self):
        """重播：--base、--merge-base 指定；merge-tree 用指定的合併基準"""
        code, d, _, err = self.run_watch('--base', self.a, '--merge-base', self.a, '--head', self.b)
        self.assertEqual(code, 1, err)
        self.assertEqual(d['refs']['baseFrom'], '指定')
        self.assertEqual(len(d['new']['commits']), 1)


class Workflow(unittest.TestCase):
    """.github/workflows/upstream-watch.yml 的靜態檢查（推送前；act 不在這台電腦）"""

    def setUp(self):
        self.text = WORKFLOW.read_text(encoding='utf-8')

    def test_structure(self):
        try:
            import yaml   # 有 PyYAML 時另外解析結構；沒有時只做下面的逐行檢查
        except ImportError:
            yaml = None
        if yaml:
            d = yaml.safe_load(self.text)
            on = d.get(True, d.get('on'))
            self.assertIn('schedule', on)
            self.assertIn('workflow_dispatch', on)
            self.assertEqual(d['permissions'], {'contents': 'read'})
            job = d['jobs']['watch']
            self.assertEqual(job['runs-on'], 'ubuntu-latest')
            self.assertNotIn('permissions', job, '工作不能另外加權限')
            uses = [s['uses'] for s in job['steps'] if 'uses' in s]
            self.assertTrue(uses)
        self.assertRegex(self.text, r'(?m)^permissions:\n  contents: read\n')

    def test_no_write_no_issue_no_secret(self):
        body = '\n'.join(l.split('#')[0] for l in self.text.splitlines())   # 註解不算
        for bad in (r'issues\s*:', r'\bwrite\b', r'secrets\.', r'\bgh\s+(issue|pr|api)', r'git\s+push', r'github-script',
                    r'create-issue', r'GITHUB_TOKEN'):
            self.assertIsNone(re.search(bad, body), bad)
        self.assertIn('persist-credentials: false', body)
        self.assertIn("'+refs/tags/*:refs/upstream-tags/*'", body, '上游 tag 不能放 refs/tags')

    def test_actions_pinned_to_sha(self):
        uses = re.findall(r'uses:\s*([^\s#]+)', self.text)
        self.assertGreaterEqual(len(uses), 4)
        for u in uses:
            self.assertRegex(u, r'^[\w.-]+/[\w./-]+@[0-9a-f]{40}$', u)

    def test_summary_is_one_line(self):
        writes = re.findall(r'>>\s*"\$GITHUB_STEP_SUMMARY"', self.text)
        self.assertEqual(len(writes), 3, '0／1／其他 各一行')
        self.assertNotIn('cat out/', self.text, '不能把報告內容放進公開的 log 或 summary')


if __name__ == '__main__':
    unittest.main(verbosity=2 if '-v' in sys.argv else 1, argv=[sys.argv[0]])
