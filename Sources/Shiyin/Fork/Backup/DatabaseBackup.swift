import AppKit
import GRDB
import os

/// F10 定期備份資料庫（fork design §F10）：排程、備份、清理、狀態。
/// 備份用 GRDB 的 `backup(to:)`（讀取交易裡的快照，WAL 下不擋寫入，DF9），寫完 integrity_check 才改成正式的檔名
@MainActor
@Observable
final class ForkBackup {
    static let shared = ForkBackup()

    static let enabledKey = "maBackupEnabled"
    static let lastErrorKey = "maBackupLastError"
    static let failingSinceKey = "maBackupFailingSince"
    /// 保留幾份（F10.4，先寫死）
    static let keep = 7
    /// 多久一次（F10.1）
    static let interval: TimeInterval = 24 * 3600
    /// 失敗多久才在設定顯示（F10.6）
    static let warnAfter: TimeInterval = 7 * 24 * 3600
    static let firstCheckDelay: TimeInterval = 120
    static let checkInterval: TimeInterval = 3600
    nonisolated static let blog = Logger(subsystem: "com.weiwei.shiyin", category: "backup")

    /// 一次檢查的結果（design §F10.2）
    enum Outcome: String {
        case done, disabled, running, deferredRecording, notDue, lowDisk, failed
    }

    private(set) var running = false
    private(set) var lastCheck: Outcome?
    private(set) var lastReason: String?
    /// 備份、清理後加一：設定頁跟著重新讀資料夾
    private(set) var revision = 0
    @ObservationIgnored weak var model: AppModel?
    @ObservationIgnored private var timer: Timer?
    #if DEBUG
    /// mabackup simulate lowdisk|fail（design §F10.4、§F10.5）
    @ObservationIgnored var simulateLowDisk = false
    @ObservationIgnored var simulateFail = false
    /// mabackup simulate slow <秒數>：下一次備份在複製完、驗證前多等（讓排程和立即備份真的重疊，design §F10.7）
    @ObservationIgnored var simulateDelay: Double = 0
    #endif

    static var enabled: Bool {
        UserDefaults.standard.object(forKey: enabledKey) == nil ? true : UserDefaults.standard.bool(forKey: enabledKey)
    }

    static var folder: URL { Paths.backupsDir.appendingPathComponent("daily", isDirectory: true) }

    /// ForkStartup.install 呼叫：啟動後 2 分鐘檢查第一次，之後每小時
    static func install(_ model: AppModel) {
        shared.model = model
        guard shared.timer == nil else { return }
        let timer = Timer(timeInterval: checkInterval, repeats: true) { _ in
            MainActor.assumeIsolated { Task { await ForkBackup.shared.check(manual: false) } }
        }
        timer.fireDate = Date().addingTimeInterval(firstCheckDelay)
        RunLoop.main.add(timer, forMode: .common)
        shared.timer = timer
    }

    // MARK: 檢查與備份

    /// 排程的檢查（manual: false）或「立即備份」（manual: true，不看開關、不看 24 小時）
    @discardableResult
    func check(manual: Bool) async -> Outcome {
        let outcome = await decideAndRun(manual: manual)
        lastCheck = outcome
        return outcome
    }

    private func decideAndRun(manual: Bool) async -> Outcome {
        guard let model else { return .failed }
        if !manual && !Self.enabled { return .disabled }
        if running { return .running }
        if model.recorder.isRecording {
            Self.blog.info("backup deferred: recording")
            return .deferredRecording
        }
        if !manual, let last = Self.lastSuccess(), Date().timeIntervalSince(last) < Self.interval { return .notDue }
        let size = Self.databaseSize()
        let free = Self.freeSpace()
        var low = free.map { $0 < size * 2 + 1_000_000_000 } ?? false
        #if DEBUG
        if simulateLowDisk { low = true }
        #endif
        if low {
            let need = ByteCountFormatter.string(fromByteCount: size * 2 + 1_000_000_000, countStyle: .file)
            let have = ByteCountFormatter.string(fromByteCount: free ?? 0, countStyle: .file)
            Self.blog.error("backup skipped: low disk space (database \(size, privacy: .public) bytes, free \(free ?? -1, privacy: .public) bytes)")
            recordFailure(String(localized: "可用空間不夠（需要 \(need)，只剩 \(have)）"))
            return .lowDisk
        }
        running = true
        defer { running = false }
        let db = model.db
        let folder = Self.folder
        var fail = false
        var delay: Double = 0
        #if DEBUG
        fail = simulateFail
        simulateFail = false
        delay = simulateDelay
        simulateDelay = 0
        #endif
        let started = Date()
        let result = await Task.detached(priority: .utility) {
            Self.write(db: db, folder: folder, simulateFail: fail, simulateDelay: delay)
        }.value
        switch result {
        case .success(let url):
            let bytes = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
            Self.blog.info("backup done: \(bytes, privacy: .public) bytes in \(Date().timeIntervalSince(started), format: .fixed(precision: 1), privacy: .public) s")
            UserDefaults.standard.removeObject(forKey: Self.lastErrorKey)
            UserDefaults.standard.removeObject(forKey: Self.failingSinceKey)
            lastReason = nil
            // 還在 running（互斥沒放開）：同一個 app 不會有別的備份在寫暫存檔，這時清掉以前中斷留下的暫存檔（design §F10.3）
            pruneBackups()
            removeStalePartials()
            revision += 1
            return .done
        case .failure(let failure):
            Self.blog.error("backup failed: \(failure.log, privacy: .public) (database \(size, privacy: .public) bytes)")
            recordFailure(failure.reason)
            return .failed
        }
    }

    private func recordFailure(_ reason: String) {
        lastReason = reason
        UserDefaults.standard.set(reason, forKey: Self.lastErrorKey)
        if UserDefaults.standard.object(forKey: Self.failingSinceKey) == nil {
            UserDefaults.standard.set(Date(), forKey: Self.failingSinceKey)
        }
        revision += 1
    }

    struct Failure: Error {
        /// 給人看的（設定、提示）
        var reason: String
        /// 給 log 的（英文、不含內容和路徑）
        var log: String
    }

    /// 背景執行：寫入目的地的步驟在 BackupWriter（fork design §F10.1a：只寫進這次 O_EXCL | O_NOFOLLOW 新建的一般檔）
    nonisolated static func write(db: AppDatabase, folder: URL, simulateFail: Bool, simulateDelay: Double = 0) -> Result<URL, Failure> {
        BackupWriter.write(db: db, folder: folder, stamp: stampFormatter().string(from: Date()),
                           simulateFail: simulateFail, simulateDelay: simulateDelay)
    }

    /// SQLite 在暫存檔旁開的檔（殘檔的判斷用，design §F10.3）
    nonisolated static let partialSidecars = ["", "-wal", "-shm", "-journal"]

    /// lstat 看類型（不跟著符號連結走）：一般檔案才是 true
    nonisolated static func isRegularFile(_ url: URL) -> Bool {
        (try? FileManager.default.attributesOfItem(atPath: url.path)[.type] as? FileAttributeType) == .typeRegular
    }

    /// 刪之前再確認一次是一般檔案（資料夾、符號連結一律不碰）
    @discardableResult
    nonisolated static func removeIfRegularFile(_ url: URL) -> Bool {
        guard isRegularFile(url) else { return false }
        do {
            try FileManager.default.removeItem(at: url)
            return true
        } catch {
            blog.error("backup cleanup failed: \((error as NSError).code, privacy: .public)")
            return false
        }
    }

    nonisolated static func stampFormatter() -> DateFormatter {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.calendar = Calendar(identifier: .gregorian)
        f.timeZone = .current
        f.dateFormat = "yyyyMMdd-HHmmss"
        return f
    }

    // MARK: 資料夾

    /// 檔名的時間部分：名稱完全是 `ma-daily-<yyyyMMdd-HHmmss><suffix>`，而且時間合法（解析後再格式化回去相同）。
    /// 不符合時 nil（design §F10.3）
    nonisolated static func stamp(of name: String, suffix: String = ".sqlite") -> String? {
        let prefix = "ma-daily-"
        guard name.hasPrefix(prefix), name.hasSuffix(suffix), name.count == prefix.count + 15 + suffix.count else { return nil }
        let middle = Array(name.dropFirst(prefix.count).dropLast(suffix.count))
        guard middle.count == 15 else { return nil }
        for (i, c) in middle.enumerated() where i == 8 ? c != "-" : !("0"..."9").contains(c) { return nil }
        let text = String(middle)
        let formatter = stampFormatter()
        guard let date = formatter.date(from: text), formatter.string(from: date) == text else { return nil }
        return text
    }

    /// 資料夾這一層的名稱（不遞迴）
    nonisolated static func entries(in folder: URL) -> [String] {
        (try? FileManager.default.contentsOfDirectory(atPath: folder.path)) ?? []
    }

    /// 資料夾裡的定期備份，舊到新：一般檔案、名稱完全符合、時間合法。份數、上一次成功、清理、age 都用這個（design §F10.3）
    static func backups() -> [String] {
        backups(in: folder)
    }

    nonisolated static func backups(in folder: URL) -> [String] {
        entries(in: folder).filter { stamp(of: $0) != nil && isRegularFile(folder.appendingPathComponent($0)) }.sorted()
    }

    /// 以前中斷留下的暫存檔：一般檔案、名稱完全是 `ma-daily-<合法時間>.partial` 或加上 -wal／-shm／-journal
    nonisolated static func stalePartials(in folder: URL) -> [String] {
        entries(in: folder).filter { name in
            partialSidecars.contains { stamp(of: name, suffix: ".partial" + $0) != nil }
                && isRegularFile(folder.appendingPathComponent(name))
        }.sorted()
    }

    static func date(of name: String) -> Date? {
        stamp(of: name).flatMap { stampFormatter().date(from: $0) }
    }

    /// 上一次成功：資料夾裡最新的那份（DF9：不存在設定裡，設定不跟著 SHIYIN_HOME）
    static func lastSuccess() -> Date? {
        backups().last.flatMap(date(of:))
    }

    /// 留最新 7 份。只刪 backups() 認得的一般檔，刪之前再確認類型；migration 前的備份、其他名字的檔、資料夾、連結都不碰
    func pruneBackups() {
        let all = Self.backups()
        var removed = 0
        for name in all.dropLast(Self.keep) where Self.removeIfRegularFile(Self.folder.appendingPathComponent(name)) {
            removed += 1
        }
        if removed > 0 { Self.blog.info("backup pruned \(removed, privacy: .public) old file(s)") }
    }

    /// 刪以前中斷留下的暫存檔。呼叫的地方要保證沒有正在寫的備份（成功收尾時 running 還是 true，或 running 是 false）
    func removeStalePartials() {
        var removed = 0
        for name in Self.stalePartials(in: Self.folder) where Self.removeIfRegularFile(Self.folder.appendingPathComponent(name)) {
            removed += 1
        }
        if removed > 0 { Self.blog.info("backup removed \(removed, privacy: .public) leftover partial file(s)") }
    }

    /// mabackup prune：份數；沒在備份時才清暫存檔
    func prune() {
        pruneBackups()
        if !running { removeStalePartials() }
        revision += 1
    }

    static func databaseSize() -> Int64 {
        [Paths.database.path, Paths.database.path + "-wal"].reduce(Int64(0)) { sum, path in
            sum + ((try? FileManager.default.attributesOfItem(atPath: path)[.size] as? Int64) ?? 0)
        }
    }

    static func freeSpace() -> Int64? {
        let values = try? Paths.home.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey, .volumeAvailableCapacityKey])
        if let important = values?.volumeAvailableCapacityForImportantUsage, important > 0 { return important }
        return values?.volumeAvailableCapacity.map(Int64.init)
    }

    // MARK: 給畫面的

    /// 「立即備份」能不能按
    var canBackupNow: Bool { !running && model?.recorder.isRecording != true }

    /// 失敗超過 7 天時設定顯示的一行（F10.6）；沒有就 nil
    var warning: String? {
        _ = revision
        guard let reason = UserDefaults.standard.string(forKey: Self.lastErrorKey) else { return nil }
        let last = Self.lastSuccess()
        guard let since = last ?? (UserDefaults.standard.object(forKey: Self.failingSinceKey) as? Date),
              Date().timeIntervalSince(since) > Self.warnAfter else { return nil }
        guard let last else { return String(localized: "還沒有成功備份過：\(reason)") }
        let days = Int(Date().timeIntervalSince(last) / 86400)
        return String(localized: "上次成功備份是 \(days) 天前：\(reason)")
    }

    /// 「MA」選單的「立即備份資料庫」：做完用主視窗的短暫提示說一聲
    static func backupNowFromMenu(_ model: AppModel) {
        Task {
            let outcome = await shared.check(manual: true)
            switch outcome {
            case .done: model.noticeMessage = String(localized: "資料庫已備份")
            case .deferredRecording: model.noticeMessage = String(localized: "錄音中不備份，錄完再試")
            case .running: break
            default: model.noticeMessage = String(localized: "備份失敗：\(shared.lastReason ?? "")")
            }
        }
    }

    static func openFolder() {
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        NSWorkspace.shared.open(folder)
    }

    #if DEBUG
    /// mabackup schedule off|on：停掉、重新開始排程（自動化測試時不讓啟動後 2 分鐘的檢查插進來）
    func setSchedule(_ on: Bool) {
        timer?.invalidate()
        timer = nil
        if on, let model { Self.install(model) }
    }

    /// mabackup age <天數>：每份備份的檔名時間往前移（只改檔名），failingSince 也往前移
    func age(days: Double) {
        let fm = FileManager.default
        let formatter = Self.stampFormatter()
        for name in Self.backups() {
            guard let date = Self.date(of: name) else { continue }
            let newName = "ma-daily-\(formatter.string(from: date.addingTimeInterval(-days * 86400))).sqlite"
            try? fm.moveItem(at: Self.folder.appendingPathComponent(name), to: Self.folder.appendingPathComponent(newName))
        }
        if let since = UserDefaults.standard.object(forKey: Self.failingSinceKey) as? Date {
            UserDefaults.standard.set(since.addingTimeInterval(-days * 86400), forKey: Self.failingSinceKey)
        }
        revision += 1
    }
    #endif
}
