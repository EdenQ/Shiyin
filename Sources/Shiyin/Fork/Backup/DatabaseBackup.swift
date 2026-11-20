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
        #if DEBUG
        fail = simulateFail
        simulateFail = false
        #endif
        let started = Date()
        let result = await Task.detached(priority: .utility) { Self.write(db: db, folder: folder, simulateFail: fail) }.value
        switch result {
        case .success(let url):
            let bytes = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
            Self.blog.info("backup done: \(bytes, privacy: .public) bytes in \(Date().timeIntervalSince(started), format: .fixed(precision: 1), privacy: .public) s")
            UserDefaults.standard.removeObject(forKey: Self.lastErrorKey)
            UserDefaults.standard.removeObject(forKey: Self.failingSinceKey)
            lastReason = nil
            prune()
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

    /// 背景執行：暫存檔 → integrity_check → 單一檔（DELETE 模式）→ 改名。失敗時刪掉暫存檔
    nonisolated static func write(db: AppDatabase, folder: URL, simulateFail: Bool) -> Result<URL, Failure> {
        let fm = FileManager.default
        let stamp = stampFormatter().string(from: Date())
        let final = folder.appendingPathComponent("ma-daily-\(stamp).sqlite")
        let partial = folder.appendingPathComponent("ma-daily-\(stamp).partial")
        do {
            try fm.createDirectory(at: folder, withIntermediateDirectories: true)
        } catch {
            return .failure(Failure(reason: String(localized: "建立備份資料夾失敗"), log: "create folder: \(fileCode(error))"))
        }
        if fm.fileExists(atPath: final.path) {
            return .failure(Failure(reason: String(localized: "同名的備份已經存在"), log: "file exists"))
        }
        removePartial(partial)
        do {
            let dest = try DatabaseQueue(path: partial.path)
            try db.pool.backup(to: dest)
            try dest.close()
            if simulateFail { throw Failure(reason: "simulated failure (DEBUG)", log: "simulated failure") }
            let verify = try DatabaseQueue(path: partial.path)
            let lines = try verify.read { try String.fetchAll($0, sql: "PRAGMA integrity_check") }
            guard lines == ["ok"] else {
                try? verify.close()
                throw Failure(reason: String(localized: "備份的完整性檢查沒有通過"), log: "integrity_check: \(lines.count) lines")
            }
            _ = try verify.writeWithoutTransaction { try String.fetchOne($0, sql: "PRAGMA journal_mode=DELETE") }
            try verify.close()
            try fm.moveItem(at: partial, to: final)
            removePartial(partial)   // 驗證時 WAL 模式留下的 -shm（改名後不會再用）
            return .success(final)
        } catch let failure as Failure {
            removePartial(partial)
            return .failure(failure)
        } catch let error as DatabaseError {
            removePartial(partial)
            return .failure(Failure(reason: String(localized: "資料庫錯誤（\(error.resultCode.rawValue)）"),
                                    log: "sqlite \(error.resultCode.rawValue)"))
        } catch {
            removePartial(partial)
            return .failure(Failure(reason: String(localized: "寫入備份失敗"), log: "file: \(fileCode(error))"))
        }
    }

    nonisolated private static func fileCode(_ error: Error) -> String {
        let ns = error as NSError
        return "\(ns.domain) \(ns.code)"
    }

    /// 暫存檔和 SQLite 在旁邊開的檔
    nonisolated static func removePartial(_ partial: URL) {
        for suffix in ["", "-wal", "-shm", "-journal"] {
            try? FileManager.default.removeItem(at: URL(fileURLWithPath: partial.path + suffix))
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

    /// 檔名的時間部分（`ma-daily-yyyyMMdd-HHmmss.sqlite` 的 yyyyMMdd-HHmmss）；名稱不完全符合時 nil
    nonisolated static func stamp(of name: String) -> String? {
        let prefix = "ma-daily-", suffix = ".sqlite"
        guard name.hasPrefix(prefix), name.hasSuffix(suffix) else { return nil }
        let middle = Array(name.dropFirst(prefix.count).dropLast(suffix.count))
        guard middle.count == 15 else { return nil }
        for (i, c) in middle.enumerated() where i == 8 ? c != "-" : !("0"..."9").contains(c) { return nil }
        return String(middle)
    }

    /// 資料夾裡的定期備份（只看這一層、名稱完全符合的檔），舊到新
    static func backups() -> [String] {
        let names = (try? FileManager.default.contentsOfDirectory(atPath: folder.path)) ?? []
        return names.filter { stamp(of: $0) != nil }.sorted()
    }

    static func date(of name: String) -> Date? {
        stamp(of: name).flatMap { stampFormatter().date(from: $0) }
    }

    /// 上一次成功：資料夾裡最新的那份（DF9：不存在設定裡，設定不跟著 SHIYIN_HOME）
    static func lastSuccess() -> Date? {
        backups().last.flatMap(date(of:))
    }

    /// 留最新 7 份；沒在備份時順便刪掉沒寫完的暫存檔。migration 前的備份（backups/ 那一層）、其他名字的檔都不碰
    func prune() {
        let fm = FileManager.default
        let all = Self.backups()
        for name in all.dropLast(Self.keep) {
            do {
                try fm.removeItem(at: Self.folder.appendingPathComponent(name))
            } catch {
                Self.blog.error("backup prune failed: \((error as NSError).code, privacy: .public)")
            }
        }
        if !running {
            let names = (try? fm.contentsOfDirectory(atPath: Self.folder.path)) ?? []
            for name in names where name.hasPrefix("ma-daily-") && name.contains(".partial") {
                try? fm.removeItem(at: Self.folder.appendingPathComponent(name))
            }
        }
        if all.count > Self.keep { Self.blog.info("backup pruned \(all.count - Self.keep, privacy: .public) old file(s)") }
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
