#if DEBUG
import AppKit

/// fork 的 DEBUG 指令（fork design §F0.1：新的一律 `ma` 開頭，4.x 就有的照舊）。上游 DebugControl 的 `default:` 先交給這裡，
/// 不認得才記「unknown」（`// MA-FORK(F0)`）；`state` 的輸出在上游的 `return out` 前由 `augmentState` 補上 fork 的欄位
@MainActor
enum ForkDebug {
    static func handle(_ args: [String], model: AppModel) -> Bool {
        guard !args.isEmpty else { return false }
        return general(args, model: model) || speakerTags(args, model: model) || mute(args, model: model) || notes(args, model: model)
    }

    /// 跟上游同名、fork 要蓋過的指令（上游 DebugControl 的 switch 之前先問這裡，`// MA-FORK(F0)`）：
    /// `windowshot <輸出.png> [main|popover]` 是 4.x 的 fork 寫法，上游 5.0 另有 `windowshot <視窗 id> <輸出.png>`；
    /// 5.0.1 的 fork 那一段排在上游的前面，所以一直是 fork 的寫法（測試腳本照這個用）。不改名（fork design §F0.1 第 6 點）
    static let shadowed: Set<String> = ["windowshot"]

    static func shadows(_ args: [String], model: AppModel) -> Bool {
        guard let name = args.first, shadowed.contains(name) else { return false }
        return general(args, model: model)
    }

    static func augmentState(_ out: inout [String: Any], model: AppModel) {
        speakerTagsState(&out, model: model)
        muteState(&out, model: model)
        notesState(&out, model: model)
    }

    private static func general(_ args: [String], model: AppModel) -> Bool {
        switch args[0] {
        case "windowshot":   // windowshot <輸出.png> [main|popover]：app 自己把視窗畫成圖片，不需要螢幕錄製權限（4.x 就有的名字）
            let popover = args.count > 2 && args[2] == "popover"
            let window = NSApp.windows.last { $0.isVisible && (popover ? $0.className.contains("Popover") : $0.identifier?.rawValue == "main") }
            if let view = window?.contentView?.superview ?? window?.contentView,
               let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) {
                view.cacheDisplay(in: view.bounds, to: rep)
                try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: args[1]))
            }
        case "mawindowshot":   // mawindowshot <輸出.png> <island|視窗的 identifier、標題或類別名稱的一部分>：app 自己把那個視窗畫成圖片
            // （錄音島 R81 看 F3.7 的靜音顯示、設定的預覽看 F3 的開關）；不需要螢幕錄製權限
            guard args.count > 2 else { return true }
            let key = args[2]
            let window = NSApp.windows.first { w in
                w.isVisible && (key == "island" ? w is IslandPanel
                    : (w.identifier?.rawValue ?? "").contains(key) || w.title.contains(key) || w.className.contains(key))
            }
            guard let view = window?.contentView, let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return true }
            view.cacheDisplay(in: view.bounds, to: rep)
            try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: args[1]))
        default:
            return false
        }
        return true
    }

    /// 同上游 DebugControl 的 write（那份是 private）
    static func write(_ object: [String: Any], to path: String) {
        guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys]) else { return }
        try? data.write(to: URL(fileURLWithPath: path))
    }
}
#endif

/// `-debugQuietPrompts YES`（DEBUG 版）：驗證時不要跳出系統的通知詢問、通知（fork design §F0.1），內容照樣記在 recent。
/// 上游 Notifier.post 的接點；正式版一律 false
enum ForkDebugPrompts {
    static var quiet: Bool {
        #if DEBUG
        UserDefaults.standard.bool(forKey: "debugQuietPrompts")
        #else
        false
        #endif
    }
}
