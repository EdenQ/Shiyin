import SwiftUI

/// 設定「錄音與轉錄 → 提醒與快捷鍵」的「錄音島放在」（F11.1，fork design §F11.3）。由 F0 的 `ForkRecordingSettingsRows` 放進去
struct ForkIslandScreenRow: View {
    @AppStorage(ForkIsland.placementKey) private var placement = ForkIsland.Placement.builtin.rawValue
    @AppStorage(AppSettings.recordingIslandKey) private var islandEnabled = true

    var body: some View {
        Picker("錄音島放在", selection: $placement) {
            Text("跟著目前在用的螢幕").tag(ForkIsland.Placement.follow.rawValue)
            Text("內建螢幕").tag(ForkIsland.Placement.builtin.rawValue)
            Text("主視窗所在的螢幕").tag(ForkIsland.Placement.mainWindow.rawValue)
        }
        .disabled(!islandEnabled)
        .onChange(of: placement) { _, _ in RecordingIsland.shared.place(animated: true) }
        Text("選內建螢幕時，筆電闔上或沒有內建螢幕就放在主視窗所在的螢幕。偵測到線上會議的提醒也在同一個螢幕。")
            .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
    }
}
