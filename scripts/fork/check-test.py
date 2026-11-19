#!/usr/bin/env python3
"""check.sh 自己的負對照（fork design §F0.4「check.sh 自己的測試」；REVIEW-3a P2-1～P2-3、P3-1）。

source scripts/fork/check-lib.sh，在暫存資料夾放假的 defaults、lsof、ps（PATH 最前面）呼叫裡面的函式：
不讀寫真的設定、不碰任何資料庫、不送訊號。plutil 用系統的（只檢查暫存檔）。
用法：python3 scripts/fork/check-test.py [-v]；全部符合 exit 0，否則 exit 1。
"""
import os
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
    # 有狀態的 defaults（STUB_STORE 資料夾，一個鍵一個檔）：測 save_keys／restore_keys
    'sdefaults': r'''#!/bin/bash
store="$STUB_STORE"; f="$store/$(printf %s "$3" | shasum | cut -c1-12)"
case "$1" in
  read) [ -f "$f" ] && { cat "$f"; echo; exit 0; }; echo "does not exist" >&2; exit 1;;
  read-type) [ -f "$f" ] && { echo "Type is string"; exit 0; }; exit 1;;
  write) printf %s "$5" > "$f"; exit 0;;
  delete) rm -f "$f"; exit 0;;
esac
exit 1
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

    # ---------- DEBUG 版會寫的鍵：開前記下、結束後改回 ----------
    def test_save_restore_keys(self):
        store = self.tmp / 'store'
        store.mkdir(exist_ok=True)
        run = self.tmp / 'run keys'
        sbin = self.tmp / 'sbin'
        sbin.mkdir(exist_ok=True)
        shutil.copy(self.bin / 'sdefaults', sbin / 'defaults')
        env = {'PATH': f'{sbin}:/usr/bin:/bin', 'HOME': str(self.tmp), 'STUB_STORE': str(store), 'RUN': str(run)}
        def sh(script):
            p = subprocess.run(['/bin/bash', '-c', f'. "{LIB}"; {script}'], capture_output=True, text=True, env=env)
            return p.returncode, p.stdout + p.stderr
        # 開始前：settingsPage = provider、視窗位置有結尾空白；之後 DEBUG 版改了兩個
        sh('defaults write com.weiwei.shiyin settingsPage -string provider; '
           'defaults write com.weiwei.shiyin "NSWindow Frame main" -string "274 187 1180 780 0 0 1728 1084 "')
        code, msg = sh('save_keys; defaults write com.weiwei.shiyin settingsPage -string recording; '
                       'defaults write com.weiwei.shiyin "NSWindow Frame main" -string "-1550 172 1180 780 -1920 37 1920 1050 "; '
                       'restore_keys; defaults read com.weiwei.shiyin settingsPage; defaults read com.weiwei.shiyin "NSWindow Frame main" | od -c | tail -3')
        self.assertEqual(code, 0, msg)
        self.assertIn('改回：「NSWindow Frame main」', msg)
        self.assertIn('provider', msg)
        code, out = sh('defaults read com.weiwei.shiyin "NSWindow Frame main"')
        self.assertEqual(out, '274 187 1180 780 0 0 1728 1084 \n', '結尾空白也要原樣改回')
        # 開始前沒有的鍵，DEBUG 版寫了：刪掉
        sh('defaults delete com.weiwei.shiyin settingsPage')
        code, msg = sh('save_keys; defaults write com.weiwei.shiyin settingsPage -string x; restore_keys; '
                       'defaults read com.weiwei.shiyin settingsPage')
        self.assertNotEqual(code, 0, msg)
        # 沒變的不動
        code, msg = sh('save_keys; restore_keys')
        self.assertNotIn('改回', msg)

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
