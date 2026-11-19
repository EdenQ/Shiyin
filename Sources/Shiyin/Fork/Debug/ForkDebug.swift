#if DEBUG
import AppKit

/// fork 的 DEBUG 指令（fork design §F0.1：一律 `ma` 開頭）。DebugControl 的 `default:` 先交給這裡，不認得才記「unknown」
@MainActor
enum ForkDebug {
    static func handle(_ args: [String], model: AppModel) -> Bool {
        switch args.first ?? "" {
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
            return true
        default:
            return false
        }
    }
}
#endif
