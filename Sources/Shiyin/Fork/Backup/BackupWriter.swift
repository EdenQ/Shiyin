import Darwin
import Foundation
import GRDB
import SQLite3

/// F10 寫入目的地（fork design §F10.1a，REVIEW-F10b P2-3）：只寫進這次自己用 O_EXCL | O_NOFOLLOW 新建的一般檔。
/// 目的地不交給 GRDB 用路徑開（GRDB 沒有 SQLITE_OPEN_NOFOLLOW，SQLite 會跟著連結把別的檔覆寫掉）
enum BackupWriter {
    typealias Failure = ForkBackup.Failure

    static let sidecars = ["-wal", "-shm", "-journal"]

    /// 背景執行。成功時回傳正式備份的位置
    static func write(db: AppDatabase, folder: URL, stamp: String, simulateFail: Bool, simulateDelay: Double) -> Result<URL, Failure> {
        let partialName = "ma-daily-\(stamp).partial"
        let finalName = "ma-daily-\(stamp).sqlite"
        let partialPath = folder.appendingPathComponent(partialName).path

        // 1. daily 是真的資料夾（不是連結），之後都用它的 fd
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        } catch {
            return .failure(Failure(reason: String(localized: "建立備份資料夾失敗"), log: "create folder: \((error as NSError).code)"))
        }
        var st = stat()
        guard lstat(folder.path, &st) == 0, isDirectory(st) else {
            return .failure(Failure(reason: String(localized: "備份資料夾不是一般的資料夾"), log: "daily is not a directory"))
        }
        let dirfd = open(folder.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard dirfd >= 0 else {
            return .failure(Failure(reason: String(localized: "備份資料夾不是一般的資料夾"), log: "open daily: errno \(errno)"))
        }
        defer { close(dirfd) }

        // 2. 這次的檔名上以前留下的一般殘檔刪掉；之後四個名字還有任何東西（連結、資料夾…）就失敗，原物件不刪、不寫
        for name in [partialName] + sidecars.map({ partialName + $0 }) where entryType(dirfd, name) == .regular {
            unlinkat(dirfd, name, 0)
        }
        for name in [partialName] + sidecars.map({ partialName + $0 }) where entryType(dirfd, name) != .absent {
            return .failure(Failure(reason: String(localized: "暫存檔的位置已經有別的東西"), log: "partial path occupied"))
        }
        guard entryType(dirfd, finalName) == .absent else {
            return .failure(Failure(reason: String(localized: "同名的備份已經存在"), log: "file exists"))
        }

        // 3. 排他、不跟著連結新建這次的暫存檔，記下 dev／inode
        let fd = openat(dirfd, partialName, O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard fd >= 0 else {
            return .failure(Failure(reason: String(localized: "建立暫存檔失敗"), log: "create partial: errno \(errno)"))
        }
        defer { close(fd) }
        var created = stat()
        guard fstat(fd, &created) == 0, isRegular(created) else {
            unlinkIfSame(dirfd, partialName, created)
            return .failure(Failure(reason: String(localized: "建立暫存檔失敗"), log: "fstat partial"))
        }

        /// 路徑（經過資料夾的路徑和資料夾的 fd 兩種）都還是剛剛建的那個一般檔
        func stillOurs() -> Bool {
            var byPath = stat(), byDir = stat()
            return lstat(partialPath, &byPath) == 0 && same(byPath, created)
                && fstatat(dirfd, partialName, &byDir, AT_SYMLINK_NOFOLLOW) == 0 && same(byDir, created)
        }
        func sidecarsAbsent() -> Bool { sidecars.allSatisfy { entryType(dirfd, partialName + $0) == .absent } }
        let replaced = Failure(reason: String(localized: "暫存檔在寫入時被換掉了"), log: "partial replaced")

        do {
            // 4. SQLite 開這次的檔：不跟著連結、不建立；開完核對是同一個檔
            var dest: OpaquePointer?
            var rc = sqlite3_open_v2(partialPath, &dest, SQLITE_OPEN_READWRITE | SQLITE_OPEN_NOFOLLOW, nil)
            guard rc == SQLITE_OK, let dest else {
                sqlite3_close_v2(dest)
                throw sqliteFailure(rc)
            }
            do {
                guard stillOurs() else { throw replaced }
                // 5. 不建 -journal；複製完不再下指令（檔頭這時是來源的 WAL 標記）
                try exec(dest, "PRAGMA journal_mode=OFF")
                try db.pool.read { source in
                    guard let src = source.sqliteConnection, let backup = sqlite3_backup_init(dest, "main", src, "main") else {
                        throw sqliteFailure(sqlite3_errcode(dest))
                    }
                    let step = sqlite3_backup_step(backup, -1)
                    let finish = sqlite3_backup_finish(backup)
                    guard step == SQLITE_DONE, finish == SQLITE_OK else { throw sqliteFailure(step == SQLITE_DONE ? finish : step) }
                }
            } catch {
                sqlite3_close_v2(dest)
                throw error
            }
            rc = sqlite3_close_v2(dest)
            guard rc == SQLITE_OK else { throw sqliteFailure(rc) }
            if simulateDelay > 0 { Thread.sleep(forTimeInterval: simulateDelay) }
            if simulateFail { throw Failure(reason: "simulated failure (DEBUG)", log: "simulated failure") }
            guard stillOurs(), sidecarsAbsent() else { throw replaced }

            // 6. 用自己的 fd 把檔頭改成 rollback 模式（第 18、19 位元組 2 → 1）
            try setRollbackHeader(fd)

            // 7. 唯讀、不跟著連結驗證
            var verify: OpaquePointer?
            rc = sqlite3_open_v2(partialPath, &verify, SQLITE_OPEN_READONLY | SQLITE_OPEN_NOFOLLOW, nil)
            guard rc == SQLITE_OK, let verify else {
                sqlite3_close_v2(verify)
                throw sqliteFailure(rc)
            }
            let check: (lines: [String], mode: [String])
            do {
                guard stillOurs() else { throw replaced }
                check = (try query(verify, "PRAGMA integrity_check"), try query(verify, "PRAGMA journal_mode"))
            } catch {
                sqlite3_close_v2(verify)
                throw error
            }
            sqlite3_close_v2(verify)
            guard check.lines == ["ok"] else {
                throw Failure(reason: String(localized: "備份的完整性檢查沒有通過"), log: "integrity_check: \(check.lines.count) lines")
            }
            guard check.mode == ["delete"] else {
                throw Failure(reason: String(localized: "備份的完整性檢查沒有通過"), log: "journal_mode: \(check.mode.first ?? "")")
            }
            guard stillOurs(), sidecarsAbsent() else { throw replaced }

            // 8. 改名：正式檔名有任何東西（含斷掉的連結）就失敗，不覆蓋
            guard renameatx_np(dirfd, partialName, dirfd, finalName, UInt32(RENAME_EXCL)) == 0 else {
                let code = errno
                throw code == EEXIST
                    ? Failure(reason: String(localized: "同名的備份已經存在"), log: "file exists")
                    : Failure(reason: String(localized: "寫入備份失敗"), log: "rename: errno \(code)")
            }
            return .success(folder.appendingPathComponent(finalName))
        } catch {
            // 9. 只刪還是同一個 inode 的暫存檔；旁檔只刪一般檔
            unlinkIfSame(dirfd, partialName, created)
            for name in sidecars.map({ partialName + $0 }) where entryType(dirfd, name) == .regular {
                unlinkat(dirfd, name, 0)
            }
            if let failure = error as? Failure { return .failure(failure) }
            return .failure(Failure(reason: String(localized: "寫入備份失敗"), log: "file: \((error as NSError).domain) \((error as NSError).code)"))
        }
    }

    // MARK: 小工具

    enum EntryType { case absent, regular, other }

    /// fstatat（不跟著連結）：沒有、一般檔、其他（連結、資料夾…；讀不到也算其他，不能當成沒有）
    static func entryType(_ dirfd: Int32, _ name: String) -> EntryType {
        var st = stat()
        if fstatat(dirfd, name, &st, AT_SYMLINK_NOFOLLOW) == 0 { return isRegular(st) ? .regular : .other }
        return errno == ENOENT ? .absent : .other
    }

    static func isRegular(_ st: stat) -> Bool { (st.st_mode & S_IFMT) == S_IFREG }
    static func isDirectory(_ st: stat) -> Bool { (st.st_mode & S_IFMT) == S_IFDIR }
    static func same(_ a: stat, _ b: stat) -> Bool { isRegular(a) && a.st_dev == b.st_dev && a.st_ino == b.st_ino }

    static func unlinkIfSame(_ dirfd: Int32, _ name: String, _ created: stat) {
        var st = stat()
        if fstatat(dirfd, name, &st, AT_SYMLINK_NOFOLLOW) == 0, same(st, created) { unlinkat(dirfd, name, 0) }
    }

    static func sqliteFailure(_ code: Int32) -> Failure {
        Failure(reason: String(localized: "資料庫錯誤（\(code)）"), log: "sqlite \(code)")
    }

    static func exec(_ db: OpaquePointer, _ sql: String) throws {
        let rc = sqlite3_exec(db, sql, nil, nil, nil)
        guard rc == SQLITE_OK else { throw sqliteFailure(rc) }
    }

    static func query(_ db: OpaquePointer, _ sql: String) throws -> [String] {
        var statement: OpaquePointer?
        var rc = sqlite3_prepare_v2(db, sql, -1, &statement, nil)
        guard rc == SQLITE_OK, let statement else { throw sqliteFailure(rc) }
        defer { sqlite3_finalize(statement) }
        var rows: [String] = []
        while true {
            rc = sqlite3_step(statement)
            if rc == SQLITE_DONE { return rows }
            guard rc == SQLITE_ROW else { throw sqliteFailure(rc) }
            rows.append(sqlite3_column_text(statement, 0).map { String(cString: $0) } ?? "")
        }
    }

    /// SQLite 檔頭第 18、19 位元組是 file format write／read version：2 是 WAL、1 是 rollback journal
    static func setRollbackHeader(_ fd: Int32) throws {
        var header = [UInt8](repeating: 0, count: 20)
        let bad = Failure(reason: String(localized: "備份的完整性檢查沒有通過"), log: "header")
        guard pread(fd, &header, 20, 0) == 20, Array(header[0..<16]) == Array("SQLite format 3\0".utf8) else { throw bad }
        guard header[18] != 1 || header[19] != 1 else { return }
        guard header[18] <= 2, header[19] <= 2 else { throw bad }
        var rollback: [UInt8] = [1, 1]
        guard pwrite(fd, &rollback, 2, 18) == 2, fsync(fd) == 0 else {
            throw Failure(reason: String(localized: "寫入備份失敗"), log: "header write: errno \(errno)")
        }
    }
}
