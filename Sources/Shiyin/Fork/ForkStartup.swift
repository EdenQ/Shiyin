import SwiftUI

/// fork 的共用入口（fork design §F0.2、§F10.6）：上游檔各只有 1 行接點，以後的 fork 功能加在這裡、不再加接點。
/// AppModel 啟動時：`ForkStartup.install(self)   // MA-FORK(F0)`（原本是 F3 的 `ForkMute.install(self)`，位置不變）
@MainActor
enum ForkStartup {
    static func install(_ model: AppModel) {
        ForkMute.install(model)     // F3：⌃⌥⌘M、靜音的提醒
        ForkBackup.install(model)   // F10：定期備份資料庫
    }
}

/// 「MA」選單（AppCommands 的 `ForkAppMenuCommands(model: model)   // MA-FORK(F0)`，原本是 F7 的 `BrandAboutCommand()`）
struct ForkAppMenuCommands: Commands {
    let model: AppModel

    var body: some Commands {
        BrandAboutCommand()                   // F7：關於 MA
        ForkBackupMenuCommands(model: model)  // F10：立即備份、打開備份資料夾
    }
}
