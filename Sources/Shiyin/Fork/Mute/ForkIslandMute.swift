import SwiftUI

/// F3.7 錄音島（上游 5.0 的 R81）顯示麥克風靜音（fork design §F3.6）：
/// 收起時紅點換成劃掉的麥克風；滑過去寫「麥克風靜音中」加「打開麥克風」；忘了打開的提醒（F3.4）跟錄音畫面的提示列一樣出現在島上（R81.2）
@MainActor
enum ForkIslandMute {
    /// 提醒的順序同錄音畫面的提示列：沒人說話 → 靜音中好像有人說話 → 藍牙 → 收音
    static func hintKey(_ recorder: Recorder) -> String? { recorder.muteHint ? "mute" : nil }

    static func hint(_ recorder: Recorder) -> IslandHint? {
        guard recorder.muteHint else { return nil }
        return IslandHint(text: Recorder.muteHintText, symbol: "mic.slash", buttons: [
            .init(title: String(localized: "知道了"), primary: false) { recorder.dismissMuteHint() },
            .init(title: String(localized: "打開麥克風"), primary: true) { recorder.setMicMuted(false) },
        ])
    }
}

/// 收起時的狀態點：靜音中是劃掉的麥克風（有提醒時琥珀色）
struct ForkIslandMutedDot: View {
    var alert: Bool
    var body: some View {
        Image(systemName: "mic.slash.fill")
            .font(.system(size: 10, weight: .semibold))
            .foregroundStyle(alert ? Color.signal : Color.red)
            .accessibilityLabel(Text("麥克風靜音中"))
    }
}

/// 滑過去時音量下面的一行：靜音中才出現
struct ForkIslandMuteRow: View {
    let recorder: Recorder
    var body: some View {
        if recorder.micMuted {
            HStack(spacing: 8) {
                Label("麥克風靜音中", systemImage: "mic.slash.fill").foregroundStyle(Color.signal)
                Spacer(minLength: 0)
                Button("打開麥克風") { recorder.setMicMuted(false) }
                    .buttonStyle(.plain)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .background(Capsule().fill(.white.opacity(0.15)))
            }
        }
    }
}
