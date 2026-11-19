// DF5 的資料競態檢查（fork design §F-UP 的 §50.2、DF5；PLAN-fork-5.0 §8.1 第 11 項）。
// LockedValue 由 run.sh 從 Sources/Shiyin/Capture/AudioSources.swift 原樣取出（LockedValue.swift），不碰硬體：
// 背景佇列（同 Recorder 的 deviceQueue）一直 start()（讀 UID、寫 current），主執行緒同時一直換 UID、讀 current。
// 參數 locked：照 MicrophoneSource、FileSource 的寫法用 LockedValue 存；plain：改回普通屬性（對照組，TSan 應該報告競態）
import Foundation

struct Device: Equatable { var uid: String; var name: String }

protocol Source: AnyObject {
    var deviceUID: String { get set }
    var current: Device? { get set }
}

/// 照 AudioSources.swift 的 MicrophoneSource：uidState、currentState 是 LockedValue，對外是計算屬性
final class LockedSource: Source {
    private let uidState = LockedValue("")
    private let currentState = LockedValue<Device?>(nil)
    var deviceUID: String {
        get { uidState.value }
        set { uidState.value = newValue }
    }
    var current: Device? {
        get { currentState.value }
        set { currentState.value = newValue }
    }
}

/// 對照組：4.7.6 以前的寫法（普通屬性）
final class PlainSource: Source {
    var deviceUID = ""
    var current: Device?
}

let mode = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "locked"
let source: Source = mode == "plain" ? PlainSource() : LockedSource()
let rounds = 30_000
let deviceQueue = DispatchQueue(label: "deviceQueue")
let done = DispatchSemaphore(value: 0)

deviceQueue.async {
    for i in 0..<rounds {
        let uid = source.deviceUID                         // start() 一開始讀一次 UID 當快照
        source.current = Device(uid: uid, name: "mic \(i)") // 開始收音後寫正在收音的裝置
    }
    done.signal()
}
var seen = 0
for i in 0..<rounds {
    source.deviceUID = "uid-\(i % 7)"                      // 換麥克風
    if source.current != nil { seen += 1 }                 // 更新畫面時讀
}
done.wait()
print("\(mode): \(rounds) rounds done, current seen \(seen) times")
