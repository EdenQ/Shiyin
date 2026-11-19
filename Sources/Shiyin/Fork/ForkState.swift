import Foundation

/// fork 的畫面狀態（fork design §F0.2）：`@Observable` 的 AppModel、MeetingDetail 不能在 extension 加存起來的屬性，
/// 所以 fork 的狀態放這裡，上游的檔只多一個屬性（`AppModel.fork`，`// MA-FORK(F0)`）；
/// 各功能在自己的 extension 用跟原本一樣的名字讀寫（`model.knownPeople`、`model.currentTopicBranch`…）
@MainActor
@Observable
final class ForkAppState {
    // F2 錄音中標記說話者
    /// 一行的選單、＋ 的輸入框列出的認識的人（打開錄音畫面時讀一次）
    var knownPeople: [String] = []
    #if DEBUG
    /// shiyinctl tagui：add 等於按「正在說話」的 ＋，name:<行的 id> 等於一行選單裡的「其他名字…」（打開彈出視窗）
    var debugTagUI: String?
    #endif

    // F4 紀錄條列頁
    /// 播放中的議題（F4.9，fork design §F4.3）：心智圖的第幾支。播放條在議題換了時才設，紀錄頁不用隨播放時間重算
    var currentTopicBranch: Int?
    /// 在紀錄分頁點議題帶：紀錄頁捲到那個議題（F4.10）；每次點都是新的 id，同一段連點也會捲
    var topicScrollRequest: TopicScrollRequest?
    /// 紀錄條列頁收起來的議題（`notes.topics` 的位置，F4.7）；nil 是預設（議題 > 5 個全部收起）。只記這次選取期間
    var notesCollapsedTopics: Set<Int>?
    /// 議題帶切段的快取（fork design §F4.3）：會議紀錄或長度變了才重算；播放條每 0.1 秒重畫時只查表
    @ObservationIgnored var topicSegmentsCache: (notes: MeetingNotes, duration: Double, segments: [MindMap.TopicRange])?

    /// 上游換選取的會議時（AppModel 的 selection）：清掉議題的狀態
    func selectionChanged() {
        currentTopicBranch = nil
        topicScrollRequest = nil
        notesCollapsedTopics = nil
    }
}
