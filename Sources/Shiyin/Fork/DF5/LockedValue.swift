import Foundation

/// 跨執行緒讀寫的小值（fork design DF5）：每次讀寫只短暫拿鎖，不會等正在進行的重新連接。
/// 換麥克風在主執行緒寫 UID、重新連接在背景佇列讀，沒有鎖就是資料競態（2026-11-16 審查用 TSan 證實）。
/// 用在上游 AudioSources 的 MicrophoneSource、FileSource（`// MA-FORK(DF5)`）；上游哪天自己加鎖就刪掉
final class LockedValue<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: Value
    init(_ value: Value) { stored = value }
    var value: Value {
        get { lock.withLock { stored } }
        set { lock.withLock { stored = newValue } }
    }
}
