import Foundation
import GRDB

/// 錄音中標記的說話者的存取（fork design §F2、F2.1～F2.5）：`extension AppDatabase`，上游的檔不放 fork 的查詢
extension AppDatabase {
    func speakerTags(_ meetingId: Int64) throws -> [SpeakerTag] {
        try pool.read { db in try SpeakerTag.filter(Column("meeting_id") == meetingId).order(Column("id")).fetchAll(db) }
    }

    /// 標記即時逐字稿的一行：先刪掉這一行有的標記（中間點在這一行裡的），改名字才不會留下兩個名字
    func tagLine(_ meetingId: Int64, start: Double, end: Double, name: String) throws {
        try pool.write { db in
            try Self.deleteLineTags(db, meetingId: meetingId, start: start, end: end)
            var tag = SpeakerTag(meetingId: meetingId, start: start, end: end, name: name, kind: "line")
            try tag.insert(db)
        }
    }

    func clearLineTags(_ meetingId: Int64, start: Double, end: Double) throws {
        try pool.write { db in try Self.deleteLineTags(db, meetingId: meetingId, start: start, end: end) }
    }

    private static func deleteLineTags(_ db: Database, meetingId: Int64, start: Double, end: Double) throws {
        try db.execute(sql: "DELETE FROM speaker_tags WHERE meeting_id = ? AND (start + \"end\") / 2 BETWEEN ? AND ?",
                       arguments: [meetingId, start, end])
    }

    /// 「正在說話」：標記按下前 3 秒到後 1 秒；前一個「正在說話」的中間點差不到 2 秒就取代它（按錯馬上改）
    func tagNow(_ meetingId: Int64, at time: Double, name: String) throws {
        let range = SpeakerTagging.nowRange(at: time)
        try pool.write { db in
            try db.execute(sql: "DELETE FROM speaker_tags WHERE meeting_id = ? AND kind = 'now' AND abs((start + \"end\") / 2 - ?) < ?",
                           arguments: [meetingId, (range.start + range.end) / 2, SpeakerTagging.nowReplaceWithin])
            var tag = SpeakerTag(meetingId: meetingId, start: range.start, end: range.end, name: name, kind: "now")
            try tag.insert(db)
        }
    }

    func addSpeakerTag(_ meetingId: Int64, start: Double, end: Double, name: String, kind: String = "line") throws {
        try pool.write { db in
            var tag = SpeakerTag(meetingId: meetingId, start: start, end: end, name: name, kind: kind)
            try tag.insert(db)
        }
    }

    func deleteSpeakerTag(_ id: Int64) throws {
        _ = try pool.write { db in try SpeakerTag.deleteOne(db, key: id) }
    }

    /// 與會者加一個名字（fork design §F2.2）：已經有了就不加，分隔符號跟原本的一樣
    func addParticipant(_ meetingId: Int64, name: String) throws {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return }
        try pool.write { db in
            guard var m = try Meeting.fetchOne(db, key: meetingId),
                  !m.participantList.contains(where: { SpeakerTagging.sameName($0, name) }) else { return }
            let existing = m.participants.trimmingCharacters(in: .whitespaces)
            let separator = existing.contains("、") ? "、" : existing.contains("，") ? "，" : ", "  // l10n-skip
            m.participants = existing.isEmpty ? name : existing + separator + name
            m.updatedAt = Clock.now()
            try m.update(db)
        }
    }

    /// 錄完套用標記（fork design §F2.3）：轉錄存檔後、聲紋比對前。名字還是預設的說話者，對上他的標記都是同一個名字，
    /// 就改成那個名字（name_source = tag）。回傳套用了的說話者，學聲紋由呼叫的人做（要看設定）
    func applySpeakerTags(_ meetingId: Int64) throws -> [(idx: Int, name: String)] {
        try pool.write { db in
            let tags = try SpeakerTag.filter(Column("meeting_id") == meetingId).order(Column("id")).fetchAll(db)
            guard !tags.isEmpty else { return [] }
            let segments = try Segment.filter(Column("meeting_id") == meetingId && Column("kind") == "final").fetchAll(db)
            let candidates = try Int.fetchAll(db, sql: "SELECT idx FROM speakers WHERE meeting_id = ? AND name_source = 'default'",
                                              arguments: [meetingId])
            let names = SpeakerTagging.names(for: tags.map(\.tag), in: segments, candidates: Set(candidates))
            for (idx, name) in names {
                try db.execute(sql: "UPDATE speakers SET name = ?, name_source = 'tag' WHERE meeting_id = ? AND idx = ?",
                               arguments: [name, meetingId, idx])
            }
            return names.sorted { $0.key < $1.key }.map { (idx: $0.key, name: $0.value) }
        }
    }

    /// 用標記帶入的名字要不要存聲紋（fork design §F2.3、DF2）：說話者辨識沒有提示可能把不同的人併成一位才存
    func rememberTaggedVoices(_ meetingId: Int64) throws -> Bool {
        !(try meeting(meetingId)?.mayHaveMergedSpeakers ?? false)
    }

    /// 「只改這句」（F2.12）：to 是 nil 時新增一位說話者、改成標記的名字（算手動改的）。跟 5.0.1 一樣在同一筆交易裡做完：
    /// 復原快照、新增、命名、句子歸屬、拿掉空的說話者，任何一步失敗整筆回復（DF8）。to 不是 nil 或沒有名字時就是上游的 `reassignSegments`
    @discardableResult
    func reassignSegments(_ meetingId: Int64, ids: [Int64], to idx: Int?, naming name: String?, label: String) throws -> Int {
        guard idx == nil, let name else { return try reassignSegments(meetingId, ids: ids, to: idx, label: label) }
        return try pool.write { db in
            try Self.forkSaveSpeakerUndo(db, meetingId: meetingId, label: label)
            let target = try Self.forkAddSpeaker(db, meetingId: meetingId)
            try ForkSpeakerTags.nameNewSpeaker(db, meetingId: meetingId, idx: target, name: name)
            // 跟上游 reassignSegments 的迴圈相同（DF8 的複本）
            for id in ids {
                try db.execute(sql: "UPDATE segments SET speaker = ?, speaker_manual = 1 WHERE id = ? AND meeting_id = ?",
                               arguments: [target, id, meetingId])
            }
            try Self.removeEmptySpeakers(db, meetingId: meetingId)
            return target
        }
    }

    #if DEBUG
    /// shiyinctl applytags：用標記帶入的名字先回到預設名稱，等於重新轉錄存檔時（fork design §F2.5）
    func resetTaggedSpeakers(_ meetingId: Int64) throws {
        try pool.write { db in
            let language = try Meeting.fetchOne(db, key: meetingId)?.meetingLanguage ?? .zh
            for idx in try Int.fetchAll(db, sql: "SELECT idx FROM speakers WHERE meeting_id = ? AND name_source = 'tag'", arguments: [meetingId]) {
                try db.execute(sql: "UPDATE speakers SET name = ?, name_source = 'default', person_id = NULL WHERE meeting_id = ? AND idx = ?",
                               arguments: [language.defaultSpeaker(idx), meetingId, idx])  // l10n-skip
            }
        }
    }
    #endif
}

extension ForkSpeakerTags {
    /// 上游 Voiceprints.learnVoiceprint 的接點：標記帶入的名字（source = tag），說話者辨識可能把人併在一起時
    /// 只連到那個人、不存聲紋（F2.9、DF2）；其他來源照上游。
    /// F12：要存時交給 `ForkVoiceSources.willStore`（記來源；防呆選了「只改名」回 false，fork design §F12.3、§F12.4）
    static func remembersVoice(_ db: Database, meetingId: Int64, idx: Int, source: String) throws -> Bool {
        if source == "tag", try Meeting.fetchOne(db, key: meetingId)?.mayHaveMergedSpeakers ?? false {
            ForkVoiceSources.skip(meetingId, idx)
            return false
        }
        return ForkVoiceSources.willStore(db, meetingId: meetingId, idx: idx, source: source)
    }

    /// 上游 JobRunner 轉錄存檔、重新辨識說話者之後的接點（F2.3、F2.10）：在聲紋比對之前套用，使用者自己標的優先；
    /// 跟手動改名一樣記住聲紋，但說話者辨識可能把人併在一起時只連到認識的人、不存聲紋（F2.9）。setSpeakerCheck 要先寫好
    static func applyTags(_ db: AppDatabase, _ meetingId: Int64) throws {
        let tagged = try db.applySpeakerTags(meetingId)
        guard !tagged.isEmpty else { return }
        let remember = try db.rememberTaggedVoices(meetingId)
        log.info("speaker tags applied to \(tagged.count) speakers, voiceprints \(remember ? "kept" : "skipped", privacy: .public)")
        if AppSettings.voiceprints {
            for (idx, name) in tagged {
                ForkVoiceSources.noteTagging(meetingId, idx)   // F12：來源記成「錄音時標記」
                try db.learnVoiceprint(meetingId, idx: idx, name: name, source: "tag")
            }
        }
    }

    /// 套用失敗不影響逐字稿和之後的整理，只記 log
    static func afterTranscription(_ db: AppDatabase, _ meetingId: Int64) {
        do { try applyTags(db, meetingId) } catch { log.error("apply speaker tags failed: \(error.logSummary, privacy: .public)") }
        // F12.15：重新轉錄後刪對不上的舊聲紋、沿用的名字重新學、對不上的名字存成建議（只處理 saveTranscript 記下結果的會議）
        do { try ForkRetranscribe.after(db, meetingId) } catch { log.error("retranscribe names failed: \(error.logSummary, privacy: .public)") }
    }
}
