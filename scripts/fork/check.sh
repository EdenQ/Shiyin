#!/bin/bash
# fork 的回歸檢查（fork design §F0.4；PLAN-fork-5.0 §8.1、階段 3a）：一個指令跑完能自動化的 1～12 項，輸出 markdown 摘要。
# 用法：scripts/fork/check.sh [--quick] [--only 3,5,I1] [--base-app <舊版.app> | --base-ref <tag>] [--out <資料夾>] [--keep] [--clean-cache]
#   --quick        只跑靜態的（不建 app、不開 DEBUG 版）：3（原始碼）、4（repo）、T、I1、I2、L、11、12
#   --only         只跑這幾項（逗號分隔，只收 1～13、I1、I2、L、T、S；不認得或一項都沒有就 exit 2）；
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
CACHE="$HOME/Library/Caches/ShiyinBuild/check"
SCRATCH="$CACHE/scratch"
REAL="$HOME/Library/Application Support/Shiyin"
# shellcheck source=check-lib.sh
. "$ROOT/scripts/fork/check-lib.sh" || exit 2
MODE=full; ONLY=""; BASE_APP=""; BASE_REF=""; OUT=""; KEEP=0; CLEAN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --quick) MODE=quick;;
    --only) ONLY=",$2,"; shift;;
    --base-app) BASE_APP="$2"; shift;;
    --base-ref) BASE_REF="$2"; shift;;
    --out) OUT="$2"; shift;;
    --keep) KEEP=1;;
    --clean-cache) CLEAN=1;;
    -h|--help) sed -n '2,13p' "$0"; exit 0;;
    *) echo "不認得的參數：$1（--help 看用法）"; exit 2;;
  esac
  shift
done
if [ -n "$ONLY" ]; then validate_only "$ONLY" || exit 2; fi
TS="$(date +%Y%m%d-%H%M%S)"
RUN="$CACHE/run-$TS"
if [ -z "$OUT" ]; then OUT="${TMPDIR:-/tmp}"; OUT="${OUT%/}/shiyin-check-$TS"; fi
mkdir -p "$OUT/logs" "$OUT/shots" || exit 2
OUT="$(cd "$OUT" && pwd)"
SUMMARY="$OUT/summary.md"
START=$(date +%s)

# ---------- 開始前 ----------
if [ -n "$(ls -A "$REAL/audio/recording" 2>/dev/null)" ]; then
  echo "停止：$REAL/audio/recording/ 有檔案（使用者可能正在錄音），不跑檢查"; exit 2
fi
debug_apps() {   # 正在跑的 DEBUG 版（只有 DEBUG 版的執行檔有控制通道的名字）
  ps -axo pid=,comm= | awk '/\/Contents\/MacOS\/Shiyin$/ {print $1}' | while read -r p; do
    exe="$(ps -o comm= -p "$p" 2>/dev/null)"
    [ -n "$exe" ] && grep -q 'com.weiwei.shiyin.debug' "$exe" 2>/dev/null && echo "$p $exe"
  done
}
others="$(debug_apps)"
if [ -n "$others" ]; then echo "停止：已經有 DEBUG 版在跑（shiyinctl 是廣播，同時只能一個）：$others"; exit 2; fi
mkdir -p "$RUN" || exit 2
# 開始時拿不到有效的設定快照就不跑：沒有快照，#12 證明不了什麼（fork design §F0.4）
if ! defaults_snapshot "$OUT/defaults-before.plist"; then echo "停止：拿不到開始時的設定快照"; rm -rf "$RUN"; exit 2; fi

DBG_PID=""; DBG_APP=""; REL_APP=""; CTL=""; BUILT=""; BUILD_FAILED=0
cleanup() {
  stop_debug
  restore_keys
  if [ "$KEEP" = 1 ]; then echo "留下暫存資料夾：$RUN"; else rm -rf "$RUN"; fi
  if [ "$CLEAN" = 1 ]; then rm -rf "$SCRATCH" "$CACHE/scratch-base" "$CACHE/base"; fi
}
trap cleanup EXIT
trap 'echo "中斷"; exit 1' INT TERM

# ---------- 項目的記錄 ----------
ROWS=()    # "編號|名稱|狀態|秒數|證據|說明"
want() {   # 這一項要不要跑
  local id="$1"
  if [ -n "$ONLY" ]; then case "$ONLY" in *",$id,"*) return 0;; *) return 1;; esac; fi
  [ "$MODE" = full ] && return 0
  case "$id" in 3|4|T|I1|I2|L|11|12) return 0;; esac
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
    git -C "$ROOT" archive "$tag" | tar -x -C "$src" || return 1
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
i_isotest() { run python3 "$ROOT/scripts/fork/isolation-check-test.py"; }
i_l10n() {
  local table="$ROOT/Resources/Localizable.xcstrings" before after code
  cp "$table" "$RUN/xcstrings.bak"
  before="$(git -C "$ROOT" status --porcelain)"
  run python3 "$ROOT/scripts/dev/l10n.py" check; code=$?
  after="$(git -C "$ROOT" status --porcelain)"
  if ! cmp -s "$table" "$RUN/xcstrings.bak"; then
    cp "$RUN/xcstrings.bak" "$table"; echo "l10n.py check 改了翻譯表（有新的介面字串沒進表）：已放回原本的內容"
    NOTE="翻譯表會被改：有字串沒進表，先跑 l10n.py check、apply"; return 1
  fi
  [ "$before" = "$after" ] || { echo "git status 前後不同：$before ／ $after"; NOTE="l10n.py check 改了 repo 的檔"; return 1; }
  return $code
}

# ---------- DEBUG 版 ----------
start_debug() {   # start_debug <AppleLanguages 的語言：zh-Hant、en>（只寫 zh 會解析成簡體）
  local lang="$1" home="$RUN/home-$1" exe pid=""
  exe="$DBG_APP/Contents/MacOS/Shiyin"
  [ -z "$(debug_apps)" ] || { echo "已經有 DEBUG 版在跑：$(debug_apps)"; return 1; }
  rm -rf "$home"; mkdir -p "$home"
  open -g -n --env SHIYIN_HOME="$home" "$DBG_APP" --args -ApplePersistenceIgnoreState YES -llmProvider none \
    -autoSummarize NO -correctTranscript NO -debugQuietPrompts YES -recordingIsland NO -mcpEnabled NO \
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
  "$CTL" closewindow onboarding >/dev/null 2>&1
  sleep 1
}
stop_debug() {   # kill，不用 quit：正常結束會把視窗位置寫進共用設定
  [ -n "$DBG_PID" ] || return 0
  # 送訊號前核對 pid 還是這次的 app（pid 可能已經結束、被別的程序重用）
  if ! owned_pid "$DBG_PID" "$DBG_APP"; then echo "pid $DBG_PID 已經不是這次的 DEBUG 版，不送訊號"; DBG_PID=""; return 0; fi
  kill -TERM "$DBG_PID" 2>/dev/null
  for _ in $(seq 1 20); do owned_pid "$DBG_PID" "$DBG_APP" || break; sleep 0.5; done
  owned_pid "$DBG_PID" "$DBG_APP" && kill -KILL "$DBG_PID" 2>/dev/null
  DBG_PID=""
}
# DEBUG 指令本來就會寫進共用設定的鍵（preview settings 記住開到哪一頁）：開 DEBUG 版前記下，結束後改回。
# 只改回這幾個、而且是值真的變了的；其他鍵的差異交給 #12 回報，不自動改（可能是使用者同時改的）
WRITTEN_KEYS="settingsPage"
SAVED_KEYS=""
save_keys() {
  [ -n "$SAVED_KEYS" ] && return 0
  mkdir -p "$RUN/keys"
  for k in $WRITTEN_KEYS; do
    if defaults read com.weiwei.shiyin "$k" > "$RUN/keys/$k" 2>/dev/null; then echo set > "$RUN/keys/$k.state"; else echo unset > "$RUN/keys/$k.state"; fi
    defaults read-type com.weiwei.shiyin "$k" 2>/dev/null | awk '{print $NF}' > "$RUN/keys/$k.type"
  done
  SAVED_KEYS=1
}
restore_keys() {
  [ -n "$SAVED_KEYS" ] || return 0
  local k now type
  for k in $WRITTEN_KEYS; do
    now="$(defaults read com.weiwei.shiyin "$k" 2>/dev/null)"; now_state=$([ $? = 0 ] && echo set || echo unset)
    if [ "$(cat "$RUN/keys/$k.state")" = unset ]; then
      [ "$now_state" = set ] && defaults delete com.weiwei.shiyin "$k" && echo "改回：刪掉 ${k}（檢查前沒有這個鍵）"
    elif [ "$now_state" = unset ] || [ "$now" != "$(cat "$RUN/keys/$k")" ]; then
      type="$(cat "$RUN/keys/$k.type")"
      case "$type" in integer) defaults write com.weiwei.shiyin "$k" -int "$(cat "$RUN/keys/$k")";;
        boolean) defaults write com.weiwei.shiyin "$k" -bool "$(cat "$RUN/keys/$k")";;
        *) defaults write com.weiwei.shiyin "$k" -string "$(cat "$RUN/keys/$k")";; esac
      echo "改回：$k = $(cat "$RUN/keys/$k")（檢查中被 DEBUG 指令改成 ${now}）"
    fi
  done
  SAVED_KEYS=""
}
dbg() { run python3 "$ROOT/scripts/fork/check-debug.py" "$1" "$HOME_DIR" "$CTL" --out "$OUT/$2" "${@:3}"; }
SESSION_OK=0
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
  run "$CTL" seedfixtures "$ROOT/shared/golden/fixtures.json" zh en ja; sleep 3
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
  stop_debug
  start_debug en || return 1
  "$CTL" seedfixtures "$ROOT/shared/golden/fixtures.json" zh en >/dev/null; sleep 3
  dbg shots shots --lang en || fail=1
  stop_debug
  rm -f "$OUT/shots/state-raw.json"
  EVID="shots/"
  NOTE="看一眼：$(cd "$OUT/shots" && ls *.png 2>/dev/null | tr '\n' ' ')"
  [ $fail = 1 ] && return 1
  return 4
}
i_session_fail() { NOTE="DEBUG 版沒有開起來（看 logs/debug-start.log）"; return 1; }

# ---------- 11、12、13 ----------
i_tsan() { run bash "$ROOT/scripts/fork/tsan-lockedvalue/run.sh"; }
i_defaults() {
  EVID="defaults-before.plist、defaults-after.plist"
  defaults_snapshot "$OUT/defaults-after.plist" || { NOTE="結束時拿不到設定快照，無法比對"; return 1; }
  if cmp -s "$OUT/defaults-before.plist" "$OUT/defaults-after.plist"; then NOTE="defaults export 前後逐位元組相同"; return 0; fi
  python3 - "$OUT/defaults-before.plist" "$OUT/defaults-after.plist" <<'PY'
import plistlib, sys
def load(p):
    raw = open(p, 'rb').read()
    return {} if raw.startswith(b'MA-CHECK: domain absent') else plistlib.loads(raw)
a, b = (load(p) for p in sys.argv[1:])
for k in sorted(set(a) | set(b)):
    if a.get(k) != b.get(k):
        print(f'{k}: {a.get(k)!r} → {b.get(k)!r}'[:300])
PY
  NOTE="設定跟開始前不同（鍵列在 log；可能是檢查留下的，也可能是使用者同時改的），沒有自動改回"; return 1
}
i_manual() { NOTE="4.7.6 → 新版的 app 內更新：開舊會議看標記、靜音、條列頁（使用者在電腦前做）"; return 4; }

# ---------- 跑 ----------
echo "回歸檢查（$MODE${ONLY:+，只跑 ${ONLY//,/ }}）：$ROOT @ $(git -C "$ROOT" rev-parse --short HEAD)；輸出 $OUT"
item 1 "編譯（swift build、release、DEBUG）" i_build
[ -n "$ONLY" ] || [ "$MODE" = quick ] || [ -n "$BUILT" ] || BUILD_FAILED=1
item 2 "migration（check-fork-migrations）" i_mig
item 3 "品牌（掃描、brand-test、建置結果、逐鍵比對）" i_brand
item T "check.sh 自己的負對照（check-test.py）" i_selftest
item I1 "接點隔離（isolation-check）" i_iso
item I2 "隔離檢查的回歸測試" i_isotest
item L "介面字串（l10n.py check）" i_l10n
item 4 "F1 名稱、網址、圖示、接點" i_f1
if want 5 || want 6 || want 7 || want 8 || want 9 || want 10 || want S; then
  need_build && save_keys
  if need_build && start_debug zh-Hant > "$OUT/logs/debug-start.log" 2>&1; then
    item 5 "F2 標記（錄音中標記、套用、只改這句的交易）" i_f2
    item 6 "F2 加上 5.0（編輯會議、分割、合併、封包）" i_f2edit
    item 7 "F3 靜音（狀態、快捷鍵、錄音檔）" i_f3
    item 8 "F3 加上 5.0（選單列、收音提示、muteHint）" i_f3hint
    item 9 "F4（議題切段、分段複製）" i_f4
    item 10 "F4 加上 5.0（noteitem 刪除後）" i_f4items
    item S "截圖（#7～#10 要看一眼的畫面，zh、en）" i_shots
    stop_debug
    restore_keys >> "$OUT/logs/debug-start.log" 2>&1
  else
    cat "$OUT/logs/debug-start.log" 2>/dev/null
    for id in 5 6 7 8 9 10 S; do item "$id" "DEBUG 版的項目" i_session_fail; done
  fi
fi
item 11 "DF5（TSan LockedValue）" i_tsan
item 12 "設定殘留（defaults 前後比對）" i_defaults
want 13 && item 13 "4.7.6 → 新版實機更新" i_manual

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
