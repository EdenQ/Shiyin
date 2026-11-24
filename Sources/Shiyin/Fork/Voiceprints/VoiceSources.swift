import Foundation
import GRDB

/// F12 聲紋的來源紀錄、人物頁的資料、刪單份聲紋（fork design §F12.4～§F12.6、DF14）。
/// 唯一的接點 `remembersVoice` 在上游 INSERT 之前，拿不到新聲紋的 id：先寫 `ma_voiceprint_pending`，事後 `resolve` 對到 id
enum ForkVoiceSources {
    /// 使用者取名（`ForkVoiceGuard.holds` 記下）、F2 套用標記：之後 `willStore` 用來判斷來源
    struct Intent {
        var source: String
        var warned = false
        var noVoice = false
        var at = Date()
    }

    /// 記憶體裡的取名、標記：主執行緒寫、資料庫的寫入佇列讀（同 DF5，短暫拿鎖），60 秒內有效、用一次就拿掉
    private static let lock = NSLock()
    nonisolated(unsafe) private static var intents: [String: Intent] = [:]
    static let intentLifetime: TimeInterval = 60

    static func key(_ meetingId: Int64, _ idx: Int) -> String { "\(meetingId)-\(idx)" }

    static func noteNaming(_ meetingId: Int64, _ idx: Int, source: String, warned: Bool = false, noVoice: Bool = false) {
        let intent = Intent(source: source, warned: warned, noVoice: noVoice)
        lock.withLock { intents[key(meetingId, idx)] = intent }
    }

    /// F2 套用標記時（`ForkSpeakerTags.applyTags`）
    static func noteTagging(_ meetingId: Int64, _ idx: Int) {
        lock.withLock { intents[key(meetingId, idx)] = Intent(source: "tag") }
    }

    private static func takeIntent(_ meetingId: Int64, _ idx: Int) -> Intent? {
        let now = Date()
        return lock.withLock {
            let found = intents.removeValue(forKey: key(meetingId, idx))
            intents = intents.filter { now.timeIntervalSince($0.value.at) < intentLifetime }
            guard let found, now.timeIntervalSince(found.at) < intentLifetime else { return nil }
            return found
        }
    }

    /// F2 不存聲紋時（標記、說話者可能併在一起）：取名的紀錄也拿掉
    static func skip(_ meetingId: Int64, _ idx: Int) { _ = takeIntent(meetingId, idx) }

    /// 上游 `learnVoiceprint` 的 `remembersVoice` 接點（經過 F2 之後）：在同一筆寫入交易裡、INSERT 之前。
    /// 回 false 不存聲紋（防呆選了「只改名」）；要存時記下來源（pending），事後對到 id
    static func willStore(_ db: Database, meetingId: Int64, idx: Int, source: String) -> Bool {
        let intent = takeIntent(meetingId, idx)
        if intent?.noVoice == true { return false }
        do {
            try resolve(db)
            let kind: String
            if let intent { kind = intent.source }
            else if try Bool.fetchOne(db, sql: """
                SELECT EXISTS (SELECT 1 FROM jobs WHERE meeting_id = ? AND kind = 'rediarize' AND status = 'running')
                """, arguments: [meetingId]) == true { kind = "rediarize" }
            else { kind = "merge" }   // 上游 mergeSpeaker 合併後用合併的聲紋重新學
            try db.execute(sql: """
                INSERT OR REPLACE INTO ma_voiceprint_pending (meeting_id, speaker_idx, source, warned, recorded_at) VALUES (?, ?, ?, ?, ?)
                """, arguments: [meetingId, idx, kind, intent?.warned == true ? 1 : 0, Clock.now()])
        } catch {
            // 來源記不起來不影響上游存聲紋（顯示「不明」）
            log.error("voiceprint source not recorded: \(error.logSummary, privacy: .public)")
        }
        return true
    }

    /// pending 對到聲紋的 id：同一場、同一位說話者、在記下之後存的、還沒有來源的非 enroll 聲紋
    static func resolve(_ db: Database) throws {
        guard try Bool.fetchOne(db, sql: "SELECT EXISTS (SELECT 1 FROM ma_voiceprint_pending)") == true else { return }
        try db.execute(sql: """
            INSERT OR IGNORE INTO ma_voiceprint_source (voiceprint_id, source, warned, recorded_at)
              SELECT v.id, p.source, p.warned, p.recorded_at FROM voiceprints v
              JOIN ma_voiceprint_pending p ON p.meeting_id = v.meeting_id AND p.speaker_idx = v.speaker_idx
              WHERE v.audio_source <> 'enroll' AND v.created_at >= p.recorded_at
                AND v.id NOT IN (SELECT voiceprint_id FROM ma_voiceprint_source);
            DELETE FROM ma_voiceprint_pending WHERE EXISTS (
              SELECT 1 FROM voiceprints v JOIN ma_voiceprint_source s ON s.voiceprint_id = v.id
              WHERE v.meeting_id = ma_voiceprint_pending.meeting_id AND v.speaker_idx = ma_voiceprint_pending.speaker_idx
                AND s.recorded_at = ma_voiceprint_pending.recorded_at);
            """)
    }

    static func resolveIfNeeded(_ app: AppDatabase) {
        do {
            guard try app.pool.read({ db in
                try Bool.fetchOne(db, sql: "SELECT EXISTS (SELECT 1 FROM ma_voiceprint_pending)") ?? false
            }) else { return }
            try app.pool.write { db in try resolve(db) }
        } catch {
            log.error("voiceprint source resolve failed: \(error.logSummary, privacy: .public)")
        }
    }

    // MARK: 人物頁（§F12.5）

    struct PrintRow: Identifiable, Equatable {
        var id: Int64
        var createdAt: String
        var meetingId: Int64?
        var meetingTitle: String?
        var meetingTrashed = false
        var enrolled: Bool
        /// manual / suggestion / tag / merge / rediarize；nil 是不明（F12 之前存的）
        var source: String?
        var warned: Bool
        /// 跟這個人其他樣本最像的；nil 是只有這一份
        var ownBest: Double?
        /// 別人裡最像的
        var other: ForkVoiceScores.Ranked?

        /// 跟這個人其他樣本不像（< 0.50 或只有這一份），而且跟別人很像（≥ 0.88）：同防呆的門檻（§F12.3）
        var suspicious: Bool {
            guard let other, other.score >= ForkVoiceGuard.otherThreshold else { return false }
            return (ownBest ?? -1) < ForkVoiceGuard.targetThreshold
        }
    }

    static func rows(_ app: AppDatabase, personId: Int64) throws -> [PrintRow] {
        resolveIfNeeded(app)
        return try app.pool.read { db in
            let prints = try ForkVoiceScores.library(db)
            let names = try ForkVoiceScores.names(db)
            let others = prints.filter { $0.personId != personId }
            let mine = prints.filter { $0.personId == personId }
            var sources: [Int64: (String, Bool)] = [:]
            for r in try Row.fetchAll(db, sql: """
                SELECT s.voiceprint_id, s.source, s.warned FROM ma_voiceprint_source s JOIN voiceprints v ON v.id = s.voiceprint_id
                WHERE v.person_id = ?
                """, arguments: [personId]) {
                sources[r["voiceprint_id"]] = (r["source"], (r["warned"] as Int) != 0)
            }
            return try mine.sorted { $0.id > $1.id }.map { print in
                var row = PrintRow(id: print.id, createdAt: print.createdAt, meetingId: print.meetingId,
                                   enrolled: print.audioSource == "enroll", source: sources[print.id]?.0, warned: sources[print.id]?.1 ?? false)
                if let meetingId = print.meetingId, let meeting = try Meeting.fetchOne(db, key: meetingId) {
                    row.meetingTitle = meeting.displayTitle
                    row.meetingTrashed = meeting.deletedAt != nil
                }
                row.ownBest = mine.filter { $0.id != print.id }.map { Voiceprint.similarity(print.vector, $0.vector) }.max()
                row.other = ForkVoiceScores.rank(print.vector, prints: others, names: names, excluding: nil).first
                return row
            }
        }
    }

    /// 刪單份聲紋（§F12.5）：只刪這一份，來源紀錄由外鍵一起刪；這個人和會議裡的名字不變（不呼叫 deleteOrphanPeople）。
    /// 錄的「我的聲音」不在這裡刪（設定的「我的聲音」管理）。回傳有沒有刪到
    @discardableResult
    static func delete(_ app: AppDatabase, voiceprintId: Int64) throws -> Bool {
        try app.pool.write { db in
            try db.execute(sql: "DELETE FROM voiceprints WHERE id = ? AND audio_source <> 'enroll'", arguments: [voiceprintId])
            return db.changesCount > 0
        }
    }

    /// 來源的文字（介面語言）
    static func label(_ row: PrintRow) -> String {
        if row.enrolled { return String(localized: "錄「我的聲音」") }
        switch row.source {
        case "manual": return String(localized: "手動取名")
        case "suggestion": return String(localized: "套用建議")
        case "tag": return String(localized: "錄音時標記")
        case "merge": return String(localized: "合併說話者")
        case "rediarize": return String(localized: "重新辨識說話者")
        default: return String(localized: "不明")
        }
    }
}
