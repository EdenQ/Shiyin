import Foundation
import GRDB

/// F12.15 重新轉錄後名字跟著聲音（fork design §F12.9、DF15）。上游 `saveTranscript` 照編號沿用舊名字、不動這場的聲紋；
/// 重新分群會重新編號，同一個編號可能是別人。這裡改成用聲紋對應，存檔後刪對不上的舊聲紋、重新學、對不上的名字存成建議
enum ForkRetranscribe {
    /// 舊、新說話者雙向最像而且 ≥ 這個值才沿用名字：同一場重新轉錄前後同一個聲音 0.88～0.98，使用者的資料裡不同人最高 0.56～0.60（DF15）
    static let voiceThreshold = 0.80
    /// 對不上的名字要建議給「舊聲音最像的新說話者」的最低相似度（同上游 voiceprintThreshold）
    static let suggestThreshold = AppDatabase.voiceprintThreshold

    /// `named` 記下的結果，給存檔後的 `after` 用（同一個寫入流程裡先後，記憶體就夠）
    struct Outcome {
        /// 跟著聲音沿用名字的新編號 → 舊說話者
        var voiceMapped: [Int: SpeakerName] = [:]
        /// 聲音對不上的舊說話者，和舊聲音最像的新編號、相似度
        var unmatched: [(old: SpeakerName, best: Int?, score: Double)] = []
    }
    private static let outcomes = LockedValue<[Int64: Outcome]>([:])
    /// 存成建議、等著在 annotate 補回一次的（會議 → 編號 → 名字）
    private static let restores = LockedValue<[Int64: [Int: String]]>([:])

    /// 上游 `saveTranscript` 算 `named` 的那一行（`// MA-FORK(F12)`，原本是 F2 的 `existing.filter { 不是預設名稱 && 不是 tag }` 照編號）。
    /// 回傳 [新編號: 舊說話者]，上游照這個沿用名字、name_source、person_id
    static func named(_ existing: [SpeakerName], voices: [Int: SpeakerVoice]) -> [Int: SpeakerName] {
        let keep = existing.filter { !AppDatabase.isDefaultSpeakerName($0.name) && $0.nameSource != "tag" }   // F2：標記的名字存完用標記重新對（F2.3）
        // 沒有舊說話者（匯入封包、匯入逐字稿、第一次轉錄）：跟上游一樣，不記錄
        guard let meetingId = existing.first?.meetingId else { return [:] }
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
        var outcome = Outcome()
        var fallback: [SpeakerName] = []
        for old in keep {
            guard let vector = oldVector(old), !news.isEmpty else { fallback.append(old); continue }
            let scored = news.compactMap { idx, v in ForkVoiceSources.similarity(vector, v).map { (idx, $0) } }
            guard let best = scored.max(by: { $0.1 < $1.1 }) else { fallback.append(old); continue }
            let newVector = news.first { $0.0 == best.0 }!.1
            let back = olds.compactMap { s, v in ForkVoiceSources.similarity(v, newVector).map { (s.idx, $0) } }.max(by: { $0.1 < $1.1 })
            if best.1 >= voiceThreshold, back?.0 == old.idx, result[best.0] == nil {
                result[best.0] = old
                outcome.voiceMapped[best.0] = old
            } else {
                outcome.unmatched.append((old, best.0, best.1))
            }
        }
        // 沒有聲紋可比的照編號（上游）；那個編號已經被聲音對應用掉時不沿用
        for old in fallback where result[old.idx] == nil { result[old.idx] = old }
        outcomes.value[meetingId] = outcome
        return result
    }

    /// 存檔後（`ForkSpeakerTags.afterTranscription`，在 F2 套用標記之後、上游 matchVoiceprints 之前）。只處理 `named` 記下結果的會議：
    /// 重新辨識說話者、匯入不經過這裡的記錄
    static func after(_ app: AppDatabase, _ meetingId: Int64) throws {
        var all = outcomes.value
        guard let outcome = all.removeValue(forKey: meetingId) else { return }
        outcomes.value = all
        // 1. 跟同編號新說話者對不上的舊聲紋刪掉（只比有效的向量；來源紀錄由外鍵一起刪）
        let removed = try app.pool.write { db -> Int in
            var count = 0
            for row in try Row.fetchAll(db, sql: """
                SELECT v.id, v.embedding AS print, s.embedding AS current FROM voiceprints v
                JOIN speakers s ON s.meeting_id = v.meeting_id AND s.idx = v.speaker_idx WHERE v.meeting_id = ?
                """, arguments: [meetingId]) {
                guard let current = row["current"] as Data? else { continue }
                if let score = ForkVoiceSources.similarity(Voiceprint.vector(row["print"] as Data), Voiceprint.vector(current)),
                   score < ForkVoiceSources.unlikeThreshold {
                    try db.execute(sql: "DELETE FROM voiceprints WHERE id = ?", arguments: [row["id"] as Int64])
                    count += 1
                }
            }
            return count
        }
        // 2. 跟著聲音沿用的使用者取名，用新聲音重新學（同 rediarize；自動帶入的不學）
        var relearned = 0
        if AppSettings.voiceprints {
            for (idx, old) in outcome.voiceMapped.sorted(by: { $0.key < $1.key }) where old.nameSource == "manual" || old.nameSource == "suggestion" {
                ForkVoiceSources.noteNaming(meetingId, idx, source: "retranscribe")
                try app.learnVoiceprint(meetingId, idx: idx, name: old.name, source: old.nameSource)
                relearned += 1
            }
        }
        // 3. 對不上的舊名字存成建議（會議語言），記下來給 annotate 補回一次
        var suggested: [Int: String] = [:]
        try app.pool.write { db in
            let language = try Meeting.fetchOne(db, key: meetingId)?.meetingLanguage ?? .zh
            let speakers = Dictionary(try SpeakerName.filter(Column("meeting_id") == meetingId).fetchAll(db).map { ($0.idx, $0) },
                                      uniquingKeysWith: { a, _ in a })
            func free(_ idx: Int?) -> Bool {
                guard let idx, let s = speakers[idx] else { return false }
                return s.nameSource == "default" && s.suggestedName == nil && suggested[idx] == nil
            }
            for item in outcome.unmatched {
                let target = (item.score >= suggestThreshold && free(item.best)) ? item.best : (free(item.old.idx) ? item.old.idx : nil)
                guard let target else { continue }
                try db.execute(sql: """
                    UPDATE speakers SET suggested_name = ?, suggestion_reason = ?, suggestion_time = NULL WHERE meeting_id = ? AND idx = ?
                    """, arguments: [item.old.name, reason(item.old.name, language: language), meetingId, target])
                suggested[target] = item.old.name
            }
        }
        if !suggested.isEmpty { restores.value[meetingId] = suggested }
        log.info("retranscribe names: \(outcome.voiceMapped.count) by voice, \(outcome.unmatched.count) unmatched (\(suggested.count) suggested), \(removed) stale voiceprints removed, \(relearned) relearned")
    }

    /// `ForkVoiceScores.annotate`（讀說話者的接點）：上游 matchVoiceprints 把對不上的名字的建議換掉時補回一次；補過或不用補都拿掉記錄
    static func restoreSuggestions(_ detail: inout MeetingDetail, _ rows: [SpeakerName], app: AppDatabase) {
        guard let meetingId = detail.meeting.id else { return }
        var all = restores.value
        guard let pending = all.removeValue(forKey: meetingId) else { return }
        restores.value = all
        let language = detail.meeting.meetingLanguage
        for (idx, name) in pending {
            guard let row = rows.first(where: { $0.idx == idx }), row.nameSource == "default", row.suggestedName != name else { continue }
            let text = reason(name, language: language)
            do {
                try app.pool.write { db in
                    try db.execute(sql: """
                        UPDATE speakers SET suggested_name = ?, suggestion_reason = ?, suggestion_time = NULL WHERE meeting_id = ? AND idx = ? AND name_source = 'default'
                        """, arguments: [name, text, meetingId, idx])
                }
                detail.speakerSuggestions[idx] = SpeakerNaming.Suggestion(speaker: idx, name: name, reason: text, time: "")
            } catch {
                log.error("retranscribe suggestion restore failed: \(error.logSummary, privacy: .public)")
            }
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
