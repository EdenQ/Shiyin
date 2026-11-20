# 會議助手（fork）：任務

> 只放 fork 還沒完成的任務；做完就刪掉（紀錄在 git 歷史）。上游的任務在 `docs/tasks.md`，照上游原樣、fork 不改；
> 上游任務在 fork 這邊的實測狀態寫在這裡。需求在 `docs/fork/requirements.md`，設計在 `docs/fork/design.md`。
> 規則同 CLAUDE.md：每項都有驗證方式；`[~]` 是程式完成、還差要使用者的驗證。「design §F#」指 fork design，「design §數字」「D#」「R#」指上游文件。

## 5.0.1（合併上游 5.0.0）待使用者實測

合併、M2～M7 的程式和自動驗證做完了（分支 feature/f9-merge-upstream-5.0）。這台電腦沒有給 Claude 輔助使用、螢幕錄製的權限，下面要使用者在電腦前：

- [~] **M5 錄音島的靜音**（F3.7）：DEBUG 版 `record-sim` 中 `micmute on`，`mawindowshot <輸出> island` 拍過收起、滑過去（中英簡）。還差：真的錄音中按錄音畫面的麥克風、⌃⌥⌘M，看螢幕上方的島（有瀏海、沒瀏海的 Mac）；靜音中現場有人說話約 20 秒時島上出現提醒、按「打開麥克風」
- [~] **M6 提醒事項的列表**（F7.5）：DEBUG 版用的是假的提醒事項（`FakeReminders`），接點用 `brand-hooks-test` 驗過。還差（要同意提醒事項權限）：正式建置按「加到提醒事項」：沒有列表時建立「會議助手」；先手動建一個叫「拾音」的列表時沿用它、不再建新的。測完刪掉測試建立的列表和待辦
- [~] **M7 F2、F3、F4 在 5.0 的新畫面上按**：`windowshot` 看過紀錄分頁（條數、色條、「加到提醒事項」、負責人頭像）、錄音畫面的靜音、設定「錄音」頁的開關。還差：紀錄分頁點兩下條目就地編輯、右鍵、⋯ 之後 F4 的樣式還在；會議頁上方「標記」的名字點了出現「是別人／不是他」；說話者名字彈窗的「不是他」
- [ ] **4.7.6 → 5.0.1 的 app 內更新**：裝 4.7.6 的使用者更新後，打開舊會議看標記、靜音、條列頁；資料夾、編輯會議等 5.0 的功能可以用

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

## 上游監看（PLAN-fork-5.0 階段 3b，fork design §F0.5）

- [~] **W1 推送後手動觸發一次**：`upstream-watch.yml` 要在 GitHub 上才會跑。推送到 EdenQ/Shiyin 的 main 後，在 Actions 分頁手動執行 upstream-watch（或 `gh workflow run upstream-watch.yml -R EdenQ/Shiyin`），確認：exit 不是工具錯誤、artifact 有 `upstream-watch.md`／`.json`、job summary 只有一行、沒有建立 Issue；第二次執行時 cache 有取回上次的狀態（報告的「比對起點」是上次的 upstream/main）。

