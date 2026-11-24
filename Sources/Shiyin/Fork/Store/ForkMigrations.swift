import GRDB

/// fork 的 migration（fork design §F-DB）：名稱 `ma_` 開頭，只新增、不改、不刪；在上游的 migration 全部註冊完之後才註冊。
/// GRDB 依名稱判斷跑過沒有：4.7.6 以前 `ma_speaker_tags_v1` 註冊在上游 v9、v10 之間，已經跑過的資料庫不會重跑，
/// 新的資料庫在上游最後一個之後才建 `speaker_tags`，結果一樣（`scripts/dev/check-fork-migrations.py` 驗證）
enum ForkMigrations {
    static func register(_ migrator: inout DatabaseMigrator) {
        // F2 說話者標記（fork design §F2.1）。Fork 舊版 v8 是 speaker_tags，上游 v8 是 min_speakers；兩種資料庫都要補齊。
        // 已經發布，內容不能改
        migrator.registerMigration("ma_speaker_tags_v1") { db in
            if try !db.columns(in: "meetings").contains(where: { $0.name == "min_speakers" }) {
                try db.execute(sql: "ALTER TABLE meetings ADD COLUMN min_speakers INTEGER")
            }
            try db.execute(sql: """
                CREATE TABLE IF NOT EXISTS speaker_tags (
                  id         INTEGER PRIMARY KEY AUTOINCREMENT,
                  meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
                  start      REAL NOT NULL,
                  end        REAL NOT NULL,
                  name       TEXT NOT NULL,
                  kind       TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS speaker_tags_meeting ON speaker_tags(meeting_id);
                """)
        }
        // F2.13 編輯會議（上游 R107）的快照也存標記（fork design §F-DB.2）：跟著上游的 meeting_edits 一起刪
        migrator.registerMigration("ma_meeting_edit_tags_v1") { db in
            try db.execute(sql: """
                CREATE TABLE ma_meeting_edit_tags (
                  meeting_id INTEGER PRIMARY KEY REFERENCES meeting_edits(meeting_id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
                  tags_json  TEXT NOT NULL
                );
                """)
        }
        // F12 聲紋的來源（fork design §F12.4、DF14）：外鍵指到上游的 voiceprints，聲紋刪了紀錄跟著刪；
        // pending 是上游存聲紋之前記下的，事後對到聲紋的 id
        migrator.registerMigration("ma_voiceprint_source_v1") { db in
            try db.execute(sql: """
                CREATE TABLE ma_voiceprint_source (
                  voiceprint_id INTEGER PRIMARY KEY REFERENCES voiceprints(id) ON DELETE CASCADE,
                  source        TEXT NOT NULL,
                  warned        INTEGER NOT NULL DEFAULT 0,
                  recorded_at   TEXT NOT NULL
                );
                CREATE TABLE ma_voiceprint_pending (
                  meeting_id  INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
                  speaker_idx INTEGER NOT NULL,
                  source      TEXT NOT NULL,
                  warned      INTEGER NOT NULL DEFAULT 0,
                  recorded_at TEXT NOT NULL,
                  PRIMARY KEY (meeting_id, speaker_idx)
                );
                """)
        }
        // F12.15 重新轉錄後名字跟著聲音（fork design §F12.9、DF15）：存檔後待處理的結果（跟 saveTranscript 同一筆交易寫入）、
        // 對不上的舊名字建議；fingerprint 是說話者指紋，不合就表示說的不是現在這批說話者
        migrator.registerMigration("ma_retranscribe_v1") { db in
            try db.execute(sql: """
                CREATE TABLE ma_retranscribe_pending (
                  meeting_id  INTEGER PRIMARY KEY REFERENCES meetings(id) ON DELETE CASCADE,
                  fingerprint TEXT NOT NULL,
                  payload     TEXT NOT NULL,
                  created_at  TEXT NOT NULL
                );
                CREATE TABLE ma_retranscribe_suggestion (
                  meeting_id  INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
                  speaker_idx INTEGER NOT NULL,
                  name        TEXT NOT NULL,
                  fingerprint TEXT NOT NULL,
                  created_at  TEXT NOT NULL,
                  PRIMARY KEY (meeting_id, speaker_idx)
                );
                """)
        }
    }
}
