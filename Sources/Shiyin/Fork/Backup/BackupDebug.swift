#if DEBUG
import AppKit

/// F10 的 DEBUG 指令 `mabackup`（fork design §F10.7）
@MainActor
extension ForkDebug {
    static func backup(_ args: [String], model: AppModel) -> Bool {
        guard args[0] == "mabackup" else { return false }
        let backup = ForkBackup.shared
        let sub = args.count > 1 ? args[1] : "status"
        let out = args.count > 2 ? args[2] : nil
        switch sub {
        case "now", "check":   // mabackup now|check [<輸出.json>]：立即備份／排程的檢查，做完寫結果
            Task {
                let outcome = await backup.check(manual: sub == "now")
                if let out {
                    var status = backupStatus(model)
                    status["outcome"] = outcome.rawValue
                    status["reason"] = backup.lastReason ?? NSNull()
                    write(status, to: out)
                }
            }
        case "status":   // mabackup status <輸出.json>
            if let out { write(backupStatus(model), to: out) }
        case "prune":
            backup.prune()
        case "simulate":   // mabackup simulate lowdisk|fail|off
            let what = args.count > 2 ? args[2] : "off"
            backup.simulateLowDisk = what == "lowdisk"
            backup.simulateFail = what == "fail"
        case "age":   // mabackup age <天數>
            if args.count > 2, let days = Double(args[2]) { backup.age(days: days) }
        case "menu":   // mabackup menu <輸出.json>：「MA」選單每一項的標題、能不能按
            guard let out else { break }
            // 先 update()：SwiftUI 的 .disabled 在選單驗證時才套到 NSMenuItem（選單打開前 isEnabled 不準）
            func dump(_ menu: NSMenu?) -> [[String: Any]] {
                menu?.update()
                return (menu?.items ?? []).map { ["title": $0.isSeparatorItem ? "-" : $0.title, "enabled": $0.isEnabled] }
            }
            let menus = NSApp.mainMenu?.items ?? []
            // file：上游「檔案」選單（對照錄音中能不能按的「暫停錄音」等）
            write(["items": dump(menus.first?.submenu), "file": menus.count > 1 ? dump(menus[1].submenu) : []], to: out)
        default:
            break
        }
        return true
    }

    static func backupStatus(_ model: AppModel) -> [String: Any] {
        let backup = ForkBackup.shared
        let iso = ISO8601DateFormatter()
        return [
            "enabled": ForkBackup.enabled,
            "running": backup.running,
            "lastCheck": backup.lastCheck?.rawValue ?? NSNull(),
            "backups": ForkBackup.backups(),
            "lastSuccess": ForkBackup.lastSuccess().map { iso.string(from: $0) } ?? NSNull(),
            "lastError": UserDefaults.standard.string(forKey: ForkBackup.lastErrorKey) ?? NSNull(),
            "failingSince": (UserDefaults.standard.object(forKey: ForkBackup.failingSinceKey) as? Date).map { iso.string(from: $0) } ?? NSNull(),
            "warning": backup.warning ?? NSNull(),
            "menuEnabled": backup.canBackupNow,
            "folder": ForkBackup.folder.path,
        ]
    }

    /// state 的 backup
    static func backupState(_ out: inout [String: Any], model: AppModel) {
        out["backup"] = backupStatus(model)
    }
}
#endif
