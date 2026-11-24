import Foundation
import GRDB

/// F12 改名防呆（fork design §F12.3、DF13）：使用者幫說話者取名前，聲音明顯是另一位認識的人、
/// 跟取的名字既有的樣本又都不像時，先擋下來問「仍要存／只改名，不記住聲音／取消」
@MainActor
enum ForkVoiceGuard {
    /// 別人「很像」：上游自動帶入的門檻
    nonisolated static let otherThreshold = AppDatabase.voiceprintAutoThreshold
    /// 跟取的名字「不像」：上游 AMI 評估裡同一個人最低 0.81、不同的人最高 0.42 之間（design §21.4.1）
    nonisolated static let targetThreshold = 0.50

    /// 擋下、等使用者回答的一位
    struct Item: Identifiable, Equatable {
        var meetingId: Int64
        var idx: Int
        /// 現在的名字（例如「說話者 6」）
        var current: String
        /// 要取的名字
        var name: String
        /// manual / suggestion（上游 renameSpeaker 的 source）
        var source: String
        var other: ForkVoiceScores.Ranked
        /// 取的名字的人既有樣本裡最高的；nil 是還沒有樣本
        var target: Double?
        var id: String { ForkVoiceSources.key(meetingId, idx) }
    }

    /// 只算、不改任何東西（`mavoice check` 也用）
    struct Verdict {
        var warn: Bool
        var other: ForkVoiceScores.Ranked?
        var target: Double?
        /// 不檢查的原因（沒有聲紋、太短…）；檢查了是 nil
        var skipped: String?
    }

    enum Choice: String { case keep, nameOnly = "nameonly", cancel }

    /// 回答過、要照做的放行：同一場、同一位、同一個名字，60 秒內用一次
    private struct Release {
        var name: String
        var warned: Bool
        var noVoice: Bool
        var at = Date()
    }
    private static var releases: [String: Release] = [:]

    /// 上游 `AppModel.renameSpeaker` 開頭的接點（`// MA-FORK(F12)`）：回 true 是先擋下（不改名），等使用者回答
    static func holds(_ model: AppModel, meetingId: Int64, idx: Int, name: String, source: String) -> Bool {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let key = ForkVoiceSources.key(meetingId, idx)
        if let release = releases.removeValue(forKey: key), release.name == trimmed,
           Date().timeIntervalSince(release.at) < ForkVoiceSources.intentLifetime {
            ForkVoiceSources.noteNaming(meetingId, idx, source: source, warned: release.warned, noVoice: release.noVoice)
            return false
        }
        ForkVoiceSources.noteNaming(meetingId, idx, source: source)
        guard AppSettings.voiceprints, !trimmed.isEmpty, !AppDatabase.isDefaultSpeakerName(trimmed) else { return false }
        let verdict = evaluate(model.db, meetingId: meetingId, idx: idx, name: trimmed)
        guard verdict.warn, let other = verdict.other else { return false }
        let current = model.detail?.meeting.id == meetingId ? (model.detail?.speakers[idx] ?? "") : ""
        let item = Item(meetingId: meetingId, idx: idx, current: current, name: trimmed, source: source, other: other, target: verdict.target)
        model.fork.voiceGuard.removeAll { $0.id == item.id }
        model.fork.voiceGuard.append(item)
        model.fork.voiceGuardShowing = true
        log.info("speaker naming held for voice check: meeting \(meetingId), speaker \(idx)")
        return true
    }

    /// 別人 ≥ 0.88，而且取的名字既有的 < 0.50 或沒有樣本 → 要提醒。兩邊都不算這位說話者自己那一份（上游取名時會先刪掉）
    nonisolated static func evaluate(_ app: AppDatabase, meetingId: Int64, idx: Int, name: String) -> Verdict {
        do {
            return try app.pool.read { db in
                guard let speaker = try SpeakerName.filter(Column("meeting_id") == meetingId && Column("idx") == idx).fetchOne(db) else {
                    return Verdict(warn: false, skipped: "no speaker")
                }
                guard let embedding = speaker.embedding, speaker.speechSeconds >= AppDatabase.voiceprintMinimumSeconds else {
                    return Verdict(warn: false, skipped: "no voice")
                }
                let prints = try ForkVoiceScores.library(db)
                let names = try ForkVoiceScores.names(db)
                let ranked = ForkVoiceScores.rank(Voiceprint.vector(embedding), prints: prints, names: names, excluding: (meetingId, idx))
                let targetId = try Int64.fetchOne(db, sql: "SELECT id FROM people WHERE name = ? COLLATE NOCASE", arguments: [name])
                let target = ranked.first { $0.personId == targetId }?.score
                let other = ranked.first { $0.personId != targetId && $0.name.caseInsensitiveCompare(name) != .orderedSame }
                let warn = (other?.score ?? -1) >= otherThreshold && (target ?? -1) < targetThreshold
                return Verdict(warn: warn, other: other, target: target)
            }
        } catch {
            log.error("voice check failed: \(error.logSummary, privacy: .public)")
            return Verdict(warn: false, skipped: "error")
        }
    }

    /// 防呆視窗的按鈕（套用到這場會議佇列裡的全部）：仍要存、只改名都照上游的流程再取一次名，取消什麼都不改
    static func choose(_ model: AppModel, _ choice: Choice) {
        let items = model.fork.voiceGuard.filter { $0.meetingId == model.selection }
        model.fork.voiceGuard.removeAll()
        model.fork.voiceGuardShowing = false
        guard choice != .cancel else { return }
        for item in items {
            releases[item.id] = Release(name: item.name, warned: choice == .keep, noVoice: choice == .nameOnly)
            model.renameSpeaker(item.idx, to: item.name, source: item.source)
        }
    }

    /// 換會議時（`ForkAppState.selectionChanged`）：還沒回答的就當取消
    static func clear(_ state: ForkAppState) {
        state.voiceGuard.removeAll()
        state.voiceGuardShowing = false
    }
}
