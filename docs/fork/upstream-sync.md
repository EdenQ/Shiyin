# 跟上游同步

上游：`https://github.com/juinwei7/Shiyin.git`（remote `upstream`）；fork：`https://github.com/EdenQ/Shiyin.git`（remote `origin`）。fork 的需求、設計在 `docs/fork/`，上游三份文件（`docs/requirements.md`、`design.md`、`tasks.md`）照上游原樣，合併時直接用上游的版本。

## 1. 版本號（DF6）

- **build 號**：單調遞增，從 31 開始，不跟上游。
- **版本號**：合併上游 X.Y.Z 的那一版是 **X.Y.(Z+1)**；比 fork 目前的版本小時，取 fork 版本的 patch + 1。fork 自己的發布（只有 fork 功能、修正）只加 patch。
  - 例：合併上游 5.0.0 → 5.0.1；之後 fork 自己的修正 → 5.0.2；接著合併上游 5.0.1：上游 patch + 1 是 5.0.2、fork patch + 1 是 5.0.3，取大的 **5.0.3**。
- **Release 說明**：第一行（「會議助手 X.Y.Z：…」）後面加一條「- 基於上游 拾音 X.Y.Z」，中英文各一條（英文「- Based on upstream Shiyin X.Y.Z」）。其餘格式照 CLAUDE.md「發布新版的說明文字」。
- app 內更新只比數字（`Updater.isNewer`），這個規則永遠往上，使用者不會收不到更新。

## 2. 合併流程

### 2.1 接回上游歷史（一次性，合併 5.0 時）

上游在 2026-11 重寫過歷史：fork 是從重寫**前**的 4.7.1（`9e0f9ef`）分出來的，重寫後的同一版是 `78ceab8`（內容只差上游拿掉了 CLAUDE.md），所以 `git merge-base main refs/upstream-tags/v5.0.0` 是空的，一般的 `git merge` 會失敗。用指定的合併基準做成有兩個上層的 merge commit，接回歷史：

1. 在暫存 worktree（`~/Library/Caches/ShiyinBuild/` 底下）從 fork 的 main 開始。
2. 先合 4.8.1：`git -c merge.conflictStyle=diff3 merge-tree --write-tree --merge-base=78ceab8 <fork> 3980efd`（`3980efd` 是重寫後的 v4.8.1）。解完衝突，`git commit-tree <tree> -p <fork> -p 3980efd` 得到 M1（內部用，不發布）。
3. 從 M1 `git merge refs/upstream-tags/v5.0.0`：這時已經有共同祖先，是一般的 merge。
4. **不可以用 `--allow-unrelated-histories`**：會把兩邊整個歷史都當成新增，每個檔都衝突。
5. 驗證：`git merge-base HEAD refs/upstream-tags/v5.0.0` 是 `7e5b274`。
6. 合併時文件的處理：上游三份文件直接取上游的版本（fork 的都在 `docs/fork/`）；CLAUDE.md 上游從 5.0 起不追蹤（`.gitignore` 列了 `CLAUDE.md`、`.claude/`），fork 繼續追蹤：fork 的 `.gitignore` 拿掉 `CLAUDE.md` 那一行（`.claude/` 保留）。

### 2.2 之後的同步

- 一般的 `git fetch upstream` 加 `git merge refs/upstream-tags/vX.Y.Z`（跟到上游發布的 tag，不跟 main 上還沒發布的 commit）。
- 只想要上游某一個修正時，照樣 merge 到那個 tag；**避免 cherry-pick**：cherry-pick 的 commit 跟上游的不是同一個，下次合併同一段又會衝突（4.7.6 帶入 4.8.1 的 R57、R73、R74 就是這樣，F6）。
- `rerere` 已經打開（`rerere.enabled`、`rerere.autoupdate`，只在這台電腦）：同一個衝突解過一次會記下來，試合併重做、審查退回再合時重用。衝突用 diff3 看（`-c merge.conflictStyle=diff3`）。
- 合併後：版本照 §1 改；跑回歸檢查（`brand.py check-sources`、`l10n.py check`、`check-fork-migrations.py`、`f4-check.py`、`brand-test.py`、`brand-hooks-test`，合併後再加 `brand.py crosscheck`，fork design §F7.4）；上游文件跟上游的 tag 比對要沒有差異（`git diff refs/upstream-tags/vX.Y.Z -- docs/requirements.md docs/design.md docs/tasks.md`）；fork 對上游的補充（fork design §F-UP）、資料庫規則的清單（§F-DB.2）照上游的新寫法檢查一次。
- 時機：上游發布新版後 1～3 天決定跟不跟；修正版（patch）通常直接跟，大版本先等它的第一個修正版。分工：Claude Code 合併、驗證、發布；Codex 審查、推送（CLAUDE.md 的 Herdr 分工）。

## 3. refs 的命名空間

| refs | 內容 |
|---|---|
| `refs/tags/v*`（`git tag`） | **只有 fork 自己的發布**（v4.5.0～v4.7.6，以及之後的）。origin 上也是這些 |
| `refs/upstream-tags/*` | 上游的 tag（重寫後的 SHA）。`remote.upstream.tagOpt = --no-tags`，加上 fetch refspec `+refs/tags/*:refs/upstream-tags/*`，`git fetch upstream` 只會寫到這裡，不會蓋掉 fork 的 tag |
| `refs/upstream-tags-legacy/*` | 上游重寫**前**的舊 SHA（舊的本機 tag 搬過來的），只用來對照新舊 SHA，不要拿來合併 |
| `refs/remotes/upstream/*` | 上游的分支（main 等） |

上游也有 `win-vX.Y.Z` 的 tag（Windows 版），fork 不做 Windows，不用管。

## 4. 新舊 SHA 對照（上游重寫歷史前後，同一個 tag）

`git rev-parse refs/upstream-tags-legacy/<tag>^{commit}` 對 `git rev-parse refs/upstream-tags/<tag>^{commit}`。fork 的歷史裡只有舊的（`9e0f9ef` 以前）。

| tag | 重寫前（legacy） | 重寫後（upstream-tags） | 備註 |
|---|---|---|---|
| v3.1.0 | `e48ccc9` | `addade9` |  |
| v3.1.1 | `49e9633` | `f1c7868` |  |
| v3.2.0 | `0281a0b` | `19548cb` |  |
| v3.2.1 | `ea19e64` | `cde0195` |  |
| v3.3.0 | `d413b72` | `c6d523b` |  |
| v3.4.0 | `2984341` | `854b758` |  |
| v3.4.1 | `28e1433` | `38a8c99` |  |
| v3.5.0 | `777f74c` | `fb7365c` |  |
| v3.6.0 | `30a09fc` | `89ab743` |  |
| v4.0.0 | `63cb963` | `ac6c0bc` |  |
| v4.1.0 | `21cddd2` | `117b71f` |  |
| v4.1.1 | `c7b05f9` | `ebdfbd5` |  |
| v4.1.2 | `9e30313` | `3bbb6c8` |  |
| v4.2.0 | `02b9c42` | `f3d4cc4` |  |
| v4.2.1 | `95c44d5` | `7562dc1` |  |
| v4.2.2 | `3ed45ca` | `cb19e3a` |  |
| v4.2.3 | `7c437b5` | `8839b68` |  |
| v4.3.0 | `5f1fdf3` | `caca797` |  |
| win-v4.5.0 | `d99bbee` | `b2f48bc` | 舊的只留 win- 的 tag（同名的 Mac tag 是 fork 的發布）；新的也在 `refs/upstream-tags/v4.x.y` |
| win-v4.6.0 | `31dc554` | `f4ae711` | 舊的只留 win- 的 tag（同名的 Mac tag 是 fork 的發布）；新的也在 `refs/upstream-tags/v4.x.y` |
| win-v4.7.0 | `69ca5ba` | `54080b4` | 舊的只留 win- 的 tag（同名的 Mac tag 是 fork 的發布）；新的也在 `refs/upstream-tags/v4.x.y` |
| win-v4.7.1 | `9e0f9ef` | `78ceab8` | fork 分出來的地方（舊）；新的 `78ceab8` 是 §2.1 的合併基準 |
| win-v4.7.2 | `a6ef50b` | `21e056d` | 舊的只留 win- 的 tag（同名的 Mac tag 是 fork 的發布）；新的也在 `refs/upstream-tags/v4.x.y` |
| v4.8.0 | `0ed2031` | `468a206` |  |
| v4.8.1 | `25e79a6` | `3980efd` | §2.1 先合的那一版 |
| v5.0.0 | `7e5b274` | `7e5b274` | 重寫之後才發布，前後相同 |

- `refs/tags/v4.5.0`～`v4.7.2` 在本機和 origin 上是 **fork 自己的發布**，跟上游同版號的發布不是同一個 commit；上游的在 `refs/upstream-tags/v4.5.0`～`v4.7.2`（上游 Mac、Windows 同一個 commit 發布，所以跟同版號的 `win-` tag 相同）。
- 用法：上游的說明、issue 引用舊 SHA 時，用這張表找重寫後的 commit；fork 的 commit 訊息引用上游時，寫重寫後的 SHA。
