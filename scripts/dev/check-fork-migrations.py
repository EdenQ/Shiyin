#!/usr/bin/env python3
"""MA fork 合併的回歸檢查：使用實際 Swift migrator，測試兩種舊 v8 資料庫與說話者標記。

先完成 DEBUG 建置，再執行：python3 scripts/dev/check-fork-migrations.py
只使用暫存資料庫，不啟動 App、不讀取使用者資料。
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

helpers = source[source.index('    private static let metaRowidBase:'):source.index('    func rebuildSearchIndex()')]
search_hit = source[source.index('struct SearchHit:'):source.index('final class AppDatabase:')]

HARNESS = r'''
import Foundation
import GRDB

__SEARCH_HIT__
enum AppMigrations {
    static func make() -> DatabaseMigrator {
__APP_MIGRATOR__
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
for scenario in ["fresh", "v7", "fork-v8", "upstream-v8", "upstream-v9"] {
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
    } else if scenario == "upstream-v8" || scenario == "upstream-v9" {
        try migrator.migrate(queue, upTo: scenario == "upstream-v8" ? "v8" : "v9")
        try queue.write { db in try db.execute(sql: "UPDATE meetings SET min_speakers = 3 WHERE id = 1") }
        if scenario == "upstream-v9" {
            try queue.write { db in try db.execute(sql: "UPDATE segments SET speaker_manual = 1 WHERE meeting_id = 1") }
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
        require(try String.fetchOne(db, sql: "PRAGMA integrity_check") == "ok", "Integrity check failed")
        require(try Row.fetchAll(db, sql: "PRAGMA foreign_key_check").isEmpty, "Foreign key check failed")
        let count = try Int.fetchOne(db, sql: "SELECT COUNT(*) FROM speaker_tags")
        require(count == (scenario == "fork-v8" ? 1 : 0), "Tag data changed")
        if scenario != "fresh" {
            require(try String.fetchOne(db, sql: "SELECT audio_file FROM meetings WHERE id = 1") == "1.wav", "Audio link lost")
            require(try String.fetchOne(db, sql: "SELECT notes FROM meetings WHERE id = 1") == "{\"summary\":\"retained\"}", "Notes lost")
            require(try String.fetchOne(db, sql: "SELECT text FROM segments WHERE meeting_id = 1") == "Retained transcript", "Transcript lost")
            require(try String.fetchOne(db, sql: "SELECT name FROM speakers WHERE meeting_id = 1") == "Fixture person", "Speaker lost")
        }
        if scenario.hasPrefix("upstream") {
            require(try Int.fetchOne(db, sql: "SELECT min_speakers FROM meetings WHERE id = 1") == 3, "Speaker count lost")
        }
        if scenario == "upstream-v9" {
            require(try Int.fetchOne(db, sql: "SELECT speaker_manual FROM segments WHERE meeting_id = 1") == 1, "Manual speaker edit lost")
        }
    }
    print("PASS migration: \(scenario) + reopen; data retained")
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
    swift.write_text(HARNESS.replace('__APP_MIGRATOR__', match.group(1))
                     .replace('__SEARCH_HELPERS__', helpers).replace('__SEARCH_HIT__', search_hit))
    # Only Meeting is needed by the migration search helpers. Omit its UI-only
    # diarization-quality property so this database test does not load audio engines.
    records = (ROOT/'Sources/Shiyin/Model/Records.swift').read_text().split('struct Segment:', 1)[0]
    records = re.sub(r'^    var mayHaveMergedSpeakers:.*\n', '', records, flags=re.M)
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
                    *[str(ROOT/name) for name in ['Sources/Shiyin/Model/SpeakerTagging.swift',
                        'Sources/Shiyin/Model/MeetingNotes.swift',
                        'Sources/Shiyin/Model/MeetingLanguage.swift', 'Sources/Shiyin/Services/Paths.swift']],
                    str(model), str(obj), '-lsqlite3',
                    '-o', str(executable)], check=True)
    subprocess.run([str(executable), str(work)], check=True)
