#!/usr/bin/env python3
"""check.sh 自己的負對照（fork design §F0.4「check.sh 自己的測試」；REVIEW-3a P2-1～P2-3、P3-1）。

source scripts/fork/check-lib.sh，在暫存資料夾放假的 defaults、lsof、ps（PATH 最前面）呼叫裡面的函式：
不讀寫真的設定、不碰任何資料庫、不送訊號。plutil 用系統的（只檢查暫存檔）。
用法：python3 scripts/fork/check-test.py [-v]；全部符合 exit 0，否則 exit 1。
"""
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / 'scripts/fork/check-lib.sh'
REAL = '/Users/someone/Library/Application Support/Shiyin'

STUBS = {
    # defaults：STUB_DEFAULTS = ok | notplist | fail | absent
    'defaults': r'''#!/bin/bash
mode="${STUB_DEFAULTS:-fail}"
case "$1" in
  export)
    case "$mode" in
      ok) printf '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict><key>a</key><string>b</string></dict></plist>\n' > "$3"; exit 0;;
      notplist) echo 'not a plist' > "$3"; exit 0;;
      absent) echo "Domain $2 does not exist" >&2; exit 1;;
      *) echo 'Could not export domain: Operation not permitted' >&2; exit 1;;
    esac;;
  read)
    case "$mode" in
      absent) echo "Domain $2 does not exist" >&2; exit 1;;
      ok) echo '{ a = b; }'; exit 0;;
      *) echo 'cfprefsd error' >&2; exit 1;;
    esac;;
esac
exit 1
''',
    # lsof：印 STUB_LSOF_FILE 的內容，exit STUB_LSOF_EXIT
    'lsof': r'''#!/bin/bash
[ -n "${STUB_LSOF_FILE:-}" ] && cat "$STUB_LSOF_FILE"
exit "${STUB_LSOF_EXIT:-0}"
''',
    # 有狀態的 defaults（python）：STUB_STORE/<網域>.json 存值，每次呼叫記在 STUB_LOG。測正式網域不被改寫、測試網域被清掉
    'sdefaults': r'''#!/usr/bin/python3
import json, os, plistlib, sys
store, log = os.environ['STUB_STORE'], os.environ['STUB_LOG']
open(log, 'a').write(json.dumps(sys.argv[1:]) + '\n')
cmd, domain = sys.argv[1], sys.argv[2]
path = os.path.join(store, domain + '.json')
data = json.load(open(path)) if os.path.exists(path) else None
if cmd == 'export':
    if data is None:
        sys.exit('Domain %s does not exist' % domain)
    plistlib.dump(data, open(sys.argv[3], 'wb')); sys.exit(0)
if cmd == 'read':
    if data is None:
        sys.exit('Domain %s does not exist' % domain)
    if len(sys.argv) > 3:
        if sys.argv[3] not in data: sys.exit('does not exist')
        print(data[sys.argv[3]]); sys.exit(0)
    print(data); sys.exit(0)
if cmd == 'write':
    data = data or {}; data[sys.argv[3]] = sys.argv[-1]; json.dump(data, open(path, 'w')); sys.exit(0)
if cmd == 'delete':
    if data is None: sys.exit(1)
    if len(sys.argv) > 3: data.pop(sys.argv[3], None); json.dump(data, open(path, 'w'))
    else: os.remove(path)
    sys.exit(0)
sys.exit(1)
''',
    # lsregister：只記下呼叫
    'lsregister': r'''#!/bin/bash
echo "lsregister $*" >> "$STUB_LOG"
''',
    # ps -o comm= -p <pid>：印 STUB_PS_COMM；空的時候等於 pid 不在
    'ps': r'''#!/bin/bash
[ -n "${STUB_PS_COMM:-}" ] || exit 1
echo "$STUB_PS_COMM"
''',
}


class Lib(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='check-test '))   # 路徑有空白
        cls.bin = cls.tmp / 'bin'
        cls.bin.mkdir()
        for name, body in STUBS.items():
            (cls.bin / name).write_text(body)
            (cls.bin / name).chmod(0o755)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def call(self, func, *args, **env):
        e = {'PATH': f'{self.bin}:/usr/bin:/bin', 'HOME': str(self.tmp), **env}
        p = subprocess.run(['/bin/bash', '-c', f'. "{LIB}"; {func} "$@"', 'check-test', *map(str, args)],
                           capture_output=True, text=True, env=e)
        return p.returncode, p.stdout + p.stderr

    # ---------- P2-1 設定快照 ----------
    def test_snapshot_ok(self):
        out = self.tmp / 'ok.plist'
        code, msg = self.call('defaults_snapshot', out, STUB_DEFAULTS='ok')
        self.assertEqual(code, 0, msg)
        self.assertIn(b'<plist', out.read_bytes())

    def test_snapshot_export_failure_is_failure(self):
        out = self.tmp / 'fail.plist'
        code, msg = self.call('defaults_snapshot', out, STUB_DEFAULTS='fail')
        self.assertEqual(code, 1, msg)
        self.assertFalse(out.exists(), '失敗時不能留下（空的）快照檔')

    def test_snapshot_not_plist_is_failure(self):
        out = self.tmp / 'bad.plist'
        code, msg = self.call('defaults_snapshot', out, STUB_DEFAULTS='notplist')
        self.assertEqual(code, 1, msg)
        self.assertFalse(out.exists())

    def test_snapshot_absent_domain_is_explicit(self):
        out = self.tmp / 'absent.plist'
        code, msg = self.call('defaults_snapshot', out, STUB_DEFAULTS='absent')
        self.assertEqual(code, 0, msg)
        self.assertEqual(out.read_text(), 'MA-CHECK: domain absent\n')

    def test_absent_and_empty_are_different(self):
        """網域不存在跟拿到一個空 plist 不能被當成一樣"""
        a, b = self.tmp / 'a1.plist', self.tmp / 'a2.plist'
        self.call('defaults_snapshot', a, STUB_DEFAULTS='absent')
        self.call('defaults_snapshot', b, STUB_DEFAULTS='ok')
        self.assertNotEqual(a.read_bytes(), b.read_bytes())

    # ---------- P2-2 資料庫 ----------
    def lsof(self, *paths, exit=0):
        f = self.tmp / f'lsof-{len(list(self.tmp.glob("lsof-*")))}.txt'
        f.write_text(''.join(['p123\n'] + [f'fcwd\nn{x}\n' for x in paths]))
        return {'STUB_LSOF_FILE': str(f), 'STUB_LSOF_EXIT': str(exit)}

    def verify(self, home, *paths, exit=0):
        return self.call('verify_db_files', 123, home, REAL, **self.lsof(*paths, exit=exit))

    HOME = '/Users/someone/Library/Caches/ShiyinBuild/check/run 1/home-zh-Hant'   # 暫存 home 也有空白

    def test_only_temp_passes(self):
        h = self.HOME
        code, msg = self.verify(h, '/usr/lib/dyld', f'{h}/shiyin.sqlite', f'{h}/shiyin.sqlite-wal', f'{h}/shiyin.sqlite-shm')
        self.assertEqual(code, 0, msg)

    def test_only_real_fails(self):
        code, msg = self.verify(self.HOME, f'{REAL}/shiyin.sqlite', f'{REAL}/shiyin.sqlite-wal')
        self.assertEqual(code, 1, msg)
        self.assertIn('Application Support/Shiyin/shiyin.sqlite', msg, '要印出完整路徑')

    def test_both_fail(self):
        h = self.HOME
        code, msg = self.verify(h, f'{h}/shiyin.sqlite', f'{REAL}/shiyin.sqlite')
        self.assertEqual(code, 1, msg)
        self.assertIn(f'{REAL}/shiyin.sqlite', msg)

    def test_real_wal_only_fails(self):
        h = self.HOME
        code, msg = self.verify(h, f'{h}/shiyin.sqlite', f'{REAL}/shiyin.sqlite-wal')
        self.assertEqual(code, 1, msg)

    def test_other_real_file_fails(self):
        h = self.HOME
        code, msg = self.verify(h, f'{h}/shiyin.sqlite', f'{REAL}/audio/1.m4a')
        self.assertEqual(code, 1, msg)

    def test_other_home_database_fails(self):
        h = self.HOME
        code, msg = self.verify(h, f'{h}/shiyin.sqlite', '/tmp/other home/shiyin.sqlite')
        self.assertEqual(code, 1, msg)

    def test_prefix_lookalike_home_fails(self):
        """home-zh-Hant2 不是 home-zh-Hant 底下"""
        h = self.HOME
        code, msg = self.verify(h, f'{h}/shiyin.sqlite', f'{h}2/shiyin.sqlite')
        self.assertEqual(code, 1, msg)

    def test_temp_missing_fails(self):
        code, msg = self.verify(self.HOME, '/usr/lib/dyld')
        self.assertEqual(code, 1, msg)

    def test_lsof_failure_fails(self):
        h = self.HOME
        code, msg = self.verify(h, f'{h}/shiyin.sqlite', exit=1)
        self.assertEqual(code, 1, msg)

    def test_lsof_empty_fails(self):
        code, msg = self.call('verify_db_files', 123, self.HOME, REAL, STUB_LSOF_FILE='/dev/null')
        self.assertEqual(code, 1, msg)

    # ---------- P2-3 品牌比對 ----------
    def test_compare_status(self):
        for c, want_code, want in ((0, 0, 'PASS'), (1, 4, '需人工'), (2, 1, 'FAIL'), (3, 1, 'FAIL'), (127, 1, 'FAIL')):
            code, msg = self.call('compare_status', c)
            self.assertEqual((code, msg.strip()), (want_code, want), f'compare exit {c}')

    def test_brand_compare_invalid_base_is_2(self):
        """真的 brand.py：基準不是有效的 app（缺 Info.plist）時 exit 2，不是 1（差異）"""
        bad = self.tmp / 'invalid-base.app'
        bad.mkdir(exist_ok=True)
        p = subprocess.run([sys.executable, str(ROOT / 'scripts/fork/brand.py'), 'compare', bad, bad],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        code, msg = self.call('compare_status', p.returncode)
        self.assertEqual((code, msg.strip()), (1, 'FAIL'))

    # ---------- P3-1 --only ----------
    def test_only_validation(self):
        for value, want in (('999', 2), ('', 2), (',', 2), ('3,999', 2), ('3 5', 2), ('3,I1,S', 0),
                            (',3,5,', 0), ('T', 0), ('13', 0)):
            code, msg = self.call('validate_only', value)
            self.assertEqual(code, want, f'--only {value!r}：{msg}')

    # ---------- P2-4：DEBUG 版用測試 id；正式網域分不出來源的變更不改寫、不刪 ----------
    def stateful(self):
        store, sbin = Path(tempfile.mkdtemp(dir=self.tmp)), Path(tempfile.mkdtemp(dir=self.tmp))
        log = store / 'calls.log'
        shutil.copy(self.bin / 'sdefaults', sbin / 'defaults')
        env = {'PATH': f'{sbin}:/usr/bin:/bin', 'HOME': str(store / 'home'), 'STUB_STORE': str(store),
               'STUB_LOG': str(log), 'MA_LSREGISTER': str(self.bin / 'lsregister')}
        def sh(script):
            p = subprocess.run(['/bin/bash', '-c', f'. "{LIB}"; {script}'], capture_output=True, text=True, env=env)
            return p.returncode, p.stdout + p.stderr
        def domain(name):
            f = store / f'{name}.json'
            return json.loads(f.read_text()) if f.exists() else None
        def put(name, data):
            (store / f'{name}.json').write_text(json.dumps(data))
        def calls():
            return [json.loads(x) if x.startswith('[') else x for x in log.read_text().splitlines()] if log.exists() else []
        return store, sh, domain, put, calls

    def end_of_run(self, sh, store):
        # check.sh 結束時做的事：清測試網域、拿結束的快照、比對（#12）
        return sh(f'cleanup_test_domain com.weiwei.shiyin.macheck; defaults_snapshot "{store}/after.plist" && '
                  f'snapshot_diff "{store}/before.plist" "{store}/after.plist"')

    def assert_production_untouched_by_check(self, calls):
        bad = [c for c in calls if isinstance(c, list) and c[0] in ('write', 'delete') and c[1] == 'com.weiwei.shiyin']
        self.assertEqual(bad, [], f'檢查不能寫、刪正式網域：{bad}')

    def test_user_changes_existing_value_is_kept(self):
        store, sh, domain, put, calls = self.stateful()
        put('com.weiwei.shiyin', {'NSWindow Frame main': '274 187 1180 780 0 0 1728 1084 ', 'llmProvider': 'claude'})
        self.assertEqual(sh(f'defaults_snapshot "{store}/before.plist"')[0], 0)
        put('com.weiwei.shiyin.macheck', {'NSWindow Frame main': '-1550 172 1180 780 -1920 37 1920 1050 ', 'settingsPage': 'recording'})
        # 檢查中使用者自己移動了正式 app 的主視窗
        user = '10 20 1180 780 -1920 37 1920 1050 '
        put('com.weiwei.shiyin', {'NSWindow Frame main': user, 'llmProvider': 'claude'})
        code, msg = self.end_of_run(sh, store)
        self.assertEqual(code, 1, msg)
        self.assertIn('NSWindow Frame main', msg, '#12 要列出不同的鍵')
        self.assertEqual(domain('com.weiwei.shiyin')['NSWindow Frame main'], user, '使用者的值要原樣留著')
        self.assertIsNone(domain('com.weiwei.shiyin.macheck'), '測試網域要清掉')
        self.assert_production_untouched_by_check(calls())

    def test_user_creates_new_key_is_kept(self):
        store, sh, domain, put, calls = self.stateful()
        put('com.weiwei.shiyin', {'llmProvider': 'claude'})
        self.assertEqual(sh(f'defaults_snapshot "{store}/before.plist"')[0], 0)
        put('com.weiwei.shiyin', {'llmProvider': 'claude', 'settingsPage': 'models'})   # 使用者中途打開設定的「模型」頁
        code, msg = self.end_of_run(sh, store)
        self.assertEqual(code, 1, msg)
        self.assertIn('settingsPage', msg)
        self.assertEqual(domain('com.weiwei.shiyin').get('settingsPage'), 'models', '使用者建立的鍵不能被刪')
        self.assert_production_untouched_by_check(calls())

    def test_unchanged_production_passes(self):
        store, sh, domain, put, calls = self.stateful()
        put('com.weiwei.shiyin', {'llmProvider': 'claude'})
        sh(f'defaults_snapshot "{store}/before.plist"')
        put('com.weiwei.shiyin.macheck', {'settingsPage': 'recording'})   # 只有測試網域被寫
        code, msg = self.end_of_run(sh, store)
        self.assertEqual(code, 0, msg)
        self.assertIsNone(domain('com.weiwei.shiyin.macheck'))
        self.assert_production_untouched_by_check(calls())

    def test_cleanup_only_test_domain(self):
        store, sh, domain, put, calls = self.stateful()
        lib = store / 'home/Library'
        prod = [lib / 'Preferences/com.weiwei.shiyin.plist', lib / 'HTTPStorages/com.weiwei.shiyin']
        test = [lib / 'Preferences/com.weiwei.shiyin.macheck.plist', lib / 'HTTPStorages/com.weiwei.shiyin.macheck',
                lib / 'Caches/com.weiwei.shiyin.macheck', lib / 'Saved Application State/com.weiwei.shiyin.macheck.savedState']
        for f in prod + test:
            f.parent.mkdir(parents=True, exist_ok=True); f.write_text('x')
        put('com.weiwei.shiyin', {'a': 'b'})
        put('com.weiwei.shiyin.macheck', {'a': 'b'})
        for refused in ('com.weiwei.shiyin', '', 'com.weiwei.shiyinX', 'other.domain'):
            code, msg = sh(f'cleanup_test_domain "{refused}" "/x/Meeting Assistant.app"')
            self.assertEqual(code, 1, f'{refused!r}：{msg}')
        self.assertEqual(calls(), [], '拒絕時一個指令都不能下')
        self.assertTrue(all(f.exists() for f in prod + test))
        app = store / 'debug-test/Meeting Assistant.app'
        app.mkdir(parents=True)
        code, msg = sh(f'cleanup_test_domain com.weiwei.shiyin.macheck "{app}"')
        self.assertEqual(code, 0, msg)
        self.assertTrue(all(f.exists() for f in prod), '正式的檔不能動')
        self.assertFalse(any(f.exists() for f in test), '測試網域的檔要刪掉')
        self.assertIsNone(domain('com.weiwei.shiyin.macheck'))
        self.assertEqual(domain('com.weiwei.shiyin'), {'a': 'b'})
        self.assertIn(f'lsregister -u {app}', calls())
        self.assert_production_untouched_by_check(calls())

    def test_isolate_debug_app(self):
        src = self.tmp / 'iso-src/Meeting Assistant.app'
        (src / 'Contents/MacOS').mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / 'Resources/Info.plist', src / 'Contents/Info.plist')
        shutil.copy('/usr/bin/true', src / 'Contents/MacOS/Shiyin')
        e = {'PATH': '/usr/bin:/bin', 'HOME': str(self.tmp)}
        p = subprocess.run(['/bin/bash', '-c', f'. "{LIB}"; isolate_debug_app "$1" "$2"', 'x', src, self.tmp / 'iso out'],
                           capture_output=True, text=True, env=e)
        self.assertEqual(p.returncode, 0, p.stderr)
        app = Path(p.stdout.strip())
        info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
        self.assertEqual(info['CFBundleIdentifier'], 'com.weiwei.shiyin.macheck')
        for key in ('CFBundleURLTypes', 'CFBundleDocumentTypes', 'UTExportedTypeDeclarations'):
            self.assertNotIn(key, info)
        self.assertEqual(plistlib.loads((src / 'Contents/Info.plist').read_bytes())['CFBundleIdentifier'], 'com.weiwei.shiyin',
                         '原本那一份（#3、#4 檢查的）不能動')
        self.assertEqual(subprocess.run(['codesign', '--verify', '--strict', app]).returncode, 0)
        p = subprocess.run(['/bin/bash', '-c', f'. "{LIB}"; isolate_debug_app "$1" "$2" com.weiwei.shiyin', 'x', src, self.tmp / 'iso2'],
                           capture_output=True, text=True, env=e)
        self.assertEqual(p.returncode, 1, '測試 id 給成正式的要拒絕')

    # ---------- stop_debug 的 pid 核對 ----------
    def test_owned_pid(self):
        app = '/x/check/run 1/debug/Meeting Assistant.app'
        exe = f'{app}/Contents/MacOS/Shiyin'
        self.assertEqual(self.call('owned_pid', 123, app, STUB_PS_COMM=exe)[0], 0)
        self.assertEqual(self.call('owned_pid', 123, app, STUB_PS_COMM='/usr/bin/vim')[0], 1)
        self.assertEqual(self.call('owned_pid', 123, app, STUB_PS_COMM='/Users/x/Desktop/Shiyin.app/Contents/MacOS/Shiyin')[0], 1)
        self.assertEqual(self.call('owned_pid', 123, app, STUB_PS_COMM='')[0], 1)


class CheckScript(unittest.TestCase):
    """check.sh 本身：--only 不對就 exit 2，在開始前（不建置、不讀設定）"""

    def run_check(self, *args):
        with tempfile.TemporaryDirectory() as out:
            p = subprocess.run(['/bin/bash', str(ROOT / 'scripts/fork/check.sh'), *args, '--out', out],
                               capture_output=True, text=True, timeout=60)
        return p.returncode, p.stdout + p.stderr

    def test_unknown_only_exits_2(self):
        for value in ('999', '', '3,999'):
            code, msg = self.run_check('--quick', '--only', value)
            self.assertEqual(code, 2, f'--only {value!r}：{msg}')
            self.assertNotIn('回歸檢查（', msg, '參數錯時不能開始跑')

    def test_unknown_option_exits_2(self):
        code, _ = self.run_check('--bogus')
        self.assertEqual(code, 2)


if __name__ == '__main__':
    unittest.main(verbosity=2 if '-v' in sys.argv else 1, argv=[sys.argv[0]])
