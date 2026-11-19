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
| F0 共用 | `ForkState.swift`（`ForkAppState`：F2、F4 的畫面狀態）、`Debug/ForkDebug.swift`（DEBUG 指令入口、`augmentState`、`ForkDebugPrompts`） | AppModel 的 `let fork`、DebugControl 的 `default:`、`state` 的 `return out` 前、Notifier 的 `-debugQuietPrompts` |
| F2 說話者標記 | `SpeakerTags/`：`SpeakerTagging`（規則）、`SpeakerTag`（資料表 `speaker_tags`）、`SpeakerTagStore`（`extension AppDatabase`）、`AppModel+SpeakerTags`（`MeetingDetail`、`AppModel` 的 extension）、`SpeakerTagViews`（錄音畫面、會議頁、逐字稿的畫面）、`SpeakerTagsDebug`、`ForkSpeakerTags`（跟著上游的編輯、分割、合併、封包）；`Store/ForkMigrations` | RecordingView、MeetingDetailView、TranscriptTab、JobRunner、AppModel、AppDatabase、MeetingEdits、Package、Exporters、Voiceprints、SpeakerEdits（`forkSaveSpeakerUndo`、`forkAddSpeaker`：轉呼叫 private 的 `saveSpeakerUndo`、`addSpeaker`） |
| F3 靜音 | `Mute/`：`MicMute`（`ForkMute`、`extension Recorder/GlobalHotKey/AppSettings/AppModel`）、`MuteViews`、`MuteDebug`、`ForkMuteSettingsRow`、`ForkIslandMute` | Recorder、RecordingWriter（`muted`、`setMuted`、混音，跟寫檔的鎖綁在一起，留在原檔）、GlobalHotKey、AppModel、RecordingView、MenuBar、ShiyinApp、SettingsView、IslandView、RecordingIsland、DebugControl 的 `hotkey mute` |
| F4 條列頁 | `Notes/`：`NotesListViews`（`ForkNotesList` 整個條列模式、`ForkNotesSection`、`NoteRow`、`TopicBlock`、`TopicChips`、`ForkActionItemsTable`、`FlowLayout`）、`NotesModel`（`NotesSectionScope`、`plainSection`、`topicSegments`、顏色、`AppModel` 的議題狀態、播放條的 `forkTrackTopic`）、`NotesDebug` | NotesTabs（條列模式換成 `ForkNotesList`；`ItemList` 的符號、`NoteRow`）、PlayerBar、AppModel、MindMap（`clean`、`shownTopics` 改 internal） |
| F7 品牌 | `Brand.swift` | ShiyinApp、ReleaseNotes、Reminders、IslandView、`build-app.sh`、`make-dmg.sh`、`make-update-fixtures.sh` |
| DF5 | `DF5/LockedValue.swift` | AudioSources 的 `MicrophoneSource`、`FileSource`（`deviceUID`、`current` 用 `LockedValue` 存，7 行） |

- 跟上游元件長得一樣的 fork 複本（上游改了原本的，複本不會跟著變；manifest 的 `highRisk` 有列，監看要比對）：`ForkTaggedSpeakerName`（上游 `AutoSpeakerName`，多了「標記」）、`ForkSubduedTimeButton`（`TimeButton`，平常淡色）、`ForkNotesSection`（`NotesSection`，條數、色條、複製鈕）、`ForkActionItemsTable`（`ActionItemsTable`，fork 的欄位順序）。上游的原元件不動，人物頁照用上游的 `NotesSection`。

### F0.3 接點的規則與檢查（`scripts/fork/isolation-check.py`）

- **接點的範圍就是那一行**：上游檔加的每一行，同一行要有 `MA-FORK(F#)`（`F#` 是 manifest 的功能：F0、F1、F2、F3、F4、F7、DF5）。一個接點要多行時寫成多個標了記號的行，或把內容搬進 Fork/ 只留一行呼叫。
- 改掉、拿掉上游的行：同一處（同一個 diff hunk）一定要有加上的接點行，等於「這幾行換成接點」；只刪不加的不行。例如 NotesPage 的條列模式整段換成 1 行 `ForkNotesList(…)`、RecordingView 即時逐字稿的一行換成 `LiveLineRow(…)`。
- 上游的檔被搬走、改名、換類型（例如換成連結）都算拿掉上游的檔：比對時不偵測改名（`git diff --no-renames`，改名會變成刪掉舊的、加新的），舊路徑一定會被檢查到。
- 檢查的範圍：上游 tag（manifest 的 `upstream.base.tag`，現在是 v5.0.0）裡就有的 `Sources/**/*.swift`、`Package.swift`（程式）和 `scripts/` 底下的 `.sh`、`.swift`（腳本）。程式加的行數合計不超過 `rules.upstreamLineBudget`（100）；腳本另外算。不檢查：文件、README、CLAUDE.md、翻譯表、Info.plist、圖示、`.github`（品牌由 `brand.py` 管，§F7.4；版本號照 DF6）。
- manifest 要對得上：每個功能的 `forkFiles`、`upstreamFiles` 存在；`symbols` 找得到宣告；`markers`（`file`、`line`、`hook`＝那一行去掉接點註解）跟程式裡實際的接點一致，多的、少的都算錯，只有行號不同時提示用 `--write` 更新。
- 跑法：`python3 scripts/fork/isolation-check.py`（exit 1 表示有問題，列出每一處）；新增、搬動接點後 `--write` 重寫 manifest 的 `markers`、`upstreamFiles`，再跑一次不加參數的。目前的檔數、行數看檢查的輸出（「上游程式 N 個檔、M 行」），這裡不寫固定的數字（會過期）。`python3 scripts/fork/isolation-check-test.py` 是檢查本身的回歸測試（未標記的修改、已 stage 和已 commit 的改名、刪檔、換類型都要失敗）。兩支都串在 `scripts/fork/check.sh`（§F0.4）。

### F0.4 回歸檢查（`scripts/fork/check.sh`，PLAN-fork-5.0 §8.1、階段 3a）

合併上游、改 fork 功能之後，一個指令跑完 PLAN §8.1 的回歸清單裡能自動化的項目（1～12），輸出 markdown 摘要。

**用法**

```bash
scripts/fork/check.sh                 # 完整：建置、DEBUG 版實際操作（約 15～25 分鐘，第一次要建基準版更久）
scripts/fork/check.sh --quick         # 只跑靜態的（不建 app、不開 DEBUG 版，約 1～2 分鐘）
scripts/fork/check.sh --base-app <舊版.app>   # 品牌逐鍵比對的基準（預設：HEAD 之前最近的 fork tag 的 release 建置，見下）
scripts/fork/check.sh --base-ref v5.0.1        # 基準改用這個 tag 建
scripts/fork/check.sh --only 3,5,7    # 只跑這幾項（1、2、11 這類自己會建需要的東西）
scripts/fork/check.sh --out <資料夾>  # 摘要、log、截圖放這裡（預設 $TMPDIR/shiyin-check-<時間>）
scripts/fork/check.sh --keep          # 留下這次的 app、暫存 SHIYIN_HOME（除錯用）
scripts/fork/check.sh --clean-cache   # 結束時連建置快取、基準版也刪掉
```

exit 0：沒有 FAIL（SKIP、需人工不算失敗）；1：有 FAIL；2：沒開始（使用者正在錄音、有別的 DEBUG 版在跑、參數錯）。摘要是輸出資料夾的 `summary.md`，最後也印在終端機。每一項一列：狀態（PASS／FAIL／SKIP／需人工）、耗時、證據路徑（log、JSON、截圖），細項寫在下面。

**項目**（編號照 PLAN §8.1；`--quick` 只跑標 Q 的）

| # | 項目 | 做法 |
|---|---|---|
| 1 | 編譯 | `swift build -c debug`；release、DEBUG 版用 `build-app.sh` 的複本建到這次的暫存資料夾（只換 `SCRATCH`、`APP` 兩行，其他照 repo 的腳本） |
| 2 | migration | `scripts/dev/check-fork-migrations.py --scratch-path <check 的建置快取>` |
| 3 | 品牌 | Q：`brand.py check-sources`、`brand-test.py`；完整：`brand.py check` release 和 DEBUG 版、`brand.py compare <基準> <release>`（有差異是「需人工」，差異清單在證據；新版本本來就可能多字串） |
| 4 | F1 | Q：repo 的 `Resources/AppIcon.icns` sha256 等於 manifest `F1.iconSha256`、`Info.plist` 的 `ShiyinIssuesURL` 等於 manifest、`BrandAboutCommand()   // MA-FORK(F7)` 和 ReleaseNotes 的 F7 接點在、`brand-hooks-test`（更新說明選段落）；完整：建好的 app 的 icns、`ShiyinIssuesURL` 也一樣；更新網址（CI 的 `vars.SHIYIN_UPDATE_URL`）用 `gh variable get` 讀得到時要指到 fork（`EdenQ/Shiyin`），讀不到是 SKIP |
| 5 | F2 標記 | `record-sim` 中 `tagspeaker now 甲`、停止：`speaker_tags` 有這一筆、時間在送出指令時的 elapsed 附近；`f2-atomic-check.py`（套用：說話者 1 變「甲」、說話者 2 有乙又有丙不套用；「只改這句」的交易、復原） |
| 6 | F2 加上 5.0 | 兩場示範會議加標記：`editmeeting` 裁頭尾、刪中間、分割、合併，標記跟著平移、分到新會議、合併後加上偏移；每次 `restoreedit` 都回到原本；`.shiyin` 封包帶標記、匯入回來一樣，舊封包沒有標記也能匯入 |
| 7 | F3 靜音 | `f3-mute-check.py`（狀態、⌃⌥⌘M、錄音檔兩聲道、靜音那段麥克風是 0）；靜音中 `recordstall 32 1`：20 秒左右 `muteHint` 出現、`micmute dismiss` 收掉；windowshot 主畫面（提示列）放證據，「需人工」看一眼 |
| 8 | F3 加上 5.0 | 靜音中 `levelCheck` 沒有收音提示；選單列圖示是 `mic.slash.circle.fill`；`hotkey.muteRegistered` 錄音中是 true、停止後 false；設定「錄音」頁 `preview settings recording` 加 `mawindowshot`（需人工） |
| 9 | F4 | `scripts/dev/f4-check.py`；示範會議的紀錄分頁 windowshot（繁中、英文，需人工；還沒有基準圖，不做像素比對） |
| 10 | F4 加上 5.0 | `noteitem delete decisions 0` 之後 `copysection` 少一條、其他條照舊；windowshot（需人工看條數、色條、「加到提醒事項」） |
| 11 | DF5 | Q：`scripts/fork/tsan-lockedvalue/run.sh` |
| 12 | 設定殘留 | Q：開始、結束各 `defaults export com.weiwei.shiyin`，要逐位元組相同（不同時列出哪幾個鍵；檢查不自己改回，免得蓋掉使用者同時改的設定） |
| 13 | 實機更新 | 不自動：列為「需人工」（4.7.6 → 新版的 app 內更新，開舊會議看標記、靜音、條列頁） |

另外 Q 一定跑：`isolation-check.py`、`isolation-check-test.py`（§F0.3）、`l10n.py check`（跑之前存一份翻譯表，跑完翻譯表有變就算 FAIL 並放回原本的內容：檢查不該改到 repo）。這三項在摘要列在 #3 之後（編號 I1、I2、L）。

**安全規則**（CLAUDE.md「驗證時要注意」）

- 開始前看 `~/Library/Application Support/Shiyin/audio/recording/`：有檔案就停（exit 2）。有別的 DEBUG 版在跑也停（`shiyinctl` 是廣播）；檢查中同時只開自己的一個 DEBUG 版。
- 建置：`build-app.sh` 的複本，`APP` 在這次的暫存資料夾（`~/Library/Caches/ShiyinBuild/check/run-<時間>/`），`SCRATCH` 是 check 自己的建置快取 `~/Library/Caches/ShiyinBuild/check/scratch`；不碰 `~/Library/Caches/ShiyinBuild/app`（使用者可能拿它錄音）、不跑 `--install`。`shiyinctl` 也編到暫存資料夾。
- DEBUG 版：暫存 `SHIYIN_HOME`，`open -g -n --env SHIYIN_HOME=…`，參數 `-ApplePersistenceIgnoreState YES -llmProvider none -autoSummarize NO -correctTranscript NO -debugQuietPrompts YES -recordingIsland NO -mcpEnabled NO -autoCheckUpdates NO -muteHotKey YES`（設定只在這次執行有效）；啟動後用 `lsof` 確認開的是暫存的資料庫，開到正式資料庫就結束 app、FAIL。錄音島關掉：上游 5.0 的 DEBUG `state` 在島出現時寫不出 JSON。結束用 `kill`（TERM，10 秒後 KILL），不用 `quit`：正常結束會把視窗位置寫進共用設定。
- 不送按鍵、不用 System Events、不用 AX：畫面一律 `windowshot`、`mawindowshot`（app 自己畫）。
- 結束（含失敗、Ctrl-C）時結束自己的 DEBUG 版、刪掉這次的暫存資料夾（app、home、`shiyinctl`）；輸出資料夾留著（摘要和證據）。建置快取和基準版留著給下次用（`--clean-cache` 才刪）。

**品牌比對的基準**：`--base-app` 沒給時，用 `git describe --tags --abbrev=0 --match 'v[0-9]*' HEAD^` 找到的 fork tag（現在是 v5.0.1），`git archive` 那個 tag 到暫存資料夾、用它自己的 `build-app.sh`（同樣的複本規則）建 release，放在 `~/Library/Caches/ShiyinBuild/check/base/<tag>/`，之後直接用。用同一台電腦、同一版 Xcode 建，`xcstringstool` 的版本差異不會變成假的差異（F7.5 跟 GitHub 上的 4.7.6 比時就多了 3 條）。

**怎麼確定檢查會抓到問題**（PLAN 階段 3a 的驗收）：在暫存 worktree 故意弄壞、不 commit，跑對應的項目要 FAIL、整體 exit 1，例如拿掉一個 `MA-FORK` 接點（I1）、原始碼加一句不查表的品牌字（#3）、讓「只改這句」不在同一筆交易或標記不套用（#5）。結果寫在 commit 訊息。

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
- `tagspeaker only <會議 id> <標記 id>`：等於按沒套用的標記的「只改這句」（F2.12）。
- `addparticipant <會議 id> <名字>`：等於在 ＋ 按「加入」。
- `tagui add`、`tagui name <第幾行>`：等於按 ＋、一行選單裡的「其他名字…」，打開輸入名字的彈出視窗；接著用 `typefield 名字 <名字>`、`submitfield 名字` 送出（走表單的送出路徑）。這台電腦沒有輔助使用權限時用這個代替 AX。
- `applytags <會議 id>`：等於重新轉錄存檔後那幾步（`tag` 的名字先回到預設，再套用標記、學聲紋，然後聲紋比對）。
- `speakertags <會議 id> <輸出.json>`：每個標記和它對上的說話者、重疊比例、逐字稿上的位置、是不是沒套用；說話者的名字、來源、連到的人。
- `state` 的 `recorder.liveTags`：即時逐字稿每一行的名字（沒有是空字串）。
- `windowshot <輸出.png> [main|popover]`：app 自己把主視窗（或彈出視窗）畫成圖片（`cacheDisplay`），不需要螢幕錄製權限；畫的是視窗裡真正的元件，選單也是畫面上的樣子（`snapshot` 畫不出 ScrollView 和選單）。
- `-debugQuietPrompts YES` 也不發通知：測試版跟使用者的拾音是同一個 bundle ID，通知權限還沒決定時轉錄完會跳出系統的詢問。

### F2.6 驗證

- 比對規則：`SpeakerTagging` 用小程式單獨測（同名、不同名、不明確、沒人說話、同名兩位）。資料庫：測試用的 `SHIYIN_HOME` 建一場有說話者的會議（直接寫段落），`tagspeaker add`＋`applytags` 跑一遍，加上手動改過名字的說話者不覆蓋、聲紋有存、`tag` 的名字在重新套用時會重算。
- 「只改這句」的交易（DF8）：`python3 scripts/fork/f2-atomic-check.py <SHIYIN_HOME> <shiyinctl> --out <資料夾>`（DEBUG 版先用那個 home 開著）：SQLite trigger 只擋「改名成丙」，按「只改這句」後說話者、句子、復原快照要跟按之前完全相同；拿掉 trigger 再按一次、再復原，輸出可以跟別的版本逐位元組比。
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
- 全域快捷鍵 ⌃⌥⌘M（`GlobalHotKey` 第 3 組）：跟標記重點一樣只在錄音中註冊，而且只在 `both` 的錄音（`onStarted` 時看 `AppSettings.muteHotKey`），停止時取消註冊。按了切換，靜音播「Bottle」、打開播「Pop」（標記重點是「Tink」），人在 Teams 裡也知道按到了。
- 設定「錄音與轉錄 → 提醒與快捷鍵」多一個開關：「錄音中按 ⌃⌥⌘M 靜音或打開麥克風（麥克風＋電腦聲音的錄音）」，`muteHotKey`，預設開。

### F3.4 DEBUG

- `micmute on|off|toggle`：等於按錄音畫面的麥克風圖示；`micmute dismiss`：提示列的「知道了」。
- `hotkey mute`：模擬按下 ⌃⌥⌘M。
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
- `phrases`：整句的特例（`from`、`to`、`required`），先換、不再被名稱對照影響：「「拾音」選單」→「「MA」選單」（應用程式選單叫 MA，F1.1）、`/Applications/Shiyin.app` → 加引號的 `Meeting Assistant.app`、第三方授權的開場白、Credits 的贊助說明（「會議助手改自 juinwei7 的開源專案拾音 Shiyin…請原作者喝杯咖啡」）。`required` 依資源指定哪些整句一定要命中（相對 `Contents/Resources` 的檔案，`guide:` 開頭是安裝說明）：換完的資源裡看不到 `to` 就失敗。上游改了句子（連一個標點）時，整句對不到，一般的名稱替換會把句子換成「Enjoying Meeting Assistant?」、署名消失，殘留檢查看不出來，所以要靠 `required`（2026-11-18 審查 P2-2）。檢查的是輸出有沒有 `to`，對換過的產物重跑結果不變。
- `keep`：不換的片段（正規表示式，F7.2）。`Shiyin(?=[A-Z])` 是 `ShiyinIssuesURL` 這類鍵名、識別。

### F7.2 建置時替換（`scripts/fork/brand.py apply <app>`）

`build-app.sh` 在組好 app、簽章之前呼叫（`--debug` 同一條路），只改 `$APP` 裡的檔案，repo 不變：

- 各 `.lproj` 的 `Localizable.strings`、`.stringsdict`（xcstringstool 編出來的 XML plist）：只換值、鍵不動。繁中是翻譯表的來源語言，編出來的繁中檔也有全部的鍵（值等於鍵），所以換值就夠，不用另外寫明確的繁中值。
- `InfoPlist.strings`：鍵也換（鍵是 Info.plist 的英文值，例如 `Shiyin Meeting`）；`CFBundleName`、`CFBundleDisplayName` 直接設成 `brand.json` 的值。
- `Info.plist`：`CFBundleName` = MA、`CFBundleDisplayName` = Meeting Assistant；`infoPlistBrandKeys`（檔案類型名稱、權限說明）換名稱；識別（執行檔、bundle id、URL scheme、UTType）不動。另外寫入 `MABrand`（名稱對照、`aboutName`），給 §F7.3 的接點讀。
- `Credits.html`、`ThirdPartyLicenses.txt`：用 `phrases` 換開場白和贊助說明。`build-app.sh` 產生 Credits 的程式照上游原樣。
- 每一條換過的字串比對格式碼（`%@`、`%lld`、`%1$@`…）的種類和數量，不同就失敗（名稱裡不會有格式碼，這是防 `brand.json` 寫錯）。
- `make-dmg.sh`：`brand.py guides` 把兩份安裝說明換好放到暫存資料夾再轉 PDF；DMG 裡的第三方授權改拿 app 裡換過的那份。
- 驗證基準：`brand.py compare <上一版.app> <新.app>` 逐鍵比對各 `.lproj`、Info.plist（版本號除外）、Credits、第三方授權；舊版的鍵是 fork 寫死的「會議助手」時，先還原成上游的鍵再找。

### F7.3 不經過翻譯表的接點（`Sources/Shiyin/Fork/Brand.swift`）

`Brand` 讀 Info.plist 的 `MABrand`；沒有（`swift build` 直接跑、上游原樣）時回傳上游名稱。上游檔裡的接點各 1 行，標 `// MA-FORK(F7)`：

- 「關於 MA」：`AppCommands` 裡放 `BrandAboutCommand()`，取代系統的 `.appInfo`，`orderFrontStandardAboutPanel(options: [.applicationName: Brand.aboutName])`（F1.3）。
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
| §12.1 更新網址 | GitHub 的 repository variable `SHIYIN_UPDATE_URL` 設成 `https://github.com/EdenQ/Shiyin/releases/latest/download/shiyin-update.json`（fork 的更新來源，**不可指回上游**）。Release 的說明文字照 DF6 加「- 基於上游 拾音 X.Y.Z」 |
| §12.1 Credits | 贊助說明、授權開場白在建置時換成「會議助手改自 juinwei7 的開源專案拾音 Shiyin…請原作者喝杯咖啡」（§F7.1），`build-app.sh` 產生 Credits 的程式照上游 |
| §21.9 回報問題 | Info.plist 的 `ShiyinIssuesURL` 設成 `https://github.com/EdenQ/Shiyin/issues`（F1.5）；程式裡的預設常數保留上游的值，減少合併衝突 |
| §38.5 文字大小 | 錄音中說話者標記（F2）的名字、時間欄位與未定稿文字的空白欄一起依 `textScale` 縮放 |
| §43 議題時間軸、D145 | fork 的議題帶改用 `MindMap.topicSegments`（依每條重點的時間切段，同一個議題可以有好幾段），點了在紀錄分頁也捲到那個議題（§F4.2、§F4.3、DF4）。上游的 `topicRanges` 和它的標準答案不變 |
| §44 本地 MCP | 給 AI 工具的英文訊息、`serverInfo` 照上游寫 Shiyin，不換品牌（F7.3）；設定頁和錯誤訊息這些查翻譯表的文字建置時換成會議助手 |
| §49、§50（R73、R74） | 4.7.6 帶入上游 4.8.1 的寫法（F6）。§49.2、R73.6、R74.6 的 Windows 部分 fork 不做 |
| §50.2 重新連接在背景 | fork 補的同步規則（DF5）：音源上會被兩個執行緒碰到的值都用 `LockedValue`（`NSLock`，每次讀寫只短暫拿鎖）存。`MicrophoneInput.deviceUID`：換麥克風時主執行緒寫、`deviceQueue` 上的 `start()` 讀；`current`（正在收音的裝置）：`start()` 在背景寫、主執行緒更新畫面時讀。`MicrophoneSource`、`FileSource` 一樣。不用 `deviceQueue.sync` 包住換麥克風：那會等整個重新連接做完，畫面又卡住（R74.4）。`start()` 一開始讀一次 UID 當這次的快照，中途換了就由 `restartAgain` 再做一次。`LockedValue` 的類別在 `Fork/DF5/LockedValue.swift`，用到的地方留在上游的 AudioSources、標 `MA-FORK(DF5)`。驗證：`LockedValue` 原樣放進不碰硬體的 ThreadSanitizer 小程式（`scripts/fork/tsan-lockedvalue/run.sh`），背景一直 `start()`、主執行緒一直換 UID、讀 current，沒有資料競態；改回普通屬性時 TSan 報告競態。上游的同一段沒有加鎖（上游仍有這個競態），上游哪天自己加鎖時刪掉 fork 的 |
| 上游 5.0 的錄音島（R81、§57） | 靜音中（F3.7）：收起時紅點換成劃掉的麥克風（有提醒時琥珀色）；滑過去在音量下面寫「麥克風靜音中」加「打開麥克風」；靜音中好像有人說話的提醒（F3.4）跟錄音畫面的提示列一樣出現在島上，順序同提示列（沒人說話 → 靜音中好像有人說話 → 藍牙 → 收音）。`Fork/Mute/ForkIslandMute.swift` |
| 上游 5.0 的收音檢查（R75、§51.1） | 靜音中不做麥克風的提醒（F3.5），但上游新的「錄不到電腦聲音」（系統音訊權限被拒）照樣提示：`checkLevels` 在 `checkSystemPermission` 和 `guard hasMic` 之後 1 行接點 |
| 上游 5.0 的選單列圖示（`hint.symbol`） | 上游的收音提醒圖示優先，再來是 F3 的「忘了打開」提醒（`mic.badge.xmark`）、靜音中（`mic.slash.circle.fill`） |
| 上游 5.0 的設定十一頁（R108） | F3 的「錄音中按 ⌃⌥⌘M 靜音」開關放在「錄音」頁的「提醒與快捷鍵」最後（`Fork/Mute/ForkMuteSettingsRow`） |
| 上游 5.0 的會議頁上方（R84）、彈窗（R106） | `speakerChip` 的來源是 `tag` 時用 fork 的 `ForkTaggedSpeakerName`（上游 `AutoSpeakerName` 的複本，後面標「標記」，§F0.2）；說話者名字彈窗的「從錄音時的標記帶入」說明和「不是他」照舊（F2.9） |
| 上游 5.0 的就地編輯（R100）、加到提醒事項（R76） | 條列模式整頁是 fork 的 `ForkNotesList`（§F0.2）；段落用 `ForkNotesSection`：fork 的條數、色條、複製鈕加上上游的 `accessory`（「待辦」的「加到提醒事項」放在複製鈕後面）；條目在編輯中用上游的 `NoteItemEditor`，其他時候用 fork 的 `NoteRow`，接上 `noteItemActions`（右鍵、⋯），可以就地編輯的條目不設成可選取；待辦表（`ForkActionItemsTable`）保留 fork 的欄位順序（負責人、期限、事項、時間點），負責人加上游的頭像，事項接上就地編輯和提醒事項的勾。上游的 `NotesSection`、`ActionItemsTable` 不動 |
| 上游 R70 拆句、`addSpeaker()` | F2.12「只改這句」在 fork 的 `AppDatabase.reassignSegments(…naming:…)` 用一筆 `pool.write` 照 5.0.1 的順序做完：上游的 `saveSpeakerUndo`（復原快照）、`addSpeaker()`（新增說話者）、`ForkSpeakerTags.nameNewSpeaker`（標記的名字）、改句子的說話者、上游的 `removeEmptySpeakers`；任何一步失敗整筆回復（DF8）。上游 private 的 `saveSpeakerUndo`、`addSpeaker` 由 SpeakerEdits 裡各 1 行接點 `forkSaveSpeakerUndo`、`forkAddSpeaker` 轉呼叫（`saveSpeakerUndo` 的參數用到 private 的 `SpeakerSnapshot`，不能直接改 internal；只加行、不改上游的行）；上游的函式不改簽章 |
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
| DF6 | 版本號規則：build 號從 31 起單調遞增、不跟上游；合併上游 X.Y.Z 的那一版是 X.Y.(Z+1)，比 fork 目前的版本小時取 fork 的 patch + 1；fork 自己的發布只加 patch；說明文字第一行後面加「- 基於上游 拾音 X.Y.Z」（PLAN-fork-5.0 §2.3，2026-11-18 使用者同意） | 照上游的版本號：fork 自己的修正沒有號碼可用，跟上游同號會讓使用者以為是同一版。另外一套版本號（例如 1.0 起）：看不出基於上游哪一版，`Updater.isNewer` 只比數字，從 4.7.6 換到 1.0 使用者就收不到更新。這個規則永遠往上，app 內更新照常 |
| DF7 | 品牌在建置時換建好的 app（`brand.py apply`），原始碼、翻譯表、Info.plist 照上游寫（F7，2026-11-18） | 原始碼直接寫「會議助手」（4.7.6 以前）：每次合併上游，32 個 Swift 檔、翻譯表 89 個鍵、Info.plist、安裝說明都衝突，而且上游新加的字串一定是「拾音」，要人工找。在建置前換一份翻譯表再編（PLAN 的原案）：繁中是來源語言，要另外寫明確的繁中值，還要處理鍵；編出來的繁中 `.strings` 本來就有全部的鍵，直接換值比較簡單，也能一起處理 `.stringsdict`、InfoPlist.strings。Swift 裡用 `Brand.name(...)` 包每一處：還是會衝突。代價：有幾處不經過翻譯表（關於、更新說明、5.0 的提醒事項）要留 1 行接點，原始碼掃描擋住上游新增的。防護要嚴：原始碼掃描只認包住字串的最內層查表呼叫，不看附近幾行；整句特例依資源規定一定要命中，不能只看有沒有殘留的「拾音」（2026-11-18 審查 P2-1、P2-2）。原始碼掃描只放行能證明會查表的參數寫法（單一常值、兩邊都是常值的三元運算），其他保守報錯；正確性用 Swift 編譯器的 `-emit-localized-strings` 依位置核對（`brand.py crosscheck`），不在每次建置都跑編譯器：那要改上游的 `swift build` 那行或多編一次整個模組（複審 P2-3） |
| DF8 | fork 功能隔離到 `Sources/Shiyin/Fork/`，上游檔只留標了 `MA-FORK` 的單行接點（PLAN-fork-5.0 階段 2，2026-11-19）：狀態放 fork 自己的物件（`ForkAppState`、`MeetingDetail.forkTags`、`ForkMute.State`），要用的上游 `private` 成員改 internal 並標成接點，條列模式整頁、`AutoSpeakerName` 這種整塊改過的畫面用 fork 的複本；「只改這句」在 fork 的函式裡用一筆交易重用上游的 `saveSpeakerUndo`、`addSpeaker`、`removeEmptySpeakers`（兩個 private 的由 SpeakerEdits 裡各 1 行轉呼叫的接點 `forkSaveSpeakerUndo`、`forkAddSpeaker` 開出來），改句子說話者的那幾行是 fork 的複本（跟上游 `reassignSegments` 的迴圈相同）；不改成先呼叫上游的 `reassignSegments` 再另開一筆改名：第二筆失敗時第一筆已經存了（多出一位預設名稱的說話者、句子已改、留下復原快照），跟 5.0.1 的整筆回復不同（REVIEW-2 P2-1，`scripts/fork/f2-atomic-check.py` 用 SQLite trigger 讓改名失敗來檢查）；標記的名字存不存聲紋改由 `learnVoiceprint` 裡 1 行接點問 `ForkSpeakerTags.remembersVoice`；`LockedValue` 類別搬到 `Fork/DF5`；用 `isolation-check.py` 檢查（§F0.3） | 照舊在上游的函式加參數（`reassignSegments(name:)`、`learnVoiceprint(remember:)`）：改了上游函式的簽章，上游改同一個函式就衝突（§F0.1 第 4 點）。在上游元件加參數（`NotesSection` 的 count、accent、copy，`TimeButton` 的 subdued）：上游 5.0 就地編輯時已經衝突過一次，複本的代價是上游改原元件時要人工比對（manifest `highRisk`）。把上游的條列模式留著、fork 的另開一頁：同一份內容兩份程式，使用者看到的仍是 fork 的，上游的那份只是佔位。「只改這句」第二筆失敗時再補做復原：補做本身也可能失敗，中間別的寫入看得到改了一半的資料，不是原子性。接點的範圍用「開始、結束」兩個記號包住一段：可以包很長一段，失去「上游檔只留接點」的意思，行數也看不出來 |
