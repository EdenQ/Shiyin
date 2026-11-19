#if DEBUG
import Foundation

/// F4 的 DEBUG 指令（fork design §F4.5）：4.x 就有的名字照舊（topicsegments、copysection、topicscroll、topiccollapse）
@MainActor
extension ForkDebug {
    static func notes(_ args: [String], model: AppModel) -> Bool {
        let id = args.count > 1 ? Int64(args[1]) : nil
        switch args[0] {
        case "topicsegments":   // topicsegments <輸入.json> <輸出.json>：每個 case 的 topicSegments 和 topicRanges
            var out: [String: Any] = ["ok": false]
            if let input = (try? JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: args[1])))) as? [String: Any] {
                let duration = (input["duration"] as? Double) ?? 0
                func json(_ r: [MindMap.TopicRange]) -> [[String: Any]] { r.map { ["branch": $0.branch, "start": $0.start, "end": $0.end] } }
                out["cases"] = ((input["cases"] as? [[String: Any]]) ?? []).map { c -> [String: Any] in
                    let notes = (c["notes"]).flatMap { try? JSONSerialization.data(withJSONObject: $0) }
                        .flatMap { try? JSONDecoder().decode(MeetingNotes.self, from: $0) } ?? MeetingNotes(title: "")
                    let d = (c["duration"] as? Double) ?? duration
                    return ["name": c["name"] ?? "", "segments": json(MindMap.topicSegments(notes: notes, duration: d, untitled: "T")),
                            "ranges": json(MindMap.topicRanges(notes: notes, duration: d, untitled: "T")),
                            "branches": MindMap.topicBranches(notes).map { ["topic": $0.key, "branch": $0.value] }]
                }
                out["ok"] = true
            }
            write(out, to: args[2])
        case "copysection":   // copysection <會議 id> <summary|decisions|actionItems|openQuestions|custom:N|topic:N> <輸出.txt>：不碰剪貼簿
            let scope: NotesSectionScope? = {
                let parts = args[2].split(separator: ":").map(String.init)
                switch parts[0] {
                case "summary": return .summary
                case "decisions": return .decisions
                case "actionItems": return .actionItems
                case "openQuestions": return .openQuestions
                case "custom": return parts.count > 1 ? Int(parts[1]).map { .custom($0) } : nil
                case "topic": return parts.count > 1 ? Int(parts[1]).map { .topic($0) } : nil
                default: return nil
                }
            }()
            if let id, let scope, let meeting = try? model.db.meeting(id), let notes = meeting.decodedNotes {
                try? NotesExporter.plainSection(scope, notes: notes, language: meeting.meetingLanguage)
                    .write(to: URL(fileURLWithPath: args[3]), atomically: true, encoding: .utf8)
            }
        case "topicscroll":   // topicscroll <branch>：等於在紀錄分頁點議題帶的那一支（F4.10）
            if model.tab == .summary, let branch = Int(args[1]) { model.topicScrollRequest = TopicScrollRequest(branch: branch) }
        case "topiccollapse":   // topiccollapse all|none|default：議題全部收合、全部展開、回到預設（F4.7）
            model.notesCollapsedTopics = args[1] == "default" ? nil : (args[1] == "all" ? Set(model.detail?.notes?.topics.indices ?? 0..<0) : [])
        default: return false
        }
        return true
    }

    /// state：議題帶依重點時間切的段、目前議題、收起來的議題
    static func notesState(_ out: inout [String: Any], model: AppModel) {
        out["topicSegments"] = model.detail.flatMap { d in
            d.notes.map { MindMap.topicSegments(notes: $0, duration: max(model.player.duration, Double(d.meeting.durationSeconds ?? 0)),
                                                untitled: MindMap.topicLabel(.interface)) }
        }.map { $0.map { ["branch": $0.branch, "title": $0.title, "start": $0.start, "end": $0.end] } } ?? []
        out["currentTopicBranch"] = model.currentTopicBranch ?? -1
        out["notesTopicsCollapsed"] = model.notesCollapsedTopics.map { Array($0).sorted() as Any } ?? "default"
    }
}
#endif
