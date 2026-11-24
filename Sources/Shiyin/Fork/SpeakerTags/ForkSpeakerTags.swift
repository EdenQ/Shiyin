import Foundation
import GRDB

/// F2 說話者標記的資料處理（fork design §F2、§F-DB）：上游的檔只留 1 行接點（`// MA-FORK(F2)`）
enum ForkSpeakerTags {
    /// F2.12「只改這句」：上游的 `addSpeaker` 新增的說話者，改成標記的名字（當成手動改名）
    static func nameNewSpeaker(_ db: Database, meetingId: Int64, idx: Int, name: String) throws {
        try db.execute(sql: "UPDATE speakers SET name = ?, name_source = 'manual' WHERE meeting_id = ? AND idx = ?",
                       arguments: [name, meetingId, idx])
    }

    // MARK: 跟著上游的編輯會議（R107）、分成兩場（R90）、合併（F2.13，fork design §F-DB.2）

    /// 快照裡的一個標記（`ma_meeting_edit_tags.tags_json`）
    struct Saved: Codable {
        var start: Double
        var end: Double
        var name: String
        var kind: String
        var createdAt: String
    }

    /// 第一次編輯前存下這場的標記（上游的快照不認得 speaker_tags）；跟著 meeting_edits 刪
    static func snapshot(_ db: Database, meetingId: Int64) throws {
        let saved = try SpeakerTag.filter(Column("meeting_id") == meetingId).order(Column("id")).fetchAll(db)
            .map { Saved(start: $0.start, end: $0.end, name: $0.name, kind: $0.kind, createdAt: $0.createdAt) }
        let json = String(decoding: try JSONEncoder().encode(saved), as: UTF8.self)
        try db.execute(sql: "INSERT OR REPLACE INTO ma_meeting_edit_tags (meeting_id, tags_json) VALUES (?, ?)", arguments: [meetingId, json])
        try ForkRetranscribe.snapshot(db, meetingId: meetingId)   // F12.15：重新轉錄前的名字建議、pending 也存（§F12.9）
    }

    /// 這場的標記照編輯的時間對照搬到新的時間軸；中間點被剪掉的刪掉（同句子，EditPlan.mapSentence）
    static func remap(_ db: Database, meetingId: Int64, plan: EditPlan) throws {
        try ForkRetranscribe.invalidatePending(db, meetingId: meetingId)   // F12.15：說話者可能被移除，pending 失效（§F12.9）
        for tag in try SpeakerTag.filter(Column("meeting_id") == meetingId).fetchAll(db) {
            if let kept = plan.mapSentence(meetingId, start: tag.start, end: tag.end) {
                try db.execute(sql: "UPDATE speaker_tags SET start = ?, \"end\" = ? WHERE id = ?", arguments: [kept.start, kept.end, tag.id])
            } else {
                _ = try SpeakerTag.deleteOne(db, key: tag.id!)
            }
        }
    }

    /// 合併：另一場的標記複製過來（那場移到垃圾桶，它自己的標記留著，還原時用得到）
    static func copyForMerge(_ db: Database, into id: Int64, from other: Int64, plan: EditPlan) throws {
        try ForkRetranscribe.invalidatePending(db, meetingId: id)   // F12.15：說話者合併、重新編號，pending 失效；另一場的建議不帶過來（§F12.9）
        for tag in try SpeakerTag.filter(Column("meeting_id") == other).order(Column("id")).fetchAll(db) {
            guard let kept = plan.mapSentence(other, start: tag.start, end: tag.end) else { continue }
            var copy = SpeakerTag(meetingId: id, start: kept.start, end: kept.end, name: tag.name, kind: tag.kind, createdAt: tag.createdAt)
            try copy.insert(db)
        }
    }

    /// 分成兩場：切點之後的標記移到新的那場、時間減掉切點；跨過切點的切成兩段
    static func split(_ db: Database, from id: Int64, to newId: Int64, at cut: Double) throws {
        try ForkRetranscribe.split(db, from: id, to: newId)   // F12.15：建議照編號複製到新的那場、pending 失效（§F12.9）
        for tag in try SpeakerTag.filter(Column("meeting_id") == id && Column("end") > cut).fetchAll(db) {
            if tag.start >= cut {
                try db.execute(sql: "UPDATE speaker_tags SET meeting_id = ?, start = ?, \"end\" = ? WHERE id = ?",
                               arguments: [newId, tag.start - cut, tag.end - cut, tag.id])
            } else {
                try db.execute(sql: "UPDATE speaker_tags SET \"end\" = ? WHERE id = ?", arguments: [cut, tag.id])
                var rest = SpeakerTag(meetingId: newId, start: 0, end: tag.end - cut, name: tag.name, kind: tag.kind, createdAt: tag.createdAt)
                try rest.insert(db)
            }
        }
    }

    /// 還原編輯前：照快照放回這場的標記（合併進來、搬過的都換回原本的）
    static func restore(_ db: Database, meetingId: Int64) throws {
        try ForkRetranscribe.restore(db, meetingId: meetingId)   // F12.15：建議、pending 回到編輯前（§F12.9）
        guard let json = try String.fetchOne(db, sql: "SELECT tags_json FROM ma_meeting_edit_tags WHERE meeting_id = ?", arguments: [meetingId]),
              let saved = try? JSONDecoder().decode([Saved].self, from: Data(json.utf8)) else { return }
        try db.execute(sql: "DELETE FROM speaker_tags WHERE meeting_id = ?", arguments: [meetingId])
        for item in saved {
            var tag = SpeakerTag(meetingId: meetingId, start: item.start, end: item.end, name: item.name, kind: item.kind, createdAt: item.createdAt)
            try tag.insert(db)
        }
    }

    // MARK: .shiyin 封包（F2.8，fork design §F-DB.3）

    /// 封包裡 fork 自己的檔：上游的拾音匯入時不認得、會略過
    static let packageFile = "ma-speaker-tags.json"

    struct PackageTag: Codable { var start: Double; var end: Double; var name: String; var kind: String }

    @MainActor
    static func attach(_ bundle: ExportBundle, db: AppDatabase, meetingId: Int64) -> ExportBundle {
        var bundle = bundle
        bundle.speakerTags = (try? db.speakerTags(meetingId)) ?? []
        return bundle
    }

    /// 沒有標記就不寫這個檔（封包跟上游的一樣）
    static func writePackage(_ tags: [SpeakerTag], to dir: URL) throws {
        guard !tags.isEmpty else { return }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(tags.map { PackageTag(start: $0.start, end: $0.end, name: $0.name, kind: $0.kind) })
            .write(to: dir.appendingPathComponent(packageFile))
    }

    /// 封包可能來自別人：讀不出來、時間不合理的略過，不讓整個匯入失敗
    static func readPackage(_ dir: URL, meetingId: Int64, db: AppDatabase) throws {
        let url = dir.appendingPathComponent(packageFile)
        guard let data = try? Data(contentsOf: url), let tags = try? JSONDecoder().decode([PackageTag].self, from: data) else { return }
        for tag in tags where tag.start.isFinite && tag.end.isFinite && tag.end >= tag.start && tag.start >= 0
            && !tag.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            try db.addSpeakerTag(meetingId, start: tag.start, end: tag.end, name: tag.name, kind: tag.kind == "now" ? "now" : "line")
        }
    }
}
