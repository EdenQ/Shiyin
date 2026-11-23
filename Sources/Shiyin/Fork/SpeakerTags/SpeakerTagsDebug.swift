#if DEBUG
import AppKit

/// F2 的 DEBUG 指令（fork design §F2.5）：4.x 就有的名字照舊（tagspeaker、tagui、addparticipant、applytags、speakertags），不改成 ma 開頭
@MainActor
extension ForkDebug {
    static func speakerTags(_ args: [String], model: AppModel) -> Bool {
        let id = args.count > 1 ? Int64(args[1]) : nil
        switch args[0] {
        case "tagspeaker":   // tagspeaker now <名字> | line <第幾行> <名字|-> | add <會議 id> <開始> <結束> <名字> | delete <標記 id> | only <會議 id> <標記 id>
            let count = ["now": 3, "line": 4, "add": 6, "delete": 3, "only": 4][args.count > 1 ? args[1] : ""] ?? Int.max
            guard args.count >= count else { break }
            switch args[1] {
            case "now": model.tagSpeakerNow(args[2])
            case "line":
                let lines = model.recorder.liveLines
                guard let index = Int(args[2]), lines.indices.contains(index) else { break }
                if args[3] == "-" { model.clearLiveLineTag(lines[index]) } else { model.tagLiveLine(lines[index], as: args[3]) }
            case "add":
                model.perform(.detail([.speakerTags])) {
                    try model.db.addSpeakerTag(Int64(args[2]) ?? 0, start: Double(args[3]) ?? 0, end: Double(args[4]) ?? 0, name: args[5])
                }
            case "only":   // 沒套用的標記按「只改這句」（F2.12）；only <會議 id> <標記 id> [<錯誤輸出.json>]
                model.selection = Int64(args[2])
                // 故障注入用（fork design §F2.5）：DEBUG＋quiet、給了輸出檔時，這次新出現的錯誤寫進檔、errorMessage 還原，
                // 不讓上游 MainWindow 的「出了一點問題」對話框在使用者畫面上跳出來。受測的函式、交易照常走
                let capture = args.count > 4 && ForkDebugPrompts.quiet ? args[4] : nil
                let previous = model.errorMessage
                if let tag = model.detail?.speakerTags.first(where: { $0.id == Int64(args[3]) }) { model.reassignTaggedSegments(tag) }
                if let capture { captureError(since: previous, model: model, to: capture) }
            default: model.deleteSpeakerTag(Int64(args[2]) ?? 0)
            }
        case "tagui":   // tagui add | tagui name <第幾行>：等於按 ＋、一行選單裡的「其他名字…」，打開輸入名字的彈出視窗
            if args.count > 2, args[1] == "name", let index = Int(args[2]), model.recorder.liveLines.indices.contains(index) {
                model.debugTagUI = "name:\(model.recorder.liveLines[index].id)"
            } else if args.count > 1, args[1] == "add" {
                model.debugTagUI = "add"
            }
        case "addparticipant": model.selection = id; model.addParticipant(args[2])   // addparticipant <會議 id> <名字>：等於在 ＋ 按「加入」
        case "applytags": model.selection = id; if let id { model.debugApplyTags(id) }   // applytags <會議 id>：重新套用標記
        case "speakertags": write(speakerTagsReport(id ?? 0, db: model.db), to: args[2])   // speakertags <會議 id> <輸出.json>
        default: return false
        }
        return true
    }

    /// 同步呼叫返回後馬上做（同一個 main actor 的回合，SwiftUI 還沒重畫）：新錯誤寫進檔、errorMessage 還原成呼叫前的值。
    /// 約 1 秒後補上那時的 errorMessage、有沒有視窗掛著 sheet 或對話框，給 f2-atomic-check 確認畫面上沒有跳出來
    private static func captureError(since previous: String?, model: AppModel, to path: String) {
        let current = model.errorMessage
        let new = current != previous ? current : nil
        if current != previous { model.errorMessage = previous }
        // 閉包裡不改外面的變數（@Sendable 閉包改外面的 var，各版編譯器的判斷不同；fork design §F0.6 的 Swift 版本差異）
        let error = new
        let restored = model.errorMessage == previous
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
            MainActor.assumeIsolated {
                let visible = NSApp.windows.filter(\.isVisible)
                let out: [String: Any] = [
                    "error": error ?? NSNull(), "restored": restored,
                    "errorMessageAfter": model.errorMessage ?? NSNull(),
                    "sheetVisible": visible.contains { $0.attachedSheet != nil || $0.isSheet || $0.className.contains("Alert") },
                    "mainWindowVisible": visible.contains { $0.identifier?.rawValue == "main" },
                ]
                write(out, to: path)
            }
        }
    }

    /// state：即時逐字稿每一行的名字、「正在說話」的名單（錄音中的會議）、沒套用的標記
    static func speakerTagsState(_ out: inout [String: Any], model: AppModel) {
        guard let detail = model.detail else { return }
        if detail.meeting.id == model.recorder.meetingId, var recorder = out["recorder"] as? [String: Any] {
            recorder["liveTags"] = model.recorder.liveLines.map { detail.liveTag(start: $0.start, end: $0.end)?.name ?? "" }
            recorder["tagRoster"] = detail.tagRoster
            out["recorder"] = recorder
        }
        out["unappliedTags"] = detail.unappliedTags.map(\.name)
    }

    /// speakertags：每個標記對上的說話者、重疊比例、逐字稿上的位置、是不是沒套用；說話者的名字和來源
    private static func speakerTagsReport(_ id: Int64, db: AppDatabase) -> [String: Any] {
        let segments = (try? db.segments(id)) ?? []
        let speakers = (try? db.speakers(id)) ?? []
        let names = Dictionary(uniqueKeysWithValues: speakers.map { ($0.idx, $0.name) })
        let tags = ((try? db.speakerTags(id)) ?? []).map { tag -> [String: Any] in
            let match = SpeakerTagging.match(tag.tag, in: segments)
            return ["id": tag.id ?? 0, "start": tag.start, "end": tag.end, "name": tag.name, "kind": tag.kind,
                    "speaker": match.speaker ?? -1, "share": match.share, "segment": match.segmentId ?? -1,
                    "segmentSpeaker": match.segmentSpeaker ?? -1,
                    "unapplied": match.segmentSpeaker.map { !SpeakerTagging.sameName(names[$0] ?? "", tag.name) } ?? false]
        }
        return ["tags": tags,
                "speakers": speakers.map { ["idx": $0.idx, "name": $0.name, "source": $0.nameSource, "person": $0.personId ?? -1,
                                            "seconds": $0.speechSeconds] },
                "participants": (try? db.meeting(id))?.participants ?? "",
                "people": ((try? db.peopleSummaries()) ?? []).map { ["name": $0.name, "voiceprints": $0.voiceprintCount] }]
    }
}
#endif
