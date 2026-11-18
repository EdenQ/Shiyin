import SwiftUI

/// F3 靜音麥克風的全域快捷鍵開關（fork design §F3.3）：放在 5.0 設定「錄音」頁的「提醒與快捷鍵」（R108）
struct ForkMuteSettingsRow: View {
    @Environment(AppModel.self) private var model
    @AppStorage(AppSettings.muteHotKeyKey) private var muteHotKey = true

    var body: some View {
        Toggle("錄音中按 \(GlobalHotKey.muteDisplay) 靜音或打開麥克風（麥克風＋電腦聲音的錄音）", isOn: $muteHotKey)
            .onChange(of: muteHotKey) { _, enabled in
                GlobalHotKey.shared.setMuteEnabled(enabled && model.recorder.canMuteMic)
            }
    }
}
