// check.sh 用（fork design §F0.4 #12、安全規則）：列出 shiyin:// 和 .shiyin（com.weiwei.shiyin.meeting）的預設處理程式和所有候選 app。
// 編譯：xcrun swiftc scripts/fork/check-handlers.swift -o <輸出>；執行：<輸出>（只讀 LaunchServices，不改任何設定）
// 輸出每行「種類<TAB>路徑」：scheme-default、scheme-candidate、type-default、type-candidate；沒有時路徑寫 -
import AppKit
import UniformTypeIdentifiers

let ws = NSWorkspace.shared
func emit(_ kind: String, _ url: URL?) { print("\(kind)\t\(url?.path ?? "-")") }

let link = URL(string: "shiyin://meeting/1")!
emit("scheme-default", ws.urlForApplication(toOpen: link))
for app in ws.urlsForApplications(toOpen: link).sorted(by: { $0.path < $1.path }) { emit("scheme-candidate", app) }

if let type = UTType("com.weiwei.shiyin.meeting") {
    emit("type-default", ws.urlForApplication(toOpen: type))
    for app in ws.urlsForApplications(toOpen: type).sorted(by: { $0.path < $1.path }) { emit("type-candidate", app) }
} else {
    print("type-default\t-（系統不認得 com.weiwei.shiyin.meeting）")
}
