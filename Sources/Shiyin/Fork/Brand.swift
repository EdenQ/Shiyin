import AppKit
import SwiftUI

/// Fork 的品牌（design §F7、DF7）：原始碼照上游寫「拾音」「Shiyin」，建置時 `scripts/fork/brand.py apply`
/// 換掉翻譯表、InfoPlist.strings、Info.plist、Credits，並把名稱對照寫進 Info.plist 的 `MABrand`。
/// 不經過翻譯表的少數地方（關於面板、更新說明選段落、5.0 的提醒事項列表）用這裡的 1 行接點。
/// 沒有 `MABrand`（`swift build` 直接跑、上游原樣）時一律回傳上游的名稱，行為跟上游相同。
enum Brand {
    /// 介面語言 → [上游名稱: fork 名稱]，例如 "zh-Hant": ["拾音": "會議助手"]
    nonisolated(unsafe) static var table: [String: [String: String]] = loadTable()
    /// 「關於」面板的 app 名稱（MA — Meeting Assistant）；沒有就用系統預設（CFBundleName）
    nonisolated(unsafe) static var aboutName: String? = info["aboutName"] as? String
    /// 簡稱（MA）：只用在放不下完整名稱的地方（錄音島，F7.7）；沒有就不換
    nonisolated(unsafe) static var shortName: String? = info["shortName"] as? String

    private static var info: [String: Any] { Bundle.main.object(forInfoDictionaryKey: "MABrand") as? [String: Any] ?? [:] }

    private static func loadTable() -> [String: [String: String]] {
        (info["names"] as? [String: [String: String]]) ?? [:]
    }

    /// 上游名稱換成 fork 名稱：「拾音」跟著介面語言（繁體／簡體），「Shiyin」換英文名稱；沒有對照就原樣
    static func name(_ upstream: String) -> String {
        let preferred = Bundle.main.preferredLocalizations.first ?? "en"
        if let hit = table[preferred]?[upstream] { return hit }
        for lang in ["zh-Hant", "en", "zh-Hans"] { if let hit = table[lang]?[upstream] { return hit } }
        return upstream
    }

    /// 比對名稱時用：fork 名稱在前、上游名稱在後（使用者在舊版建立的「拾音」列表、舊版的更新說明都認得）
    static func names(_ upstream: String...) -> [String] {
        var out: [String] = []
        for name in upstream.map(name(_:)) + upstream where !out.contains(name) { out.append(name) }
        return out
    }

    /// 查表後的字串裡的完整品牌名（會議助手、会议助手、Meeting Assistant）換成簡稱，跟中文相鄰時前後補一個空白：
    /// 「打開會議助手」→「打開 MA」、"Open Meeting Assistant" → "Open MA"（錄音島，F7.7、fork design §F7.3）
    static func short(_ text: String) -> String {
        guard let short = shortName, !short.isEmpty else { return text }
        let full = Set(table.values.flatMap { $0.values }).sorted { $0.count > $1.count }
        var out = text
        for name in full where !name.isEmpty {
            while let range = out.range(of: name) {
                let before = out[..<range.lowerBound].last, after = out[range.upperBound...].first
                out.replaceSubrange(range, with: (isCJK(before) ? " " : "") + short + (isCJK(after) ? " " : ""))
            }
        }
        return out
    }

    private static func isCJK(_ c: Character?) -> Bool {
        guard let scalar = c?.unicodeScalars.first?.value else { return false }
        return (0x3400...0x4DBF).contains(scalar) || (0x4E00...0x9FFF).contains(scalar) || (0xF900...0xFAFF).contains(scalar)
    }

    /// 上游 5.0 的提醒事項（R101）找已存在的列表時用：新名稱「會議助手」、舊名稱「拾音」「Shiyin」都認得，
    /// 使用者在舊版建立的列表沿用、不重複建立。新建的列表用 `name(Reminders.listTitle)`（design §F7.3）
    static func isListTitle(_ title: String) -> Bool { names("拾音", "Shiyin").contains(title) }   // l10n-skip
}

/// 「關於 MA」：系統預設的關於面板顯示 CFBundleName（MA），fork 要顯示完整名稱（design §F7.3）
struct BrandAboutCommand: Commands {
    var body: some Commands {
        CommandGroup(replacing: .appInfo) {
            Button("關於 MA") {
                NSApp.orderFrontStandardAboutPanel(options: Brand.aboutName.map { [.applicationName: $0] } ?? [:])
            }
        }
    }
}
