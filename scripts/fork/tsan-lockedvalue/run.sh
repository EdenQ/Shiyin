#!/bin/bash
# DF5 的 TSan 檢查：python 從 AudioSources.swift 取出 LockedValue，編成 -sanitize=thread，
# locked 跑 3 次要 0 個資料競態（exit 0）；plain（對照組）跑 3 次要報告 data race（exit 非 0）
set -u
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
python3 - "$ROOT/Sources/Shiyin/Capture/AudioSources.swift" "$WORK/LockedValue.swift" <<'PY'
import re,sys
s=open(sys.argv[1]).read()
m=re.search(r'^final class LockedValue<Value>.*?^}\n', s, re.S|re.M)
if not m: sys.exit('LockedValue not found')
open(sys.argv[2],'w').write('import Foundation\n'+m.group(0))
PY
xcrun swiftc -swift-version 5 -sanitize=thread -Onone -module-cache-path "$WORK/mc" -o "$WORK/tsan" "$ROOT/scripts/fork/tsan-lockedvalue/main.swift" "$WORK/LockedValue.swift" || exit 2
fail=0
for mode in locked plain; do
  for n in 1 2 3; do
    TSAN_OPTIONS=halt_on_error=1 "$WORK/tsan" $mode > "$WORK/out" 2>&1; code=$?
    races=$(grep -c 'WARNING: ThreadSanitizer: data race' "$WORK/out")
    echo "$mode #$n: exit $code, data race reports $races"
    if [ $mode = locked ] && { [ $code -ne 0 ] || [ $races -ne 0 ]; }; then fail=1; fi
    if [ $mode = plain ] && [ $races -eq 0 ]; then echo "  對照組沒有報告競態：測試沒有效"; fail=1; fi
  done
done
[ $fail = 0 ] && echo "PASS：LockedValue 沒有資料競態；對照組（普通屬性）有" || echo FAIL
exit $fail
