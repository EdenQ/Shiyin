#if DEBUG
import Foundation

/// F3 的 DEBUG 指令（fork design §F3.4）：`micmute` 是 4.x 就有的名字，照舊；`hotkey mute` 在上游的 hotkey 指令加一個接點
@MainActor
extension ForkDebug {
    static func mute(_ args: [String], model: AppModel) -> Bool {
        switch args[0] {
        case "micmute":   // micmute on|off|toggle|dismiss：錄音畫面的麥克風圖示、提示列的「知道了」
            switch args.count > 1 ? args[1] : "toggle" {
            case "on": model.recorder.setMicMuted(true)
            case "off": model.recorder.setMicMuted(false)
            case "dismiss": model.recorder.dismissMuteHint()
            default: model.recorder.toggleMicMute()
            }
        default: return false
        }
        return true
    }

    /// state：recorder 的 micMuted、muteHint、muteCheck；hotkey 的 muteRegistered
    static func muteState(_ out: inout [String: Any], model: AppModel) {
        if var recorder = out["recorder"] as? [String: Any] {
            recorder["micMuted"] = model.recorder.micMuted
            recorder["muteHint"] = model.recorder.muteHint
            recorder["muteCheck"] = model.recorder.muteCheck
            out["recorder"] = recorder
        }
        if var hotkey = out["hotkey"] as? [String: Any] {
            hotkey["muteRegistered"] = GlobalHotKey.shared.isMuteRegistered
            out["hotkey"] = hotkey
        }
    }
}
#endif
