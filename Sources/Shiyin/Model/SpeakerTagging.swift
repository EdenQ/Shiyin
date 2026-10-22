import Foundation

/// 有時間範圍、可能標了說話者的一段（正式逐字稿的段落）
protocol SpeakerSpan {
    var id: Int64? { get }
    var start: Double { get }
    var end: Double { get }
    var speaker: Int? { get }
}

/// 錄音中標記的說話者怎麼對到正式轉錄分出的說話者（design §24、R23、D37）。
/// 不依賴資料庫，規則可以單獨測
enum SpeakerTagging {
    /// 標記的範圍裡說話不到這麼多秒（那段沒人說話）就不算
    static let minimumSpeech = 0.5
    /// 重疊最多的說話者至少要佔這個比例才算對上他，不然這個標記不明確
    static let dominance = 0.7
    /// 「正在說話」標記的範圍：按下前 3 秒到按下後 1 秒。通常是聽了一兩秒、認出是誰才按（design §24.2）
    static let nowBefore = 3.0
    static let nowAfter = 1.0
    /// 前一個「正在說話」的標記，中間點差不到這麼多秒就取代它（按錯馬上改按另一個人）
    static let nowReplaceWithin = 2.0

    struct Tag: Equatable {
        var start: Double
        var end: Double
        var name: String
        var center: Double { (start + end) / 2 }
    }

    struct Match: Equatable {
        /// 對上的說話者：重疊最多而且佔 70% 以上；不明確或沒人說話是 nil
        var speaker: Int?
        /// 重疊最多的說話者佔的比例（沒人說話是 0）
        var share: Double
        /// 逐字稿上的位置：重疊最多的一段，沒有重疊就用時間最近的一段（design §24.4）
        var segmentId: Int64?
        /// 那一段的說話者
        var segmentSpeaker: Int?
    }

    static func nowRange(at time: Double) -> (start: Double, end: Double) {
        (max(0, time - nowBefore), time + nowAfter)
    }

    /// 名字一樣：前後空白不算、不分大小寫
    static func sameName(_ a: String, _ b: String) -> Bool {
        a.trimmingCharacters(in: .whitespacesAndNewlines)
            .caseInsensitiveCompare(b.trimmingCharacters(in: .whitespacesAndNewlines)) == .orderedSame
    }

    /// 一個標記對上哪位說話者：範圍跟每位說話者的段落重疊幾秒，重疊最多的佔 70% 以上才算
    static func match<S: SpeakerSpan>(_ tag: Tag, in spans: [S]) -> Match {
        var overlap: [Int: Double] = [:]
        var best: (span: S, seconds: Double)?
        var nearest: (span: S, distance: Double)?
        for span in spans {
            let seconds = min(tag.end, span.end) - max(tag.start, span.start)
            if seconds > 0 {
                if let speaker = span.speaker { overlap[speaker, default: 0] += seconds }
                if seconds > (best?.seconds ?? 0) { best = (span, seconds) }
            } else {
                let distance = -seconds
                if distance < (nearest?.distance ?? .infinity) { nearest = (span, distance) }
            }
        }
        let total = overlap.values.reduce(0, +)
        // 一樣多時取編號小的，結果才固定
        let top = overlap.max { $0.value != $1.value ? $0.value < $1.value : $0.key > $1.key }
        let share = total > 0 ? (top?.value ?? 0) / total : 0
        let target = best?.span ?? nearest?.span
        return Match(speaker: total >= minimumSpeech && share >= dominance ? top?.key : nil, share: share,
                     segmentId: target?.id, segmentSpeaker: target?.speaker)
    }

    /// 每位說話者要套用的名字（design §24.3）：只看 candidates 裡的說話者（名字還是預設的），
    /// 對上他的標記都是同一個名字才套用，寫法用第一個標記的（tags 依標記的先後）
    static func names<S: SpeakerSpan>(for tags: [Tag], in spans: [S], candidates: Set<Int>) -> [Int: String] {
        var votes: [Int: [String]] = [:]
        for tag in tags {
            let name = tag.name.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !name.isEmpty, let speaker = match(tag, in: spans).speaker, candidates.contains(speaker) else { continue }
            votes[speaker, default: []].append(name)
        }
        return votes.compactMapValues { names in
            names.allSatisfy { sameName($0, names[0]) } ? names[0] : nil
        }
    }

    /// 「正在說話」的名單（design §24.2）：與會者照原本的順序，接著是標過、不在與會者裡的名字；不分大小寫去掉重複
    static func roster(participants: [String], tagged: [String]) -> [String] {
        var result: [String] = []
        for name in participants + tagged {
            let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty && !result.contains(where: { sameName($0, trimmed) }) { result.append(trimmed) }
        }
        return result
    }

    /// 即時逐字稿的一行有的標記：中間點落在這一行裡的（design §24.2）
    static func belongs(_ tag: Tag, toLine start: Double, _ end: Double) -> Bool {
        tag.center >= start && tag.center <= end
    }
}
