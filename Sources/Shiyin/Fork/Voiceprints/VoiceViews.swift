import SwiftUI

/// 會議頁上方 `speakerChip` 選名字畫法的那一行（`// MA-FORK(F2)`，fork design §F12.1、§F0.7）：
/// 標記帶入的用 F2 的 `ForkTaggedSpeakerName`；自動帶入、算得出依據的用 `ForkAutoSpeakerName`；其他回 nil 照上游
struct ForkSpeakerChip: View {
    private enum Kind { case tag, auto(ForkVoiceScores.Basis) }
    let idx: Int
    let name: String
    let others: [String]
    private let kind: Kind

    init?(idx: Int, name: String, detail: MeetingDetail) {
        switch detail.speakerSources[idx] {
        case "tag": kind = .tag
        case "voiceprint":
            guard let basis = detail.forkTags.voice[idx] else { return nil }
            kind = .auto(basis)
        default: return nil
        }
        self.idx = idx
        self.name = name
        others = detail.speakerCandidates[idx] ?? []
    }

    var body: some View {
        switch kind {
        case .tag: ForkTaggedSpeakerName(idx: idx, name: name, others: others)
        case .auto(let basis): ForkAutoSpeakerName(idx: idx, name: name, others: others, basis: basis)
        }
    }
}

/// 聲紋自動帶入的名字（上游 MeetingDetailView 的 `AutoSpeakerName` 的複本，R19.3、R33.4；DF8 的做法）：
/// 選單最上面多一行依據（F12.4）。上游改 `AutoSpeakerName` 時要跟著比對
struct ForkAutoSpeakerName: View {
    @Environment(AppModel.self) private var model
    let idx: Int
    let name: String
    let others: [String]
    let basis: ForkVoiceScores.Basis

    var body: some View {
        HStack(spacing: 3) {
            Menu {
                Text(ForkVoiceScores.autoBasis(basis, name: name))   // F12.4：依據
                Divider()
                if !others.isEmpty {
                    Section("是別人：") {
                        ForEach(others, id: \.self) { other in
                            Button(other) { model.renameSpeaker(idx, to: other) }
                        }
                    }
                }
                Button("其他人…（到逐字稿改名）") { model.tab = .transcript }
                Divider()
                Button("不是\(name)（不知道是誰）") { model.rejectVoiceprintMatch(idx) }
            } label: {
                Text(name).foregroundStyle(Color.speaker(idx))
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .fixedSize()
            // 選單按鈕在畫面上只畫標題的文字（標籤裡的背景會被拿掉），「自動」標記要放在選單外面
            Text("自動")
                .font(.caption2)
                .padding(.horizontal, 4)
                .padding(.vertical, 1)
                .background(Color.secondary.opacity(0.15), in: Capsule())
        }
        .help("拾音認出這個人的聲音，自動帶入名字。不對的話點名字")
    }
}

/// 會議頁上方 fork 的提示列（`// MA-FORK(F0)`，fork design §F0.7）：F2 沒套用的標記（條件照舊）、F12 改名防呆
struct ForkDetailBanners: View {
    @Environment(AppModel.self) private var model
    let detail: MeetingDetail
    /// 不在錄音、不在垃圾桶（F2 的提示列原本的條件）
    let active: Bool

    var body: some View {
        if active && !detail.unappliedTags.isEmpty { UnappliedTagsBanner(detail: detail) }
        if let id = detail.meeting.id, model.fork.voiceGuard.contains(where: { $0.meetingId == id }) { ForkVoiceGuardBanner() }
    }
}

/// 改名防呆的提示列和視窗（F12.8、F12.9）：佇列從空變成有東西時視窗自動打開；「查看」再打開
struct ForkVoiceGuardBanner: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let items = model.fork.voiceGuard.filter { $0.meetingId == model.selection }
        HStack(spacing: 10) {
            Label("有 \(items.count) 位說話者的名字還沒改：聲音跟名字對不上", systemImage: "exclamationmark.triangle")
            Spacer()
            Button("查看") { model.fork.voiceGuardShowing = true }
        }
        .font(.callout)
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(Color.orange.opacity(0.10), in: RoundedRectangle(cornerRadius: 8))
        .sheet(isPresented: Binding(get: { model.fork.voiceGuardShowing && !items.isEmpty },
                                    set: { if !$0 { model.fork.voiceGuardShowing = false } })) {
            ForkVoiceGuardSheet(items: items)
        }
    }
}

struct ForkVoiceGuardSheet: View {
    @Environment(AppModel.self) private var model
    let items: [ForkVoiceGuard.Item]

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(items.count == 1 ? String(localized: "確定是\(items[0].name)嗎？")
                                  : String(localized: "這 \(items.count) 位說話者的聲音跟名字對不上"))
                .font(.title3).fontWeight(.bold)
            VStack(alignment: .leading, spacing: 8) {
                ForEach(items) { item in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                        Text(Self.line(item)).fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            Text("「仍要存」照樣取名、記住這個聲音；「只改名，不記住聲音」名字照改，但之後的會議不會用這個聲音比對。")
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 8) {
                Spacer()
                Button("取消") { ForkVoiceGuard.choose(model, .cancel) }
                    .buttonStyle(SheetPillButtonStyle(.secondary))
                    .keyboardShortcut(.cancelAction)
                Button("仍要存") { ForkVoiceGuard.choose(model, .keep) }
                    .buttonStyle(SheetPillButtonStyle(.secondary))
                Button("只改名，不記住聲音") { ForkVoiceGuard.choose(model, .nameOnly) }
                    .buttonStyle(SheetPillButtonStyle(.primary))
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 460)
        .background(Color(nsColor: .windowBackgroundColor))   // 視窗底色畫進內容裡：DEBUG 的 mawindowshot 才畫得出文字
    }

    /// 「『說話者 6』→ Ben：聲音很像 Amy（95%），跟 Ben 之前的聲音只有 26%。」
    static func line(_ item: ForkVoiceGuard.Item) -> String {
        let other = ForkVoiceScores.percent(item.other.score)
        if let target = item.target {
            return String(localized: "「\(item.current)」→ \(item.name)：聲音很像 \(item.other.name)（\(other)%），跟 \(item.name) 之前的聲音只有 \(ForkVoiceScores.percent(target))%。")
        }
        return String(localized: "「\(item.current)」→ \(item.name)：聲音很像 \(item.other.name)（\(other)%），\(item.name) 還沒有聲音樣本。")
    }
}

/// 人物頁的「聲音特徵」（F12.10～F12.12）：PersonPage「會議」那一段之後（`// MA-FORK(F12)`）
struct ForkPersonVoiceprints: View {
    @Environment(AppModel.self) private var model
    let personId: Int64
    @State private var rows: [ForkVoiceSources.PrintRow] = []
    @State private var confirming: Int64?

    var body: some View {
        NotesSection(title: String(localized: "聲音特徵（\(rows.count) 份）")) {
            if rows.isEmpty {
                Text("這個人還沒有聲音特徵。").foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(rows) { row in printRow(row) }
                }
            }
        }
        .task(id: personId) { load() }
        .onChange(of: model.peopleOverview) { load() }
        .confirmationDialog("刪除這份聲音特徵？", isPresented: Binding(get: { confirming != nil }, set: { if !$0 { confirming = nil } })) {
            Button("刪除", role: .destructive) {
                if let id = confirming { delete(id) }
                confirming = nil
            }
            Button("取消", role: .cancel) { confirming = nil }
        } message: {
            Text("會議裡的名字不會變；之後的會議不再用這份比對。")
        }
    }

    @ViewBuilder
    private func printRow(_ row: ForkVoiceSources.PrintRow) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline, spacing: 14) {
                Text(Self.date(row.createdAt)).monospacedDigit().foregroundStyle(.secondary)
                if row.enrolled {
                    Text("我的聲音")
                } else if let meetingId = row.meetingId, let title = row.meetingTitle, !row.meetingTrashed {
                    Button { model.openFromPersonPage(meetingId) } label: { Text(title).meetingText().lineLimit(1) }
                        .buttonStyle(.plain)
                        .help("打開這場會議")
                } else {
                    Text(row.meetingTrashed ? String(localized: "會議在垃圾桶") : String(localized: "會議已刪除")).foregroundStyle(.secondary)
                }
                Spacer(minLength: 12)
                Text(ForkVoiceSources.label(row)).font(.callout).foregroundStyle(.secondary)
                Text(row.ownBest.map { String(localized: "跟其他樣本最像 \(ForkVoiceScores.percent($0))%") } ?? String(localized: "只有這一份"))
                    .font(.callout).monospacedDigit()
                if row.enrolled {
                    Image(systemName: "trash").foregroundStyle(.tertiary)
                        .help("在設定的「我的聲音」管理")
                } else {
                    Button { confirming = row.id } label: { Image(systemName: "trash") }
                        .buttonStyle(.borderless)
                        .help("刪除這份…")
                        .accessibilityLabel(Text("刪除這份…"))
                }
            }
            ForEach(ForkVoiceSources.Flag.allCases.filter { row.flags.contains($0) }, id: \.self) { flag in
                Label(ForkVoiceSources.flagText(flag), systemImage: "exclamationmark.triangle.fill")
                    .font(.callout).foregroundStyle(.orange)
            }
            if row.suspicious, let other = row.other {
                Label("跟這個人其他樣本不像，跟 \(other.name) 很像（\(ForkVoiceScores.percent(other.score))%）", systemImage: "exclamationmark.triangle.fill")
                    .font(.callout).foregroundStyle(.orange)
            }
            if row.warned {
                Text("存的時候提醒過").font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, row.needsCheck ? 4 : 0)
        .padding(.horizontal, row.needsCheck ? 8 : 0)
        .background(row.needsCheck ? Color.orange.opacity(0.08) : Color.clear, in: RoundedRectangle(cornerRadius: 6))
    }

    private func load() {
        rows = (try? ForkVoiceSources.rows(model.db, personId: personId)) ?? []
    }

    private func delete(_ id: Int64) {
        do {
            try ForkVoiceSources.delete(model.db, voiceprintId: id)
        } catch {
            model.errorMessage = error.localizedDescription
        }
        ForkVoiceprintsUI.afterDelete(model)
        load()
    }

    /// created_at（ISO8601 UTC）→ 本地日期
    static func date(_ iso: String) -> String {
        guard let date = ISO8601DateFormatter().date(from: iso) else { return String(iso.prefix(10)) }
        return date.formatted(date: .numeric, time: .omitted)
    }
}

@MainActor
enum ForkVoiceprintsUI {
    /// 刪了單份聲紋之後：人物頁的摘要、目前會議的說話者（「是別人」的候選、依據）重讀
    static func afterDelete(_ model: AppModel) {
        model.reloadPeopleOverview()
        if model.detail != nil { model.reloadDetail([.speakers]) }
    }
}
