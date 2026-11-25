#!/usr/bin/env python3
"""MA fork 合併的回歸檢查：使用實際 Swift migrator，測試兩種舊 v8 資料庫與說話者標記（fork design §F-DB）。

情境：全新、v7、fork 舊 v8、上游 v8／v9／v10／v15（從沒裝過 fork）、fork 4.7.6（用 4.7.6 的 migrator 跑完）；
升級後重新開啟；降回 4.7.6 的 migrator 再寫入、再升回來；ma_meeting_edit_tags 跟著 meeting_edits 刪。
先完成 DEBUG 建置，再執行：python3 scripts/dev/check-fork-migrations.py [--scratch-path <建置暫存>]
只使用暫存資料庫，不啟動 App、不讀取使用者資料。4.7.6 的 migrator 從 git 的 v4.7.6 tag 讀。
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--scratch-path', type=Path, default=Path.home() / 'Library/Caches/ShiyinBuild')
args = parser.parse_args()
source = (ROOT / 'Sources/Shiyin/Store/AppDatabase.swift').read_text()
match = re.search(r'private static var migrator: DatabaseMigrator \{\n(.*?)\n    \}\n', source, re.S)
if not match:
    raise SystemExit('Cannot locate the app migrator')
old_source = subprocess.run(['git', '-C', str(ROOT), 'show', 'v4.7.6:Sources/Shiyin/Store/AppDatabase.swift'],
                            capture_output=True, text=True, check=True).stdout
old_match = re.search(r'private static var migrator: DatabaseMigrator \{\n(.*?)\n    \}\n', old_source, re.S)
if not old_match:
    raise SystemExit('Cannot locate the 4.7.6 migrator')

helpers = source[source.index('    private static let metaRowidBase:'):source.index('    func rebuildSearchIndex()')]
search_hit = source[source.index('struct SearchHit:'):source.index('final class AppDatabase:')]

HARNESS = r'''
import Foundation
import GRDB
import os

let log = Logger(subsystem: "com.weiwei.shiyin.fork-regression", category: "test")

__SEARCH_HIT__
// 測試替身：只給 MeetingLanguage 用（5.0 的簡體設定），不讀 UserDefaults
enum AppSettings {
    static func script(_ text: String, for language: MeetingLanguage) -> String { text }
    static func simplifiedChinese(for language: MeetingLanguage) -> Bool { false }
}
enum AppMigrations {
    static func make() -> DatabaseMigrator {
__APP_MIGRATOR__
    }
    // v14 換側欄設定的鍵：測試不寫 UserDefaults
    static var seriesKeysReplaced: [Int64: String] = [:]
    static func replaceSeriesKeys(_ names: [Int64: String]) { seriesKeysReplaced = names }
__SEARCH_HELPERS__
}
enum OldForkMigrations {
    static func make() -> DatabaseMigrator {
__OLD_MIGRATOR__
    }
__SEARCH_HELPERS__
}

// Historical fork v8 fixture: this migration name used to create only speaker_tags.
func legacyTags(_ db: Database) throws {
    try db.execute(sql: """
        CREATE TABLE speaker_tags (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
          start REAL NOT NULL, end REAL NOT NULL, name TEXT NOT NULL,
          kind TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX speaker_tags_meeting ON speaker_tags(meeting_id);
        """)
}

func require(_ value: Bool, _ message: String) {
    precondition(value, message)
}

let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
for scenario in ["fresh", "v7", "fork-v8", "upstream-v8", "upstream-v9", "upstream-v10", "upstream-v15", "fork-476"] {
    let path = directory.appendingPathComponent(scenario + ".sqlite").path
    var config = Configuration()
    config.foreignKeysEnabled = true
    var queue = try DatabaseQueue(path: path, configuration: config)
    let migrator = AppMigrations.make()
    if scenario != "fresh" {
        try migrator.migrate(queue, upTo: "v7")
        try queue.write { db in
            try db.execute(sql: """
                INSERT INTO meetings (id, title, meeting_date, source_filename, audio_file, created_at, updated_at, notes)
                VALUES (1, 'Fixture meeting', '2026-10-24', 'fixture.wav', '1.wav', '2026-10-24', '2026-10-24', '{"summary":"retained"}');
                INSERT INTO segments (meeting_id, seq, start, end, text, speaker) VALUES (1, 0, 0, 4, 'Retained transcript', 1);
                INSERT INTO speakers (meeting_id, idx, name) VALUES (1, 1, 'Fixture person');
                """)
        }
    }
    if scenario == "fork-v8" {
        var old = DatabaseMigrator()
        old.registerMigration("v8") { db in try legacyTags(db) }
        try old.migrate(queue)
        try queue.write { db in
            try db.execute(sql: """
                INSERT INTO speaker_tags (meeting_id, start, end, name, kind, created_at)
                VALUES (1, 0, 4, 'Fixture person', 'line', '2026-10-24');
                """)
        }
    } else if scenario == "fork-476" {
        // fork 4.7.6 的使用者：用 4.7.6 的 migrator 全部跑完（v1～v9、ma_speaker_tags_v1、v10），放標記、文件、資料夾
        try OldForkMigrations.make().migrate(queue)
        try queue.write { db in
            try db.execute(sql: """
                INSERT INTO speaker_tags (meeting_id, start, end, name, kind, created_at) VALUES (1, 0, 4, 'Fixture person', 'line', '2026-11-16');
                INSERT INTO documents (meeting_id, name, file, kind, pages, created_at) VALUES (1, 'Fixture document', 'fixture.txt', 'text', '["Retained document"]', '2026-11-16');
                UPDATE meetings SET folder = 'Fixture folder', min_speakers = 3 WHERE id = 1;
                UPDATE segments SET speaker_manual = 1 WHERE meeting_id = 1;
                """)
        }
    } else if scenario.hasPrefix("upstream-") {
        try migrator.migrate(queue, upTo: String(scenario.dropFirst("upstream-".count)))
        try queue.write { db in try db.execute(sql: "UPDATE meetings SET min_speakers = 3 WHERE id = 1") }
        if scenario != "upstream-v8" {
            try queue.write { db in try db.execute(sql: "UPDATE segments SET speaker_manual = 1 WHERE meeting_id = 1") }
        }
        if scenario == "upstream-v10" || scenario == "upstream-v15" {
            // 模擬上游已升級、從未安裝 fork 的資料庫（fork 的 migration 在上游全部之後，upTo 不會跑到）
            try queue.write { db in
                require(try !db.tableExists("speaker_tags"), "Fork table created before upstream finished")
            }
        }
        if scenario == "upstream-v10" {
            // 模擬上游已升級 v10、從未安裝 fork 的資料庫；保留真實的文件資料。
            try queue.write { db in
                try db.execute(sql: """
                    DROP TABLE IF EXISTS speaker_tags;
                    DELETE FROM grdb_migrations WHERE identifier = 'ma_speaker_tags_v1';
                    INSERT INTO documents (meeting_id, name, file, kind, pages, created_at)
                    VALUES (1, 'Fixture document', 'fixture.txt', 'text', '["Retained document"]', '2026-11-05');
                    """)
            }
        }
    }
    try migrator.migrate(queue)
    // Reopen the database and migrate again, catching duplicate-column/table failures.
    queue = try DatabaseQueue(path: path, configuration: config)
    try migrator.migrate(queue)
    try queue.read { db in
        let applied = try migrator.appliedIdentifiers(db)
        require(Set(migrator.migrations).isSubset(of: applied), "Pending migrations: \(scenario)")
        require(try db.columns(in: "meetings").contains { $0.name == "min_speakers" }, "Missing upstream column")
        require(try db.columns(in: "segments").contains { $0.name == "speaker_manual" }, "Missing upstream speaker edits")
        require(try db.tableExists("speaker_tags"), "Missing fork tags")
        require(try db.tableExists("speaker_undo"), "Missing upstream undo")
        require(try db.tableExists("documents"), "Missing upstream documents")
        require(try db.tableExists("ma_meeting_edit_tags"), "Missing fork edit snapshot table")
        require(try db.tableExists("ma_voiceprint_source") && db.tableExists("ma_voiceprint_pending"), "Missing fork voiceprint source tables")
        require(try db.tableExists("ma_retranscribe_pending") && db.tableExists("ma_retranscribe_suggestion"), "Missing fork retranscribe tables")
        require(try db.tableExists("ma_meeting_edit_retranscribe") && db.columns(in: "ma_retranscribe_suggestion").contains { $0.name == "speaker_hash" }, "Missing fork retranscribe v2")
        require(migrator.migrations.suffix(5) == ["ma_speaker_tags_v1", "ma_meeting_edit_tags_v1", "ma_voiceprint_source_v1", "ma_retranscribe_v1", "ma_retranscribe_v2"], "Fork migrations are not last")
        require(try String.fetchOne(db, sql: "PRAGMA integrity_check") == "ok", "Integrity check failed")
        require(try Row.fetchAll(db, sql: "PRAGMA foreign_key_check").isEmpty, "Foreign key check failed")
        let count = try Int.fetchOne(db, sql: "SELECT COUNT(*) FROM speaker_tags")
        require(count == (scenario == "fork-v8" || scenario == "fork-476" ? 1 : 0), "Tag data changed")
        if scenario != "fresh" {
            require(try String.fetchOne(db, sql: "SELECT audio_file FROM meetings WHERE id = 1") == "1.wav", "Audio link lost")
            require(try String.fetchOne(db, sql: "SELECT notes FROM meetings WHERE id = 1") == "{\"summary\":\"retained\"}", "Notes lost")
            require(try String.fetchOne(db, sql: "SELECT text FROM segments WHERE meeting_id = 1") == "Retained transcript", "Transcript lost")
            require(try String.fetchOne(db, sql: "SELECT name FROM speakers WHERE meeting_id = 1") == "Fixture person", "Speaker lost")
        }
        if scenario.hasPrefix("upstream") {
            require(try Int.fetchOne(db, sql: "SELECT min_speakers FROM meetings WHERE id = 1") == 3, "Speaker count lost")
        }
        if scenario == "upstream-v9" || scenario == "upstream-v10" {
            require(try Int.fetchOne(db, sql: "SELECT speaker_manual FROM segments WHERE meeting_id = 1") == 1, "Manual speaker edit lost")
        }
        if scenario == "fork-476" {
            require(try String.fetchOne(db, sql: "SELECT name FROM folders") == "Fixture folder", "Folder not migrated (v13)")
            require(try db.tableExists("meeting_edits") && db.tableExists("clean_lines") && db.tableExists("folder_rules"), "Missing v11-v15 tables")
            require(try Int.fetchOne(db, sql: "SELECT min_speakers FROM meetings WHERE id = 1") == 3, "Speaker count lost")
            require(try Int.fetchOne(db, sql: "SELECT speaker_manual FROM segments WHERE meeting_id = 1") == 1, "Manual speaker edit lost")
        }
        if scenario == "upstream-v10" || scenario == "fork-476" {
            require(try String.fetchOne(db, sql: "SELECT pages FROM documents WHERE meeting_id = 1") == "[\"Retained document\"]", "Document lost")
        }
    }
    if scenario != "fresh" {
        // 編輯會議的標記快照（F2.13）：先寫快照、交易結束前才有 meeting_edits（延後檢查的外鍵）；刪 meeting_edits 時跟著刪
        try queue.write { db in
            try db.execute(sql: "INSERT INTO ma_meeting_edit_tags (meeting_id, tags_json) VALUES (1, '[]')")
            try db.execute(sql: "INSERT INTO meeting_edits (meeting_id, snapshot, audio_file, created_at, edited_at) VALUES (1, '{}', '', 'x', 'x')")
        }
        try queue.write { db in
            try db.execute(sql: "INSERT INTO ma_meeting_edit_retranscribe (meeting_id, snapshot_json) VALUES (1, '{}')")
        }
        try queue.write { db in try db.execute(sql: "DELETE FROM meeting_edits WHERE meeting_id = 1") }
        try queue.read { db in
            require(try Int.fetchOne(db, sql: "SELECT COUNT(*) FROM ma_meeting_edit_tags") == 0, "Edit tag snapshot not cascaded")
            require(try Int.fetchOne(db, sql: "SELECT COUNT(*) FROM ma_meeting_edit_retranscribe") == 0, "Edit retranscribe snapshot not cascaded")
            require(try Row.fetchAll(db, sql: "PRAGMA foreign_key_check").isEmpty, "Foreign key check failed after edit snapshot")
        }
    }
    // F12 聲紋的來源（§F12.4、§F12.6）：聲紋刪了來源跟著刪；會議刪了 pending 跟著刪
    try queue.write { db in
        try db.execute(sql: "INSERT INTO people (name, created_at) VALUES ('F12 fixture', 'x')")
        let person = db.lastInsertedRowID
        try db.execute(sql: "INSERT INTO voiceprints (person_id, embedding, audio_source, meeting_id, speaker_idx, created_at) VALUES (?, x'00000000', 'mix', NULL, NULL, 'x')", arguments: [person])
        try db.execute(sql: "INSERT INTO ma_voiceprint_source (voiceprint_id, source, warned, recorded_at) VALUES (?, 'manual', 0, 'x')", arguments: [db.lastInsertedRowID])
        try db.execute(sql: "INSERT INTO meetings (title, meeting_date, source_filename, audio_file, created_at, updated_at) VALUES ('F12', '2026-11-24', 'f.wav', 'f.wav', 'x', 'x')")
        let meeting = db.lastInsertedRowID
        try db.execute(sql: "INSERT INTO ma_voiceprint_pending (meeting_id, speaker_idx, source, warned, recorded_at) VALUES (?, 1, 'manual', 0, 'x')", arguments: [meeting])
        try db.execute(sql: "INSERT INTO ma_retranscribe_pending (meeting_id, fingerprint, payload, created_at) VALUES (?, 'f', '{}', 'x')", arguments: [meeting])
        try db.execute(sql: "INSERT INTO ma_retranscribe_suggestion (meeting_id, speaker_idx, name, fingerprint, created_at) VALUES (?, 1, 'n', 'f', 'x')", arguments: [meeting])
        try db.execute(sql: "DELETE FROM people WHERE id = ?", arguments: [person])
        try db.execute(sql: "DELETE FROM meetings WHERE id = ?", arguments: [meeting])
    }
    try queue.read { db in
        require(try Int.fetchOne(db, sql: "SELECT COUNT(*) FROM ma_voiceprint_source") == 0, "Voiceprint source not cascaded")
        require(try Int.fetchOne(db, sql: "SELECT COUNT(*) FROM ma_voiceprint_pending") == 0, "Voiceprint pending not cascaded")
        require(try Int.fetchOne(db, sql: "SELECT COUNT(*) FROM ma_retranscribe_pending") == 0, "Retranscribe pending not cascaded")
        require(try Int.fetchOne(db, sql: "SELECT COUNT(*) FROM ma_retranscribe_suggestion") == 0, "Retranscribe suggestion not cascaded")
        require(try Row.fetchAll(db, sql: "PRAGMA foreign_key_check").isEmpty, "Foreign key check failed after voiceprint source")
    }
    print("PASS migration: \(scenario) + reopen; data retained")
    if scenario == "fork-476" || scenario == "fresh" {
        // 降回 4.7.6：舊 migrator 開升級後的資料庫（v11～v15、ma_meeting_edit_tags_v1 對它是不認得的 migration）
        let old = OldForkMigrations.make()
        let back = try DatabaseQueue(path: path, configuration: config)
        try old.migrate(back)
        try back.write { db in
            try db.execute(sql: "INSERT INTO meetings (title, meeting_date, source_filename, audio_file, created_at, updated_at) VALUES ('After downgrade', '2026-11-18', 'b.wav', 'b.wav', '2026-11-18', '2026-11-18')")
            let mid = db.lastInsertedRowID
            try db.execute(sql: "INSERT INTO segments (meeting_id, seq, start, end, text, speaker) VALUES (?, 0, 0, 1, 'x', 1)", arguments: [mid])
            try db.execute(sql: "INSERT INTO speaker_tags (meeting_id, start, end, name, kind, created_at) VALUES (?, 0, 1, 'Downgrade', 'now', 'x')", arguments: [mid])
            try db.execute(sql: "UPDATE segments SET text = 'edited' WHERE meeting_id = ?", arguments: [mid])
            try db.execute(sql: "DELETE FROM meetings WHERE id = ?", arguments: [mid])
        }
        try back.read { db in
            require(try String.fetchOne(db, sql: "PRAGMA integrity_check") == "ok", "Integrity after downgrade")
            require(try Row.fetchAll(db, sql: "PRAGMA foreign_key_check").isEmpty, "FK after downgrade")
            require(Set(old.migrations).isSubset(of: try old.appliedIdentifiers(db)), "Old migrator pending after downgrade")
        }
        let again = try DatabaseQueue(path: path, configuration: config)
        try migrator.migrate(again)
        print("PASS downgrade to fork 4.7.6 migrator: \(scenario) opens, writes, deletes, FK/integrity ok; re-upgrade ok")
    }
}

struct Span: SpeakerSpan {
    var id: Int64?
    var start: Double
    var end: Double
    var speaker: Int?
}
let spans = [Span(id: 1, start: 0, end: 3, speaker: 1), Span(id: 2, start: 3, end: 4, speaker: 2)]
let tag = SpeakerTagging.Tag(start: 0, end: 4, name: "Alice")
require(SpeakerTagging.match(tag, in: spans).speaker == 1, "Dominant speaker not matched")
let ambiguous = SpeakerTagging.Tag(start: 2, end: 4, name: "Alice")
require(SpeakerTagging.match(ambiguous, in: spans).speaker == nil, "Ambiguous tag assigned")
let silence = SpeakerTagging.Tag(start: 10, end: 11, name: "Alice")
require(SpeakerTagging.match(silence, in: spans).speaker == nil, "Silent tag assigned")
let conflicting = [tag, SpeakerTagging.Tag(start: 0, end: 2, name: "Bob")]
require(SpeakerTagging.names(for: conflicting, in: spans, candidates: [1, 2]).isEmpty, "Conflicting names assigned")
require(SpeakerTagging.names(for: [tag], in: spans, candidates: [2]).isEmpty, "Manual speaker name overwritten")
require(SpeakerTagging.names(for: [tag], in: spans, candidates: [1])[1] == "Alice", "Valid name not assigned")
require(SpeakerTagging.roster(participants: ["Alice"], tagged: [" alice ", "Bob"]) == ["Alice", "Bob"], "Roster deduplication changed")
print("PASS speaker tagging: dominant, ambiguous, silence, conflicting names, manual names, valid names, roster")
'''

with tempfile.TemporaryDirectory(prefix='ma-fork-regression-') as work:
    work = Path(work)
    swift = work / 'main.swift'
    swift.write_text(HARNESS.replace('__APP_MIGRATOR__', match.group(1)).replace('__OLD_MIGRATOR__', old_match.group(1))
                     .replace('__SEARCH_HELPERS__', helpers).replace('__SEARCH_HIT__', search_hit))
    # Only Meeting is needed by the migration search helpers. Omit its UI-only
    # diarization-quality property so this database test does not load audio engines.
    records = (ROOT/'Sources/Shiyin/Model/Records.swift').read_text().split('struct Segment:', 1)[0]
    records = re.sub(r'^    var mayHaveMergedSpeakers:.*\n', '', records, flags=re.M)
    # 上游 5.1 起搜尋索引的 helper 也收畫面（indexScreen 用 MeetingDocument，design §83.1）：一起帶上文件的型別
    full_records = (ROOT/'Sources/Shiyin/Model/Records.swift').read_text()
    doc = re.search(r'^enum DocumentKind\b.*?^struct MeetingDocument\b.*?^}\n', full_records, re.S | re.M)
    if doc:
        records += '\n' + doc.group(0)
    model = work/'MigrationRecords.swift'
    model.write_text(records)
    products = args.scratch_path / 'debug'
    grdb = args.scratch_path / 'checkouts/GRDB.swift/Sources/GRDBSQLite'
    obj = products / 'GRDB.o'
    if not obj.exists():
        raise SystemExit('Missing DEBUG GRDB.o; run the DEBUG build first')
    executable = work / 'check-fork-migrations'
    subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', '-module-cache-path', str(work/'modules'),
                    '-I', str(products), '-I', str(grdb), str(swift),
                    *[str(ROOT/name) for name in ['Sources/Shiyin/Fork/SpeakerTags/SpeakerTagging.swift',
                        'Sources/Shiyin/Model/MeetingNotes.swift',
                        'Sources/Shiyin/Model/MeetingLanguage.swift', 'Sources/Shiyin/Services/Paths.swift',
                        'Sources/Shiyin/Services/DesktopApps.swift', 'Sources/Shiyin/Transcribe/ChineseScript.swift',
                        'Sources/Shiyin/Fork/Store/ForkMigrations.swift']],
                    str(model), str(obj), '-lsqlite3',
                    '-o', str(executable)], check=True)
    subprocess.run([str(executable), str(work)], check=True)
