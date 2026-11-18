#!/usr/bin/env python3
"""fork 的品牌替換（design §F7、DF7）：原始碼照上游寫「拾音」「Shiyin」，建置時換成 fork/brand.json 的名稱。

用法：
  brand.py apply <App.app>             換掉 app 裡的翻譯（各 .lproj 的 .strings、.stringsdict、InfoPlist.strings）、
                                       Info.plist、Credits.html、ThirdPartyLicenses.txt；寫入 Info.plist 的 MABrand；
                                       比對格式碼；最後跑 check（有違規 exit 1）。build-app.sh（含 --debug）呼叫
  brand.py check <App.app>             只檢查建置結果和原始碼，不改檔
  brand.py check-sources               只檢查原始碼：不經過翻譯表的地方寫了「拾音」「Shiyin」（白名單 fork/brand-allow.txt）
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

    for old, new in CONFIG["phrases"]:
        if old in text:
            text = text.replace(old, hold(new))
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


# 原始碼：這些寫法會查翻譯表，品牌字交給 apply 換
LOCALIZED = re.compile(r'String\(localized:|LocalizedStringKey|\b(?:Text|Button|Toggle|Label|Section|Window|Menu|Link|LabeledContent|Picker|TextField|GuideBullet|GroupBox)\((?!verbatim)|\.(?:help|alert|navigationTitle|confirmationDialog|accessibilityLabel)\(')
NOT_LOCALIZED = re.compile(r'verbatim:|\bui\(zh:|\.text\(zh:|prompt\(zh:|format\(zh:|// l10n-skip|"\s*\+|\+\s*"')
LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"')


def load_allow():
    rules = []
    if ALLOW_FILE.exists():
        for line in ALLOW_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                path, _, text = line.partition(" | ")
                rules.append((path.strip(), text.strip()))
    return rules


def check_sources():
    allow = load_allow()
    used = set()
    problems = []
    for f in sorted((ROOT / "Sources").rglob("*.swift")):
        rel = str(f.relative_to(ROOT))
        lines = f.read_text(encoding="utf-8").splitlines()
        for no, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("///") or stripped.startswith("*"):
                continue
            hits = [lit for lit in LITERAL.findall(line) if UPSTREAM.search(lit)]
            if not hits:
                continue
            # 跨行的呼叫（三元運算的第二行）：往上看兩行有沒有查表的呼叫
            context = "\n".join(lines[max(0, no - 3):no])
            localized = LOCALIZED.search(context) and not NOT_LOCALIZED.search(line)
            if localized:
                continue
            for lit in hits:
                if not leftover(lit):
                    continue
                rule = next((r for r in allow if fnmatch_path(rel, r[0]) and r[1] in line), None)
                if rule:
                    used.add(rule)
                    continue
                problems.append(f"{rel}:{no}：不經過翻譯表的品牌字 \"{lit[:70]}\"")
    for rule in allow:
        if rule not in used:
            problems.append(f"fork/brand-allow.txt：用不到的白名單 {rule[0]} | {rule[1]}（原始碼改了的話一起刪）")
    return problems


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
    for old, new in CONFIG["phrases"]:
        key = key.replace(new, old)
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
        return report(problems, "安裝說明")
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
