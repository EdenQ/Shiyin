import SwiftUI

/// 閱讀用的欄位：靠左、寬度上限約 680 pt
struct ReadingColumn<Content: View>: View {
    @Environment(\.snapshotMode) private var snapshotMode
    @Environment(\.textScale) private var scale
    @ViewBuilder var content: Content

    var body: some View {
        if snapshotMode {
            column
        } else {
            ScrollView { column }
        }
    }

    private var column: some View {
        VStack(alignment: .leading, spacing: 26) {
            content
        }
        .contentFont()   // 文字大小（design §38.5）：欄寬跟著放大，一行的字數不變
        .frame(maxWidth: 680 * scale, alignment: .leading)
        .padding(.horizontal, 32)
        .padding(.vertical, 24)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// 紀錄的一段（fork F4.1、F4.3，design §F4.4）：標題、條數、滑過才出現的「複製這一段」；`accent` 有給時左邊一條色條
struct NotesSection<Content: View>: View {
    let title: String
    var count: Int? = nil
    var accent: Color? = nil
    var copy: NotesSectionScope? = nil
    @ViewBuilder var content: Content
    @State private var hovering = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(title).contentTitleFont(18)
                if let count { Text(verbatim: String(count)).contentFont(.callout, monospacedDigit: true).foregroundStyle(.secondary) }
                Spacer(minLength: 0)
                if let copy { SectionCopyButton(scope: copy, help: String(localized: "複製這一段（純文字）")).opacity(hovering ? 1 : 0) }
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
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
            if let ref, let detail { ReviewMarker(ref: ref, count: detail.reviewCount(ref)) }
            if !item.time.isEmpty { TimeButton(time: item.time, subdued: true, highlighted: hovering) }
        }
        .contentShape(Rectangle())
        .onHover { hovering = $0 }
    }
}

/// 一段紀錄的條目。`ref` 給每一條在會議紀錄裡的位置（R41.1）：有對到待確認的題目時顯示標記，點了在下面展開題目就地回答
struct ItemList: View {
    @Environment(AppModel.self) private var model
    let items: [MeetingNotes.Item]
    var detail: MeetingDetail? = nil
    var symbol = "•"
    var symbolColor: Color? = nil
    var ref: (Int) -> NoteItemRef? = { _ in nil }

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                let ref = ref(index)
                VStack(alignment: .leading, spacing: 8) {
                    NoteRow(item: item, symbol: symbol, symbolColor: symbolColor, ref: ref, detail: detail)
                    if let ref, let detail, model.reviewDraft?.expanded == ref {
                        InlineReviewCard(detail: detail, indexes: detail.reviewLinks[ref] ?? [])
                    }
                }
            }
        }
        .lineSpacing(3)
    }
}

/// 一個議題（fork F4.5、F4.7、F4.11，design §F4.4）：左邊心智圖那一支的色條；標題列可以收合，
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
            // 展開／收合只由箭頭和「標題＋條數」兩個按鈕觸發；時間、「？」、複製是旁邊獨立的按鈕，父層沒有點擊手勢（design §F4.4）
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

/// 待確認的標記（R41.1，design §31.2）：這一條紀錄有幾題整理時不確定的地方，琥珀色跟側欄的「待確認 N 題」一樣。
/// 點了在那一條下面展開題目（R41.2）；同時只展開一條，再點一次收合
struct ReviewMarker: View {
    @Environment(AppModel.self) private var model
    let ref: NoteItemRef
    let count: Int

    var body: some View {
        if count > 0 {
            Button {
                if let draft = model.reviewDraft {
                    draft.expanded = draft.expanded == ref ? nil : ref
                } else {
                    model.tab = .summary
                    model.reviewExpanded = true
                }
            } label: {
                Text(count > 1 ? "\(MeetingLanguage.ui(zh: "？", en: "?"))\(count)" : MeetingLanguage.ui(zh: "？", en: "?"))
                    .contentFont(.caption2, weight: .semibold, monospacedDigit: true)
                    .foregroundStyle(Color.signal)
                    .padding(.horizontal, count > 1 ? 5 : 0)
                    .frame(minWidth: 17, minHeight: 17)
                    .background(Color.signal.opacity(0.16), in: Capsule())
            }
            .buttonStyle(.plain)
            .help(count > 1 ? String(localized: "整理時有 \(count) 題不確定的地方，點了就能回答") : String(localized: "整理時有一題不確定的地方，點了就能回答"))
            .accessibilityLabel(String(localized: "待確認 \(count) 題"))
        }
    }
}

/// 就地回答（R41.2，design §31.2）：展開在那一條紀錄下面，列出對應的題目；回答跟待確認分頁是同一份草稿，
/// 「送出」的規則也一樣（送目前所有已回答和略過的題目）
struct InlineReviewCard: View {
    @Environment(AppModel.self) private var model
    let detail: MeetingDetail
    let indexes: [Int]

    var body: some View {
        if let draft = model.reviewDraft, draft.meetingId == detail.meeting.id, let items = detail.notes?.reviewItems {
            let shown = Set(indexes.filter { items.indices.contains($0) })
            VStack(alignment: .leading, spacing: 12) {
                ForEach(shown.sorted(), id: \.self) { index in
                    ReviewQuestionRow(index: index, item: items[index], language: detail.meeting.meetingLanguage, draft: draft)
                }
                HStack(spacing: 12) {
                    Text("只送這一條的題目；有回答的交給整理工具依答案修正，略過的直接移除。")
                        .contentFont(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer()
                    Button("收合") { draft.expanded = nil }
                    // 只送這一條對到的題目（R41.2），題數也只算這幾題
                    Button(draft.submitTitle(only: shown)) { model.submitReviewDraft(only: shown) }
                        .buttonStyle(.borderedProminent)
                        .disabled(!draft.hasSomethingToSubmit(only: shown) || model.detailStatus?.isActive == true)
                }
            }
            .padding(14)
            .background(Color.signal.opacity(0.07), in: RoundedRectangle(cornerRadius: 8))
            .padding(.leading, 14)
        }
    }
}

/// 沒有會議紀錄時的說明與動作
struct NotesPlaceholder: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openSettings) private var openSettings
    let detail: MeetingDetail

    var body: some View {
        let status = model.detailStatus
        VStack(alignment: .leading, spacing: 12) {
            if status == .recording {
                Text("錄音結束、轉錄完成後，會議紀錄會出現在這裡。").foregroundStyle(.secondary)
            } else if status?.isActive == true {
                Text("轉錄和整理完成後，會議紀錄會出現在這裡。").foregroundStyle(.secondary)
            } else if detail.segments.isEmpty && detail.meeting.userNotes.isEmpty {
                Text("還沒有逐字稿。").foregroundStyle(.secondary)
            } else if AppSettings.needsProviderSetup {
                // 沒選過整理工具、也沒有 claude、codex（R35.2）：說還沒設定，給打開設定的按鈕（整理工具是第一個分頁）
                Text("還沒設定整理工具。選好之後，就能把逐字稿整理成摘要、決議和待辦；之後的會議轉錄完會自動整理。")
                    .foregroundStyle(.secondary)
                Button("設定整理工具") { openSettings() }
            } else if AppSettings.provider != .none, let problem = model.summarizerProblem {
                // 選了整理工具但還沒準備好（沒登入、沒有 key…，R45.4）：說原因，給修的按鈕
                // 不加 fixedSize：這裡不在 ScrollView 裡，量最小高度時整個視窗的內容會被往上推（CLAUDE.md）
                Text("整理工具還沒設定好：\(problem.message)")
                    .foregroundStyle(.secondary)
                Button(problem.actionTitle) {
                    switch problem.action {
                    case .openSettings: openSettings()
                    case .login(let provider): CLILogin.openLogin(provider)
                    }
                }
            } else {
                Text(AppSettings.provider == .none
                     ? "整理工具目前設定為「不整理」。要產生會議紀錄，請到設定選擇 Claude、Codex 或 API。"
                     : "這場會議還沒整理成會議紀錄。")
                    .foregroundStyle(.secondary)
                Button("整理成會議紀錄") { model.resummarize() }
                    .disabled(AppSettings.provider == .none)
            }
        }
        .padding(32)
    }
}

/// 紀錄分頁（R44.1，design §33.1）：待確認的條、摘要、決議、待辦、未決問題、議題、自訂段落，一頁捲到底（順序同匯出）。
/// 可以切換成編輯模式（R6.6），一份編輯器編全部；也可以切換成心智圖（R67，design §42.4）
struct NotesPage: View {
    @Environment(AppModel.self) private var model
    @Environment(\.textScale) private var scale
    @Environment(\.snapshotMode) private var snapshotMode
    @AppStorage(AppSettings.notesViewKey) private var notesView = "list"
    let detail: MeetingDetail
    @State private var editing: MeetingNotes?
    @State private var base: MeetingNotes?

    var body: some View {
        if let current = editing {
            NotesEditor(notes: Binding(draft: $editing, fallback: current)) { finish($0) }
                .onDisappear { finish(true, automatically: true) }   // 切到別的分頁、別場會議：自動存，不丟掉打的字
        } else if let notes = detail.notes, !notes.isEmpty, notesView == "mindMap" {
            mindMapPage(notes)
        } else if let notes = detail.notes, !notes.isEmpty {
            listPage(notes)
        } else {
            NotesPlaceholder(detail: detail)
        }
    }

    /// 條列模式（fork F4，design §F4.4）：摘要 → 決議 → 待辦 → 未決問題 → 自訂段落 → 議題（自訂段落在議題前面，同匯出）
    private func listPage(_ notes: MeetingNotes) -> some View {
        let duration = max(model.player.duration, Double(detail.meeting.durationSeconds ?? 0))
        let segments = model.topicSegments(notes: notes, duration: duration)
        let branches = MindMap.topicBranches(notes)
        let collapsed = collapsedTopics(notes)
        return ScrollViewReader { proxy in
            ReadingColumn {
                header(notes)
                if notes.topics.count > 5 {
                    TopicChips(topics: notes.topics.indices.map { t in
                        (index: t, title: notes.topics[t].title.isEmpty ? MindMap.topicLabel(.interface) : notes.topics[t].title,
                         branch: branches[t], segments: branches[t].map { b in segments.filter { $0.branch == b }.count } ?? 0)
                    }) { reveal($0, proxy: proxy) }
                }
                if !notes.summary.isEmpty {
                    NotesSection(title: String(localized: "摘要"), count: notes.summary.count, accent: .slate, copy: .summary) {
                        ItemList(items: notes.summary, detail: detail, symbolColor: .slate) { .summary($0) }
                    }
                }
                if !notes.decisions.isEmpty {
                    NotesSection(title: String(localized: "決議"), count: notes.decisions.count, accent: .celadon, copy: .decisions) {
                        ItemList(items: notes.decisions, detail: detail, symbol: "✓", symbolColor: .celadon) { .decisions($0) }
                    }
                }
                if !notes.actionItems.isEmpty {
                    NotesSection(title: String(localized: "待辦"), count: notes.actionItems.count, accent: .actionBlue, copy: .actionItems) {
                        ActionItemsTable(items: notes.actionItems, detail: detail) { .actionItems($0) }
                    }
                }
                if !notes.openQuestions.isEmpty {
                    NotesSection(title: String(localized: "未決問題"), count: notes.openQuestions.count, accent: .signal, copy: .openQuestions) {
                        ItemList(items: notes.openQuestions, detail: detail, symbol: "?", symbolColor: .signal) { .openQuestions($0) }
                    }
                }
                ForEach(Array(notes.custom.enumerated()), id: \.offset) { c, section in
                    if !section.items.isEmpty {
                        NotesSection(title: section.title, count: section.items.count, copy: .custom(c)) {
                            ItemList(items: section.items, detail: detail) { .custom(c, $0) }
                        }
                    }
                }
                if !notes.topics.isEmpty {
                    // 議題段落本身不加色條：每個議題已經有自己的色條（design §F4.4）
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

    /// 提示條和編輯列：條列、心智圖共用
    @ViewBuilder private func header(_ notes: MeetingNotes) -> some View {
        // 加入、移除文件之後還沒重新整理（R61.8）：提示列不跟著文字大小（R59.2）
        if let id = detail.meeting.id, model.documentsChanged.contains(id) {
            DocumentsBanner().environment(\.textScale, 1)
        }
        if detail.reviewCount > 0 { ReviewBanner(detail: detail) }
        EditBar(viewMode: $notesView, disabled: model.detailStatus?.isActive == true,
                onUndo: detail.canUndoNotes ? { model.undoNotes() } : nil) {
            base = notes; editing = notes
        }
    }

    /// 心智圖模式（design §42.4）：上面照舊是提示條、編輯列，下面是心智圖；段落名稱跟著介面語言（同條列）。
    /// 整頁一起上下捲（同條列）：待確認展開時很高，放在捲動外面會把整個視窗的內容往上推（2026-11-05 使用者看到整個視窗空白）
    private func mindMapPage(_ notes: MeetingNotes) -> some View {
        let layout = MindMap.layout(MindMap.tree(notes: notes, title: detail.meeting.displayTitle, labels: .init(.interface)))
        func page(width: Double) -> some View {
            VStack(alignment: .leading, spacing: 0) {
                VStack(alignment: .leading, spacing: 26) { header(notes) }
                    .contentFont()
                    .frame(maxWidth: 680 * scale, alignment: .leading)
                    .padding(.horizontal, 32)
                    .padding(.top, 24)
                    .padding(.bottom, 26)
                    .frame(maxWidth: .infinity, alignment: .leading)
                MindMapView(layout: layout, language: detail.meeting.meetingLanguage, availableWidth: width,
                            onSeek: model.player.isLoaded ? { model.player.seek(to: $0) } : nil)
            }
        }
        return Group {
            if snapshotMode {
                page(width: 900)
            } else {
                GeometryReader { geo in
                    ScrollView(.vertical) { page(width: geo.size.width) }
                }
            }
        }
    }

    private func finish(_ save: Bool, automatically: Bool = false) {
        guard let draft = editing, let id = detail.meeting.id else { return }
        editing = nil
        if save { model.finishNotesEdit(draft, base: base, meetingId: id, automatically: automatically) }
    }

    private var templateName: String {
        String(localized: "範本：") + (model.templates.first { $0.id == detail.meeting.templateId }?.displayName ?? String(localized: "一般會議"))
    }
}

/// 紀錄頂部「還有 N 題待確認」（R44.2，design §33.1）：點了在原地展開待確認的內容（同一份 ReviewTab），回答跟就地回答共用草稿；
/// 展開狀態只記這次選取期間（AppModel.reviewExpanded，換會議收起）
struct ReviewBanner: View {
    @Environment(AppModel.self) private var model
    let detail: MeetingDetail

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button {
                withAnimation(.easeInOut(duration: 0.15)) { model.reviewExpanded.toggle() }
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: "questionmark.circle.fill").foregroundStyle(Color.signal)
                    Text("還有 \(detail.reviewCount) 題待確認").contentFont(.callout, weight: .medium)
                    Spacer()
                    Text(model.reviewExpanded ? "收起" : "展開").contentFont(.callout).foregroundStyle(.secondary)
                    Image(systemName: model.reviewExpanded ? "chevron.up" : "chevron.down").contentFont(.caption).foregroundStyle(.secondary)
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(String(localized: "待確認 \(detail.reviewCount) 題"))
            if model.reviewExpanded {
                Divider()
                ReviewTab(detail: detail, embedded: true)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 12)
            }
        }
        .background(Color.signal.opacity(0.08), in: RoundedRectangle(cornerRadius: 10))
    }
}

/// 右上角的「編輯」按鈕；有上一版時旁邊多一顆「復原上一版」（R44.4，原本在「更多」）；左邊是「條列｜心智圖」（R67）
struct EditBar: View {
    /// list／mindMap；nil 不顯示切換
    var viewMode: Binding<String>? = nil
    /// 轉錄或整理中不能編輯：工作完成時會整份寫回，手動改的會被蓋掉
    var disabled = false
    /// nil：沒有上一版，不顯示
    var onUndo: (() -> Void)? = nil
    let onEdit: () -> Void

    var body: some View {
        HStack(spacing: 14) {
            if let viewMode {
                Picker("顯示方式", selection: viewMode) {
                    Text("條列").tag("list")
                    Text("心智圖").tag("mindMap")
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .fixedSize()
                .help("把會議紀錄切換成條列或心智圖")
            }
            Spacer()
            if let onUndo {
                Button("復原上一版", systemImage: "arrow.uturn.backward", action: onUndo)
                    .buttonStyle(.borderless)
                    .foregroundStyle(disabled ? Color.secondary : Color.celadon)
                    .disabled(disabled)
                    .help("換回上一版會議紀錄（再按一次換回更早的）")
            }
            Button("編輯", systemImage: "pencil", action: onEdit)
                .buttonStyle(.borderless)
                .foregroundStyle(disabled ? Color.secondary : Color.celadon)
                .disabled(disabled)
                .help(disabled ? "正在處理這場會議，完成後才能編輯" : "直接修改會議紀錄，存檔時會留一個版本")
        }
        .font(.body)   // 按鈕不跟著文字大小（R59.2）
        .padding(.bottom, -18)
    }
}

/// 待辦表（fork F4.4）：負責人、期限在左邊方便掃讀，事項在右邊、時間點在最後；三個文字欄都能選取
struct ActionItemsTable: View {
    @Environment(AppModel.self) private var model
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
                    Text(item.owner.isEmpty ? String(localized: "未指定") : item.owner).meetingText()
                        .fontWeight(item.owner.isEmpty ? .regular : .semibold)
                        .foregroundStyle(item.owner.isEmpty ? Color.signal : Color.primary)
                        .textSelection(.enabled)
                    Text(item.due.isEmpty ? "—" : item.due)
                        .monospacedDigit()
                        .foregroundStyle(item.due.isEmpty ? .tertiary : .primary)
                        .textSelection(.enabled)
                    Text(item.task).meetingText()
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .gridColumnAlignment(.leading)
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        if let ref, let detail { ReviewMarker(ref: ref, count: detail.reviewCount(ref)) }
                        if !item.time.isEmpty { TimeButton(time: item.time, subdued: true, highlighted: hovered == index) }
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

extension Binding {
    /// 編輯中的草稿（可能是 nil）給編輯器用：草稿已經是 nil 時讀到 fallback，寫入不理會。
    /// 不能用 `Binding($editing)`：按「完成」「取消」把草稿設成 nil 時，同一次更新裡編輯器的欄位還會再讀一次，
    /// 它會強制解開 nil 而閃退（3.2.0 的錯誤，3.2.1 修正）
    init(draft base: Binding<Value?>, fallback: Value) {
        self.init(get: { base.wrappedValue ?? fallback },
                  set: { if base.wrappedValue != nil { base.wrappedValue = $0 } })
    }
}

/// 手動編輯會議紀錄（R6.6）：每一條都是可以改的欄位，可以新增、刪除、上下移動；按「完成」才存成新版本
struct NotesEditor: View {
    @Environment(\.textScale) private var scale
    @Binding var notes: MeetingNotes
    let onFinish: (Bool) -> Void

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("編輯會議紀錄").font(.headline)
                Spacer()
                Button("取消") { onFinish(false) }
                    .keyboardShortcut(.cancelAction)
                Button("完成") { onFinish(true) }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
            }
            .padding(.horizontal, 32)
            .padding(.vertical, 10)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    TextField("標題", text: $notes.title).contentTitleFont(18)
                    EditorSection(title: String(localized: "摘要")) { ItemsEditor(items: $notes.summary) }
                    EditorSection(title: String(localized: "決議")) { ItemsEditor(items: $notes.decisions) }
                    EditorSection(title: String(localized: "待辦")) { ActionItemsEditor(items: $notes.actionItems) }
                    EditorSection(title: String(localized: "未決問題")) { ItemsEditor(items: $notes.openQuestions) }
                    // 議題（原「詳細」分頁的編輯器，R44.1 合併成一份）
                    EditorSection(title: String(localized: "議題")) {
                        ForEach(notes.topics.indices, id: \.self) { i in
                            let topic = $notes.topics.safe(i, fallback: .init(title: "", start: "", points: []))
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    TextField("時間", text: topic.start).frame(width: 70 * scale).monospacedDigit()
                                    TextField("議題", text: topic.title).contentTitleFont(16)
                                    Button { if notes.topics.indices.contains(i) { notes.topics.remove(at: i) } } label: { Image(systemName: "trash") }
                                        .buttonStyle(.borderless).help("刪除這個議題")
                                }
                                ItemsEditor(items: topic.points)
                            }
                        }
                        Button("新增議題", systemImage: "plus") {
                            notes.topics.append(.init(title: "", start: "", points: []))
                        }
                        .buttonStyle(.borderless)
                        .contentFont(.callout)
                    }
                    ForEach(notes.custom.indices, id: \.self) { i in
                        let section = $notes.custom.safe(i, fallback: .init(title: "", items: []))
                        EditorSection(title: section.wrappedValue.title) { ItemsEditor(items: section.items) }
                    }
                    if !notes.reviewItems.isEmpty {
                        EditorSection(title: String(localized: "待確認")) {
                            ForEach(Array(notes.reviewItems.enumerated()), id: \.offset) { index, item in
                                HStack(alignment: .firstTextBaseline) {
                                    Text(item.time).monospacedDigit().foregroundStyle(.secondary)
                                    Text(item.question).meetingText()
                                    Spacer()
                                    Button { if notes.reviewItems.indices.contains(index) { notes.reviewItems.remove(at: index) } } label: { Image(systemName: "trash") }
                                        .buttonStyle(.borderless).help("刪除這一題")
                                }
                            }
                        }
                    }
                }
                .textFieldStyle(.roundedBorder)
                .contentFont()   // 文字大小（design §38.5）
                .frame(maxWidth: 720 * scale, alignment: .leading)
                .padding(.horizontal, 32)
                .padding(.vertical, 20)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }
}

private struct EditorSection<Content: View>: View {
    let title: String
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).contentTitleFont(16)
            content
        }
    }
}

private struct ItemsEditor: View {
    @Environment(\.textScale) private var scale
    @Binding var items: [MeetingNotes.Item]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(items.indices, id: \.self) { i in
                let item = $items.safe(i, fallback: .init(text: ""))
                HStack(spacing: 6) {
                    TextField("內容", text: item.text, axis: .vertical).meetingText()
                    TextField("時間", text: item.time).frame(width: 64 * scale).monospacedDigit()
                    RowButtons(index: i, count: items.count, move: { $items.move(i, to: $0) }, delete: { $items.remove(i) })
                }
            }
            Button("新增一條", systemImage: "plus") { items.append(.init(text: "")) }
                .buttonStyle(.borderless)
                .contentFont(.callout)
        }
    }
}

private struct ActionItemsEditor: View {
    @Environment(\.textScale) private var scale
    @Binding var items: [MeetingNotes.ActionItem]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(items.indices, id: \.self) { i in
                let item = $items.safe(i, fallback: .init(owner: "", task: "", due: ""))
                HStack(spacing: 6) {
                    TextField("負責人", text: item.owner).frame(width: 90 * scale)
                    TextField("事項", text: item.task, axis: .vertical).meetingText()
                    TextField("yyyy-MM-dd", text: item.due).frame(width: 100 * scale).monospacedDigit()
                    TextField("時間", text: item.time).frame(width: 64 * scale).monospacedDigit()
                    RowButtons(index: i, count: items.count, move: { $items.move(i, to: $0) }, delete: { $items.remove(i) })
                }
            }
            Button("新增待辦", systemImage: "plus") { items.append(.init(owner: "", task: "", due: "")) }
                .buttonStyle(.borderless)
                .contentFont(.callout)
        }
    }
}

private struct RowButtons: View {
    let index: Int
    let count: Int
    let move: (Int) -> Void
    let delete: () -> Void

    var body: some View {
        HStack(spacing: 2) {
            Button { move(index - 1) } label: { Image(systemName: "chevron.up") }.disabled(index == 0).help("往上移")
            Button { move(index + 1) } label: { Image(systemName: "chevron.down") }.disabled(index >= count - 1).help("往下移")
            Button(action: delete) { Image(systemName: "trash") }.help("刪除")
        }
        .buttonStyle(.borderless)
    }
}

/// 編輯清單用的陣列元素綁定：刪掉一條之後 SwiftUI 可能還會用舊的位置讀寫一次，越界時讀到空值、不寫入，不會閃退
extension Binding where Value: MutableCollection & RangeReplaceableCollection, Value.Index == Int {
    func safe(_ index: Int, fallback: Value.Element) -> Binding<Value.Element> {
        Binding<Value.Element>(
            get: { wrappedValue.indices.contains(index) ? wrappedValue[index] : fallback },
            set: { if wrappedValue.indices.contains(index) { wrappedValue[index] = $0 } })
    }

    func remove(_ index: Int) {
        if wrappedValue.indices.contains(index) { wrappedValue.remove(at: index) }
    }

    func move(_ index: Int, to target: Int) {
        if wrappedValue.indices.contains(index) && wrappedValue.indices.contains(target) { wrappedValue.swapAt(index, target) }
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
