import AppKit
import SwiftUI

/// 「複製這一段」的範圍（F4.1）：`topic`、`custom` 是 `notes` 裡的位置
enum NotesSectionScope: Hashable {
    case summary, decisions, actionItems, openQuestions
    case custom(Int)
    case topic(Int)
}

/// 在紀錄分頁點播放條的議題帶時，請紀錄頁捲到那個議題（F4.10）
struct TopicScrollRequest: Equatable {
    let branch: Int
    let id = UUID()
}

extension NotesExporter {
    /// 只複製一段（F4.1，fork design §F4.1）：純文字，固定文字跟著會議語言（同匯出）；段落是空的時候回傳空字串
    static func plainSection(_ scope: NotesSectionScope, notes: MeetingNotes, language: MeetingLanguage) -> String {
        let x = ExportText(language)
        func t(_ time: String) -> String { time.isEmpty ? "" : x.paren(time) }
        func list(_ title: String, _ items: [MeetingNotes.Item]) -> String {
            items.isEmpty ? "" : ([title] + items.map { "- \($0.text)\(t($0.time))" }).joined(separator: "\n") + "\n"
        }
        switch scope {
        case .summary: return list(x.section("summary"), notes.summary)
        case .decisions: return list(x.section("decisions"), notes.decisions)
        case .openQuestions: return list(x.section("openQuestions"), notes.openQuestions)
        case .custom(let c):
            guard notes.custom.indices.contains(c) else { return "" }
            return list(notes.custom[c].title, notes.custom[c].items)
        case .topic(let i):
            guard notes.topics.indices.contains(i) else { return "" }
            let topic = notes.topics[i]
            let head = topic.start.isEmpty ? topic.title : "[\(topic.start)] \(topic.title)"
            return ([head] + topic.points.map { "- \($0.text)\(t($0.time))" }).joined(separator: "\n") + "\n"
        case .actionItems:
            guard !notes.actionItems.isEmpty else { return "" }
            let lines = notes.actionItems.map { item -> String in
                let owner = item.owner.isEmpty ? x.unassigned : item.owner
                let due = item.due.isEmpty ? "" : x.paren("\(x.due) \(item.due)")
                return "- \(owner)\(x.colon)\(item.task)\(due)\(t(item.time))"
            }
            return ([x.section("actionItems")] + lines).joined(separator: "\n") + "\n"
        }
    }
}

extension MindMap {
    /// 議題帶依每條重點的時間切段（F4.11，fork design §F4.2）：同一個議題可以有好幾段（議題重回討論）。
    /// 重點時間都在自己議題區間內時，結果跟 `topicRanges` 一樣；`topicRanges` 和它的標準答案不動（DF4）
    static func topicSegments(notes: MeetingNotes, duration: Double, untitled: String, minSeconds: Double = 60) -> [TopicRange] {
        guard duration > 0 else { return [] }
        let shown = shownTopics(notes)
        // 1～2. 每個議題的 start 和各重點的時間，依時間排序（同一秒照 branch）
        var marks: [(time: Double, branch: Int)] = []
        var starts: [Int: Double] = [:]
        for (branch, topic) in shown.enumerated() {
            if let t = TimeFormat.seconds(topic.start), t < duration {
                marks.append((t, branch))
                starts[branch] = t
            }
            for point in topic.points {
                if let t = TimeFormat.seconds(point.time), t < duration { marks.append((t, branch)) }
            }
        }
        marks.sort { ($0.time, $0.branch) < ($1.time, $1.branch) }
        var segments: [TopicRange] = []
        for mark in marks where segments.last?.branch != mark.branch {
            let name = clean(shown[mark.branch].title)
            segments.append(TopicRange(branch: mark.branch, title: name.isEmpty ? untitled : name, start: mark.time, end: 0))
        }
        // 3. 每段到下一段的開始，最後一段到會議長度
        for k in segments.indices { segments[k].end = k + 1 < segments.count ? segments[k + 1].start : duration }
        func mergeAdjacent() {
            var merged: [TopicRange] = []
            for s in segments {
                if let last = merged.last, last.branch == s.branch { merged[merged.count - 1].end = s.end } else { merged.append(s) }
            }
            segments = merged
        }
        // 4. 零長度的段（同一秒好幾個議題）不算一段：先拿掉，再合併因此相鄰的同議題段
        segments.removeAll { $0.end <= $0.start }
        mergeAdjacent()
        // 開始段：區間確定之後，實際包含那個議題自己 start 的段（半開區間 start ≤ t < end，同播放條）。
        // 不看「收過 start 這個時間點」：start 跟別的議題同一秒時，那一秒歸後面的議題，前面那段並不包含它
        func isStart(_ s: TopicRange) -> Bool { starts[s.branch].map { s.start <= $0 && $0 < s.end } ?? false }
        // 5. 太短、不是開始段、而且那個議題還有別段的：併進前一段（第一段併進後一段）
        while let k = segments.indices.first(where: { k in
            let s = segments[k]
            return !isStart(s) && s.end - s.start < minSeconds && segments.contains { $0.branch == s.branch && $0.start != s.start }
        }) {
            if k > 0 { segments[k - 1].end = segments[k].end } else { segments[1].start = segments[0].start }
            segments.remove(at: k)
            mergeAdjacent()
        }
        return segments
    }

    /// `notes.topics` 的位置 → 心智圖的第幾支（議題帶、條列頁的議題色條用；沒畫出來的議題沒有）
    static func topicBranches(_ notes: MeetingNotes) -> [Int: Int] {
        var map: [Int: Int] = [:]
        var branch = 0
        for (i, topic) in notes.topics.enumerated()
        where !clean(topic.title).isEmpty || topic.points.contains(where: { !clean($0.text).isEmpty }) {
            map[i] = branch
            branch += 1
        }
        return map
    }
}

extension Color {
    /// 紀錄條列頁的段落色條（F4.3，fork design §F4.4）：摘要用低飽和的灰藍，跟待辦的藍、心智圖的 6 色分得開
    static let slate = Color(nsColor: .dynamic(light: 0x6B7A8F, dark: 0x8E9CB0))
    /// 待辦的段落色條：心智圖調色盤的藍（MindMap.palette[1]）
    static let actionBlue = Color(nsColor: .dynamic(light: 0x3E6FA8, dark: 0x6E9BD6))
}

/// 紀錄條列頁的時間點（F4.2）：同上游的 TimeButton，平常淡色，滑過那一條（highlighted）才變青瓷綠
struct ForkSubduedTimeButton: View {
    @Environment(AppModel.self) private var model
    let time: String
    var highlighted = false

    var body: some View {
        // 沒有錄音的會議（例如匯入逐字稿）點了也沒辦法播，顯示成一般文字
        if let seconds = TimeFormat.seconds(time), model.player.isLoaded {
            Button(time) { model.player.seek(to: seconds) }
                .buttonStyle(.plain)
                .contentFont(.callout, monospacedDigit: true)   // 跟著文字大小（上游 design §38.5）
                .foregroundStyle(highlighted ? AnyShapeStyle(Color.celadon) : AnyShapeStyle(.tertiary))
                .help("從 \(time) 開始播放")
        } else if !time.isEmpty {
            Text(time).contentFont(.callout, monospacedDigit: true).foregroundStyle(.secondary)
        }
    }
}

// MARK: AppModel 的議題狀態（存在 `AppModel.fork`）

extension AppModel {
    var currentTopicBranch: Int? {
        get { fork.currentTopicBranch }
        set { fork.currentTopicBranch = newValue }
    }

    var topicScrollRequest: TopicScrollRequest? {
        get { fork.topicScrollRequest }
        set { fork.topicScrollRequest = newValue }
    }

    var notesCollapsedTopics: Set<Int>? {
        get { fork.notesCollapsedTopics }
        set { fork.notesCollapsedTopics = newValue }
    }

    func topicSegments(notes: MeetingNotes, duration: Double) -> [MindMap.TopicRange] {
        if let cache = fork.topicSegmentsCache, cache.duration == duration, cache.notes == notes { return cache.segments }
        let segments = MindMap.topicSegments(notes: notes, duration: duration, untitled: MindMap.topicLabel(.interface))
        fork.topicSegmentsCache = (notes, duration, segments)
        return segments
    }

    /// 只複製一段（F4.1，fork design §F4.1）：從會議紀錄產生純文字，跟著會議語言
    func copyNotesSection(_ scope: NotesSectionScope) {
        guard let b = exportBundle(), let notes = b.notes else { return }
        let text = NotesExporter.plainSection(scope, notes: notes, language: b.meeting.meetingLanguage)
        guard !text.isEmpty else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        let title = text.split(separator: "\n", maxSplits: 1).first.map(String.init) ?? ""
        noticeMessage = String(localized: "已複製「\(title)」")
    }
}

// MARK: 播放條的議題帶（上游 PlayerBar 的接點）

enum ForkTopics {
    /// 點了議題帶的一支：在紀錄分頁的條列模式，紀錄頁捲到那個議題（F4.10）；其他分頁、心智圖只播放
    @MainActor
    static func tapped(_ model: AppModel, branch: Int) {
        if model.tab == .summary, (UserDefaults.standard.string(forKey: AppSettings.notesViewKey) ?? "list") == "list" {
            model.topicScrollRequest = TopicScrollRequest(branch: branch)
        }
    }
}

extension View {
    /// 目前議題（F4.9，fork design §F4.3）：只在換了議題時寫進 model，紀錄頁不用隨播放時間重算
    func forkTrackTopic(_ topics: [MindMap.TopicRange], player: Player, model: AppModel) -> some View {
        let current = player.isLoaded ? topics.first { player.currentTime >= $0.start && player.currentTime < $0.end }?.branch : nil
        return onChange(of: current, initial: true) { _, branch in
            if model.currentTopicBranch != branch { model.currentTopicBranch = branch }
        }
    }
}
