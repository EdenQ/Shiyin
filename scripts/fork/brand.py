#!/usr/bin/env python3
"""fork 的品牌替換（design §F7、DF7）：原始碼照上游寫「拾音」「Shiyin」，建置時換成 fork/brand.json 的名稱。

用法：
  brand.py apply <App.app>             換掉 app 裡的翻譯（各 .lproj 的 .strings、.stringsdict、InfoPlist.strings）、
                                       Info.plist、Credits.html、ThirdPartyLicenses.txt；寫入 Info.plist 的 MABrand；
                                       比對格式碼；最後跑 check（有違規 exit 1）。build-app.sh（含 --debug）呼叫
  brand.py check <App.app>             只檢查建置結果和原始碼，不改檔
  brand.py check-sources               只檢查原始碼：包住字串的最內層呼叫不是查表的，字串裡卻有「拾音」「Shiyin」
                                       （白名單 fork/brand-allow.txt 比對字串全文）
  brand.py crosscheck <stringsdata 資料夾>  用 Swift 編譯器抽出的字串（位置）核對掃描器：放行的每個字串，
                                       編譯器在同一個位置也要抽得到（design §F7.4；合併上游後跑）。產生方式：
                                       swift build … --scratch-path <別的資料夾> --target Shiyin -Xswiftc -emit-localized-strings
                                       -Xswiftc -emit-localized-strings-path -Xswiftc <stringsdata 資料夾>
  測試：python3 scripts/fork/brand-test.py -v
  brand.py guides <輸出資料夾> <html>…   安裝說明換好放到輸出資料夾（make-dmg.sh 呼叫），也會檢查
  brand.py compare <舊.app> <新.app>    逐鍵比對兩個建置的翻譯、Info.plist、Credits（每版跟上一版比；
                                       舊版的鍵是換過品牌的寫法時，先還原成上游的鍵再找）。有差異 exit 1

只用 Python 標準函式庫。repo 裡的翻譯表、Info.plist 都不改。
"""
import json
import plistlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / "fork/brand.json").read_text(encoding="utf-8"))
ALLOW_FILE = ROOT / "fork/brand-allow.txt"
UPSTREAM = re.compile(r"拾音|Shiyin")   # 拾音的簡體寫法也是這兩個字
FORMAT = re.compile(r"%(?:\d+\$)?[-+ #0']*(?:\d+|\*)?(?:\.(?:\d+|\*))?(?:hh|h|ll|l|q|z|t|j|L)?[@dDiuUxXoOfFeEgGcCsSpaA%]")


def names_for(lang):
    """lproj 名稱 → 名稱對照；沒有的語言（日文、韓文等之後才有的）用英文"""
    table = CONFIG["names"]
    if lang == "all":
        merged = {}
        for t in table.values():
            merged.update(t)
        return merged
    return table.get(lang) or table["en"]


def brand(text, lang):
    """phrases（整句換）→ keep（不換）→ 名稱，三種先換成佔位字再還原，互不影響"""
    if not isinstance(text, str) or not UPSTREAM.search(text):
        return text
    slots = []

    def hold(value):
        slots.append(value)
        return f"{len(slots) - 1}"

    for phrase in CONFIG["phrases"]:
        if phrase["from"] in text:
            text = text.replace(phrase["from"], hold(phrase["to"]))
    for pattern in CONFIG["keep"]:
        text = re.sub(pattern, lambda m: hold(m.group(0)), text)
    for old, new in sorted(names_for(lang).items(), key=lambda kv: -len(kv[0])):
        text = text.replace(old, new)
    while "" in text:
        text = re.sub("(\\d+)", lambda m: slots[int(m.group(1))], text)
    return text


def leftover(text):
    """扣掉 keep 之後還剩下的上游名稱"""
    for pattern in CONFIG["keep"]:
        text = re.sub(pattern, "", text)
    return [m.group(0) for m in UPSTREAM.finditer(text)]


def required_problems(target, texts):
    """語意要緊的整句特例（Credits 的署名和贊助、授權開場白、安裝說明的指令和選單名）：brand.json 裡
    `required` 列了這個資源，換完就一定要看得到 `to`。整句對不到時一般的名稱替換會蓋掉失配（例如上游改了一個標點，
    贊助句變成「Enjoying Meeting Assistant?」、署名不見），所以不能只靠「沒有殘留的拾音」判斷。
    檢查的是輸出有沒有 `to`，對已經換過的檔案重跑也成立（冪等）。target 例：en.lproj/Credits.html、guide:install-guide.html"""
    problems = []
    for phrase in CONFIG["phrases"]:
        if target in phrase.get("required", []) and not any(phrase["to"] in t for t in texts):
            problems.append(f"{target}：缺少必要的整句「{phrase['to'][:60]}」（上游的「{phrase['from'][:40]}」對不到，改 fork/brand.json）")
    return problems


def required_targets():
    return sorted({t for phrase in CONFIG["phrases"] for t in phrase.get("required", [])})


def target_texts(app, target):
    """target 在 app 裡的文字；.strings 取所有的值。檔案不存在回傳 None"""
    path = app / "Contents/Resources" / target
    if not path.exists():
        return None
    if path.suffix in (".strings", ".stringsdict") and path.name != "InfoPlist.strings":
        data, _ = load_plist(path)
        return [v for _, v in flatten(data)]
    return [path.read_text(encoding="utf-8")]


# MARK: - apply

class FormatMismatch(Exception):
    pass


def checked(old, new, where):
    if sorted(FORMAT.findall(old)) != sorted(FORMAT.findall(new)):
        raise FormatMismatch(f"{where}：格式碼不同\n  原本：{old}\n  換後：{new}")
    return new


def walk(obj, lang, where, counter):
    if isinstance(obj, str):
        new = brand(obj, lang)
        if new != obj:
            counter[0] += 1
            checked(obj, new, where)
        return new
    if isinstance(obj, dict):
        return {k: (v if k in ("NSStringFormatSpecTypeKey", "NSStringFormatValueTypeKey") else walk(v, lang, f"{where}/{k}", counter))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [walk(v, lang, where, counter) for v in obj]
    return obj


def load_plist(path):
    data = path.read_bytes()
    fmt = plistlib.FMT_BINARY if data.startswith(b"bplist") else plistlib.FMT_XML
    return plistlib.loads(data), fmt


STRINGS_LINE = re.compile(r'^(\s*)"((?:[^"\\]|\\.)*)"(\s*=\s*)"((?:[^"\\]|\\.)*)";(.*)$')


def apply_text_strings(path, lang):
    """InfoPlist.strings（文字格式）：鍵也要換，因為鍵是 Info.plist 的英文值（"Shiyin Meeting"）"""
    special = {"CFBundleName": CONFIG["bundleName"], "CFBundleDisplayName": CONFIG["displayName"].get(lang)}
    out = []
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        m = STRINGS_LINE.match(line)
        if m:
            indent, key, eq, value, rest = m.groups()
            if key in special and special[key]:
                new_key, new_value = key, special[key]
            else:
                new_key, new_value = brand(key, "en"), checked(value, brand(value, lang), f"{path}:{key}")
            if (new_key, new_value) != (key, value):
                count += 1
            line = f'{indent}"{new_key}"{eq}"{new_value}";{rest}'
        out.append(line)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return count


def apply_info_plist(path):
    info, fmt = load_plist(path)
    info["CFBundleName"] = CONFIG["bundleName"]
    info["CFBundleDisplayName"] = CONFIG["displayName"]["en"]
    keys = set(CONFIG["infoPlistBrandKeys"])

    def fix(obj):
        if isinstance(obj, dict):
            return {k: (brand(v, "en") if k in keys and isinstance(v, str) else fix(v)) for k, v in obj.items()}
        if isinstance(obj, list):
            return [fix(v) for v in obj]
        return obj

    info = fix(info)
    info["MABrand"] = {"names": CONFIG["names"], "aboutName": CONFIG["aboutName"]}
    path.write_bytes(plistlib.dumps(info, fmt=fmt, sort_keys=True))


def apply(app):
    res = app / "Contents/Resources"
    report = []
    # 翻譯表編出來的 .strings 有全部的鍵（繁中的值就是鍵），只換值；格式碼數量要一樣
    for lproj in sorted(res.glob("*.lproj")):
        lang = lproj.stem
        for f in sorted(lproj.glob("*.strings")) + sorted(lproj.glob("*.stringsdict")):
            if f.name == "InfoPlist.strings":
                report.append(f"{lproj.name}/{f.name}: {apply_text_strings(f, lang)}")
                continue
            data, fmt = load_plist(f)
            counter = [0]
            data = {k: walk(v, lang, f"{lproj.name}/{f.name}:{k}", counter) for k, v in data.items()}
            f.write_bytes(plistlib.dumps(data, fmt=fmt, sort_keys=False))
            report.append(f"{lproj.name}/{f.name}: {counter[0]}")
        credits = lproj / "Credits.html"
        if credits.exists():
            credits.write_text(brand(credits.read_text(encoding="utf-8"), lang), encoding="utf-8")
    licenses = res / "ThirdPartyLicenses.txt"
    if licenses.exists():
        licenses.write_text(brand(licenses.read_text(encoding="utf-8"), "all"), encoding="utf-8")
    apply_info_plist(app / "Contents/Info.plist")
    print("brand.py：換過的條目 " + "、".join(report))


# MARK: - check

def check_app(app):
    problems = []
    res = app / "Contents/Resources"
    for lproj in sorted(res.glob("*.lproj")):
        for f in sorted(lproj.iterdir()):
            rel = f"{lproj.name}/{f.name}"
            if f.suffix == ".html" or (f.name == "InfoPlist.strings"):
                text = f.read_text(encoding="utf-8")
                if f.name == "InfoPlist.strings":   # 文字格式只看值
                    text = "\n".join(m.group(4) for m in map(STRINGS_LINE.match, text.splitlines()) if m)
                for hit in leftover(text):
                    problems.append(f"{rel}：還有「{hit}」")
            elif f.suffix in (".strings", ".stringsdict"):
                data, _ = load_plist(f)
                for key, value in flatten(data):
                    if leftover(value):
                        problems.append(f"{rel}：{key[:60]} → {value[:80]}")
    licenses = res / "ThirdPartyLicenses.txt"
    if licenses.exists():
        for line in licenses.read_text(encoding="utf-8").splitlines()[:5]:
            if leftover(line):
                problems.append(f"ThirdPartyLicenses.txt：{line[:80]}")
    info, _ = load_plist(app / "Contents/Info.plist")
    identity = set(CONFIG["infoPlistIdentityKeys"])
    for key, value in flatten(info):
        if key.split("/")[-1] in identity or key.split("/")[-2:-1] and key.split("/")[-2] in identity:
            continue
        if key.startswith("MABrand"):
            continue
        if leftover(value):
            problems.append(f"Info.plist：{key} = {value[:80]}")
    if "MABrand" not in info:
        problems.append("Info.plist：沒有 MABrand")
    for target in required_targets():
        if target.startswith("guide:"):
            continue
        texts = target_texts(app, target)
        if texts is None:
            problems.append(f"{target}：建置結果裡沒有這個檔案（brand.json 的 required 指到它）")
        else:
            problems += required_problems(target, texts)
    return problems


def flatten(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from flatten(v, f"{prefix}/{k}" if prefix else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from flatten(v, f"{prefix}/{i}")
    elif isinstance(obj, str):
        yield prefix, obj


# MARK: - 原始碼掃描

# 包住字串的那個呼叫是這些，字串才會查翻譯表（SwiftUI 的 LocalizedStringKey、String(localized:)）
LOOKUP_CALLS = {"Text", "Button", "Toggle", "Label", "Section", "Window", "Menu", "Link", "LabeledContent", "Picker",
                "TextField", "GroupBox", "LocalizedStringKey", "LocalizedStringResource", "help", "alert", "navigationTitle",
                "confirmationDialog", "accessibilityLabel"}
# 這些呼叫要看字串在哪個參數：String(localized: "…")
LOOKUP_LABELED = {"String": "localized"}


class Literal:
    """一個字串常值：位置、原文，和它在哪個呼叫的哪個參數裡"""
    def __init__(self, start, end, body, line, column, frame):
        self.start, self.end, self.body, self.line, self.column = start, end, body, line, column
        self.call = frame["name"] if frame else None
        self.label = frame["label"] if frame else None
        self.arg = (frame["id"], frame["arg"]) if frame else None
        self.arg_start = frame["arg_start"] if frame else None
        self.localized = False


def swift_literals(source):
    """把 Swift 原始碼切成字串常值（Literal），並判斷每一個會不會查翻譯表。
    認得註解、一般／多行／raw 字串、字串插值（插值裡的字串另算一個，包住它的是插值）。
    呼叫是包住字串的「最內層括號」：( 前面的名稱；[ ] 和 { } 也算一層（陣列、字典、closure 裡的字串不查表）。
    查表只放行兩種參數寫法（design §F7.4）：整個參數就是一個字串常值；三元運算兩邊都是字串常值。
    其他運算式（變數、.uppercased()、as String、+ 串接、??、多一層括號）判斷不了型別，一律當成不查表"""
    literals, comments, arg_end = [], [], {}
    frames = []
    counter = [0]
    i, n = 0, len(source)
    line_starts = [0] + [k + 1 for k, ch in enumerate(source) if ch == "\n"]

    def position(pos):
        import bisect
        row = bisect.bisect_right(line_starts, pos) - 1
        return row + 1, len(source[line_starts[row]:pos].encode("utf-8")) + 1   # 欄跟編譯器一樣用 UTF-8 位元組

    def label_at(pos):
        m = re.match(r"\s*([A-Za-z_]\w*)\s*:(?!:)", source[pos:pos + 80])
        return m.group(1) if m else None

    def read_string(start, hashes, multi):
        close = ('"""' if multi else '"') + "#" * hashes
        interp = "\\" + "#" * hashes + "("
        j = start
        while j < n:
            if source.startswith(interp, j):
                return "interp", j + len(interp)
            if source[j] == "\\" and hashes == 0:
                j += 2
                continue
            if source.startswith(close, j):
                return "end", j + len(close)
            j += 1
        return "end", n

    def scan_string(open_pos, body_start, hashes, multi, resume_from, owner):
        kind, j = read_string(resume_from, hashes, multi)
        if kind == "interp":
            frames.append({"name": "\\(", "label": None, "id": -1, "arg": 0, "arg_start": j,
                           "interp": (open_pos, body_start, hashes, multi, owner)})
            return j
        line, column = position(open_pos)
        body = source[body_start:j - len('"""' if multi else '"') - hashes]
        literals.append(Literal(open_pos, j, body, line, column, owner))
        return j

    def open_frame(name, pos):
        counter[0] += 1
        frames.append({"name": name, "label": label_at(pos), "id": counter[0], "arg": 0, "arg_start": pos, "interp": None})

    while i < n:
        c = source[i]
        if source.startswith("//", i):
            j = source.find("\n", i)
            j = n if j < 0 else j
            comments.append((i, j))
            i = j
            continue
        if source.startswith("/*", i):   # Swift 的 /* */ 可以巢狀
            depth, j = 1, i + 2
            while j < n and depth:
                if source.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif source.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            comments.append((i, j))
            i = j
            continue
        m = re.match(r'(#*)("""|")', source[i:i + 12])
        if m and (m.group(1) or c == '"'):
            body = i + m.end()
            owner = frames[-1] if frames else None
            owner = dict(owner) if owner else None   # 記下當時的參數（標籤、第幾個）
            i = scan_string(i, body, len(m.group(1)), m.group(2) == '"""', body, owner)
            continue
        if c == "(":
            m2 = re.search(r"([A-Za-z_]\w*)\s*$", source[max(0, i - 60):i])
            open_frame(m2.group(1) if m2 else "(", i + 1)
            i += 1
            continue
        if c in "[{":
            open_frame(c, i + 1)
            frames[-1]["label"] = None
            i += 1
            continue
        if c in ")]}":
            if frames:
                f = frames.pop()
                if f["interp"]:
                    open_pos, body_start, hashes, multi, owner = f["interp"]
                    i = scan_string(open_pos, body_start, hashes, multi, i + 1, owner)
                    continue
                arg_end[(f["id"], f["arg"])] = i
            i += 1
            continue
        if c == "," and frames and frames[-1]["id"] > 0:
            f = frames[-1]
            arg_end[(f["id"], f["arg"])] = i
            f["arg"] += 1
            f["arg_start"] = i + 1
            f["label"] = label_at(i + 1) if f["name"] not in "[{" else None
        i += 1

    # 參數的文字：註解換成空白（位置不變），去掉開頭的「標籤:」
    blank = list(source)
    for a, b in comments:
        for k in range(a, b):
            if blank[k] != "\n":
                blank[k] = " "
    blanked = "".join(blank)
    by_arg = {}
    for lit in literals:
        if lit.arg:
            by_arg.setdefault(lit.arg, []).append(lit)
    for key, lits in by_arg.items():
        end = arg_end.get(key)
        if end is None:
            continue
        start = lits[0].arg_start
        text = blanked[start:end]
        label = re.match(r"\s*[A-Za-z_]\w*\s*:(?!:)", text)
        offset = start + (label.end() if label else 0)
        if not lookup_argument(lits[0]):
            continue
        parts = [(l.start - offset, l.end - offset) for l in lits]
        body = blanked[offset:end]
        if argument_is_literal_key(body, parts):
            for l in lits:
                l.localized = True
    return literals


def lookup_argument(lit):
    """字串所在的參數是不是查表的參數：查表呼叫的第一個沒有標籤的參數，或 String(localized:)"""
    if lit.call in LOOKUP_LABELED:
        return lit.label == LOOKUP_LABELED[lit.call]
    return lit.call in LOOKUP_CALLS and lit.label is None and lit.arg[1] == 0


def argument_is_literal_key(body, parts):
    """整個參數是一個字串常值，或「條件 ? 常值 : 常值」（條件裡不能有字串）"""
    stripped = body.strip()
    if len(parts) == 1:
        a, b = parts[0]
        return body[:a].strip() == "" and body[b:].strip() == ""
    if len(parts) == 2:
        (a1, b1), (a2, b2) = parts
        before, middle, after = body[:a1].rstrip(), body[b1:a2].strip(), body[b2:].strip()
        return (before.endswith("?") and not before.endswith("??") and before[:-1].strip() != ""
                and "?" not in before[:-1] and middle == ":" and after == "")
    return stripped == "" and False


def literal_is_localized(lit, line):
    """字串會不會查翻譯表：swift_literals 判斷過的寫法，而且那行沒有 l10n-skip"""
    return lit.localized and "// l10n-skip" not in line


def load_allow(allow_file=None):
    """白名單：<路徑（可用 *）> | <字串常值的全文>；全文結尾寫「…」表示開頭相同就算"""
    rules = []
    allow_file = allow_file or ALLOW_FILE
    if allow_file.exists():
        for line in allow_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                path, _, text = line.partition(" | ")
                rules.append((path.strip(), text.strip()))
    return rules


def allow_matches(rule, rel, literal):
    if not fnmatch_path(rel, rule[0]):
        return False
    text = rule[1]
    return literal.startswith(text[:-1]) if text.endswith("…") else literal == text


def check_sources(root=None, allow_file=None):
    root = root or ROOT
    allow = load_allow(allow_file)
    used = set()
    problems = []
    for f in sorted((root / "Sources").rglob("*.swift")):
        rel = str(f.relative_to(root))
        source = f.read_text(encoding="utf-8")
        lines = source.splitlines()
        for lit in swift_literals(source):
            no, literal, name = lit.line, lit.body, lit.call
            if not leftover(literal):
                continue
            if literal_is_localized(lit, lines[no - 1] if no <= len(lines) else ""):
                continue
            rule = next((r for r in allow if allow_matches(r, rel, literal)), None)
            if rule:
                used.add(rule)
                continue
            problems.append(f"{rel}:{no}：不經過翻譯表的品牌字 \"{literal[:70]}\"（包住它的是 {name or '沒有呼叫'}）")
    for rule in allow:
        if rule not in used:
            problems.append(f"fork/brand-allow.txt：用不到的白名單 {rule[0]} | {rule[1]}（原始碼改了的話一起刪）")
    return problems


def crosscheck(stringsdata_dir, root=None):
    """掃描器放行、編譯器卻沒抽出的品牌字串 → 掃描器有漏洞（problems）；編譯器抽出、掃描器報錯的只列出來（保守）"""
    root = (root or ROOT).resolve()
    extracted = {}
    for f in Path(stringsdata_dir).glob("*.stringsdata"):
        data = json.loads(f.read_text(encoding="utf-8"))
        source = Path(data.get("source", "")).resolve()
        for entries in data.get("tables", {}).values():
            for e in entries:
                extracted.setdefault(source, set()).add((e["location"]["startingLine"], e["location"]["startingColumn"]))
    if not extracted:
        return [f"{stringsdata_dir}：沒有 stringsdata"], [], 0
    problems, conservative, passed = [], [], 0
    for f in sorted((root / "Sources").rglob("*.swift")):
        locations = extracted.get(f.resolve(), set())
        for lit in swift_literals(f.read_text(encoding="utf-8")):
            if not UPSTREAM.search(lit.body):
                continue
            hit = (lit.line, lit.column) in locations
            where = f"{f.relative_to(root)}:{lit.line}:{lit.column} \"{lit.body[:60]}\""
            if lit.localized:
                passed += 1
                if not hit:
                    problems.append(f"{where}：掃描器放行，編譯器卻沒有抽出（不查表）")
            elif hit:
                conservative.append(where)
    return problems, conservative, passed


def fnmatch_path(path, pattern):
    from fnmatch import fnmatch
    return fnmatch(path, pattern)


def report(problems, what):
    if problems:
        print(f"brand.py check：{what}有 {len(problems)} 個問題", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        return 1
    print(f"brand.py check：{what} 0 個違規")
    return 0


# MARK: - compare

def unbrand_key(key):
    """4.7.6 以前的鍵是 fork 直接寫在原始碼的「會議助手」：還原成上游的寫法"""
    for phrase in CONFIG["phrases"]:
        key = key.replace(phrase["to"], phrase["from"])
    for table in CONFIG["names"].values():
        for old, new in table.items():
            key = key.replace(new, old)
    return key


def bundle_strings(app):
    """{(檔案, 鍵): 值}：各 lproj 的 Localizable.strings、.stringsdict（攤平）、InfoPlist.strings，加上 Info.plist"""
    out = {}
    res = app / "Contents/Resources"
    for lproj in sorted(res.glob("*.lproj")):
        for f in sorted(lproj.iterdir()):
            rel = f"{lproj.name}/{f.name}"
            if f.name == "InfoPlist.strings":
                for m in map(STRINGS_LINE.match, f.read_text(encoding="utf-8").splitlines()):
                    if m:
                        out[(rel, m.group(2))] = m.group(4)
            elif f.suffix in (".strings", ".stringsdict"):
                data, _ = load_plist(f)
                for k, v in flatten(data):
                    out[(rel, k)] = v
            elif f.suffix == ".html":
                out[(rel, "")] = f.read_text(encoding="utf-8")
    licenses = res / "ThirdPartyLicenses.txt"
    if licenses.exists():
        out[("ThirdPartyLicenses.txt", "")] = licenses.read_text(encoding="utf-8")
    info, _ = load_plist(app / "Contents/Info.plist")
    for k, v in flatten(info):
        out[("Info.plist", k)] = v
    return out


def compare(old_app, new_app):
    old, new = bundle_strings(old_app), bundle_strings(new_app)
    skip = {"CFBundleShortVersionString", "CFBundleVersion"}
    diffs, matched, seen = [], 0, set()
    for (rel, key), value in sorted(old.items()):
        if rel == "Info.plist" and (key in skip or key.startswith("MABrand")):
            continue
        cand = [(rel, key), (rel, unbrand_key(key))]
        if rel.endswith("InfoPlist.strings"):
            cand.append((rel, unbrand_key(key).replace("會議助手", "Shiyin").replace("Meeting Assistant", "Shiyin")))
        hit = next((c for c in cand if c in new), None)
        if hit is None:
            diffs.append(f"只有舊版：{rel} {key[:70]} = {value[:70]}")
            continue
        seen.add(hit)
        if new[hit] == value:
            matched += 1
        else:
            diffs.append(f"值不同：{rel} {key[:70]}\n    舊：{value[:160]}\n    新：{new[hit][:160]}")
    for (rel, key), value in sorted(new.items()):
        if (rel, key) not in seen and not (rel == "Info.plist" and (key in skip or key.startswith("MABrand"))):
            diffs.append(f"只有新版：{rel} {key[:70]} = {value[:70]}")
    print(f"brand.py compare：相同 {matched} 條，差異 {len(diffs)} 條")
    for d in diffs:
        print("  " + d)
    return 1 if diffs else 0


def main(argv):
    if len(argv) >= 2 and argv[0] == "apply":
        app = Path(argv[1])
        try:
            apply(app)
        except FormatMismatch as e:
            print(f"brand.py：{e}", file=sys.stderr)
            return 1
        return report(check_app(app) + check_sources(), "建置結果和原始碼")
    if len(argv) >= 2 and argv[0] == "check":
        return report(check_app(Path(argv[1])) + check_sources(), "建置結果和原始碼")
    if len(argv) >= 3 and argv[0] == "compare":
        return compare(Path(argv[1]), Path(argv[2]))
    if len(argv) >= 2 and argv[0] == "crosscheck":
        problems, conservative, passed = crosscheck(argv[1])
        print(f"brand.py crosscheck：掃描器放行 {passed} 個品牌字串；編譯器抽出、掃描器保守報錯的 {len(conservative)} 個")
        for c in conservative:
            print("  保守：" + c)
        return report(problems, "掃描器對照編譯器")
    if argv[:1] == ["check-sources"]:
        return report(check_sources(), "原始碼")
    if len(argv) >= 3 and argv[0] == "guides":
        out = Path(argv[1])
        out.mkdir(parents=True, exist_ok=True)
        problems = []
        for src in map(Path, argv[2:]):
            text = src.read_text(encoding="utf-8")
            lang = (re.search(r'<html lang="([^"]+)"', text) or [None, "en"])[1]
            new = brand(text, lang)
            (out / src.name).write_text(new, encoding="utf-8")
            problems += [f"{src.name}：還有「{h}」" for h in leftover(new)]
            problems += required_problems(f"guide:{src.name}", [new])
        return report(problems, "安裝說明")
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
