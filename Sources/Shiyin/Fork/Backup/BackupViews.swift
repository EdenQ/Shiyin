import SwiftUI

/// 「MA」選單的「立即備份資料庫」「打開備份資料夾」（fork design §F10.6）：放在「設定⋯」和「服務」之間。
/// 不用 `before: .appSettings`：上游用 `replacing: .appSettings` 換掉了設定那一組，放在它前面的項目不會出現（實測）
struct ForkBackupMenuCommands: Commands {
    let model: AppModel

    var body: some Commands {
        CommandGroup(before: .systemServices) {
            Button("立即備份資料庫") { ForkBackup.backupNowFromMenu(model) }
                .disabled(!ForkBackup.shared.canBackupNow)
            Button("打開備份資料夾") { ForkBackup.openFolder() }
            Divider()
        }
    }
}

/// 設定「一般」頁的「資料庫備份」（fork design §F10.6、F10.7）
struct ForkBackupSettingsSection: View {
    @AppStorage(ForkBackup.enabledKey) private var enabled = true
    private let backup = ForkBackup.shared

    var body: some View {
        Section("資料庫備份") {
            Toggle("每天自動備份資料庫", isOn: $enabled)
            LabeledContent("上次備份") { Text(lastText) }
            if let warning = backup.warning {
                Text(warning)
                    .font(.callout).foregroundStyle(.red).fixedSize(horizontal: false, vertical: true)
            }
            Text("保留最近 7 份，放在資料夾的 backups/daily。錄音中不備份。")
                .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            Button("打開備份資料夾") { ForkBackup.openFolder() }
        }
    }

    private var lastText: String {
        _ = backup.revision
        guard let last = ForkBackup.lastSuccess() else { return String(localized: "還沒有備份") }
        return last.formatted(date: .abbreviated, time: .shortened)
    }
}
