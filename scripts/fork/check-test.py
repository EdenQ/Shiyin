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
      absent) echo "Error: Domain '$2' not found." >&2; exit 1;;
      *) echo 'Could not export domain: Operation not permitted' >&2; exit 1;;
    esac;;
  read)
    case "$mode" in
      absent) echo "Error: Domain '$2' not found." >&2; exit 1;;
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
if cmd == 'read' and os.environ.get('STUB_READ_ERROR'):   # cfprefsd 之類的錯誤：不是「不存在」
    sys.exit('cfprefsd: connection interrupted')
# 指定 read 的 stdout／stderr／exit（STUB_READ_DOMAIN 沒給時只套用在測試網域）：測「不存在」的嚴格比對
if cmd == 'read' and 'STUB_READ_STDERR' in os.environ and domain == os.environ.get('STUB_READ_DOMAIN', 'com.weiwei.shiyin.macheck'):
    sys.stdout.write(os.environ.get('STUB_READ_STDOUT', '')); sys.stderr.write(os.environ['STUB_READ_STDERR'])
    sys.exit(int(os.environ.get('STUB_READ_EXIT', '1')))
if cmd == 'export' and os.environ.get('STUB_EXPORT_EXIT'):
    sys.exit(int(os.environ['STUB_EXPORT_EXIT']))
if cmd == 'delete' and os.environ.get('STUB_DELETE_EXIT'):
    sys.exit(int(os.environ['STUB_DELETE_EXIT']))
data = json.load(open(path)) if os.path.exists(path) else None
if cmd == 'export':
    if data is None:
        sys.exit("Error: Domain '%s' not found." % domain)
    plistlib.dump(data, open(sys.argv[3], 'wb')); sys.exit(0)
if cmd == 'read':
    if data is None:
        sys.exit("Error: Domain '%s' not found." % domain)
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
exit "${STUB_LSREG_EXIT:-0}"
''',
    # rm：參數含 STUB_RM_FAIL 時失敗（檔留著），其他交給真的 rm
    'rm': r'''#!/bin/bash
if [ -n "${STUB_RM_FAIL:-}" ]; then for a in "$@"; do case "$a" in *"$STUB_RM_FAIL"*) echo "rm: $a: Operation not permitted" >&2; exit 1;; esac; done; fi
exec /bin/rm "$@"
''',
    # xcrun：編 check-handlers.swift 時照 STUB_HELPER 做出假的 helper（fail-compile／fail-run／incomplete／ok）
    'xcrun': r'''#!/bin/bash
out=""; prev=""; for a in "$@"; do [ "$prev" = -o ] && out="$a"; prev="$a"; done
case "${STUB_HELPER:-ok}" in
  fail-compile) echo "error: forced compile failure" >&2; exit 42;;
  fail-run) printf '#!/bin/bash\necho broken >&2; exit 3\n' > "$out";;
  incomplete) printf '#!/bin/bash\nprintf "scheme-default\\t/x.app\\n"\n' > "$out";;
  *) printf '#!/bin/bash\nprintf "scheme-default\\t/x.app\\ntype-default\\t/x.app\\n"\n' > "$out";;
esac
chmod +x "$out"
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
        shutil.copy(self.bin / 'rm', sbin / 'rm')
        env = {'PATH': f'{sbin}:/usr/bin:/bin', 'HOME': str(store / 'home'), 'STUB_STORE': str(store),
               'STUB_LOG': str(log), 'MA_LSREGISTER': str(self.bin / 'lsregister')}
        def sh(script, **extra):
            p = subprocess.run(['/bin/bash', '-c', f'. "{LIB}"; {script}'], capture_output=True, text=True, env={**env, **extra})
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

    # ---------- P2-6：清理失敗要回報，後置條件要成立 ----------
    def cleanup_case(self, **extra):
        store, sh, domain, put, calls = self.stateful()
        pref = store / 'home/Library/Preferences/com.weiwei.shiyin.macheck.plist'
        pref.parent.mkdir(parents=True, exist_ok=True); pref.write_text('x')
        put('com.weiwei.shiyin.macheck', {'settingsPage': 'recording'})
        put('com.weiwei.shiyin', {'llmProvider': 'claude'})
        app = store / 'debug-test/Meeting Assistant.app'
        app.mkdir(parents=True)
        code, msg = sh(f'cleanup_test_domain com.weiwei.shiyin.macheck "{app}"', **extra)
        return code, msg, store, domain, pref, calls

    def test_cleanup_ok_postconditions(self):
        code, msg, store, domain, pref, calls = self.cleanup_case()
        self.assertEqual(code, 0, msg)
        self.assertIsNone(domain('com.weiwei.shiyin.macheck'))
        self.assertFalse(pref.exists())
        self.assertEqual(domain('com.weiwei.shiyin'), {'llmProvider': 'claude'})

    def test_cleanup_rm_failure_fails(self):
        code, msg, store, domain, pref, calls = self.cleanup_case(STUB_RM_FAIL='com.weiwei.shiyin.macheck.plist')
        self.assertEqual(code, 1, msg)
        self.assertTrue(pref.exists())
        self.assertIn('還在', msg)

    def test_cleanup_defaults_delete_failure_fails(self):
        code, msg, store, domain, pref, calls = self.cleanup_case(STUB_DELETE_EXIT='23')
        self.assertEqual(code, 1, msg)
        self.assertIsNotNone(domain('com.weiwei.shiyin.macheck'), '假的刪除失敗：網域還在')
        self.assertIn('defaults delete', msg)

    def test_cleanup_lsregister_failure_fails(self):
        code, msg, *_ = self.cleanup_case(STUB_LSREG_EXIT='5')
        self.assertEqual(code, 1, msg)
        self.assertIn('lsregister', msg)

    def test_cleanup_unreadable_domain_is_not_absent(self):
        """defaults read 回的不是「不存在」：不能當成清乾淨"""
        code, msg, *_ = self.cleanup_case(STUB_READ_ERROR='1')
        self.assertEqual(code, 1, msg)
        self.assertIn('讀不了網域', msg)

    # REVIEW-3a4 P2-7：只有「完全等於」支援的格式才算不存在
    NEAR_MISSES = (
        "cfprefsd: Domain '{d}' not found in cache; Operation not permitted",   # 審查的例子
        "Error: Domain '{d}' not found.\ncfprefsd: connection interrupted",       # 正常訊息後面再接一行錯誤
        "cfprefsd: warming up\nError: Domain '{d}' not found.",                   # 前面多一行
        "Error: Domain '{d}' not found. ",                                         # 多一個空白
        " Error: Domain '{d}' not found.",
        "Error: Domain '{d}' not found",                                           # 少句點
        "Error: Domain 'com.weiwei.shiyin' not found.",                            # 別的網域（正式的）
        "Error: Domain '{d}.other' not found.",
        "Domain {d} does not exist (cached)",
        "",
    )

    def test_domain_absent_message(self):
        d = 'com.weiwei.shiyin.macheck'
        for msg, want in ((f"Error: Domain '{d}' not found.", 0), (f'Domain {d} does not exist', 0)):
            self.assertEqual(self.call('domain_absent_message', d, msg)[0], want, msg)
        for msg in self.NEAR_MISSES + ('cfprefsd: connection interrupted',):
            code, out = self.call('domain_absent_message', d, msg.format(d=d))
            self.assertEqual(code, 1, f'{msg!r} 不能當成不存在：{out}')
        self.assertEqual(self.call('domain_absent_message', '', "Error: Domain '' not found.")[0], 1, '空的網域名稱')

    def test_domain_state_strict(self):
        """domain_state：exit 非 0、stdout 空、stderr 完全等於才是 absent；其他都 return 1"""
        store, sh, domain, put, calls = self.stateful()
        d = 'com.weiwei.shiyin.macheck'
        exact = f"Error: Domain '{d}' not found.\n"
        code, out = sh(f'domain_state {d}', STUB_READ_STDERR=exact)
        self.assertEqual((code, out.strip()), (0, 'absent'))
        code, out = sh(f'domain_state {d}', STUB_READ_STDERR=exact, STUB_READ_STDOUT='{ a = b; }\n')
        self.assertEqual(code, 1, f'stdout 不是空的：{out}')
        for msg in self.NEAR_MISSES:
            code, out = sh(f'domain_state {d}', STUB_READ_STDERR=msg.format(d=d) + '\n')
            self.assertEqual(code, 1, f'{msg!r}：{out}')
            self.assertNotIn('absent', out.split('\n')[0])

    def test_cleanup_and_snapshot_reject_near_miss(self):
        """cleanup_test_domain、defaults_snapshot 共用同一個判斷：近似訊息都失敗"""
        d = 'com.weiwei.shiyin.macheck'
        for msg in self.NEAR_MISSES:
            code, out, *_ = self.cleanup_case(STUB_READ_STDERR=msg.format(d=d) + '\n')
            self.assertEqual(code, 1, f'cleanup {msg!r}：{out}')
        store, sh, domain, put, calls = self.stateful()
        for msg in self.NEAR_MISSES:
            if msg.format(d='com.weiwei.shiyin') == "Error: Domain 'com.weiwei.shiyin' not found.":
                continue   # 「別的網域」那一條用的正好是正式網域的名字：對正式網域的快照來說是完全相符
            code, out = sh(f'defaults_snapshot "{store}/s.plist"', STUB_EXPORT_EXIT='1', STUB_READ_DOMAIN='com.weiwei.shiyin',
                           STUB_READ_STDERR=msg.format(d='com.weiwei.shiyin') + '\n')
            self.assertEqual(code, 1, f'snapshot {msg!r}：{out}')
        code, out = sh(f'defaults_snapshot "{store}/s.plist"', STUB_EXPORT_EXIT='1', STUB_READ_DOMAIN='com.weiwei.shiyin',
                       STUB_READ_STDERR="Error: Domain 'com.weiwei.shiyin' not found.\n")
        self.assertEqual(code, 0, out)
        self.assertEqual((store / 's.plist').read_text(), 'MA-CHECK: domain absent\n')

    # ---------- REVIEW-3a4 P2-8：git archive | tar 兩邊的 exit ----------
    def test_extract_tag(self):
        work = Path(tempfile.mkdtemp(dir=self.tmp))
        sbin = work / 'bin'; sbin.mkdir()
        (sbin / 'git').write_text('#!/bin/bash\necho payload; exit "${STUB_GIT_EXIT:-0}"\n')
        (sbin / 'tar').write_text('#!/bin/bash\ncat >/dev/null; exit "${STUB_TAR_EXIT:-0}"\n')
        for f in ('git', 'tar'): (sbin / f).chmod(0o755)
        for git, tar, want in (('0', '0', 0), ('128', '0', 1), ('0', '2', 1), ('128', '2', 1)):
            p = subprocess.run(['/bin/bash', '-c', f'set -u; . "{LIB}"; extract_tag /repo v5.0.1 "{work}"'], capture_output=True, text=True,
                               env={'PATH': f'{sbin}:/usr/bin:/bin', 'HOME': str(self.tmp), 'STUB_GIT_EXIT': git, 'STUB_TAR_EXIT': tar})
            self.assertEqual(p.returncode, want, f'git {git}、tar {tar}：{p.stdout}{p.stderr}')
            self.assertNotIn('unbound variable', p.stderr)

    # ---------- P2-5：處理程式的 helper、開始時的快照是必要條件 ----------
    def handlers_case(self, mode):
        work = Path(tempfile.mkdtemp(dir=self.tmp))
        e = {'PATH': f'{self.bin}:/usr/bin:/bin', 'HOME': str(self.tmp), 'STUB_HELPER': mode}
        p = subprocess.run(['/bin/bash', '-c', f'. "{LIB}"; prepare_handlers "$1" "$2" "$3"', 'x',
                            work / 'handlers', work / 'before.txt', work / 'build.log'], capture_output=True, text=True, env=e)
        return p.returncode, p.stdout + p.stderr

    def test_prepare_handlers(self):
        for mode, want in (('fail-compile', 1), ('fail-run', 1), ('incomplete', 1), ('ok', 0)):
            code, msg = self.handlers_case(mode)
            self.assertEqual(code, want, f'{mode}：{msg}')

    def test_debug_apps_ps_failure(self):
        bad = Path(tempfile.mkdtemp(dir=self.tmp))
        (bad / 'ps').write_text('#!/bin/bash\nexit 1\n'); (bad / 'ps').chmod(0o755)
        p = subprocess.run(['/bin/bash', '-c', f'. "{LIB}"; debug_apps'], capture_output=True, text=True,
                           env={'PATH': f'{bad}:/usr/bin:/bin', 'HOME': str(self.tmp)})
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)

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

    def test_missing_option_value_exits_2(self):
        for args in (['--only'], ['--quick', '--base-app'], ['--quick', '--out']):
            p = subprocess.run(['/bin/bash', str(ROOT / 'scripts/fork/check.sh'), *args], capture_output=True, text=True, timeout=60)
            self.assertEqual(p.returncode, 2, f'{args}：{p.stdout}{p.stderr}')
            self.assertNotIn('unbound variable', p.stderr)

    def test_single_debug_item_with_failed_build(self):
        """P3-2、P2-5：--only 5、5,12、--quick --only 5 要能跑完；建置失敗 → 5 FAIL、12 FAIL（缺處理程式快照）、C PASS、exit 1。
        假的 swift（建置失敗）、有狀態的假 defaults、HOME 在暫存資料夾：不建 app、不開 DEBUG 版、不碰真的設定"""
        tmp = Path(tempfile.mkdtemp(prefix='check-cli '))
        try:
            sbin, store = tmp / 'bin', tmp / 'store'
            sbin.mkdir(); store.mkdir()
            (sbin / 'swift').write_text('#!/bin/bash\necho "error: forced build failure" >&2; exit 1\n'); (sbin / 'swift').chmod(0o755)
            (sbin / 'defaults').write_text(STUBS['sdefaults']); (sbin / 'defaults').chmod(0o755)
            (store / 'com.weiwei.shiyin.json').write_text(json.dumps({'llmProvider': 'claude'}))
            env = {'PATH': f'{sbin}:/usr/bin:/bin', 'HOME': str(tmp / 'home'), 'STUB_STORE': str(store), 'STUB_LOG': str(tmp / 'calls.log'),
                   'TMPDIR': str(tmp)}
            for args in (['--only', '5'], ['--only', '5,12'], ['--quick', '--only', '5']):
                out = tmp / ('out-' + '-'.join(a.strip('-') for a in args))
                p = subprocess.run(['/bin/bash', str(ROOT / 'scripts/fork/check.sh'), *args, '--out', str(out)],
                                   capture_output=True, text=True, timeout=120, env=env)
                msg = p.stdout + p.stderr
                self.assertNotIn('unbound variable', msg, f'{args}')
                self.assertEqual(p.returncode, 1, f'{args}：{msg}')
                summary = (out / 'summary.md').read_text()
                self.assertRegex(summary, r'\| 5 \| .* \| FAIL \|.*建置失敗', f'{args}')
                self.assertRegex(summary, r'\| C \| .* \| PASS \|', f'{args}')
                if '12' in ','.join(args):
                    self.assertRegex(summary, r'\| 12 \| .* \| FAIL \|.*處理程式快照', f'{args}')
            calls = (tmp / 'calls.log').read_text() if (tmp / 'calls.log').exists() else ''
            self.assertNotIn('"write", "com.weiwei.shiyin"', calls)
            self.assertNotIn('"delete", "com.weiwei.shiyin"]', calls)
            # REVIEW-3a4 P2-7：測試網域的 defaults read 回近似的訊息 → 開始前清不掉、收尾 C FAIL、exit 1
            d = 'com.weiwei.shiyin.macheck'
            for msg in ("cfprefsd: Domain '{d}' not found in cache; Operation not permitted",
                        "Error: Domain '{d}' not found.\ncfprefsd: connection interrupted"):
                out = tmp / f'out-near-{len(msg)}'
                p = subprocess.run(['/bin/bash', str(ROOT / 'scripts/fork/check.sh'), '--only', '5', '--out', str(out)],
                                   capture_output=True, text=True, timeout=120, env={**env, 'STUB_READ_STDERR': msg.format(d=d) + '\n'})
                summary = (out / 'summary.md').read_text()
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                self.assertRegex(summary, r'\| 5 \| .* \| FAIL \|.*測試網域清不掉', msg)
                self.assertRegex(summary, r'\| C \| .* \| FAIL \|', msg)
        finally:
            shutil.rmtree(tmp)



class CacheLocation(unittest.TestCase):
    """REVIEW-3a5 P2-9：MA_CHECK_CACHE（和預設快取被換成符號連結）指到受保護或別人的資料夾 → exit 2、什麼都不建不刪。
    合成的 HOME（假的正式 app、正式資料夾）、假的 defaults；不碰真的 app 和設定"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='check-cache '))
        self.home = self.tmp / 'home'
        self.app = self.home / 'Library/Caches/ShiyinBuild/app/Meeting Assistant.app'
        for d in (self.app / 'Contents', self.app / 'base', self.home / 'Library/Application Support/Shiyin/base'):
            d.mkdir(parents=True)
            (d / 'sentinel.txt').write_text('keep me')
        (self.app / 'sentinel.txt').write_text('keep me')
        sbin, store = self.tmp / 'bin', self.tmp / 'store'
        sbin.mkdir(); store.mkdir()
        (sbin / 'defaults').write_text(STUBS['sdefaults']); (sbin / 'defaults').chmod(0o755)
        (store / 'com.weiwei.shiyin.json').write_text(json.dumps({'llmProvider': 'claude'}))
        self.env = {'PATH': f'{sbin}:/usr/bin:/bin', 'HOME': str(self.home), 'STUB_STORE': str(store),
                    'STUB_LOG': str(self.tmp / 'calls.log'), 'TMPDIR': str(self.tmp), 'PYTHONDONTWRITEBYTECODE': '1'}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def snapshot(self):
        # 不算：這次的輸出資料夾、假 defaults 的呼叫紀錄、Xcode 的 python 放在 HOME 的位元組碼快取
        skip = ('out-', 'calls.log', 'com.apple.python')
        return sorted(str(p.relative_to(self.tmp)) for p in self.tmp.rglob('*') if not any(k in str(p) for k in skip))

    def run_check(self, cache, *extra):
        env = dict(self.env)
        if cache is not None:
            env['MA_CHECK_CACHE'] = str(cache)
        out = Path(tempfile.mkdtemp(prefix='out-', dir=self.tmp))
        p = subprocess.run(['/bin/bash', str(ROOT / 'scripts/fork/check.sh'), '--quick', '--only', '12', *extra, '--out', str(out)],
                           capture_output=True, text=True, timeout=120, env=env)
        return p.returncode, p.stdout + p.stderr

    def assert_refused(self, cache, *extra, label=''):
        before = self.snapshot()
        code, msg = self.run_check(cache, *extra)
        self.assertEqual(code, 2, f'{label}：{msg}')
        self.assertIn('快取位置不能用', msg, label)
        self.assertNotIn('回歸檢查（', msg, f'{label}：不能開始跑')
        self.assertEqual(self.snapshot(), before, f'{label}：不能建立或刪除任何東西')
        for f in (self.app / 'sentinel.txt', self.app / 'base/sentinel.txt', self.app / 'Contents/sentinel.txt'):
            self.assertTrue(f.exists(), f'{label}：{f} 要留著')

    def test_refuse_fake_formal_app(self):
        self.assert_refused(self.app, '--clean-cache', label='直接指向正式 app')

    def test_refuse_symlink_alias(self):
        alias = self.tmp / 'alias'
        alias.symlink_to(self.app)
        self.assert_refused(alias, '--clean-cache', label='符號連結別名')

    def test_refuse_existing_foreign_dir(self):
        other = self.tmp / 'not-a-cache'
        (other / 'base').mkdir(parents=True)
        (other / 'sentinel.txt').write_text('keep me'); (other / 'base/sentinel.txt').write_text('keep me')
        self.assert_refused(other, '--clean-cache', label='非快取的既有資料夾')
        self.assertTrue((other / 'base/sentinel.txt').exists())

    def test_refuse_home_repo_parents_and_protected(self):
        self.assert_refused(self.home, label='$HOME')
        self.assert_refused(ROOT, label='repo')
        self.assert_refused(ROOT / 'scripts/fork-cache', label='repo 底下')
        self.assert_refused(self.home / 'Library/Caches/ShiyinBuild', label='正式 app 的上層')
        self.assert_refused(self.home / 'Library/Application Support/Shiyin', '--clean-cache', label='正式資料夾')
        self.assert_refused(self.home / 'Library/Application Support/Shiyin/cache', label='正式資料夾底下')
        self.assert_refused(Path('/'), label='/')
        self.assert_refused(self.home.parent, label='$HOME 的上層')
        self.assert_refused('relative-cache', label='相對路徑')
        f = self.tmp / 'a-file'
        f.write_text('x')
        self.assert_refused(f, label='不是資料夾')

    def test_refuse_shiyin_home(self):
        sh = self.tmp / 'demo-home'
        (sh / 'base').mkdir(parents=True)
        self.env['SHIYIN_HOME'] = str(sh)
        self.assert_refused(sh / 'cache', label='SHIYIN_HOME 底下')

    def test_refuse_default_symlinked_to_app(self):
        default = self.home / 'Library/Caches/ShiyinBuild/check'
        default.symlink_to(self.app)
        self.assert_refused(None, '--clean-cache', label='預設快取被換成指到正式 app 的符號連結')

    def test_accept_new_empty_and_marked(self):
        new = self.tmp / 'new-cache'
        code, msg = self.run_check(new)
        self.assertEqual(code, 0, msg)
        self.assertTrue((new / '.ma-check-cache').is_file(), '新建的快取要有標記')
        empty = self.tmp / 'empty-cache'
        empty.mkdir()
        code, msg = self.run_check(empty)
        self.assertEqual(code, 0, msg)
        self.assertTrue((empty / '.ma-check-cache').is_file())
        # 有標記的：--clean-cache 只刪 scratch、scratch-base、base，別的留著
        marked = self.tmp / 'marked-cache'
        for d in ('base/v1', 'scratch', 'scratch-base', 'other'):
            (marked / d).mkdir(parents=True)
        (marked / '.ma-check-cache').write_text('')
        (marked / 'other/keep.txt').write_text('keep')
        code, msg = self.run_check(marked, '--clean-cache')
        self.assertEqual(code, 0, msg)
        for d in ('base', 'scratch', 'scratch-base'):
            self.assertFalse((marked / d).exists(), d)
        self.assertTrue((marked / 'other/keep.txt').exists())
        self.assertTrue((marked / '.ma-check-cache').exists())

    def test_default_still_works(self):
        code, msg = self.run_check(None)
        self.assertEqual(code, 0, msg)
        self.assertTrue((self.home / 'Library/Caches/ShiyinBuild/check').is_dir())

if __name__ == '__main__':
    unittest.main(verbosity=2 if '-v' in sys.argv else 1, argv=[sys.argv[0]])
