import Foundation
import GRDB

/// F2 說話者標記的資料處理（fork design §F2、§F-DB）：上游的檔只留 1 行接點（`// MA-FORK(F2)`）
enum ForkSpeakerTags {
    /// F2.12「只改這句」：上游的 `addSpeaker` 新增的說話者，改成標記的名字（當成手動改名）
    static func nameNewSpeaker(_ db: Database, meetingId: Int64, idx: Int, name: String) throws {
        try db.execute(sql: "UPDATE speakers SET name = ?, name_source = 'manual' WHERE meeting_id = ? AND idx = ?",
                       arguments: [name, meetingId, idx])
    }
}
