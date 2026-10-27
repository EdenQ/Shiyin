import SwiftUI

/// 錄音中的畫面（design §5.4、R2）：即時逐字稿＋我的筆記＋重點
struct RecordingPanel: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let detail: MeetingDetail
    @State private var followLatest = true

    var body: some View {
        #if DEBUG
        let _ = DebugMetrics.bump("recordingPanelBody")
        #endif
        let recorder = model.recorder
        VStack(spacing: 0) {
            // 計時、音量每 0.05 秒變一次，只讓這一塊重算（design §21.12）
            Isolated { controls(recorder) }
            if let change = recorder.languageSwitch {
                // 自動偵測換了語言（design §18.8）：可以改回來
                HStack(spacing: 12) {
                    Label("聽起來是\(change.to.uiName)，即時逐字稿和會議語言已經改成\(change.to.uiName)", systemImage: "globe")
                    Spacer()
                    Button("改回\(change.from.uiName)") { recorder.switchLanguage(to: change.from) }
                }
                .font(.callout)
                .padding(.horizontal, 16)
                .padding(.vertical, 8)
                .background(Color.signal.opacity(0.12))
            }
            if let hint = recorder.levelHint {
                // 收音提醒（design §26.1）
                HStack(spacing: 12) {
                    Label(Self.levelHintText(hint), systemImage: hint == .noisy ? "waveform.badge.exclamationmark" : "mic.badge.xmark")
                    Spacer()
                    Button("知道了") { recorder.dismissLevelHint() }
                        .help("這場錄音不再提示這件事")
                }
                .font(.callout)
                .padding(.horizontal, 16)
                .padding(.vertical, 8)
                .background(Color.signal.opacity(0.12))
            }
            Divider()
            // 不用 HSplitView：它在 NavigationSplitView 裡會把內容撐到視窗的預設寬度，視窗窄的時候左右被切掉
            HStack(spacing: 0) {
                VStack(spacing: 0) {
                    // 錄音中標記說話者（design §24.2）：說話者辨識關掉時沒有說話者可以套用，不顯示
                    if AppSettings.diarize {
                        SpeakerTagBar(roster: detail.tagRoster)
                        Divider()
                    }
                    Isolated { liveTranscript(recorder) }
                }
                .frame(minWidth: 300, maxWidth: .infinity)
                Divider()
                VStack(alignment: .leading, spacing: 8) {
                    Text("我的筆記").font(.songti(16))
                    Text("每換一行會自動加上當下的錄音時間；整理時會優先納入這些內容。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    UserNotesEditor(meetingId: detail.meeting.id!, initial: detail.meeting.userNotes) { recorder.elapsed }
                }
                .padding(16)
                .frame(width: 300)
            }
        }
        .onAppear { model.refreshKnownPeople() }
    }

    /// 提示的文字在 `Recorder.LevelHint.text`（錄音畫面、選單列、通知共用，R42）
    static func levelHintText(_ hint: Recorder.LevelHint) -> String { hint.text }

    private func controls(_ recorder: Recorder) -> some View {
        HStack(spacing: 14) {
            HStack(spacing: 8) {
                Circle().fill(recorder.isPaused ? Color.secondary : .red).frame(width: 10, height: 10)
                Text(recorder.isPaused ? "已暫停" : "錄音中")
                RecorderClock(recorder: recorder).foregroundStyle(.secondary)
            }
            .font(.title3)
            if recorder.hasMic {
                Label { RecorderMeter(recorder: recorder, system: false) } icon: { Image(systemName: "mic") }
                    .help("麥克風音量")
            }
            if recorder.hasSystem {
                Label { RecorderMeter(recorder: recorder, system: true) } icon: { Image(systemName: "speaker.wave.2") }
                    .help("電腦播放的聲音（線上會議的對方）")
            }
            Spacer(minLength: 0)
            // 視窗窄的時候（側邊欄打開、視窗寬 960）按鈕只留圖示，說明放在滑鼠提示。
            // 英文的字比較長，中間多一層：暫停、標記只留圖示，「停止並轉錄」保留文字
            ViewThatFits(in: .horizontal) {
                actionButtons(recorder).labelStyle(.titleAndIcon)
                HStack(spacing: 14) {
                    HStack(spacing: 14) { pauseButton(recorder); bookmarkButton(recorder) }.labelStyle(.iconOnly)
                    stopButton(recorder).labelStyle(.titleAndIcon)
                }
                .fixedSize()
                actionButtons(recorder).labelStyle(.iconOnly)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
        .overlay(alignment: .bottomLeading) {
            if let warning = warning(recorder) {
                Label(warning, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(Color.signal)
                    .padding(.leading, 20)
                    .offset(y: 14)
            }
        }
    }

    private func actionButtons(_ recorder: Recorder) -> some View {
        HStack(spacing: 14) {
            pauseButton(recorder)
            bookmarkButton(recorder)
            stopButton(recorder)
        }
        .fixedSize()
    }

    private func pauseButton(_ recorder: Recorder) -> some View {
        Button(recorder.isPaused ? "繼續" : "暫停", systemImage: recorder.isPaused ? "play.fill" : "pause.fill") {
            recorder.isPaused ? recorder.resume() : recorder.pause()
        }
        .help(recorder.isPaused ? "繼續錄音（⇧⌘P）" : "暫停錄音（⇧⌘P）")
    }

    private func bookmarkButton(_ recorder: Recorder) -> some View {
        Button("標記重點", systemImage: "star") {
            model.addBookmark(at: recorder.elapsed, meetingId: detail.meeting.id)
            model.noticeMessage = String(localized: "已標記 \(TimeFormat.string(recorder.elapsed)) 為重點")
        }
        .help("標記這個時間點（⌘B），整理時會被當成重點")
    }

    private func stopButton(_ recorder: Recorder) -> some View {
        Button("停止並轉錄", systemImage: "stop.fill") { recorder.stop() }
            .buttonStyle(.borderedProminent)
            .tint(.red)
            .help("停止錄音，開始正式轉錄")
    }

    private func warning(_ recorder: Recorder) -> String? {
        if let warning = recorder.deviceWarning { return warning }
        if recorder.hasSystem && recorder.systemSilent {
            return String(localized: "超過 15 秒沒有收到系統聲音：請確認線上會議有聲音，並在「系統設定 → 隱私權與安全性 → 錄製螢幕與系統錄音」允許會議助手")
        }
        return recorder.liveStatus.isEmpty ? nil : recorder.liveStatus
    }

    private func liveTranscript(_ recorder: Recorder) -> some View {
        #if DEBUG
        DebugMetrics.bump("liveTranscriptBuild")
        #endif
        // 每個重點只標在一段上：開始時間不晚於它的最後一段
        let starred = Set(detail.bookmarks.compactMap { mark in recorder.liveLines.last(where: { $0.start <= mark.time })?.id })
        let tagging = AppSettings.diarize
        let roster = detail.tagRoster
        return ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 8) {
                    if recorder.liveLines.isEmpty && recorder.volatileText.isEmpty {
                        Text(AppSettings.liveTranscription ? "開始說話後，逐字稿會即時出現在這裡。" : "即時逐字稿已在設定中關閉，錄音結束後會正式轉錄。")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(recorder.liveLines) { line in
                        LiveLineRow(line: line, tagged: tagging ? detail.liveTag(start: line.start, end: line.end)?.name : nil,
                                    roster: roster, starred: starred.contains(line.id), tagging: tagging)
                            .id(line.id)
                    }
                    // 還沒定稿的文字一直在變，只讓這一行重算，不拖著整份即時逐字稿（design §21.12）
                    Isolated {
                        if !recorder.volatileText.isEmpty {
                            HStack(alignment: .firstTextBaseline, spacing: 12) {
                                Text("…").frame(width: 52, alignment: .trailing).foregroundStyle(.tertiary)
                                // 跟定稿的行對齊：空出標記名字那一欄
                                if tagging { Color.clear.frame(width: 64, height: 0) }
                                Text(recorder.volatileText).foregroundStyle(.secondary).meetingText()
                            }
                            .id("volatile")
                            .onChange(of: recorder.volatileText.count) { _, _ in
                                guard followLatest else { return }
                                proxy.scrollTo("bottom", anchor: .bottom)
                            }
                        }
                    }
                    Color.clear.frame(height: 1).id("bottom")
                }
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            // 使用者往回看時不要自動捲動（R2.2）：看捲動的位置。往上捲（內容沒有變短）就不跟了，回到底部再跟。
            // 不用「底部的標記出現／消失」改狀態：那是在排版途中改，可能讓排版一直重來（design §25）
            .onScrollGeometryChange(for: LivePosition.self) { geometry in
                LivePosition(offset: geometry.contentOffset.y, content: geometry.contentSize.height,
                             bottom: geometry.visibleRect.maxY)
            } action: { old, new in
                if new.bottom >= new.content - 40 {
                    if !followLatest { followLatest = true }
                } else if new.offset < old.offset - 1 && new.content >= old.content {
                    if followLatest { followLatest = false }
                }
            }
            .onChange(of: recorder.liveLines.count) { _, _ in
                guard followLatest else { return }
                if reduceMotion { proxy.scrollTo("bottom", anchor: .bottom) }
                else { withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo("bottom", anchor: .bottom) } }
            }
            .overlay(alignment: .bottomTrailing) {
                if !followLatest {
                    Button("回到最新", systemImage: "arrow.down") {
                        proxy.scrollTo("bottom", anchor: .bottom)
                        followLatest = true
                    }
                    .padding(12)
                }
            }
        }
    }
}

/// 「正在說話」（design §24.2、R23.2）：誰在說話就按他的名字，標記現在這幾秒；＋ 加入與會者
private struct SpeakerTagBar: View {
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
        .font(.callout)
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

/// 即時逐字稿的一行（design §5.4）：時間、這段是誰說的（design §24.2、R23.1）、文字、重點
private struct LiveLineRow: View {
    @Environment(AppModel.self) private var model
    let line: Recorder.LiveLine
    let tagged: String?
    let roster: [String]
    let starred: Bool
    let tagging: Bool
    @State private var hovering = false
    @State private var naming = false

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(TimeFormat.string(line.start)).font(.callout.monospacedDigit()).foregroundStyle(Color.celadon)
                .frame(width: 52, alignment: .trailing)
            if tagging { tagMenu }
            Text(line.text).textSelection(.enabled).fixedSize(horizontal: false, vertical: true).meetingText()
            if starred {
                Image(systemName: "star.fill").foregroundStyle(Color.signal).font(.caption)
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
        .frame(width: 64, alignment: .leading)
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

/// 輸入說話者的名字（design §24.2）：Enter 或按鈕送出；下面列出還不在名單裡的認識的人，點了就用那個名字
private struct SpeakerNameForm: View {
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

/// 使用者筆記（R2.3）：換行時自動加上時間點，停下來 0.8 秒後存檔
struct UserNotesEditor: View {
    @Environment(AppModel.self) private var model
    let meetingId: Int64
    let initial: String
    let now: () -> Double?
    @State private var text = ""
    @State private var savedText = ""
    @State private var saveTask: Task<Void, Never>?

    var body: some View {
        TextEditor(text: $text).meetingText()
            .font(.body)
            .scrollContentBackground(.hidden)
            .padding(8)
            .background(Color.secondary.opacity(0.07), in: RoundedRectangle(cornerRadius: 8))
            .onAppear {
                text = initial
                savedText = initial
            }
            .onChange(of: text) { old, new in
                if let stamp = now().map({ "[\(TimeFormat.string($0))] " }) {
                    if old.isEmpty && !new.isEmpty && !new.hasPrefix("[") {
                        text = stamp + new
                        return
                    }
                    if new.count == old.count + 1 && new.hasSuffix("\n") {
                        text = new + stamp
                        return
                    }
                }
                guard new != savedText else { return }
                saveTask?.cancel()
                saveTask = Task {
                    try? await Task.sleep(for: .milliseconds(800))
                    guard !Task.isCancelled else { return }
                    save()
                }
            }
            .onDisappear {
                saveTask?.cancel()
                // 只有使用者改過才存，避免用舊內容蓋掉別處寫進去的筆記
                if text != savedText { save() }
            }
            // 別處改了筆記（例如匯入 Markdown 筆記）：換成新的內容，不然下一次存檔會蓋回舊的
            .onChange(of: initial) { _, new in
                guard new != savedText else { return }
                saveTask?.cancel()
                text = new
                savedText = new
            }
    }

    private func save() {
        savedText = text
        model.saveUserNotes(meetingId, text)
    }
}

/// 逐字稿頂部的「我的筆記」（R44.3，design §33.1）：預設收起，標籤寫有幾行；展開是錄音中同一個編輯器，播放時換行會加上播放時間。
/// 展開狀態只記這次選取期間（AppModel.userNotesExpanded，換會議收起）
struct UserNotesDisclosure: View {
    @Environment(AppModel.self) private var model
    let detail: MeetingDetail

    /// 有字的行數
    private var lineCount: Int {
        detail.meeting.userNotes.split(whereSeparator: \.isNewline).filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }.count
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Button {
                    withAnimation(.easeInOut(duration: 0.15)) { model.userNotesExpanded.toggle() }
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: "note.text").foregroundStyle(.secondary)
                        Text(lineCount > 0 ? String(localized: "我的筆記（\(lineCount) 行）") : String(localized: "寫筆記")).font(.callout)
                        Image(systemName: model.userNotesExpanded ? "chevron.up" : "chevron.down").font(.caption).foregroundStyle(.secondary)
                        Spacer(minLength: 0)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                if !detail.bookmarks.isEmpty {
                    Menu("重點標記 \(detail.bookmarks.count)") {
                        ForEach(detail.bookmarks) { bookmark in
                            Button("\(TimeFormat.string(bookmark.time)) \(bookmark.label)") { model.player.seek(to: bookmark.time) }
                        }
                    }
                    .fixedSize()
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 8)
            if model.userNotesExpanded {
                VStack(alignment: .leading, spacing: 8) {
                    Text("播放錄音時換行，會自動加上當下的播放時間。整理時 AI 會參考這些筆記；改完之後可以從「更多 → 重新處理」選「重新整理會議紀錄」。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    UserNotesEditor(meetingId: detail.meeting.id!, initial: detail.meeting.userNotes) {
                        model.player.isPlaying ? model.player.currentTime : nil
                    }
                    .frame(height: 180)
                    .id(detail.meeting.id)
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 12)
                .frame(maxWidth: 760, alignment: .leading)
            }
        }
    }
}

/// 即時逐字稿捲動的位置：捲了多少、內容多高、看得到的底部在哪
struct LivePosition: Equatable {
    var offset: CGFloat
    var content: CGFloat
    var bottom: CGFloat
}

/// 錄音的經過時間：在自己的 body 裡讀，整秒變了只重算這一個 Text（design §25）
struct RecorderClock: View {
    let recorder: Recorder
    var body: some View { Text(TimeFormat.string(Double(recorder.elapsedSeconds))).monospacedDigit() }
}

/// 錄音的音量條（design §25）：AppKit 的 view 自己定時讀音量，不經過 SwiftUI 的更新。
/// DEBUG 截圖（ImageRenderer 畫不出 AppKit 的 view）時用 SwiftUI 的 VUMeter
struct RecorderMeter: View {
    @Environment(\.snapshotMode) private var snapshotMode
    let recorder: Recorder
    let system: Bool
    var segments = 14

    var body: some View {
        if snapshotMode {
            VUMeter(level: system ? recorder.systemLevel : recorder.micLevel, segments: segments)
        } else {
            LevelMeter(segments: segments) { [recorder, system] in system ? recorder.systemLevel : recorder.micLevel }
        }
    }
}

/// 讓內容在自己的 body 裡算：裡面讀到、一直在變的資料（計時、音量、播放位置、還沒定稿的文字）
/// 只會讓這一塊重算，不會拖著外面整個畫面一起重算（design §21.12）
struct Isolated<Content: View>: View {
    @ViewBuilder let content: () -> Content
    var body: some View { content() }
}
