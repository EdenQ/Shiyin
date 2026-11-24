#if DEBUG
import Foundation
import GRDB

/// F12 的 DEBUG 指令 `mavoice`（fork design §F12.7）
@MainActor
extension ForkDebug {
    static func voiceprints(_ args: [String], model: AppModel) -> Bool {
        guard args[0] == "mavoice" else { return false }
        let sub = args.count > 1 ? args[1] : ""
        let meeting = args.count > 2 ? Int64(args[2]) : nil
        let idx = args.count > 3 ? Int(args[3]) : nil
        func select(_ id: Int64) { if model.selection != id { model.selection = id } }
        switch sub {
        case "setvoice":   // mavoice setvoice <會議> <說話者> <秒數> <向量.json>：只有測試用的合成聲紋
            guard let meeting, let idx, args.count > 5, let seconds = Double(args[4]),
                  let data = FileManager.default.contents(atPath: args[5]),
                  let numbers = try? JSONSerialization.jsonObject(with: data) as? [Double] else { return true }
            let vector = numbers.map { Float($0) }
            do {
                try model.db.pool.write { db in
                    let language = try Meeting.fetchOne(db, key: meeting)?.meetingLanguage ?? .zh
                    try db.execute(sql: "DELETE FROM voiceprints WHERE meeting_id = ? AND speaker_idx = ?", arguments: [meeting, idx])
                    try db.execute(sql: """
                        UPDATE speakers SET embedding = ?, speech_seconds = ?, name = ?, name_source = 'default', person_id = NULL,
                          suggested_name = NULL, suggestion_reason = NULL, suggestion_time = NULL
                        WHERE meeting_id = ? AND idx = ?
                        """, arguments: [Voiceprint.data(vector), seconds, language.defaultSpeaker(idx), meeting, idx])  // l10n-skip
                    try AppDatabase.deleteOrphanPeople(db)
                }
            } catch { log.error("mavoice setvoice failed: \(error.logSummary, privacy: .public)") }
            if model.selection == meeting { model.reloadDetail([.speakers, .meeting]) }
        case "match":   // mavoice match <會議>：上游 matchVoiceprints
            if let meeting { _ = try? model.db.matchVoiceprints(meeting) }
            if model.selection == meeting { model.reloadDetail([.speakers, .meeting]) }
        case "suggest":   // mavoice suggest <會議> <說話者> <名字> <時間> <原因>：上游 saveSpeakerSuggestions（AI 猜的）
            if let meeting, let idx, args.count > 6 {
                try? model.db.saveSpeakerSuggestions(meeting, [SpeakerNaming.Suggestion(speaker: idx, name: args[4], reason: args[6], time: args[5])])
            }
            if model.selection == meeting { model.reloadDetail([.speakers]) }
        case "rename":   // mavoice rename <會議> <說話者> <名字>：上游 renameSpeaker（經過防呆）
            if let meeting, let idx, args.count > 4 { select(meeting); model.renameSpeaker(idx, to: args[4]) }
        case "apply":   // mavoice apply <會議> <說話者>
            if let meeting, let idx { select(meeting); model.applySpeakerSuggestion(idx) }
        case "applyall":   // mavoice applyall <會議>
            if let meeting { select(meeting); model.applyAllSpeakerSuggestions() }
        case "choose":   // mavoice choose keep|nameonly|cancel：防呆視窗的按鈕
            if args.count > 2, let choice = ForkVoiceGuard.Choice(rawValue: args[2]) { ForkVoiceGuard.choose(model, choice) }
        case "check":   // mavoice check <會議> <說話者> <名字> <輸出.json>：只算防呆
            guard let meeting, let idx, args.count > 5 else { return true }
            let v = ForkVoiceGuard.evaluate(model.db, meetingId: meeting, idx: idx, name: args[4])
            write(["warn": v.warn, "other": v.other?.name ?? NSNull(), "otherScore": v.other?.score ?? NSNull(),
                   "target": v.target ?? NSNull(), "skipped": v.skipped ?? NSNull()], to: args[5])
        case "state":   // mavoice state <輸出.json>
            if args.count > 2 { write(voiceState(model), to: args[2]) }
        case "prints":   // mavoice prints <person id> <輸出.json>
            guard let person = meeting, args.count > 3 else { return true }
            let rows = (try? ForkVoiceSources.rows(model.db, personId: person)) ?? []
            write(["rows": rows.map { r -> [String: Any] in
                ["id": r.id, "createdAt": r.createdAt, "meetingId": r.meetingId ?? NSNull(), "meetingTitle": r.meetingTitle ?? NSNull(),
                 "trashed": r.meetingTrashed, "enrolled": r.enrolled, "source": r.source ?? NSNull(), "label": ForkVoiceSources.label(r),
                 "warned": r.warned, "ownBest": r.ownBest ?? NSNull(), "other": r.other?.name ?? NSNull(),
                 "otherScore": r.other?.score ?? NSNull(), "suspicious": r.suspicious,
                 "flags": ForkVoiceSources.Flag.allCases.filter { r.flags.contains($0) }.map(\.rawValue)]
            }], to: args[3])
        case "delete":   // mavoice delete <聲紋 id>：同人物頁的刪除（不經過確認）
            if let id = meeting { _ = try? ForkVoiceSources.delete(model.db, voiceprintId: id); ForkVoiceprintsUI.afterDelete(model) }
        case "retranscribe":   // mavoice retranscribe <會議> <設定.json>：模擬重新轉錄（§F12.9），同 JobRunner 的順序
            guard let meeting, args.count > 3, let data = FileManager.default.contents(atPath: args[3]),
                  let spec = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return true }
            simulateRetranscribe(model, meeting, spec)
        case "retranscribe-retry":   // mavoice retranscribe-retry <會議>：再呼叫一次存檔後的處理（同啟動時的重試）
            if let meeting {
                do { try ForkRetranscribe.after(model.db, meeting) } catch { log.error("mavoice retranscribe-retry failed: \(error.logSummary, privacy: .public)") }
                if model.selection == meeting { model.reloadDetail() }
            }
        case "dismiss":   // mavoice dismiss <會議> <說話者>：等於按建議的「忽略」
            if let meeting, let idx { select(meeting); model.dismissSpeakerSuggestion(idx) }
        case "person":   // mavoice person <person id>：切到人物頁、選這個人
            if let id = meeting { model.reloadPeopleOverview(); model.sidebarMode = .people; model.selectedPerson = id }
        default:
            break
        }
        return true
    }

    /// {"map": {"舊編號": 新編號}, "vectors": {"新編號": [向量]}, "seconds": {"新編號": 秒數}}：用目前的段落換編號、換聲紋，
    /// 呼叫上游 saveTranscript，再 afterTranscription、matchVoiceprints
    private static func simulateRetranscribe(_ model: AppModel, _ meetingId: Int64, _ spec: [String: Any]) {
        let map = (spec["map"] as? [String: Int] ?? [:]).reduce(into: [Int: Int]()) { r, kv in if let k = Int(kv.key) { r[k] = kv.value } }
        let vectors = (spec["vectors"] as? [String: [Double]] ?? [:]).reduce(into: [Int: [Float]]()) { r, kv in if let k = Int(kv.key) { r[k] = kv.value.map(Float.init) } }
        let seconds = (spec["seconds"] as? [String: Double] ?? [:]).reduce(into: [Int: Double]()) { r, kv in if let k = Int(kv.key) { r[k] = kv.value } }
        ForkRetranscribe.debugFailSave.value = spec["failSave"] as? Bool ?? false
        ForkRetranscribe.debugFailLearn.value = spec["failLearn"] as? Bool ?? false
        let db = model.db
        do {
            let old = try db.speakers(meetingId)
            let segments = try db.segments(meetingId).enumerated().map { i, s -> Segment in
                var copy = s
                copy.id = nil
                copy.seq = i
                copy.speaker = s.speaker.map { map[$0] ?? $0 }
                return copy
            }
            var voices: [Int: SpeakerVoice] = [:]
            for o in old {
                let n = map[o.idx] ?? o.idx
                let vector = vectors[n] ?? o.embedding.map(Voiceprint.vector)
                if let vector { voices[n] = SpeakerVoice(embedding: vector, seconds: seconds[n] ?? o.speechSeconds, source: o.audioSource) }
            }
            for (n, v) in vectors where voices[n] == nil { voices[n] = SpeakerVoice(embedding: v, seconds: seconds[n] ?? 30, source: "mix") }
            let count = max(segments.compactMap(\.speaker).max() ?? 0, voices.keys.max() ?? 0)
            try db.saveTranscript(meetingId, segments: segments, duration: model.detail?.meeting.durationSeconds ?? 0, speakerCount: count, voices: voices)
        } catch {
            // failSave：存檔回滾。照樣呼叫 afterTranscription（模擬之後別的流程，例如重新辨識說話者，也會呼叫），應該不做事
            log.error("mavoice retranscribe save failed: \(error.logSummary, privacy: .public)")
        }
        ForkSpeakerTags.afterTranscription(db, meetingId)
        if AppSettings.voiceprints { _ = try? db.matchVoiceprints(meetingId) }
        ForkRetranscribe.debugFailSave.value = false
        ForkRetranscribe.debugFailLearn.value = false
        // noselect：模擬轉錄完、還沒打開這場（不重讀畫面；目前選的是別場時也不切過去）
        if spec["noselect"] as? Bool == true { return }
        if model.selection == meetingId { model.reloadDetail() } else { model.selection = meetingId }
    }

    private static func voiceState(_ model: AppModel) -> [String: Any] {
        guard let detail = model.detail, let meetingId = detail.meeting.id else { return ["meeting": NSNull()] }
        let people = Dictionary(((try? model.db.speakers(meetingId)) ?? []).map { ($0.idx, $0.personId) }, uniquingKeysWith: { a, _ in a })
        let speakers: [[String: Any]] = detail.speakers.keys.sorted().map { idx in
            let name = detail.speakers[idx] ?? ""
            let basis = detail.forkTags.voice[idx]
            var item: [String: Any] = ["idx": idx, "name": name, "source": detail.speakerSources[idx] ?? "",
                                       "personId": (people[idx] ?? nil) ?? NSNull(),
                                       "basis": (basis?.ranked ?? []).map { ["name": $0.name, "score": $0.score] },
                                       "autoBasis": detail.speakerSources[idx] == "voiceprint" ? basis.map { ForkVoiceScores.autoBasis($0, name: name) } ?? NSNull() : NSNull()]
            if let s = detail.speakerSuggestions[idx] {
                item["suggestion"] = ["name": s.name, "reason": s.reason, "time": s.time]
            }
            return item
        }
        let queue: [[String: Any]] = model.fork.voiceGuard.map {
            ["meetingId": $0.meetingId, "idx": $0.idx, "current": $0.current, "name": $0.name, "source": $0.source,
             "other": $0.other.name, "otherScore": $0.other.score, "target": $0.target ?? NSNull(), "line": ForkVoiceGuardSheet.line($0)]
        }
        return ["meeting": meetingId, "speakers": speakers, "guard": queue, "guardShowing": model.fork.voiceGuardShowing,
                "sidebarMode": model.sidebarMode.rawValue, "selectedPerson": model.selectedPerson ?? NSNull()]
    }
}
#endif
