#!/usr/bin/env python3
"""brand.py 的回歸測試（fork design §F7.5）：python3 scripts/fork/brand-test.py [-v]

- 原始碼掃描：只認包住字串的那個查表呼叫（REVIEW-0b-brand P2-1 的 ReviewBrandProbe），真正跨行的查表呼叫要放過
- 整句特例：Credits、授權開場白、安裝說明的整句對不到時要失敗（P2-2 的標點漂移），對換過的產物重跑不變（冪等）
- 漏換、格式碼不同要失敗

只用標準函式庫；所有檔案放在暫存資料夾，不碰 repo 和使用者的 app。
"""
import html
import importlib.util
import json
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True   # import brand.py 時不要在 repo 留 __pycache__
ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / "scripts/fork/brand.py"
spec = importlib.util.spec_from_file_location("brand", BRAND)
brand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brand)
KOFI = "https://ko-fi.com/weiwei_chang"


def run(*args):
    p = subprocess.run([sys.executable, str(BRAND), *map(str, args)], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


class SourceScan(unittest.TestCase):
    def scan(self, swift, allow=""):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Sources/Shiyin/Views").mkdir(parents=True)
            (root / "Sources/Shiyin/Views/Probe.swift").write_text(swift, encoding="utf-8")
            (root / "allow.txt").write_text(allow, encoding="utf-8")
            return brand.check_sources(root=root, allow_file=root / "allow.txt")

    def test_review_probe_nearby_text_does_not_excuse(self):
        """P2-1：前一行有 Text("…")，下一個不查表的字串照樣要報"""
        problems = self.scan('''import SwiftUI
struct ReviewBrandProbe: View {
    var body: some View {
        let _ = Text("Nearby localized text")
        let message = "Shiyin unlocalized brand probe"
        return Text(verbatim: message)
    }
}
''')
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("Shiyin unlocalized brand probe", problems[0])

    def test_real_multiline_lookup_passes(self):
        """跨行的查表呼叫（三元運算、修飾元、插值）不算違規"""
        problems = self.scan('''import SwiftUI
struct Probe: View {
    let tagged = true
    let count = 2
    var body: some View {
        Text(tagged
             ? "拾音標記的名字"
             : "拾音認出的名字")
            .help(tagged ? "Shiyin 1" : "Shiyin 2")
        Button("結束拾音") { }
        Text(Brand.short(String(localized: "打開拾音")))
        Window("拾音", id: "main")
    }
    func message() -> String {
        String(localized: "拾音試了 \\(count) 次，\\(tagged ? "a" : "b")")
    }
    func multiline() -> String {
        String(
            localized: "拾音跨行的參數"
        )
    }
    // 註解裡的 "拾音" 不算
    /* "Shiyin" 也不算 */
    /* 巢狀 /* "拾音 inner" */ "Shiyin outer" */
}
''')
        self.assertEqual(problems, [])

    def test_unlocalized_forms_are_reported(self):
        problems = self.scan('''import SwiftUI
struct Probe: View {
    let suffix = ""
    let name: String? = nil
    var body: some View {
        Text("拾音" + suffix)
        Text(verbatim: "拾音 verbatim")
        Text(name ?? "拾音 fallback")
        Text(["拾音 陣列"].joined())
        Text(MeetingLanguage.ui(zh: "拾音 ui", en: "Shiyin ui"))
    }
    func a() -> String { String(format: "拾音 %@", suffix) }
    func b() -> String { String(localized: "x \\(MeetingLanguage.ui(zh: "拾音 插值", en: "a"))") }
    func c() -> String { #"拾音 raw"# }
    func d() -> String {
        """
        拾音 多行
        """
    }
    func e() -> String { String(localized: "拾音 skip") }  // l10n-skip
}
''')
        found = "\n".join(problems)
        for text in ["拾音\"", "拾音 verbatim", "拾音 fallback", "拾音 陣列", "拾音 ui", "Shiyin ui",
                     "拾音 %@", "拾音 插值", "拾音 raw", "拾音 多行", "拾音 skip"]:
            self.assertIn(text, found, f"沒抓到 {text}")
        self.assertEqual(len(problems), 11, found)

    def test_review2_string_expressions_are_reported(self):
        """複審 P2-3：呼叫是 Text，但參數其實是 String 運算式，不會查表，要報"""
        problems = self.scan('''import SwiftUI
struct Probe: View {
    let flag = true
    let supplied = ""
    var body: some View {
        Text(flag ? supplied : "Shiyin variable alternative")
        Text("Shiyin transform".uppercased())
        Text("Shiyin comment concat" /* note */ + supplied)
        Text("Shiyin cast" as String)
        Text(flag ? "Shiyin both a" : supplied)
        Text(supplied.isEmpty ? "Shiyin opt" : "x" + supplied)
        Text("Shiyin line comment" // 註解
             + supplied)
    }
}
''')
        found = "\n".join(problems)
        for text in ["Shiyin variable alternative", "Shiyin transform", "Shiyin comment concat", "Shiyin cast",
                     "Shiyin both a", "Shiyin opt", "Shiyin line comment"]:
            self.assertIn(text, found, f"沒抓到 {text}")
        self.assertEqual(len(problems), 7, found)

    def test_supported_boundary(self):
        """fork design §F7.4 的語法邊界：放行的寫法"""
        problems = self.scan('''import SwiftUI
struct Probe: View {
    let flag = true
    var body: some View {
        Text(flag ? "Shiyin literal first" : "Shiyin literal second")
        Text(flag /* 註解 */ ? "Shiyin c1" : /* 註解 */ "Shiyin c2")
        Text("Shiyin modifier").font(.title)
        Button("Shiyin button", role: .destructive) { }
        Label("Shiyin label", systemImage: "star")
    }
    func s() -> String { String(localized: "Shiyin \\(flag ? 1 : 2) 次") }
}
''')
        self.assertEqual(problems, [])

    def test_conservative_boundary_reported(self):
        """fork design §F7.4 的語法邊界：編譯器其實會查表，但掃描器不認得、保守報錯的寫法（要用白名單或改寫）"""
        swift = '''import SwiftUI
struct CustomLookup: View {
    let key: LocalizedStringKey
    init(_ key: LocalizedStringKey) { self.key = key }
    var body: some View { Text(key) }
}
struct Probe: View {
    var body: some View {
        CustomLookup("Shiyin custom key")
        Text(("Shiyin parenthesized"))
        Text(String(localized: "opaque key", defaultValue: "Shiyin localized default"))
        Text(LocalizedStringKey(stringLiteral: "Shiyin literal key"))
    }
}
'''
        problems = self.scan(swift)
        found = "\n".join(problems)
        for text in ["Shiyin custom key", "Shiyin parenthesized", "Shiyin localized default", "Shiyin literal key"]:
            self.assertIn(text, found, f"沒抓到 {text}")
        self.assertEqual(len(problems), 4, found)
        allowed = self.scan(swift, "Sources/Shiyin/Views/Probe.swift | Shiyin custom key\n")
        self.assertEqual(len(allowed), 3, allowed)   # 白名單只放過自訂 View 那一個

    def test_allowlist_is_exact_per_literal(self):
        swift = '''func f() {
    let a = Path("Shiyin")
    let b = Path("Shiyin.app")
    let c = log("Reading meetings is turned off in Shiyin. Ask the user…")
}
'''
        allow = ("Sources/Shiyin/Views/Probe.swift | Shiyin\n"
                 "Sources/Shiyin/Views/Probe.swift | Reading meetings is turned off in Shiyin.…\n"
                 "Sources/Shiyin/Views/Probe.swift | Shiyin 不存在的字串\n")
        problems = self.scan(swift, allow)
        found = "\n".join(problems)
        self.assertIn('"Shiyin.app"', found)            # 白名單的 Shiyin 不會放過同一行之外的其他字串
        self.assertIn("用不到的白名單", found)
        self.assertEqual(len(problems), 2, found)

    def test_repo_sources_clean(self):
        self.assertEqual(brand.check_sources(), [])


class CompilerCrossCheck(unittest.TestCase):
    """掃描器放行的每個字串，Swift 編譯器（-emit-localized-strings）在同一個位置也要抽得出來：
    證明「放行＝真的查表」。編譯器沒有的話略過（CI 的 macOS runner 有）"""

    PROBE = '''import SwiftUI
struct CustomLookup: View {
    let key: LocalizedStringKey
    init(_ key: LocalizedStringKey) { self.key = key }
    var body: some View { Text(key) }
}
struct CompilerProbe: View {
    let flag: Bool
    let supplied: String
    var body: some View {
        VStack {
            Text(flag ? "Shiyin literal first" : "Shiyin literal second")
            Text(flag ? supplied : "Shiyin variable alternative")
            CustomLookup("Shiyin custom key")
            Text("Shiyin transform".uppercased())
            Text("Shiyin comment concat" /* note */ + supplied)
            Text("Shiyin cast" as String)
            Text(String(localized: "opaque key", defaultValue: "Shiyin localized default"))
            Text("拾音 plain")
            Text(verbatim: "拾音 verbatim")
            Text("拾音" + supplied)
            Text(flag /* c */ ? "拾音 c1" : "拾音 c2")
            Button("拾音 button") { }
            Label("拾音 label", systemImage: "star")
            Toggle("拾音 toggle", isOn: .constant(true))
            Text(("拾音 parenthesized"))
            Text(supplied ?? "拾音 fallback")
        }
        .help("拾音 help")
        .navigationTitle(flag ? "拾音 nav1" : "拾音 nav2")
    }
    func message(_ n: Int) -> String { String(localized: "拾音 \\(n) 次") }
    func other() -> String { MeetingLanguageStub.ui(zh: "拾音 ui", en: "Shiyin ui") }
}
enum MeetingLanguageStub { static func ui(zh: String, en: String) -> String { zh } }
'''

    def test_scanner_passes_only_what_compiler_extracts(self):
        import shutil as sh
        swiftc = sh.which("swiftc")
        if not swiftc:
            self.skipTest("沒有 swiftc")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "Sources").mkdir()
            src = tmp / "Sources/CompilerProbe.swift"
            src.write_text(self.PROBE.replace("supplied ?? ", "Optional(supplied) ?? "), encoding="utf-8")
            out = tmp / "strings"
            p = subprocess.run([swiftc, "-parse-as-library", "-emit-module", "-module-name", "CompilerProbe",
                                "-module-cache-path", str(tmp / "mc"), "-emit-localized-strings",
                                "-emit-localized-strings-path", str(out), "-emit-module-path", str(tmp / "P.swiftmodule"),
                                str(src)], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr[-2000:])
            data = json.loads(next(out.glob("*.stringsdata")).read_text(encoding="utf-8"))
            extracted = {(e["location"]["startingLine"], e["location"]["startingColumn"])
                         for entries in data["tables"].values() for e in entries}
            literals = [l for l in brand.swift_literals(src.read_text(encoding="utf-8")) if brand.UPSTREAM.search(l.body)]
            passed = [l for l in literals if l.localized]
            for l in passed:
                self.assertIn((l.line, l.column), extracted, f"掃描器放行、編譯器卻沒抽出：{l.body}")
            # 編譯器沒抽出的品牌字串，掃描器一定要報
            for l in literals:
                if (l.line, l.column) not in extracted:
                    self.assertFalse(l.localized, l.body)
            self.assertGreaterEqual(len(passed), 10)   # 正向的寫法真的有被放行（不是全部報錯）
            problems, conservative, count = brand.crosscheck(out, root=tmp)   # brand.py crosscheck 同一套
            self.assertEqual(problems, [])
            self.assertEqual(count, len(passed))
            # 編譯器會查表、掃描器保守報錯的：自訂 LocalizedStringKey 的 View、多一層括號（defaultValue 的位置不是鍵，編譯器抽的是鍵）
            self.assertEqual(len(conservative), 2, conservative)



class Phrases(unittest.TestCase):
    """用最小的假 app（照 build-app.sh 的 Credits 寫法、repo 的翻譯和授權）跑 apply"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.app = self.tmp / "T.app"
        res = self.app / "Contents/Resources"
        for lang in ("en", "zh-Hant", "zh-Hans"):
            (res / f"{lang}.lproj").mkdir(parents=True)
        shutil.copy(ROOT / "Resources/Info.plist", self.app / "Contents/Info.plist")
        licenses = (ROOT / "Resources/ThirdPartyLicenses.txt").read_text(encoding="utf-8")
        (res / "ThirdPartyLicenses.txt").write_text(licenses, encoding="utf-8")
        sponsor = {"zh-Hant": f'覺得拾音好用的話，可以<a href="{KOFI}">請我喝杯咖啡</a>。',
                   "zh-Hans": f'觉得拾音好用的话，可以<a href="{KOFI}">请我喝杯咖啡</a>。',
                   "en": f'Enjoying Shiyin? <a href="{KOFI}">Buy me a coffee</a>.'}
        for lang, line in sponsor.items():
            (res / f"{lang}.lproj/Credits.html").write_text(
                f'<!doctype html><html lang="{lang}"><meta charset="utf-8"><p>{line}</p><pre>{html.escape(licenses)}</pre>',
                encoding="utf-8")
        catalog = json.loads((ROOT / "Resources/Localizable.xcstrings").read_text(encoding="utf-8"))["strings"]
        key = next(k for k in catalog if "「拾音」選單" in k)
        en = catalog[key]["localizations"]["en"]["stringUnit"]["value"]
        hans = catalog[key]["localizations"]["zh-Hans"]["stringUnit"]["value"]
        (res / "zh-Hant.lproj/Localizable.strings").write_bytes(plistlib.dumps({key: key, "結束拾音": "結束拾音", "打開拾音": "打開拾音"}))
        (res / "en.lproj/Localizable.strings").write_bytes(plistlib.dumps({key: en, "結束拾音": "Quit Shiyin", "打開拾音": "Open Shiyin"}))
        (res / "zh-Hans.lproj/Localizable.strings").write_bytes(plistlib.dumps({key: hans, "結束拾音": "退出拾音", "打開拾音": "打开拾音"}))
        self.res = res

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def edit(self, rel, old, new):
        p = self.res / rel
        text = p.read_text(encoding="utf-8")
        self.assertIn(old, text)
        p.write_text(text.replace(old, new), encoding="utf-8")

    def test_apply_then_rerun_is_idempotent(self):
        code, out = run("apply", self.app)
        self.assertEqual(code, 0, out)
        credits = (self.res / "en.lproj/Credits.html").read_text(encoding="utf-8")
        self.assertIn("based on Shiyin, an open-source app by juinwei7", credits)
        self.assertIn("Meeting Assistant uses the following open-source software", credits)
        zh = plistlib.loads((self.res / "zh-Hant.lproj/Localizable.strings").read_bytes())
        self.assertIn("結束會議助手", zh.values())
        before = {p: p.read_bytes() for p in self.res.rglob("*") if p.is_file()}
        code, out = run("apply", self.app)
        self.assertEqual(code, 0, out)
        after = {p: p.read_bytes() for p in self.res.rglob("*") if p.is_file()}
        self.assertEqual(before, after, "重跑 apply 改了檔案")

    def test_review_en_credits_punctuation_drift_fails(self):
        """P2-2：上游贊助句的句點改成驚嘆號，不能默默變成「Enjoying Meeting Assistant?」"""
        self.edit("en.lproj/Credits.html", "Buy me a coffee</a>.", "Buy me a coffee</a>!")
        code, out = run("apply", self.app)
        self.assertEqual(code, 1, out)
        self.assertIn("en.lproj/Credits.html：缺少必要的整句", out)

    def test_zh_credits_drift_fails(self):
        self.edit("zh-Hant.lproj/Credits.html", "請我喝杯咖啡</a>。", "請我喝杯咖啡</a>！")
        code, out = run("apply", self.app)
        self.assertEqual(code, 1, out)
        self.assertIn("zh-Hant.lproj/Credits.html：缺少必要的整句", out)

    def test_island_short_name_only_at_runtime(self):
        """F7.7：錄音島的「打開 MA」在執行時由 Brand.short 換；翻譯表裡同一條鍵（選單列也在用）照舊是完整名稱，
        簡稱寫進 Info.plist 的 MABrand"""
        code, out = run("apply", self.app)
        self.assertEqual(code, 0, out)
        values = {lang: plistlib.loads((self.res / f"{lang}.lproj/Localizable.strings").read_bytes())["打開拾音"]
                  for lang in ("zh-Hant", "zh-Hans", "en")}
        self.assertEqual(values, {"zh-Hant": "打開會議助手", "zh-Hans": "打开会议助手", "en": "Open Meeting Assistant"})
        info = plistlib.loads((self.app / "Contents/Info.plist").read_bytes())
        self.assertEqual(info["MABrand"]["shortName"], "MA")

    def test_zh_hans_credits_drift_fails(self):
        """上游 4.8 起有簡體的 Credits：贊助句漂移也要失敗"""
        self.edit("zh-Hans.lproj/Credits.html", "请我喝杯咖啡</a>。", "请我喝杯咖啡</a>！")
        code, out = run("apply", self.app)
        self.assertEqual(code, 1, out)
        self.assertIn("zh-Hans.lproj/Credits.html：缺少必要的整句", out)

    def test_license_header_drift_fails(self):
        self.edit("ThirdPartyLicenses.txt", "Shiyin uses the following open-source software", "Shiyin uses these open-source packages")
        code, out = run("apply", self.app)
        self.assertEqual(code, 1, out)
        self.assertIn("ThirdPartyLicenses.txt：缺少必要的整句", out)

    def test_missing_required_file_fails_check(self):
        run("apply", self.app)
        (self.res / "en.lproj/Credits.html").unlink()
        code, out = run("check", self.app)
        self.assertEqual(code, 1, out)
        self.assertIn("en.lproj/Credits.html：建置結果裡沒有這個檔案", out)

    def test_leftover_brand_fails(self):
        run("apply", self.app)
        p = self.res / "zh-Hant.lproj/Localizable.strings"
        data = plistlib.loads(p.read_bytes())
        data["測試鍵"] = "拾音漏換的字串"
        p.write_bytes(plistlib.dumps(data))
        code, out = run("check", self.app)
        self.assertEqual(code, 1, out)
        self.assertIn("拾音漏換的字串", out)

    def test_format_mismatch_raises(self):
        saved = brand.CONFIG["names"]["zh-Hant"]
        try:
            brand.CONFIG["names"]["zh-Hant"] = {"拾音": "%@"}
            with self.assertRaises(brand.FormatMismatch):
                brand.checked("要結束拾音嗎？", brand.brand("要結束拾音嗎？", "zh-Hant"), "test")
        finally:
            brand.CONFIG["names"]["zh-Hant"] = saved


class Guides(unittest.TestCase):
    def guides(self, edit=None):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            srcs = []
            for name in ("install-guide.html", "install-guide.en.html"):
                text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
                if edit and edit[0] == name:
                    self.assertIn(edit[1], text)
                    text = text.replace(edit[1], edit[2])
                (tmp / "src").mkdir(exist_ok=True)
                (tmp / "src" / name).write_text(text, encoding="utf-8")
                srcs.append(tmp / "src" / name)
            code, out = run("guides", tmp / "out", *srcs)
            again = run("guides", tmp / "out2", *[tmp / "out" / s.name for s in srcs]) if code == 0 else None
            same = again and all((tmp / "out" / s.name).read_bytes() == (tmp / "out2" / s.name).read_bytes() for s in srcs)
            return code, out, again, same

    def test_guides_ok_and_idempotent(self):
        code, out, again, same = self.guides()
        self.assertEqual(code, 0, out)
        self.assertEqual(again[0], 0, again[1])
        self.assertTrue(same)

    def test_menu_name_drift_fails(self):
        code, out, _, _ = self.guides(("install-guide.html", "也可以從「拾音」選單選", "也可以從『拾音』選單選"))
        self.assertEqual(code, 1, out)
        self.assertIn("guide:install-guide.html：缺少必要的整句", out)

    def test_quarantine_command_drift_fails(self):
        code, out, _, _ = self.guides(("install-guide.en.html", "/Applications/Shiyin.app", "/Applications/Shiyin*.app"))
        self.assertEqual(code, 1, out)
        self.assertIn("guide:install-guide.en.html：缺少必要的整句", out)


if __name__ == "__main__":
    unittest.main()
