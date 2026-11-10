#!/usr/bin/env python3
"""紀錄條列頁（fork F4，design §F4.6）的驗證：議題帶依重點時間切段、分段複製的格式。

要先用暫存的 SHIYIN_HOME 開 DEBUG 版，並 `shiyinctl seedfixtures shared/golden/fixtures.json zh en ja`。
用法：scripts/dev/f4-check.py <SHIYIN_HOME> [shiyinctl 路徑]
全部通過時 exit 0，否則列出不符的地方、exit 1。
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time

HOME = sys.argv[1]
CTL = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser("~/Library/Caches/ShiyinBuild/shiyinctl")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
failures = []


def ctl(*args, output):
    if os.path.exists(output):
        os.remove(output)
    subprocess.run([CTL, *args], check=True, stdout=subprocess.DEVNULL)
    for _ in range(100):
        if os.path.exists(output) and os.path.getsize(output) > 0:
            time.sleep(0.1)
            return
        time.sleep(0.1)
    raise SystemExit(f"{args[0]} 沒有寫出 {output}（DEBUG 版有開嗎？）")


def topic(title, start, points):
    return {"title": title, "start": start, "points": [{"text": f"{title}-{i}", "time": t} for i, t in enumerate(points)]}


def notes(*topics):
    return {"title": "t", "topics": list(topics)}


def mmss(s):
    return f"{s // 60:02d}:{s % 60:02d}" if s < 3600 else f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


# ── 議題帶依重點時間切段（§F4.2）────────────────────────────────
# expect：[(branch, start, end)]；"ranges" 表示要跟現在的 topicRanges 一樣
cases = [
    ("沒有重回＝現在的規則", 1800, notes(topic("A", "00:00", ["01:00", "05:00"]), topic("B", "10:00", ["11:00", "19:59"]),
                                    topic("C", "20:00", ["20:30", "29:00"])), "ranges"),
    ("議題內時間亂序但沒跑出區間＝現在的規則", 1800, notes(topic("A", "00:00", ["02:04", "00:29"]), topic("B", "10:00", ["15:00", "11:00"])), "ranges"),
    ("重回：B 在 C 中間又講一次", 2400,
     notes(topic("A", "00:00", ["01:00", "05:00"]), topic("B", "10:00", ["10:50", mmss(2000), mmss(2050)]),
           topic("C", "25:00", ["26:40", mmss(2200)])),
     [(0, 0, 600), (1, 600, 1500), (2, 1500, 2000), (1, 2000, 2200), (2, 2200, 2400)]),
    ("短於 60 秒的重回併進前一段", 1500,
     notes(topic("A", "00:00", ["01:40", mmss(1030)]), topic("B", "05:00", ["06:40", mmss(1000)]), topic("C", mmss(1050), [mmss(1100)])),
     [(0, 0, 300), (1, 300, 1050), (2, 1050, 1500)]),
    ("第一段太短併進後一段", 3600,
     notes(topic("A", "00:00", [mmss(3000)]), topic("B", "00:10", ["00:20", "01:40"])),
     [(1, 0, 3000), (0, 3000, 3600)]),
    ("早於議題開始的重點照算、讀不到的時間丟掉", 900,
     notes(topic("A", "05:00", ["01:00", "bad", "10:00"]), topic("B", "08:00", ["09:00"])),
     [(0, 60, 480), (1, 480, 600), (0, 600, 900)]),
    ("超過會議長度的時間丟掉", 600,
     notes(topic("A", "00:00", ["01:00", "2:00:00"]), topic("B", "05:00", ["06:00"])),
     [(0, 0, 300), (1, 300, 600)]),
    ("唯一一段再短也留著", 600,
     notes(topic("A", "00:00", ["01:00"]), topic("B", "05:00", []), topic("C", "05:20", ["06:00"])),
     [(0, 0, 300), (1, 300, 320), (2, 320, 600)]),
    ("沒標題也沒重點的議題不畫（branch 往前補）", 600,
     notes({"title": "", "start": "00:00", "points": []}, topic("B", "05:00", ["06:00"])),
     [(0, 300, 600)]),
]

with tempfile.TemporaryDirectory() as tmp:
    src = os.path.join(tmp, "in.json")
    out = os.path.join(tmp, "out.json")
    json.dump({"duration": 0, "cases": [{"name": n, "duration": d, "notes": nt} for n, d, nt, _ in cases]},
              open(src, "w", encoding="utf-8"), ensure_ascii=False)
    ctl("topicsegments", src, out, output=out)
    result = json.load(open(out, encoding="utf-8"))
    if not result.get("ok"):
        failures.append("topicsegments：ok 不是 true")
    for (name, _, _, expect), got in zip(cases, result.get("cases", [])):
        segs = [(s["branch"], round(s["start"]), round(s["end"])) for s in got["segments"]]
        ranges = [(s["branch"], round(s["start"]), round(s["end"])) for s in got["ranges"]]
        want = ranges if expect == "ranges" else expect
        status = "通過" if segs == want else "不符"
        print(f"[{status}] topicSegments：{name}")
        if segs != want:
            failures.append(f"topicSegments「{name}」：得到 {segs}，應該是 {want}")
    if result.get("cases"):
        branches = {b["topic"]: b["branch"] for b in result["cases"][-1]["branches"]}
        if branches != {1: 0}:
            failures.append(f"topicBranches：得到 {branches}，應該是 {{1: 0}}")

# ── 分段複製（§F4.1）：中、英、日的示範會議 ──────────────────────────
LABELS = {
    "zh": dict(summary="摘要", decisions="決議", actionItems="待辦", openQuestions="未決問題",
               paren="（{}）", colon="：", unassigned="未指定", due="期限"),
    "en": dict(summary="Summary", decisions="Decisions", actionItems="Action items", openQuestions="Open questions",
               paren=" ({})", colon=": ", unassigned="Unassigned", due="Due"),
    "ja": dict(summary="要約", decisions="決定事項", actionItems="ToDo", openQuestions="未決事項",
               paren="（{}）", colon="：", unassigned="未定", due="期限"),
}


def expected(scope, n, x):
    def t(time):
        return x["paren"].format(time) if time else ""

    def lines(title, items):
        return "" if not items else "\n".join([title] + [f"- {i['text']}{t(i.get('time', ''))}" for i in items]) + "\n"

    kind, _, idx = scope.partition(":")
    if kind in ("summary", "decisions", "openQuestions"):
        return lines(x[kind], n.get(kind, []))
    if kind == "custom":
        c = n["custom"][int(idx)]
        return lines(c["title"], c["items"])
    if kind == "topic":
        tp = n["topics"][int(idx)]
        head = f"[{tp['start']}] {tp['title']}" if tp["start"] else tp["title"]
        return "\n".join([head] + [f"- {p['text']}{t(p.get('time', ''))}" for p in tp["points"]]) + "\n"
    items = n.get("actionItems", [])
    if not items:
        return ""
    rows = [f"- {a['owner'] or x['unassigned']}{x['colon']}{a['task']}"
            f"{x['paren'].format(x['due'] + ' ' + a['due']) if a['due'] else ''}{t(a.get('time', ''))}" for a in items]
    return "\n".join([x["actionItems"]] + rows) + "\n"


fixtures = {m["key"]: m for m in json.load(open(os.path.join(ROOT, "shared/golden/fixtures.json"), encoding="utf-8"))["meetings"]}
# 日文的示範會議沒有會議紀錄：另外放一場有紀錄的（內容是測試用的假資料），一樣用 seedfixtures 寫進暫存的資料庫
JA_NOTES = {
    "title": "定例会議",
    "summary": [{"text": "リリース日程を確認", "time": "00:30"}, {"text": "キャッシュは来週完了", "time": ""}],
    "decisions": [{"text": "デプロイ手順は現状維持", "time": "01:10"}],
    "actionItems": [{"owner": "田中", "task": "権限を確認する", "due": "2026-10-21", "time": "02:00"},
                    {"owner": "", "task": "キャッシュの検証", "due": "", "time": ""}],
    "openQuestions": [{"text": "Kubernetes のバージョンは？", "time": "03:00"}],
    "topics": [{"title": "日程", "start": "00:00", "points": [{"text": "目標は 10/21", "time": "00:40"}]},
               {"title": "", "start": "", "points": [{"text": "その他", "time": ""}]}],
    "custom": [], "reviewItems": [],
}
db = sqlite3.connect(f"file:{os.path.join(HOME, 'shiyin.sqlite')}?mode=ro", uri=True)
with tempfile.TemporaryDirectory() as tmp:
    ja = json.loads(json.dumps(fixtures["ja"]))
    ja["key"] = "ja-f4"
    ja["meeting"]["sourceFilename"] = "f4-check-ja.m4a"
    ja["notes"] = JA_NOTES
    fixtures["ja"] = ja
    if not db.execute("select 1 from meetings where source_filename = 'f4-check-ja.m4a'").fetchone():
        extra = os.path.join(tmp, "fixtures-ja.json")
        json.dump({"meetings": [ja]}, open(extra, "w", encoding="utf-8"), ensure_ascii=False)
        subprocess.run([CTL, "seedfixtures", extra, "ja-f4"], check=True, stdout=subprocess.DEVNULL)
        for _ in range(50):
            if db.execute("select 1 from meetings where source_filename = 'f4-check-ja.m4a'").fetchone():
                break
            time.sleep(0.1)
    for lang in ("zh", "en", "ja"):
        fx = fixtures[lang]
        row = db.execute("select id, notes from meetings where source_filename = ? and language = ? order by id desc limit 1",
                         (fx["meeting"]["sourceFilename"], lang)).fetchone()
        if not row:
            failures.append(f"找不到 {lang} 的示範會議：先 seedfixtures")
            continue
        mid, saved = row
        n = json.loads(saved)   # 存進資料庫後的會議紀錄（時間點會被整理過）
        scopes = ["summary", "decisions", "actionItems", "openQuestions"]
        scopes += [f"custom:{i}" for i in range(len(n.get("custom", [])))] + [f"topic:{i}" for i in range(len(n.get("topics", [])))]
        for scope in scopes:
            out = os.path.join(tmp, f"{lang}-{scope.replace(':', '-')}.txt")
            want = expected(scope, n, LABELS[lang])
            if want == "":
                subprocess.run([CTL, "copysection", str(mid), scope, out], check=True, stdout=subprocess.DEVNULL)
                time.sleep(0.5)
                got = open(out, encoding="utf-8").read() if os.path.exists(out) else ""
            else:
                ctl("copysection", str(mid), scope, out, output=out)
                got = open(out, encoding="utf-8").read()
            status = "通過" if got == want else "不符"
            print(f"[{status}] copysection {lang} {scope}")
            if got != want:
                failures.append(f"copysection {lang} {scope}：\n得到：{got!r}\n應該：{want!r}")

if failures:
    print("\n".join(["", "不符："] + failures))
    sys.exit(1)
print("\n全部通過")
