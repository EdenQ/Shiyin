import AppKit
import Foundation

extension ForkSpeakerTags {
    /// 選取中的會議的標記（MeetingDetail 的 `forkTags`，`// MA-FORK(F2)`）：依標記的先後；每個標記對上的說話者、逐字稿上的位置
    struct DetailState: Equatable {
        var tags: [SpeakerTag] = []
        var matches: [Int64: SpeakerTagging.Match] = [:]

        /// 上游 `MeetingDetail.buildIndexes` 的接點：段落、標記變了重算
        mutating func rebuild(_ segments: [Segment]) {
            matches = Dictionary(uniqueKeysWithValues: tags.compactMap { tag in
                tag.id.map { ($0, SpeakerTagging.match(tag.tag, in: segments)) }
            })
        }
    }
}

extension MeetingDetail {
    /// 錄音中標記的說話者（fork design §F2），依標記的先後
    var speakerTags: [SpeakerTag] {
        get { forkTags.tags }
        set { forkTags.tags = newValue }
    }

    /// 每個標記對上的說話者、逐字稿上的位置（buildIndexes 算）
    var tagMatches: [Int64: SpeakerTagging.Match] { forkTags.matches }

    /// 「正在說話」的名單：與會者，接著是標過的名字（fork design §F2.2）
    var tagRoster: [String] {
        SpeakerTagging.roster(participants: meeting.participantList, tagged: speakerTags.map(\.name))
    }

    /// 即時逐字稿的一行有的標記：中間點落在這一行裡的，有好幾個時用最後標的（fork design §F2.2）
    func liveTag(start: Double, end: Double) -> SpeakerTag? {
        speakerTags.last { SpeakerTagging.belongs($0.tag, toLine: start, end) }
    }

    /// 錄音時標記、沒套用的名字（fork design §F2.4）：逐字稿上那一段的說話者現在的名字跟標記不同。依時間排
    var unappliedTags: [SpeakerTag] {
        speakerTags.filter(isUnapplied).sorted { $0.start < $1.start }
    }

    func unappliedTags(on segmentId: Int64?) -> [SpeakerTag] {
        guard let segmentId else { return [] }
        return speakerTags.filter { tag in tag.id.flatMap { tagMatches[$0]?.segmentId } == segmentId && isUnapplied(tag) }
    }

    func isUnapplied(_ tag: SpeakerTag) -> Bool {
        guard let id = tag.id, let idx = tagMatches[id]?.segmentSpeaker else { return false }
        return !SpeakerTagging.sameName(speakerName(idx) ?? "", tag.name)
    }

    /// 「只改這句」改哪幾句（fork design §F2.4、F2.12）
    func taggedSegments(_ tag: SpeakerTag) -> [Int64] {
        guard let id = tag.id, let match = tagMatches[id] else { return [] }
        return SpeakerTagging.covered(tag.tag, by: match, in: segments)
    }

    /// 這場名字跟 name 一樣的說話者（不分大小寫），except 那位不算
    func speaker(named name: String, except idx: Int?) -> Int? {
        speakers.keys.sorted().first { $0 != idx && SpeakerTagging.sameName(speakers[$0] ?? "", name) }
    }
}

extension AppModel.DetailParts {
    /// 錄音中標記的說話者（上游用到 1 << 5，fork 從 1 << 6 起）
    static let speakerTags = AppModel.DetailParts(rawValue: 1 << 6)
}

// MARK: 錄音中標記說話者（fork design §F2）

extension AppModel {
    var knownPeople: [String] {
        get { fork.knownPeople }
        set { fork.knownPeople = newValue }
    }

    func refreshKnownPeople() {
        knownPeople = (try? db.peopleNames()) ?? []
    }

    /// 「正在說話」的名字：標記現在這幾秒。標記的名字不加進與會者，打錯、清除之後就不會留下（fork design §F2.2）
    func tagSpeakerNow(_ name: String) {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let id = recorder.meetingId, !recorder.isPaused, !name.isEmpty else { return }
        let time = recorder.elapsed
        perform(.detail([.speakerTags])) { try db.tagNow(id, at: time, name: name) }
        noticeMessage = String(localized: "已標記 \(TimeFormat.string(time)) 是\(name)在說話")
    }

    /// 標記即時逐字稿的一行（換成別人也是這個）
    func tagLiveLine(_ line: Recorder.LiveLine, as name: String) {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let id = recorder.meetingId, !name.isEmpty else { return }
        perform(.detail([.speakerTags])) { try db.tagLine(id, start: line.start, end: line.end, name: name) }
    }

    func clearLiveLineTag(_ line: Recorder.LiveLine) {
        guard let id = recorder.meetingId else { return }
        perform(.detail([.speakerTags])) { try db.clearLineTags(id, start: line.start, end: line.end) }
    }

    /// 「正在說話」那一排的 ＋：加進與會者
    func addParticipant(_ name: String) {
        guard let id = recorder.meetingId ?? selection else { return }
        perform(.detail([.meeting])) { try db.addParticipant(id, name: name) }
    }

    /// 錄完：刪掉沒套用的標記（fork design §F2.4）
    func deleteSpeakerTag(_ id: Int64) {
        perform(.detail([.speakerTags])) { try db.deleteSpeakerTag(id) }
    }

    /// 沒套用的標記「只改這句」（F2.12，fork design §F2.4）：標記蓋到的句子改給叫這個名字的說話者，沒有就新增一位
    func reassignTaggedSegments(_ tag: SpeakerTag) {
        guard let id = selection, let detail else { return }
        if let problem = speakerEditProblem(id) {
            noticeMessage = problem
            return
        }
        let ids = detail.taggedSegments(tag)
        guard let tagId = tag.id, !ids.isEmpty else { return }
        let name = tag.name.trimmingCharacters(in: .whitespacesAndNewlines)
        let target = detail.speaker(named: name, except: detail.tagMatches[tagId]?.segmentSpeaker)
        let label = ids.count == 1 ? String(localized: "把一句改成「\(name)」說的")
                                   : String(localized: "把 \(ids.count) 句改成「\(name)」說的")
        perform(.detail([.speakers, .segments])) {
            try db.reassignSegments(id, ids: ids, to: target, naming: target == nil ? name : nil, label: label)
        }
    }

    #if DEBUG
    var debugTagUI: String? {
        get { fork.debugTagUI }
        set { fork.debugTagUI = newValue }
    }

    /// shiyinctl applytags：等於重新轉錄存檔後那幾步：標記帶入的名字回到預設、套用標記、聲紋比對（fork design §F2.5）
    func debugApplyTags(_ id: Int64) {
        perform(.detail([.speakers, .meeting])) {
            try db.resetTaggedSpeakers(id)
            try ForkSpeakerTags.applyTags(db, id)
            if AppSettings.voiceprints { try db.matchVoiceprints(id) }
        }
    }
    #endif
}
