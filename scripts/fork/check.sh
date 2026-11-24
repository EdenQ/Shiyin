#!/bin/bash
# fork 的回歸檢查（fork design §F0.4；PLAN-fork-5.0 §8.1、階段 3a）：一個指令跑完能自動化的 1～12 項，輸出 markdown 摘要。
# 用法：scripts/fork/check.sh [--quick] [--only 3,5,I1] [--base-app <舊版.app> | --base-ref <tag>] [--out <資料夾>] [--keep] [--clean-cache]
#   --quick        只跑靜態的（不建 app、不開 DEBUG 版）：3（原始碼）、4（repo）、T、W、I1、I2、L、11、12
#   --only         只跑這幾項（逗號分隔，只收 1～16、I1、I2、L、T、W、S；不認得或一項都沒有就 exit 2）；
#                  需要的建置、DEBUG 版會自己做（加 --quick 時 3、4 只做靜態的部分，選到的其他項目照常建置）
#   --base-app     品牌逐鍵比對的基準；預設用 HEAD^ 之前最近的 fork tag 在本機建（快取在 ~/Library/Caches/ShiyinBuild/check/base/<tag>）
#   --out          摘要、log、截圖放這裡（預設 $TMPDIR/shiyin-check-<時間>）
#   --keep         留下這次的暫存資料夾（app、SHIYIN_HOME、shiyinctl）
#   --clean-cache  結束時連 check 的建置快取、基準版也刪掉
# exit 0：沒有 FAIL；1：有 FAIL；2：沒開始（使用者在錄音、有別的 DEBUG 版在跑、拿不到設定快照、參數錯）
# 安全規則（CLAUDE.md「驗證時要注意」）：不碰 ~/Library/Caches/ShiyinBuild/app 和正式資料；DEBUG 版用暫存 SHIYIN_HOME、
# 同時只開一個；不送按鍵、不用 System Events；結束時結束自己的 DEBUG 版、刪掉暫存資料夾。
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CACHE_RAW="${MA_CHECK_CACHE:-}"   # MA_CHECK_CACHE：測沒有基準快取的路徑；參數驗證完先核對（resolve_cache，fork design §F0.4）
REAL="$HOME/Library/Application Support/Shiyin"
# shellcheck source=check-lib.sh
. "$ROOT/scripts/fork/check-lib.sh" || exit 2
MODE=full; ONLY=""; BASE_APP=""; BASE_REF=""; OUT=""; KEEP=0; CLEAN=0
need_value() { [ $# -ge 2 ] || { echo "$1 後面要有值（--help 看用法）"; exit 2; }; }
while [ $# -gt 0 ]; do
  case "$1" in
    --quick) MODE=quick;;
    --only) need_value "$@"; ONLY=",$2,"; shift;;
    --base-app) need_value "$@"; BASE_APP="$2"; shift;;
    --base-ref) need_value "$@"; BASE_REF="$2"; shift;;
    --out) need_value "$@"; OUT="$2"; shift;;
    --keep) KEEP=1;;
    --clean-cache) CLEAN=1;;
    -h|--help) sed -n '2,13p' "$0"; exit 0;;
    *) echo "不認得的參數：$1（--help 看用法）"; exit 2;;
  esac
  shift
done
if [ -n "$ONLY" ]; then validate_only "$ONLY" || exit 2; fi
# 任何建立、建置、清理之前：解析快取的真實路徑、拒絕受保護的位置和別人的資料夾（不通過就什麼都不建、不刪）
CACHE="$(resolve_cache "$CACHE_RAW" "$ROOT")" || { echo "停止：快取位置不能用（MA_CHECK_CACHE=${CACHE_RAW:-（預設）}）"; exit 2; }
SCRATCH="$CACHE/scratch"
TS="$(date +%Y%m%d-%H%M%S)"
RUN="$CACHE/run-$TS"
if [ -z "$OUT" ]; then OUT="${TMPDIR:-/tmp}"; OUT="${OUT%/}/shiyin-check-$TS"; fi
mkdir -p "$OUT/logs" "$OUT/shots" || exit 2
OUT="$(cd "$OUT" && pwd)"
SUMMARY="$OUT/summary.md"
START=$(date +%s)

# ---------- 開始前 ----------
if [ -e "$REAL/audio/recording" ]; then
  recording="$(ls -A "$REAL/audio/recording")" || { echo "停止：列不出 $REAL/audio/recording/，判斷不了使用者是不是在錄音"; exit 2; }
  [ -z "$recording" ] || { echo "停止：$REAL/audio/recording/ 有檔案（使用者可能正在錄音），不跑檢查"; exit 2; }
fi
others="$(debug_apps)" || { echo "停止：列不出程序，判斷不了有沒有別的 DEBUG 版"; exit 2; }
if [ -n "$others" ]; then echo "停止：已經有 DEBUG 版在跑（shiyinctl 是廣播，同時只能一個）：$others"; exit 2; fi
if [ -n "$CACHE_RAW" ]; then   # 自訂的快取：建立並寫入所有權標記，--clean-cache 才認得它
  mkdir -p "$CACHE" && touch "$CACHE/$MA_CACHE_MARK" || { echo "停止：建立不了快取 $CACHE"; exit 2; }
fi
mkdir -p "$RUN" || exit 2
# 開始時拿不到有效的設定快照就不跑：沒有快照，#12 證明不了什麼（fork design §F0.4）
if ! defaults_snapshot "$OUT/defaults-before.plist"; then echo "停止：拿不到開始時的設定快照"; rm -rf "$RUN"; exit 2; fi

DBG_PID=""; DBG_APP=""; TEST_APP=""; REL_APP=""; CTL=""; BUILT=""; BUILD_FAILED=0
NOTE=""; EVID=""; LOG="$OUT/logs/main.log"   # 每一項用之前 item() 會重設；先給值，--only 單選 DEBUG 項目時 need_build 才不會在 set -u 下中止
DEBUG_WANTED=0; HANDLERS_REQUIRED=0; FINISHED=0
# 中斷、出錯時的安全網：正常流程在摘要前由收尾項 C 做同樣的事並列入結果；這裡清不乾淨就讓 exit 變成 1
cleanup() {
  local code=$? bad=0
  [ "$FINISHED" = 1 ] && return
  stop_debug || bad=1
  if [ "$DEBUG_WANTED" = 1 ]; then cleanup_test_domain "$MA_TEST_DOMAIN" "$TEST_APP" || bad=1; fi
  if [ "$KEEP" = 1 ]; then echo "留下暫存資料夾：$RUN"; else rm -rf "$RUN" || bad=1; fi
  if [ $bad = 1 ]; then echo "收尾失敗：DEBUG 版、測試網域或暫存資料夾沒清乾淨" >&2; exit 1; fi
  exit $code
}
trap cleanup EXIT
trap 'echo "中斷"; exit 1' INT TERM

# ---------- 項目的記錄 ----------
ROWS=()    # "編號|名稱|狀態|秒數|證據|說明"
want() {   # 這一項要不要跑
  local id="$1"
  if [ -n "$ONLY" ]; then case "$ONLY" in *",$id,"*) return 0;; *) return 1;; esac; fi
  [ "$MODE" = full ] && return 0
  case "$id" in 3|4|T|W|I1|I2|L|11|12) return 0;; esac
  return 1
}
# item <編號> <名稱> <函式>：函式 return 0 PASS、1 FAIL、3 SKIP、4 需人工；可以設 NOTE、EVID；輸出寫到 $LOG
item() {
  local id="$1" title="$2" fn="$3" t0 code status
  want "$id" || return 0
  LOG="$OUT/logs/$id.log"; NOTE=""; EVID="logs/$id.log"; : > "$LOG"
  printf '%-4s %s … ' "$id" "$title"
  t0=$(date +%s)
  "$fn" >> "$LOG" 2>&1; code=$?
  case $code in 0) status=PASS;; 3) status=SKIP;; 4) status=需人工;; *) status=FAIL;; esac
  if [ "$status" = FAIL ] && [ -z "$NOTE" ]; then   # 說明沒寫時，帶 log 裡第一個不符的地方
    NOTE="$(grep -E 'FAIL|不符|Error|錯誤' "$LOG" | grep -v '^\$ ' | head -1 | cut -c1-100)"
  fi
  echo "${status}（$(( $(date +%s) - t0 )) 秒）${NOTE:+：$NOTE}"
  ROWS+=("$id|$title|$status|$(( $(date +%s) - t0 ))|$EVID|$NOTE")
}
add_row() { ROWS+=("$1|$2|$3|$4|$5|$6"); printf '%-4s %s … %s%s\n' "$1" "$2" "$3" "${6:+：$6}"; }   # 不經過 item 的列（4u、C）
# 在 log 裡記一行指令並執行
run() { echo "\$ $*"; "$@"; local c=$?; echo "→ exit $c"; return $c; }

# ---------- 建置 ----------
# build_app <原始碼> <release|debug> <放 app 的資料夾> <建置快取>：repo 的 build-app.sh 換掉 SCRATCH、APP 兩行的複本
# （cd 到原始碼、不建 build 捷徑、不碰 ~/Library/Caches/ShiyinBuild/app）
build_app() {
  local src="$1" cfg="$2" dir="$3" scratch="$4" copy
  copy="$RUN/build-app-$cfg-$RANDOM.sh"
  mkdir -p "$dir"
  sed -e "s|^SCRATCH=.*|SCRATCH=\"$scratch\"|" \
      -e "s|^APP=.*|APP=\"$dir/Meeting Assistant.app\"|" \
      -e "s|^cd \"\$(dirname \"\$0\")/\.\.\"\$|cd \"$src\"|" \
      -e "s|^mkdir -p \"\$SCRATCH/app\"\$|mkdir -p \"$dir\"|" \
      -e '/^\[ -L "\$ROOT\/build" \]/d' "$src/scripts/build-app.sh" > "$copy"
  # 換不到（上游改了這幾行）就不建：寧可失敗，也不要建到使用者的 app 資料夾
  if ! grep -qF "APP=\"$dir/Meeting Assistant.app\"" "$copy" || ! grep -qF "SCRATCH=\"$scratch\"" "$copy" \
     || ! grep -qF "cd \"$src\"" "$copy" || grep -q 'ShiyinBuild/app\|\$SCRATCH/app' "$copy"; then
    echo "build-app.sh 的 SCRATCH／APP／cd 行跟預期不同，沒辦法安全地換成暫存資料夾"; return 1
  fi
  if [ "$cfg" = debug ]; then run bash "$copy" --debug; else run bash "$copy"; fi
}
i_build() {
  run swift build -c debug --arch arm64 --disable-keychain --scratch-path "$SCRATCH" --package-path "$ROOT" || return 1
  build_app "$ROOT" release "$RUN/release" "$SCRATCH" || return 1
  build_app "$ROOT" debug "$RUN/debug" "$SCRATCH" || return 1
  run xcrun swiftc "$ROOT/scripts/dev/shiyinctl.swift" -module-cache-path "$RUN/mc" -o "$RUN/shiyinctl" || return 1
  REL_APP="$RUN/release/Meeting Assistant.app"; DBG_APP="$RUN/debug/Meeting Assistant.app"; CTL="$RUN/shiyinctl"; BUILT=1
  NOTE="release、DEBUG 版建到暫存資料夾"
}
need_build() {   # 後面的項目要用到建置；--only 沒選 1 時在這裡建
  [ -n "$BUILT" ] && return 0
  [ "$BUILD_FAILED" = 1 ] && return 1
  local keep_note="$NOTE" keep_evid="$EVID" c=0   # i_build 會設 NOTE、EVID：不要蓋掉呼叫它的那一項的
  i_build >> "$OUT/logs/1.log" 2>&1 || c=1
  NOTE="$keep_note"; EVID="$keep_evid"
  [ $c = 0 ] || { BUILD_FAILED=1; return 1; }
}

# ---------- 2 migration ----------
i_mig() { run python3 "$ROOT/scripts/dev/check-fork-migrations.py" --scratch-path "$SCRATCH"; }

# ---------- 3 品牌 ----------
base_app() {   # 品牌比對的基準
  [ -n "$BASE_APP" ] && { echo "$BASE_APP"; return 0; }
  local tag="${BASE_REF:-$(git -C "$ROOT" describe --tags --abbrev=0 --match 'v[0-9]*' HEAD^ 2>/dev/null)}"
  [ -n "$tag" ] || return 1
  local dir="$CACHE/base/$tag"
  if [ ! -f "$dir/.ok" ]; then
    local src="$RUN/base-src"
    rm -rf "$src" "$dir"; mkdir -p "$src"
    extract_tag "$ROOT" "$tag" "$src" || return 1
    build_app "$src" release "$dir" "$CACHE/scratch-base" >&2 || return 1
    touch "$dir/.ok"; rm -rf "$src" "$CACHE/scratch-base"
  fi
  echo "$dir/Meeting Assistant.app"
}
i_brand() {
  local fail=0 review=0 base
  run python3 "$ROOT/scripts/fork/brand.py" check-sources || { fail=1; NOTE="brand.py check-sources 有違規；"; }
  run python3 "$ROOT/scripts/fork/brand-test.py" || { fail=1; NOTE="${NOTE}brand-test 失敗；"; }
  if [ "$MODE" = quick ]; then NOTE="${NOTE:-原始碼掃描、brand-test 通過}（--quick 不檢查建置結果）"; return $fail; fi
  need_build || { NOTE="${NOTE}建置失敗（build-app 的 brand.py apply 也會擋品牌違規）"; return 1; }
  run python3 "$ROOT/scripts/fork/brand.py" check "$REL_APP" || fail=1
  run python3 "$ROOT/scripts/fork/brand.py" check "$DBG_APP" || fail=1
  base="$(base_app)"
  if [ -z "$base" ] || [ ! -d "$base" ]; then NOTE="基準版建不出來（--base-app 指定）"; return 1; fi
  echo "基準：$base"
  # brand.py compare：0 相同、1 比完有差異（需人工）、2 工具或輸入錯誤（FAIL）；其他非 0 也是 FAIL
  python3 "$ROOT/scripts/fork/brand.py" compare "$base" "$REL_APP" > "$OUT/brand-compare.txt" 2>&1
  local ccode=$? cstatus
  cstatus="$(compare_status $ccode)"
  echo "brand.py compare exit $ccode → $cstatus"
  tail -3 "$OUT/brand-compare.txt"
  EVID="logs/3.log、brand-compare.txt"
  if [ "$cstatus" = FAIL ]; then NOTE="${NOTE}brand.py compare 沒有比完（exit ${ccode}）：$(tail -1 "$OUT/brand-compare.txt" | cut -c1-120)"; return 1; fi
  [ $fail = 1 ] && return 1
  if [ "$cstatus" = 需人工 ]; then NOTE="跟 $(basename "$(dirname "$base")") 逐鍵比對有差異：$(tail -1 "$OUT/brand-compare.txt")，看 brand-compare.txt"; return 4; fi
  NOTE="跟 $(basename "$(dirname "$base")") 逐鍵比對：$(tail -1 "$OUT/brand-compare.txt" | sed 's/^brand.py compare：//')"
}

# ---------- 4 F1 ----------
i_f1() {
  local fail=0 apps=()
  if [ "$MODE" = full ]; then
    need_build || { NOTE="建置失敗"; return 1; }
    apps=(--app "$REL_APP" --app "$DBG_APP")
  fi
  run python3 "$ROOT/scripts/fork/check-f1.py" ${apps[@]+"${apps[@]}"} --update-url || fail=1
  run xcrun swiftc -swift-version 5 -module-cache-path "$RUN/mc" -o "$RUN/brand-hooks" \
    "$ROOT/scripts/fork/brand-hooks-test/main.swift" "$ROOT/Sources/Shiyin/Fork/Brand.swift" && run "$RUN/brand-hooks" || fail=1
  if [ $fail = 1 ]; then NOTE="$(grep -E '^FAIL|^ok   |^FAIL ' "$LOG" | grep '^FAIL' | head -2 | cut -c6-80 | tr '\n' '；')"
  elif grep -q '^SKIP' "$LOG"; then NOTE="子項 SKIP：$(grep '^SKIP' "$LOG" | head -1 | cut -c6-60)…"; fi
  return $fail
}

# ---------- 隔離、l10n ----------
i_iso() {
  run python3 "$ROOT/scripts/fork/isolation-check.py"; local c=$?
  NOTE="$(grep -o "上游程式裡 fork 的行數：[0-9]*（上限 [0-9]*）" "$LOG" | head -1)"
  [ $c = 0 ] || NOTE="$(grep -E '^  - ' "$LOG" | head -2 | sed 's/^  - //' | cut -c1-90 | tr '\n' '；')${NOTE}"
  return $c
}
i_selftest() { run python3 "$ROOT/scripts/fork/check-test.py"; }
i_watchtest() { run python3 "$ROOT/scripts/fork/upstream-watch-test.py"; }   # 上游監看（fork design §F0.5）
i_isotest() { run python3 "$ROOT/scripts/fork/isolation-check-test.py"; }
i_l10n() {
  local table="$ROOT/Resources/Localizable.xcstrings" before after code
  cp "$table" "$RUN/xcstrings.bak" || { NOTE="備份不了翻譯表，不跑（l10n.py check 會改它）"; return 1; }
  before="$(git -C "$ROOT" status --porcelain)" || { NOTE="git status 失敗"; return 1; }
  run python3 "$ROOT/scripts/dev/l10n.py" check; code=$?
  after="$(git -C "$ROOT" status --porcelain)" || { NOTE="git status 失敗"; return 1; }
  if ! cmp -s "$table" "$RUN/xcstrings.bak"; then
    cp "$RUN/xcstrings.bak" "$table" || echo "放不回翻譯表：備份在 $RUN/xcstrings.bak"
    echo "l10n.py check 改了翻譯表（有新的介面字串沒進表）：已放回原本的內容"
    NOTE="翻譯表會被改：有字串沒進表，先跑 l10n.py check、apply"; return 1
  fi
  [ "$before" = "$after" ] || { echo "git status 前後不同：$before ／ $after"; NOTE="l10n.py check 改了 repo 的檔"; return 1; }
  return $code
}

# ---------- DEBUG 版 ----------
start_debug() {   # start_debug <AppleLanguages 的語言：zh-Hant、en>（只寫 zh 會解析成簡體）
  # DBG_ISLAND=YES：錄音島開著、放在桌面層（#15；平常 NO，不出現在畫面上）；home 另外開一個資料夾
  local lang="$1" home="$RUN/home-$1${DBG_ISLAND:+-island}" exe pid="" island="${DBG_ISLAND:-NO}" behind=""
  [ "$island" = YES ] && behind="-debugIslandBehind YES"
  local running
  running="$(debug_apps)" || { echo "列不出程序"; return 1; }
  [ -z "$running" ] || { echo "已經有 DEBUG 版在跑：$running"; return 1; }
  if [ -z "$TEST_APP" ]; then   # 測試專用 bundle id 的複本：不寫正式網域、不搶 shiyin://、.shiyin（fork design §F0.4）
    TEST_APP="$(isolate_debug_app "$DBG_APP" "$RUN/debug-test")" || { echo "做不出測試 id 的 DEBUG 版"; TEST_APP=""; return 1; }
    echo "DEBUG 版複本：${TEST_APP}（bundle id ${MA_TEST_DOMAIN}）"
  fi
  exe="$TEST_APP/Contents/MacOS/Shiyin"
  # KEEP_HOME=1：沿用上一次的暫存 SHIYIN_HOME（#16 測重啟），不清空
  [ "${KEEP_HOME:-0}" = 1 ] && [ -d "$home" ] || { rm -rf "$home"; mkdir -p "$home"; }
  open -g -n --env SHIYIN_HOME="$home" "$TEST_APP" --args -ApplePersistenceIgnoreState YES -llmProvider none \
    -autoSummarize NO -correctTranscript NO -debugQuietPrompts YES -recordingIsland "$island" $behind -mcpEnabled NO \
    -autoCheckUpdates NO -muteHotKey YES -AppleLanguages "($lang)" || return 1
  for _ in $(seq 1 60); do pid="$(pgrep -f "$exe" | head -1)"; [ -n "$pid" ] && [ -f "$home/shiyin.sqlite" ] && break; sleep 0.5; done
  [ -n "$pid" ] || { echo "DEBUG 版沒有啟動"; return 1; }
  DBG_PID="$pid"; HOME_DIR="$home"
  sleep 4
  lsof -p "$pid" -Fn > "$OUT/logs/lsof-$lang.txt" 2>&1
  if ! verify_db_files "$pid" "$home" "$REAL"; then
    echo "DEBUG 版開的不只是暫存資料庫（或核對不了），結束它"; stop_debug; return 1
  fi
  echo "DEBUG 版 pid=${pid}，SHIYIN_HOME=${home}（lsof 確認只開暫存的資料庫）"
  # 測試版開著時，shiyin://、.shiyin 的候選 app 裡不能有它（沒有 URL scheme、文件類型宣告才對）
  # 必要條件：helper 在前面已經編好（prepare_handlers），這裡讀不到就不跑
  if ! "$RUN/handlers" > "$OUT/logs/handlers-$lang.txt" 2>&1 || ! valid_handlers "$OUT/logs/handlers-$lang.txt"; then
    echo "測試版開著時讀不了 shiyin://、.shiyin 的處理程式"; stop_debug; return 1
  fi
  if grep -qF "$TEST_APP" "$OUT/logs/handlers-$lang.txt"; then
    echo "測試版出現在 shiyin://、.shiyin 的處理程式裡：$(cat "$OUT/logs/handlers-$lang.txt")"; stop_debug; return 1
  fi
  echo "shiyin://、.shiyin 的處理程式裡沒有測試版"
  "$CTL" closewindow onboarding >/dev/null 2>&1   # 沒有引導視窗時也是 exit 0（廣播）；不是必要步驟
  sleep 1
}
stop_debug() {   # kill，不用 quit：正常結束會把視窗位置寫進共用設定
  [ -n "$DBG_PID" ] || return 0
  # 送訊號前核對 pid 還是這次的 app（pid 可能已經結束、被別的程序重用）
  if ! owned_pid "$DBG_PID" "$TEST_APP"; then echo "pid $DBG_PID 已經不是這次的 DEBUG 版，不送訊號"; DBG_PID=""; return 0; fi
  kill -TERM "$DBG_PID" 2>/dev/null
  for _ in $(seq 1 20); do owned_pid "$DBG_PID" "$TEST_APP" || break; sleep 0.5; done
  if owned_pid "$DBG_PID" "$TEST_APP"; then
    kill -KILL "$DBG_PID" 2>/dev/null
    for _ in $(seq 1 10); do owned_pid "$DBG_PID" "$TEST_APP" || break; sleep 0.5; done
    if owned_pid "$DBG_PID" "$TEST_APP"; then echo "DEBUG 版 pid $DBG_PID 結束不了"; return 1; fi
  fi
  DBG_PID=""
}
dbg() { run python3 "$ROOT/scripts/fork/check-debug.py" "$1" "$HOME_DIR" "$CTL" --out "$OUT/$2" "${@:3}"; }
i_f2() {
  local fail=0
  run python3 "$ROOT/scripts/fork/f2-atomic-check.py" "$HOME_DIR" "$CTL" --out "$OUT/f2" || fail=1
  dbg f2-apply f2 --f2-out "$OUT/f2" || fail=1
  dbg f2-record f2 || fail=1
  EVID="logs/5.log、f2/"; return $fail
}
i_f2edit() { dbg f2-edit f2-edit; local c=$?; EVID="logs/6.log、f2-edit/"; return $c; }
i_f3() { run python3 "$ROOT/scripts/fork/f3-mute-check.py" "$HOME_DIR" "$CTL" --out "$OUT/f3"; local c=$?; EVID="logs/7.log、f3/"; return $c; }
i_f3hint() { dbg f3-hint f3-hint; local c=$?; cp "$OUT/f3-hint/f3-hint-main.png" "$OUT/shots/f3-hint-main-zh.png" 2>/dev/null; EVID="logs/8.log、f3-hint/"; return $c; }
i_f4() {
  run "$CTL" seedfixtures "$ROOT/shared/golden/fixtures.json" zh en ja || { NOTE="seedfixtures 失敗"; return 1; }
  sleep 3
  run python3 "$ROOT/scripts/dev/f4-check.py" "$HOME_DIR" "$CTL"
}
i_f4items() {
  dbg f4-items f4-items; local c=$?
  cp "$OUT/f4-items/f4-after-delete.png" "$OUT/shots/f4-after-delete-zh.png" 2>/dev/null
  EVID="logs/10.log、f4-items/"
  NOTE="只自動驗證刪除待辦；noteitem edit 之後的樣式、人物頁不套 F4 樣式仍需人工（S、使用者）"
  return $c
}
i_shots() {
  local fail=0
  dbg shots shots --lang zh || fail=1
  stop_debug || { NOTE="繁中的 DEBUG 版結束不了"; return 1; }
  start_debug en || { NOTE="英文的 DEBUG 版開不起來（必要條件見 log）"; return 1; }
  run "$CTL" seedfixtures "$ROOT/shared/golden/fixtures.json" zh en || { NOTE="seedfixtures 失敗"; return 1; }
  sleep 3
  dbg shots shots --lang en || fail=1
  stop_debug || { NOTE="英文的 DEBUG 版結束不了"; return 1; }
  rm -f "$OUT/shots/state-raw.json"
  EVID="shots/"
  NOTE="看一眼：$(cd "$OUT/shots" && ls *.png 2>/dev/null | tr '\n' ' ')"
  [ $fail = 1 ] && return 1
  return 4
}
i_f10() {   # F10 備份（fork design §F10.8）：清理的反例、重疊、錄完後到期的檢查
  run python3 "$ROOT/scripts/fork/f10-backup-check.py" "$HOME_DIR" "$CTL" --out "$OUT/f10"; local c=$?
  EVID="logs/14.log、f10/"; return $c
}
i_f12() {   # F12 聲紋（fork design §F12.8）：會刪會議、刪人，另外開一次 DEBUG 版（新的暫存 SHIYIN_HOME），排在 S 之後
  stop_debug || { NOTE="前一個 DEBUG 版結束不了"; return 1; }
  start_debug zh-Hant || { NOTE="DEBUG 版開不起來（必要條件見 log）"; return 1; }
  run python3 "$ROOT/scripts/fork/f12-voiceprint-check.py" "$HOME_DIR" "$CTL" --out "$OUT/f12"; local c=$?
  cp "$OUT/f12/"f12-*.png "$OUT/shots/" 2>/dev/null
  # F12.15 的建議跨重啟（§F12.9）：轉錄完沒打開就重啟 → 打開補回、略過 → 再重啟不復活。真的結束、再開同一個暫存 SHIYIN_HOME
  local phase
  for phase in restart-seed restart-check restart-final; do
    if [ "$phase" != restart-seed ]; then
      stop_debug || { NOTE="重啟前 DEBUG 版結束不了"; return 1; }
      KEEP_HOME=1 start_debug zh-Hant || { NOTE="重啟 DEBUG 版開不起來"; return 1; }
    fi
    run python3 "$ROOT/scripts/fork/f12-voiceprint-check.py" "$HOME_DIR" "$CTL" --out "$OUT/f12" --phase "$phase" || c=1
  done
  stop_debug || { NOTE="DEBUG 版結束不了"; return 1; }
  EVID="logs/16.log、f12/"; return $c
}
i_f11() {   # F11 錄音島的螢幕（fork design §F11.6）：錄音島開著、放在桌面層，另外開一次 DEBUG 版
  stop_debug || { NOTE="前一個 DEBUG 版結束不了"; return 1; }
  DBG_ISLAND=YES start_debug zh-Hant || { NOTE="錄音島開著的 DEBUG 版開不起來（必要條件見 log）"; return 1; }
  run python3 "$ROOT/scripts/fork/f11-island-check.py" "$HOME_DIR" "$CTL" --out "$OUT/f11"; local c=$?
  stop_debug || { NOTE="錄音島開著的 DEBUG 版結束不了"; return 1; }
  EVID="logs/15.log、f11/"; return $c
}
i_session_fail() { NOTE="沒有跑：DEBUG 版的必要條件不成立：${SESSION_REASON}（logs/debug-start.log）"; return 1; }

# ---------- 11、12、13 ----------
i_tsan() { run bash "$ROOT/scripts/fork/tsan-lockedvalue/run.sh"; }
i_defaults() {
  # 正式網域前後不同就 FAIL、保留現值：DEBUG 版用測試 id 本來就不寫正式網域，分不出來源的變更不改寫也不刪（REVIEW-3a2 P2-4）
  local fail=0
  EVID="defaults-before.plist、defaults-after.plist"
  defaults_snapshot "$OUT/defaults-after.plist" || { NOTE="結束時拿不到設定快照，無法比對"; return 1; }
  if snapshot_diff "$OUT/defaults-before.plist" "$OUT/defaults-after.plist"; then NOTE="正式網域 defaults export 前後逐位元組相同"
  else NOTE="正式網域跟開始前不同（鍵列在 log；可能是使用者同時改的），保留現值、沒有改寫"; fail=1; fi
  if [ "$HANDLERS_REQUIRED" = 1 ]; then   # 選了 DEBUG 項目：shiyin://、.shiyin 的預設處理程式前後相同，快照是必要的
    EVID="${EVID}、handlers-before.txt、handlers-after.txt"
    valid_handlers "$OUT/handlers-before.txt" || { NOTE="${NOTE}；沒有開始時的處理程式快照，核對不了 shiyin://、.shiyin"; return 1; }
    { [ -x "$RUN/handlers" ] && "$RUN/handlers" > "$OUT/handlers-after.txt" 2>&1 && valid_handlers "$OUT/handlers-after.txt"; } \
      || { NOTE="${NOTE}；結束時讀不了處理程式"; return 1; }
    if ! diff <(grep -- '-default' "$OUT/handlers-before.txt") <(grep -- '-default' "$OUT/handlers-after.txt"); then
      NOTE="${NOTE}；shiyin://、.shiyin 的預設處理程式跟開始前不同"; fail=1
    else NOTE="${NOTE}；shiyin://、.shiyin 的預設處理程式前後相同"; fi
  fi
  return $fail
}
i_manual() { NOTE="4.7.6 → 新版的 app 內更新：開舊會議看標記、靜音、條列頁（使用者在電腦前做）"; return 4; }

# ---------- 跑 ----------
echo "回歸檢查（$MODE${ONLY:+，只跑 ${ONLY//,/ }}）：$ROOT @ $(git -C "$ROOT" rev-parse --short HEAD)；輸出 $OUT"
item 1 "編譯（swift build、release、DEBUG）" i_build
[ -n "$ONLY" ] || [ "$MODE" = quick ] || [ -n "$BUILT" ] || BUILD_FAILED=1
item 2 "migration（check-fork-migrations）" i_mig
item 3 "品牌（掃描、brand-test、建置結果、逐鍵比對）" i_brand
item T "check.sh 自己的負對照（check-test.py）" i_selftest
item W "上游監看的測試（upstream-watch-test.py）" i_watchtest
item I1 "接點隔離（isolation-check）" i_iso
item I2 "隔離檢查的回歸測試" i_isotest
item L "介面字串（l10n.py check）" i_l10n
item 4 "F1 名稱、網址、圖示、接點" i_f1
if want 4 && grep -q '^SKIP' "$OUT/logs/4.log" 2>/dev/null; then   # 唯一定義成可選的子項（fork design §F0.4）
  add_row 4u "CI 的更新網址（vars.SHIYIN_UPDATE_URL）" SKIP 0 logs/4.log "$(grep '^SKIP' "$OUT/logs/4.log" | head -1 | cut -c6-90)"
fi
SESSION_REASON=""
if want 5 || want 6 || want 7 || want 8 || want 9 || want 10 || want 14 || want 15 || want 16 || want S; then
  DEBUG_WANTED=1; HANDLERS_REQUIRED=1
  # 必要條件（fork design §F0.4）：任一步不成立，5～10、14、15、S 全部 FAIL，不會沒核對就照跑
  {
    if ! cleanup_test_domain "$MA_TEST_DOMAIN"; then SESSION_REASON="上次留下的測試網域清不掉"
    elif ! need_build; then SESSION_REASON="建置失敗（logs/1.log）"
    elif ! prepare_handlers "$RUN/handlers" "$OUT/handlers-before.txt" "$OUT/logs/handlers-build.log"; then SESSION_REASON="處理程式的 helper 或開始時的快照失敗"
    elif ! start_debug zh-Hant; then SESSION_REASON="DEBUG 版開不起來或核對沒過"
    fi
  } > "$OUT/logs/debug-start.log" 2>&1
  if [ -z "$SESSION_REASON" ]; then
    item 5 "F2 標記（錄音中標記、套用、只改這句的交易）" i_f2
    item 6 "F2 加上 5.0（編輯會議、分割、合併、封包）" i_f2edit
    item 7 "F3 靜音（狀態、快捷鍵、錄音檔）" i_f3
    item 8 "F3 加上 5.0（選單列、收音提示、muteHint）" i_f3hint
    item 9 "F4（議題切段、分段複製）" i_f4
    item 10 "F4 加上 5.0（noteitem 刪除後）" i_f4items
    item 14 "F10 備份（清理只動自己的一般檔、重疊、錄完後到期）" i_f10
    item S "截圖（#7～#10 要看一眼的畫面，zh、en）" i_shots
    item 16 "F12 聲紋（分數、改名防呆、來源紀錄、人物頁、§F-DB）" i_f12
    item 15 "F11 錄音島的螢幕（三種選項、沒有內建螢幕和主視窗的退路）" i_f11
  else
    cat "$OUT/logs/debug-start.log"
    for id in 5 6 7 8 9 10 14 S 16 15; do item "$id" "DEBUG 版的項目" i_session_fail; done
  fi
fi
item 11 "DF5（TSan LockedValue）" i_tsan
item 12 "設定殘留（defaults 前後比對）" i_defaults
want 13 && item 13 "4.7.6 → 新版實機更新" i_manual

# ---------- 收尾（C）：每次都跑、列進結果 ----------
finish() {
  local bad=0 t0 left
  t0=$(date +%s); : > "$OUT/logs/C.log"
  {
    stop_debug || bad=1
    left="$(debug_apps)" || { echo "列不出程序"; bad=1; }
    if [ -n "$TEST_APP" ] && printf '%s' "$left" | grep -qF "$TEST_APP"; then echo "還有測試版在跑：$left"; bad=1; fi
    if [ "$DEBUG_WANTED" = 1 ]; then
      cleanup_test_domain "$MA_TEST_DOMAIN" "$TEST_APP" && echo "測試網域 $MA_TEST_DOMAIN 和它的快取都不在了" || bad=1
    fi
    if [ "$KEEP" = 1 ]; then echo "留下暫存資料夾：$RUN"
    else rm -rf "$RUN"; [ -e "$RUN" ] && { echo "刪不掉暫存資料夾 $RUN"; bad=1; } || echo "暫存資料夾刪了"; fi
    if [ "$CLEAN" = 1 ]; then   # 只刪 check.sh 認領的快取（預設位置或有標記）底下自己的三個子資料夾
      if [ -z "$CACHE_RAW" ] || [ -f "$CACHE/$MA_CACHE_MARK" ]; then rm -rf "$SCRATCH" "$CACHE/scratch-base" "$CACHE/base" || bad=1
      else echo "快取 $CACHE 沒有 ${MA_CACHE_MARK}，--clean-cache 不刪"; bad=1; fi
    fi
  } >> "$OUT/logs/C.log" 2>&1
  if [ $bad = 0 ]; then add_row C "收尾（DEBUG 版、測試網域、暫存資料夾）" PASS $(( $(date +%s) - t0 )) logs/C.log ""
  else add_row C "收尾（DEBUG 版、測試網域、暫存資料夾）" FAIL $(( $(date +%s) - t0 )) logs/C.log "$(grep -E '失敗|不了|還在|刪不掉|列不出|結束不了' "$OUT/logs/C.log" | head -1 | cut -c1-100)"; fi
  FINISHED=1
}
finish

# ---------- 摘要 ----------
fails=0
{
  echo "# fork 回歸檢查摘要"
  echo
  echo "- 模式：$MODE${ONLY:+（只跑 ${ONLY//,/ }）}"
  echo "- repo：\`$ROOT\` @ \`$(git -C "$ROOT" rev-parse --short HEAD)\`（$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)）"
  echo "- 時間：$(date '+%Y-%m-%d %H:%M')，共 $(( $(date +%s) - START )) 秒"
  echo "- 輸出：\`$OUT\`"
  echo
  echo "| # | 項目 | 狀態 | 耗時 | 證據 | 說明 |"
  echo "|---|---|---|---|---|---|"
  for row in "${ROWS[@]}"; do
    IFS='|' read -r id title status secs evid note <<< "$row"
    [ "$status" = FAIL ] && fails=$((fails + 1))
    echo "| $id | $title | $status | ${secs} 秒 | $evid | ${note//|/／} |"
  done
} > "$SUMMARY"
echo
cat "$SUMMARY"
echo
if [ $fails -gt 0 ]; then echo "結果：FAIL（$fails 項），摘要 $SUMMARY"; exit 1; fi
echo "結果：沒有 FAIL，摘要 $SUMMARY"; exit 0
