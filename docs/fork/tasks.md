# 會議助手（fork）：任務

> 只放 fork 還沒完成的任務；做完就刪掉（紀錄在 git 歷史）。上游的任務在 `docs/tasks.md`，照上游原樣、fork 不改；
> 上游任務在 fork 這邊的實測狀態寫在這裡。需求在 `docs/fork/requirements.md`，設計在 `docs/fork/design.md`。
> 規則同 CLAUDE.md：每項都有驗證方式；`[~]` 是程式完成、還差要使用者的驗證。「design §F#」指 fork design，「design §數字」「D#」「R#」指上游文件。

## 合併上游 5.0（PLAN-fork-5.0 階段 1，發布 5.0.1／build 31）

- [ ] **M1 接回上游歷史並合併**：照 `docs/fork/upstream-sync.md` §2：內部先合 4.8.1、再合 5.0.0；版本照 DF6 改成 5.0.1（build 31）
  - 驗證：`git merge-base HEAD refs/upstream-tags/v5.0.0` 是 v5.0.0 那個 commit；`brand.py check-sources`、`l10n.py check`、`swift build` 通過；跟 5.0.0 比，上游三份文件 `docs/requirements.md`、`design.md`、`tasks.md` 沒有差異
- [ ] **M2 fork 的 migration 搬到上游的後面**（design §F-DB.1 第 3 點）：`ForkMigrations.register(&migrator)` 在上游最後一個 migration 之後
  - 驗證：`scripts/dev/check-fork-migrations.py` 跟著 5.0 改（`ChineseScript`、`AppSettings` 的替身），全新、v7、Fork v8、上游 v8～v15、fork 4.7.6 的資料庫升級、重新開啟、降回 4.7.6 再打開都通過
- [ ] **M3 標記跟著上游的編輯、分割、合併**（F2.13，design §F-DB.2）
  - 驗證：DEBUG 版 `record-sim`＋`tagspeaker add` 放標記，跑 `editmeeting`、`restoreedit`、`splitmeeting` 和合併，用 `speakertags <id> <out.json>` 比對時間
- [ ] **M4 封包帶標記**（F2.8，design §F-DB.3）
  - 驗證：帶標記的會議匯出再匯入，`speakertags` 相同；4.7.6 匯出的舊封包照常匯入；上游 5.0 的 app 匯入帶標記的封包成功
- [ ] **M5 錄音島顯示靜音**（F3.7）：上游 5.0 的錄音島（R81）在麥克風靜音時寫「麥克風靜音中」
  - 驗證：DEBUG 版模擬錄音中 `mute`，`windowshot` 錄音島中英文
- [ ] **M6 提醒事項列表的品牌接點**（F7.5，design §F7.3）：`Reminders.listTitle` 包 `Brand.name(…)`、`EventKitReminders.list()` 用 `Brand.isListTitle`
  - 驗證：`brand-hooks-test`；真的提醒事項：有舊名「拾音」列表時沿用、沒有時建立「會議助手」（要使用者同意提醒事項權限）
- [ ] **M7 F2、F3、F4 接到 5.0 的新畫面**（會議頁上方、設定十一頁、就地編輯）
  - 驗證：PLAN-fork-5.0 §8.1 的回歸清單全部通過

## 上游 R74 在 fork 的實測（design §50、D159、D160；fork 4.7.6 帶入，F6）

- [~] **RC1 Mac**（§50.1～§50.3）：程式完成；fork 4.7.6 用 DEBUG 版 `record-sim`＋`recordflap 6 3` 驗過（2026-11-16，見版本 commit）：麥克風重新連接 7 次、間隔 3.9、3.8、5.6、7.6、11.6、19.5 秒，第 3 次起提示「麥克風一直在重新連接」、60 秒後收起，`maxMainGapMs` 104 ms；F3 靜音中遇到重新連接時兩種提示同時出現（windowshot）。還差（要使用者在電腦前：DEBUG 版用真的麥克風可能跳出權限確認）：內建麥克風錄音、錄音中從麥克風名稱換到別的麥克風再換回來，錄音照常、log 沒有 `microphone engine exception`
- [ ] **RC3 真的 AirPods**：回報的人（GitHub #8）提供當機報告、更新後再試；或使用者用 AirPods 錄一段

## 上游 R57 在 fork 的實測（design §45、D151；fork 4.7.6 帶入，F6）

- [~] **R57 Mac 實作**（R57.1～R57.5，design §45）：程式完成，用 `record-sim` 驗過（2026-11-12，見 commit 訊息）。還差（要使用者在電腦前，會用到麥克風）：
  - 真的語音處理：DEBUG 版用內建麥克風錄音時跑 `scripts/dev/vpio-hold.swift`，10 秒內出現提示；關掉後提示收起
  - 用 Safari 開 Google Meet 時提示寫的是 Safari（Safari 的網頁由 `com.apple.WebKit.GPU` 收音是照 GitHub #4 的 log 寫的，還沒在這台電腦看過 Core Audio 回報的 bundle ID；不是的話「偵測到線上會議」對 Safari 也不會提醒，要一起改 `MeetingDetector.known`）

## 系統預設麥克風的名稱、藍牙提醒（上游 54bc6f5，design §38.1；fork 4.7.6 帶入）

- [~] **DM1 真的麥克風**：程式完成、能編譯；模擬錄音不走這條路，沒有驗證。還差（要使用者在電腦前，會用到麥克風）：麥克風選「系統預設」錄幾秒，錄音畫面的麥克風名稱是真的裝置名稱（不是 `CADefaultDeviceAggregate-…`）、錄音中的麥克風清單沒有多一項；AirPods 當系統預設時，錄現場會議出現藍牙耳機的提醒（R58.3）

## App 圖示換成使用者的貓（F1.6，design §F1；2026-11-12 使用者從草稿選定）

只做 Mac；`windows/` 不動。

- [~] **IC1 看實際效果**（F1.6）：`Resources/AppIcon-1024.png` → `make-icon-from-png.sh` 產生 `AppIcon.icns`，`iconutil -c iconset` 反解 10 張尺寸正確；`docs/images/icon.png`、favicon、apple-touch-icon 已換。還差：
  - 建置後使用者在 Finder、Dock、「關於 MA」、DMG 看 16～1024 各尺寸（macOS 的圖示快取可能要重新登入或 `killall Dock` 才換）
  - 官網分享預覽圖 `site/public/og*.png` 還是舊圖示：`site/make-images.sh` 要用 Chrome 截圖，等使用者在電腦前再跑

## 紀錄條列頁的閱讀與複製（F4，design §F4、DF4；2026-11-10 使用者看過預覽後確認）

只做 Mac；`windows/`、`shared/golden/`、`MindMap.topicRanges` 不動。測試用另外的 `SHIYIN_HOME` 和另外的建置資料夾（使用者用 build cache 的 app 錄音）。

- [~] **NL 真的畫面上操作**（F4.1～F4.11）：程式完成；`f4-check.py`（議題切段的所有案例、中英日分段複製）和畫面的 `windowshot` 已驗過（見各 commit 訊息）。這台電腦沒有給 Claude 輔助使用和螢幕錄製的權限
  - 待使用者：滑過條目時時間點變綠、滑過段落標題出現複製按鈕；按「複製這一段」「複製這個議題」後貼到別的 app；點議題帶的色塊（在紀錄分頁會捲動、在逐字稿分頁只播放）；點膠囊、議題列（箭頭、標題）、全部展開／收合，點議題列裡的時間、「？」、複製按鈕時不會收合；播放中目前議題換了時標示跟著換；英文介面看一次

## 錄音中靜音麥克風（F3，design §F3；2026-11-03 使用者已確認做法）

- [~] **MU1 真的線上＋實體會議**（F3.1～F3.4，要使用者）：程式完成、模擬錄音驗過（見 commit 訊息）。還差：真的麥克風＋Teams 的錄音中，按錄音畫面的麥克風圖示、選單列的「靜音麥克風」、⇧⌘M、在 Teams 裡按 ⌃⌥⌘M（聽得到聲音、選單列圖示變成靜音），錄完逐字稿裡沒有靜音那段的現場對話、Teams 的話都在；靜音中 Teams 沒人說話、現場有人說話約 20 秒時出現提示（不在前景時送通知）；英文介面看一次

## 錄音中標記說話者（F2，fork design §F2；2026-10-22 使用者已確認做法）

錄音中不辨識說話者（DF1）。測試一律用另外的 `SHIYIN_HOME`；使用者的拾音可能正在錄音，不要跑會結束它的 `build-app.sh`。資料表、比對規則、錄完套用、重新轉錄、錄音畫面、錄完的提示、英文介面都已經驗證（見 commit）。

- [~] **S2、S3 在真的畫面上按**（§F2.2、§F2.4，F2.1、F2.2、F2.5）：這台電腦沒有給 Claude 輔助使用和螢幕錄製的權限，用 `windowshot` 看過畫面、用 `tagui`＋`typefield`／`submitfield` 走過彈出視窗的送出
  - 待使用者：錄音中按「正在說話」的名字、＋ 的「加入」「取消」，一行的選單（名單、認識的人、其他名字…的「標記」、清除標記、右鍵的「拷貝」）；錄完按提示列的「查看」、逐字稿的「套用到…」「刪除標記」；標記帶入的名字（F2.9）：會議頁名字的選單（是別人、不是 X）、逐字稿改名視窗的「不是他」
- [~] **S4 多人真人錄音的端到端**（§F2.6）：模擬錄音只有一個人的聲音（FluidAudio 附的 3 段測試音檔是同一個人），驗證了時間對得上、矛盾時不套用、只標一個名字時套用
  - 待使用者：實際開會時標記幾個人，錄完看名字有沒有套到對的說話者；或同意下載 AMI 會議語料來測
