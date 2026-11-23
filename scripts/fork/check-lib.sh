# check.sh 的判斷（fork design §F0.4「失敗一律不放行」）：check.sh source 這支；scripts/fork/check-test.py 用假的
# defaults／lsof／ps／lsregister 跑同樣的函式（負對照）。只定義函式，不執行任何東西。
# 判斷不了的情況一律算失敗：拿不到快照、lsof 失敗、比對工具出錯都不能當成「相同」「通過」。

MA_DOMAIN="com.weiwei.shiyin"
MA_ITEMS="1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 I1 I2 L T W S"

# domain_absent_message <網域> <defaults read 的 stderr，去掉結尾換行>：是不是「網域不存在」。
# 整段訊息要「只有一行、完全等於」支援的格式之一（REVIEW-3a4 P2-7：前後萬用字元會把
# `cfprefsd: Domain 'X' not found in cache; …`、正常訊息後面再接一行錯誤都當成不存在）：
#   macOS 27.2.1 實測（2026-11-20）：exit 1、stdout 空、stderr `Error: Domain 'X' not found.` 加換行
#   舊的寫法：`Domain X does not exist`
domain_absent_message() {
  [ -n "$1" ] || return 1
  [ "$2" = "Error: Domain '$1' not found." ] && return 0
  [ "$2" = "Domain $1 does not exist" ] && return 0
  return 1
}

# defaults_snapshot <輸出檔>：共用設定的快照。0：成功（plist，或網域確實不存在時寫 MA-CHECK: domain absent）；1：拿不到
defaults_snapshot() {
  local out="$1" err
  rm -f "$out"
  if err="$(defaults export "$MA_DOMAIN" "$out" 2>&1)"; then
    if [ -s "$out" ] && plutil -lint -s "$out" >/dev/null 2>&1; then return 0; fi
    echo "defaults export 成功，但輸出不是 plist：$out"
    rm -f "$out"; return 1
  fi
  if [ "$(domain_state "$MA_DOMAIN" 2>/dev/null)" = absent ]; then
    printf 'MA-CHECK: domain absent\n' > "$out"; return 0
  fi
  echo "defaults export 失敗：$err"
  rm -f "$out"; return 1
}

# verify_db_files <pid> <暫存 home> <正式資料夾>：DEBUG 版開著的資料庫都在暫存 home 下。0 通過；1 失敗（原因印出來）
verify_db_files() {
  local pid="$1" home="${2%/}" real="${3%/}" out path bad=0 found=0 n=0
  if ! out="$(lsof -p "$pid" -Fn 2>/dev/null)"; then echo "lsof -p $pid 失敗"; return 1; fi
  while IFS= read -r path; do
    case "$path" in n*) path="${path#n}";; *) continue;; esac
    n=$((n + 1))
    case "$path" in "$real"/*) echo "開了正式資料夾的檔：$path"; bad=1;; esac
    case "${path##*/}" in
      shiyin.sqlite|shiyin.sqlite-wal|shiyin.sqlite-shm)
        case "$path" in
          "$home"/*) [ "$path" = "$home/shiyin.sqlite" ] && found=1;;
          *) echo "暫存 home 以外的資料庫：$path"; bad=1;;
        esac;;
    esac
  done <<< "$out"
  [ $n -gt 0 ] || { echo "lsof 沒有列出任何檔"; return 1; }
  [ $found = 1 ] || { echo "沒看到暫存 home 的 shiyin.sqlite：$home/shiyin.sqlite"; bad=1; }
  return $bad
}

# compare_status <brand.py compare 的 exit code>：印出狀態；return 0 PASS、4 需人工、1 FAIL
compare_status() {
  case "$1" in
    0) echo PASS; return 0;;
    1) echo 需人工; return 4;;
    *) echo FAIL; return 1;;
  esac
}

# ---------- DEBUG 版用測試專用的 bundle id（fork design §F0.4 安全規則；REVIEW-3a2 P2-4） ----------
# 正式網域一律不寫：AppKit 的視窗位置、preview settings 的頁面都寫進測試網域，結束時整個刪掉。
# 不再「記下、改回」正式網域：分不出是檢查還是使用者同時改的，改回會蓋掉使用者的操作。
MA_TEST_DOMAIN="com.weiwei.shiyin.macheck"
MA_LSREGISTER="${MA_LSREGISTER:-/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister}"

# isolate_debug_app <建好的 DEBUG 版> <放複本的資料夾> [測試 id]：複製一份、換 bundle id、拿掉 URL scheme／文件類型／
# 匯出的 UTType（不搶 shiyin://、.shiyin）、ad-hoc 重簽。印出複本的路徑；0 成功、1 失敗（id 是正式的也算失敗）
isolate_debug_app() {
  local src="$1" dir="$2" id="${3:-$MA_TEST_DOMAIN}" app plist key
  case "$id" in "$MA_DOMAIN"|"") echo "測試 id 不能是正式的 $MA_DOMAIN" >&2; return 1;; esac
  app="$dir/$(basename "$src")"; plist="$app/Contents/Info.plist"
  rm -rf "$app"; mkdir -p "$dir" || return 1
  ditto "$src" "$app" || return 1
  /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $id" "$plist" >&2 || return 1
  for key in CFBundleURLTypes CFBundleDocumentTypes UTExportedTypeDeclarations; do
    /usr/libexec/PlistBuddy -c "Delete :$key" "$plist" >/dev/null 2>&1
  done
  [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$plist" 2>/dev/null)" = "$id" ] || { echo "換不了 bundle id" >&2; return 1; }
  for key in CFBundleURLTypes CFBundleDocumentTypes UTExportedTypeDeclarations; do
    /usr/libexec/PlistBuddy -c "Print :$key" "$plist" >/dev/null 2>&1 && { echo "$key 還在" >&2; return 1; }
  done
  codesign --force --sign - --identifier "$id" "$app" >&2 2>&1 || return 1
  codesign --verify --strict "$app" >&2 2>&1 || { echo "重簽後驗不過" >&2; return 1; }
  echo "$app"
}

# cleanup_test_domain <測試 id> [複本 app]：取消登記複本、刪測試網域和它的快取，做完核對後置條件（fork design §F0.4）。
# 0：確認清乾淨（網域明確不存在、快取檔都不在）；1：任何一步失敗或後置條件不成立（印出哪一步）。
# id 不是測試網域就什麼都不做、return 1
test_domain_files() {
  local id="$1" lib="$HOME/Library"
  printf '%s\n' "$lib/Preferences/$id.plist" "$lib/HTTPStorages/$id" "$lib/HTTPStorages/$id.binarycookies" \
    "$lib/Caches/$id" "$lib/Saved Application State/$id.savedState" "$lib/WebKit/$id"
}
domain_state() {   # domain_state <id>：印 absent／present；判斷不了（讀失敗但不是明確的「不存在」）return 1
  local out err rc tmp
  tmp="$(mktemp)" || { echo "mktemp 失敗" >&2; return 1; }
  out="$(defaults read "$1" 2>"$tmp")"; rc=$?   # 讀一次，stdout、stderr、exit code 分開看
  err="$(cat "$tmp")"; rm -f "$tmp"
  if [ $rc = 0 ]; then echo present; return 0; fi
  if [ -z "$out" ] && domain_absent_message "$1" "$err"; then echo absent; return 0; fi
  echo "讀不了網域 ${1}（exit ${rc}）：$err" >&2; return 1
}
cleanup_test_domain() {
  local id="$1" app="${2:-}" err=0 state f
  case "$id" in "$MA_TEST_DOMAIN"|"$MA_TEST_DOMAIN".*) ;; *) echo "拒絕清理：$id 不是測試網域" >&2; return 1;; esac
  if [ -n "$app" ] && [ -d "$app" ]; then
    "$MA_LSREGISTER" -u "$app" >/dev/null 2>&1 || { echo "lsregister -u 失敗：$app" >&2; err=1; }
  fi
  state="$(domain_state "$id")" || err=1
  if [ "$state" = present ]; then
    defaults delete "$id" >/dev/null 2>&1 || { echo "defaults delete $id 失敗" >&2; err=1; }
  fi
  while IFS= read -r f; do
    rm -rf "$f" 2>/dev/null || { echo "刪不掉：$f" >&2; err=1; }
  done < <(test_domain_files "$id")
  # 後置條件：網域明確不存在、檔都不在
  state="$(domain_state "$id")" || err=1
  [ "$state" = absent ] || { echo "清理後測試網域 $id 還在（${state:-判斷不了}）" >&2; err=1; }
  while IFS= read -r f; do
    [ -e "$f" ] && { echo "清理後還在：$f" >&2; err=1; }
  done < <(test_domain_files "$id")
  return $err
}

# extract_tag <repo> <tag> <放原始碼的資料夾>：git archive | tar；兩邊的 exit 都要是 0。
# pipeline 結束後立刻把 PIPESTATUS 整個存下來（REVIEW-3a4 P2-8：第一個 [ 會蓋掉 PIPESTATUS）
extract_tag() {
  local st
  git -C "$1" archive "$2" | tar -x -C "$3"
  st=("${PIPESTATUS[@]}")
  [ "${st[0]}" = 0 ] && [ "${st[1]:-1}" = 0 ] && return 0
  echo "git archive $2 | tar 失敗（git exit ${st[0]}、tar exit ${st[1]:-?}）" >&2; return 1
}

# resolve_cache <MA_CHECK_CACHE 的值，空字串＝預設> <repo>：快取的真實絕對路徑（fork design §F0.4「快取位置」；REVIEW-3a5 P2-9）。
# 快取會被建立、--clean-cache 會刪裡面的東西，所以在任何建立、建置、清理之前核對；不通過 return 2（印出原因），通過就印出路徑。
MA_CACHE_MARK=".ma-check-cache"
resolve_cache() {
  python3 - "$1" "$2" "$HOME" "${SHIYIN_HOME:-}" "$MA_CACHE_MARK" <<'PY'
import os, sys
raw, repo, home, shome, mark = sys.argv[1:6]
def fail(msg):
    print(f'快取位置不能用：{msg}', file=sys.stderr); sys.exit(2)
custom = raw != ''
cand = raw if custom else os.path.join(home, 'Library/Caches/ShiyinBuild/check')
if not os.path.isabs(cand):
    fail(f'要是絕對路徑：{cand}')
real = os.path.realpath   # 解開符號連結；不存在的部分照字面接上
c = real(cand)
def inside(a, b):   # a 等於 b 或在 b 底下
    return a == b or a.startswith(b.rstrip('/') + '/')
protected = {'~/Library/Caches/ShiyinBuild/app': os.path.join(home, 'Library/Caches/ShiyinBuild/app'),
             '~/Library/Application Support/Shiyin': os.path.join(home, 'Library/Application Support/Shiyin'),
             'repo': repo}
if shome:
    protected['SHIYIN_HOME'] = shome
for name, path in protected.items():
    p = real(path)
    if inside(c, p) or inside(p, c):
        fail(f'{cand}（解析後 {c}）跟受保護的 {name}（{p}）重疊')
for name, path in (('$HOME', home), ('/', '/')):
    p = real(path)
    if inside(p, c):
        fail(f'{cand}（解析後 {c}）是 {name} 本身或它的上層')
if custom and os.path.lexists(c):
    if not os.path.isdir(c):
        fail(f'{c} 不是資料夾')
    entries = os.listdir(c)
    if entries and not os.path.isfile(os.path.join(c, mark)):
        fail(f'{c} 是已經有東西、不是 check.sh 建的資料夾（沒有 {mark}）')
print(c)
PY
}

# valid_handlers <快照檔>：check-handlers 的輸出要有 scheme-default、type-default 兩行
valid_handlers() {
  [ -s "$1" ] && grep -q $'^scheme-default\t' "$1" && grep -q $'^type-default\t' "$1"
}
# prepare_handlers <放 helper 的路徑> <快照檔> <log>：編譯 check-handlers.swift、拿開始時的快照、核對內容。
# 都是開 DEBUG 版的必要條件：任一步失敗 return 1（印出哪一步）
prepare_handlers() {
  local bin="$1" snap="$2" log="$3" src
  src="$(dirname "${BASH_SOURCE[0]}")/check-handlers.swift"
  rm -f "$bin" "$snap"
  xcrun swiftc "$src" -module-cache-path "$(dirname "$bin")/mc" -o "$bin" > "$log" 2>&1 || { echo "check-handlers.swift 編譯失敗（${log}）"; return 1; }
  [ -x "$bin" ] || { echo "check-handlers 沒有產生執行檔"; return 1; }
  "$bin" > "$snap" 2>&1 || { echo "check-handlers 執行失敗：$(head -3 "$snap")"; return 1; }
  valid_handlers "$snap" || { echo "處理程式快照不完整（缺 scheme-default 或 type-default）：$(head -3 "$snap")"; return 1; }
}

# debug_apps：正在跑的 DEBUG 版（只有 DEBUG 版的執行檔有控制通道的名字），每行「pid 路徑」；ps 失敗 return 1
debug_apps() {
  local list p exe
  list="$(ps -axo pid=,comm=)" || { echo "ps 列不出程序" >&2; return 1; }
  while read -r p exe; do
    case "$exe" in */Contents/MacOS/Shiyin) ;; *) continue;; esac
    exe="$(ps -o comm= -p "$p" 2>/dev/null)" || continue   # 已經結束
    [ -n "$exe" ] && grep -q 'com.weiwei.shiyin.debug' "$exe" 2>/dev/null && echo "$p $exe"
  done <<< "$list"
  return 0
}

# snapshot_diff <開始的快照> <結束的快照>：逐位元組相同 return 0；不同時列出哪幾個鍵、return 1（只讀，不改任何設定）
snapshot_diff() {
  cmp -s "$1" "$2" && return 0
  python3 - "$1" "$2" <<'PY'
import plistlib, sys
def load(p):
    raw = open(p, 'rb').read()
    return {} if raw.startswith(b'MA-CHECK: domain absent') else plistlib.loads(raw)
a, b = (load(p) for p in sys.argv[1:])
for k in sorted(set(a) | set(b)):
    if a.get(k) != b.get(k):
        print(f'{k}: {a.get(k)!r} → {b.get(k)!r}'[:300])
PY
  return 1
}

# validate_only <逗號分隔的項目>：每一項都在白名單、至少一項。0 通過；2 參數錯
validate_only() {
  local list="$1" id n=0 IFS=','
  for id in $list; do
    [ -n "$id" ] || continue
    case " $MA_ITEMS " in *" $id "*) n=$((n + 1));; *) echo "--only 有不認得的項目：${id}（可以用：${MA_ITEMS}）"; return 2;; esac
  done
  [ $n -gt 0 ] || { echo "--only 沒有選到任何項目（可以用：${MA_ITEMS}）"; return 2; }
  return 0
}

# owned_pid <pid> <app>：這個 pid 還是這個 app 的執行檔（送訊號前核對，pid 可能被重用）
owned_pid() {
  local exe
  exe="$(ps -o comm= -p "$1" 2>/dev/null)" || return 1
  [ -n "$exe" ] && [ "$exe" = "$2/Contents/MacOS/Shiyin" ]
}
