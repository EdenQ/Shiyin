import CryptoKit
import Foundation
import GRDB

/// F12.15 重新轉錄後名字跟著聲音（fork design §F12.9、DF15）。上游 `saveTranscript` 照編號沿用舊名字、不動這場的聲紋；
/// 重新分群會重新編號，同一個編號可能是別人。這裡改成用聲紋對應；存檔後重新學、刪對不上的舊聲紋、對不上的名字存成建議。
/// 待處理的結果、建議都存在 fork 的表（`ma_retranscribe_pending`、`ma_retranscribe_suggestion`），用說話者指紋確認是同一批說話者
enum ForkRetranscribe {
    /// 舊、新說話者雙向最像而且 ≥ 這個值才沿用名字：同一場重新轉錄前後同一個聲音 0.88～0.98，使用者的資料裡不同人最高 0.56～0.60（DF15）
    static let voiceThreshold = 0.80
    /// 對不上的名字要建議給「舊聲音最像的新說話者」的最低相似度（同上游 voiceprintThreshold）
    static let suggestThreshold = AppDatabase.voiceprintThreshold

    /// `ma_retranscribe_pending.payload`
    struct Payload: Codable {
        struct Mapped: Codable { var idx: Int; var name: String; var source: String }
        struct Unmatched: Codable { var name: String; var oldIdx: Int; var best: Int?; var score: Double }
        var mapped: [Mapped] = []
        var unmatched: [Unmatched] = []
    }

    struct DebugFailure: Error {}
    /// DEBUG 的模擬失敗（`mavoice retranscribe` 的 failSave、failLearn）
    static let debugFailSave = LockedValue(false)
    static let debugFailLearn = LockedValue(false)

    // MARK: 說話者指紋

    /// 這場所有說話者照編號排，「編號:聲紋的 base64（沒有就 -）」接起來的 SHA-256：改名不會變，重新轉錄、重新辨識、合併、編輯會議會變
    static func fingerprint(_ entries: [(idx: Int, embedding: Data?)]) -> String {
        let text = entries.sorted { $0.idx < $1.idx }.map { "\($0.idx):\($0.embedding?.base64EncodedString() ?? "-")" }.joined(separator: "\n")
        return SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    static func fingerprint(_ db: Database, _ meetingId: Int64) throws -> String {
        let rows = try Row.fetchAll(db, sql: "SELECT idx, embedding FROM speakers WHERE meeting_id = ?", arguments: [meetingId])
        return fingerprint(rows.map { (idx: $0["idx"] as Int, embedding: $0["embedding"] as Data?) })
    }

    static func fingerprint(_ rows: [SpeakerName]) -> String {
        fingerprint(rows.map { (idx: $0.idx, embedding: $0.embedding) })
    }

    // MARK: 存檔時（上游 saveTranscript 的交易裡）

    /// 上游 `saveTranscript` 算 `named` 的那一行（`// MA-FORK(F12)`）。回傳 [新編號: 舊說話者]，上游照這個沿用名字、name_source、person_id。
    /// db 是 saveTranscript 自己的寫入交易：待處理的結果跟著它一起提交或回滾（REV-F12c P2-2）
    static func named(_ db: Database, _ existing: [SpeakerName], voices: [Int: SpeakerVoice], count: Int) throws -> [Int: SpeakerName] {
        // 沒有舊說話者（匯入封包、匯入逐字稿、第一次轉錄）：跟上游一樣，不記錄
        guard let meetingId = existing.first?.meetingId else { return [:] }
        let keep = existing.filter { !AppDatabase.isDefaultSpeakerName($0.name) && $0.nameSource != "tag" }   // F2：標記的名字存完用標記重新對（F2.3）
        func oldVector(_ s: SpeakerName) -> [Float]? {
            guard let data = s.embedding, s.speechSeconds >= AppDatabase.voiceprintMinimumSeconds else { return nil }
            let v = Voiceprint.vector(data)
            return ForkVoiceSources.isValid(v) ? v : nil
        }
        let olds = existing.compactMap { s in oldVector(s).map { (s, $0) } }
        let news = voices.compactMap { idx, voice -> (Int, [Float])? in
            voice.seconds >= AppDatabase.voiceprintMinimumSeconds && ForkVoiceSources.isValid(voice.embedding) ? (idx, voice.embedding) : nil
        }
        var result: [Int: SpeakerName] = [:]
        var payload = Payload()
        var fallback: [SpeakerName] = []
        for old in keep {
            guard let vector = oldVector(old), !news.isEmpty else { fallback.append(old); continue }
            let scored = news.compactMap { idx, v in ForkVoiceSources.similarity(vector, v).map { (idx, $0) } }
            guard let best = scored.max(by: { $0.1 < $1.1 }) else { fallback.append(old); continue }
            let newVector = news.first { $0.0 == best.0 }!.1
            let back = olds.compactMap { s, v in ForkVoiceSources.similarity(v, newVector).map { (s.idx, $0) } }.max(by: { $0.1 < $1.1 })
            if best.1 >= voiceThreshold, back?.0 == old.idx, result[best.0] == nil {
                result[best.0] = old
                payload.mapped.append(.init(idx: best.0, name: old.name, source: old.nameSource))
            } else {
                payload.unmatched.append(.init(name: old.name, oldIdx: old.idx, best: best.0, score: best.1))
            }
        }
        // 沒有聲紋可比的照編號（上游）；那個編號已經被聲音對應用掉時不沿用
        for old in fallback where result[old.idx] == nil { result[old.idx] = old }
        // 存檔後的說話者指紋：上游接著照 1…count 重建說話者，聲紋是 voices 的
        let expected = fingerprint(stride(from: 1, through: count, by: 1).map { idx in
            (idx: idx, embedding: voices[idx].map { Voiceprint.data($0.embedding) })
        })
        let json = String(decoding: try JSONEncoder().encode(payload), as: UTF8.self)
        // 舊編號的建議不算數了；這次的結果等存檔後處理
        try db.execute(sql: "DELETE FROM ma_retranscribe_suggestion WHERE meeting_id = ?", arguments: [meetingId])
        try db.execute(sql: """
            INSERT OR REPLACE INTO ma_retranscribe_pending (meeting_id, fingerprint, payload, created_at) VALUES (?, ?, ?, ?)
            """, arguments: [meetingId, expected, json, Clock.now()])
        #if DEBUG
        if debugFailSave.value { debugFailSave.value = false; throw DebugFailure() }
        #endif
        return result
    }

    // MARK: 存檔後

    /// 存檔後（`ForkSpeakerTags.afterTranscription`，在 F2 套用標記之後、上游 matchVoiceprints 之前；啟動時 `retryAll` 也呼叫）。
    /// 沒有 pending、或指紋跟現在的說話者不合（重新辨識說話者、別的流程改過說話者）：刪掉 pending、不做事。
    /// 刪對不上的舊聲紋 → 重新學 → 存建議並消耗 pending，各自一筆交易、不巢狀；pending 到最後才消耗，任何一步失敗往上丟，
    /// pending 留著，重試時整個再做一次（每一步都可以重做；REV-F12c P2-3）
    static func after(_ app: AppDatabase, _ meetingId: Int64) throws {
        let loaded = try app.pool.read { db -> (payload: Payload, stored: String, current: String)? in
            guard let row = try Row.fetchOne(db, sql: "SELECT fingerprint, payload FROM ma_retranscribe_pending WHERE meeting_id = ?",
                                             arguments: [meetingId]) else { return nil }
            let payload = try JSONDecoder().decode(Payload.self, from: Data((row["payload"] as String).utf8))
            return (payload, row["fingerprint"], try fingerprint(db, meetingId))
        }
        guard let loaded else { return }
        guard loaded.stored == loaded.current else {
            try app.pool.write { db in try db.execute(sql: "DELETE FROM ma_retranscribe_pending WHERE meeting_id = ?", arguments: [meetingId]) }
            log.info("retranscribe names: pending for meeting \(meetingId) is for other speakers, dropped")
            return
        }
        // 1. 刪掉跟同編號新說話者對不上的舊聲紋（只比有效的向量；來源紀錄由外鍵一起刪）。要先刪：上游 learnVoiceprint 跟同一人
        //    既有的某份 > 0.95 就不存，舊編號那份還在時會擋掉新編號的學習。pending 到最後才消耗，之後的步驟失敗時重試會再學回來
        let removed = try app.pool.write { db -> Int in
            guard try fingerprint(db, meetingId) == loaded.stored else { return 0 }
            var removed = 0
            for row in try Row.fetchAll(db, sql: """
                SELECT v.id, v.embedding AS print, s.embedding AS current FROM voiceprints v
                JOIN speakers s ON s.meeting_id = v.meeting_id AND s.idx = v.speaker_idx WHERE v.meeting_id = ?
                """, arguments: [meetingId]) {
                guard let current = row["current"] as Data? else { continue }
                if let score = ForkVoiceSources.similarity(Voiceprint.vector(row["print"] as Data), Voiceprint.vector(current)),
                   score < ForkVoiceSources.unlikeThreshold {
                    try db.execute(sql: "DELETE FROM voiceprints WHERE id = ?", arguments: [row["id"] as Int64])
                    removed += 1
                }
            }
            return removed
        }
        // 2. 跟著聲音沿用的使用者取名，用新聲音重新學（同 rediarize；自動帶入的不學）。上游先刪這位說話者的聲紋再存，重做沒關係
        var relearned = 0
        if AppSettings.voiceprints {
            for item in loaded.payload.mapped.sorted(by: { $0.idx < $1.idx }) where item.source == "manual" || item.source == "suggestion" {
                ForkVoiceSources.noteNaming(meetingId, item.idx, source: "retranscribe")
                try app.learnVoiceprint(meetingId, idx: item.idx, name: item.name, source: item.source)
                relearned += 1
                #if DEBUG
                if debugFailLearn.value { debugFailLearn.value = false; throw DebugFailure() }
                #endif
            }
        }
        // 3. 一筆交易：存對不上的名字建議、消耗 pending
        let suggested = try app.pool.write { db -> Int in
            guard try fingerprint(db, meetingId) == loaded.stored else { return 0 }
            let language = try Meeting.fetchOne(db, key: meetingId)?.meetingLanguage ?? .zh
            let speakers = Dictionary(try SpeakerName.filter(Column("meeting_id") == meetingId).fetchAll(db).map { ($0.idx, $0) },
                                      uniquingKeysWith: { a, _ in a })
            var chosen = Set<Int>()
            func free(_ idx: Int?) -> Bool {
                guard let idx, let s = speakers[idx], !chosen.contains(idx) else { return false }
                return s.nameSource == "default" || s.nameSource == "voiceprint"
            }
            for item in loaded.payload.unmatched {
                let target = (item.score >= suggestThreshold && free(item.best)) ? item.best : (free(item.oldIdx) ? item.oldIdx : nil)
                guard let target else { continue }
                chosen.insert(target)
                try db.execute(sql: """
                    UPDATE speakers SET suggested_name = ?, suggestion_reason = ?, suggestion_time = NULL WHERE meeting_id = ? AND idx = ?
                    """, arguments: [item.name, reason(item.name, language: language), meetingId, target])
                try db.execute(sql: """
                    INSERT OR REPLACE INTO ma_retranscribe_suggestion (meeting_id, speaker_idx, name, fingerprint, created_at) VALUES (?, ?, ?, ?, ?)
                    """, arguments: [meetingId, target, item.name, loaded.stored, Clock.now()])
            }
            try db.execute(sql: "DELETE FROM ma_retranscribe_pending WHERE meeting_id = ?", arguments: [meetingId])
            return chosen.count
        }
        log.info("retranscribe names: \(loaded.payload.mapped.count) by voice, \(loaded.payload.unmatched.count) unmatched (\(suggested) suggested), \(removed) stale voiceprints removed, \(relearned) relearned")
    }

    /// 啟動時（`ForkStartup.install`）：上次沒處理完的逐場再做（存檔後 app 結束、學到一半失敗）
    static func retryAll(_ app: AppDatabase) {
        let ids = (try? app.pool.read { db in try Int64.fetchAll(db, sql: "SELECT meeting_id FROM ma_retranscribe_pending") }) ?? []
        for id in ids {
            do { try after(app, id) } catch { log.error("retranscribe names retry failed: \(error.logSummary, privacy: .public)") }
        }
    }

    // MARK: 顯示（ForkVoiceScores.annotate，上游 loadSpeakers 的接點）

    /// 對不上的舊名字建議：說話者換了（指紋不合）、使用者套用或改名、略過（suggested_name 清掉）就刪紀錄，不再出現；
    /// 被上游 matchVoiceprints 換成別人的建議時寫回；高信心自動帶名（name_source = voiceprint）時照樣放進建議清單（REV-F12c P2-1）
    static func present(_ detail: inout MeetingDetail, _ rows: [SpeakerName], app: AppDatabase) {
        guard let meetingId = detail.meeting.id else { return }
        do {
            let saved = try app.pool.read { db in
                try Row.fetchAll(db, sql: "SELECT speaker_idx, name, fingerprint FROM ma_retranscribe_suggestion WHERE meeting_id = ?",
                                 arguments: [meetingId])
            }
            guard !saved.isEmpty else { return }
            let current = fingerprint(rows)
            let language = detail.meeting.meetingLanguage
            var drop: [Int] = []
            var restore: [(Int, String)] = []
            for row in saved {
                let idx: Int = row["speaker_idx"], name: String = row["name"], stored: String = row["fingerprint"]
                guard stored == current, let speaker = rows.first(where: { $0.idx == idx }),
                      speaker.nameSource == "default" || speaker.nameSource == "voiceprint",
                      speaker.suggestedName != nil else {
                    drop.append(idx)
                    continue
                }
                if speaker.suggestedName != name { restore.append((idx, name)) }
                detail.speakerSuggestions[idx] = SpeakerNaming.Suggestion(speaker: idx, name: name, reason: reason(name, language: language), time: "")
            }
            if !drop.isEmpty || !restore.isEmpty {
                try app.pool.write { db in
                    for idx in drop {
                        try db.execute(sql: "DELETE FROM ma_retranscribe_suggestion WHERE meeting_id = ? AND speaker_idx = ?", arguments: [meetingId, idx])
                    }
                    for (idx, name) in restore {
                        try db.execute(sql: """
                            UPDATE speakers SET suggested_name = ?, suggestion_reason = ?, suggestion_time = NULL WHERE meeting_id = ? AND idx = ?
                            """, arguments: [name, reason(name, language: language), meetingId, idx])
                    }
                }
            }
        } catch {
            log.error("retranscribe suggestions failed: \(error.logSummary, privacy: .public)")
        }
    }

    /// 建議的原因（會議語言）
    static func reason(_ name: String, language: MeetingLanguage) -> String {
        language.format(zh: "重新轉錄前的名字：%@（聲音對不上，請確認）", en: "Name before re-transcribing: %@ (the voice didn't match; please check)",
                        ja: "再文字起こし前の名前：%@（声が一致しません。確認してください）", name)  // l10n-skip：會議語言的原因
    }

    /// 這種建議：時間空的，原因等於任何一種會議語言寫的那一句（改了會議語言也認得）
    static func isRetranscribeSuggestion(_ suggestion: SpeakerNaming.Suggestion) -> Bool {
        guard suggestion.time.isEmpty else { return false }
        return MeetingLanguage.allCases.contains { suggestion.reason == reason(suggestion.name, language: $0) }
    }
}
