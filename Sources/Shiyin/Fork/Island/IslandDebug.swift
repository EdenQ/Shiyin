#if DEBUG
import AppKit

/// F11 的 DEBUG 指令 `maisland`（fork design §F11.5）
@MainActor
extension ForkDebug {
    static func island(_ args: [String], model: AppModel) -> Bool {
        guard args[0] == "maisland" else { return false }
        let sub = args.count > 1 ? args[1] : ""
        switch sub {
        case "screens":   // maisland screens <輸出.json>
            if args.count > 2 { write(islandScreens(), to: args[2]) }
        case "mode":   // maisland mode follow|builtin|mainWindow：寫設定（測試版的網域），馬上重新放
            if args.count > 2, let mode = ForkIsland.Placement(rawValue: args[2]) {
                UserDefaults.standard.set(mode.rawValue, forKey: ForkIsland.placementKey)
                RecordingIsland.shared.place(animated: false)
            }
        case "simulate":   // maisland simulate nobuiltin on|off、mainscreen <N|closed|off>、remembered <N|none>
            let what = args.count > 2 ? args[2] : ""
            let value = args.count > 3 ? args[3] : "off"
            switch what {
            case "nobuiltin":
                ForkIsland.simulateNoBuiltin = value == "on"
            case "mainscreen":
                ForkIsland.simulateMainScreen = value == "closed" ? -1 : Int(value)
            case "remembered":
                ForkIsland.setRemembered(Int(value))
            case "off":
                ForkIsland.simulateNoBuiltin = false
                ForkIsland.simulateMainScreen = nil
            default:
                break
            }
            RecordingIsland.shared.place(animated: false)
        default:
            break
        }
        return true
    }

    static func islandScreens() -> [String: Any] {
        let screens = NSScreen.screens
        func index(_ screen: NSScreen?) -> Any {
            guard let screen, let i = screens.firstIndex(where: { $0 === screen }) else { return NSNull() }
            return i
        }
        let rect: (NSRect) -> [CGFloat] = { [$0.minX, $0.minY, $0.width, $0.height] }
        let pick = ForkIsland.pick()
        let upstream = NSScreen.main ?? screens.first
        let remembered = ForkIsland.rememberedDisplay.flatMap { id in screens.first { ForkIsland.displayID($0) == id } }
        var mainWindow: NSScreen?
        if let window = NSApp.windows.first(where: { ForkIsland.isMainWindow($0) && $0.isVisible && !$0.isMiniaturized }) {
            mainWindow = window.screen
        }
        return [
            "screens": screens.enumerated().map { i, screen in
                ["index": i, "displayID": ForkIsland.displayID(screen).map { Int($0) } ?? NSNull(),
                 "frame": rect(screen.frame), "visibleFrame": rect(screen.visibleFrame),
                 "builtin": ForkIsland.isBuiltin(screen), "notch": IslandNotch(screen: screen).hasNotch] as [String: Any]
            },
            "main": index(NSScreen.main),
            "placement": ForkIsland.placement.rawValue,
            "pick": index(pick.screen),
            "reason": pick.reason,
            "expected": index(pick.screen ?? upstream),
            "upstream": index(upstream),
            "mainWindow": index(mainWindow),
            "remembered": index(remembered),
            "simulate": ["noBuiltin": ForkIsland.simulateNoBuiltin, "mainScreen": ForkIsland.simulateMainScreen ?? NSNull()] as [String: Any],
            "island": RecordingIsland.shared.debugInfo,
        ]
    }
}
#endif
