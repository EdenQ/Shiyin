import Foundation
import GRDB

/// 錄音中標記的說話者（fork design §F2、F2.1）：錄完依時間套到正式轉錄分出的說話者。
/// 資料表 `speaker_tags`（v8 起就叫這個名字，不改名，fork design §F-DB）
struct SpeakerTag: SnakeCaseRecord, Identifiable, Hashable {
    static let databaseTableName = "speaker_tags"
    var id: Int64?
    var meetingId: Int64
    var start: Double
    var end: Double
    var name: String
    var kind: String                       // line：即時逐字稿的一行；now：「正在說話」按鈕
    var createdAt: String = Clock.now()

    var tag: SpeakerTagging.Tag { SpeakerTagging.Tag(start: start, end: end, name: name) }

    mutating func didInsert(_ inserted: InsertionSuccess) { id = inserted.rowID }
}

extension Segment: SpeakerSpan {}
