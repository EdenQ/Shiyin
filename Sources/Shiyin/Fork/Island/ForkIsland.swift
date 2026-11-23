import AppKit
import CoreGraphics

/// F11：錄音島放在哪個螢幕（fork design §F11、DF11）。上游 `RecordingIsland.place` 選螢幕的那一行先問 `screen()`
/// （`// MA-FORK(F11)`）；回傳 nil 時照上游（`NSScreen.main`）
@MainActor
enum ForkIsland {
    enum Placement: String, CaseIterable {
        case follow       // 跟著目前在用的螢幕（上游 R81.1）
        case builtin      // 內建螢幕（預設）
        case mainWindow   // 主視窗所在的螢幕
    }

    /// 設定鍵（F11.6）：沒有值、不認得時當成 builtin
    static let placementKey = "maIslandScreen"

    static var placement: Placement {
        Placement(rawValue: UserDefaults.standard.string(forKey: placementKey) ?? "") ?? .builtin
    }

    /// 最後一次記下的主視窗所在螢幕（display ID，只記在記憶體；F11.3）
    private(set) static var rememberedDisplay: CGDirectDisplayID?
    private static var observers: [NSObjectProtocol] = []

    /// 上游 `place` 的接點：nil＝照上游
    static func screen() -> NSScreen? { pick().screen }

    /// 理由：follow、builtin、mainWindow、mainWindowRemembered、upstream（退到上游）
    static func pick() -> (screen: NSScreen?, reason: String) {
        switch placement {
        case .follow:
            return (nil, "follow")
        case .builtin:
            if let screen = builtinScreen() { return (screen, "builtin") }
            return mainWindowPick()
        case .mainWindow:
            return mainWindowPick()
        }
    }

    private static func mainWindowPick() -> (screen: NSScreen?, reason: String) {
        if let screen = currentMainWindowScreen() { return (screen, "mainWindow") }
        if let id = rememberedDisplay, let screen = NSScreen.screens.first(where: { displayID($0) == id }) {
            return (screen, "mainWindowRemembered")
        }
        return (nil, "upstream")
    }

    // MARK: 螢幕

    static func displayID(_ screen: NSScreen) -> CGDirectDisplayID? {
        (screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber)?.uint32Value
    }

    /// 系統判斷的內建螢幕（不看名稱：名稱跟著語言變、可以改；F11.2）
    static func isBuiltin(_ screen: NSScreen) -> Bool {
        guard let id = displayID(screen) else { return false }
        return CGDisplayIsBuiltin(id) != 0
    }

    static func builtinScreen() -> NSScreen? {
        #if DEBUG
        if simulateNoBuiltin { return nil }
        #endif
        return NSScreen.screens.first { isBuiltin($0) }
    }

    // MARK: 主視窗

    static func isMainWindow(_ window: NSWindow) -> Bool { window.identifier?.rawValue == "main" }

    /// 主視窗現在所在的螢幕（看得到、沒有縮到 Dock）；有的話同時記下
    static func currentMainWindowScreen() -> NSScreen? {
        var screen: NSScreen?
        #if DEBUG
        if let index = simulateMainScreen {
            screen = index >= 0 && index < NSScreen.screens.count ? NSScreen.screens[index] : nil
            if let screen { remember(screen) }
            return screen
        }
        #endif
        if let window = NSApp.windows.first(where: { isMainWindow($0) && $0.isVisible && !$0.isMiniaturized }) {
            screen = window.screen
        }
        if let screen { remember(screen) }
        return screen
    }

    static func remember(_ screen: NSScreen) {
        if let id = displayID(screen) { rememberedDisplay = id }
    }

    /// 由 `ForkStartup.install` 呼叫：主視窗移動、換螢幕、變成 key、要關掉或縮到 Dock 時記下它的螢幕
    static func install(_ model: AppModel) {
        guard observers.isEmpty else { return }
        #if DEBUG
        loadSimulation()
        #endif
        let names: [Notification.Name] = [NSWindow.didMoveNotification, NSWindow.didChangeScreenNotification,
                                          NSWindow.didBecomeKeyNotification, NSWindow.willCloseNotification,
                                          NSWindow.willMiniaturizeNotification]
        for name in names {
            observers.append(NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { note in
                guard let window = note.object as? NSWindow else { return }
                MainActor.assumeIsolated {
                    if isMainWindow(window), let screen = window.screen { remember(screen) }
                }
            })
        }
    }

    #if DEBUG
    // MARK: DEBUG 的模擬（fork design §F11.4）

    static var simulateNoBuiltin = false
    /// 主視窗在 `NSScreen.screens[N]`；-1：主視窗關著；nil：照真的
    static var simulateMainScreen: Int?

    private static func loadSimulation() {
        let defaults = UserDefaults.standard
        simulateNoBuiltin = defaults.bool(forKey: "maIslandNoBuiltin")
        if let value = defaults.string(forKey: "maIslandMainScreen"), let index = Int(value) { simulateMainScreen = index }
    }

    static func setRemembered(_ index: Int?) {
        if let index, index >= 0, index < NSScreen.screens.count {
            remember(NSScreen.screens[index])
        } else {
            rememberedDisplay = nil
        }
    }
    #endif
}
