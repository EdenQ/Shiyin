// Brand 接點的測試（design §F7.5）：swiftc -swift-version 5 -o <輸出> scripts/fork/brand-hooks-test/main.swift Sources/Shiyin/Fork/Brand.swift && <輸出>
import Foundation
var fails = 0
func expect(_ c: Bool, _ msg: String) { print((c ? "ok   " : "FAIL ") + msg); if !c { fails += 1 } }
// 沒有 MABrand（上游原樣）：名稱不變
Brand.table = [:]
expect(Brand.name("拾音") == "拾音", "unbranded name(拾音) = 拾音")
expect(Brand.names("拾音", "Shiyin") == ["拾音", "Shiyin"], "unbranded names")
// fork 的建置：Info.plist 的 MABrand
Brand.table = ["zh-Hant": ["拾音": "會議助手"], "zh-Hans": ["拾音": "会议助手"], "en": ["Shiyin": "Meeting Assistant", "拾音": "會議助手"]]
expect(Brand.name("拾音") == "會議助手", "name(拾音) = 會議助手（新建列表的名稱）")
expect(Brand.name("Shiyin") == "Meeting Assistant", "name(Shiyin) = Meeting Assistant")
// 5.0 的 EventKitReminders.list()：照上游的流程，用 calendars 的標題模擬
func pick(_ titles: [String]) -> String {
    if let hit = titles.first(where: Brand.isListTitle) { return "沿用「\(hit)」" }
    return "新建「\(Brand.name("拾音"))」"
}
expect(pick(["提醒事項", "拾音"]) == "沿用「拾音」", "舊名「拾音」列表存在時沿用 → \(pick(["提醒事項", "拾音"]))")
expect(pick(["Shiyin"]) == "沿用「Shiyin」", "英文介面的舊名「Shiyin」列表沿用")
expect(pick(["會議助手"]) == "沿用「會議助手」", "已有「會議助手」列表沿用")
expect(pick(["提醒事項", "工作"]) == "新建「會議助手」", "都沒有時新建「會議助手」")
expect(!Brand.isListTitle("會議"), "不相干的列表不算")
// ReleaseNotes 的接點：fork 的 Release 說明（會議助手開頭）和上游的（拾音開頭）都認得
expect(Brand.names("拾音").contains { "會議助手 4.7.6：…".hasPrefix($0) }, "更新說明「會議助手 X」選得到中文段落")
expect(Brand.names("Shiyin").contains { "meeting assistant 4.7.6: …".hasPrefix($0.lowercased()) }, "英文段落「Meeting Assistant X」選得到")
// 錄音島的簡稱（F7.7）：完整名稱換成 MA，跟中文相鄰時補空白；沒有 shortName 時不換
Brand.shortName = nil
expect(Brand.short("打開會議助手") == "打開會議助手", "沒有 shortName 時 short() 不換")
Brand.shortName = "MA"
expect(Brand.short("打開會議助手") == "打開 MA", "繁中：打開會議助手 → 打開 MA")
expect(Brand.short("打开会议助手") == "打开 MA", "簡中：打开会议助手 → 打开 MA")
expect(Brand.short("Open Meeting Assistant") == "Open MA", "英文：Open Meeting Assistant → Open MA")
expect(Brand.short("會議助手正在錄音") == "MA 正在錄音", "名稱在開頭、後面接中文時補空白")
expect(Brand.short("打開拾音") == "打開拾音", "上游的名稱（沒換過品牌）不動")
expect(Brand.short("停止並轉錄") == "停止並轉錄", "沒有品牌名的不動")
print(fails == 0 ? "全部通過" : "\(fails) 項失敗"); exit(fails == 0 ? 0 : 1)
