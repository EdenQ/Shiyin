import SwiftUI

// F4 紀錄條列頁（fork design §F4）：上游 NotesPage 的條列模式整頁換成 `ForkNotesList`（`// MA-FORK(F4)`），
// 段落用 fork 自己的 `ForkNotesSection`（條數、色條、複製鈕）；上游的 NotesSection、ActionItemsTable 不動（人物頁照用上游的）

/// 條列模式（fork design §F4.4）：摘要 → 決議 → 待辦 → 未決問題 → 自訂段落 → 議題（自訂段落在議題前面，同匯出）。
/// `header` 是上游 NotesPage 的提示條和編輯列（條列、心智圖共用），`templateName` 是上游算好的範本名稱
struct ForkNotesList<Header: View>: View {
    @Environment(AppModel.self) private var model
    let detail: MeetingDetail
    let notes: MeetingNotes
    @ViewBuilder let header: () -> Header
    let templateName: String

    var body: some View {
        let duration = max(model.player.duration, Double(detail.meeting.durationSeconds ?? 0))
        let segments = model.topicSegments(notes: notes, duration: duration)
        let branches = MindMap.topicBranches(notes)
        let collapsed = collapsedTopics(notes)
        return ScrollViewReader { proxy in
            ReadingColumn {
                header()
                if notes.topics.count > 5 {
                    TopicChips(topics: notes.topics.indices.map { t in
                        (index: t, title: notes.topics[t].title.isEmpty ? MindMap.topicLabel(.interface) : notes.topics[t].title,
                         branch: branches[t], segments: branches[t].map { b in segments.filter { $0.branch == b }.count } ?? 0)
                    }) { reveal($0, proxy: proxy) }
                }
                if !notes.summary.isEmpty {
                    ForkNotesSection(title: String(localized: "摘要"), count: notes.summary.count, accent: .slate, copy: .summary) {
                        ItemList(items: notes.summary, detail: detail, symbolColor: .slate) { .summary($0) }
                    }
                }
                if !notes.decisions.isEmpty {
                    ForkNotesSection(title: String(localized: "決議"), count: notes.decisions.count, accent: .celadon, copy: .decisions) {
                        ItemList(items: notes.decisions, detail: detail, symbol: "✓", symbolColor: .celadon) { .decisions($0) }
                    }
                }
                if !notes.actionItems.isEmpty {
                    ForkNotesSection(title: String(localized: "待辦"), count: notes.actionItems.count, accent: .actionBlue, copy: .actionItems) {
                        // 加到提醒事項（design §52.2、R76.1）：垃圾桶裡的會議不顯示
                        if detail.meeting.deletedAt == nil {
                            Button("加到提醒事項", systemImage: "checklist") { model.addActionItemsToReminders() }
                                .buttonStyle(.borderless)
                                .font(.callout)
                                .disabled(model.addingReminders)
                                .help("把這場會議的待辦加到「提醒事項」app 的「\(Reminders.listTitle)」列表，加過的不會重複加")
                        }
                    } content: {
                        ForkActionItemsTable(items: notes.actionItems, detail: detail) { .actionItems($0) }
                    }
                }
                if !notes.openQuestions.isEmpty {
                    ForkNotesSection(title: String(localized: "未決問題"), count: notes.openQuestions.count, accent: .signal, copy: .openQuestions) {
                        ItemList(items: notes.openQuestions, detail: detail, symbol: "?", symbolColor: .signal) { .openQuestions($0) }
                    }
                }
                ForEach(Array(notes.custom.enumerated()), id: \.offset) { c, section in
                    if !section.items.isEmpty {
                        ForkNotesSection(title: section.title, count: section.items.count, copy: .custom(c)) {
                            ItemList(items: section.items, detail: detail) { .custom(c, $0) }
                        }
                    }
                }
                if !notes.topics.isEmpty {
                    // 議題段落本身不加色條：每個議題已經有自己的色條（fork design §F4.4）
                    VStack(alignment: .leading, spacing: 10) {
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Text("議題").contentTitleFont(18)
                            Text(verbatim: String(notes.topics.count)).contentFont(.callout, monospacedDigit: true).foregroundStyle(.secondary)
                            Spacer(minLength: 0)
                            let allOpen = collapsed.isEmpty
                            Button(allOpen ? "全部收合" : "全部展開") {
                                model.notesCollapsedTopics = allOpen ? Set(notes.topics.indices) : []
                            }
                            .buttonStyle(.borderless)
                            .foregroundStyle(Color.celadon)
                            .font(.callout)   // 不跟著文字大小（同編輯列）
                        }
                        VStack(alignment: .leading, spacing: 8) {
                            ForEach(Array(notes.topics.enumerated()), id: \.offset) { t, topic in
                                let branch = branches[t]
                                TopicBlock(index: t, topic: topic, branch: branch,
                                           segments: branch.map { b in segments.filter { $0.branch == b } } ?? [],
                                           expanded: !collapsed.contains(t) || reviewOpen(in: t), detail: detail) {
                                    toggleTopic(t, notes: notes)
                                }
                                .id("topic-\(t)")
                            }
                        }
                    }
                }
                if let by = detail.meeting.notesBy {
                    Text("由 \(LLMProvider(rawValue: by)?.shortLabel ?? by) 整理．\(templateName)")
                        .contentFont(.caption)
                        .foregroundStyle(.tertiary)
                }
            }
            // 在紀錄分頁點播放條的議題帶：展開並捲到那個議題（F4.10）
            .onChange(of: model.topicScrollRequest) { _, request in
                guard let request, let t = branches.first(where: { $0.value == request.branch })?.key else { return }
                reveal(t, proxy: proxy)
            }
        }
    }

    /// 議題 > 5 個時預設全部收起（F4.7）；收合狀態只記這次選取期間（`AppModel.notesCollapsedTopics`）
    private func collapsedTopics(_ notes: MeetingNotes) -> Set<Int> {
        model.notesCollapsedTopics ?? (notes.topics.count > 5 ? Set(notes.topics.indices) : [])
    }

    private func toggleTopic(_ t: Int, notes: MeetingNotes) {
        var collapsed = collapsedTopics(notes)
        if collapsed.contains(t) { collapsed.remove(t) } else { collapsed.insert(t) }
        model.notesCollapsedTopics = collapsed
    }

    /// 就地回答展開在這個議題的重點下時，議題一定展開（不然卡片被藏起來）
    private func reviewOpen(in t: Int) -> Bool {
        if case .topicPoint(let topic, _) = model.reviewDraft?.expanded { return topic == t }
        return false
    }

    /// 展開並捲到那個議題（膠囊、議題帶）
    private func reveal(_ t: Int, proxy: ScrollViewProxy) {
        if let notes = detail.notes {
            var collapsed = collapsedTopics(notes)
            collapsed.remove(t)
            model.notesCollapsedTopics = collapsed
        }
        DispatchQueue.main.async {
            withAnimation(.easeInOut(duration: 0.2)) { proxy.scrollTo("topic-\(t)", anchor: .top) }
        }
    }

}

/// 紀錄的一段（fork F4.1、F4.3，fork design §F4.4）：標題、條數、滑過才出現的「複製這一段」；`accent` 有給時左邊一條色條。
/// 上游 5.0 的標題右邊按鈕（`accessory`，「待辦」的「加到提醒事項」，design §52.2）放在複製鈕後面
struct ForkNotesSection<Content: View, Accessory: View>: View {
    let title: String
    var count: Int? = nil
    var accent: Color? = nil
    var copy: NotesSectionScope? = nil
    /// 標題右邊的按鈕（「待辦」的「加到提醒事項」，design §52.2）
    var accessory: Accessory
    var content: Content
    @State private var hovering = false

    init(title: String, count: Int? = nil, accent: Color? = nil, copy: NotesSectionScope? = nil,
         @ViewBuilder content: () -> Content) where Accessory == EmptyView {
        self.title = title
        self.count = count
        self.accent = accent
        self.copy = copy
        self.accessory = EmptyView()
        self.content = content()
    }

    init(title: String, count: Int? = nil, accent: Color? = nil, copy: NotesSectionScope? = nil,
         @ViewBuilder accessory: () -> Accessory, @ViewBuilder content: () -> Content) {
        self.title = title
        self.count = count
        self.accent = accent
        self.copy = copy
        self.accessory = accessory()
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(title).contentTitleFont(18)
                if let count { Text(verbatim: String(count)).contentFont(.callout, monospacedDigit: true).foregroundStyle(.secondary) }
                Spacer(minLength: 0)
                if let copy { SectionCopyButton(scope: copy, help: String(localized: "複製這一段（純文字）")).opacity(hovering ? 1 : 0) }
                accessory
            }
            content
        }
        .padding(.leading, accent == nil ? 0 : 14)
        .overlay(alignment: .leading) {
            if let accent { Rectangle().fill(accent).frame(width: 3) }
        }
        .onHover { hovering = $0 }
    }
}

/// 「複製這一段」「複製這個議題」（fork F4.1）：從會議紀錄產生純文字，跟著會議語言；按鈕不跟著文字大小（R59.2）
struct SectionCopyButton: View {
    @Environment(AppModel.self) private var model
    let scope: NotesSectionScope
    let help: String

    var body: some View {
        Button { model.copyNotesSection(scope) } label: {
            Image(systemName: "doc.on.doc")
        }
        .buttonStyle(.borderless)
        .font(.callout)
        .foregroundStyle(Color.celadon)
        .help(help)
        .accessibilityLabel(help)
    }
}

/// 一條紀錄：符號、內容、待確認的標記、時間點（R6.4：點時間點就跳到錄音那裡）。
/// 時間點平常淡色、在行尾對齊成一欄，滑過這一條才變青瓷綠（fork F4.2）；「？」放在時間點前面，照舊琥珀色
struct NoteRow: View {
    let item: MeetingNotes.Item
    let symbol: String
    var symbolColor: Color? = nil
    var ref: NoteItemRef? = nil
    var detail: MeetingDetail? = nil
    @State private var hovering = false

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(verbatim: symbol)
                .foregroundStyle(symbolColor.map { AnyShapeStyle($0) } ?? AnyShapeStyle(.secondary))
                .frame(minWidth: 10, alignment: .leading)
            Text(item.text).meetingText()
                .selectableUnlessEditable(ref != nil && detail != nil)   // 上游 R100：可以就地編輯的條目不設成可選取（點了編輯）
                .frame(maxWidth: .infinity, alignment: .leading)
            if let ref, let detail { ReviewMarker(ref: ref, count: detail.reviewCount(ref)) }
            if !item.time.isEmpty { ForkSubduedTimeButton(time: item.time, highlighted: hovering) }
        }
        .contentShape(Rectangle())
        .onHover { hovering = $0 }
    }
}

/// 一個議題（fork F4.5、F4.7、F4.11，fork design §F4.4）：左邊心智圖那一支的色條；標題列可以收合，
/// 寫重點幾條、待確認幾題、議題重回時有幾段；正在播放時底色淡淡的那一支顏色
struct TopicBlock: View {
    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var colorScheme
    let index: Int
    let topic: MeetingNotes.Topic
    let branch: Int?
    let segments: [MindMap.TopicRange]
    let expanded: Bool
    let detail: MeetingDetail
    let onToggle: () -> Void
    @State private var hovering = false

    var body: some View {
        let color = branch.map { Color(hex: MindMap.color($0, dark: colorScheme == .dark)) } ?? Color.secondary
        let isCurrent = branch != nil && model.currentTopicBranch == branch
        let reviewRefs = topic.points.indices.map { NoteItemRef.topicPoint(index, $0) }
        let reviewTotal = reviewRefs.reduce(0) { $0 + detail.reviewCount($1) }
        VStack(alignment: .leading, spacing: 8) {
            // 展開／收合只由箭頭和「標題＋條數」兩個按鈕觸發；時間、「？」、複製是旁邊獨立的按鈕，父層沒有點擊手勢（fork design §F4.4）
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Button(action: onToggle) {
                    Image(systemName: expanded ? "chevron.down" : "chevron.right")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .frame(width: 12)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(expanded ? String(localized: "收合這個議題") : String(localized: "展開這個議題"))
                TimeButton(time: topic.start)
                Button(action: onToggle) {
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        // 標題太長時換行，不截斷（在 ScrollView 裡，可以用 fixedSize）
                        Text(topic.title).contentTitleFont(16)
                            .multilineTextAlignment(.leading)
                            .fixedSize(horizontal: false, vertical: true)
                        Text("\(topic.points.count) 條").contentFont(.callout).foregroundStyle(.secondary)
                            .fixedSize()
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityHint(expanded ? String(localized: "收合這個議題") : String(localized: "展開這個議題"))
                if reviewTotal > 0, let first = reviewRefs.first(where: { detail.reviewCount($0) > 0 }) {
                    ReviewMarker(ref: first, count: reviewTotal)
                }
                Spacer(minLength: 0)
                SectionCopyButton(scope: .topic(index), help: String(localized: "複製這個議題（純文字）"))
                    .opacity(hovering ? 1 : 0)
            }
            // 議題重回的段、目前播放位置：另一行，段很多或字很大時自動換行（FlowLayout），不擠壓標題
            if segments.count > 1 || isCurrent {
                FlowLayout(spacing: 4, lineSpacing: 2) {
                    if segments.count > 1 {
                        Text("\(segments.count) 段：").contentFont(.callout).foregroundStyle(.secondary)
                        ForEach(Array(segments.enumerated()), id: \.offset) { k, segment in
                            HStack(spacing: 0) {
                                TimeButton(time: TimeFormat.string(segment.start), seek: segment.start)
                                if k < segments.count - 1 {
                                    Text(verbatim: MeetingLanguage.ui(zh: "、", en: ",")).contentFont(.callout).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                    if isCurrent {
                        Text("目前播放位置").contentFont(.caption, weight: .semibold).foregroundStyle(Color.celadon)
                            .padding(.leading, segments.count > 1 ? 8 : 0)
                    }
                }
                .padding(.leading, 22)
            }
            if expanded {
                ItemList(items: topic.points, detail: detail) { .topicPoint(index, $0) }
                    .padding(.leading, 22)
            }
        }
        .padding(.vertical, 4)
        .padding(.leading, 12)
        .background(isCurrent ? color.opacity(0.08) : .clear)
        .overlay(alignment: .leading) { Rectangle().fill(color).frame(width: 3) }
        .onHover { hovering = $0 }
    }
}

/// 議題 > 5 個時紀錄上方一列議題的膠囊（fork F4.8）：點了展開並捲到那個議題；不跟著文字大小（同編輯列）
struct TopicChips: View {
    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.snapshotMode) private var snapshotMode
    let topics: [(index: Int, title: String, branch: Int?, segments: Int)]
    let onSelect: (Int) -> Void

    var body: some View {
        if snapshotMode {
            HStack(spacing: 6) { chips }.environment(\.textScale, 1)
        } else {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) { chips }.padding(.vertical, 2)
            }
        }
    }

    private var chips: some View {
        ForEach(topics, id: \.index) { topic in
            let color = topic.branch.map { Color(hex: MindMap.color($0, dark: colorScheme == .dark)) } ?? Color.secondary
            let isCurrent = topic.branch != nil && model.currentTopicBranch == topic.branch
            Button { onSelect(topic.index) } label: {
                HStack(spacing: 6) {
                    RoundedRectangle(cornerRadius: 2).fill(color).frame(width: 8, height: 8)
                    Text(topic.title).lineLimit(1)
                    if topic.segments > 1 {
                        Text(verbatim: "×\(topic.segments)").font(.caption2.weight(.semibold)).foregroundStyle(.secondary)
                    }
                }
                .font(.callout)
                .padding(.horizontal, 9)
                .padding(.vertical, 3)
                .background(Capsule().fill(Color(nsColor: .controlBackgroundColor)))
                .overlay(Capsule().strokeBorder(isCurrent ? Color.celadon : Color.secondary.opacity(0.3), lineWidth: isCurrent ? 1.5 : 1))
            }
            .buttonStyle(.plain)
            .help(String(localized: "捲到「\(topic.title)」"))
        }
    }
}

/// 待辦表（fork F4.4）：負責人、期限在左邊方便掃讀，事項在右邊、時間點在最後；三個文字欄都能選取
struct ForkActionItemsTable: View {
    @Environment(AppModel.self) private var model
    @Environment(\.textScale) private var scale
    let items: [MeetingNotes.ActionItem]
    var detail: MeetingDetail? = nil
    var ref: (Int) -> NoteItemRef? = { _ in nil }
    @State private var hovered: Int?

    var body: some View {
        Grid(alignment: .leadingFirstTextBaseline, horizontalSpacing: 14, verticalSpacing: 9) {
            GridRow {
                Text("負責人")
                Text("期限")
                Text("事項")
                Color.clear.frame(width: 1, height: 1)
            }
            .contentFont(.caption)
            .foregroundStyle(.secondary)
            Divider().gridCellUnsizedAxes(.horizontal)
            ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                let ref = ref(index)
                GridRow {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        // 負責人是這場的說話者時放他的頭像（design §58.2、R83.2）
                        if let idx = detail?.speakerIdx(named: item.owner) {
                            PersonAvatar(name: item.owner, color: Color.speaker(idx), isMe: idx == detail?.selfIdx)
                                .alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] + 4 * scale }
                        }
                        Text(item.owner.isEmpty ? String(localized: "未指定") : item.owner).meetingText()
                            .fontWeight(item.owner.isEmpty ? .regular : .semibold)
                            .foregroundStyle(item.owner.isEmpty ? Color.signal : Color.primary)
                            .textSelection(.enabled)
                    }
                    Text(item.due.isEmpty ? "—" : item.due)
                        .monospacedDigit()
                        .foregroundStyle(item.due.isEmpty ? .tertiary : .primary)
                        .textSelection(.enabled)
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        if let ref, detail != nil, model.editingNoteItem == ref {
                            NoteItemEditor(ref: ref)   // 就地改這一條（R100）
                        } else {
                            Text(item.task).meetingText()
                                .selectableUnlessEditable(ref != nil && detail != nil)
                                .fixedSize(horizontal: false, vertical: true)
                            // 已經加到提醒事項的（design §52.2、R76.4）：完成了打勾
                            if detail != nil, let done = model.reminderStatus[Reminders.key(item.task)] {
                                Image(systemName: done ? "checkmark.circle.fill" : "checklist")
                                    .foregroundStyle(done ? Color.celadon : Color.secondary)
                                    .contentFont(.caption)
                                    .help(done ? "已在提醒事項裡完成" : "已加到提醒事項")
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .noteItemActions(ref: detail == nil || model.editingNoteItem == ref ? nil : ref, text: item.task, time: item.time)
                    .gridColumnAlignment(.leading)
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        if let ref, let detail { ReviewMarker(ref: ref, count: detail.reviewCount(ref)) }
                        if !item.time.isEmpty { ForkSubduedTimeButton(time: item.time, highlighted: hovered == index) }
                    }
                }
                .onHover { inside in
                    if inside { hovered = index } else if hovered == index { hovered = nil }
                }
                if let ref, let detail, model.reviewDraft?.expanded == ref {
                    GridRow {
                        InlineReviewCard(detail: detail, indexes: detail.reviewLinks[ref] ?? [])
                            .gridCellColumns(4)
                    }
                }
            }
        }
    }
}


/// 由左到右排、放不下就換行（議題列的「N 段：時間…」，fork F4.11）：段很多、字很大或視窗很窄時往下換行，不擠壓、不超出
struct FlowLayout: Layout {
    var spacing: CGFloat = 4
    var lineSpacing: CGFloat = 2

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = arrange(width: proposal.width ?? .infinity, subviews: subviews)
        let width = rows.map(\.width).max() ?? 0
        let height = rows.reduce(0) { $0 + $1.height } + lineSpacing * CGFloat(max(rows.count - 1, 0))
        return CGSize(width: proposal.width.map { min($0, width) } ?? width, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in arrange(width: bounds.width, subviews: subviews) {
            var x = bounds.minX
            for index in row.items {
                let size = subviews[index].sizeThatFits(.unspecified)
                subviews[index].place(at: CGPoint(x: x, y: y + (row.height - size.height) / 2), proposal: ProposedViewSize(size))
                x += size.width + spacing
            }
            y += row.height + lineSpacing
        }
    }

    private func arrange(width: CGFloat, subviews: Subviews) -> [(items: [Int], width: CGFloat, height: CGFloat)] {
        var rows: [(items: [Int], width: CGFloat, height: CGFloat)] = []
        for index in subviews.indices {
            let size = subviews[index].sizeThatFits(.unspecified)
            if let last = rows.last, last.width + spacing + size.width <= width {
                rows[rows.count - 1].items.append(index)
                rows[rows.count - 1].width += spacing + size.width
                rows[rows.count - 1].height = max(last.height, size.height)
            } else {
                rows.append(([index], size.width, size.height))
            }
        }
        return rows
    }
}
