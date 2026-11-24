import Foundation
import GRDB

/// F12 聲紋的分數（fork design §F12.2、DF12）：顯示時用說話者存好的向量跟現在的聲紋庫重算，不存分數。
/// 建議的原因、自動帶入的依據都從這裡來；人物頁、防呆也用同一份聲紋庫
enum ForkVoiceScores {
    /// 等級照上游的門檻（design §21.4.1、D91）：≥ 0.88 很像（自動帶入）、≥ 0.65 有點像（列成建議）、其他不像
    enum Level { case close, possible, unlikely }

    static func level(_ score: Double) -> Level {
        score >= AppDatabase.voiceprintAutoThreshold ? .close : score >= AppDatabase.voiceprintThreshold ? .possible : .unlikely
    }

    static func percent(_ score: Double) -> Int { max(0, Int((score * 100).rounded())) }

    /// 最像和第二像差不到上游自動帶入要的差距（0.15）：兩人很像
    static func tooClose(_ top: Double, _ next: Double) -> Bool { top - next < AppDatabase.voiceprintAutoMargin }

    /// 一個人的最高分
    struct Ranked: Equatable {
        var personId: Int64
        var name: String
        var score: Double
    }

    /// 一位說話者跟每個認識的人比的結果，由高到低（`MeetingDetail.forkTags.voice`）
    struct Basis: Equatable {
        var ranked: [Ranked]
    }

    /// 聲紋庫的一份
    struct Print {
        var id: Int64
        var personId: Int64
        var meetingId: Int64?
        var speakerIdx: Int?
        var audioSource: String
        var createdAt: String
        var vector: [Float]
    }

    /// 由 `ForkStartup.install` 設定：`MeetingDetail.loadSpeakers` 的接點沒有資料庫可用
    static let database = LockedValue<AppDatabase?>(nil)
    /// 聲紋的向量（id → 向量）：不會變的才快取，中繼資料每次重讀（§F12.2）
    private static let vectorCache = LockedValue<[Int64: [Float]]>([:])

    @MainActor
    static func install(_ model: AppModel) {
        database.value = model.db
        ForkVoiceSources.resolveIfNeeded(model.db)
        ForkRetranscribe.retryAll(model.db)   // F12.15：上次重新轉錄存檔後沒處理完的再做
    }

    /// 聲紋庫：中繼資料每次重讀（分成兩場會改 meeting_id、合併人會改 person_id），只快取向量（以 id 為鍵；
    /// 上游從不更新 embedding、AUTOINCREMENT 的 id 不會重用）。fork design §F12.2、REV-F12 P2-1
    static func library(_ db: Database) throws -> [Print] {
        let rows = try Row.fetchAll(db, sql: """
            SELECT id, person_id, meeting_id, speaker_idx, audio_source, created_at FROM voiceprints ORDER BY id
            """)
        var vectors = vectorCache.value
        let ids = Set(rows.map { $0["id"] as Int64 })
        let missing = ids.subtracting(vectors.keys)
        if !missing.isEmpty {
            for r in try Row.fetchAll(db, sql: "SELECT id, embedding FROM voiceprints WHERE id IN (\(missing.map(String.init).joined(separator: ",")))") {
                vectors[r["id"]] = Voiceprint.vector(r["embedding"] as Data)
            }
        }
        vectors = vectors.filter { ids.contains($0.key) }
        vectorCache.value = vectors
        return rows.compactMap { r in
            let id: Int64 = r["id"]
            guard let vector = vectors[id] else { return nil }
            return Print(id: id, personId: r["person_id"], meetingId: r["meeting_id"], speakerIdx: r["speaker_idx"],
                         audioSource: r["audio_source"], createdAt: r["created_at"], vector: vector)
        }
    }

    static func names(_ db: Database) throws -> [Int64: String] {
        Dictionary(try Row.fetchAll(db, sql: "SELECT id, name FROM people").map { ($0["id"] as Int64, $0["name"] as String) },
                   uniquingKeysWith: { a, _ in a })
    }

    /// 跟每個人比，每人取最高（同上游 matchVoiceprints）；不算這位說話者自己存進去的那一份
    static func rank(_ vector: [Float], prints: [Print], names: [Int64: String], excluding: (meetingId: Int64, idx: Int)?) -> [Ranked] {
        var best: [Int64: Double] = [:]
        for print in prints {
            if let excluding, print.meetingId == excluding.meetingId, print.speakerIdx == excluding.idx { continue }
            let score = Voiceprint.similarity(vector, print.vector)
            best[print.personId] = max(best[print.personId] ?? -1, score)
        }
        return best.compactMap { person, score in names[person].map { Ranked(personId: person, name: $0, score: score) } }
            .sorted { $0.score != $1.score ? $0.score > $1.score : $0.name < $1.name }
    }

    // MARK: 接點

    /// 上游 `MeetingDetail.loadSpeakers` 最後的接點（`// MA-FORK(F12)`）：整場讀取、只重讀說話者都經過這裡。
    /// 算每位說話者的依據（存進 `forkTags.voice`），建議的原因改寫成依據（只改顯示，資料庫裡的不動）
    static func annotate(_ detail: inout MeetingDetail, _ rows: [SpeakerName]) {
        guard let app = database.value, let meetingId = detail.meeting.id else { return }
        ForkVoiceSources.resolveIfNeeded(app)
        let voiced = rows.filter { $0.embedding != nil && $0.speechSeconds >= AppDatabase.voiceprintMinimumSeconds }
        var bases: [Int: Basis] = [:]
        if !voiced.isEmpty, let loaded = try? app.pool.read({ db in (try library(db), try Self.names(db)) }), !loaded.0.isEmpty {
            for row in voiced {
                let ranked = rank(Voiceprint.vector(row.embedding!), prints: loaded.0, names: loaded.1, excluding: (meetingId, row.idx))
                if !ranked.isEmpty { bases[row.idx] = Basis(ranked: ranked) }
            }
        }
        detail.forkTags.voice = bases
        ForkRetranscribe.present(&detail, rows, app: app)   // F12.15：重新轉錄前的名字建議（補回、清掉處理過的、自動帶名時照樣顯示）
        let language = detail.meeting.meetingLanguage
        for (idx, suggestion) in detail.speakerSuggestions {
            detail.speakerSuggestions[idx]?.reason = suggestionReason(suggestion, basis: bases[idx], language: language)
        }
    }

    // MARK: 文字

    /// 上游 matchVoiceprints 寫的原因：時間是空的，而且原因等於任何一種會議語言（精調、一般語言）用建議的名字寫的那一句，
    /// 就是聲紋的建議。看所有語言：上游存的是當時的會議語言，使用者改會議語言後不重寫（REV-F12 P2-2）。
    /// 上游改了這句要跟著改（f12-voiceprint-check 會驗）
    static func isVoiceprintSuggestion(_ suggestion: SpeakerNaming.Suggestion) -> Bool {
        guard suggestion.time.isEmpty else { return false }
        return MeetingLanguage.allCases.contains { language in
            suggestion.reason == language.format(zh: "聲音跟之前的%@很像", en: "Sounds like %@ from earlier meetings",
                                                 ja: "以前の%@の声に似ています", suggestion.name)  // l10n-skip：上游的原因
        }
    }

    /// 組依據的文字用的片語：建議的原因用會議語言（`meeting`），自動帶入的選單用介面語言（`interface`）
    struct Phrases {
        var head: (String, Int, String) -> String
        var second: (String, Int) -> String
        var now: (String, Int) -> String
        var close: String
        var separator: String
        var level: (Level) -> String

        static func meeting(_ l: MeetingLanguage) -> Phrases {
            Phrases(
                head: { l.format(zh: "聲紋比對：%@ %ld%%（%@）", en: "Voice match: %@ %ld%% (%@)", ja: "声の照合：%@ %ld%%（%@）", $0, $1, $2) },  // l10n-skip：會議語言
                second: { l.format(zh: "第二像 %@ %ld%%", en: "next %@ %ld%%", ja: "次点 %@ %ld%%", $0, $1) },  // l10n-skip
                now: { l.format(zh: "現在最像的是 %@ %ld%%", en: "closest now: %@ %ld%%", ja: "今いちばん近いのは %@ %ld%%", $0, $1) },  // l10n-skip
                close: l.text(zh: "兩人很像，請確認", en: "the two sound alike, please check", ja: "二人の声が近いので確認してください"),  // l10n-skip
                separator: l.text(zh: "・", en: " · ", ja: "・"),  // l10n-skip
                level: { level in
                    switch level {
                    case .close: l.text(zh: "很像", en: "very close", ja: "よく似ている")  // l10n-skip
                    case .possible: l.text(zh: "有點像", en: "possible", ja: "似ている")  // l10n-skip
                    case .unlikely: l.text(zh: "不像", en: "unlikely", ja: "似ていない")  // l10n-skip
                    }
                })
        }

        static var interface: Phrases {
            Phrases(
                head: { name, percent, level in String(localized: "聲紋比對：\(name) \(percent)%（\(level)）") },
                second: { name, percent in String(localized: "第二像 \(name) \(percent)%") },
                now: { name, percent in String(localized: "現在最像的是 \(name) \(percent)%") },
                close: String(localized: "兩人很像，請確認"),
                separator: String(localized: "・"),
                level: { level in
                    switch level {
                    case .close: String(localized: "很像")
                    case .possible: String(localized: "有點像")
                    case .unlikely: String(localized: "不像")
                    }
                })
        }
    }

    /// 依據：`name` 是建議或目前的名字。
    /// 名字是最像的：「name 97%（很像）・第二像 X 61%」，差不到 0.15 加「兩人很像，請確認」；
    /// 名字不是最像的（聲紋庫後來變了）：「name 80%（有點像）・現在最像的是 X 96%」；名字不在聲紋庫：寫最像的兩位
    static func describe(_ basis: Basis, name: String, phrases p: Phrases) -> String {
        guard let top = basis.ranked.first else { return "" }
        let mine = basis.ranked.first { $0.name.caseInsensitiveCompare(name) == .orderedSame }
        let lead = mine ?? top
        var parts = [p.head(lead.name, percent(lead.score), p.level(level(lead.score)))]
        if lead.personId == top.personId {
            if let next = basis.ranked.dropFirst().first {
                parts.append(p.second(next.name, percent(next.score)))
                if tooClose(top.score, next.score) { parts.append(p.close) }
            }
        } else {
            parts.append(p.now(top.name, percent(top.score)))
            if tooClose(top.score, lead.score) { parts.append(p.close) }
        }
        return parts.joined(separator: p.separator)
    }

    /// 建議的原因（會議語言）：聲紋的改寫成依據；AI 猜的前面加「依內容猜：」；算不出分數的聲紋建議照上游
    static func suggestionReason(_ suggestion: SpeakerNaming.Suggestion, basis: Basis?, language: MeetingLanguage) -> String {
        if ForkRetranscribe.isRetranscribeSuggestion(suggestion) {   // F12.15：重新轉錄前的名字，用目前的會議語言重新寫
            return ForkRetranscribe.reason(suggestion.name, language: language)
        }
        if isVoiceprintSuggestion(suggestion) {
            guard let basis else { return suggestion.reason }
            return describe(basis, name: suggestion.name, phrases: .meeting(language))
        }
        let prefix = language.text(zh: "依內容猜：", en: "Guessed from what was said: ", ja: "内容から推測：")  // l10n-skip：會議語言
        return prefix + suggestion.reason
    }

    /// 自動帶入的名字選單最上面一行（介面語言）
    static func autoBasis(_ basis: Basis, name: String) -> String {
        describe(basis, name: name, phrases: .interface)
    }
}
