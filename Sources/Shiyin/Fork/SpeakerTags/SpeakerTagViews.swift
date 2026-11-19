import AppKit
import SwiftUI

// 錄音中標記說話者的畫面（fork design §F2.2、§F2.4）：錄音畫面的「正在說話」、即時逐字稿每一行的名字、
// 會議頁的「標記」名字、沒套用的標記。上游的檔只留接點（`// MA-FORK(F2)`）

extension View {
    /// 上游 RecordingPanel 的接點：即時逐字稿上面放「正在說話」那一排。說話者辨識關掉時沒有說話者可以套用，不顯示
    func forkSpeakerTagBar(_ detail: MeetingDetail) -> some View {
        VStack(spacing: 0) {
            if AppSettings.diarize {
                SpeakerTagBar(roster: detail.tagRoster)
                Divider()
            }
            self
        }
    }
}

/// 「正在說話」（fork design §F2.2、R23.2）：誰在說話就按他的名字，標記現在這幾秒；＋ 加入與會者
struct SpeakerTagBar: View {
    @Environment(AppModel.self) private var model
    let roster: [String]
    @State private var adding = false

    var body: some View {
        HStack(spacing: 10) {
            Text("正在說話").foregroundStyle(.secondary)
            if roster.isEmpty {
                Text("按 ＋ 加入與會者的名字，誰在說話就按他的名字").foregroundStyle(.tertiary).lineLimit(1)
                Spacer(minLength: 0)
            } else {
                ScrollView(.horizontal) {
                    HStack(spacing: 6) {
                        ForEach(Array(roster.enumerated()), id: \.element) { index, name in
                            // 選單、工具列以外的按鈕才畫得出膠囊背景；顏色跟一行前面的名字一樣，依名單的順序
                            Button { model.tagSpeakerNow(name) } label: {
                                Text(name)
                                    .padding(.horizontal, 10)
                                    .padding(.vertical, 3)
                                    .foregroundStyle(Color.speaker(index + 1))
                                    .background(Color.speaker(index + 1).opacity(0.12), in: Capsule())
                            }
                            .buttonStyle(.plain)
                            .help("\(name)正在說話：標記現在這幾秒，錄完會套到他的說話者")
                        }
                    }
                }
                .scrollIndicators(.never)
                .disabled(model.recorder.isPaused)
            }
            Button { adding = true } label: { Image(systemName: "plus") }
                .buttonStyle(.borderless)
                .help("加入與會者的名字")
                .accessibilityLabel("加入名字")
                .popover(isPresented: $adding, arrowEdge: .bottom) {
                    SpeakerNameForm(actionTitle: "加入", exclude: roster) { name in
                        model.addParticipant(name)
                        adding = false
                    } onCancel: { adding = false }
                }
        }
        .contentFont(.callout)
        .padding(.horizontal, 20)
        .padding(.vertical, 8)
        #if DEBUG
        .onChange(of: model.debugTagUI) { _, value in
            guard value == "add" else { return }
            adding = true
            model.debugTagUI = nil
        }
        #endif
    }
}

/// 即時逐字稿的一行（上游 design §5.4）：時間、這段是誰說的（fork design §F2.2、R23.1）、文字、重點
struct LiveLineRow: View {
    @Environment(AppModel.self) private var model
    @Environment(\.textScale) private var scale
    let line: Recorder.LiveLine
    let tagged: String?
    let roster: [String]
    let starred: Bool
    let tagging: Bool
    @State private var hovering = false
    @State private var naming = false

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(TimeFormat.string(line.start)).contentFont(.callout, monospacedDigit: true).foregroundStyle(Color.celadon)
                .frame(width: 52 * scale, alignment: .trailing)
            if tagging { tagMenu }
            Text(line.text).textSelection(.enabled).fixedSize(horizontal: false, vertical: true).meetingText()
            if starred {
                Image(systemName: "star.fill").foregroundStyle(Color.signal).contentFont(.caption)
            }
        }
        .onHover { hovering = $0 }
        // 右鍵選單會取代文字原本的選單，所以「拷貝」要自己放（跟逐字稿分頁一樣）
        .contextMenu {
            if tagging {
                menuItems
                Divider()
            }
            Button("拷貝") {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(line.text, forType: .string)
            }
        }
        .popover(isPresented: $naming, arrowEdge: .bottom) {
            SpeakerNameForm(actionTitle: "標記", exclude: roster) { name in
                model.tagLiveLine(line, as: name)
                naming = false
            } onCancel: { naming = false }
        }
        #if DEBUG
        .onChange(of: model.debugTagUI) { _, value in
            guard value == "name:\(line.id)" else { return }
            naming = true
            model.debugTagUI = nil
        }
        #endif
    }

    /// 標過是名字（說話者的顏色，依名單的順序），沒標是淡淡的人像、滑過時變清楚。
    /// 選單在畫面上只畫標題的文字，所以名字不加背景
    private var tagMenu: some View {
        Menu { menuItems } label: {
            if let tagged {
                let index = roster.firstIndex { SpeakerTagging.sameName($0, tagged) } ?? 0
                Text(tagged).fontWeight(.medium).foregroundStyle(Color.speaker(index + 1))
            } else {
                Image(systemName: "person.crop.circle").foregroundStyle(.secondary)
            }
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .lineLimit(1)
        .frame(width: 64 * scale, alignment: .leading)
        .opacity(tagged != nil || hovering ? 1 : 0.35)
        .help(tagged == nil ? "這段是誰說的？標記後，錄完會套到他的說話者" : "改成別人或清除標記")
        .accessibilityLabel(tagged ?? String(localized: "這段是誰說的"))
    }

    @ViewBuilder
    private var menuItems: some View {
        Section("這段是誰說的") {
            ForEach(roster, id: \.self) { name in
                Button {
                    model.tagLiveLine(line, as: name)
                } label: {
                    if let tagged, SpeakerTagging.sameName(tagged, name) { Label(name, systemImage: "checkmark") } else { Text(name) }
                }
            }
        }
        let others = model.knownPeople.filter { person in !roster.contains { SpeakerTagging.sameName($0, person) } }
        if !others.isEmpty {
            // 設定頁的「認識的人」英文帶 app 名稱，放在選單裡太長
            Menu(MeetingLanguage.ui(zh: "認識的人", en: "Known People")) {
                ForEach(others, id: \.self) { person in
                    Button(person) { model.tagLiveLine(line, as: person) }
                }
            }
        }
        Button("其他名字…") { naming = true }
        if tagged != nil {
            Divider()
            Button("清除標記") { model.clearLiveLineTag(line) }
        }
    }
}

/// 輸入說話者的名字（fork design §F2.2）：Enter 或按鈕送出；下面列出還不在名單裡的認識的人，點了就用那個名字
struct SpeakerNameForm: View {
    @Environment(AppModel.self) private var model
    let actionTitle: LocalizedStringKey
    let exclude: [String]
    let onDone: (String) -> Void
    let onCancel: () -> Void
    @State private var name = ""
    @FocusState private var focused: Bool

    var body: some View {
        let typed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let people = model.knownPeople.filter { person in
            !exclude.contains { SpeakerTagging.sameName($0, person) } && (typed.isEmpty || person.localizedCaseInsensitiveContains(typed))
        }
        VStack(alignment: .leading, spacing: 10) {
            TextField("名字", text: $name)
                .textFieldStyle(.roundedBorder)
                .focused($focused)
                .onSubmit(submit)
            if !people.isEmpty {
                Text(MeetingLanguage.ui(zh: "認識的人", en: "Known People")).font(.caption).foregroundStyle(.secondary)
                ScrollView {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(people, id: \.self) { person in
                            Button(person) { onDone(person) }.buttonStyle(.link)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(height: min(120, CGFloat(people.count) * 22))
            }
            HStack {
                Spacer()
                Button("取消", role: .cancel, action: onCancel)
                    .keyboardShortcut(.cancelAction)
                Button(actionTitle, action: submit)
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
                    .disabled(typed.isEmpty)
            }
        }
        .padding(14)
        .frame(width: 260)
        .onAppear { focused = true }
    }

    private func submit() {
        let typed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        if !typed.isEmpty { onDone(typed) }
    }
}


/// 聲紋自動帶入的名字（上游的 AutoSpeakerName，R19.3）同一個樣子，標「標記」（fork design §F2.4、F2.9）：
/// 錄音時標記帶入的名字。點一下選是別人，或說不是他（同上游的「不是他」）
struct ForkTaggedSpeakerName: View {
    @Environment(AppModel.self) private var model
    let idx: Int
    let name: String
    let others: [String]

    var body: some View {
        HStack(spacing: 3) {
            Menu {
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
            // 選單按鈕在畫面上只畫標題的文字（標籤裡的背景會被拿掉），標記要放在選單外面
            Text(MeetingLanguage.ui(zh: "標記", en: "Tagged"))
                .font(.caption2)
                .padding(.horizontal, 4)
                .padding(.vertical, 1)
                .background(Color.secondary.opacity(0.15), in: Capsule())
        }
        .help("錄音時標記的名字。不對的話點名字")
    }
}

/// 錄音時標記、沒有自動套用的名字（fork design §F2.4、R23.5）：「查看」跳到逐字稿上的位置，在那裡套用或刪掉
struct UnappliedTagsBanner: View {
    @Environment(AppModel.self) private var model
    let detail: MeetingDetail

    var body: some View {
        let tags = detail.unappliedTags
        let names = SpeakerTagging.roster(participants: [], tagged: tags.map(\.name))
        HStack(spacing: 10) {
            Label("錄音時標記的 \(names.count) 個名字沒有自動套用：\(names.joined(separator: String(localized: "、")))",
                  systemImage: "person.crop.circle.badge.questionmark")
            Spacer()
            Button("查看") {
                model.tab = .transcript
                if let first = tags.first?.id, let segment = detail.tagMatches[first]?.segmentId { model.flashSegment(segment) }
            }
        }
        .font(.callout)
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(Color.signal.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
    }
}


/// 錄音時標記、沒套用的名字（fork design §F2.4、R23.5）：逐字稿那一段下面，套用到這一段的說話者（跟手動改名一樣），或刪掉標記
struct UnappliedTagLine: View {
    @Environment(AppModel.self) private var model
    let tag: SpeakerTag
    let idx: Int
    let detail: MeetingDetail

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Label("錄音時標記為\(tag.name)", systemImage: "person.crop.circle.badge.questionmark")
                .foregroundStyle(Color.signal)
            Spacer(minLength: 8)
            Button("刪除標記") { if let id = tag.id { model.deleteSpeakerTag(id) } }
                .buttonStyle(.link)
            let count = detail.taggedSegments(tag).count
            if count > 0 {
                Button(count == 1 ? String(localized: "只改這句") : String(localized: "只改這 \(count) 句")) {
                    model.reassignTaggedSegments(tag)
                }
                .buttonStyle(.link)
                .help("只把標記蓋到的句子改成\(tag.name)說的，說話者的其他句子不變")
            }
            Button("套用到\(detail.speakerName(idx) ?? "")") { model.renameSpeaker(idx, to: tag.name) }
                .buttonStyle(.link)
        }
        .font(.caption)
    }
}

/// 改名的小視窗（上游的 RenameSpeakerForm）：名字是錄音時標記帶入的，說明換成這一句（fork design §F2.4、F2.9）
struct ForkTaggedNameNote: View {
    var body: some View {
        Text("這個名字是從錄音時的標記帶入的。不對的話直接改名，或按「不是他」。")
            .font(.caption)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
    }
}
