# check.sh 的判斷（fork design §F0.4「失敗一律不放行」）：check.sh source 這支；scripts/fork/check-test.py 用假的
# defaults／lsof／ps／lsregister 跑同樣的函式（負對照）。只定義函式，不執行任何東西。
# 判斷不了的情況一律算失敗：拿不到快照、lsof 失敗、比對工具出錯都不能當成「相同」「通過」。

MA_DOMAIN="com.weiwei.shiyin"
MA_ITEMS="1 2 3 4 5 6 7 8 9 10 11 12 13 I1 I2 L T S"

# defaults_snapshot <輸出檔>：共用設定的快照。0：成功（plist，或網域確實不存在時寫 MA-CHECK: domain absent）；1：拿不到
defaults_snapshot() {
  local out="$1" err
  rm -f "$out"
  if err="$(defaults export "$MA_DOMAIN" "$out" 2>&1)"; then
    if [ -s "$out" ] && plutil -lint -s "$out" >/dev/null 2>&1; then return 0; fi
    echo "defaults export 成功，但輸出不是 plist：$out"
    rm -f "$out"; return 1
  fi
  if defaults read "$MA_DOMAIN" 2>&1 >/dev/null | grep -q "Domain $MA_DOMAIN does not exist"; then
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

# cleanup_test_domain <測試 id> [複本 app]：取消登記複本、刪測試網域和它的快取。id 不是測試網域就什麼都不做、return 1
cleanup_test_domain() {
  local id="$1" app="${2:-}" lib="$HOME/Library"
  case "$id" in "$MA_TEST_DOMAIN"|"$MA_TEST_DOMAIN".*) ;; *) echo "拒絕清理：$id 不是測試網域" >&2; return 1;; esac
  [ -n "$app" ] && [ -d "$app" ] && "$MA_LSREGISTER" -u "$app" >/dev/null 2>&1
  defaults delete "$id" >/dev/null 2>&1
  rm -rf "$lib/Preferences/$id.plist" "$lib/HTTPStorages/$id" "$lib/HTTPStorages/$id.binarycookies" \
         "$lib/Caches/$id" "$lib/Saved Application State/$id.savedState" "$lib/WebKit/$id"
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
