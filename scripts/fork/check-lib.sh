# check.sh 的判斷（fork design §F0.4「失敗一律不放行」）：check.sh source 這支；scripts/fork/check-test.py 用假的
# defaults／lsof／ps／plutil 跑同樣的函式（負對照）。只定義函式，不執行任何東西。
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

# DEBUG 版本來就會寫進共用設定的鍵：開 DEBUG 版前記下，結束後改回（fork design §F0.4 #12）。
#   settingsPage：preview settings 記住開到哪一頁
#   NSWindow Frame main：主視窗的位置。螢幕配置跟上次存的不同（例如接了外接螢幕）時，AppKit 一打開視窗就重存
#   （2026-11-19 FIX-3a 接了兩台外接螢幕後的完整模式 #12 抓到）
# 只改回這幾個、而且是值真的變了的；其他鍵的差異交給 #12 回報，不自動改（可能是使用者同時改的）
WRITTEN_KEYS=("settingsPage" "NSWindow Frame main")
SAVED_KEYS=""
# save_keys／restore_keys 用 $RUN/keys 存開始前的值
save_keys() {
  [ -n "$SAVED_KEYS" ] && return 0
  mkdir -p "$RUN/keys"
  local i k
  for i in "${!WRITTEN_KEYS[@]}"; do
    k="${WRITTEN_KEYS[$i]}"
    if defaults read com.weiwei.shiyin "$k" > "$RUN/keys/$i" 2>/dev/null; then echo set > "$RUN/keys/$i.state"; else echo unset > "$RUN/keys/$i.state"; fi
    defaults read-type com.weiwei.shiyin "$k" 2>/dev/null | awk '{print $NF}' > "$RUN/keys/$i.type"
  done
  SAVED_KEYS=1
}
restore_keys() {
  [ -n "$SAVED_KEYS" ] || return 0
  local i k now now_state saved
  for i in "${!WRITTEN_KEYS[@]}"; do
    k="${WRITTEN_KEYS[$i]}"
    if now="$(defaults read com.weiwei.shiyin "$k" 2>/dev/null)"; then now_state=set; else now_state=unset; fi
    saved="$(cat "$RUN/keys/$i")"
    if [ "$(cat "$RUN/keys/$i.state")" = unset ]; then
      [ "$now_state" = set ] && defaults delete com.weiwei.shiyin "$k" && echo "改回：刪掉「${k}」（檢查前沒有這個鍵）"
    elif [ "$now_state" = unset ] || [ "$now" != "$saved" ]; then
      case "$(cat "$RUN/keys/$i.type")" in
        integer) defaults write com.weiwei.shiyin "$k" -int "$saved";;
        boolean) defaults write com.weiwei.shiyin "$k" -bool "$saved";;
        *) defaults write com.weiwei.shiyin "$k" -string "$saved";;
      esac
      echo "改回：「${k}」= ${saved}（檢查中被 DEBUG 版改成 ${now}）"
    fi
  done
  SAVED_KEYS=""
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
