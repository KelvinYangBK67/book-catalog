# 紙上藏書

用於管理個人紙質藏書的本地 Web 應用。資料依照 `Work → Edition → Volume → Copy` 四層保存，提供新增、列表、完整詳情、修改及跨字段搜尋。

首頁頂層可切換智能、Work、Edition 三種模式，並可另按文種、標籤、出版社、藏書位置或年份分類；兩種偏好都會保存在瀏覽器中。智能模式通常按 Work 展示，但多個 Work 全部以 contained 關聯聚合在同一物理冊時，改以單一 Edition 條目展示；含 volume 分冊關聯時仍分別保留 Work 入口。分組檢視提供可跳轉索引。

Edition 卡片按 Edition 題名、翻譯題名、Work 題名的順序選擇主題名，副標題也按相同層級回退；Work 詳情頁頂部始終保留 Work 原題。Edition 的翻譯題名、譯者、系列等字段各自獨立顯示，不依賴版本字段。真正的多卷書在 Volume 使用冊號與冊名，因此同一 Edition 的多冊仍歸在同一版本下。同一 Volume 可關聯多份 Copy；某冊只有一份 Copy 時界面可直接顯示藏書位置。

正常新增時可按題名與作者檢出 Work 候選，但只有題名、副標題、作者、文種及明示標籤均與候選相容時才自動復用；否則建立獨立 Work，交由明確 merge 處理。相似項只作候選提示，不會被永久合併。同一 Work 下，Edition 題名、副標題、文種、Edition 責任人、Edition 版本、系列與正規化出版社構成 matching identity。識別號、出版年份及 Volume 差異不拆分 Edition，但冊級差異保存在各自 Volume，不再 union 到 Edition 或壓成年份範圍。新增時可勾選「強制建立獨立 Edition」。資料庫啟動 migration 只做結構轉換，不在啟動時進行 Work／Edition 語義性自動歸併。

Work 保存題名、副標題、作者或相關責任人及可多選的文種。Edition 保存整個出版版本的共同書目資料。Volume 保存冊號、冊名、穩定 position，以及冊級 identifier、version、publication year、responsibility 例外；普通單冊書也有一個可在 UI 隱藏的隱式 Volume。Copy 只保存 acquisition date、藏書位置、閱讀記錄等物理副本資料，並以 volume_id 引用 Volume。冊級識別號留空時可繼承 Edition 識別號。

Edition 默認只關聯一個 Work。多 Work 關聯會保存順序與類型：volume 表示該 Work 對應 Edition 中一個真實 Volume，edition_works 以 volume_id 外鍵引用 volumes，不再另存冊號字串；contained 表示多個 Work 同冊收錄。只有臨時合刊數個彼此獨立、且沒有穩定集合身份的作品時，才使用多個 contained 關聯。

Work–Edition 關聯可從兩側編輯：Edition 表單按 Work 題名、副題名與作者搜尋候選；Work 新增／修改表單按 Edition 題名、副題名、識別號、出版社與出版年組合搜尋。空條件可瀏覽候選，點擊確認後才建立關聯；兩側共用 edition_works 關聯表並由唯一鍵防止重複。Work 可先獨立建立，也可在建立時直接加入已有 Edition。

錄入時可用半角分號選擇或直接輸入多個標籤，系統會自動建立新標籤；已有標籤以 ID 掛載，避免同名歧義。作品只能掛在葉節點；已有藏書的標籤必須先重新分類，才能增加下級。標籤管理會列出既有的非葉節點掛書違規，但不會自動搬移。出版社會保留書上所印的原始名稱，同時建立出版社實體與別名；建立一次關聯後，後續錄入會自動識別。

## 啟動

### 一鍵啟動（Windows）

雙擊專案根目錄的 [`start_library.bat`](start_library.bat)。首次啟動會自動建立 `.venv` 並安裝所需組件；之後會直接開啟瀏覽器及服務。關閉命令窗口或在其中按 `Ctrl+C` 即可停止。

### 手動啟動

需要 Python 3.11 或以上版本。在專案目錄執行：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 17321 --reload
```

然後開啟 <http://127.0.0.1:17321>。API 文件位於 <http://127.0.0.1:17321/docs>。

本專案固定使用本地埠 `17321`。建立專案時已確認該埠未被其他程序監聽，且不在 Windows TCP 排除範圍內。

## 資料與備份

資料預設保存於 `data/library.db`，與程序碼分開且不納入 Git。停止應用後，直接複製此檔即可備份。

也可以用環境變數把資料庫放到其他位置：

```powershell
$env:LIBRARY_DATABASE = "D:\BookData\library.db"
python -m uvicorn app.main:app --host 127.0.0.1 --port 17321
```

應用啟動時會自動建立目錄、資料庫及資料表。

舊三層資料庫會在單一 `BEGIN IMMEDIATE` transaction 中執行版本化 migration：先以確定性規則補齊已知 legacy 欄位，依 Edition 與標準化後的冊號／冊名建立 Volume，再把 Copy 改接 `volume_id`，最後移除 `editions.work_id` 與 Copy 冊級舊欄位。整段升級失敗即回滾，結果記入 `schema_migrations`，重啟具 idempotent 性；不會猜測或自動歸併 Work／Edition。正式資料庫升級前仍建議先備份檔案。


## 本機字體

字體檔不隨本專案發布。未設定字體庫時，WebUI 直接使用瀏覽器及作業系統的預設字體。

本機若有 IMPE 字體庫，可指定其 `assets/fonts` 目錄。偵測成功後，拉丁文字使用 Libertinus，漢字使用 Shanggu；天城文、藏文、西夏文、契丹小字、諺文、假名、蒙古文及其他文字按 Unicode 區段使用相應的 Noto 等字體。若要使用 Libertinus，需另將 Web 字體放在 `static/fonts/libertinus` 或 `static/fonts/web`。

如 IMPE 字體庫移至其他位置，可在啟動前指定：

```powershell
$env:LIBRARY_FONT_ROOT = "D:\新的位置\assets\fonts"
```

## 多值字段與導出

作者、文種、標籤、識別號、版本等多值資料統一按「多項用半角分號 `;` 分隔」輸入；半角分號後的空格忽略。後端也接受 `；`、`、`、`，`，保存後統一為 `; `。識別號與版本在 WebUI 中可用按鈕增加輸入框，純數字版本會自動保存為「第X版」。多個識別號在詳情中逐行顯示。

首頁提供 JSON 與 CSV 導出。JSON 使用 `schema_version: 2`，頂層分別保存 `works`、`editions`、`volumes`、`copies`、`publishers` 與 `tags`；Edition–Work 關聯及其順序、類型和 `volume_id` 外鍵也會完整保存。JSON 可由 `POST /api/import/json` 原樣導回，匯入只做 ID 重映射與確定性的結構還原，不執行 semantic matching 或自動合併。

CSV schema version 2 仍以每個 Copy 一行，欄名按層級區分為 `work_*`、`edition_*`、`volume_*`、`copy_*`。Edition 與 Volume 的 identifier 分別使用 `edition_identifier`、`volume_identifier`；Copy 僅輸出 `copy_id`、`copy_acquisition_date`、`copy_location`、`copy_reading_record`，新 CSV 不再輸出 `copy_identifier`。標籤以名稱作為跨資料庫匯入的主要依據；明示的出版社正規名稱與別名關係也會在正式匯入時重建。

舊三層 CSV 仍可導入。legacy `volume_number`、`volume_title`、`copy_identifier` 會確定性映射到 Volume；`location`、`acquisition_date`、`reading_record` 映射到 Copy。legacy adapter 不負責 semantic merge，也不會把冊級差異壓回 Edition。

CSV 預覽依次檢查 Work candidate → Edition candidate → Volume candidate → Copy candidate。Volume 以同一 Edition 下的冊號與冊名辨識；Copy 則以取得日期、位置和閱讀記錄等館藏字段完全相同才視為重複。因此同 Edition、同 Volume、不同位置通常會建立同一冊的另一個 Copy，而不是另一個 Volume。matching 本身不修改資料；是否新增或覆蓋仍由使用者逐行選擇。

Edition identifier 表示整套或共同識別號，Volume identifier 表示冊級識別號，兩者可以並存。新增或匯入 Volume 不再觸發舊的 `identifier_transition` 提示，也不會自動清空 Edition identifier。若確實要把 Edition identifier 重新解釋為某冊的 identifier，使用明確的 `POST /api/editions/{edition_id}/move-identifier-to-volume` 操作；衝突時拒絕執行。

四層 API 提供 Work detail（Edition → Volume → Copy）、單獨 Edition／Volume／Copy 讀取與修改、為 Edition 新增 Volume，以及為 Volume 新增 Copy。`/api/books` 是以每個 Copy 一筆表示的平面索引端點，但每筆仍明確分開 `work`、`edition`、`volume`、`copy`；有效 metadata 統一由後端 resolver 計算。

識別號會保存為帶類型的形式，例如 ISBN 978-...、ISSN 0169-8524。同類識別號若明確標有多種載體，只保留 hbk > pbk > ebook 優先級最高的一項；沒有載體限定的不同 ISBN（例如不同冊各自的 ISBN）則全部保留。

新增藏書仍支持批量建立冊模式：作品與 Edition 建立一次，每組冊號／冊名建立獨立 Volume，並為每個 Volume 建立一份 Copy。

出版社原始名稱始終保留。出版社管理中由使用者填寫正規名稱，再從出版物中已有的名稱多選關聯；未知名稱不會自動被指定為正規名稱。

## 緊湊 WebUI

日常新增表單只常駐 Work 的題名、副題名、作者或相關責任人、文種、標籤；Edition 的出版社、出版年份、版本、識別號；以及 Copy 的藏書位置、取得日期。Edition 題名、翻譯資料、系列等放在「更多版本信息」，冊號／冊名放在「冊資料」，冊級 identifier／version／year／responsibility 放在「冊級例外」，閱讀記錄放在「其他館藏信息」，多 Work 關聯、force separate 和批量建立放在「進階結構」。折疊區有值時會顯示項目數並在編輯時自動展開。

詳情按 Work → Edition → Volume → Copy 逐層展示：各層只顯示自己的資料；普通單冊的隱式 Volume 會壓縮隱藏，有冊級例外、多冊或同冊多份 Copy 時才展開 Volume。每層操作統一收進「⋯」選單。分類群組、標籤樹與出版社 aliases 均可逐項折疊，並提供全部收起／全部展開和本機偏好保存。

前端維持 plain JavaScript，公共 API 請求、偏好狀態、通用元件、格式化及四層目錄投影分別位於 `static/api.js`、`static/state.js`、`static/components.js`、`static/formatters.js`、`static/catalog-model.js`。後端標籤／出版社管理集中在 `app/admin_repository.py`；schema bootstrap 留在 `app/database.py`，legacy migration 與資料完整性 guards 集中在 `app/migrations.py`。

## Metadata resolver、matching 與 merge

`app.metadata_resolver.resolve_metadata(work, edition, volume)` 是有效書目資料的唯一計算入口。它為每個 override 字段返回 `{value, source}`，`source` 為 `work`、`edition`、`volume` 或 `null`；責任人使用 append 語義，返回合併後的 `value` 與逐層 `sources`。API 的 Edition group 及 Volume record 會返回 `effective_metadata`，Copy 不包含任何冊級或繼承字段。

Override 字段包括題名、副標題、文種、識別號、版本與出版年份；實際可回退層級由字段模型決定。責任人是 append 字段：Work 作者、Edition 譯者或相關責任人、Volume 冊級責任人依層級追加並去重。

`app.edition_matching` 與 `app.work_matching` 都是純候選偵測，不寫資料。matching 不等於 merge。正式合併集中在 `app.merge_service` 的 `merge_works`、`merge_editions`、`merge_volumes`，全部在 transaction 內執行；兩側非空字段不同、關聯語義不同或 Volume 跨 Edition 時會拋出 `MergeConflict` 並完整回滾，不會自行挑選衝突值。

`initialize()` 僅建立表、執行 deterministic/lossless schema migration、維護 index 與 constraint。它不再按題名作者合併 Work，不再按 matcher 合併 Edition，也不搬移或刪除可能重複的語義記錄。

## 搜尋範圍

單一搜尋框會同時比對題名、副標題、作者或相關責任人、文種、識別號、版本、系列、其他題名與副標題、翻譯題名與副標題、譯者或相關責任人、出版社及其別名、標籤、藏書位置和閱讀記錄。

## 測試

測試使用獨立的臨時 SQLite 資料庫，不會接觸正式資料：

```powershell
python -m unittest discover -s tests -v
```
