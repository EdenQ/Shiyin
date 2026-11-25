# 會議助手（fork）：設計

> 上游的設計在 `docs/design.md`（§數字、D#），**照上游原樣、fork 不改**。這份寫 fork 自己的設計（§F#、DF#）、fork 對上游設計的補充（§F-UP，引用上游的節號）、資料庫規則（§F-DB）。
> 需求在 `docs/fork/requirements.md`（F#.#），任務在 `docs/fork/tasks.md`，同步上游的做法在 `docs/fork/upstream-sync.md`，給機器讀的清單在 `docs/fork/manifest.json`。
> 本文件裡的「§F#」「§F-DB」「§F-UP」「DF#」指這份；「§數字」「D#」「R#」指上游文件。

## F0. 開發規則（PLAN-fork-5.0 §3.3）

### F0.1 以後新增功能的規則

1. 新功能先寫進 `docs/fork/requirements.md`（新功能從 F10 編號），再寫這份的 §F#（重要的取捨寫成 DF#），再加 `docs/fork/tasks.md` 的任務，最後寫程式。
2. 程式放 `Sources/Shiyin/Fork/<功能>/`：邏輯、畫面、DEBUG 指令都放這裡。上游的檔只加「接點」，每個接點行尾標 `// MA-FORK(F#)`（shell 腳本用 `# MA-FORK(F#)`），規則見 §F0.3，並登記在 `docs/fork/manifest.json`（`python3 scripts/fork/isolation-check.py --write` 照程式產生）。
3. 能用 extension 就用 extension（`extension AppModel`、`extension AppDatabase`、`extension Recorder`…寫在 Fork/ 的檔）。extension 看不到上游的 `private` 成員：真的要用時把那個成員改成 internal（參數用到 private 型別、不能改 internal 時，在同一個檔加 1 行 internal 的 `fork…` 轉呼叫），**這一行也算接點**、要標記，並列進 manifest 的 `highRisk`。
4. 不改上游函式的簽章（不加參數、不改型別）。需要不同的行為時，fork 另寫一個函式呼叫上游的，或重用上游的 helper 自己組（例如 `reassignSegments(…naming:…)` 用上游的 `saveSpeakerUndo`、`addSpeaker`、`removeEmptySpeakers` 在同一筆交易裡做完，DF8），或在上游函式裡放 1 行接點問 fork（例如 `ForkSpeakerTags.remembersVoice`）。原本在同一筆資料庫交易裡的步驟，拆到 fork 後也要在同一筆交易裡（不能先呼叫上游的寫入、再另開一筆寫 fork 的），失敗時才會整筆回復。真的要改簽章時寫成 DF 決策，列進 manifest 的 `highRisk`。
5. `@Observable` 的類別、struct 不能在 extension 加存起來的屬性：fork 的狀態放 fork 自己的物件，上游的型別只多一個屬性（`AppModel.fork`〔`ForkAppState`〕、`MeetingDetail.forkTags`、`Recorder.mute`〔`ForkMute.State`〕），fork 的 extension 用原本的名字讀寫（`model.currentTopicBranch`、`recorder.micMuted`），畫面照樣會跟著更新。
6. 資料照 §F-DB：migration、新表 `ma_` 開頭，只新增、不改、不刪，`ForkMigrations.register` 在上游全部的 migration 之後。設定鍵（UserDefaults）一律 `ma` 開頭（例如 `maMuteHotKey`）；已經發布的 `muteHotKey` 不改名（使用者的設定會不見）。DEBUG 指令一律 `ma` 開頭（例如 `matagspeaker`），4.x 就有的（`tagspeaker`、`micmute`、`windowshot`…，manifest 的 `rules.legacyNames`）保留原名。fork 的 DEBUG 指令寫在 `ForkDebug`（`Fork/Debug/ForkDebug.swift` 加各功能的 `extension ForkDebug`），`state` 的欄位在 `ForkDebug.augmentState` 補上。
7. 介面文字照樣寫中文、照上游寫「拾音」，鍵不要含「會議助手」，建置時由 `brand.py` 換（§F7）；不經過翻譯表的寫法（`ui(zh:`、`verbatim:`）不能有品牌字，`brand.py check-sources` 會擋。
8. 只做 Mac：`windows/`、`docs/design-windows.md`、Windows 的翻譯表不動；上游文件裡 Windows 的段落照留，fork 不適用。

### F0.2 Fork/ 的配置（5.0.1 之後，PLAN-fork-5.0 階段 2）

| 功能 | `Sources/Shiyin/Fork/` | 上游檔的接點（manifest 的 `markers`） |
|---|---|---|
| F0 共用 | `ForkState.swift`（`ForkAppState`：F2、F4 的畫面狀態）、`Debug/ForkDebug.swift`（DEBUG 指令入口 `intercept`、`commands`、`augmentState`、`ForkDebugPrompts`）、`ForkStartup.swift`（`ForkStartup.install`：啟動時各功能的安裝；`ForkAppMenuCommands`：「MA」選單，§F10.6；`ForkRecordingSettingsRows`：設定「提醒與快捷鍵」的 fork 列），共用入口的清單見 §F0.7 | AppModel 的 `let fork`、`ForkStartup.install(self)`、ShiyinApp 的 `ForkAppMenuCommands(model: model)`、SettingsView 的 `ForkRecordingSettingsRows()`、DebugControl switch 前的 `ForkDebug.intercept`、`state` 的 `return out` 前、Notifier 的 `-debugQuietPrompts` |
| F2 說話者標記 | `SpeakerTags/`：`SpeakerTagging`（規則）、`SpeakerTag`（資料表 `speaker_tags`）、`SpeakerTagStore`（`extension AppDatabase`）、`AppModel+SpeakerTags`（`MeetingDetail`、`AppModel` 的 extension）、`SpeakerTagViews`（錄音畫面、會議頁、逐字稿的畫面）、`SpeakerTagsDebug`、`ForkSpeakerTags`（跟著上游的編輯、分割、合併、封包）；`Store/ForkMigrations` | RecordingView、MeetingDetailView、TranscriptTab、JobRunner、AppModel、AppDatabase、MeetingEdits、Package、Exporters、Voiceprints、SpeakerEdits（`forkSaveSpeakerUndo`、`forkAddSpeaker`：轉呼叫 private 的 `saveSpeakerUndo`、`addSpeaker`） |
| F3 靜音 | `Mute/`：`MicMute`（`ForkMute`、`extension Recorder/GlobalHotKey/AppSettings/AppModel`）、`MuteViews`、`MuteDebug`、`ForkMuteSettingsRow`、`ForkIslandMute` | Recorder、RecordingWriter（`muted`、`setMuted`、混音，跟寫檔的鎖綁在一起，留在原檔）、GlobalHotKey、AppModel、RecordingView、MenuBar、ShiyinApp、IslandView、RecordingIsland（設定列、`hotkey mute`、停止時關 ⌃⌥⌘M 改走 F0 的共用入口，§F0.7） |
| F4 條列頁 | `Notes/`：`NotesListViews`（`ForkNotesList` 整個條列模式、`ForkNotesSection`、`NoteRow`、`TopicBlock`、`TopicChips`、`ForkActionItemsTable`、`FlowLayout`）、`NotesModel`（`NotesSectionScope`、`plainSection`、`topicSegments`、顏色、`AppModel` 的議題狀態、播放條的 `forkTrackTopic`）、`NotesDebug` | NotesTabs（條列模式換成 `ForkNotesList`；`ItemList` 的符號、`NoteRow`）、PlayerBar、AppModel、MindMap（`clean`、`shownTopics` 改 internal） |
| F7 品牌 | `Brand.swift`（「關於 MA」的 `BrandAboutCommand` 由 F0 的 `ForkAppMenuCommands` 放進選單） | ReleaseNotes、Reminders、IslandView、`build-app.sh`、`make-dmg.sh`、`make-update-fixtures.sh` |
| F11 錄音島的螢幕 | `Island/`：`ForkIsland`（選螢幕、記下主視窗的螢幕、設定鍵）、`IslandScreenViews`（設定的「錄音島放在」）、`IslandDebug`（`maisland`） | RecordingIsland 的 `place`：`ForkIsland.screen() ?? NSScreen.main ?? NSScreen.screens.first`（§F11.1）；設定列走 F0 的 `ForkRecordingSettingsRows` |
| DF5 | `DF5/LockedValue.swift` | AudioSources 的 `MicrophoneSource`、`FileSource`（`deviceUID`、`current` 用 `LockedValue` 存，7 行） |

- 跟上游元件長得一樣的 fork 複本（上游改了原本的，複本不會跟著變；manifest 的 `highRisk` 有列，監看要比對）：`ForkTaggedSpeakerName`（上游 `AutoSpeakerName`，多了「標記」）、`ForkSubduedTimeButton`（`TimeButton`，平常淡色）、`ForkNotesSection`（`NotesSection`，條數、色條、複製鈕）、`ForkActionItemsTable`（`ActionItemsTable`，fork 的欄位順序）。上游的原元件不動，人物頁照用上游的 `NotesSection`。

### F0.3 接點的規則與檢查（`scripts/fork/isolation-check.py`）

- **接點的範圍就是那一行**：上游檔加的每一行，同一行要有 `MA-FORK(F#)`（`F#` 是 manifest 的功能：F0、F1、F2、F3、F4、F7、DF5）。一個接點要多行時寫成多個標了記號的行，或把內容搬進 Fork/ 只留一行呼叫。
- 改掉、拿掉上游的行：同一處（同一個 diff hunk）一定要有加上的接點行，等於「這幾行換成接點」；只刪不加的不行。例如 NotesPage 的條列模式整段換成 1 行 `ForkNotesList(…)`、RecordingView 即時逐字稿的一行換成 `LiveLineRow(…)`。
- 上游的檔被搬走、改名、換類型（例如換成連結）都算拿掉上游的檔：比對時不偵測改名（`git diff --no-renames`，改名會變成刪掉舊的、加新的），舊路徑一定會被檢查到。
- 檢查的範圍：上游 tag（manifest 的 `upstream.base.tag`，現在是 v5.0.0）裡就有的 `Sources/**/*.swift`、`Package.swift`（程式）和 `scripts/` 底下的 `.sh`、`.swift`（腳本）。程式加的行數合計不超過 `rules.upstreamLineBudget`（100）；腳本另外算。不檢查：文件、README、CLAUDE.md、翻譯表、Info.plist、圖示、`.github`（品牌由 `brand.py` 管，§F7.4；版本號照 DF6）。
- manifest 要對得上：每個功能的 `forkFiles`、`upstreamFiles` 存在；`symbols` 找得到宣告；`markers`（`file`、`line`、`hook`＝那一行去掉接點註解）跟程式裡實際的接點一致，多的、少的都算錯，只有行號不同時提示用 `--write` 更新。
- 跑法：`python3 scripts/fork/isolation-check.py`（exit 1 表示有問題，列出每一處）；新增、搬動接點後 `--write` 重寫 manifest 的 `markers`、`upstreamFiles`，再跑一次不加參數的。目前的檔數、行數看檢查的輸出（「上游程式 N 個檔、M 行」），這裡不寫固定的數字（會過期）。`python3 scripts/fork/isolation-check-test.py` 是檢查本身的回歸測試（未標記的修改、已 stage 和已 commit 的改名、刪檔、換類型、DEBUG 指令撞名（§F0.7）都要失敗）。兩支都串在 `scripts/fork/check.sh`（§F0.4）。

### F0.4 回歸檢查（`scripts/fork/check.sh`，PLAN-fork-5.0 §8.1、階段 3a）

合併上游、改 fork 功能之後，一個指令跑完 PLAN §8.1 的回歸清單裡能自動化的項目（1～12），輸出 markdown 摘要。

**用法**

```bash
scripts/fork/check.sh                 # 完整：建置、DEBUG 版實際操作（約 15～25 分鐘，第一次要建基準版更久）
scripts/fork/check.sh --quick         # 只跑靜態的（不建 app、不開 DEBUG 版，約 1～2 分鐘）
scripts/fork/check.sh --base-app <舊版.app>   # 品牌逐鍵比對的基準（預設：HEAD 之前最近的 fork tag 的 release 建置，見下）
scripts/fork/check.sh --base-ref v5.0.1        # 基準改用這個 tag 建
scripts/fork/check.sh --only 3,5,7    # 只跑這幾項（1～16、I1、I2、L、T、W、S；要用到的建置、DEBUG 版自己會建、會開）
scripts/fork/check.sh --out <資料夾>  # 摘要、log、截圖放這裡（預設 $TMPDIR/shiyin-check-<時間>）
scripts/fork/check.sh --keep          # 留下這次的 app、暫存 SHIYIN_HOME（除錯用）
scripts/fork/check.sh --clean-cache   # 結束時連建置快取、基準版也刪掉
```

exit 0：沒有 FAIL（SKIP、需人工不算失敗）；1：有 FAIL；2：沒開始（使用者正在錄音、有別的 DEBUG 版在跑、拿不到開始時的設定快照、參數錯，含 `--only` 有不認得的項目或一項都沒選到）。

`--only` 只收 `1`～`16`、`I1`、`I2`、`L`、`T`、`W`、`S`（逗號分隔），有一個不認得就 exit 2。跟 `--quick` 合用時：`--only` 決定跑哪幾項，`--quick` 只讓 3、4 停在靜態的部分（不建 app）；`--only` 選到的非 Q 項目（1、2、5～10、14～16、S）照常建置、開 DEBUG 版，所以 `--quick --only 5` 還是會建 app。摘要是輸出資料夾的 `summary.md`，最後也印在終端機。每一項一列：狀態（PASS／FAIL／SKIP／需人工）、耗時、證據路徑（log、JSON、截圖），細項寫在下面。

**項目**（編號照 PLAN §8.1；`--quick` 只跑標 Q 的）

| # | 項目 | 做法 |
|---|---|---|
| 1 | 編譯 | `swift build -c debug`；release、DEBUG 版用 `build-app.sh` 的複本建到這次的暫存資料夾（只換 `SCRATCH`、`APP` 兩行，其他照 repo 的腳本） |
| 2 | migration | `scripts/dev/check-fork-migrations.py --scratch-path <check 的建置快取>` |
| 3 | 品牌 | Q：`brand.py check-sources`、`brand-test.py`；完整：`brand.py check` release 和 DEBUG 版、`brand.py compare <基準> <release>`（有差異是「需人工」，差異清單在證據；新版本本來就可能多字串） |
| 4 | F1 | Q：repo 的 `Resources/AppIcon.icns` sha256 等於 manifest `F1.iconSha256`、`Info.plist` 的 `ShiyinIssuesURL` 等於 manifest、ShiyinApp 的 `ForkAppMenuCommands(model: model)   // MA-FORK(F0)`、`ForkStartup.swift` 裡的 `BrandAboutCommand()` 和 ReleaseNotes 的 F7 接點在、`brand-hooks-test`（更新說明選段落）；完整：建好的 app 的 icns、`ShiyinIssuesURL` 也一樣；更新網址（CI 的 `vars.SHIYIN_UPDATE_URL`）用 `gh variable get` 讀得到時要指到 fork（`EdenQ/Shiyin`），讀不到是 SKIP：這是唯一定義成可選的子項，摘要另外列一行 `4u`、狀態 SKIP |
| 5 | F2 標記 | `record-sim` 中 `tagspeaker now 甲`、停止：`speaker_tags` 有這一筆、時間在送出指令時的 elapsed 附近；`f2-atomic-check.py`（套用：說話者 1 變「甲」、說話者 2 有乙又有丙不套用；「只改這句」的交易、復原） |
| 6 | F2 加上 5.0 | 兩場示範會議加標記：`editmeeting` 裁頭尾、刪中間、分割、合併，標記跟著平移、分到新會議、合併後加上偏移；每次 `restoreedit` 都回到原本；`.shiyin` 封包帶標記、匯入回來一樣，舊封包沒有標記也能匯入 |
| 7 | F3 靜音 | `f3-mute-check.py`（狀態、⌃⌥⌘M、錄音檔兩聲道、靜音那段麥克風是 0、電腦聲音照常） |
| 8 | F3 加上 5.0 | `check-debug.py f3-hint`：靜音中 `levelCheck` 沒有收音提示；選單列圖示是 `mic.slash.circle.fill`；`hotkey.muteRegistered` 錄音中是 true、停止後 false；靜音中 `recordstall 32 1`（電腦聲音停下）：20 秒左右 `muteHint` 出現、`micmute dismiss` 收掉；提示列的 windowshot 放進截圖 |
| 9 | F4 | `scripts/dev/f4-check.py`（議題切段、中英日的分段複製） |
| 10 | F4 加上 5.0 | **只自動驗證刪除**：`noteitem delete actionItems 0` 之後 `copysection` 的待辦少一條、其他條和別的段落照舊（示範會議的決議只有 1 條，刪了整段變空）；刪除後的 windowshot 放進截圖。`noteitem edit` 之後的樣式、「人物」頁不套 F4 樣式沒有自動驗證，摘要的說明欄寫明，留給 S 和使用者 |
| 14 | F10 備份 | `scripts/fork/f10-backup-check.py`（§F10.8 的自動化：清理只動自己的一般檔、舊暫存檔在成功時清掉、排程和立即備份重疊時第二個回 `running`、錄完後到期的檢查會做） |
| 15 | F11 錄音島的螢幕 | `scripts/fork/f11-island-check.py`（§F11.6 的自動化）。這一項要錄音島開著、放在桌面層：先結束這次的 DEBUG 版，用同一個測試複本、新的暫存 `SHIYIN_HOME` 加 `-recordingIsland YES -debugIslandBehind YES` 重開（其他參數照舊，`-debugQuietPrompts YES`），跑完結束；排在 S 後面 |
| 16 | F12 聲紋 | `scripts/fork/f12-voiceprint-check.py`（§F12.8 的自動化：分數的文字、防呆和三個選項、全部套用、來源紀錄、人物頁的資料和刪單份、§F-DB；`windowshot` 拍會議頁、防呆視窗、人物頁）。會刪會議、刪人，所以另外開一次 DEBUG 版（同一個測試複本、新的暫存 `SHIYIN_HOME`、`-recordingIsland NO`），自己 `seedfixtures`；跑完再真的結束、重開同一個 `SHIYIN_HOME` 兩次，測 F12.15 的建議不因重啟遺失或復活（`--phase restart-*`，`start_debug` 加 `KEEP_HOME=1`）；排在 S 之後、#15 之前 |
| S | 截圖 | 繁中、英文各開一次 DEBUG 版：示範會議的紀錄、逐字稿分頁（`windowshot`）、設定「錄音」頁（`preview settings recording` 加 `mawindowshot`），加上 #8、#10 的圖，放在輸出資料夾的 `shots/`；狀態一律「需人工」（看條數、色條、「加到提醒事項」、靜音開關、提示列；還沒有基準圖，不做像素比對） |
| 11 | DF5 | Q：`scripts/fork/tsan-lockedvalue/run.sh` |
| 12 | 設定殘留 | Q：開始、結束各 `defaults export com.weiwei.shiyin`（正式 app 的網域），要逐位元組相同；不同時列出哪幾個鍵、FAIL，**保留現值、不改寫也不刪**（分不出是檢查還是使用者同時改的，例如使用者自己移動了主視窗）。DEBUG 版用測試專用的 bundle id（見安全規則），本來就不寫正式網域，所以這一項不靠任何還原。有選 DEBUG 版的項目（5～10、S）時另外核對 `shiyin://` 和 `.shiyin`（`com.weiwei.shiyin.meeting`）的預設處理程式在檢查前後相同：這時處理程式的快照是**必要的**，開始時沒拿到、結束時讀不到都算 FAIL，不會因為缺檔就跳過 |
| 13 | 實機更新 | 不自動：列為「需人工」（4.7.6 → 新版的 app 內更新，開舊會議看標記、靜音、條列頁） |
| C | 收尾 | 每次都跑（不能用 `--only` 選）：結束自己的 DEBUG 版、確認沒有留下測試版的程序、清掉測試網域（後置條件見下）、刪掉這次的暫存資料夾（`--keep` 時留著）。任何一步失敗就 FAIL，整體 exit 1 |

另外五項也標 Q：`upstream-watch-test.py`（W，上游監看的測試，§F0.5）、`check-test.py`（T，check.sh 自己的負對照，見下）、`isolation-check.py`（I1）、`isolation-check-test.py`（I2，§F0.3）、`l10n.py check`（L；跑之前存一份翻譯表，跑完翻譯表有變就算 FAIL 並放回原本的內容：檢查不該改到 repo）。摘要列在 #3 之後。#4 的子項（例如 CI 的更新網址）讀不到時整項照樣 PASS，說明欄寫哪一個子項 SKIP。

**安全規則**（CLAUDE.md「驗證時要注意」）

- 開始前看 `~/Library/Application Support/Shiyin/audio/recording/`：有檔案就停（exit 2）。有別的 DEBUG 版在跑也停（`shiyinctl` 是廣播）；檢查中同時只開自己的一個 DEBUG 版。
- 建置：`build-app.sh` 的複本，`APP` 在這次的暫存資料夾（`~/Library/Caches/ShiyinBuild/check/run-<時間>/`），`SCRATCH` 是 check 自己的建置快取 `~/Library/Caches/ShiyinBuild/check/scratch`；不碰 `~/Library/Caches/ShiyinBuild/app`（使用者可能拿它錄音）、不跑 `--install`。`shiyinctl` 也編到暫存資料夾。
- DEBUG 版用**測試專用的 bundle id**（`com.weiwei.shiyin.macheck`）：建好的 DEBUG 版（#3、#4 檢查的那一份不動）複製一份到 `run-<時間>/debug-test/`，Info.plist 的 `CFBundleIdentifier` 換成測試 id、拿掉 `CFBundleURLTypes`（`shiyin://`）、`CFBundleDocumentTypes`、`UTExportedTypeDeclarations`（`.shiyin`、`meeting-ids`），再 ad-hoc 重簽。AppKit 存的視窗位置、`preview settings` 記住的頁面、其他 `UserDefaults.standard` 都寫進測試網域，不碰正式 app 的設定；系統的 `shiyin://`、`.shiyin` 處理程式也不會被測試版搶走（開 DEBUG 版後核對候選的 app 裡沒有測試版，結束後預設處理程式跟開始前相同）。換 id 不影響檢查要用的東西：控制通道是固定名稱的 distributed notification（`com.weiwei.shiyin.debug`，`shiyinctl` 照用）、`SHIYIN_HOME` 是環境變數、啟動參數是這次執行的 argument domain；寫死 `com.weiwei.shiyin` 的其他地方是 log subsystem、DispatchQueue 名稱、鑰匙圈 service（DEBUG 預設不讀）、UTType 名稱、`Notification.Name`，都跟偏好設定網域無關。結束時（含失敗、Ctrl-C）先 `lsregister -u` 取消登記測試版，再刪測試網域（`defaults delete com.weiwei.shiyin.macheck`、`~/Library/Preferences`、`HTTPStorages`、`Caches`、`Saved Application State`、`WebKit` 底下那個 id 的檔）；刪之前核對 id 不是正式的。
- DEBUG 版：暫存 `SHIYIN_HOME`，`open -g -n --env SHIYIN_HOME=…`，參數 `-ApplePersistenceIgnoreState YES -llmProvider none -autoSummarize NO -correctTranscript NO -debugQuietPrompts YES -recordingIsland NO -mcpEnabled NO -autoCheckUpdates NO -muteHotKey YES`（設定只在這次執行有效）；啟動後用 `lsof` 確認開的是暫存的資料庫，開到正式資料庫就結束 app、FAIL。錄音島關掉：上游 5.0 的 DEBUG `state` 在島出現時寫不出 JSON。結束用 `kill`（TERM，10 秒後 KILL），不用 `quit`：正常結束會把視窗位置寫進共用設定。
- 不送按鍵、不用 System Events、不用 AX：畫面一律 `windowshot`、`mawindowshot`（app 自己畫）。
- 結束（含失敗、Ctrl-C）時結束自己的 DEBUG 版、刪掉這次的暫存資料夾（app、home、`shiyinctl`）；輸出資料夾留著（摘要和證據）。建置快取和基準版留著給下次用（`--clean-cache` 才刪）。

**失敗一律不放行**（check.sh 是安全防線：判斷不了的情況算失敗，不算通過）

- 設定快照：`defaults export` 成功、而且 `plutil -lint` 認得是 plist 才算快照。網域確實不存在（`defaults read <網域>` exit 非 0、stdout 是空的、stderr 去掉結尾換行後**只有一行而且完全等於** `Error: Domain '<網域>' not found.`（macOS 27.2.1 實測）或舊的 `Domain <網域> does not exist`；前後多一個字、多一行、別的網域都不算，例如 `cfprefsd: Domain '<網域>' not found in cache; …`；`defaults export` 這時寫出空的 plist）是另一種明確狀態，快照檔寫成 `MA-CHECK: domain absent`；其他失敗（權限、服務、I/O、輸出不是 plist）：開始時 exit 2（不跑），結束時 #12 FAIL。不會用空檔代替。
- 資料庫：DEBUG 版啟動後用 `lsof -p <pid> -Fn`（每個路徑一行、保留空白）列出開著的檔，`lsof` 失敗或沒有輸出就算失敗；所有 `shiyin.sqlite`、`-wal`、`-shm` 都要在這次的暫存 home 底下，而且一定要看得到暫存 home 的 `shiyin.sqlite`；開了任何正式資料夾（`~/Library/Application Support/Shiyin/`）底下的檔也算失敗。失敗時結束那個 DEBUG 版，DEBUG 版的項目全部 FAIL。
- 品牌比對：`brand.py compare` 的 exit code 分三種：0 相同、1 比完有差異（需人工）、2 工具或輸入錯誤（基準或新版不是有效的 app：沒有 `Contents/Info.plist`、讀不了、沒有任何 `.lproj` 的 `Localizable.strings`；或比對中丟例外）。check.sh 只把 1 當「需人工」，其他非 0 一律 FAIL；呼叫前也先確認基準 bundle 有這些檔。
- 結束 DEBUG 版：送訊號前核對那個 pid 的執行檔還是這次暫存資料夾裡的 app（`ps -o comm=`），不是就不送（pid 可能被別的程序重用）。
- `--only`：照上面的白名單驗證；`--only`、`--base-app`、`--base-ref`、`--out` 後面少了值也是 exit 2（不是 shell 的錯誤）。單選 DEBUG 版的項目（`--only 5`、`--only 5,12`、`--quick --only 5`）要能正常跑：每一項的說明、證據欄在用到前就有初始值。
- DEBUG 版的**必要條件**（依序；任一步失敗，5～10、14、S 全部 FAIL，說明欄寫哪一步，不會「沒核對就照跑」）：
  1. 清掉上次中斷留下的測試網域（後置條件要成立）；
  2. 建置（#1）；
  3. 編譯 `check-handlers.swift`；
  4. 拿到開始時的處理程式快照，而且內容有效（有 `scheme-default`、`type-default` 兩行）；
  5. 做出測試 id 的複本（`isolate_debug_app`）；
  6. 啟動、`lsof` 核對資料庫；
  7. 測試版開著時再讀一次處理程式（要讀得到、候選裡沒有測試版）。
- 測試網域的清理（`cleanup_test_domain`）：`lsregister -u`、`defaults delete`、刪檔每一步的失敗都算；做完核對後置條件：`defaults read <測試 id>` 要明確說網域不存在（同上面設定快照的嚴格比對；其他錯誤、近似的訊息都不算「已確認不存在」），Preferences、HTTPStorages、Caches、Saved Application State、WebKit 底下那個 id 的檔都不在。不成立就 return 1：開 DEBUG 版前的清理失敗 → DEBUG 項目 FAIL；結束時的清理失敗 → C FAIL。對正式 id 照樣拒絕、什麼都不做。
- 結束 DEBUG 版：TERM 10 秒、再 KILL，之後那個 pid 還是這次的 app 就算失敗（C FAIL）；收尾時再用 `debug_apps` 確認沒有留下這次測試版的程序。
- 開始前：`audio/recording/` 存在卻列不出來（權限）、`ps` 列不出程序，都 exit 2（判斷不了使用者是不是在錄音、有沒有別的 DEBUG 版）。
- 其他前置步驟：`git archive <基準 tag> | tar` 任何一邊失敗都算基準建不出來（#3 FAIL；pipeline 結束後立刻把 `PIPESTATUS` 整個存下來再判斷，`extract_tag`）；`l10n.py check` 前備份翻譯表、讀 `git status` 失敗就 L FAIL；`seedfixtures` 失敗就那一項 FAIL；`check-debug.py` 的 `restoreedit` 後編輯紀錄沒清掉也算不符。
- 每個外部指令、helper、前置步驟失敗會走到哪裡，列在 IMPL／FIX 的報告（FIX-3a3 的自查表）；新增步驟時照同樣原則：必要的失敗 → 依賴的項目 FAIL；只有明確定義成可選、摘要標 SKIP 的才可以跳過（目前只有 `4u`）。

**check.sh 自己的測試**（`python3 scripts/fork/check-test.py`，也是 quick 的 T）：check.sh 的判斷寫在 `scripts/fork/check-lib.sh`（`check.sh` source 它），測試在暫存資料夾放假的 `defaults`、`lsof`、`ps`、`plutil` 指令（PATH 最前面），只呼叫 lib 的函式，不讀寫真的設定、不碰任何資料庫。負對照都要失敗或 exit 2：

| 函式 | 情境 | 要的結果 |
|---|---|---|
| `defaults_snapshot` | export 失敗（非網域不存在）、export 成功但不是 plist、網域不存在 | 前兩個 return 1；不存在寫 `MA-CHECK: domain absent`、return 0 |
| `verify_db_files` | 只有暫存、只有正式、兩者都有、路徑有空白（暫存 home 有空白；正式的 `Application Support`）、只有 `-wal` 在正式、lsof 失敗、lsof 沒輸出 | 只有「只有暫存」（含有空白的暫存 home）通過 |
| `compare_status` | brand.py compare 回 0、1、2、其他 | PASS、需人工、FAIL、FAIL |
| `validate_only` | `999`、空字串、`3,999`、`3,I1,S` | 前三個 return 2，最後一個通過 |
| `owned_pid` | pid 的執行檔是這次的 app、是別的程式、pid 不在 | 只有第一個通過 |
| `isolate_debug_app` | 複製出來的 DEBUG 版 | `CFBundleIdentifier` 是測試 id、沒有 URL scheme、文件類型、匯出的 UTType；簽章驗得過；id 給成正式的就拒絕 |
| `cleanup_test_domain` | 測試網域、它的 Preferences／HTTPStorages／Caches 檔 | 只刪測試 id 的；給正式 id 就拒絕、什麼都不刪 |
| `snapshot_diff` 和結束流程 | 檢查中使用者把正式網域的既有值改了（移動主視窗）、建立了原本沒有的鍵（`settingsPage`） | #12 FAIL、列出那些鍵；正式網域一次 `write`、`delete` 都沒有，使用者的值原樣留著 |
| `cleanup_test_domain`（失敗） | `lsregister -u` 失敗、`defaults delete` 失敗而網域還在、刪檔失敗而檔還在、`defaults read` 回的不是「不存在」 | 都 return 1、印出哪一步 |
| `prepare_handlers` | `check-handlers.swift` 編譯失敗、helper 執行失敗、輸出缺 `scheme-default` 或 `type-default` | 都 return 1（DEBUG 項目不開始） |
| `check.sh`（CLI，假的 `swift`、`defaults`、HOME 在暫存資料夾） | `--only 5`、`--only 5,12`、`--quick --only 5`，建置失敗 | 不會因為 `NOTE` 沒有值而中止；5 FAIL（說明是建置失敗）、12 FAIL（缺處理程式快照）、exit 1 |
| `check.sh`（CLI） | `--only`、`--out` 後面沒有值 | exit 2 |

另外 `brand-test.py` 加 `brand.py compare` 的測試：相同 0、有差異 1、基準缺 `Info.plist` 或沒有翻譯 2。

**快取位置**：預設 `~/Library/Caches/ShiyinBuild/check`（建置快取 `scratch/`、基準版 `base/<tag>/`、這次的 `run-<時間>/`）；環境變數 `MA_CHECK_CACHE` 可以換到別的資料夾，用來在不刪現有快取的情況下測「沒有基準快取」的路徑。快取會被建立、`--clean-cache` 會刪裡面的東西，所以在任何建立、建置、清理之前先核對（`resolve_cache`，REVIEW-3a5 P2-9），不通過就 exit 2、什麼都不建也不刪：

- 先解析成真實的絕對路徑（符號連結解開；不存在的部分照字面接上）。`MA_CHECK_CACHE` 本身、或預設路徑被換成符號連結，都看解開後指到哪裡。
- 受保護的位置（也先解析）：`~/Library/Caches/ShiyinBuild/app`（使用者可能拿來錄音的 app）、`~/Library/Application Support/Shiyin`（正式資料）、有設的話 `SHIYIN_HOME`、這個 repo。快取等於它們、在它們底下、或是它們的上層，都拒絕。另外快取不能是 `$HOME` 或 `/`，也不能是 `$HOME` 的上層。
- 自訂值（有設 `MA_CHECK_CACHE`）只接受三種：還不存在（check.sh 會建立）、空資料夾、已經有 check.sh 放的所有權標記 `.ma-check-cache`。其他既有的資料夾、不是資料夾的檔都拒絕。通過後建立資料夾並寫入標記。
- 預設值不用標記（照舊可用），但同樣要通過受保護位置的核對。
- `--clean-cache` 只刪快取底下 check.sh 自己的三個子資料夾（`scratch`、`scratch-base`、`base`），而且只在快取是預設位置、或有 `.ma-check-cache` 標記時才刪。

**品牌比對的基準**：`--base-app` 沒給時，用 `git describe --tags --abbrev=0 --match 'v[0-9]*' HEAD^` 找到的 fork tag（現在是 v5.0.1），`git archive` 那個 tag 到暫存資料夾、用它自己的 `build-app.sh`（同樣的複本規則）建 release，放在 `~/Library/Caches/ShiyinBuild/check/base/<tag>/`，之後直接用。用同一台電腦、同一版 Xcode 建，`xcstringstool` 的版本差異不會變成假的差異（F7.5 跟 GitHub 上的 4.7.6 比時就多了 3 條）。

**怎麼確定檢查會抓到問題**（PLAN 階段 3a 的驗收）：在暫存 worktree 故意弄壞、不 commit，跑對應的項目要 FAIL、整體 exit 1，例如拿掉一個 `MA-FORK` 接點（I1）、原始碼加一句不查表的品牌字（#3）、讓「只改這句」不在同一筆交易或標記不套用（#5）。結果寫在 commit 訊息。

### F0.5 上游監看（`scripts/fork/upstream-watch.py`、`.github/workflows/upstream-watch.yml`，PLAN-fork-5.0 §8.2、階段 3b）

每天機械式比對上游有沒有新東西、會不會跟 fork 衝突或撞名、有沒有做了跟 fork 相似的功能。只篩選、不判斷：有 🔴 或新 tag 時由統一入口派 Claude 讀報告做語意判斷（upstream-sync §5）。

**報告只放 GitHub Actions 的 artifact**（使用者決定，DECISIONS-fork-5.0 第 6 項）：不建立 Issue、不留言、不推送；job summary 只寫一行；報告內容只有兩個公開 repo 的程式碼和文件，不放使用者的路徑、帳號。workflow 的權限只有 `contents: read`，不用任何 secret。

**範圍**：比對的三個點是
- `fork`：fork 的 main（Actions 上是 checkout 的 commit；本機預設 `main`）；
- `head`：上游要看的那一點（預設 `upstream/main`）；
- `base`：上次看過的上游（狀態檔裡的 `upstreamMain`）；沒有狀態檔時用 `git merge-base fork head`（fork 已經合進來的上游）。`--base`、`--head`、`--fork`、`--merge-base` 可以指定，用來重播一段歷史（例如 `--fork v4.7.6 --merge-base 78ceab8 --base 78ceab8 --head refs/upstream-tags/v5.0.0`：當時上游重寫過歷史，merge-base 要自己給）。

**比對方法**（只用 Python 標準函式庫和 git）：
1. **新東西**：`refs/upstream-tags/*`（不看 `win-v*`，fork 只做 Mac）和 `head` 跟狀態檔比。列新 tag（附 tag 的說明文字）、`base..head` 的 commit 標題。上次看過的 `upstreamMain` 不再是 `head` 的祖先 → 🔴「上游改寫了歷史」；已經看過的 tag 指到別的 commit → 🔴。
2. **試合併**：`git merge-tree --write-tree --name-only [--merge-base=…] fork head`。列衝突檔、每個檔的衝突處數（合併結果裡 `<<<<<<<` 的數量）；每一處看前後 20 行的 `MA-FORK(F#)` 標記歸到功能；附近沒有標記時，歸到 manifest 把這個檔列為接點或 `upstreamFiles` 的功能（標「依檔」）；都沒有才歸「品牌／其他」。
3. **改到 fork 接點但沒衝突**：fork 的接點在上游檔裡是加上的行，所以先用 `git diff -U0 <merge-base> fork -- <檔>` 找出含 `MA-FORK` 的 hunk 在合併基準版上的位置（錨點），再看上游 `git diff -U0 <merge-base> head` 的 hunk 有沒有落在錨點前後 3 行內；有衝突的檔不重複列。檔案清單來自 manifest 的 `markers`。
4. **名稱碰撞**（上游新增的行；名稱層級的保守篩選，列出來給人判斷）：UserDefaults 鍵（`forKey: "…"`、`…Key = "…"`、`@AppStorage("…")`）、DebugControl 的 `case "…"`、`registerMigration("…")`、`CREATE TABLE …`、Info.plist 的新鍵：精確比對 manifest 各功能的 `settingsKeys`、`debugCommands`（多字的如 `hotkey mute` 是上游指令的子指令，不算）、`migrations`、`tables`、`infoPlistKeys` 和 `rules.legacyNames`，另外 `ma[A-Z]` 開頭的設定鍵、`ma_` 開頭的 migration 和表、`MA` 開頭的 Info.plist 鍵也算。翻譯表的鍵：上游新增的鍵 ∩ fork 自己加的鍵（fork 的翻譯表減掉合併基準的）。改到 `Sources/Shiyin/Fork/` 底下的檔。型別／函式：不直接用 manifest 的 `symbols`（裡面混了上游的型別，例如 `MicrophoneSource`），而是解析 fork 在 `Sources/Shiyin/Fork/` 的 Swift 檔：宣告的型別（`class|struct|enum|actor|protocol|typealias`），以及加進上游型別的 `extension` 第一層的成員（`func`、`var`、`let`；只看大括號深度，不是完整的 Swift 解析）；上游新增行上宣告的型別和 `func` 名稱撞到這些就列出來，但合併基準的 `Sources` 裡已經有的名字不算（上游只是改到既有那一行）。只比名稱，不看宣告在哪個型別、哪個作用域：上游在別的型別加了同名方法也會列出來，由人判斷。
5. **搬動會議資料的 SQL**：上游新增的行符合 `UPDATE (segments|bookmarks|speakers|meetings) SET … (start|end|time|meeting_id)`、`INSERT INTO … SELECT`，或新增名稱含 snapshot／restore 的函式 → 🟡，列成「fork 的表要不要跟著處理」（§F-DB）。
6. **相似功能**：manifest 每個功能有 `watchKeywords`（`zh`、`en`），掃上游新增的行（程式、翻譯表、docs），每個功能列命中的關鍵字和幾行例子；上游 `docs/requirements.md` 新的章節（`## `、`### ` 開頭、標題在 base 沒有的）跟 `docs/fork/requirements.md` 每個 F 段落算相似度：中文用 CJK 字的雙字組、英文用小寫單字（3 個字母以上），兩組合起來算 Jaccard。分數 ≥ 門檻、或那一節命中同一個功能的關鍵字 ≥ 2 個 → 列為「可能相似」，附兩邊的標題、摘要、分數、命中的關鍵字。門檻 PLAN 先定 0.2，用 78ceab8..v5.0.0 校正成 **0.08**：上游 57 個新章節對 fork F 段落最高的五對（R81 錄音島／F3、R75 錄不到電腦聲音／F3、R92、R101／F4、R74／F3）都是 5.0 合併時真的要處理的，第六名起開始混進不相干的，0.2 一對都抓不到（理由寫在 `SIMILARITY_THRESHOLD` 旁）。關鍵字要具體：太常見的字（「標記」會撞到「標記重點」、「拾音」「名稱」「圖示」到處都是）不放進 `watchKeywords`，品牌由第 7 點管。
7. **品牌**：上游新增或改過的 Swift 檔，用 `brand.py` 同一個掃描器切出字串常值；字串常值的**整個來源範圍**（從開頭的引號到結尾，三引號的多行字串也算整段）只要有一行是上游新增的，就檢查它含不含「拾音」「Shiyin」（只改多行字串內文、開頭那行沒變也抓得到）。不經過翻譯表又不在白名單的（建置時換不到）→ ⚪ 列出來（報告的格式表把品牌放在 ⚪，但這一類在摘要裡標 🔴 計數）；經過翻譯表的只計數。

**報告**（markdown 一份，標題「上游監看 YYYY-MM-DD：上游 x.y.z（N 個新 commit）」，x.y.z 是 head 能走到的最新 `v*` tag）：
1. 摘要：新 tag 和說明、改寫歷史；建議（直接跟／先看／先等／不用動）：有改寫歷史、衝突、名稱碰撞、換不到的品牌字 → 先看；新 tag 是大版本（x.0.0）→ 先等它的第一個修正版（upstream-sync §2.2）；只有 patch 而且沒有 🔴 → 直接跟；沒有新東西 → 不用動。
2. 🔴 衝突表：檔、處數、歸屬功能。
3. 🔴 名稱碰撞。
4. 🟡 改到 fork 接點但沒衝突。
5. 🟡 搬動會議資料的新 SQL。
6. 🟡 可能相似的功能。
7. ⚪ 品牌：建置時換不到的新字串（另外計數經過翻譯表的）。
8. ⚪ 新的 migration、設定鍵、DEBUG 指令、`scripts/dev` 工具（給 CLAUDE.md 補注意事項用）。

另外輸出同樣內容的 JSON（`--out-json`）給機器讀。

**exit code**：0 沒有新東西（沒有新 commit、新 tag、改寫）；1 有新東西；2 工具錯誤（git 失敗、manifest 讀不到、merge-tree 不是 0／1 等）。失敗一律 2，不能被當成「沒有變化」。

**狀態檔**（`--state`，JSON：`upstreamMain`、`tags`〔名稱 → commit〕、`checkedAt`）：有 `--update-state` 才寫，寫到 `--state-out`（沒給時就是 `--state`）；本機預設不寫。**狀態只能在報告交付之後前移**（REVIEW-3b P2-2：報告只放 artifact，先存狀態再上傳時，上傳失敗或取消，這批警告就永久看不到了）：workflow 的順序是 Compare（新狀態寫到另一個檔 `.upstream-watch-next/state.json`）→ Upload report（`if-no-files-found: error`）→ Promote state（把新狀態搬到 cache 的路徑）→ Save state；Promote、Save 的條件都是 Compare 的 exit 是 0 或 1、而且 Upload 的 outcome 是 success。Compare 是 0／1 卻沒有 md、json 報告檔也算錯誤。上傳失敗、被取消時 cache 留著舊狀態，下一輪照樣報出同樣的警告。Actions 用 `actions/cache` 存（每次用新的 key `upstream-watch-state-<run_id>`、`restore-keys` 取最近一份）：比從前一次的 artifact 取簡單，不用第三方 action、不用 `actions: read` 權限；cache 7 天沒用會被清掉，清掉時退回「跟 merge-base 比」，只是多報一次、不會漏。

**測試**：`python3 scripts/fork/upstream-watch-test.py` 在暫存 git repo 造上游、fork 的合成情境，測每一節（新 tag、改寫歷史、衝突歸屬、改到接點、各種名稱碰撞、搬資料的 SQL、相似功能、品牌）和 exit code（沒有變化 0、有新東西 1、工具錯誤 2）。列進 check.sh 的 quick（W，§F0.4）。

### F0.6 推送時自動檢查（`.github/workflows/fork-check.yml`）

每次推送到 main、每個 pull request 都在 GitHub 的 Mac runner 上跑 `scripts/fork/check.sh --quick`（§F0.4）。這樣靜態的回歸檢查不必等人在本機跑，push 之後就知道有沒有壞。完整模式（建置、DEBUG 版）照舊在本機跑，CI 不跑：要開 GUI app、等太久，runner 也沒有螢幕可以 `windowshot`。

**觸發、環境**

- 觸發：`push`（只有 `main`）、`pull_request`、`workflow_dispatch`。
- 同一個分支或 PR 有新的推送時，取消還在跑的舊 run：`concurrency` 用 `github.ref`，`cancel-in-progress: true`。
- `runs-on: macos-26`，跟 `release.yml` 一樣。Xcode 也一樣用 runner 預設的那一版，只在「環境」步驟印出 `xcodebuild -version`、`swift --version`、`sw_vers`。
- `--quick` 不建 app、不開 DEBUG 版，但**會編譯**：
  - L（`l10n.py check`）用 `swift build --target Shiyin`（`-emit-localized-strings`）抽介面字串，建置快取在 `~/Library/Caches/ShiyinBuild-l10n`。runner 是全新的，所以每次都是冷編譯，會下載 GRDB、FluidAudio 等依賴和 whisper、llama 的 binary target。
  - 另外用 `xcrun swiftc` 編兩個小檔：`brand-hooks-test`、TSan 的 `LockedValue`。
- 時間：
  - 隔離的冷跑實測（全新 HOME、SwiftPM 的快取也是空的；REVIEW-CA）：L 約 3 分鐘，整個 quick 約 4.5 分鐘。
  - 本機有快取時約 2 分鐘。
- 目前**不快取 SPM**。
- `timeout-minutes: 30`：照上面的實測應該夠，但 runner 的下載速度、編譯速度沒看過。第一次 CI 看實際耗時，太接近 30 分鐘或太慢時，再考慮放大 timeout，或用 `actions/cache` 快取 `ShiyinBuild-l10n` 的依賴（同樣鎖 SHA）。

**安全**

- 權限只有 `contents: read`，工作層級不另外加權限。
- 不用任何 secret、不用 `GITHUB_TOKEN`。
- `actions/checkout` 用 `persist-credentials: false`。
- 第三方 action 鎖在 commit SHA，沿用 §F0.5 查證過的 checkout、upload-artifact。
- 不推送、不建 Issue、不留言。

**要準備的東西**

- I1 要上游的基準 tag（`refs/upstream-tags/<manifest upstream.base.tag>`）。checkout 之後，只把那一個 tag 從上游抓進 `refs/upstream-tags/`，不碰 `refs/tags`。tag 名稱從 manifest 讀，不寫死。
- checkout 用 `fetch-depth: 0`。

**在 runner 上每一項應該是什麼結果**

不改 check.sh 的失敗語意。runner 跟使用者的 Mac 只有下面這些差別，每一項都照原本的規則判斷：

| 項目 | runner 上 | 預期 |
|---|---|---|
| 開始前 | 沒有 `~/Library/Application Support/Shiyin`、沒有 DEBUG 版 | 照常開始（沒有錄音資料夾就不算在錄音） |
| 12、開始時的快照 | 沒有 `com.weiwei.shiyin` 網域 | macOS 27.2.1 上 `defaults export` 不存在的網域會寫出空的 plist、exit 0，快照就是空的 plist；前後相同 → PASS。export 失敗時才看「網域不存在」的訊息（§F0.4 的嚴格比對） |
| 4、4u | 有 `gh`，但沒有給 token | `gh variable get` 失敗 → 4u SKIP，4 照樣 PASS（4u 是唯一可選的子項） |
| 3、T、W、I1、I2、11 | 只用 python3、git、`xcrun swiftc`、`codesign` | PASS |
| L | `swift build --target Shiyin` 冷編譯，要下載依賴（要網路） | PASS（約 3 分鐘） |
| C | 沒有開 DEBUG 版 | PASS |

**macOS 26 上還沒看過**：runner 是 macOS 26，下面兩件事還沒看過：

- `defaults export` 不存在的網域會不會像 27.2.1 一樣寫出空的 plist；
- export 失敗時的訊息是什麼。§F0.4 只認兩種完全相同的訊息：27.2.1 實測的 `Error: Domain '<網域>' not found.`，和舊的 `Domain <網域> does not exist`。

如果 export 失敗、訊息又是別的寫法，開始時就判斷不了設定快照，check.sh 會 exit 2，CI 變紅。

- 這是預期中的失敗方式，不是假通過。
- 處理方式：「環境」步驟會把 `defaults read com.weiwei.shiyin` 的 exit code 和 stderr 印在 log，check.sh 的輸出會寫 export 為什麼失敗。看過那一行後，把那個寫法加進 `domain_absent_message`（一樣要整行完全相同），不放寬比對。

**輸出**

- artifact：check.sh 輸出資料夾裡的 `summary.md`、`logs/`、`defaults-*.plist`，名稱 `fork-check-<run_id>`，保留 14 天；`if: always()`，失敗時也上傳。
- job summary：只放 `summary.md` 裡的表格行（`|` 開頭的行）。
  - 內容是項目、狀態、耗時、證據檔名、說明，沒有使用者資料。
  - runner 上的路徑是 runner 自己的（`/Users/runner/…`）。
- check.sh 的 exit code 就是這一步的結果：1（有 FAIL）、2（沒開始）都讓 job 失敗。不加 `continue-on-error`、`|| true`。

**失敗時的編譯診斷**

- L（`l10n.py check`）的 `swift build` 輸出被上游的 `l10n.py` 丟掉（stdout 是 DEVNULL），編譯失敗時 log 只看得到 `CalledProcessError`。`l10n.py` 是上游的檔，不改。
- 所以 workflow 在 `check.sh --quick` 後面加「編譯診斷（失敗時）」：`if: failure()`，只在 job 已經失敗、而且摘要裡 L 是 FAIL（或沒有摘要）時，用跟 `l10n.py` 完全一樣的指令（同樣的 scratch path、`--target Shiyin`、`-emit-localized-strings`）再編一次，輸出存成 `$RUNNER_TEMP/swift-build.log`，在 log 印出含 `error:` 的行（最多 200 行）和最後 300 行。這一步不會讓失敗的 job 變綠（job 早就失敗了），也不寫進 job summary；log 檔一起放進 artifact。
- 本機和 runner 的 Swift 版本可能不同（2026-11-23 第一次推送：runner 是 Xcode 26.6／Swift 6.3.3／macOS 26.7.2，本機是 Xcode 27.2／Swift 6.4.2），本機編得過不代表 runner 編得過；有 FAIL 時先看這一步的錯誤。

**測試**：`check-test.py` 的 `ForkCheckWorkflow` 做靜態檢查。

- 觸發條件、`contents: read`、工作層級沒有權限。
- action 都鎖 SHA，沒有 secret、`GITHUB_TOKEN`、寫入、`gh issue`、`git push`。
- `persist-credentials: false`；`concurrency` 會取消舊的 run。
- 跑的是 `check.sh --quick`，而且沒有吞掉失敗。
- 上游 tag 放 `refs/upstream-tags/`。
- tag 步驟實際跑一次：從 workflow 抽出那一步的 shell，換上假的 `git`（記下有沒有被呼叫），用惡意或型別不對的 manifest 跑。跨 ref、`../`、換行、分號、命令替換、null、數字、空字串都要被拒絕（exit 非 0）而且 `git` 沒被呼叫；正常的 `v5.0.0` 要呼叫 `git fetch`，refspec 是 `+refs/tags/v5.0.0:refs/upstream-tags/v5.0.0`。拿掉格式檢查那一行時，這個測試要失敗。
- artifact 保留 14 天、`if: always()`；job summary 只取表格行。
- 編譯診斷只在 `if: failure()` 跑、在 `check.sh --quick` 之後和上傳之前，指令跟 `l10n.py` 一樣（`--target Shiyin`、`-emit-localized-strings`、同一個 scratch path），只印 log、不寫 job summary，`swift-build.log` 放進 artifact。

**推送後第一次要確認**

- run 是綠的。
- 摘要表格裡：
  - 3、T、W、I1、I2、L、4、11、12、C 都是 PASS，4u 是 SKIP；
  - 12 的說明是「前後逐位元組相同」。
- 「環境」那一步印出的 `defaults read` 訊息記下來，是不是支援的兩種之一。現在用不到，export 失敗時才用得到。
- artifact 有 `summary.md`、`logs/`。
- 沒有建 Issue。
- 再推一次（或對同一個 PR 連推兩次）時，舊的 run 被取消。

### F0.7 共用入口與接點合併（DF10）

上限 100 行不提高（2026-11-23 使用者決定）。新功能要碰上游時，先看能不能走既有的共用入口；行數快滿時，把既有的接點收進共用入口騰出空間。合併只換「fork 從哪裡被呼叫」，行為不變。

**共用入口**（上游檔各 1 行，以後的 fork 功能加在 Fork/ 裡）：

| 入口 | 上游的那一行 | 現在放了什麼 |
|---|---|---|
| `ForkStartup.install(model)` | AppModel：`ForkStartup.install(self)   // MA-FORK(F0)` | F3 `ForkMute.install`（⌃⌥⌘M、靜音提醒、錄音開始／結束時開關 ⌃⌥⌘M）、F10 `ForkBackup.install` |
| `ForkAppMenuCommands(model:)` | ShiyinApp：`ForkAppMenuCommands(model: model)   // MA-FORK(F0)` | F7 關於 MA、F10 立即備份 |
| `ForkDebug.intercept(args, model:)` | DebugControl `handle` 的 switch 之前：`if ForkDebug.intercept(args, model: model) { return }   // MA-FORK(F0)` | fork 全部的 DEBUG 指令、蓋過上游的 `windowshot`、上游 `hotkey` 的子指令 `hotkey mute` |
| `ForkDebug.augmentState` | DebugControl `state` 的 `return out` 前 | 各功能 `state` 的欄位 |
| `ForkRecordingSettingsRows()` | SettingsView「錄音與轉錄 → 提醒與快捷鍵」最後：`ForkRecordingSettingsRows()   // MA-FORK(F0)` | F11 的「錄音島放在」、F3 的 ⌃⌥⌘M 開關 |
| `ForkIsland.screen()` | RecordingIsland `place` 選螢幕的那一行：`ForkIsland.screen() ?? NSScreen.main ?? NSScreen.screens.first`（`// MA-FORK(F11)`） | F11 錄音島放在哪個螢幕；以後錄音島位置相關的 fork 功能也走這裡 |
| `ForkBackupSettingsSection()` | SettingsView 一般頁 | F10（一般頁的 fork 設定以後也可以改成共用列） |
| `ForkDetailBanners(detail:active:)` | MeetingDetailView 會議頁上方的提示列（原本是 F2 的 `UnappliedTagsBanner` 那一行，F12 改寫，行數不變） | F2 沒套用的標記、F12 改名防呆的提示列和視窗 |
| `ForkSpeakerChip(idx:name:detail:)` | MeetingDetailView `speakerChip` 選名字畫法的那一行（原本是 F2 的 `if …"tag"`，F12 改寫） | F2 標記帶入的名字、F12 自動帶入的名字加依據；回 nil 照上游 |

**這次合併的 3 行**（99 → 96；HK-consolidate）：

1. DebugControl `default:` 的 `if !ForkDebug.handle(…)`（F0）→ 還原成上游原樣的 `default: log.error("unknown debug command \(name)")`。fork 的指令改由 switch 前的 `ForkDebug.intercept` 處理（原本的 `ForkDebug.shadows` 那一行改名、擴大）。
   - 行為不變的前提：fork 的頂層指令名稱跟上游 `DebugControl` 的 `case` 不重疊（`windowshot` 除外，本來就是 fork 蓋過上游）。這樣「先問 fork」跟「上游不認得才問 fork」結果相同。
   - `intercept` 只認 `ForkDebug.commands`（明列的頂層名稱）。不認得的照樣交給上游，最後由上游記「unknown」。
   - 防止以後撞名：`isolation-check.py` 比對三件事，有一件不符就失敗：
     - `ForkDebug.commands` 等於 manifest 各功能 `debugCommands` 的單字名稱；
     - 也等於 fork 各 `*Debug.swift` 比對的指令名稱（多字的 `debugCommands` 例如 `hotkey mute`，第一個字是上游的指令，不算 fork 的頂層指令，但上游一定要還有）；
     - 跟上游 `DebugControl` 的指令名稱的交集只有 `ForkDebug.shadowed`。
   - 指令名稱怎麼收集（上游、fork 同一套規則，`command_names`；HK-fix，REV-HK P2-1）：
     - 用 Swift 的詞彙切分，不是逐行比對：跳過 `//`、`/* */`（可巢狀）註解；字串整個當一個 token，有插值或跳脫字元的不算單純的字面值。
     - 主旨是 `name`、`args[0]`、`args.first` 的 `switch`，大括號第一層的每個 `case` 從 `case` 收到同一層的冒號：逗號分隔，有沒有空白、跨不跨行、中間有沒有註解都一樣。小括號、中括號、大括號（`where` 裡的閉包）裡的冒號、逗號不算。帶 `where` 的照樣算那個字面值（寧可多算）。
     - 不完整解析 Swift，改成保守（HK-fix2，REV-HK-2 P2-2）：`where` 條件裡有 `{`、`}` 或 `?`（閉包、三元運算、optional chaining）時，冒號可能屬於條件本身，一律報錯、要人工核對，不繼續猜。條件裡只有比較、`&&`、呼叫、下標、字典字面值的照常收；`case` 本體裡的閉包、三元運算不受影響（本體的大括號照常算深度）。
     - 掃描提早結束的保險：switch 結尾的 `}` 要自己在一行的開頭、縮排跟 `switch` 那一行一樣；不是的話（裡面的結構讓深度提早歸零，或一行寫完的 switch），報錯、要人工核對。case 找不到結尾的冒號、switch 找不到結尾的大括號也一樣。
     - 同一個主旨跟字串比對（`name == "x"`、`"x" == args[0]`），檔裡任何地方都算。
     - 最外層的 pattern 不是字串字面值（`let x where …`、運算式、有插值的字串），或上游找不到這樣的 `switch`：報錯、要人工核對，不默默少算。現在的上游、fork 程式都沒有這種寫法，不需要白名單。
     - 回歸測試在 `isolation-check-test.py` 的 `DEBUG_CASES`：上游寫成有空白、沒空白、跨行、中間有註解、帶 `where`、`if name ==` 的撞名，fork 端沒空白、跨行的未列名稱，兩邊看不懂的 pattern 都要失敗；`where` 裡的閉包加三元運算（REV-HK-2 的兩個反例）、巢狀閉包、字串插值、沒有括號的三元運算、optional chaining，case 本體裡的閉包之後的撞名，switch 結尾不在行首，也都要失敗；只出現在註解裡、本體裡的三元運算和閉包、`where` 裡的字典字面值、正常的要通過。
   - 上游新增同名指令時，`upstream-watch` 本來就會列出名稱碰撞（§F0.5）。
2. DebugControl `case "hotkey":` 那一行（F3 加了 `mute` 的分支）→ 還原成上游原樣。`hotkey mute` 改在 `intercept` 裡先接（`args[0] == "hotkey" && args[1] == "mute"` 才接，其他的 `hotkey`、`hotkey bookmark` 照樣交給上游）。
3. AppModel `recordingFinished` 裡的 `GlobalHotKey.shared.setMuteEnabled(false)   // MA-FORK(F3)` → 拿掉。改由 `ForkMute.install` 包住 `recorder.onFinished`（跟既有包 `onStarted` 的做法相同）：先 `setMuteEnabled(false)`，再呼叫上游原本的回呼。
   - 上游只有 `AppModel` 的一處（`recorder.onFinished = { … recordingFinished … }`）設這個回呼，在 `ForkStartup.install` 之前；`recordingFinished` 也只從這裡被呼叫。
   - 原本 `setMuteEnabled(false)` 在 `recordingFinished` 的第 3 行，前兩行（關掉「要停止錄音嗎？」、取消 ⌃⌥⌘B）跟它互不相關。改成在整個 `recordingFinished` 之前做，時間點一樣是「錄音結束、處理結果之前」。

**一併改名（行數不變）**：SettingsView 的 `ForkMuteSettingsRow()   // MA-FORK(F3)` 換成共用列 `ForkRecordingSettingsRows()   // MA-FORK(F0)`，裡面照樣只有 F3 的開關（同一個 `ForkMuteSettingsRow` 畫面）。這是 F11 要放設定的地方，先改成共用入口。

**沒有合併的候選**：見 DF10 的「沒選的做法」。

## F1. 名稱（F1）

- `CFBundleName`（含繁中在地化）設為 `MA`，提供應用程式選單的短名稱；`CFBundleDisplayName` 英文為 `Meeting Assistant`，繁中為「會議助手」。
- App 檔名使用 `Meeting Assistant.app`，對應未在地化的 `CFBundleDisplayName`，讓 Finder 能套用繁中顯示名稱；建置、安裝、DMG 和 CI 同步調整並引用含空白的路徑。
- SwiftUI 取代 `.appInfo` 群組的預設按鈕，呼叫 `orderFrontStandardAboutPanel(options:)`，只指定 `.applicationName` 為 `MA — Meeting Assistant`，版本、圖示和 `Credits.html` 沿用系統行為。
- App 圖示（F1.6）：原始檔是 `Resources/AppIcon-1024.png`（1024×1024、sRGB、外框透明；Apple 圖示範本：圓角方塊 824×824、圓角 185 置中，奶茶色 #F4EADB→#E3CFB4→#D6BC97 漸層加極淡內緣暗角，貓的照片用 Vision 去背後放在框內）。`scripts/make-icon-from-png.sh` 用 `sips` 從原始檔直接縮出 16、32、128、256、512 的 @1x／@2x 共 10 張（512@2x 就是原圖），`iconutil -c icns` 產生 `Resources/AppIcon.icns`，重跑結果相同；`build-app.sh`、`make-dmg.sh`、CI 照舊複製 `AppIcon.icns`（Info.plist `CFBundleIconFile` = AppIcon），Finder、Dock、「關於 MA」都用它。官網與 README 的 `docs/images/icon.png` 是原始檔縮成 256，`site/public/favicon.png`（64）、`apple-touch-icon.png`（180）照 `site/make-images.sh` 的 `sips -z` 從 icon.png 縮。上游的 `scripts/make-icon.swift` 畫舊的波形圖示：fork 保留檔案以減少合併衝突，但不再使用（檔頭註明），跑了會蓋掉 fork 的圖示；合併上游時 `AppIcon.icns`、`docs/images/icon.png` 的圖示衝突一律保留 fork 的版本，再跑 `make-icon-from-png.sh` 確認。`site/` 從 5.0.1 起照上游原樣（fork 沒部署官網，F7.6），裡面的 favicon、apple-touch-icon 也是上游的。
- 介面文字使用「會議助手」／`Meeting Assistant`，提到左上角的應用程式選單時使用 `MA`。內部 Swift target、執行檔、Bundle Identifier、資料和設定位置維持原值（F1.4）。4.7.6 以後名稱都在建置時換（§F7）：原始碼、翻譯表、Info.plist 照上游寫，上面這些值由 `scripts/fork/brand.py` 寫進建好的 app。
- 驗證：Swift 建置、字串抽取與中英翻譯檢查、plist 檢查、打包腳本語法檢查；檢查中英文 bundle 讀取的短名稱和顯示名稱。

- 本地 MCP（4.7）：保留伺服器／CLI 設定鍵 `shiyin`、`bin/shiyin-mcp`、執行檔 `Shiyin` 與 `shiyin://` scheme。設定頁、錯誤訊息這些查翻譯表的文字在建置時換成會議助手；給 AI 工具的英文訊息、`serverInfo` 照上游寫 Shiyin（F7.3）。啟動檔使用 `Bundle.main.executableURL`，能指到含空白的 `Meeting Assistant.app`，不寫死上游 app 名稱。
- Claude Desktop 設定格式錯誤的訊息照上游查翻譯表，建置時跟其他訊息一起換（4.7.6 以前在執行時只換前綴，§F7 之後拿掉）。MCP 的共同標準答案保持上游內容。

## F2. 錄音中標記說話者（F2，DF1）

錄音中不辨識說話者，只記下使用者的標記（時間範圍、名字）；正式轉錄分出說話者後，依時間把名字套到說話者。

### F2.1 資料模型（migration `ma_speaker_tags_v1`）

- 合併 4.0.0：上游的 `v8`／`v9` 保留原樣。Fork 舊版也叫 `v8`，但建立的是 `speaker_tags`；在 `v9` 後以獨立的 `ma_speaker_tags_v1` 補上缺少的 `min_speakers`，並以 `IF NOT EXISTS` 建立標記表及索引。全新、上游 v8/v9、Fork v8 資料庫都走同一流程，既有標記不刪除。
- 合併 4.5.0：保留 `ma_speaker_tags_v1`，接著執行上游參考文件的 `v10`；已經有上游 v10 的資料庫只補 fork 標記表，不重建文件表。
- 回歸檢查：DEBUG 建置後執行 `python3 scripts/dev/check-fork-migrations.py`。使用實際 migrator 與隔離的暫存資料庫，驗證全新、v7、Fork v8、上游 v8/v9/v10 的升級、重新開啟與既有會議／錄音連結／逐字稿／說話者標記／參考文件保留；同時測試標記比對規則，不開啟使用者的資料庫。

```sql
CREATE TABLE speaker_tags (id INTEGER PRIMARY KEY AUTOINCREMENT,
                           meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
                           start REAL NOT NULL, end REAL NOT NULL,   -- 錄音檔的時間（秒），跟逐字稿同一個時間軸
                           name TEXT NOT NULL,
                           kind TEXT NOT NULL,                      -- line：即時逐字稿的一行；now：「正在說話」按鈕
                           created_at TEXT NOT NULL);
CREATE INDEX speaker_tags_meeting ON speaker_tags(meeting_id);
```

- `speakers.name_source` 多一種 `tag`：用標記帶入的名字。
- 封包（`MeetingJSON`）：4.7.6 以前不帶標記；合併 5.0 時改成帶（F2.8，§F-DB.3）。

### F2.2 錄音中標記（F2.1～F2.3）

- 時間：`Recorder.elapsed`（寫進檔案的秒數，暫停的部分不算）。即時逐字稿的時間、正式逐字稿的時間都是這個時間軸（§5.2、§5.3），所以不用換算。
- 一行：標記的範圍就是那一行的開始到結束。這一行「有」的標記 = 中間點落在這一行裡的標記（line、now 都算）。標記一行時先刪掉這一行有的標記，再新增，所以改名字不會留下兩個不同的名字；「清除標記」刪掉這一行有的標記。
- 正在說話：範圍是 `[現在 − 3 秒, 現在 + 1 秒]`（開始不小於 0）。通常是聽了一兩秒、認出是誰才按，前幾秒是他在講，後面 1 秒他通常還沒講完。中間點跟前一個 now 標記差不到 2 秒時取代它（按錯馬上改按另一個人）。暫停時不能按。
- 名單：這場會議的與會者（`participantList`，原本的順序），接著是這場標過、不在與會者裡的名字（依第一次標的時間），不分大小寫去掉重複。認識的人（`people`）放在一行的選單的子選單。
- 新增名字：＋ 加入的名字加進與會者，接在 `participants` 後面（原本用「、」或「，」分隔就用同樣的，不然用「, 」），已經有（不分大小寫）就不加。標記時用的新名字（其他名字…、認識的人）不加進與會者：名單本來就包含標過的名字，清除標記後名字就從名單消失，打錯的名字不會留在會議紀錄的與會者裡（驗證時發現）。
- 說話者辨識關掉時（`AppSettings.diarize`）不顯示標記的介面：沒有說話者可以套用。
- 畫面（§5.4 的左欄，即時逐字稿上方多一排）：

```
┌ 錄音中 ● 12:34   麥克風 ▮▮▮▮▯▯   系統聲音 ▮▮▯▯▯▯          [暫停] [重點] [停止並轉錄] ┐
├───────────────────────────────────────────────────┬──────────────────────────────┤
│ 正在說話  (藍心) (阿華) (Kevin)  [＋]               │ 我的筆記                      │
├───────────────────────────────────────────────────┤                              │
│ [12:01] 藍心  第二，上線日期改到下個月…             │                              │
│ [12:20] 👤    這個改動阿華這週五前上線…             │                              │
│ …       暫定：第三，Lumio 的定價方案…（灰色）       │                              │
└───────────────────────────────────────────────────┴──────────────────────────────┘
```

  - 「正在說話」的名字按下去提示「已標記 12:34 是藍心在說話」。還沒有名字時顯示說明「按 ＋ 加入與會者的名字，誰在說話就按他的名字」。
  - ＋：彈出視窗，輸入框（Enter 就加入）、下面列出還不在名單裡的認識的人（點了就加入），按「加入」。
  - 每一行時間後面是這一行的名字（說話者的顏色，依名單的順序），沒有標記時是淡淡的 👤（滑過時變清楚）。兩者都是選單：名單裡的名字（目前的打勾）、認識的人 ▸、其他名字…、清除標記（有標記才有）。整行按右鍵是同樣的選單，加上「拷貝」（右鍵選單會取代文字原本的選單）。「其他名字…」打開跟 ＋ 一樣的彈出視窗，按鈕是「標記」：標記這一行。
  - SwiftUI 的 `Menu` 在畫面上只畫標題的文字（CLAUDE.md），所以名字用純文字加顏色，不用膠囊背景。

### F2.3 錄完套用（F2.4～F2.7）

`JobRunner.transcribe`：`saveTranscript` 之後、聲紋比對之前呼叫 `AppDatabase.applySpeakerTags`，比對規則在 `SpeakerTagging`（不依賴資料庫，可以單獨測）：

1. 每個標記，算它的範圍跟每位說話者的正式逐字稿段落（`speaker` 有值）重疊幾秒。合計不到 0.5 秒（那段沒人說話）就略過；重疊最多的說話者佔 70% 以上才算「對上」他，不然這個標記不明確。
2. 每位說話者：名字還是預設的（`name_source = 'default'`），而且對上他的標記都是同一個名字（不分大小寫）→ 改成這個名字，`name_source = 'tag'`；聲紋功能打開時跟手動改名一樣 `learnVoiceprint(source: "tag")`（連到認識的人、存聲紋）。對上的標記有兩個以上的名字 → 不套用。
   - 這場會議 `mayHaveMergedSpeakers`（碰撞率 ≥ `Diarizer.Quality.hintThreshold`，§24.5）時只連到認識的人、不存聲紋（`learnVoiceprint(…, remember: false)`，F2.9、DF2）：只標了被併在一起的其中一人時，70% 的門檻擋不下來，存下去的是兩個人混在一起的聲音。所以 `setSpeakerCheck` 要在套用標記之前寫。使用者之後自己改名，或在改名視窗按「儲存」同一個名字（`name_source` 變成 `manual`），就照手動改名存聲紋。
3. 同一個名字可以套到兩位說話者（說話者辨識把同一個人分成兩位時）。
4. 套用後照舊：聲紋比對只比還是預設名稱的說話者，已經連到某人的不會再帶給別人；排整理（會議紀錄就會用名字）；還有預設名稱的才猜說話者。
5. 重新轉錄：`saveTranscript` 保留改過的名字時，`name_source = 'tag'` 的不保留（回到預設名稱），存完再照上面重新對一次，說話者編號變了也會套到對的人。
6. 重新辨識說話者（§23.3，F2.10）：`inheritNames` 和使用者改過句子的說話者都不沿用 `tag` 的名字；`reassignSpeakers`、`setSpeakerCheck` 之後先套用標記（同上，含第 2 點的條件），再重新學沿用的名字的聲紋、聲紋比對。說話者被拆開時，標記對得上的那一位也會拿到名字；對不上了就變成「沒套用的標記」（§F2.4）。
7. 合併說話者（§24.2，F2.11）：合併到 `tag` 的說話者，跟 `manual`、`suggestion` 一樣用合併後的聲紋重新學（`source: "tag"`，第 2 點的條件一樣）。

### F2.4 沒套用的標記（F2.5）

- 每個標記在逐字稿上的位置：跟範圍重疊最多的那一段，沒有重疊就用時間最近的一段。那一段的說話者現在的名字跟標記的名字不同（不分大小寫），就是「沒套用」。依目前的名字判斷，所以使用者自己改名之後就不算了。`MeetingDetail.buildIndexes` 算好每個標記的位置。
- 只在轉錄完、有說話者、不在錄音中時顯示：
  - 會議頁上方（跟猜說話者的提示同一區）：「錄音時標記的名字有 2 個沒有自動套用：Kevin、阿華」「查看」→ 切到逐字稿、捲到第一個並加底色。
  - 逐字稿那一段的文字下面（跟校正建議同一個位置）：「錄音時標記為 Kevin」「刪除標記」「只改這句」「套用到說話者 3」。套用 = 幫那一段的說話者改名（跟手動改名相同，會記住聲紋、會議紀錄裡的名字一起換）。
  - 只改這句（F2.12）：標記蓋到的句子 = 那一段的說話者（`segmentSpeaker`）的段落裡，跟標記範圍重疊至少佔這一句一半長度的，加上那一段本身（`SpeakerTagging.covered`）；不只一句時按鈕是「只改這 N 句」。改給誰：這場有名字相同（`sameName`）的別位說話者就改給他，沒有就新增一位，名字是標記的名字、`name_source = 'manual'`（使用者按了才改，跟改名一樣算自己確認的）。走 `reassignSegments`（§24.3，`speaker_manual`、復原、沒有段落的說話者拿掉都一樣）；新的說話者沒有聲紋，不連到認識的人、不改會議紀錄（同 R23 不做的「改過句子後重新算聲紋」）。
- 套用了的名字（`name_source = 'tag'`，F2.9）：會議頁的說話者列跟聲紋自動帶入的名字用同一個元件（`AutoSpeakerName`），後面的小標記是「標記」（不是「自動」），選單一樣是「是別人：」、「其他人…」、「不是 X（不知道是誰）」；說明是「錄音時標記的名字。不對的話點名字」。逐字稿的改名視窗也有「不是他」，說明是「這個名字是從錄音時的標記帶入的。不對的話直接改名，或按「不是他」。」。「不是他」跟聲紋的一樣（`rejectVoiceprintMatch`）：回到預設名稱、`name_source = 'manual'`、刪掉這場這位說話者的聲紋；標記還在，所以會出現在沒套用的提示，可以刪掉。

### F2.5 DEBUG

- `tagspeaker now <名字>`：錄音中等於按「正在說話」的名字。
- `tagspeaker line <第幾行> <名字|->`：錄音中標記即時逐字稿的第 N 行（從 0 開始），`-` 是清除標記。
- `tagspeaker add <會議 id> <開始> <結束> <名字>`：直接加一個 line 標記，測套用規則用；`tagspeaker delete <標記 id>`。
- `tagspeaker only <會議 id> <標記 id> [<錯誤輸出.json>]`：等於按沒套用的標記的「只改這句」（F2.12）。加了第 3 個參數、而且是 `-debugQuietPrompts YES` 時：先記下呼叫前的 `model.errorMessage`，照常同步呼叫真正的 `reassignTaggedSegments`（同一筆交易、同樣的 `perform`），返回後立刻把這次新出現的錯誤寫進輸出檔，再把 `errorMessage` 還原成呼叫前的值，主視窗的「出了一點問題」對話框（綁在上游 `MainWindow` 的 `errorMessage`）就不會跳出來。只有這一條指令、只有給了輸出檔的那一次這樣做，不清別的錯誤；正式版沒有這條路。約 1 秒後在同一個檔補上 `errorMessageAfter`（那時的 `errorMessage`）、`sheetVisible`（有沒有視窗掛著 sheet 或對話框）、`mainWindowVisible`，給 `f2-atomic-check.py` 確認畫面上沒有對話框。
- `addparticipant <會議 id> <名字>`：等於在 ＋ 按「加入」。
- `tagui add`、`tagui name <第幾行>`：等於按 ＋、一行選單裡的「其他名字…」，打開輸入名字的彈出視窗；接著用 `typefield 名字 <名字>`、`submitfield 名字` 送出（走表單的送出路徑）。這台電腦沒有輔助使用權限時用這個代替 AX。
- `applytags <會議 id>`：等於重新轉錄存檔後那幾步（`tag` 的名字先回到預設，再套用標記、學聲紋，然後聲紋比對）。
- `speakertags <會議 id> <輸出.json>`：每個標記和它對上的說話者、重疊比例、逐字稿上的位置、是不是沒套用；說話者的名字、來源、連到的人。
- `state` 的 `recorder.liveTags`：即時逐字稿每一行的名字（沒有是空字串）。
- `windowshot <輸出.png> [main|popover]`：app 自己把主視窗（或彈出視窗）畫成圖片（`cacheDisplay`），不需要螢幕錄製權限；畫的是視窗裡真正的元件，選單也是畫面上的樣子（`snapshot` 畫不出 ScrollView 和選單）。
- `-debugQuietPrompts YES` 也不發通知：測試版跟使用者的拾音是同一個 bundle ID，通知權限還沒決定時轉錄完會跳出系統的詢問。

### F2.6 驗證

- 比對規則：`SpeakerTagging` 用小程式單獨測（同名、不同名、不明確、沒人說話、同名兩位）。資料庫：測試用的 `SHIYIN_HOME` 建一場有說話者的會議（直接寫段落），`tagspeaker add`＋`applytags` 跑一遍，加上手動改過名字的說話者不覆蓋、聲紋有存、`tag` 的名字在重新套用時會重算。
- 「只改這句」的交易（DF8）：`python3 scripts/fork/f2-atomic-check.py <SHIYIN_HOME> <shiyinctl> --out <資料夾>`（DEBUG 版先用那個 home 開著）：SQLite trigger 只擋「改名成丙」，按「只改這句」後說話者、句子、復原快照要跟按之前完全相同，而且錯誤要是預期的 SQLite 19（`tagspeaker only` 的錯誤輸出檔），`state` 的 `errorMessage` 是空的、沒有視窗掛著對話框（不在使用者畫面上跳出「出了一點問題」）；拿掉 trigger 再按一次、再復原，輸出可以跟別的版本逐位元組比。
- 端到端：多人真人錄音用模擬錄音（`record-sim`），在某人單獨講話時用 `tagspeaker now`、`tagspeaker line` 標記 → 停止 → 轉錄完那些說話者改成標的名字；重新轉錄後名字還在。
- 畫面：在真的畫面上用 AX 按過「正在說話」的名字、＋ 的輸入框和「加入」、一行的選單（名單、其他名字…的「標記」、清除標記）、錄完的提示「查看」、逐字稿的「套用到…」「刪除標記」。英文介面看過。

## F3. 錄音中靜音麥克風（F3，DF3）

錄音來源是「麥克風＋電腦聲音」（`source == "both"`）時，錄音中可以讓麥克風那一聲道變成無聲，電腦聲音照常錄。

### F3.1 寫檔（`RecordingWriter`）

- `setMuted(channel, Bool)`。`append`：靜音的聲道放進 `pending` 的是同樣長度的 0，`acceptedFrames` 照算，所以兩個聲道照樣對齊（§5.2 的補靜音規則不用改），錄音秒數不受影響。
- `levels`、`silentSeconds`、`recent`（每 100 毫秒的音量）照真的聲音算：忘了打開的提醒（§F3.2）要知道現場有沒有人在說話。檔案、即時轉錄、語言偵測拿到的都是 0。
- 即時轉錄的單聲道混音：麥克風靜音時只用電腦聲音那一聲道（不跟 0 平均，音量才不會小一半）。
- 正式轉錄、說話者辨識、壓縮、匯出都讀檔案，不用改：那段麥克風本來就是 0。

### F3.2 `Recorder`

- `micMuted`（畫面觀察）、`setMicMuted(_:)`、`toggleMicMute()`：只有 `source == "both"`、錄音中才有作用。`begin` 時設回 false；`pause`、`resume` 不動它。
- 收音提醒（§26.1）：`micMuted` 時 `checkLevels` 不判斷，正在顯示的收音提示收掉；打開麥克風時 `noisySeconds`、`quietSeconds` 歸零（30 秒的音量紀錄照留，是真的聲音）。
- 忘了停止錄音（§35）：不改。即時逐字稿在跑時只聽得到電腦聲音；沒在跑時 `soundsLikeSpeech` 看的是真的聲音，現場有人說話也算有人在（R48.4 寧可晚停）。
- 忘了打開的提醒（`muteHint`，F3.4）：靜音中、沒暫停時每秒記一筆（`soundsLikeSpeech` 拆成看單一聲道）：麥克風像說話、電腦聲音像說話。最近 20 秒裡麥克風像說話 ≥ 10 秒、電腦聲音 ≤ 2 秒就顯示。「知道了」（`dismissMuteHint`）這次靜音不再顯示；再按一次靜音時紀錄清掉、重新算。打開麥克風就收掉。第一次顯示時呼叫 `onMuteHint`，AppModel 照收音提醒的規則送通知（主視窗不在最前面、同一場最多一次，kind `muted`）。

### F3.3 介面

- 錄音畫面（§5.4）上方：麥克風的圖示換成按鈕（`mic.fill`／靜音時紅色的 `mic.slash.fill`），靜音時音量條變淡（透明度 0.35）、後面寫「麥克風已靜音」。滑鼠提示「靜音麥克風（⇧⌘M）：現場的聲音不錄，電腦聲音照常錄」／「打開麥克風（⇧⌘M）」。只錄麥克風時圖示照舊不能按。
- 提示列（跟收音提醒同一區、同樣式）：「麥克風靜音中，現場好像有人在說話。要錄進去的話，打開麥克風。」[打開麥克風]（`borderedProminent`）[知道了]。
- 選單列（§31.5 的錄音區）：麥克風音量條上面一列「靜音麥克風」／「打開麥克風」按鈕，靜音時寫「麥克風已靜音」；同一句提示和兩顆按鈕。圖示（`menuBarSymbol`）：有提示時照舊是警示的樣子，否則靜音時是 `mic.slash.circle.fill`。
- 「檔案」選單：「麥克風靜音」／「打開麥克風」（⇧⌘M），不是 `both` 的錄音時不能按。
- 全域快捷鍵 ⌃⌥⌘M（`GlobalHotKey` 第 3 組）：跟標記重點一樣只在錄音中註冊，而且只在 `both` 的錄音（`onStarted` 時看 `AppSettings.muteHotKey`），停止時取消註冊（開始、停止都由 `ForkMute.install` 包住 `recorder.onStarted`、`onFinished` 做，§F0.7）。按了切換，靜音播「Bottle」、打開播「Pop」（標記重點是「Tink」），人在 Teams 裡也知道按到了。
- 設定「錄音與轉錄 → 提醒與快捷鍵」多一個開關：「錄音中按 ⌃⌥⌘M 靜音或打開麥克風（麥克風＋電腦聲音的錄音）」，`muteHotKey`，預設開。

### F3.4 DEBUG

- `micmute on|off|toggle`：等於按錄音畫面的麥克風圖示；`micmute dismiss`：提示列的「知道了」。
- `hotkey mute`：模擬按下 ⌃⌥⌘M（上游 `hotkey` 的子指令，由 `ForkDebug.intercept` 先接，§F0.7）。
- `state` 的 `recorder.micMuted`、`recorder.muteHint`、`recorder.muteCheck`（最近 20 秒麥克風、電腦聲音像說話的秒數）；`hotkey.muteRegistered`。

### F3.5 驗證

- 模擬錄音（`record-sim <檔案> 1 1`，兩個聲道是同一個檔）：`python3 scripts/fork/f3-mute-check.py <SHIYIN_HOME> <shiyinctl> --out <資料夾>` 用一直有聲音的測試音錄一段、`micmute on`、快捷鍵解除再靜音、`off`，依這次錄音的會議（`recorder.meetingId`）的 `audio_file` 讀檔（等轉錄後壓成 M4A，用 afconvert 解碼），檢查兩個聲道、靜音那段麥克風是 0、電腦聲音照常、沒靜音的區間兩個聲道都有聲音。不要掃 `audio/` 下所有的檔：同一個 home 裡別的測試放的靜音 WAV 會被當成錄音。舊的做法是停止後用 numpy 讀 WAV：靜音那段左聲道全是 0、右聲道照常，檔案長度等於錄音秒數；即時逐字稿在靜音那段照樣有字（電腦聲音那一聲道）。
- 提醒：模擬錄音的兩個聲道一樣，電腦聲音一直有聲音，不會提示；用 `recordstall <秒數> 1` 讓電腦聲音停一段（停的部分補 0），靜音中 20 秒左右出現提示、`micmute dismiss` 收掉、再靜音一次又會出現。
- 收音提醒在靜音時不出現；快捷鍵只在 `both` 的錄音中註冊。
- 畫面：`windowshot` 看錄音畫面、選單列的靜音狀態和提示列。真的畫面上按圖示、真的按 ⌃⌥⌘M 待使用者。

## F4. 紀錄條列頁的閱讀與複製（F4，DF4）

只改紀錄分頁的條列模式（`NotesPage` 的 `ReadingColumn` 那一支）和播放條的議題帶；心智圖模式、編輯器（`NotesEditor`）、匯出、資料、提示詞、標準答案都不變。只做 Mac，`windows/` 不動。

### F4.1 分段複製（F4.1）

- `NotesSectionScope`：`summary`、`decisions`、`actionItems`、`openQuestions`、`custom(Int)`、`topic(Int)`（`notes.topics` 的位置）。
- `NotesExporter.plainSection(_ scope:, notes:, language:) -> String`：跟 `plain` 同一套固定文字（`ExportText`，會議語言）。
  - 一般段落：第一行段落名稱（`x.section(id)`，自訂段落用它的 title），之後每條 `- 內容（時間）`（`x.paren`）。
  - 待辦：第一行「待辦」，每條 `- 負責人：事項（期限 2026-11-11）（59:37）`；沒有負責人寫 `x.unassigned`，沒有期限就省略期限那段。英文是 `- Owner: task (Due 2026-11-11) (59:37)`。
  - 議題：第一行 `[開始] 標題`（同 Markdown 匯出的 `### [start] title`），之後每條重點。
  - 段落是空的時候回傳空字串（畫面上空段落本來就不顯示）。
- `AppModel.copyNotesSection(_ scope:)`：從 `exportBundle()` 的 notes 和會議語言產生，放進剪貼簿（純文字），提示「已複製「段落名稱」」。不經過畫面的文字。
- 按鈕：段落標題列右邊的 `doc.on.doc` 圖示按鈕（`.borderless`，滑鼠提示「複製這一段（純文字）」／「複製這個議題（純文字）」），滑鼠移到段落上才顯示（`.opacity`，不改排版；鍵盤、輔助使用照樣找得到）。按鈕不跟著文字大小（R59.2）。
- 跟 D132 不衝突：右上角是整份複製（同一件事一個入口），這裡是「只複製這一段」，是不同的動作。

### F4.2 議題帶依重點時間切段（F4.11）

- 新函式 `MindMap.topicSegments(notes:duration:untitled:minSeconds: = 60) -> [TopicRange]`，`topicRanges` 和它的標準答案（`util/topic-ranges.json`）不動：Windows 也比這份標準答案，fork 只改 Mac。`TopicRange.branch` 同心智圖（`shownTopics` 的第幾個），顏色一樣。
- 規則：
  1. 每個議題的時間點：`start` 加上每條重點的 `time`（`TimeFormat.seconds`）；讀不到的、≥ 會議長度的丟掉。一個時間點都沒有的議題不畫。
  2. 全部時間點依時間排序（同一秒照 branch），每個時間點開始一段、屬於它的議題；同一個議題相鄰的合成一段。
  3. 每段到下一段的開始，最後一段到會議長度。
  4. 拿掉長度 ≤ 0 的段（同一秒有好幾個議題時，前面的議題只會切出零長度的段），再合併因此相鄰的同議題段。零長度段不算「另一段」，也不受保護。
     **開始段**：這時候（區間確定、零長度段拿掉之後）實際包含那個議題自己 `start` 的段，用半開區間判斷（`段的開始 ≤ start < 段的結束`，同播放條判斷目前議題）。只看區間，不看「收過 start 這個時間點」：`start` 跟後面的議題同一秒時，那一秒歸後面的議題，前面那段（例如提早的重點切出的段）並不包含 `start`，不是開始段。每次合併後重新判斷。
  5. 短於 `minSeconds`、不是開始段、而且那個議題還有別的段：併進前一段（是第一段就併進後一段，開始時間取它的），再合併相鄰同議題的段，重複到沒有為止。開始段再短也保留（議題列的開始時間在議題帶上一定找得到，預覽 report-v2 的承諾）；議題的唯一一段也不會被併掉。早於 `start` 的重點切出的段不是開始段，照 60 秒的規則處理。
- 從重點的時間點開始算，不往前多算；早於議題 `start` 的重點照算（會在前面多一段）；議題內重點的順序不影響（全部重新排序）。
- 重點時間都在自己議題的區間內（`start` 到下一個議題的 `start`）時，結果跟 `topicRanges` 一樣。
- `MindMap.topicBranches(_ notes:) -> [Int: Int]`：`notes.topics` 的位置 → branch（沒畫出來的議題沒有）。條列頁的議題色條、膠囊、目前議題都用它對到同一支。

### F4.3 播放條、目前議題（F4.9、F4.10）

- `PlayerBar` 的議題帶改用 `topicSegments`。`TopicBand` 照舊（一段一個按鈕），點了 `onSeek(start)`，另外呼叫 `onTopic(branch)`。
- 切段的結果快取在 `AppModel.topicSegments(notes:duration:)`（`@ObservationIgnored`，會議紀錄或長度變了才重算；比對用 `==`，同一份紀錄是同一塊記憶體，比對很快）。`PlayerBar`、紀錄頁都用它，`PlayerBar` 每 0.1 秒重畫時只查目前的 branch，不重新切段。
- 目前議題：`PlayerBar` 本來就每 0.1 秒隨播放時間重畫；在這裡查目前的 branch，`.onChange` 到 `model.currentTopicBranch`（`@Observable` 的 `Int?`，值變了才設）。紀錄頁只讀 `currentTopicBranch`，播放中不會每個 tick 重算整頁（§3.5.1 的效能原則）。暫停時也標出（標示寫「目前播放位置」）。換會議時設回 nil。
- 點議題帶：`model.tab == .summary` 而且是條列模式（`notesView` 是 `list`）時才發送`model.topicScrollRequest = TopicScrollRequest(branch:, id: UUID())`（每次點都不同，同一段連點也會捲）；`NotesPage` 用 `ScrollViewReader` 在 `onChange` 時展開那個議題、`scrollTo("topic-<位置>", anchor: .top)`。其他分頁照舊只播放。

### F4.4 條列頁（F4.2～F4.8）

- 順序：摘要 → 決議 → 待辦 → 未決問題 → 自訂段落 → 議題 → 「由 X 整理．範本」。
- `ForkNotesSection(title:count:accent:copy:)`（上游 `NotesSection` 的 fork 版，§F0.2）：標題（18 pt）、條數（`.secondary`，callout）、複製按鈕；`accent` 不是 nil 時左邊一條 3 pt 的色條（`Rectangle` 在 `overlay(alignment: .leading)`，內容往右縮 14 pt）。
  - 顏色（`Color` 的動態色，§9）：摘要 `slate` 淺 `#6B7A8F`／深 `#8E9CB0`（低飽和，跟待辦的藍、心智圖的 6 色分得開，對比 4.37:1／5.81:1）；決議 `celadon`；待辦 `MindMap.palette[1]`（藍 `#3E6FA8`／`#6E9BD6`）；未決問題 `signal`。議題段落本身不加段落級色條（每個議題已經有自己的色條，再加會變成兩條並排）。
- `ItemList` 加 `symbol`（`•`、決議 `✓`、未決問題 `?`）、`symbolColor`。每一條是 `NoteRow`：`HStack(alignment: .firstTextBaseline)`：符號、文字（`.textSelection(.enabled)`、`maxWidth: .infinity, alignment: .leading`）、`ReviewMarker`、`TimeButton(style: .subdued)`。`NoteRow` 用 `.onHover` 記自己是不是被指著，傳給 `TimeButton`：平常 `.tertiary`、指著時 `celadon`。文字填滿中間，時間點就在行尾對齊成一欄。不加 `fixedSize`（CLAUDE.md），文字在 ScrollView 裡照舊換行。
- `TimeButton` 加 `subdued: Bool`、`highlighted: Bool`（預設 false、行為不變，逐字稿、心智圖、提問不受影響）。
- 待辦表 `ActionItemsTable`：`Grid` 四欄：負責人、期限、事項、時間點（含「？」）；三個文字欄都 `.textSelection(.enabled)`；負責人粗體，沒有時琥珀色「未指定」；期限等寬數字、沒有時「—」；就地回答的卡片照舊在那一列下面跨四欄。
- 議題（`TopicBlock`）：左邊 3 pt 色條（`MindMap.color(branch, dark:)`）。
  - 第一行：展開箭頭、開始時間（`TimeButton`）、標題（16 pt，太長時換行，不截斷）、「N 條」、「？N」（這個議題各重點的待確認加總，`ReviewMarker` 同樣式，點了展開那一條的題目）、複製按鈕。
  - 有好幾段或是目前議題時多一行（縮排對齊標題）：「N 段：」和每段的開始時間（`TimeButton`），用會自動換行的 `FlowLayout` 排，段很多、字很大、視窗很窄時往下換行，不擠壓也不超出；目前議題時接著寫「目前播放位置」。
  - 展開／收合只由兩個按鈕觸發：展開箭頭、標題加條數（`.plain` 的 `Button`）。時間、「？」、複製按鈕是旁邊獨立的按鈕，父層沒有點擊手勢，點它們不會收合。
  - 展開時下面是重點的 `ItemList`（就地回答照舊）。目前議題的底色是那一支顏色的 8%。
- 收合狀態：`AppModel.notesCollapsedTopics: Set<Int>?`（nil＝用預設：議題 > 5 個全部收合，否則全部展開）。換會議（`selection` 的 `didSet`）設回 nil；切到逐字稿、提問分頁再回來不會丟。段落標題列右邊「全部展開」「全部收合」。有就地回答展開在某個議題的重點下時，那個議題強制展開（不然卡片被藏起來）。
- 議題膠囊（議題 > 5 個）：編輯列下面一列 `ScrollView(.horizontal)`，每個議題一個膠囊（色點、標題、有好幾段時「×N」），目前議題外框青瓷綠；點了展開並捲到那個議題。
- 文字大小（R59）：條目、時間點、議題標題跟著放大；複製按鈕、膠囊、「全部展開」不跟著（同編輯列）。

### F4.5 DEBUG

- `topicsegments <輸入.json> <輸出.json>`：輸入 `{"duration": 秒數, "cases": [{"name", "notes": MeetingNotes 的 JSON}]}`，每個 case 輸出 `segments`（branch、start、end）和 `ranges`（現在的 `topicRanges`），給驗證腳本比對。
- `copysection <會議 id> <scope> <輸出.txt>`：`plainSection` 的結果寫到檔案（不碰剪貼簿）。scope：`summary`、`decisions`、`actionItems`、`openQuestions`、`custom:N`、`topic:N`。
- `state` 加 `currentTopicBranch`、`notesTopicsCollapsed`（目前收合的議題位置）。
- `topicscroll <branch>`：等於在紀錄分頁點議題帶的那一支。

### F4.6 驗證

- `scripts/dev/f4-check.py`：產生 `topicsegments` 的輸入（無重回的會議＝舊規則、模擬重回、短於 60 秒的片段、議題內時間亂序、讀不到的時間、早於議題開始的重點、空議題），跑 DEBUG 的 `topicsegments`，比對預期；再對示範會議（中、英、日）跑 `copysection` 比對預期文字。
- 畫面：`windowshot` 看議題 ≤ 5 個（展開）、> 5 個（收合、膠囊）、深色、文字大小 150%、播放中目前議題、`topicscroll` 後捲到的位置。真的畫面上的滑過變色、點按、複製後貼上待使用者。

## F7. 品牌集中在建置時替換（F7，DF7）

原始碼照上游寫「拾音」「Shiyin」，建置時把建好的 app 換成 fork 的名稱。合併上游時品牌不再造成衝突（PLAN-fork-5.0 §4；4.7.6 以前約 20 處衝突來自品牌）。

### F7.1 設定（`fork/brand.json`）

- `names`：每個介面語言的名稱對照。zh-Hant「拾音→會議助手」、zh-Hans「拾音→会议助手」、en「Shiyin→Meeting Assistant」（en 的值偶爾夾中文，也換「拾音」）。之後才有的語言（日、韓介面）用 en 那一份。
- `bundleName` = MA、`displayName`（各語言）、`aboutName` = MA — Meeting Assistant、`shortName` = MA（錄音島上用的簡稱，F7.7）。
- `phrases`：整句的特例（`from`、`to`、`required`），先換、不再被名稱對照影響：「「拾音」選單」→「「MA」選單」（應用程式選單叫 MA，F1.1）、`/Applications/Shiyin.app` → 加引號的 `Meeting Assistant.app`、第三方授權的開場白；Credits 的贊助說明（上游的「覺得拾音好用的話，可以請我喝杯咖啡」）換成空字串、整段拿掉（F13.1，§F13.1）。`required` 依資源指定哪些整句一定要命中（相對 `Contents/Resources` 的檔案，`guide:` 開頭是安裝說明）：換完的資源裡看不到 `to` 就失敗。上游改了句子（連一個標點）時，整句對不到，一般的名稱替換會把句子換成「Enjoying Meeting Assistant?」、署名消失，殘留檢查看不出來，所以要靠 `required`（2026-11-18 審查 P2-2）。檢查的是輸出有沒有 `to`，對換過的產物重跑結果不變。
- `keep`：不換的片段（正規表示式，F7.2）。`Shiyin(?=[A-Z])` 是 `ShiyinIssuesURL` 這類鍵名、識別；`拾音 Shiyin(?= \(MIT\)|: LICENSE)` 是上游 MIT 聲明的那一項和標題（F13.2）。
- `upstreamLicense`、`creditsForbidden`、`licenseIntro`、`licenseList`、`releaseNotes`：F13 用的設定（§F13）。

### F7.2 建置時替換（`scripts/fork/brand.py apply <app>`）

`build-app.sh` 在組好 app、簽章之前呼叫（`--debug` 同一條路），只改 `$APP` 裡的檔案，repo 不變：

- 各 `.lproj` 的 `Localizable.strings`、`.stringsdict`（xcstringstool 編出來的 XML plist）：只換值、鍵不動。繁中是翻譯表的來源語言，編出來的繁中檔也有全部的鍵（值等於鍵），所以換值就夠，不用另外寫明確的繁中值。
- `InfoPlist.strings`：鍵也換（鍵是 Info.plist 的英文值，例如 `Shiyin Meeting`）；`CFBundleName`、`CFBundleDisplayName` 直接設成 `brand.json` 的值。
- `Info.plist`：`CFBundleName` = MA、`CFBundleDisplayName` = Meeting Assistant；`infoPlistBrandKeys`（檔案類型名稱、權限說明）換名稱；識別（執行檔、bundle id、URL scheme、UTType）不動。另外寫入 `MABrand`（名稱對照、`aboutName`），給 §F7.3 的接點讀。
- `Credits.html`、`ThirdPartyLicenses.txt`：用 `phrases` 換開場白、拿掉贊助說明（拿掉後留下的空 `<p>` 一起刪），再插入上游的 MIT 聲明（§F13.2）。`build-app.sh` 產生 Credits 的程式照上游原樣。
- 每一條換過的字串比對格式碼（`%@`、`%lld`、`%1$@`…）的種類和數量，不同就失敗（名稱裡不會有格式碼，這是防 `brand.json` 寫錯）。
- `make-dmg.sh`：`brand.py guides` 把兩份安裝說明換好放到暫存資料夾再轉 PDF；DMG 裡的第三方授權改拿 app 裡換過的那份。
- 驗證基準：`brand.py compare <上一版.app> <新.app>` 逐鍵比對各 `.lproj`、Info.plist（版本號除外）、Credits、第三方授權；舊版的鍵是 fork 寫死的「會議助手」時，先還原成上游的鍵再找。

### F7.3 不經過翻譯表的接點（`Sources/Shiyin/Fork/Brand.swift`）

`Brand` 讀 Info.plist 的 `MABrand`；沒有（`swift build` 直接跑、上游原樣）時回傳上游名稱。上游檔裡的接點各 1 行，標 `// MA-FORK(F7)`：

- 「關於 MA」：`BrandAboutCommand` 取代系統的 `.appInfo`；5.0.1 時 `AppCommands` 直接放 `BrandAboutCommand()   // MA-FORK(F7)`，F10 起改由 F0 的共用入口 `ForkAppMenuCommands(model: model)   // MA-FORK(F0)` 放（§F10.6，同一行換掉、不多一行），`orderFrontStandardAboutPanel(options: [.applicationName: Brand.aboutName])`（F1.3）。
- 更新說明選段落（`ReleaseNotes.items`）：`Brand.names("拾音")`、`Brand.names("Shiyin")` 認得 fork（會議助手、Meeting Assistant）和上游開頭的段落。
- 上游 5.0 的提醒事項（5.0.1 接上，F7.5）：`Reminders.listTitle` 包成 `Brand.name(MeetingLanguage.ui(zh: "拾音", en: "Shiyin"))`；`EventKitReminders.list()` 找已存在的列表時把 `["拾音", "Shiyin"].contains($0.title)` 換成 `Brand.isListTitle($0.title)`（會議助手、Meeting Assistant、拾音、Shiyin 都認得，舊列表沿用）。
- MCP 給 AI 工具的英文訊息、`serverInfo`：不換（F7.3），列白名單。
- 錄音島的「打開拾音」按鈕（F7.7，5.0.1）：`IslandView` 的按鈕標題包成 `Brand.short(String(localized: "打開拾音"))`。同一個鍵「打開拾音」選單列也在用（要照舊寫「打開會議助手」），翻譯表的整句特例（`phrases`）是以資源為單位、分不出是哪個畫面在用，所以不用 `phrases`，改在執行時換：`Brand.short` 把查表後的字串裡的完整品牌名（`names` 的值：會議助手、会议助手、Meeting Assistant）換成 `MABrand.shortName`（brand.json 的 `shortName`，`brand.py apply` 寫進 Info.plist），跟中文相鄰時前後補一個空白（「打開 MA」「打开 MA」，英文「Open MA」）。沒有 `MABrand`（上游原樣）時原樣回傳。上游檔只多 1 行接點。

### F7.4 檢查（`brand.py check <app>`、`check-sources`）

- 建好的 app：各 `.lproj` 的值、`InfoPlist.strings` 的值、Credits、第三方授權的開頭、Info.plist（識別除外）扣掉 `keep` 後還有「拾音」「Shiyin」（簡體也是這兩個字）就 exit 1。`Info.plist` 沒有 `MABrand` 也算失敗。`apply` 最後一定跑一次，所以建置會失敗。
- 原始碼（`Sources/**/*.swift`）：`brand.py` 把 Swift 切成字串常值（認得 `//`、`/* */` 註解，一般、多行 `"""`、raw `#"…"#` 字串，字串插值裡的程式另外算），每個字串找**包住它的最內層呼叫**（`(` 前面的名稱；`[ ]`、`{ }` 也算一層）和它在第幾個參數。品牌字只在下面能證明會查表的寫法放過，其他一律算違規（附近有別的 `Text(` 不算數，審查 P2-1；呼叫名稱對、參數卻是 String 運算式也不算數，複審 P2-3）：
  - 支援（放過）：`Text`、`Button`、`Toggle`、`Label`、`Section`、`Window`、`Menu`、`Link`、`LabeledContent`、`Picker`、`TextField`、`GroupBox`、`LocalizedStringKey`、`LocalizedStringResource`、`.help`、`.alert`、`.navigationTitle`、`.confirmationDialog`、`.accessibilityLabel` 的**第一個、沒有標籤**的參數，或 `String(localized:` 的參數；而且整個參數（註解當成空白）只能是「一個字串常值」或「條件 ? 常值 : 常值」（條件裡沒有字串、沒有 `?`）。字串可以有插值（插值裡的字串另外判斷）；參數後面接修飾元（`Text("…").font(…)`）、後面還有別的參數（`Button("…", role:)`）都可以。
  - 報錯，因為不會查表：三元運算一邊是變數、`"…".uppercased()` 這類字串方法、`as String`、`+` 串接（中間夾註解也一樣）、`??`、`verbatim:`、`String(format:`、`ui(zh:`／`text(zh:`、陣列字典裡的字串、`// l10n-skip` 的行、不在任何呼叫裡的字串。
  - 報錯，但其實會查表（保守，用白名單或改寫）：參數型別是 `LocalizedStringKey` 的自訂 View（例如 `CustomLookup("…")`；確認參數型別後可以把名稱加進 `LOOKUP_CALLS`，不要只看名字像就加）、多一層括號 `Text(("…"))`、`LocalizedStringKey(stringLiteral:)`、`String(localized: "鍵", defaultValue: "…")` 的 `defaultValue`（編譯器抽的是鍵的位置）、條件裡有 `?`（`x?.y ? "a" : "b"`）。
  - 白名單 `fork/brand-allow.txt`：`<路徑> | <字串常值的全文>`，太長時寫開頭加「…」；比對的是那一個字串，不是整行。用不到的條目也報錯，原始碼改了要一起刪。
- 怎麼確定掃描器沒有放過不查表的字串：Swift 編譯器的 `-emit-localized-strings` 會寫出每個檔真正進翻譯表的字串和**位置**（行、欄，欄是 UTF-8 位元組）。`brand.py crosscheck <stringsdata 資料夾>` 逐個核對：掃描器放行的品牌字串，編譯器在同一個位置一定要抽得到，否則失敗；編譯器抽到、掃描器報錯的列成「保守」。產生 stringsdata：`swift build -c debug --arch arm64 --disable-keychain --scratch-path <別的資料夾> --target Shiyin -Xswiftc -emit-localized-strings -Xswiftc -emit-localized-strings-path -Xswiftc <資料夾>`（2026-11-18 對整個 repo：品牌字串 105 個、放行 83 個，不一致 0、保守 0）。`brand-test.py` 也對一個小的 probe 檔跑同樣的核對。
- 為什麼建置時用掃描器、不直接用編譯器的 stringsdata（DF7）：stringsdata 要在編譯時加旗標，等於改上游 `build-app.sh` 的 `swift build` 那一行（加旗標也會讓整個模組重編），或每次建置另外多編一次整個 Shiyin 模組（約 50 秒）；`check-sources` 也就不能在沒有編譯的情況下快速跑。掃描器只放行兩種能證明的寫法，其他保守報錯，誤報可以用白名單處理，不會默默漏掉；它的正確性改由 `crosscheck`（合併上游後、改掃描器時）和測試裡的編譯器核對來保證。
- 上游新增不查表的品牌字時，建置失敗，看那一處是要加接點、還是列白名單。

### F7.5 驗證

- `brand.py compare` 4.7.6 正式版（GitHub Release 的 DMG）和新建置：2562 條相同；差異 4 條（Claude Desktop 設定檔格式錯誤的繁中訊息，4.7.6 在執行時才換前綴、顯示一樣；本機 Xcode 27.2 的 xcstringstool 多編出 3 條值等於鍵的英文條目，跟品牌無關）。
- 安裝說明換完跟 4.7.6 的兩份 HTML 逐字相同。
- `scripts/fork/brand-test.py`（`python3 scripts/fork/brand-test.py -v`，暫存資料夾、不碰 repo 和使用者的 app）：審查的 ReviewBrandProbe（前一行有 `Text(`、下一行不查表）要報；真正跨行的查表（三元運算分兩行、`.help`、插值、`String(` 換行才寫 `localized:`）要放過；`+` 串接、`verbatim:`、`??`、陣列、`ui(zh:`、`String(format:`、插值裡的 `ui`、raw、多行、`l10n-skip` 要報；複審的四種 String 運算式（三元一邊是變數、`.uppercased()`、註解隔開的 `+`、`as String`）要報；§F7.4 的支援寫法要放過、保守報錯的寫法要報；小 probe 檔用編譯器核對（掃描器放行的都要在編譯器的位置裡）；白名單只放過那一個字串、用不到的條目要報；Credits 中英贊助句、授權開場白、安裝說明的選單名和 `xattr` 指令漂移都要失敗；正常的 apply、guides 重跑結果不變；漏換、格式碼不同、必要的檔案不見要失敗。
- `scripts/fork/brand-hooks-test/main.swift`：`swiftc -swift-version 5 -o <輸出> scripts/fork/brand-hooks-test/main.swift Sources/Shiyin/Fork/Brand.swift` 跑過接點（沒有 MABrand 時不變、舊名列表沿用、都沒有時新建「會議助手」、更新說明選段落）。
- DEBUG 版 `shiyinctl windowshot` 拍繁中、英文、簡體（4.7.6 沒有簡體翻譯，系統退回英文，跟 4.7.6 一樣）的主畫面、錄音畫面，`snapshot … guide` 拍使用說明；`state` 的主視窗標題是「會議助手」／Meeting Assistant。

## F10. 定期備份資料庫（F10，DF9）

需求在 requirements F10。程式在 `Sources/Shiyin/Fork/Backup/`：`DatabaseBackup.swift`（`ForkBackup`：排程、備份、清理、狀態）、`BackupViews.swift`（「MA」選單的兩項、設定的一段）、`BackupDebug.swift`（`mabackup`）。

### F10.1 備份方式：sqlite3_backup（來源用 GRDB 的讀取交易）

- `ForkBackup.write`（背景）：來源照 GRDB 7 `DatabaseReader.backup` 的做法，在 `pool.read { db in … }` 的讀取交易裡，用 `db.sqliteConnection` 跑 `sqlite3_backup_init／step(-1)／finish`，一次複製全部頁面，拿到的是開始那一刻的快照；WAL 模式下讀不擋寫，錄音、轉錄照常寫入。**目的地不交給 GRDB 用路徑開**（GRDB 沒有 `SQLITE_OPEN_NOFOLLOW`，SQLite 會跟著符號連結把連結指到的檔覆寫掉，REVIEW-F10b P2-3），改用下面 §F10.1a 的步驟自己開。
- 不採用 `VACUUM INTO`：它不能在交易裡跑，GRDB 的 `read` 一律包交易，要另外開一條不經 GRDB 交易的連線才行；它會重排整個檔案（多花 CPU、暫存空間），一致性的保證跟 backup 一樣，沒有多的好處。
- 不採用直接複製檔案（上游 N3 的做法）：N3 先 `checkpoint(.truncate)` 再複製，那時 app 還沒開始用資料庫；開著時複製可能拿到寫到一半的 WAL。
- 寫完的備份是不帶 `-wal`、`-shm` 的單一檔（rollback 模式），驗證 `integrity_check` 剛好是 `ok` 才改成正式檔名；還原時直接複製一個檔就好。步驟見 §F10.1a。
- 正式檔名已經有任何東西（同一秒內做了兩次、或使用者放的連結）時算失敗，不覆蓋。

### F10.1a 寫入目的地的安全規則（REVIEW-F10b P2-3）

清理的保護（§F10.3：不刪連結、資料夾）跟寫入目的地的保護分開：不刪的東西也一定不能寫進去。依序：

1. `backups/daily` 用 `lstat` 確認是真的資料夾（不是連結），再 `open(O_DIRECTORY | O_NOFOLLOW)` 拿到資料夾的 fd，之後的建立、刪除、改名都用這個 fd 的 `openat`／`unlinkat`／`renameatx_np`。
2. 先刪掉這次檔名（`ma-daily-<時間>.partial` 和 `-wal`、`-shm`、`-journal`）上以前留下的一般檔（§F10.3 的殘檔規則）；刪完四個名字只要還有任何東西（連結、斷掉的連結、資料夾、其他類型）就**失敗**：原物件不刪、不寫，log 和 `maBackupLastError` 記「暫存檔的位置已經有別的東西」。
3. `openat(dirfd, <partial>, O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW, 0600)` 新建這次的暫存檔：名字已經有東西（含連結）就失敗，不會跟著連結；`fstat` 記下 dev／inode，這個 fd 開到最後。
4. SQLite 用 `sqlite3_open_v2(<partial>, SQLITE_OPEN_READWRITE | SQLITE_OPEN_NOFOLLOW)` 開（沒有 `CREATE`：檔一定要是剛剛建的那個），開完 `lstat` 這個路徑，要是一般檔而且 dev／inode 跟第 3 步相同，不然失敗（處理「建好到開啟之間被換掉」）。
5. 目的地連線先 `PRAGMA journal_mode=OFF`：寫入時不建 `-journal`；備份頁面直接寫進檔案，不會建 `-wal`、`-shm`。複製完馬上關掉連線（不再下任何指令：檔頭這時是來源的 WAL 標記，再用會讓 SQLite 開 WAL 旁檔）。
6. 用第 3 步的 fd 把檔頭第 18、19 位元組（file format write／read version）從 2（WAL）改成 1（rollback journal），`fsync`：效果跟 `journal_mode=DELETE` 一樣，但不用經過 SQLite 開 WAL。
7. 驗證：確認三個旁檔的名字都沒有東西後，`sqlite3_open_v2(<partial>, SQLITE_OPEN_READONLY | SQLITE_OPEN_NOFOLLOW)`，`PRAGMA integrity_check` 要剛好是 `ok`、`PRAGMA journal_mode` 要是 `delete`；關掉後再核對一次 inode。唯讀、rollback 模式不會建旁檔。
8. 改名：`renameatx_np(dirfd, <partial>, dirfd, <正式檔名>, RENAME_EXCL)`：正式檔名有任何東西（含斷掉的連結）就失敗，不覆蓋；改名前核對 `<partial>` 還是同一個一般檔。
8a. 改名成功後把 `daily` 寫進磁碟（BK2a）：對第 1 步的 `dirfd` 先做 `fcntl(F_FULLFSYNC)`；這個檔案系統不支援（回錯誤）時退回 `fsync(dirfd)`。
   - 為什麼用 `F_FULLFSYNC`：macOS 的 `fsync` 只把資料交給硬碟，不要求硬碟清掉自己的寫入快取，硬碟快取裡的東西斷電時還是會掉；`F_FULLFSYNC` 會要求硬碟清快取。APFS 上對資料夾的 fd 可以用（本機量約 5～10 ms，每天一次）。儲存裝置照實清掉快取時，第 6 步已經 `fsync` 交給硬碟的檔案內容也一起寫進去。
   - 退回 `fsync` 是為了不支援 `F_FULLFSYNC` 的檔案系統（例如部分網路磁碟、外接的非 APFS 格式）：照樣把改名交給硬碟，只是不保證硬碟快取。log 記一行 notice。照樣算成功，**仍照 7 份的規則清理**（見下面清理那一點）。
   - 兩個都失敗：**不算備份失敗**。備份檔已經用正式檔名完整存在（內容驗證過、改名成功），之後讀得到、還原得了；這時回報失敗會讓設定記下錯誤、開始算 7 天，但資料夾裡明明有這份備份，下一次檢查也會因為它是最新的而不重做，錯誤說明就跟事實不符。所以只在 log 記一行 warning（`backup dir sync failed: …`），照樣當成功，**仍照 7 份的規則清理**。
   - 清理（§F10.3）在這一步之後才刪舊備份。**只有 `F_FULLFSYNC` 成功、而且儲存裝置照實執行同步時**，這個順序才在清理之前建立了新備份的持久化屏障，斷電後不會出現「舊的刪了、新的還沒寫進去」。退回 `fsync` 或兩個都失敗時沒有這個屏障：斷電時儲存裝置可能已經寫進了清理的刪除、卻還沒寫進新備份的改名。
9. 失敗時只刪「還是同一個 inode 的一般檔」的暫存檔；旁檔照 §F10.3 只刪一般檔。成功、失敗都關掉 fd。

**安全前提（能防什麼、不保證什麼）**：
- 能防：開始備份前就已經在 `backups/daily` 裡的東西——這次檔名上的符號連結（含斷掉的）、資料夾、`-wal`／`-shm`／`-journal` 的連結、正式檔名上的連結，以及 `daily` 本身是連結。遇到這些一律不寫、不刪、回報失敗。
- 不保證：跟會議助手同一個使用者權限、正在主動搶時間的程式，在 open、核對、rename 之間的極短空檔改掉資料夾的內容（例如把 `daily` 或暫存檔換掉）。inode 核對、`O_NOFOLLOW`、`RENAME_EXCL` 縮小了這個空檔，但沒有把它變成零；同權限的程式本來就能直接改使用者的資料，這不在這個功能的防護範圍內。
- inode 核對的意義：這次建的暫存檔的 fd 一直開著，同一個檔案系統上 dev＋inode 相同就是同一個檔（開著的檔的 inode 不會被別的檔重用），所以「剛好撞到另一個同 inode 的檔」不是一般會發生的風險；核對真正防的是路徑被換成別的檔或連結。剩下的風險是上一點的主動競態，不是 inode 碰撞。
- 斷電時保證到哪裡：
  - 第 8a 步的 `F_FULLFSYNC` 成功、而且硬碟照實執行清快取時，備份完成（log 記 `backup done`）後斷電，這份備份會用正式檔名、完整的內容留下來。
  - 第 8a 步之前（複製、驗證、改名途中）斷電：剛做的這份可能不見，或還是暫存檔名（下一次成功時當殘檔清掉）；這次還沒清理，不會因為這次少掉舊的備份。
  - 退回 `fsync` 或兩個都失敗時，只保證到改名交給了作業系統（或硬碟）。這時照樣算成功、仍照 7 份的規則清理：斷電後**不保證新備份一定還在，也不保證因為保留規則刪掉的最舊一份還在**（最壞是新的和被刪的都沒有；保留規則沒刪的舊備份不受這次影響）。
  - 不宣稱能防硬碟或檔案系統本身不照規矩清快取。
- 整個過程在背景執行（`Task.detached`），主執行緒只更新狀態。同一時間只有一個備份（`running`）。

### F10.2 排程（`ForkBackup.install`，由 `ForkStartup.install` 呼叫）

- 啟動後 120 秒第一次檢查，之後每 3600 秒（`Timer`，`.common` mode）。`Shiyin --mcp` 在 `main.swift` 就分流、不建 `AppModel`，不會走到這裡；`shiyinctl` 是另一支程式。
- 每次檢查（`check(reason:)`）依序判斷，第一個不符合的就記成這次的結果（`lastCheck`，DEBUG 的 `state` 看得到），不往下做：
  1. 設定 `maBackupEnabled` 關掉 → `disabled`；
  2. 正在備份 → `running`；
  3. 錄音中（`model.recorder.isRecording`，暫停也算）→ `deferredRecording`；下一次檢查（最多 1 小時後）再判斷；
  4. 最新一份的時間（§F10.3）距離現在不到 24 小時 → `notDue`；
  5. 可用空間不夠（§F10.4）→ `lowDisk`；
  6. 開始備份。
- 「立即備份」、`mabackup now` 跳過第 1、4 項（照樣看 2、3、5）。

### F10.3 檔名、上一次成功、清理

- 資料夾 `Paths.backupsDir/daily`（`SHIYIN_HOME/backups/daily/`），第一次備份時建立。檔名用本地時間 `yyyyMMdd-HHmmss`（`en_US_POSIX`、公曆）。
- **上一次成功的時間看資料夾裡最新的那份**（檔名的時間，照名稱排序），不存在設定裡（DF9）。
- **哪些算備份**（`ForkBackup.backups()`，份數、上一次成功、清理、`age` 共用）：`backups/daily/` 這一層（不遞迴）裡同時符合：
  1. `lstat` 的類型是一般檔案（`FileManager.attributesOfItem` 的 `.type == .typeRegular`，不跟著連結走）：資料夾、符號連結、其他類型一律排除；
  2. 檔名完全是 `ma-daily-` + 15 個字（8 位數字、`-`、6 位數字）+ `.sqlite`；
  3. 時間合法：用同一個格式（`en_US_POSIX`、公曆、目前時區）解析得到日期，而且再格式化回去跟原字串相同（擋掉 `20261399-000000` 這種會被寬鬆解析的值）。
- **哪些算暫存殘檔**（`stalePartials()`）：同樣只看一般檔案，檔名完全是 `ma-daily-<合法時間>.partial`，或再加上 `-wal`、`-shm`、`-journal` 之一（SQLite 在暫存檔旁開的檔）。`ma-daily-my.partial-notes.txt`、名稱符合的資料夾都不算。
- 清理分兩步，都只刪上面兩種：
  - `pruneBackups()`：照名稱排序留最新 7 份，其餘的在刪之前再 `lstat` 一次，確定還是一般檔案才 `removeItem`。
  - `removeStalePartials()`：刪暫存殘檔，同樣刪之前再確認類型。
- 什麼時候清：成功路徑在 `running` 還是 true 時（暫存檔已改名、兩個連線都已關掉）依序呼叫 `pruneBackups()`、`removeStalePartials()`：同一個 app 裡不會有別的備份正在寫暫存檔，不用為了清理先放開互斥。app 在背景備份途中結束時留下的暫存檔，下一次成功備份就會清掉。前提跟上游一樣：同一個 `SHIYIN_HOME` 同時只有一個 app 在用。`mabackup prune` 只在沒在備份時才清暫存檔。
- 這次的暫存檔：失敗時只刪 inode 跟這次建的相同的一般檔（§F10.1a 第 9 步）；這次檔名上的連結、資料夾不刪、不寫（第 2 步）。
- `backups/` 本身（migration 前的 `shiyin-*-before-*.sqlite`）、其他名字的檔、子資料夾和裡面的東西、符號連結和它指到的檔都不碰。

### F10.4 磁碟空間

- 資料庫大小 = `shiyin.sqlite` + `shiyin.sqlite-wal` 的大小。可用空間用 `SHIYIN_HOME` 的 `volumeAvailableCapacityForImportantUsageKey`（讀不到時用 `volumeAvailableCapacityKey`）。少於「大小 × 2 + 1 GB」就跳過，log 寫大小和可用空間。
- DEBUG：`mabackup simulate lowdisk` 讓這一項一律判斷成不夠。

### F10.5 失敗、狀態、設定鍵

- 失敗時：`maBackupLastError` 寫原因（錯誤的種類、SQLite 的錯誤碼或 `integrity_check` 的第一行，不含會議內容），`maBackupFailingSince` 沒有值時寫現在的時間；log（`com.weiwei.shiyin`、category `backup`）寫原因、大小。成功時兩個鍵都刪掉。空間不夠也算失敗（原因寫空間）；錄音中延後、還沒到 24 小時、關掉不算。
- 設定顯示的提示：有 `maBackupLastError`，而且（最新一份的時間，沒有時用 `maBackupFailingSince`）距離現在超過 7 天，顯示「上次成功備份是 N 天前：<原因>」（沒成功過時「還沒有成功備份過：<原因>」）。不送通知。
- 設定鍵：`maBackupEnabled`（`bool`，沒有值時當成 true）、`maBackupLastError`（字串）、`maBackupFailingSince`（日期）。都跟著 bundle id 的設定網域；測試版用測試 bundle id，正式網域不動。
- DEBUG：`mabackup simulate fail` 讓下一次備份在寫完暫存檔之後失敗（看得到 `.partial` 被清掉、原因寫進 log 和設定）；`mabackup age <天數>` 把資料夾裡每份備份的檔名時間往前移（只在 DEBUG，改檔名、不改內容），`maBackupFailingSince` 也往前移，用來看 24 小時的判斷和 7 天的提示。

### F10.6 介面與共用入口

- `ForkStartup.install(model)`（`Fork/ForkStartup.swift`，F0）：依序呼叫 `ForkMute.install(model)`、`ForkBackup.install(model)`。AppModel 原本的 `ForkMute.install(self)   // MA-FORK(F3)` 換成 `ForkStartup.install(self)   // MA-FORK(F0)`，位置不變（F3 的安裝照舊在同一個時間點）。以後的 fork 功能要在啟動時安裝，加在這裡、不再加接點。
- `ForkAppMenuCommands(model:)`（同一個檔，F0）：`BrandAboutCommand()`（F7，取代 `.appInfo`）＋ `ForkBackupMenuCommands(model:)`（`CommandGroup(before: .systemServices)`：「立即備份資料庫」、「打開備份資料夾」、分隔線；不用 `before: .appSettings`：上游用 `replacing: .appSettings` 換掉設定那一組，放在它前面的項目實測不會出現）。ShiyinApp 的 `BrandAboutCommand()   // MA-FORK(F7)` 換成 `ForkAppMenuCommands(model: model)   // MA-FORK(F0)`。「MA」選單的順序：關於 MA、檢查更新…、設定⋯、立即備份資料庫、打開備份資料夾、服務…。
- 「立即備份資料庫」：錄音中、正在備份時 `.disabled`。做完設 `model.noticeMessage`（主視窗下方的短暫提示，3 秒）：「資料庫已備份」或「備份失敗：<原因>」。主視窗沒開時看不到這一句，結果在設定的「資料庫備份」也看得到。
- 「打開備份資料夾」：資料夾不存在時先建立，`NSWorkspace.shared.open`。
- 設定「一般」頁（`AdvancedSettings(part: .general)`，在「重新顯示首次使用引導、重建搜尋索引」那段後面）加一行 `ForkBackupSettingsSection()   // MA-FORK(F10)`：`Section("資料庫備份")`：開關「每天自動備份資料庫」（`@AppStorage("maBackupEnabled")`，預設 true）、「上次備份」（時間，或「還沒有備份」）、說明「保留最近 7 份，放在資料夾的 backups/daily。錄音中不備份。」和「打開備份資料夾」按鈕；§F10.5 的提示用紅字。
- 介面文字照 §F0.1 第 7 點：寫中文、照上游寫「拾音」，`l10n.py check` 後用 `apply` 寫英文。

### F10.7 DEBUG（`mabackup`，`BackupDebug.swift`）

- `mabackup now [<輸出.json>]`：等於「立即備份」，等做完；輸出 `ok`、`file`、`reason`（`deferredRecording`、`lowDisk`、`failed`…）。
- `mabackup check [<輸出.json>]`：馬上做一次排程的檢查（不用等 1 小時），等做完，輸出這次的結果。
- `mabackup status <輸出.json>`：`enabled`、`running`、`lastCheck`、`backups`（檔名）、`lastSuccess`、`lastError`、`failingSince`、`warning`（設定會顯示的那一行）、`menuEnabled`（「立即備份」能不能按）、`dirSync`（這個 app 上一次成功備份第 8a 步的結果：`full`、`fsync`、`failed`；還沒備份過是 null）。
- `mabackup prune`：只做清理。
- `mabackup simulate lowdisk|fail|off`、`mabackup age <天數>`：見 §F10.4、§F10.5。
- `mabackup simulate dirsync nofull|fail`：下一次備份的第 8a 步，`nofull` 當成 `F_FULLFSYNC` 不支援（ENOTSUP）、真的做 `fsync`；`fail` 兩個都當成失敗（EIO）、不呼叫。用來看退回和失敗的路徑：備份照樣 `done`、log 有 notice／warning、`status` 的 `dirSync` 是 `fsync`／`failed`。`simulate off` 也清掉這一項。
- `mabackup simulate slow <秒數>`：下一次備份在複製完、驗證前多等這麼久（背景執行緒），用來讓排程的檢查和「立即備份」真的重疊。
- `mabackup schedule off|on`：停掉、重新開始排程的 Timer（自動化測試時，避免啟動後 2 分鐘的那次檢查插進來；`on` 從現在起算 2 分鐘）。
- `mabackup menu <輸出.json>`：倒出「MA」選單每一項的標題、能不能按（沒有輔助使用權限也看得到選單）。
- `state` 的 `backup`：同 `status` 的主要欄位。

### F10.8 驗證

- 用測試 bundle id 的 DEBUG 版複本（`check-lib.sh` 的 `isolate_debug_app`）和暫存的 `SHIYIN_HOME`，`seedfixtures` 放示範會議：`mabackup now` → `sqlite3` 看 `integrity_check`、`meetings`、`segments` 的筆數跟原本相同；錄音中不備份，所以「寫入中」用別的程式對測試資料庫連續寫入（每筆交易成對寫兩列）時同時 `mabackup now`，每份 `integrity_check` ok、成對的列數是偶數（一致的快照）。
- 錄音中 `mabackup now`／`check` 回報 `deferredRecording`、`menu` 的「立即備份資料庫」不能按；停止後 `check` 做了備份。
- 放一個 `backups/shiyin-…-before-….sqlite`，做 8 份（每份之間 `age` 往前移），最舊的被刪、migration 前的還在。
- `simulate lowdisk`、`simulate fail`、`age 8` 看 `status`、log、設定的提示（`preview settings general`、`windowshot`）。
- 還原：照 requirements F10.8 的步驟（測試的 `SHIYIN_HOME`），重開後會議都在。
- 測完 `defaults read` 正式網域前後比對：完全相同。
- 自動化：`scripts/fork/f10-backup-check.py <SHIYIN_HOME> <shiyinctl> --out <資料夾>`（`check.sh` 的 #14）對開著的 DEBUG 版跑，先 `schedule off`，最後 `schedule on`：
  - 清理的反例（REVIEW-F10 P2-1、P2-2、P3-1）：放 7 份舊的一般檔備份，另外放名稱符合的資料夾（裡面有檔）、名稱符合但時間在 2099 年的符號連結和它指到的檔、時間不合法的檔、`ma-daily-notes.txt`、`ma-daily-my.partial-notes.txt`、名稱符合的 `.partial` 資料夾、migration 前的備份，和合法的舊暫存檔（`.partial` 加三個旁檔）。`mabackup now` 一次：一般檔的備份剩 7 份、最舊的被刪，舊暫存檔四個都清掉，其他全部原樣（資料夾裡的檔內容不變、連結還在、指到的檔還在），`lastSuccess` 是剛做的那份（不是 2099 年的連結），新的備份 `integrity_check` ok、會議數相同。
  - 重疊：`simulate slow 6` 後 `now`，第一份還在寫時送 `check`（已 `age` 成到期）和 `now`，兩個都回 `running`；第一份 `done`，資料夾只多一份、沒有殘檔。
  - 錄完後到期的檢查：`age` 成到期、`record-sim` 中 `check` 回 `deferredRecording`，`record stop` 後 `check` 回 `done`、多一份。
  - 寫入目的地（REVIEW-F10b P2-3）：在接下來幾秒會用到的每個時間名稱上放同一種東西，每種各跑一次 `mabackup now`：`.partial` 連結到測試資料夾裡含 sentinel 的 SQLite、斷掉的 `.partial` 連結、`.partial` 資料夾、`-wal`／`-shm`／`-journal` 連結到測試資料夾裡的 sentinel 檔、正式檔名是連結。每次都要回 `failed`（不是 `done`）、連結本身和目標的內容（sha256、sentinel 表）不變、資料夾和裡面的檔還在、正常備份照留。
  - 改名後寫進磁碟（BK2a，§F10.1a 第 8a 步）：一般的 `now` 之後 `status` 的 `dirSync` 是 `full`（APFS）；`simulate dirsync nofull` 後 `now` 回 `done`、`dirSync` 是 `fsync`；`simulate dirsync fail` 後 `now` 照樣回 `done`、`dirSync` 是 `failed`、`lastError` 是空的、多一份 `integrity_check` ok 的備份、沒有殘檔。真的斷電、硬碟快取有沒有清，自動化測不到，只能照 §F10.1a 的說明。
  - 最後份數還是 7，反例的東西都還在。

## F11. 錄音島放在哪個螢幕（F11，DF11）

需求在 requirements F11。程式在 `Sources/Shiyin/Fork/Island/`：`ForkIsland.swift`（選螢幕、記下主視窗的螢幕、設定鍵、DEBUG 的模擬）、`IslandScreenViews.swift`（設定的「錄音島放在」）、`IslandDebug.swift`（`maisland`）。

### F11.1 接點：`ForkIsland.screen()`

- 上游 `RecordingIsland.place(animated:)` 的 `guard let panel, let screen = NSScreen.main ?? NSScreen.screens.first else { return }` 改成 `… let screen = ForkIsland.screen() ?? NSScreen.main ?? NSScreen.screens.first …   // MA-FORK(F11)`。改既有的一行，算 1 行接點（96 → 97）。
- `ForkIsland.screen()` 回傳 nil 時就是上游原樣。`place` 後面的算法（`IslandNotch(screen:)` 的瀏海、位置、要不要 `setFrame`、動畫）不變，用的是選到的螢幕，所以瀏海的樣子自動跟著選到的螢幕。
- 上游呼叫 `place` 的時機都不變：每 0.5 秒（要顯示時）、換 app、換桌面、螢幕設定變了、內容大小變了。選螢幕只看 `NSScreen.screens`（2～3 個）、`CGDisplayIsBuiltin`、主視窗，很便宜。
- 偵測會議的提醒（R81.3）也是島顯示的，走同一個 `place`，所以一起固定（F11.5）。島關掉時才出現的 `MeetingDetector` 浮動視窗不經過這裡，照上游。

### F11.2 選螢幕（`ForkIsland.pick()`）

- 設定 `maIslandScreen`（`UserDefaults.standard` 的字串）：`follow`、`builtin`、`mainWindow`；沒有值、不認得時是 `builtin`（預設）。
- `follow`：回傳 nil（上游）。
- `builtin`：`NSScreen.screens` 裡第一個 `CGDisplayIsBuiltin(<NSScreenNumber>) != 0` 的螢幕；沒有時改用 `mainWindow` 的結果；再沒有回傳 nil。
- `mainWindow`：
  1. 主視窗（`identifier == "main"`）看得到、沒有縮到 Dock 時，它的 `window.screen`（視窗跟哪個螢幕重疊最多）；同時記下這個螢幕的 display ID。
  2. 否則用最後一次記下的 display ID，在現在的 `NSScreen.screens` 裡找；找不到（拔掉了）就算沒有。
  3. 都沒有：回傳 nil（上游）。
- 記下主視窗的螢幕：`ForkIsland.install`（由 `ForkStartup.install` 呼叫）監聽 `NSWindow` 的 `didMove`、`didChangeScreen`、`didBecomeKey`、`willClose`、`willMiniaturize`，視窗是主視窗時記下它的螢幕；`pick()` 看到主視窗時也記。只記在記憶體（重開 app 後主視窗一開就會再記）。
- 結果帶理由（DEBUG 用）：`follow`、`builtin`、`mainWindow`、`mainWindowRemembered`、`upstream`（退到上游）。

### F11.3 設定列（`ForkIslandScreenRow`）

- 放進 F0 的共用列 `ForkRecordingSettingsRows`（§F0.7），在 F3 的 ⌃⌥⌘M 開關前面，不加接點。
- `Picker("錄音島放在", selection:)`，`@AppStorage("maIslandScreen")`（預設 `builtin`）：「跟著目前在用的螢幕」（`follow`）、「內建螢幕」（`builtin`）、「主視窗所在的螢幕」（`mainWindow`）。下面一行說明：「選內建螢幕時，筆電闔上或沒有內建螢幕就放在主視窗所在的螢幕。偵測到線上會議的提醒也在同一個螢幕。」
- 錄音島關掉時（`@AppStorage(AppSettings.recordingIslandKey)` 是 false）`.disabled`。改了之後呼叫 `RecordingIsland.shared.place(animated: true)`，不用等下一個 0.5 秒。
- 介面文字照 §F0.1 第 7 點：寫中文，`l10n.py check` 後用 `apply` 寫英文，簡中照 `zh-Hans-overrides`。

### F11.4 DEBUG 的模擬（只在 DEBUG 版）

- 啟動參數：`-maIslandNoBuiltin YES`（當成沒有內建螢幕）、`-maIslandMainScreen <N>`（當成主視窗在 `NSScreen.screens[N]`；`-1` 當成主視窗關著）。啟動時讀一次，`maisland simulate` 可以再改。
- 模擬的主視窗也會記下螢幕，跟真的一樣；`maisland simulate remembered <N|none>` 直接設記下的螢幕。
- 不真的移動視窗、不闔上筆電：真的移動主視窗會出現在使用者的畫面上。

### F11.5 DEBUG 指令（`maisland`，`IslandDebug.swift`）

- `maisland screens <輸出.json>`：每個螢幕的 `index`、`displayID`、`frame`、`builtin`（真的）、`notch`（`IslandNotch(screen:).hasNotch`）；`main`（`NSScreen.main` 的 index）、`placement`（設定值）、`pick`（`ForkIsland.screen()` 的 index，nil 是 null）、`reason`、`expected`（`place` 最後用的螢幕：`pick ?? main ?? 0`）、`upstream`（上游會用的：`main ?? 0`）、`mainWindow`（主視窗現在所在的螢幕 index）、`remembered`、`simulate`（模擬的值）、`island`（同 `state` 的 `island`）。
- `maisland mode follow|builtin|mainWindow`：寫 `maIslandScreen`（測試版的設定網域），馬上 `place`。
- `maisland simulate nobuiltin on|off`、`maisland simulate mainscreen <N|closed|off>`、`maisland simulate remembered <N|none>`：改模擬，馬上 `place`。

### F11.6 驗證

- 用測試 bundle id 的 DEBUG 版複本和暫存的 `SHIYIN_HOME`，錄音島開著、放在桌面層（`-recordingIsland YES -debugIslandBehind YES`，不出現在使用者的畫面上），`-debugQuietPrompts YES`。
- 自動化：`scripts/fork/f11-island-check.py <SHIYIN_HOME> <shiyinctl> --out <資料夾>`（`check.sh` 的 #15）：
  - `record-sim` 開始錄音，等 `maisland screens` 輸出的 `island.visible`。
  - 每種情況 `maisland mode`／`simulate` 之後等 1 秒（大於 0.5 秒的 Timer），用 `maisland screens` 輸出的 `island` 核對：島的 `frame` 整個在 `expected` 螢幕的 `frame` 裡（水平置中在那個螢幕或瀏海的中間）；`notch` 等於那個螢幕的 `notch`。
  - 情況：`builtin`（有內建螢幕時在內建螢幕）、`follow`（`pick` 是 null、在 `upstream` 螢幕，跟上游算的一樣）、`mainWindow` 模擬主視窗在每一個螢幕、模擬主視窗關著（用記下的）、記下的清掉（退到上游）、`builtin` 加模擬沒有內建螢幕（退到主視窗的螢幕；主視窗關著又沒記下時退到上游）。
  - 只接一個螢幕的電腦：「每一個螢幕」只有一個，照樣核對退路；這台的螢幕數寫進證據。
  - 最後 `maisland simulate off`；不停止錄音（停止後的轉錄會在暫存的 `SHIYIN_HOME` 下載、編譯說話者辨識的模型，跟 F11 無關，2026-11-23 在 CoreML 編譯時當掉過一次），錄音中的 DEBUG 版由 check.sh 結束。
  - fork 還沒帶入上游 4c3a8d3（錄音島的面板存在時，DEBUG 的 `state` 會讓 app 當掉），所以一律用 `maisland screens`，不呼叫 `state`。
- 截圖：`mawindowshot <輸出> island` 拍內建螢幕（瀏海）、外接螢幕（膠囊）的樣子各一張，放進證據（需要時看）。
- 使用者在電腦前（acceptance-mac 場次 7）：真的切換操作螢幕、闔上筆電、全螢幕的會議 app。
- 測完 `defaults read` 正式網域前後比對：完全相同（check.sh #12）。

## F12. 說話者聲紋：分數顯示、改名防呆、人物頁管理單份聲紋（F12，DF12、DF13、DF14）

需求在 requirements F12。程式在 `Sources/Shiyin/Fork/Voiceprints/`：
- `VoiceScores.swift`：等級、排名、依據的文字、聲紋庫的快取。
- `VoiceGuard.swift`：防呆的判斷、待回答的佇列、三個選項。
- `VoiceSources.swift`：來源紀錄、人物頁的資料、刪單份聲紋。
- `VoiceViews.swift`：自動帶入的名字選單、防呆的提示列和視窗、人物頁的「聲音特徵」。
- `VoiceDebug.swift`：`mavoice`。

### F12.1 接點（97 → 100，另外改寫 3 行既有的）

| 上游的那一行 | 做什麼 |
|---|---|
| 新：`AppModel.renameSpeaker` 的 `guard let id = selection` 之後：`if ForkVoiceGuard.holds(self, meetingId: id, idx: idx, name: name, source: source) { return }   // MA-FORK(F12)` | 防呆（§F12.3）；不擋時記下這次取名的來源（§F12.4） |
| 新：`MeetingDetail.loadSpeakers` 最後：`ForkVoiceScores.annotate(&self, rows)   // MA-FORK(F12)` | 建議的原因改寫成依據、算自動帶入的分數（§F12.2）。`loadSpeakers` 是整場讀取和只重讀說話者共用的，一行就涵蓋 |
| 新：`PersonPage` 的「會議」那一段之後：`ForkPersonVoiceprints(personId: person.id)   // MA-FORK(F12)` | 人物頁的「聲音特徵」（§F12.5） |
| 改寫：`learnVoiceprint` 的 `ForkSpeakerTags.remembersVoice(db, meetingId:, source:)` 多傳 `idx:`（`// MA-FORK(F2)`） | 照舊判斷 F2.9；另外交給 `ForkVoiceSources.willStore`：「只改名」時回 false（不存），要存時記下來源（§F12.4） |
| 改寫：會議頁上方 `speakerChip` 的 `if detail.speakerSources[idx] == "tag" { ForkTaggedSpeakerName(…) } else if …voiceprint {` 改成 `if let chip = ForkSpeakerChip(idx:name:detail:) { chip } else if …voiceprint {`（`// MA-FORK(F2)`） | 標記帶入的照舊用 `ForkTaggedSpeakerName`；自動帶入、而且算得出依據時用 fork 的 `ForkAutoSpeakerName`（上游 `AutoSpeakerName` 的複本，選單最上面多一行依據，同 DF8 的做法）；算不出依據時回 nil，照上游 |
| 改寫：會議頁上方提示列 `if !detail.unappliedTags.isEmpty … { UnappliedTagsBanner(detail:) }` 改成 `ForkDetailBanners(detail: detail, active: !isRecording && !trashed)`（`// MA-FORK(F0)`） | fork 的共用提示列（§F0.7）：F2 沒套用的標記（條件照舊）、F12 防呆的提示列和視窗 |

- 換會議時清掉還沒回答的防呆：放進既有的 `ForkAppState.selectionChanged()`（上游那一行不變）。
- 資料庫只用 fork 自己的表（§F12.4），不改上游的表、不改上游函式的簽章。

### F12.2 分數（`ForkVoiceScores`，DF12）

- 顯示時重算，不存分數：每位說話者的 `speakers.embedding`（說話 ≥ 8 秒）跟聲紋庫裡每個人的每一份比 cosine，每人取最高（同上游 `matchVoiceprints`）。
  - 不算這位說話者自己存進去的那一份（同一個 `meeting_id`、`speaker_idx`）：手動取名的說話者跟自己的聲紋一定是 1.0，沒有意義。
- 聲紋庫：每次都重讀每一份的中繼資料（`id`、`person_id`、`meeting_id`、`speaker_idx`、`audio_source`、`created_at`），名字也每次重讀（`people` 很小）；只快取向量，以 `id` 為鍵。
  - 向量可以快取：上游只會新增、刪除聲紋，改的只有 `person_id`（合併人）、`meeting_id`（分成兩場），`embedding` 從不更新；`AUTOINCREMENT` 的 id 不會重用。
  - 中繼資料不能快取（REV-F12 P2-1）：分成兩場只改 `meeting_id`，用 count／max(id)／total(person_id) 當快取的鍵時三個值都不變，排除自己的那一份會用到舊的會議，自己跟自己算出 100%。
  - 每次讀到的 id 裡沒有快取的才讀 `embedding`；不在了的從快取拿掉。
  - 成本：中繼資料一次查詢；比對 256 維、20 位說話者，300／3000／10000 份約 1.4／14.5／48 ms（REV-F12 的量測，-O）。聲紋庫一般是幾十到幾百份；很大時會佔主執行緒，屬於已知的取捨。
- 等級（`Level`）：`≥ 0.88` 很像、`≥ 0.65` 有點像、其他不像（同上游的 `voiceprintAutoThreshold`、`voiceprintThreshold`，直接讀上游常數）；百分比是 `max(0, round(score × 100))`。
- 兩人很像：`top − second < voiceprintAutoMargin`（0.15）。

**建議的原因**（`annotate` 改 `speakerSuggestions` 的 `reason`，只改顯示，資料庫裡的不動）：
- 怎麼分聲紋的建議和 AI 猜的：`suggestion_time` 是空的、而且原因等於上游 `matchVoiceprints` 的「聲音跟之前的%@很像」**在任何一種會議語言**（`MeetingLanguage.allCases`：languages.json 的精調和一般語言，一般語言查它的 `strings`）用建議的名字寫出來的那一句，就是聲紋的；其他都算 AI 依內容猜的（時間空的 AI 建議也一樣，只要原因不是那一句）。
  - 要看所有語言（REV-F12 P2-2）：上游存的原因是當時的會議語言，使用者之後改會議語言時上游只改 `meetings.language`、不重寫原因。只比對目前的語言，聲紋建議會被誤標成「依內容猜」、分數不見。
  - 顯示一律用**目前**的會議語言重新產生（聲紋的依據），AI 猜的原因照存的原文。
- 聲紋的（會議語言，`language.format(zh:en:ja:)`）：
  - zh：`聲紋比對：Ben 80%（有點像）・第二像 Amy 70%・兩人很像，請確認・現在最像的是 Amy 96%`
  - en：`Voice match: Ben 80% (possible) · next Amy 70% · the two sound alike, please check · closest now: Amy 96%`
  - ja：`声の照合：Ben 80%（似ている）・次点 Amy 70%・二人の声が近いので確認してください・今いちばん近いのは Amy 96%`
  - 等級的字：很像／有點像／不像，`very close`／`possible`／`unlikely`，`よく似ている`／`似ている`／`似ていない`。
  - 「現在最像的是」：現在最高分的人不是建議的名字時才加。
  - 建議的名字已經不在聲紋庫（人被刪了）：只寫第一像、第二像，不寫建議名字的分數。
  - 這位說話者算不出分數（沒有向量、聲紋庫空了）：原因照上游。
- AI 猜的：前面加 `依內容猜：`（en `Guessed from what was said: `、ja `内容から推測：`），時間點照上游的 `TimeButton`。
- 「猜到 N 位說話者的名字」清單、待確認的說話者題目都讀 `speakerSuggestions`，不用改畫面。

**自動帶入的依據**（`annotate` 存進 `forkTags.voice`，`[idx: Basis]`；`MeetingDetail` 不能另外加存起來的屬性，放進既有的 fork 狀態）：
- `name_source == "voiceprint"` 的說話者：第一像、第二像（名字、分數）。
- `ForkAutoSpeakerName` 的選單最上面一行（介面語言，`String(localized:)`）：`聲紋比對：Ben 97%（很像）・第二像 Amy 61%`；兩人很像時加 `・兩人很像，請確認`；第一像不是現在的名字時加 `・現在最像的是 Amy 96%`。

### F12.3 改名防呆（`ForkVoiceGuard`，DF13）

`holds(model, meetingId:, idx:, name:, source:)` 在上游 `renameSpeaker` 一開始被呼叫，回 true 就是先擋下、等使用者回答：

1. 這位說話者有「已經回答過、要照做」的放行（§F12.3 的選項）：拿掉放行、記下來源（含「提醒過」、「不存」），回 false。
2. 記下這次取名的來源（`manual` 或 `suggestion`，§F12.4），以下任一條成立就回 false（照上游）：
   - 設定沒開「記住說話者的聲音」（`AppSettings.voiceprints`）；
   - 名字清空或是預設名稱；
   - 說話者沒有向量或說話不到 8 秒。
3. 算：
   - 取的名字的人（`people.name` 不分大小寫）既有的聲紋裡最高的分數 `target`（沒有聲紋或沒有這個人是 nil）；
   - 別人（不是取的名字的人）裡最高的 `other`。
   - 兩邊都不算這位說話者自己的那一份（上游 `learnVoiceprint` 會先刪掉它）。
4. `other ≥ 0.88` 而且（`target` 是 nil 或 `< 0.50`）：放進 `model.fork.voiceGuard` 的佇列（會議、說話者、現在的名字、取的名字、來源、別人的名字和分數、`target`），回 true。
5. 其他回 false。

- 門檻：0.88 是上游自動帶入的門檻（拾音「很有把握」的程度）；0.50 在上游 AMI 評估裡同一個人最低 0.81、不同的人最高 0.42 之間，低於它幾乎可以確定不是同一個人（design §21.4.1）。
- requirements F12 的例子（0.950／0.261）會提醒。

**一次取好幾位**：
- 上游的「全部套用」、待確認送出都是在主執行緒的迴圈裡逐位呼叫 `renameSpeaker`；擋下的進同一個佇列，沒擋的照常改。
- 迴圈結束後畫面才更新，所以使用者看到的是同一個視窗裡的全部。

**畫面**（`ForkDetailBanners` 裡的 `ForkVoiceGuardBanner`，佇列裡有這場會議的項目才出現）：
- 提示列：「有 N 位說話者的名字還沒改：聲音跟名字對不上」＋「查看」。
- 視窗（`.sheet`）在佇列從空變成有東西時自動打開。標題：一位時「確定是 Ben 嗎？」，好幾位時「這 N 位說話者的聲音跟名字對不上」。
- 每位一列：「『說話者 6』→ Ben：聲音很像 Amy（95%），跟 Ben 之前的聲音只有 26%。」；還沒有樣本時寫「Ben 還沒有聲音樣本」。
- 下面一行說明兩個存法的差別。按鈕：「取消」（Esc）、「只改名，不記住聲音」（預設）、「仍要存」。

**三個選項**（套用到佇列裡這場會議的全部）：
- 仍要存：每位設放行（`warned`），再呼叫 `model.renameSpeaker(idx, to: name, source: source)`，走上游原本的流程（改名、記聲紋、清建議、換會議紀錄）。
- 只改名：放行加「不存」，一樣呼叫 `renameSpeaker`。上游 `learnVoiceprint` 照常刪掉這位舊的那份、連到這個人；到 `remembersVoice` 時回 false，不存新的。
- 取消：清掉佇列，不呼叫任何東西：名字、建議、會議紀錄都沒動，待確認的題目還在。
- 回答時目前的會議已經不是那一場：不做（換會議時本來就清掉佇列）。
- 放行只認同一場會議、同一位說話者、同一個名字，60 秒內有效，用一次就拿掉。

### F12.4 來源紀錄（`ForkVoiceSources`，DF14）

**migration `ma_voiceprint_source_v1`**：

```sql
CREATE TABLE ma_voiceprint_source (
  voiceprint_id INTEGER PRIMARY KEY REFERENCES voiceprints(id) ON DELETE CASCADE,
  source        TEXT NOT NULL,             -- manual / suggestion / tag / merge / rediarize
  warned        INTEGER NOT NULL DEFAULT 0, -- 存的時候提醒過（仍要存）
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
```

**為什麼要兩張表**：
- 唯一的接點 `remembersVoice` 在上游 `INSERT INTO voiceprints` 之前，拿不到新聲紋的 id。
- 所以在那裡寫 `ma_voiceprint_pending`（這場、這位說話者、來源），之後再對到聲紋的 id（`resolve`）。
- 對的規則：同一場、同一位說話者、`created_at >= recorded_at`、還沒有來源紀錄的非 `enroll` 聲紋。對到的寫進 `ma_voiceprint_source`，刪掉那筆 pending。

**什麼時候對**：
- 每次 `willStore` 開始時（對前一次的）；
- `annotate` 時（改名、合併後重讀說話者，馬上就對到）；
- 人物頁讀資料前；
- app 啟動時（`ForkStartup.install`）。

**對得上的理由**：
- 上游 `learnVoiceprint` 一開始就刪掉這位說話者的舊聲紋，存新的一定經過 `remembersVoice`，而 `remembersVoice` 每次都覆寫這位的 pending。
- 所以某位說話者的聲紋如果存在，就是最近一次經過 `remembersVoice` 存的。
- 存的條件沒過（太短、跟既有的 > 0.95）時，pending 留著，沒有聲紋可對，也不會對錯：下次存一定先覆寫它。

**來源怎麼判斷**（`willStore(db, meetingId:, idx:, source:)`，依序）：
1. `holds` 記下的取名（這場、這位、60 秒內）：它的 `manual`／`suggestion`、`warned`；有「不存」就回 false（不寫 pending）。
2. F2 套用標記（`ForkSpeakerTags.applyTags` 在呼叫 `learnVoiceprint` 前記下）：`tag`。
3. 這場有正在跑的重新辨識說話者（`jobs` 的 `kind = 'rediarize' AND status = 'running'`）：`rediarize`。
4. 其他（上游 `mergeSpeaker` 合併後重新學）：`merge`。
- `enroll`（錄的「我的聲音」）不寫紀錄，看 `voiceprints.audio_source = 'enroll'`。
- 沒有紀錄的舊聲紋顯示「不明」。

**記取名的地方**：
- 記憶體裡，`LockedValue`（`holds` 在主執行緒寫，`remembersVoice` 在資料庫的寫入佇列讀）。
- 鍵是會議、說話者，60 秒內有效，用一次就拿掉。

### F12.5 人物頁的「聲音特徵」（`ForkPersonVoiceprints`）

- 放在人物頁「會議」那一段之後，同上游的 `NotesSection`。標題「聲音特徵」，後面寫幾份。
- 每份一列：
  - 日期（`created_at` 的本地日期）；
  - 來源會議的標題（按了 `model.openFromPersonPage(meetingId)`）；`meeting_id` 是 NULL 時寫「會議已刪除」，`enroll` 寫「我的聲音」；
  - 怎麼來的、「存的時候提醒過」；
  - 跟這個人其他樣本最像的百分比，或「只有這一份」。
- 可疑（§F12.3 同一組門檻：自己其他樣本最高 < 0.50 或只有這一份，而且別人 ≥ 0.88）：整列用警告色，加一行「跟這個人其他樣本不像，跟 Amy 很像（95%）」。
- 其他要確認的（F12.11a，`ForkVoiceSources.PrintRow.flags`，人物頁讀資料時算，不存）：門檻是 fork 的常數 `ForkVoiceSources.unlikeThreshold = 0.50`、`agreeThreshold = 0.65`。
  - A `unlikeOthers`：`ownBest < 0.50`，而且這個人**其他**樣本裡至少 2 份各自跟另一份其他樣本 ≥ 0.65（「互相一致」）。
  - B `pairUnlike`：這個人剛好 2 份、互相 < 0.50，兩份都標。
  - C `staleSpeaker`：`meeting_id` 不是 NULL、`speaker_idx` 不是 NULL，那一場那位說話者還在而且有 `embedding`，跟它的相似度 < 0.50。上游重新轉錄會重新分群、編號，但不刪這場舊的聲紋（AN-vpclean 從資料推得，另案），所以舊聲紋可能跟現在同編號的說話者對不上。
  - 錄的「我的聲音」（`enroll`）不比 A、B 以外的；C 不比（沒有來源說話者）。
  - 只比有效的向量（REV-F12b P3-1）：非空、維度相同、數值有限、長度不是 0。無效的比較直接略過，不當成「不像」（例如 `speakers.embedding` 是空的 BLOB、維度不符、全是 0）；A 的一致群、B 的「只有 2 份」只算跟這份「可以比」的聲紋（有效而且同維度，REV-F12c P3-1）。不另外顯示「無法比對」。
  - 畫面：每條一行橘色的說明（同 F12.11 的樣式），任何一條成立整列用警告色。
- 刪除：「刪除這份…」→ 確認（「刪除這份聲音特徵？」「會議裡的名字不會變；之後的會議不再用這份比對。」）→ `DELETE FROM voiceprints WHERE id = ?`。
  - 來源紀錄由外鍵一起刪。不呼叫 `deleteOrphanPeople`：這個人留在人物頁（還連著會議裡的說話者）。
  - 刪完 `model.reloadPeopleOverview()`、重讀目前會議的說話者。
  - `enroll` 那一列不給刪，寫「在設定的『我的聲音』管理」。

### F12.6 §F-DB

| 上游 | 對 fork 表的影響 |
|---|---|
| 刪聲紋（取名前、不是他、合併說話者、重新辨識、刪人、刪我的聲音、超過 30 份） | `ma_voiceprint_source` 的外鍵 `ON DELETE CASCADE` 一起刪 |
| 合併人（`renamePerson` 改 `person_id`）、分成兩場（`splitMeeting` 改 `meeting_id`） | 聲紋的 id 不變，來源跟著 |
| 移到垃圾桶、永久刪除會議 | 上游把 `voiceprints.meeting_id` 設成 NULL、聲紋留著，來源也留著（人物頁寫「會議已刪除」）；`ma_voiceprint_pending` 跟著會議刪（CASCADE） |
| 編輯會議（R107）、合併兩場 | 上游不動 `voiceprints`（2026-11-24 grep 確認）；pending 留在原本那場，下次存聲紋時覆寫 |
| `.shiyin` 封包 | 上游不帶聲紋，fork 也不帶來源 |

### F12.7 DEBUG（`mavoice`，`VoiceDebug.swift`）

- `mavoice setvoice <會議> <說話者> <秒數> <向量.json>`：
  - 設這位說話者的 `embedding`、`speech_seconds`；
  - 名字回預設、`name_source = default`、`person_id = NULL`、清建議；
  - 刪這位說話者的聲紋。
  - 只有測試用：合成的向量讓相似度可以算準。
- 觸發上游的流程：
  - `mavoice match <會議>`：上游 `matchVoiceprints`。
  - `mavoice suggest <會議> <說話者> <名字> <時間> <原因>`：上游 `saveSpeakerSuggestions`（AI 猜的建議）。
  - `mavoice rename <會議> <說話者> <名字>`：選這場、上游 `model.renameSpeaker`（經過防呆）。
  - `mavoice apply <會議> <說話者>`、`mavoice applyall <會議>`：套用建議、全部套用。
- 防呆：
  - `mavoice choose keep|nameonly|cancel`：等於按防呆視窗的按鈕。
  - `mavoice check <會議> <說話者> <名字> <輸出.json>`：只算防呆，不改任何東西。
- 輸出：
  - `mavoice state <輸出.json>`：目前會議每位說話者的名字、來源、`person_id`、顯示的建議（名字、原因、時間）、自動帶入的依據，和防呆的佇列、視窗開著沒有。
  - `mavoice prints <person id> <輸出.json>`：人物頁的資料。
- 人物頁：
  - `mavoice delete <聲紋 id>`：同人物頁的刪除（不經過確認）。
  - `mavoice person <person id>`：切到人物頁、選這個人（截圖用）。

### F12.8 驗證

- 用測試 bundle id 的 DEBUG 版複本和暫存的 `SHIYIN_HOME`，`seedfixtures` 的示範會議，合成的 256 維向量（正交的基底，相似度照設計好的值）。不用使用者的真實資料。
- 自動化：`scripts/fork/f12-voiceprint-check.py <SHIYIN_HOME> <shiyinctl> --out <資料夾>`（`check.sh` 的 #16）。
  - 分數：建議、自動帶入、AI 猜的顯示文字和數字跟 Python 算的一樣；「兩人很像」「現在最像的是」會出現。
  - 防呆：
    - 0.95／0.26 會擋、`check` 的數字對；
    - 取消後名字、建議、聲紋都沒變；
    - 只改名：名字改了、連到人、沒有這位的聲紋；
    - 仍要存：有聲紋、來源 `manual`、`warned = 1`；
    - 沒有樣本的新名字會擋；不需要提醒的不擋；
    - 全部套用時只有該擋的進佇列（一個視窗），選一次全部套用。
  - 來源：`manual`、`suggestion`、`merge`；沒有紀錄的顯示「不明」。
  - 人物頁的資料：可疑標記、相似度；刪一份後名字、其他聲紋不變，來源紀錄沒了。
  - §F-DB：分成兩場、合併人、刪會議、刪人之後，沒有指不到聲紋的來源紀錄；`foreign_key_check` 沒有東西。
  - 截圖：`windowshot` 拍會議頁、防呆的視窗、人物頁，放進證據（看一眼）。
- 使用者在電腦前（acceptance-mac 場次 8）：真的會議上的分數、防呆的視窗、人物頁，中英文。
- 測完 `defaults read` 正式網域前後比對：完全相同（check.sh #12）。

### F12.9 重新轉錄後名字跟著聲音（F12.15，DF15）

程式在 `Fork/Voiceprints/Retranscribe.swift`（`ForkRetranscribe`）。

**接點（不新增，維持 100/100）**：
- 上游 `AppDatabase.saveTranscript` 的 `let named = Dictionary(… existing.filter { !isDefault && nameSource != "tag" } …)` 那一行（原本就是 F2 的接點，`AppDatabase.swift:695`）換成 `let named = try ForkRetranscribe.named(db, existing, voices: voices, count: speakerCount)   // MA-FORK(F12)`。
  - 回傳一樣的 `[新編號: 舊說話者]`，上游後面 `if let old = named[idx]` 照常沿用名字、`name_source`、`person_id`。
  - `db` 是 `saveTranscript` 自己那一筆寫入交易：fork 的待處理紀錄跟著這筆交易一起提交或回滾。
- 存檔後的處理放進既有的 fork 鉤子 `ForkSpeakerTags.afterTranscription`（JobRunner 轉錄存檔後、`matchVoiceprints` 之前，F2 套用標記之後）。
- 建議的顯示和清理放在既有的 `ForkVoiceScores.annotate`（`loadSpeakers` 的接點）。
- 失敗後的重試放在 `ForkStartup.install`。
- 資料表用 fork 的 migration（`ForkMigrations.register`，既有接點）。

**資料表（migration `ma_retranscribe_v1`，只新增；REV-F12c P2-1、P2-2）**：

```sql
CREATE TABLE ma_retranscribe_pending (      -- 這場重新轉錄存檔後還沒處理完的（每場最多一筆，再轉錄一次就換掉）
  meeting_id  INTEGER PRIMARY KEY REFERENCES meetings(id) ON DELETE CASCADE,
  fingerprint TEXT NOT NULL,                -- 存檔後的說話者指紋（各編號＋聲紋的 SHA-256）
  payload     TEXT NOT NULL,                -- 跟著聲音沿用的編號、對不上的舊名字（JSON）
  created_at  TEXT NOT NULL
);
CREATE TABLE ma_retranscribe_suggestion (   -- 對不上的舊名字建議，等使用者套用或略過
  meeting_id  INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  speaker_idx INTEGER NOT NULL,
  name        TEXT NOT NULL,
  fingerprint TEXT NOT NULL,                -- 建立時的說話者指紋
  created_at  TEXT NOT NULL,
  PRIMARY KEY (meeting_id, speaker_idx)
);
```

**說話者指紋與聲音雜湊**：
- 整場指紋：這場所有說話者照編號排，「編號:聲紋的 base64（沒有就 -）」接起來的 SHA-256。
- 聲音雜湊：一位說話者的聲紋的 SHA-256（`voiceHash`）。
- 改名、套用建議都不會變；重新轉錄、重新辨識說話者、合併說話者會變。
- **編輯會議不一定會變**（REV2-F12c P2-2，修正前一版的錯誤前提）：
  - 裁切只更新留下的說話者的秒數；
  - 分割照原樣複製說話者；
  - 兩邊說話者相同時，整場指紋完全一樣。
  - 所以兩張表在編輯會議時另外處理（見「編輯會議」），不靠指紋會變。
- pending 用整場指紋確認「存檔後還沒有別的流程換過說話者」，每一項另外核對（見 `after`）。
- 建議用那位說話者自己的聲音雜湊確認「還是同一個人」。

**對應（`named`）**：
1. 要沿用的舊說話者：名字不是預設名稱、不是 F2 的標記（同原本那一行的條件）。
2. 可以比的：舊說話者有有效的聲紋、說話 ≥ 8 秒；新說話者 `voices` 裡有效、≥ 8 秒（有效同 §F12.5：非空、維度相同、有限、不是 0）。
3. 有聲紋的舊說話者：
   - 找最像的新說話者 n；
   - 再看 n 最像的舊說話者（所有有聲紋的舊說話者，包括預設名稱的）是不是它；
   - 雙向最像而且 ≥ `voiceThreshold`（0.80）→ 名字跟到 n；
   - 否則算「對不上」。
4. 沒有聲紋可比的舊說話者（舊的或新的沒有有效聲紋，例如說話 < 8 秒、匯入的逐字稿、`voices` 是空的）：照編號沿用（上游）。那個編號已經被聲音對應用掉時不沿用。
5. 有舊說話者（重新轉錄）時，在同一筆交易：
   - 寫 `ma_retranscribe_pending`：照 `voices`、`count` 算出存檔後的指紋，加上這次的結果。每個沿用項目記下存檔後預期的名字、來源、`person_id`、聲音雜湊（REV2-F12c P2-1）。
   - 刪掉這場舊的 `ma_retranscribe_suggestion`（舊編號已經不算數）。
   - `saveTranscript` 後面任何一步失敗回滾，這些也一起回滾（不會留下記憶體裡的結果）。
   - 沒有舊說話者時（匯入封包、匯入逐字稿、GoldenDump、第一次轉錄）不寫，行為跟上游一樣。

**存檔後（`after`）**：
- 讀這場的 `ma_retranscribe_pending`；沒有，或指紋跟現在的說話者不合，就刪掉紀錄、不做任何事。
  - 重新辨識說話者也會呼叫 `afterTranscription`：它不寫 pending，而且會改掉說話者的聲紋，所以就算之前留下沒處理完的紀錄，指紋也不合。
- 步驟（各自一筆交易，不巢狀包在另一個 `pool.write` 裡；pending 到最後才消耗）：
  1. 刪舊聲紋：這場每份 `voiceprints` 跟同編號的新說話者比，有效而且 < 0.50 就刪（來源紀錄由外鍵一起刪）。
     - 要先刪：上游 `learnVoiceprint` 跟同一人既有的某份 > 0.95 就不存，舊編號那份還在時，會擋掉同一個聲音在新編號的學習。
  2. 重新學：跟著聲音沿用的、來源是 `manual` 或 `suggestion` 的，用新聲音 `learnVoiceprint`（同 rediarize 的 `JobRunner.swift:542`；設定關掉記住聲音時不學）。
     - 學之前記下來源 `retranscribe`（`ForkVoiceSources.noteNaming`），連同預期的名字、聲音雜湊。
     - 每一筆都可以重做：上游先刪這場這位說話者的聲紋再存。
     - **尊重使用者後來的決定**（REV2-F12c P2-1）：存檔後到重試之間，使用者可能已經改名、說「不是他」或「只改名」。
       - 學之前先比：現在的名字、來源、`person_id`、聲音雜湊跟預期不同，就跳過這一項。
       - 上游 `learnVoiceprint` 在自己的交易裡，連人之後、存聲紋之前會呼叫 `remembersVoice`（fork 的接點）。`ForkVoiceSources.willStore` 在這裡再比一次名字和聲音雜湊，不合就丟錯，讓這筆學習整個回滾（連人也不留）。`after` 接到這個錯誤就跳過這一項，其他錯誤照樣往上丟。
       - **使用者在 pending 期間自己取名，就讓 pending 裡這位的項目失效**（REV3-F12c P2-1）。四個欄位相同不代表使用者沒有新的決定，例如同一個名字再存一次、但選「只改名，不記住聲音」。
         - 任何不是重新轉錄自己的重新學、經過 `remembersVoice` 的取名都算：改名小視窗、套用建議、仍要存、只改名、F2 標記、合併說話者後的重新學。
         - `willStore` 在同一筆學習交易裡，先把 `ma_retranscribe_pending` 的 `payload` 裡這個編號的沿用項目拿掉（`ForkRetranscribe.supersede`），再判斷要不要存聲紋（「只改名」照樣回 false 不存）。F2 標記說話者可能併在一起而不存的路徑，也一樣先拿掉。
         - 交易回滾的話，失效也一起回滾。同批其他沒被使用者動過的項目照常重試；之後 `after`、啟動時 `retryAll` 都不會再學這一位。
  3. 一筆交易：存對不上的舊名字建議（見下），刪掉 `ma_retranscribe_pending`。
- 任何一步失敗，pending 還在，下次整個重做：
  - 第 1 步已經刪掉的是對不上的舊聲紋，本來就要刪；
  - 第 2 步重學會把沿用的名字學回來（REV-F12c P2-3：不會「刪了、學失敗、又不能重試」）。
- 失敗時往上丟。`afterTranscription` 記 log，pending 留著；下次同一場的 `after`、或下次 app 啟動再做。成功後才消耗。
  - 啟動時（`ForkStartup.install`）從最舊的開始，一次最多重試 20 場，其他的下次啟動再做，避免拖慢啟動。

**對不上的舊名字建議**：
- 給哪一位說話者：
  - 舊聲音最像的新說話者（≥ 0.65）；
  - 否則同一個編號的說話者。
  - 都要求還沒被使用者取名（`name_source` 是 `default` 或 `voiceprint`），而且不是這次已經給過的；都不行就不存。
- 存法：
  - 寫進上游的 `suggested_name`、`suggestion_reason`（會議語言的「重新轉錄前的名字：%@（聲音對不上，請確認）」）、`suggestion_time = NULL`；
  - 另外寫一筆 `ma_retranscribe_suggestion`，含那位說話者的聲音雜湊（`speaker_hash`，migration `ma_retranscribe_v2`）。
- 顯示和保護（`annotate`，每次讀說話者都檢查這場的紀錄）：
  - 那個編號的說話者不在，或聲音雜湊不同（換人了：重新轉錄、重新辨識、合併說話者）：刪紀錄。
    - 編輯會議之後要回復，靠編輯的快照（見下），不靠這裡留著。
  - 使用者處理過：
    - 套用或自己改名：`name_source` 變成 `manual`、`suggestion` 或 `tag`；
    - 略過：上游 `clearSpeakerSuggestion` 把 `suggested_name` 清成 NULL。
    - 這兩種都刪紀錄，不再出現（重開、重啟都一樣）。
  - 上游 `matchVoiceprints` 低信心時把建議換成別人（`suggested_name` 不是這個名字）：寫回資料庫。
    - 紀錄在資料庫，app 在打開這場之前重啟也照樣補回。
  - **高信心自動帶名**（≥ 0.88 而且領先 0.15，上游把這位說話者改成別人、`name_source = voiceprint`）：
    - **保留上游的自動帶名**，舊名字的建議照樣顯示在待確認、「猜到 N 位說話者的名字」裡，問「『Other』是 Old 嗎？」，可以一鍵套用（**使用者 2026-11-24 決定**，DF15）。
    - 上游 `loadSpeakers` 只把預設名稱的建議放進清單，`annotate` 把這種也放進 `speakerSuggestions`。
    - 上游 `matchVoiceprints` 自動帶名不清 `suggested_name`，略過時 `clearSpeakerSuggestion` 照常清掉。
  - AI 猜名字只寫在沒有建議的說話者，不會蓋掉。

**編輯會議（REV2-F12c P2-2，走既有的 F2 編輯入口，不加接點）**：
- 上游 `MeetingEdits` 第一次編輯時呼叫 `ForkSpeakerTags.snapshot`（既有接點）。這時另外呼叫 `ForkRetranscribe.snapshot`，把這場的 `ma_retranscribe_suggestion`、`ma_retranscribe_pending` 存進 `ma_meeting_edit_retranscribe`（migration `ma_retranscribe_v2`）。
  - 外鍵指到上游的 `meeting_edits`，`ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED`，同 F2 的 `ma_meeting_edit_tags`。
- 裁切、刪中間一段（`ForkSpeakerTags.remap`）：
  - pending 失效（刪掉）：說話者可能被移除、存檔後的狀態已經不成立；
  - 建議照留，由 `present` 用聲音雜湊判斷，說話者被移除的那筆就刪掉。
- 合併兩場（`ForkSpeakerTags.copyForMerge`）：
  - 這場的 pending 失效；這場原有說話者的建議照留（說話者沒變）。
  - 另一場的建議不帶過來（明確失效）：上游合併說話者時重新編號，fork 的入口拿不到對照。
  - 另一場移到垃圾桶，它自己的紀錄留著，還原時用得到。
- 分割（`ForkSpeakerTags.split`，上游已經把說話者照原編號複製到新的那場）：
  - 建議照編號複製到新的那場，只複製新的那場有這位說話者、而且聲音雜湊相同的；
  - 兩場的 pending 都失效。
- 還原（`ForkSpeakerTags.restore`）：從 `ma_meeting_edit_retranscribe` 放回這場的建議和 pending，換掉編輯後的。
  - 上游的快照會放回說話者（含 `suggested_name`），所以自動帶名下的舊名字建議會一起回來。
  - 編輯期間使用者略過或套用的，也回到編輯前的樣子，同上游還原的語意。

**顯示**：`annotate` 認得這種原因（任何會議語言），用目前的會議語言重新產生，不加「依內容猜」、不換成聲紋分數。

**來源的文字**：人物頁「聲音特徵」的來源多一種「重新轉錄後重新學」。

**DEBUG**：
- `mavoice retranscribe <會議> <設定.json>` 模擬重新轉錄：
  - 用目前的段落，照 `{"map": {"舊編號": 新編號}, "vectors": {"新編號": [向量]}, "seconds": {"新編號": 秒數}}` 換說話者編號和聲紋；
  - 沒給向量的新編號，用對應的舊說話者的聲紋；
  - 呼叫上游 `saveTranscript`，再呼叫 `ForkSpeakerTags.afterTranscription`、`matchVoiceprints`（同 JobRunner 的順序）。
  - 加 `"noselect": true` 時不重讀畫面（模擬轉錄完、還沒打開這場）。
  - 加 `"failSave": true` 時在 `named` 寫完 pending 後丟錯（模擬存檔回滾）。
  - 加 `"failLearn": true` 時在 `after` 學完第一位後丟錯（模擬學到一半失敗）。
- `mavoice retranscribe-retry <會議>`：再呼叫一次 `after`（同啟動時的重試）。
- `mavoice dismiss <會議> <說話者>`：等於按建議的「忽略」。

**驗證**：`f12-voiceprint-check.py` 第 9 段（check.sh #16）：
- 名字跟著聲音換編號；沒聲紋的照編號；F2 標記的名字不沿用；
- 對不上的變預設名稱加建議：
  - 低信心被聲紋比對蓋掉後補回；
  - 高信心自動帶名時，名字是自動的、建議照樣在；
  - 一鍵套用、略過後重開不再出現；
- 舊聲紋刪了、沿用的使用者取名用新聲音學（來源 `retranscribe`）；
- 存檔回滾後 `after` 不做事；學到一半失敗後重試會做完；來源表沒有孤兒。
- check.sh #16 另外結束、重開同一個暫存 SHIYIN_HOME 的 DEBUG 版：
  - 轉錄完、沒打開這場就重啟，打開後建議是舊名字；
  - 略過之後再重啟，不復活。
- 匯入封包不變靠 #6（F2 加上 5.0 的封包）。

## F13. 拿掉原作者相關資訊（F13，DF16）

不加 Swift 接點（100/100 不變）。設定都在 `fork/brand.json`，`brand.py` 在建置時處理建好的 app。

### F13.1 Credits 的贊助說明（`phrases`）

- 上游 `build-app.sh` 產生三份 `Credits.html`（繁中、簡中、英文），最上面一段 `<p>` 是贊助句（R13.3），下面 `<pre>` 是第三方授權。
- `brand.json` 的三條 `phrases` 把上游的贊助句（整句）換成空字串；`brand.py apply` 換完後把變成空的 `<p …></p>` 刪掉。
- 結構檢查（REV-F13 P2-1、REV2-F13 P2-5，fail-closed）：`brand.py` 認得的 Credits 只有上游 `build-app.sh` 的骨架 `<!doctype html><html lang="…"><meta charset="utf-8"><pre …>…</pre>`，骨架和 `<pre>` 之間不能有任何東西（贊助句換成空字串、空 `<p>` 刪掉後就是這樣）。`<pre>` 裡（`ThirdPartyLicenses.txt` 同一套）分三區檢查：
  - **開場白**（第一個「- 」之前）：非空行只能是 `brand.json` 的 `licenseIntro.lines`（人工核對過的上游完整句子，現在是中英兩句）換過品牌後的樣子。白名單是寫死在設定裡的完整句子，**不從待檢查的授權檔推導**：上游在開場白同一行接上作者或贊助、改了開場白的任何一個字，都會失敗，錯誤訊息指到 `fork/brand.json` 的 `licenseIntro.lines`（人工看過、確定沒有贊助後才更新）。
  - **套件清單**（第一個「- 」到第一條 `====` 分隔線之間）：非空行要嘛是套件項目 `- <名稱> (<授權>) <網址>`（授權是 SPDX 式的代號，網址是 http(s)、不是 `licenseList.forbiddenUrls` 裡的贊助網站），要嘛是 `licenseList.continuations` 列的接續行（現在只有 FluidAudio 的「and the third-party components it includes…」）。不符合（例如「- Support development at …」、不認得的接續行）就失敗，錯誤訊息指到 `licenseList`。合法新增的套件項目照常通過，不用把套件名稱寫死。
  - **授權條款**（第一條分隔線之後）：不解析，只檢查上游 MIT 那一節（§F13.2）。
  - 上游加了贊助平台（例如 GitHub Sponsors 的 `<p>`）、加了「Created by …」、改了骨架都會失敗，要人工看過再改 `brand.json` 或 `brand.py`。不用關鍵字黑名單判斷（換一個寫法就漏），也不全域禁止 `juinwei7`（`LICENSE` 裡的著作權人要保留）。處理過的產物重跑一樣通過（冪等）。
- 另外保留關鍵字檢查（`check_app`）：每份 Credits 不能有 `creditsForbidden` 的任何一個（`ko-fi.com`、`weiwei_chang`、「喝杯咖啡」、`coffee`、「改自」、`based on Shiyin`）。上游改了贊助句（連一個標點），整句對不到時名稱替換會留下「覺得會議助手好用的話…Ko-fi」，這個檢查讓建置失敗，不會默默留下。

### F13.2 上游的 MIT 聲明（`upstreamLicense`）

- 設定：`{"file": "LICENSE", "name": "拾音 Shiyin", "license": "MIT", "url": "https://github.com/juinwei7/Shiyin"}`。`file` 是 repo 裡照上游原樣的 `LICENSE`（合併上游時跟著上游）。
- `brand.py apply` 在品牌替換**之後**插入，所以裡面的專案名稱和著作權人不會被換掉：
  - `ThirdPartyLicenses.txt`：清單（第一個 `- ` 開頭的行）前面加一項 `- 拾音 Shiyin (MIT) https://github.com/juinwei7/Shiyin`；第一個 `====` 分隔區塊前面加一節，標題 `拾音 Shiyin: LICENSE`（跟其他套件的寫法一樣），內容是 `LICENSE` 原文。
  - 三份 `Credits.html`：`<pre>` 裡同樣的位置插入同樣的內容（HTML 跳脫，跟上游產生 Credits 的寫法一樣用 `html.escape`）。
  - 已經有 `拾音 Shiyin: LICENSE` 的檔不再插入（重跑結果不變）。找不到清單或分隔區塊（上游改了格式）就失敗。
- 讀入 `LICENSE` 時檢查（REV-F13 P2-2）：去掉空白後不能是空的，而且要有 MIT 的三段——著作權行（`Copyright (c) …`）、許可段（`Permission is hereby granted, free of charge` 到 `copies or substantial portions of the Software.`）、免責段（`THE SOFTWARE IS PROVIDED "AS IS"` 到 `OTHER DEALINGS IN THE SOFTWARE.`）；比對時把連續空白視為一個空白。不符合就 `apply` 失敗、`check` 報錯，要人工核對（上游換授權或檔案壞了）。插入的仍是原文，不改寫。
- `keep` 加 `拾音 Shiyin(?= \(MIT\)|: LICENSE)`，殘留檢查不把這兩處當成漏換。
- 檢查（`check_app`）：`ThirdPartyLicenses.txt` 和每份 Credits（去掉 HTML 跳脫後）都要有那一項、標題和 `LICENSE` 全文，少了就失敗。
- DMG：`make-dmg.sh` 已經拿 app 裡換過的 `ThirdPartyLicenses.txt` 放進 DMG（§F7.2），不用另外改。

### F13.3 app 內更新說明不寫「基於上游」（`releaseNotes`）

- 來源：`release.yml` 的「更新內容」步驟把 tag 說明放進 `SHIYIN_RELEASE_NOTES`；同一個變數給 `make-dmg.sh` 寫進 `shiyin-update.json` 的 `notes`（app 內更新視窗讀這個，`ReleaseNotes.brief` 取中文或英文段落的「- 」條目），也給 `gh release create --notes`（GitHub Release）。
- `make-dmg.sh` 產生 `shiyin-update.json` 之前加 1 行腳本接點：`SHIYIN_RELEASE_NOTES` 先經過 `scripts/fork/release-notes.py app`，拿掉符合 `brand.json` `releaseNotes.appDrop` 的行（`^- 基於上游 `、`^- Based on upstream `），其他行原樣（含空行、段落）。這個變數在 `make-dmg.sh` 的子程序裡，不影響 `release.yml` 後面的 `gh release create`，GitHub Release 保留這行。
- 不在 app 裡過濾：要加 Swift 接點（`ReleaseNotes`），而且已經裝好的舊版也會讀新版的 `shiyin-update.json`；在產生的時候拿掉，舊版看到的也沒有這行。

### F13.4 停用官網的 workflow

- `site.yml` 的 job `deploy` 的 `if` 前面加 `github.repository == 'juinwei7/Shiyin' &&`（行尾 `# MA-FORK(F13)`）：在 fork 每次觸發（推 main、打包完成、每天的排程、手動）都是「略過」，不建置也不部署。
- `.github` 不在接點檢查的範圍、不算行數（§F0.3）；合併上游時這一行如果上游也改了，保留 fork 的條件。
- 不採用：在 GitHub 的 Actions 設定停用 workflow（不用改檔，但要使用者用網頁或 `gh` 操作，repo 裡看不出來；使用者想連「略過」紀錄都不要時可以另外做）；刪掉 `site.yml`（合併上游時每次衝突）。

### F13.5 README

- `README.md`、`.github/README.md` 改寫成會議助手的：簡介（MIT 授權的拾音 fork）、fork 加的功能、怎麼用、系統需求、安裝（EdenQ/Shiyin 的 Releases、自簽、仍要打開）、從原始碼建置（clone EdenQ/Shiyin）、資料與隱私（沒有匿名使用統計）、開發（docs/fork）、使用的開源專案、授權（MIT，附上游 repo 連結）。
- 兩份是上游的檔（不在接點檢查範圍）；合併上游時一律取 fork 的版本，上游 README 新增的功能說明要不要寫進來另外判斷（`docs/fork/upstream-sync.md`）。

### F13.5a `brand.py compare` 與拿掉型的 phrase（REV-F13 P2-3）

- `compare` 找舊版的鍵時用 `unbrand_key` 把 fork 的寫法還原成上游的寫法（`to` → `from`）。`to` 是空字串的 phrase（Credits 的贊助）不能反向還原：空字串會在每個字元之間插入整句。`unbrand_key` 跳過 `to` 是空的 phrase；`compare` 先找完全相同的鍵，找不到才算還原的候選。

### F13.6 更新視窗的「完整說明在官網」

- 上游 `ReleaseNotes.text` 沒列完時加一行「……還有 N 項，完整說明在官網。」（查翻譯表）。fork 沒有官網，`brand.json` 的 `phrases` 換成「完整說明在 GitHub 的 Releases 頁面。」（簡中、英文各一條，`required` 指到各自的 `Localizable.strings`）。
- 這句沒有品牌字：`brand()` 原本只處理有「拾音」「Shiyin」的字串，改成有任何一條 `phrases` 的 `from` 也處理。不加 Swift 接點。

### F13.7 驗證

- `brand-test.py`：REV2-F13 P2-5 的反例（開場白同一行接作者、接贊助、兩者都接，假的清單項目要失敗；新增一個合法套件項目要通過、重跑不變）；REV-F13 的反例（Credits 換成 GitHub Sponsors、作者介紹要失敗；`LICENSE` 空檔、純空白、截斷要失敗；舊品牌鍵 `compare` 要對得上、`unbrand_key` 不膨脹）；apply 後三份 Credits 沒有贊助、有 MIT 聲明；`ThirdPartyLicenses.txt` 有那一項和全文；重跑不變；上游贊助句改了標點要失敗；把 MIT 那一節刪掉後 `check` 要失敗；`release-notes.py app` 只拿掉兩行。
- `check.sh --only 3`（品牌：release、DEBUG 建置結果）；`isolation-check`（make-dmg.sh 的新接點登記在 manifest）。
- 用建好的 release 版的 `ThirdPartyLicenses.txt` 照 `make-dmg.sh` 的方式放進暫存的 DMG，掛載後確認內容。
- 用 v5.0.3、v5.0.4 的 tag 說明跑 `release-notes.py app`，結果用上游的 `ReleaseNotes.brief` 列出的第一項是這版的改變；建好的 app 的三份 `Localizable.strings` 是 GitHub Releases 的那一句。

## F-DB. 資料庫規則（PLAN-fork-5.0 §6）

### F-DB.1 規則

1. fork 的 migration 名稱用 `ma_` 開頭，**只新增、不改、不刪**；已經發布的 migration 內容永遠不改（`ma_speaker_tags_v1` 也一樣）。
2. 新的資料放 fork 自己的表，用 `meeting_id … REFERENCES meetings(id) ON DELETE CASCADE` 掛在會議上，表名 `ma_` 開頭（已經有的 `speaker_tags` 不改名）。不在上游的表加欄位；真的要加時欄位名 `ma_` 開頭、可以是 NULL，寫成 DF 決策。
3. 註冊順序：上游的 migration 全部註冊完之後才呼叫 `ForkMigrations.register(&migrator)`。GRDB 依名稱判斷跑過沒有，從中間搬到最後對已經升級的資料庫沒有影響；新資料庫在上游最後一個 migration 之後才建 `speaker_tags`，結果一樣。**合併 5.0 時搬**，用 `scripts/dev/check-fork-migrations.py` 驗（全新、v7、Fork v8、上游 v8～v10、fork 4.7.6 的資料庫，以及降回舊版再打開）。
4. 降回舊版要能開：fork 的 migration 不可以讓上游或舊版 fork 的程式出錯（例如加了 NOT NULL 又沒有預設值的欄位）。
5. 上游會搬動、改時間、複製、還原會議資料的功能，fork 的表要跟著處理（F2.13）。清單在 §F-DB.2；上游監看（PLAN §8.2）會自動找新出現的這種 SQL。

### F-DB.2 上游 5.0 要跟著處理標記的地方（5.0.1）

上游 5.0 不認得 `speaker_tags`（已確認上游程式沒處理）。

| 上游功能 | 上游處理的表 | fork 要補的 | 接點 |
|---|---|---|---|
| R107 編輯會議（裁切、刪中間一段） | `MeetingEdits.swift`：segments（start、end 平移）、bookmarks、speakers、documents、notes；改前存快照 | 標記照同一份時間對照平移；被刪掉的範圍裡的標記刪掉；快照也存標記，放 fork 的表 `ma_meeting_edit_tags(meeting_id, tags_json)` | `MeetingEdits` 套用、還原各 1 行：`ForkHooks.meetingTimesRemapped(db, id, map)`、`ForkHooks.meetingEditRestored(db, id)` |
| R90 從某一句分成兩場 | `AppDatabase.splitMeeting`：切點之後的 segments、bookmarks 改到新會議，時間減切點 | `start >= cut` 的標記改到新會議、時間減 `cut`；跨過切點的切成兩段 | `splitMeeting` 尾端 1 行 |
| 合併兩場 | `MeetingEditor.merge`：另一場的資料接在後面（時間加位移） | 另一場的標記改到這場、加同樣的位移 | 1 行 |
| R89 刪一句、R70 拆句 | segments | 不用動（標記是時間範圍；F2.12「只改這句」的比對自然跟著句子變） | 沒有 |
| 垃圾桶、永久刪除 | CASCADE | 沒有 | 沒有 |
| `.shiyin` 封包匯出、匯入 | 上游的表 | 帶標記（F2.8），見 §F-DB.3 | 匯出、匯入各 1 行 |

做法（`Fork/SpeakerTags/ForkSpeakerTags.swift`）：
- 第一次編輯前把這場的標記存進 `ma_meeting_edit_tags`（migration `ma_meeting_edit_tags_v1`；外鍵指到上游的 `meeting_edits`、`ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED`：上游在交易最後才存快照，過期刪快照時 fork 的跟著刪）。
- 這場的標記照 `EditPlan.mapSentence` 搬到新的時間軸（跟句子同一套：中間點在留下的片段裡就留，被剪掉的刪掉）；合併時另一場的標記複製過來（那場移到垃圾桶，它自己的標記留著，還原時用得到）。
- 分成兩場（R90 從某一句分、編輯畫面的 split 都走 `splitMeeting`）：`start >= cut` 的移到新會議、減掉切點；跨過切點的切成兩段。
- 還原：照快照放回這場的標記（合併進來的、搬過的都換回原本的）；分出去的那場移到垃圾桶，它的標記留著。

驗證（5.0.1，DEBUG 版暫存 SHIYIN_HOME，示範會議加 5 個標記：甲 10–20、乙 600–620、戊 1790–1810、丙 2000–2010、丁 3000–3020，`speaker_tags` 直接查）：
- `editmeeting 1 keep=0-500,1000-3912`：乙（中間點在剪掉的地方）刪掉，戊、丙、丁各減 500；快照存了 5 個。`restoreedit 1`：5 個回到原本的時間，快照跟著刪。
- `editmeeting 1 split=1800`：戊切成這場的 1790–1800 和新會議的 0–10；丙、丁移到新會議的 200–210、1200–1220。`restoreedit 1`：這場回到原本的 5 個，新會議移到垃圾桶。
- `editmeeting 2 merge=1:0-100`：會議 1 的甲接在會議 2（125 秒）後面變成 135–145，會議 1 移到垃圾桶、它的標記不變；`restoreedit 2`：會議 2 只剩它自己的標記，會議 1 拿出垃圾桶。

- **F12.15 的 `ma_retranscribe_suggestion`、`ma_retranscribe_pending`**（§F12.9，REV2-F12c P2-2）也走上面同一組 fork 入口：
  - 快照存進 `ma_meeting_edit_retranscribe`、還原時放回；
  - 裁切、合併時 pending 失效；
  - 分割時建議照編號複製到新的那場；
  - 刪會議由外鍵 CASCADE。
  - 前一版以為「編輯會議一定改變說話者的聲紋雜湊」，所以不處理；實際上裁切、分割可能完全不變，已修正。

### F-DB.3 封包帶標記（F2.8，2026-11-18 使用者決定）

- 匯出：封包裡多一個 fork 自己的檔 `ma-speaker-tags.json`：`[{start, end, name, kind}]`（時間是錄音檔的秒數，同 `speaker_tags`）；沒有標記時不寫這個檔，封包跟上游的一樣。封包的格式版本（`manifest.json`）、`meeting.json` 都不變：上游的拾音匯入時只讀它認得的檔，會略過這個檔、照常匯入。
  - 原本（0c）寫的是在 `meeting.json` 加 `maSpeakerTags` 鍵；實作改成另外的檔：不用改上游的 `MeetingJSON` 結構，接點少一個，上游以後改 `meeting.json` 也不會跟 fork 衝突。
  - 接點：`ExportBundle` 多一個 `speakerTags`（Exporters 1 行）；`AppModel.export` 的 `.package` 前由 `ForkSpeakerTags.attach` 帶入（1 行）；`MeetingPackage.export` 壓縮前 `writePackage`、`importPackage` 加完標記重點後 `readPackage`（各 1 行）。
- 匯入：有這個檔就把標記加進新會議（`kind` 只收 `line`、`now`；時間不合理、名字空白的略過，讀不出來整個略過，不讓匯入失敗：封包可能來自別人）。沒有（舊封包、上游拾音匯出的）照常匯入、沒有標記。標記不重新套用到說話者（封包裡的說話者名字已經是套用後的結果）；之後重新轉錄、重新辨識說話者時照 F2.7、F2.10 再對一次。
- 驗證（5.0.1，DEBUG 版暫存 SHIYIN_HOME）：帶 5 個標記的會議 `export package` → `import`，新會議的標記跟原本逐條相同；沒有標記的會議匯出的封包裡沒有 `ma-speaker-tags.json`、匯入成功、0 個標記。上游 5.0 的匯入程式只讀 `manifest.json`、`meeting.json`、`transcript.json`、`documents.json` 和錄音，不會讀到 fork 的檔（看程式碼確認，沒有另外建上游的 app 測）。

## F-UP. fork 對上游設計的補充（引用上游節號）

上游文件不改，fork 的補充都寫在這裡。合併上游時看這張表，確認上游那一節的寫法沒有讓補充失效。

| 上游 | fork 的補充 |
|---|---|
| §3 檔案配置 | `Resources/AppIcon.icns` 由 `Resources/AppIcon-1024.png` 經 `scripts/make-icon-from-png.sh` 產生（§F1）；上游的 `scripts/make-icon.swift` 畫舊圖示，fork 不用。另外有 `fork/`（品牌設定）、`scripts/fork/`（`brand.py` 等）、`Sources/Shiyin/Fork/`、`docs/fork/` |
| §12.1 更新網址 | GitHub 的 repository variable `SHIYIN_UPDATE_URL` 設成 `https://github.com/EdenQ/Shiyin/releases/latest/download/shiyin-update.json`（fork 的更新來源，**不可指回上游**）。Release 的說明文字照 DF6 加「- 基於上游 拾音 X.Y.Z」；這行不進 `shiyin-update.json` 的 `notes`（`make-dmg.sh` 的 1 行接點，§F13.3） |
| §12.1 Credits、R13.3 贊助 | 授權開場白在建置時換成會議助手；贊助說明拿掉；Credits 和第三方授權檔的最前面加上上游拾音的 MIT 聲明（§F7.1、§F13）。`build-app.sh` 產生 Credits 的程式照上游 |
| 官網（`docs/website.md`、`.github/workflows/site.yml`） | fork 不跑官網的 workflow：job 的 `if` 多一個 `github.repository == 'juinwei7/Shiyin'`（§F13.4）。`site/` 的內容照上游 |
| §21.9 回報問題 | Info.plist 的 `ShiyinIssuesURL` 設成 `https://github.com/EdenQ/Shiyin/issues`（F1.5）；程式裡的預設常數保留上游的值，減少合併衝突 |
| §38.5 文字大小 | 錄音中說話者標記（F2）的名字、時間欄位與未定稿文字的空白欄一起依 `textScale` 縮放 |
| §43 議題時間軸、D145 | fork 的議題帶改用 `MindMap.topicSegments`（依每條重點的時間切段，同一個議題可以有好幾段），點了在紀錄分頁也捲到那個議題（§F4.2、§F4.3、DF4）。上游的 `topicRanges` 和它的標準答案不變 |
| §44 本地 MCP | 給 AI 工具的英文訊息、`serverInfo` 照上游寫 Shiyin，不換品牌（F7.3）；設定頁和錯誤訊息這些查翻譯表的文字建置時換成會議助手 |
| §49、§50（R73、R74） | 4.7.6 帶入上游 4.8.1 的寫法（F6）。§49.2、R73.6、R74.6 的 Windows 部分 fork 不做 |
| §50.2 重新連接在背景 | fork 補的同步規則（DF5）：音源上會被兩個執行緒碰到的值都用 `LockedValue`（`NSLock`，每次讀寫只短暫拿鎖）存。`MicrophoneInput.deviceUID`：換麥克風時主執行緒寫、`deviceQueue` 上的 `start()` 讀；`current`（正在收音的裝置）：`start()` 在背景寫、主執行緒更新畫面時讀。`MicrophoneSource`、`FileSource` 一樣。不用 `deviceQueue.sync` 包住換麥克風：那會等整個重新連接做完，畫面又卡住（R74.4）。`start()` 一開始讀一次 UID 當這次的快照，中途換了就由 `restartAgain` 再做一次。`LockedValue` 的類別在 `Fork/DF5/LockedValue.swift`，用到的地方留在上游的 AudioSources、標 `MA-FORK(DF5)`。驗證：`LockedValue` 原樣放進不碰硬體的 ThreadSanitizer 小程式（`scripts/fork/tsan-lockedvalue/run.sh`），背景一直 `start()`、主執行緒一直換 UID、讀 current，沒有資料競態；改回普通屬性時 TSan 報告競態。上游的同一段沒有加鎖（上游仍有這個競態），上游哪天自己加鎖時刪掉 fork 的 |
| 上游 5.0 的錄音島（R81、§57） | 靜音中（F3.7）：收起時紅點換成劃掉的麥克風（有提醒時琥珀色）；滑過去在音量下面寫「麥克風靜音中」加「打開麥克風」；靜音中好像有人說話的提醒（F3.4）跟錄音畫面的提示列一樣出現在島上，順序同提示列（沒人說話 → 靜音中好像有人說話 → 藍牙 → 收音）。`Fork/Mute/ForkIslandMute.swift` |
| 上游 5.0 的錄音島放在哪個螢幕（R81.1、§57.1） | 上游用 `NSScreen.main`（目前在用的螢幕）；fork 預設固定在內建螢幕，設定可以改回上游的行為或選主視窗所在的螢幕（F11、§F11、DF11）。上游 `place` 其他的算法（瀏海、位置、動畫）不變，只換「哪個螢幕」 |
| 上游 5.0 的收音檢查（R75、§51.1） | 靜音中不做麥克風的提醒（F3.5），但上游新的「錄不到電腦聲音」（系統音訊權限被拒）照樣提示：`checkLevels` 在 `checkSystemPermission` 和 `guard hasMic` 之後 1 行接點 |
| 上游 5.0 的選單列圖示（`hint.symbol`） | 上游的收音提醒圖示優先，再來是 F3 的「忘了打開」提醒（`mic.badge.xmark`）、靜音中（`mic.slash.circle.fill`） |
| 上游 5.0 的設定十一頁（R108） | F3 的「錄音中按 ⌃⌥⌘M 靜音」開關放在「錄音」頁的「提醒與快捷鍵」最後（`Fork/Mute/ForkMuteSettingsRow`，經 F0 的共用列 `ForkRecordingSettingsRows`，§F0.7） |
| 上游 5.0 的會議頁上方（R84）、彈窗（R106） | `speakerChip` 的來源是 `tag` 時用 fork 的 `ForkTaggedSpeakerName`（上游 `AutoSpeakerName` 的複本，後面標「標記」，§F0.2）；說話者名字彈窗的「從錄音時的標記帶入」說明和「不是他」照舊（F2.9） |
| §21.4 聲紋、§21.5 猜說話者、R33 待確認的說話者題目 | 建議的原因在顯示時改寫成依據（分數、第二像、兩人很像、建議過時），AI 猜的標「依內容猜」；自動帶入的名字用 fork 的 `ForkAutoSpeakerName`（上游 `AutoSpeakerName` 的複本，選單最上面多一行依據）；上游 `renameSpeaker` 取名前先檢查聲音（防呆）；人物頁多「聲音特徵」可以刪單份（F12、§F12、DF12～DF14）。上游存的建議、`matchVoiceprints`、`learnVoiceprint` 的規則不變 |
| 上游 5.0 的就地編輯（R100）、加到提醒事項（R76） | 條列模式整頁是 fork 的 `ForkNotesList`（§F0.2）；段落用 `ForkNotesSection`：fork 的條數、色條、複製鈕加上上游的 `accessory`（「待辦」的「加到提醒事項」放在複製鈕後面）；條目在編輯中用上游的 `NoteItemEditor`，其他時候用 fork 的 `NoteRow`，接上 `noteItemActions`（右鍵、⋯），可以就地編輯的條目不設成可選取；待辦表（`ForkActionItemsTable`）保留 fork 的欄位順序（負責人、期限、事項、時間點），負責人加上游的頭像，事項接上就地編輯和提醒事項的勾。上游的 `NotesSection`、`ActionItemsTable` 不動 |
| 上游 R70 拆句、`addSpeaker()` | F2.12「只改這句」在 fork 的 `AppDatabase.reassignSegments(…naming:…)` 用一筆 `pool.write` 照 5.0.1 的順序做完：上游的 `saveSpeakerUndo`（復原快照）、`addSpeaker()`（新增說話者）、`ForkSpeakerTags.nameNewSpeaker`（標記的名字）、改句子的說話者、上游的 `removeEmptySpeakers`；任何一步失敗整筆回復（DF8）。上游 private 的 `saveSpeakerUndo`、`addSpeaker` 由 SpeakerEdits 裡各 1 行接點 `forkSaveSpeakerUndo`、`forkAddSpeaker` 轉呼叫（`saveSpeakerUndo` 的參數用到 private 的 `SpeakerSnapshot`，不能直接改 internal；只加行、不改上游的行）；上游的函式不改簽章 |
| 上游 `AppDatabase.saveTranscript`（重新轉錄存檔，§5.3、§21.4） | 名字改成照聲音沿用、對不上的存成建議、存檔後刪對不上的舊聲紋並重新學（F12.15、§F12.9、DF15）。上游照編號沿用、不動聲紋；沒有舊說話者時（匯入、第一次轉錄）跟上游一樣 |
| 上游 5.0 的 DEBUG `state` | 錄音中錄音島出現時，視窗清單裡島的面板 `maxSize` 是無限大，`state` 寫 JSON 時丟例外、DEBUG 版結束（上游原樣也一樣；正式版不受影響）。fork 不改上游的檔：測錄音中的狀態時用 `-recordingIsland NO` 啟動。島的畫面用 fork 的 DEBUG 指令 `mawindowshot <輸出.png> island` 拍 |
| 上游 5.0 的提醒事項（R101） | 列表名稱「會議助手」、舊名「拾音」列表沿用（F7.5、§F7.3 的接點） |

## DF. fork 的決策紀錄

| # | 決策 | 不採用的方案與原因 |
|---|---|---|
| DF1 | 錄音中只記使用者的標記，錄完依時間套到離線辨識分出的說話者；對不上或有矛盾就不套用 | 錄音中即時分辨說話者（FluidAudio 的 Sortformer、LS-EEND）：AMI 上錯誤率 26～34%，錄完的離線辨識是 12%，Sortformer 最多 4 人，錄音中的編號跟錄完的結果還要再對一次，也要多下載模型。標記直接當成一段一段的說話者（不經過說話者辨識）：只有標過的幾段有名字。對不上也取最接近的說話者：標錯或說話者辨識把兩個人併成一位時會套錯名字，還會學到錯的聲紋（D29：寧可少、不能錯）。代價：錄音中只有標過的那幾行看得到名字 |
| DF2 | 標記帶入的名字當成「自動」的名字：畫面上標「標記」、可以說不是他；說話者辨識可能把人併在一起的會議不存聲紋；重新辨識說話者、合併時跟重新轉錄一樣重算（F2.9～F2.11，2026-10-29） | 當成手動改名（2026-10-22 的做法）：按錯人、或說話者辨識把兩個人併成一位而只標了其中一人時，錯的聲紋直接進聲紋庫，之後的會議會以 ≥ 0.88 的相似度自動帶入錯的名字，使用者在畫面上也看不出這個名字不是自己取的。完全不從標記學聲紋：每個人標一次就能讓之後的會議認得，是標記最大的好處。只看每位說話者自己的凝聚度：FluidAudio 只給整場的品質，沒有每位的 |
| DF3 | 錄音中靜音麥克風時，麥克風那一聲道直接寫成 0（F3，2026-11-03） | 照錄、只記下靜音的時間範圍，轉錄和即時逐字稿時才拿掉：選錯了救得回來，但正式轉錄、說話者辨識、壓縮、匯出、封包、重新轉錄都要跟著處理這些範圍，錄音檔裡也還是有會議室的閒聊（使用者要的就是不錄）。跟 Teams 的靜音一樣「靜音就是沒錄」，最好懂；代價是忘了打開的那段救不回來，所以加上忘了打開的提醒（F3.4） |
| DF4 | 紀錄條列頁先做分段複製、時間點降噪、色條、議題收合與目錄，議題帶改用新函式依重點時間切段（F4，2026-11-10 使用者看過預覽後確認） | 整頁換成一份文字（唯讀 NSTextView）讓原頁可以任意拖選：待確認的就地回答要改成彈出視窗、待辦表要重排、焦點與捲動都要重做，先用分段複製滿足「貼到 Slack／郵件」的實際需求。直接改 `topicRanges`：Windows 也比對它的標準答案，fork 只做 Mac，所以另寫 `topicSegments`。修正 D145「回頭講前面的議題算進後面的議題可以接受」：使用者想看出重回；整理工具給的每條重點時間已經夠用，不必請整理工具另給結束時間。最小片段 60 秒：一條時間填錯或順口提一句時，議題帶上會切出點不到的細線、目前議題來回跳；60 秒在一小時的會議約 1.6% 寬，差不多是點得到的寬度。開始段例外保留（2026-11-10 審查後決定）：併掉時議題列寫 00:00、議題帶上卻在一小時後才出現，議題列的開始時間、點開始時間播放、目前議題對不上；代價是議題帶上可能有很細的色塊（不寫字，滑過看名稱）。保護「包含 `start` 的段」而不是「最早的段」：早於 `start` 的重點可能是時間填錯，不該永久保留。零長度段（同一秒好幾個議題）不算一段，不然唯一有效的短段會被當成「還有別段」併掉。重回的段不往前多算：沒有依據，會吃掉前一個議題。議題膠囊目錄不是 D109 拒絕的側邊欄：只在議題 > 5 個時出現、放在紀錄上方一列、只做導覽不放要處理的內容，不佔寬度。重點先行、摘要收合：使用者看過預覽後不要。播放時自動捲動：使用者在讀別段時會被拉走，只標出 |
| DF5 | 麥克風音源的 `deviceUID`、`current` 用短暫拿鎖的 `LockedValue` 存（上游 §50.2 的補充，見 §F-UP；2026-11-16 審查帶入的上游 R74 時發現） | 主執行緒先取 UID 的快照傳進背景：要改上游共用的 `AudioSource.restart()` 介面，`current` 從背景寫回仍然要同步，日後合併上游衝突多。換麥克風用 `deviceQueue.sync`：會等整個重新連接做完（藍牙要好幾秒），抵消 R74.4 的不卡住。改成 actor：`start()` 是同步的 AVAudioEngine 呼叫，要大改。上游 b042c94 原本是普通屬性，TSan 證實換麥克風和重新連接同時發生時有資料競態 |
| DF6 | 版本號規則：build 號從 31 起單調遞增、不跟上游；合併上游 X.Y.Z 的那一版是 X.Y.(Z+1)，比 fork 目前的版本小時取 fork 的 patch + 1；fork 自己的發布只加 patch；說明文字第一行後面加「- 基於上游 拾音 X.Y.Z」（PLAN-fork-5.0 §2.3，2026-11-18 使用者同意；這行只留在 GitHub Release，不進 app 內更新說明，F13.3、DF16） | 照上游的版本號：fork 自己的修正沒有號碼可用，跟上游同號會讓使用者以為是同一版。另外一套版本號（例如 1.0 起）：看不出基於上游哪一版，`Updater.isNewer` 只比數字，從 4.7.6 換到 1.0 使用者就收不到更新。這個規則永遠往上，app 內更新照常 |
| DF7 | 品牌在建置時換建好的 app（`brand.py apply`），原始碼、翻譯表、Info.plist 照上游寫（F7，2026-11-18） | 原始碼直接寫「會議助手」（4.7.6 以前）：每次合併上游，32 個 Swift 檔、翻譯表 89 個鍵、Info.plist、安裝說明都衝突，而且上游新加的字串一定是「拾音」，要人工找。在建置前換一份翻譯表再編（PLAN 的原案）：繁中是來源語言，要另外寫明確的繁中值，還要處理鍵；編出來的繁中 `.strings` 本來就有全部的鍵，直接換值比較簡單，也能一起處理 `.stringsdict`、InfoPlist.strings。Swift 裡用 `Brand.name(...)` 包每一處：還是會衝突。代價：有幾處不經過翻譯表（關於、更新說明、5.0 的提醒事項）要留 1 行接點，原始碼掃描擋住上游新增的。防護要嚴：原始碼掃描只認包住字串的最內層查表呼叫，不看附近幾行；整句特例依資源規定一定要命中，不能只看有沒有殘留的「拾音」（2026-11-18 審查 P2-1、P2-2）。原始碼掃描只放行能證明會查表的參數寫法（單一常值、兩邊都是常值的三元運算），其他保守報錯；正確性用 Swift 編譯器的 `-emit-localized-strings` 依位置核對（`brand.py crosscheck`），不在每次建置都跑編譯器：那要改上游的 `swift build` 那行或多編一次整個模組（複審 P2-3） |
| DF8 | fork 功能隔離到 `Sources/Shiyin/Fork/`，上游檔只留標了 `MA-FORK` 的單行接點（PLAN-fork-5.0 階段 2，2026-11-19）：狀態放 fork 自己的物件（`ForkAppState`、`MeetingDetail.forkTags`、`ForkMute.State`），要用的上游 `private` 成員改 internal 並標成接點，條列模式整頁、`AutoSpeakerName` 這種整塊改過的畫面用 fork 的複本；「只改這句」在 fork 的函式裡用一筆交易重用上游的 `saveSpeakerUndo`、`addSpeaker`、`removeEmptySpeakers`（兩個 private 的由 SpeakerEdits 裡各 1 行轉呼叫的接點 `forkSaveSpeakerUndo`、`forkAddSpeaker` 開出來），改句子說話者的那幾行是 fork 的複本（跟上游 `reassignSegments` 的迴圈相同）；不改成先呼叫上游的 `reassignSegments` 再另開一筆改名：第二筆失敗時第一筆已經存了（多出一位預設名稱的說話者、句子已改、留下復原快照），跟 5.0.1 的整筆回復不同（REVIEW-2 P2-1，`scripts/fork/f2-atomic-check.py` 用 SQLite trigger 讓改名失敗來檢查）；標記的名字存不存聲紋改由 `learnVoiceprint` 裡 1 行接點問 `ForkSpeakerTags.remembersVoice`；`LockedValue` 類別搬到 `Fork/DF5`；用 `isolation-check.py` 檢查（§F0.3） | 照舊在上游的函式加參數（`reassignSegments(name:)`、`learnVoiceprint(remember:)`）：改了上游函式的簽章，上游改同一個函式就衝突（§F0.1 第 4 點）。在上游元件加參數（`NotesSection` 的 count、accent、copy，`TimeButton` 的 subdued）：上游 5.0 就地編輯時已經衝突過一次，複本的代價是上游改原元件時要人工比對（manifest `highRisk`）。把上游的條列模式留著、fork 的另開一頁：同一份內容兩份程式，使用者看到的仍是 fork 的，上游的那份只是佔位。「只改這句」第二筆失敗時再補做復原：補做本身也可能失敗，中間別的寫入看得到改了一半的資料，不是原子性。接點的範圍用「開始、結束」兩個記號包住一段：可以包很長一段，失去「上游檔只留接點」的意思，行數也看不出來 |
| DF9 | 定期備份用 sqlite3_backup（來源是 GRDB 讀取交易裡的快照；目的地自己用 `O_EXCL | O_NOFOLLOW` 建、`SQLITE_OPEN_NOFOLLOW` 開，§F10.1a），寫完跑 `integrity_check` 才改名；上一次成功的時間看 `backups/daily/` 裡最新的檔，不存在設定；設定（一般頁）的一段用 1 行接點（98 → 99），啟動、「MA」選單改走 F0 的共用入口 `ForkStartup`、`ForkAppMenuCommands`，換掉既有的 2 行（F10，2026-11-20 使用者確認） | `VACUUM INTO`：不能在交易裡跑，GRDB 的讀取一律包交易，要另開連線，又會重排整個檔，沒有多的好處。存 `maBackupLastSuccess`（需求草稿的寫法）：設定跟著 bundle id、不跟著 `SHIYIN_HOME`，換了資料夾（測試、示範資料夾）時會拿別的資料夾的時間判斷，所以改成看檔案、另存 `maBackupFailingSince` 算 7 天。各功能各加接點：會用掉剩下的 2 行；提高接點上限：使用者選共用入口 |
| DF10 | 接點上限 100 不提高；行數快滿時把既有接點收進 F0 的共用入口（§F0.7）。這次收掉 3 行（99 → 96）：DebugControl 的 `default:` 和 `hotkey` 那兩行改由 switch 前的 `ForkDebug.intercept` 處理（fork 指令名稱跟上游不重疊，由 isolation-check 守住），AppModel 停止錄音時關 ⌃⌥⌘M 改由 `ForkMute.install` 包住 `recorder.onFinished`；設定的 F3 列改名成共用列 `ForkRecordingSettingsRows`（行數不變，給 F11 用）（HK-consolidate，2026-11-23 使用者決定先合併再做 F11） | 提高上限：使用者不要。把相鄰的兩行 fork 程式擠成一行（SpeakerEdits 的 `forkSaveSpeakerUndo`、`forkAddSpeaker`）：數字變小，但跟上游衝突的面積一樣，不算真的減少。GlobalHotKey 的 3 行（`register`、`unregister` 改 internal、事件處理裡分派 fork 的 id）改成 fork 自己裝 Carbon 的事件處理：按真的快捷鍵的路徑沒辦法自動測（不能送按鍵），處理的順序、吞不吞事件一錯就是兩個快捷鍵都壞。Recorder 的 `resetForStart`、`resetForStop` 改用回呼：`onStarted`、`onFinished` 被呼叫的時間點跟現在的位置（開始流程中、`cleanup` 裡）不同，要另外證明每條開始、停止、失敗的路徑都一樣，風險比省下的一行大。RecordingView、MenuBar 的麥克風音量條兩行（加 fork 的圖示、藏起或淡化上游的那條）：要藏上游的元件只能改它那一行。ReleaseNotes、AudioSources（DF5）、TranscriptTab 等改上游既有行的：一行就是一處邏輯，合併要改上游的寫法，合併上游時更容易衝突 |
| DF11 | 錄音島預設固定在內建螢幕，設定可以選「跟著目前在用的螢幕」（上游 R81.1）、「內建螢幕」、「主視窗所在的螢幕」；沒有內建螢幕時退到主視窗所在的螢幕，再不行照上游；內建螢幕用 `CGDisplayIsBuiltin` 判斷；偵測會議的提醒跟島一起固定（F11，2026-11-23 使用者決定）。偏離上游 R81.1 的理由：上游每 0.5 秒、換 app 時把島搬到 `NSScreen.main`，多螢幕時使用者在哪個螢幕操作島就跟到哪，來回切換時一直跑；固定在一個螢幕位置可以預期，有瀏海的 MacBook 接在瀏海兩側最自然。上游的行為保留成一個選項。接點 1 行（96 → 97），寫成通用入口 `ForkIsland.screen()` | 一律固定在內建螢幕、不做設定：想要上游行為的人只能把島關掉。固定在「開始錄音時主視窗所在的螢幕」：用快捷鍵、會議提醒開始錄音時主視窗常常沒開，規則也難懂（這次在左邊、上次在右邊）。沒有內建螢幕時固定在主要螢幕（有選單列的那個）：使用者要的是主視窗所在的螢幕。用螢幕名稱（`localizedName`）認內建螢幕：名稱跟著系統語言變、可以改名。不加接點、fork 在外面另外搬視窗：上游下一個 0.5 秒又搬回去，島在兩個螢幕之間閃。覆寫 `IslandPanel.setFrame`、在執行期換掉 `NSScreen.main`：要動上游的 `final class` 或用 Objective-C runtime，太脆弱。提醒維持跟著目前在用的螢幕：要多一套判斷，使用者決定一起固定 |
| DF12 | 聲紋的分數在顯示時重算（`MeetingDetail.loadSpeakers` 1 行接點），不存（F12，2026-11-24）。等級照上游的兩個門檻（≥ 0.88 很像、≥ 0.65 有點像），兩人很像用上游的差距 0.15；建議的原因只在顯示時改寫，資料庫裡上游的原因不動；現在最像的人跟存好的建議不同時加註，讓過時的建議看得出來 | 轉錄時把分數存進 fork 的表：要在上游 `matchVoiceprints` 之後多 1 行接點，而且聲紋庫一變（刪錯的聲紋、合併人）分數就過時，正好重演使用者遇到的「存好的建議不會更新」。直接改寫資料庫裡的 `suggestion_reason`：上游的待確認、匯出、MCP 都會讀到 fork 的文字，會議語言換了也不會跟著換。成本：每次重讀聲紋的中繼資料、只快取不會變的向量（以 id 為鍵）；2026-11-24 REV-F12 改掉用 count／max(id)／sum(person_id) 當鍵快取整份聲紋庫：分成兩場只改 meeting_id，三個值都不變。辨識聲紋的建議時比對所有會議語言的上游原因（使用者改會議語言後上游不重寫原因）。人物頁另外標三種要確認的樣本（F12.11a：跟本人其他不像、兩份互相不像、跟來源說話者現在的聲音對不上），門檻 0.50／0.65：使用者的聲紋庫 36 份（2026-11-24 AN-vpclean）正常的跟本人最高最低 0.70、跟來源說話者 0.98～1.00，可疑的 ≤ 0.30，0.50 兩邊都有很大的空間；只標「請確認」不自動刪，因為樣本少（7 人有 2 份以上）。「跟別人比跟本人像就標」不做：會被一份錯的樣本拖累，誤標同一人正常的那份 |
| DF13 | 改名防呆擋在上游 `AppModel.renameSpeaker` 開頭（1 行接點），所有使用者取名的路徑都經過它；別人 ≥ 0.88、取的名字既有的 < 0.50（或沒有樣本）才擋；一次好幾位時擋下的集中在一個視窗、選項套用到全部；「只改名」沿用 F2.9 的「只連到人、不存聲紋」（F12，2026-11-24） | 改完才問（在 `remembersVoice` 先不存聲紋、事後再問要不要存）：取消時要把名字、會議紀錄、建議改回去，會多存一版會議紀錄，也清不回被上游清掉的復原。只看別人很像、不看取的名字：同一個人的聲紋本來就可能跟別人 0.88 以上（使用者的資料裡不同的人有 0.85），會常常誤擋。門檻用 0.65／0.88 的差距：沒有實際資料支撐。一位一個視窗：全部套用 5 位時要按 5 次，而且上游的迴圈是同步的，做不到一個接一個問。也擋合併說話者、重新辨識時的重新學習：那時名字是使用者早就確認過的，不是新的取名 |
| DF14 | 聲紋的來源記在 fork 的表 `ma_voiceprint_source`（外鍵指到上游的 `voiceprints`、`ON DELETE CASCADE`），在既有的 `remembersVoice` 接點寫 pending、事後對到聲紋 id；取名的來源由防呆的接點記在記憶體，標記由 F2 的套用記，重新辨識看 `jobs`，其他算合併；待確認回答併進「套用建議」「手動取名」（F12，2026-11-24） | 在上游 `voiceprints` 加欄位：違反 §F-DB.1 第 2 點，降回舊版時 INSERT 沒填也沒關係，但上游以後的 migration 可能重建這張表。在 `INSERT` 之後多 1 行接點拿 id：接點已經用到 100。用觸發器（trigger）在上游的表上：上游重建表時會不見，也是改上游表的行為。以 `meeting_id`、`speaker_idx` 當鍵、不對到 id：分成兩場會改 `meeting_id`，紀錄會對錯。分出「待確認回答」：上游的待確認送出直接呼叫 `renameSpeaker`，要再 1 行接點才分得出來，對判斷聲紋可不可信沒有幫助 |
| DF15 | 重新轉錄時用聲紋對應舊、新說話者（雙向最像、≥ 0.80）沿用名字，對不上的存成建議；存檔後刪掉跟同編號新說話者對不上（< 0.50）的舊聲紋，沿用的使用者取名用新聲音重新學（F12.15，2026-11-24 使用者決定）。偏離上游 `saveTranscript`「照編號沿用、不動聲紋」：重新分群會照出現順序重新編號，同一個編號可能是別人（使用者的 #11：重新轉錄後 Kiki 的編號變成別人，舊聲紋跟新說話者只像 0.20，名字也掛錯）。0.80 的依據：同一場重新轉錄前後同一個聲音 0.88～0.98（#11），使用者的資料裡不同人最高 0.56～0.60（EV-voiceprint、AN-vpclean）；再加雙向最像，避免兩位聲音接近時對錯。只改既有的接點行，不新增接點。對不上的建議、存檔後待處理的結果存在 fork 的表（`ma_retranscribe_suggestion`、`ma_retranscribe_pending`，跟 `saveTranscript` 同一筆交易寫入），用說話者指紋判斷是不是同一批說話者；刪、學、存建議各自一筆交易，pending 到最後才消耗，失敗留著重試（REV-F12c P2-1～P2-3）。重試前每一項核對存檔後預期的名字、來源、人物、聲音雜湊，使用者改過就跳過；編輯會議時兩張表用快照保存、還原，分割照編號複製建議，不再以「聲紋雜湊一定會變」當前提（REV2-F12c）；使用者在 pending 期間自己取名（包括同名「只改名」）就在那筆學習交易裡讓這位的項目失效，不只比四個欄位（REV3-F12c）。高信心自動帶名時保留上游的自動名字、舊名字照樣當建議問（「『Other』是 Old 嗎？」，2026-11-24 使用者決定）：改成預設名稱要動上游 `matchVoiceprints` 的自動帶名，而且聲紋 ≥ 0.88、領先 0.15 本身就是很強的證據，讓使用者在待確認一鍵選擇即可 | 照時間重疊對應（rediarize 的做法）：`saveTranscript` 先刪舊段落才算名字，要在刪之前留一份得多 1 行接點，而且重新轉錄時段落邊界也會變。只刪舊聲紋、名字照編號：名字掛錯時會把錯的人的新聲音學進去，更糟。對不上的名字直接丟掉：使用者自己取的名字會消失，所以存成建議讓使用者一鍵套回。結果放記憶體（第一版）：存檔回滾後殘留、重啟後遺失、刪了舊聲紋卻學失敗就無法重試（REV-F12c） |
| DF16 | 拿掉 app 裡原作者的署名、贊助，改附上游 `LICENSE` 全文；「基於上游」只留在 GitHub Release；fork 停用官網的 workflow（F13，2026-11-25 使用者決定） | 保留「改自 juinwei7 的開源專案拾音」一句、不附 MIT 全文（現況）：使用者不要 app 裡有原作者的字句，而且 MIT 要求散布時附上著作權與許可聲明，一句話不算。在 app 顯示時過濾「基於上游」：要加 Swift 接點，已經裝好的舊版仍會顯示。連 GitHub Release 也拿掉：看不出基於上游哪一版，合併上游時要靠它對照（DF6）。在 GitHub 網頁停用官網：repo 裡看不出來，要使用者操作。改 bundle id、鑰匙圈、資料夾等識別：現有使用者的設定、API key、權限、更新會斷 |
