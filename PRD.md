# AI 驅動影音語言學習 App — MVP 產品需求規格書

| 屬性 | 內容 |
| :--- | :--- |
| **文件版本** | V0.2.0-MVP |
| **文件狀態** | MVP 定義稿（PO Pro review 後） |
| **撰寫日期** | 2026-08-25 |
| **目標平台** | iOS 17+（SwiftUI） |
| **MVP 目標語言** | 英文 → 繁體中文（台灣） |
| **產品定位** | 用個人感興趣的公開 YouTube 影片，快速開始雙語聽讀學習 |

---

## 1. MVP 目標

### 1.1 核心假設

如果使用者只需貼上符合支援範圍、且具有可取得英文字幕的影片連結，就能在合理等待時間內取得可同步播放的英文字幕與自然繁體中文翻譯，使用者便能在第一次使用時完成一段有效的聽讀學習，而不必先尋找字幕、複製文字或手動對時間軸。

無字幕影片的 STT fallback 是第二階段產品假設，只有在音訊取得方式、供應商、成本與法務條件完成確認後才開啟。

### 1.2 MVP 核心閉環

```text
貼上公開 YouTube 連結
        ↓
Server preflight：驗證來源、語言、長度與字幕可用性
        ↓
建立解析任務並取得英文字幕
        ↓
產生逐句繁中翻譯
        ↓
播放器與雙語字幕同步
        ↓
點擊句子跳轉並完成第一次學習

Release B（條件式）：無字幕 → STT → 逐句字幕 → 同一個學習頁
```

### 1.3 MVP 成功定義

MVP Release A 不是功能越多越好，而是先驗證以下四件事：

1. 有字幕影片能穩定產出可用的字幕資料。
2. 使用者能在不需教學的情況下完成「貼連結 → 開始學習」。
3. 同步字幕是否足以讓使用者願意觀看並繼續使用。
4. 失敗、重試、快取與匿名成本控制不會破壞核心流程。

### 1.4 MVP 不追求的目標

- 不在 MVP 實作完整語言學習平台、社群、帳號或付費系統。
- 不同時支援多個 STT／LLM 供應商的使用者選擇。
- 不承諾所有 YouTube 影片皆可解析；先限定可控的影片類型與長度。

### 1.5 版本與上線策略

| 版本 | 上線內容 | 上線門檻 |
| :--- | :--- | :--- |
| **MVP Release A** | 有可取得英文字幕的影片、逐句繁中翻譯、句子同步、點擊跳轉、快取與錯誤恢復。 | 不依賴 STT；通過 Release A 的 AC、品質、成本與匿名配額 gate。 |
| **Release B（條件式）** | 在 Release A 基礎上加入無字幕影片的 STT fallback。 | D1 音訊取得／法務、D2 STT provider／成本、D3 測試資料與品質 gate 全部完成。 |

Release B 未通過 gate 時，Release A 對無字幕影片回傳明確的 `captions_unavailable`，不得偷偷啟用未核准的音訊管線。

---

## 2. 目標使用者與使用情境

### 2.1 主要使用者

想用自己感興趣的英文影音學習，但不想先處理字幕、翻譯與時間軸設定的 iPhone 使用者。

### 2.2 主要使用情境

使用者在 YouTube 看到一支公開英文影片，複製網址並貼入 App。App 顯示處理階段；完成後，使用者可播放影片、閱讀同步的英文與繁中字幕，點擊句子回到對應時間重新聆聽。

### 2.3 MVP 支援範圍

- 公開、非直播、可嵌入播放的 YouTube 影片。
- 影片長度上限：15 分鐘。
- 來源語言限英文；偵測到非英文內容時，顯示目前版本尚未支援。
- Release A 必須有可取得且可解析的英文字幕；無字幕影片列為 Release B 條件式範圍。
- 單支影片、單一使用者、單一翻譯方向（英文 → 繁中）。
- 影片必須能在 iOS YouTube 嵌入播放器中正常播放。

---

## 3. MVP 範圍與優先級

### 3.1 MVP 必做（P0）

| 編號 | 功能 | MVP 規格 |
| :--- | :--- | :--- |
| **MVP-01** | YouTube 網址輸入 | 支援 `youtube.com/watch?v=` 與 `youtu.be/`；自動擷取 Video ID、移除追蹤參數並在送出前驗證格式。 |
| **MVP-02** | Preflight 與解析任務 | Server 在同一個 request 中驗證來源、語言、長度、嵌入能力與字幕可用性；通過後立即建立非同步任務。使用 HTTP polling，不做 WebSocket。 |
| **MVP-03** | 字幕取得（P0）／STT fallback（Release B） | Release A 僅使用可取得的官方或自動字幕；無字幕時回傳 `captions_unavailable`。Release B 才配置一個 STT 供應商。 |
| **MVP-04** | 逐句繁中翻譯 | 以整句語境翻譯成自然繁體中文；輸出通過 JSON Schema 驗證。MVP 不做 CEFR、詞性與重點片語。 |
| **MVP-05** | 雙語播放器 | 內嵌 YouTube 播放器；依影片時間高亮目前句子、自動滾動至目前句子、點擊句子跳轉至對應時間。 |
| **MVP-06** | 基本學習控制 | 可播放／暫停、拖曳進度、顯示／隱藏中文字幕。沿用播放器原生控制，不新增自製手勢、語速與循環控制。 |
| **MVP-07** | 失敗處理與重試 | 對無效網址、不支援影片、無字幕、處理逾時、服務失敗與網路中斷提供可理解的錯誤訊息及重試入口；preflight 拒絕不得建立任務。 |
| **MVP-08** | 結果快取 | 以 Video ID、翻譯方向與 pipeline 版本作為快取鍵；相同影片不重複建立處理任務。App 可本地保存最近 5 支影片的字幕資料，但不承諾離線播放影片。 |

### 3.2 條件式功能

- 若字幕來源或 STT 穩定提供 word timestamps，MVP 可開啟實驗性單字高亮。
- 單字高亮缺失或品質不足時，必須自動退回句子級同步，不能阻塞整支影片完成。
- 單字級高亮不列入 MVP 上線門檻。

### 3.3 明確排除（Post-MVP）

| 優先級 | 延後功能 | 延後原因 |
| :--- | :--- | :--- |
| **P1** | 單句 A-B Loop、語速調整、完整 word-level seek | 先驗證句子同步與學習價值，再增加精細播放控制。 |
| **P1** | 即點即查、生詞本、發音音檔、CEFR、詞性與片語 | 需要額外的字典／內容模型與本地資料設計，不影響第一個學習閉環。 |
| **P1** | 剪貼簿自動偵測、Share Extension、Shorts、播放清單 | 增加 iOS 入口與影片格式的邊界情況；手動貼上已足以驗證 MVP。 |
| **P1** | 帳號、雲端歷史、跨裝置同步、付費 | MVP 先驗證核心體驗，不建立會員與商業系統。 |
| **P2** | 跟讀錄音、發音評分、口說回饋 | 需要麥克風權限、語音評估模型與較高的品質驗證成本。 |
| **P2** | 多語言、多模型選擇、離線影片、社群功能 | 擴大產品面積，與 MVP 假設無直接關係。 |

---

## 4. 使用者流程

### 4.1 正常流程

1. 使用者貼上 YouTube 網址並送出。
2. Server 執行 preflight；通過後回傳影片摘要與 `jobId`，App 自動進入處理頁，不增加第二個「開始解析」步驟。
3. App 顯示目前階段與可離開／返回的狀態。
4. 任務完成後進入學習頁，載入影片與雙語字幕。
5. 播放時自動標示目前句子；使用者點擊任一句子即可跳轉重聽。
6. 分別記錄 `study_30s_reached` 與 `study_5_segments_reached`，不把兩種行為合併成單一完成事件。

### 4.2 例外流程

- 網址格式錯誤：送出前即時提示，不建立任務。
- 影片不公開、直播、不可嵌入、非英文或超過 15 分鐘：preflight 顯示明確原因，不建立任務。
- Release A 無可用字幕：回傳 `captions_unavailable`，不進入 STT；Release B 通過 gate 後才可進入 STT。
- 翻譯資料格式錯誤：伺服器自動修正／重試一次；仍失敗則任務失敗，不回傳不完整資料。
- App 暫時離開或網路中斷：回到 App 後以任務 ID 恢復狀態，不重複建立任務。

---

## 5. 功能需求

### 5.1 MVP-01：網址輸入與驗證

- 支援標準網址與短網址，將輸入正規化為 Video ID。
- 拒絕空白、非 YouTube 網址、缺少 Video ID 的網址。
- MVP 不主動讀取剪貼簿；使用者以貼上操作提供網址。
- `POST /v1/parse-jobs` 同時執行 Server preflight 與任務建立；不在 MVP 增加獨立 preflight endpoint。
- Server 端驗證網址、影片狀態、來源語言、影片長度、嵌入能力與字幕可用性；Client 端驗證不能視為安全邊界。
- Preflight 拒絕時回傳明確的 4xx `errorCode`，不建立 `jobId`，也不進入 STT／LLM。

### 5.2 MVP-02：非同步解析任務

Release A 任務狀態固定為（任一處理階段都可能進入 `failed`）：

```text
queued → fetching_captions → translating → ready
   └────────────── 任一處理階段 → failed
```

Release B 在完成 gate 後才增加 `transcribing`：

```text
queued → fetching_captions → transcribing → translating → ready
   └────────────────────── 任一處理階段 → failed
```

- `unsupported`、`non_english`、`captions_unavailable` 是 preflight 4xx 錯誤，不是任務狀態。
- Client 每 3 秒 polling 一次任務狀態；App 進入背景時停止 polling，返回前景後立即恢復。
- UI 顯示階段名稱與可預期的下一步，不顯示未經後端計算的假百分比。
- `failed` 必須帶有 `errorCode`、`errorMessageKey` 與 `retryable`；不可重試的失敗不可顯示無限重試。
- 同一 dedupe key 的進行中任務應可被重用；重試必須具備冪等性且不得重複執行 STT／LLM。

### 5.3 MVP-03：字幕與轉錄管線

1. Release A 只接受 preflight 已確認可取得的英文字幕；字幕不可用時回傳 `captions_unavailable`，不下載音訊。
2. Release B 通過 D1／D2／D3 後，字幕不可用時才下載允許處理的音訊並送至單一 STT 供應商。
3. 字幕或 STT 至少產生逐句的 `startTime`、`endTime`、`originalText`；若能穩定取得單字時間戳，再填入 `words`。
4. 影片長度、來源權限、檔案大小與服務配額在任何音訊處理前檢查。
5. 原始音訊只供處理使用，不作永久保存；處理完成後刪除，最長保留時間不得超過 24 小時。

### 5.4 MVP-04：翻譯管線

- MVP 只支援英文 → `zh-Hant-TW`。
- LLM 只配置一個供應商；程式以 adapter／protocol 隔離供應商，方便日後替換，但不提供使用者選擇。
- 翻譯以逐句批次處理，保留原始時間軸與句子順序。
- 輸出必須通過 JSON Schema；缺欄位、時間軸不合法或句數不一致時，最多自動重試一次。
- 翻譯提示詞要求自然、口語、符合台灣繁中語境；不在 MVP 產出學習等級或詞性分析。
- 結果必須標記 `transcriptSource = caption` 或 `stt`，供 Release A／B 成功率與品質分流統計。

### 5.5 MVP-05：播放器與字幕同步

- 使用 YouTube IFrame Player API 搭配 `WKWebView`；具體 wrapper 為實作選擇，不同時維護兩套播放器方案。
- 以 `startTime <= currentTime < endTime` 定位目前句子。
- 播放中目前句子需有明顯視覺狀態，字幕列表自動滾動；使用者手動捲動時不得持續搶回焦點。
- 使用者手動捲動後暫停自動跟隨；使用者點擊任一句子、重新播放或返回學習頁時恢復自動跟隨。
- 點擊字幕句子後呼叫播放器 seek，目標時間為該句 `startTime`。
- 同步驗收允許誤差為 ±300ms；播放器無法取得時間時，顯示一般字幕但不造成 App 崩潰。
- MVP 不實作自製快進手勢、語速選擇、A-B Loop、浮動字幕與背景播放。

### 5.6 MVP-06：快取、錯誤與可觀測性

- 快取鍵：`videoId + sourceLanguage + targetLanguage + pipelineVersion`。
- 解析成功後保存結果；相同 dedupe key 的 ready 結果直接回傳，不重新呼叫 STT／LLM；進行中任務直接重用。
- 失敗任務不冒充成功快取；使用者重試時產生新的 `Idempotency-Key`，但仍沿用相同 dedupe key 與 retry policy。
- 錯誤需包含可供客服或 Log 使用的 `errorCode`，但對使用者顯示可理解的文案。
- 至少記錄以下事件：`url_submitted`、`job_created`、`job_ready`、`job_failed`、`study_started`、`study_30s_reached`、`study_5_segments_reached`、`subtitle_seek`、`cache_hit`。
- 不記錄完整影片內容、原始音訊或使用者輸入以外的敏感資料。

---

## 6. API 與資料契約

### 6.1 MVP API

| 方法 | Endpoint | 用途 |
| :--- | :--- | :--- |
| `POST` | `/v1/parse-jobs` | 執行 preflight；通過後建立任務並回傳影片摘要、`jobId` 與目前狀態。 |
| `GET` | `/v1/parse-jobs/{jobId}` | 取得任務狀態、階段、錯誤、retryability 與完成後的資料引用。 |
| `GET` | `/v1/videos/{videoId}/learning-data?target=zh-Hant-TW` | 取得快取的學習資料；可由完成任務直接引用。 |

`POST /v1/parse-jobs` 的最小契約：

- Request body：`{ "url": "...", "targetLanguage": "zh-Hant-TW" }`。
- Request header：`Idempotency-Key`，由 Client 為每次送出產生的 UUID；不可直接用 Video ID 代替。
- Server dedupe key：`videoId + sourceLanguage + targetLanguage + pipelineVersion`，用於重用進行中任務與成功快取。
- 成功 response 至少包含 `jobId`、`videoId`、`title`、`duration`、`status`、`errorCode`、`retryable` 與 `learningDataPath`；處理中尚未有錯誤或學習資料時，`errorCode`／`learningDataPath` 可為 `null`，`retryable` 為 `false`；preflight 拒絕則只回傳 `APIError`。
- 相同 `Idempotency-Key` 必須回傳同一個 request 結果；相同 dedupe key 的 ready／in-flight 結果可被不同 request 重用。
- Release A preflight 拒絕時回傳 4xx `APIError`，不得回傳 `jobId`；Release B 未開啟時，無字幕回傳 `captions_unavailable`。
- Idempotency 結果至少保留 24 小時；超過保留期限後，Server 依 dedupe key 與 cache policy 判定是否重用結果。

`GET /v1/parse-jobs/{jobId}` 的狀態契約：

- `status`：`queued`、`fetching_captions`、`translating`、`ready`、`failed`；Release B 開啟後才可出現 `transcribing`。
- `failed` 必須包含 `errorCode`、`errorMessageKey` 與 `retryable`；`retryable = false` 時 Client 不顯示重試按鈕。
- 使用者重試時重新送出相同 URL，產生新的 `Idempotency-Key`；Server 依 dedupe key 與 retry policy 決定是否重用或重新處理。

```json
{
  "errorCode": "captions_unavailable",
  "errorMessageKey": "parse.error.captionsUnavailable",
  "retryable": false
}
```

### 6.2 Client 資料模型

```swift
import Foundation

enum ProcessingStatus: String, Codable {
    case queued
    case fetchingCaptions = "fetching_captions"
    case transcribing
    case translating
    case ready
    case failed
}

enum TranscriptSource: String, Codable {
    case caption
    case stt
}

struct ProcessingJob: Identifiable, Codable {
    let id: String
    let videoID: String
    let title: String?
    let duration: Double?
    let status: ProcessingStatus
    let errorCode: String?
    let errorMessageKey: String?
    let retryable: Bool
    let learningDataPath: String?
    let updatedAt: Date
}

struct APIError: Codable {
    let errorCode: String
    let errorMessageKey: String
    let retryable: Bool
}

struct LearningDocument: Codable {
    let videoID: String
    let sourceLanguage: String
    let targetLanguage: String
    let pipelineVersion: String
    let transcriptSource: TranscriptSource
    let segments: [SubtitleSegment]
}

struct SubtitleSegment: Identifiable, Codable {
    let id: String
    let startTime: Double
    let endTime: Double
    let originalText: String
    let translatedText: String
    let words: [WordTimestamp]
}

struct WordTimestamp: Identifiable, Codable {
    let id: String
    let word: String
    let start: Double
    let end: Double
}
```

資料契約原則：

- `id` 由伺服器產生且穩定，不能在解碼時以 `UUID()` 動態生成。
- `endTime` 必須大於 `startTime`；`words` 可為空陣列。
- Client 不因缺少 `words` 而拒絕整份 `LearningDocument`。
- Preflight rejected 不建立 `ProcessingJob`；拒絕只透過 `APIError` 回傳。
- `transcriptSource` 必須能區分 caption 與 STT，Release A 不得產生 `stt` 結果。
- `pipelineVersion` 變更時，舊快取不可直接視為新結果。

---

## 7. MVP 技術架構

```text
[iOS SwiftUI / MVVM]
  ├─ URL Input
  ├─ Processing State
  └─ Learning Player + Subtitle List
          │ HTTPS REST + polling
          ▼
[Backend API + Task Queue]
  ├─ URL / Video Adapter
  ├─ Caption Fetcher
  ├─ STT Adapter（單一供應商）
  ├─ Translation Adapter（單一 LLM）
  └─ Job Store + Result Cache
```

- iOS 採 SwiftUI、MVVM、`async/await`；不要求在 MVP 先建立完整 Clean Architecture。
- Backend 採 FastAPI／Cloud Run 或等價方案；任務執行與 API request 解耦。
- 使用 REST polling，暫不引入 WebSocket、Redis 或複雜即時同步。只有在實測證明 polling 不足時才升級。
- STT、LLM API 金鑰只存在後端；iOS 不直接呼叫第三方模型。
- Release A 部署預設關閉 STT；Release B 只能透過明確 release flag 在 D1／D2／D3 gate 通過後開啟。
- 解析流程需可替換字幕來源與模型 adapter，但 MVP 只啟用一條預設路徑。

---

## 8. 非功能需求與限制

### 8.1 效能與可靠性目標

以下為 MVP Release A 內部測試目標：至少 20 支通過 preflight 的影片用於主流程與翻譯品質驗證，另以獨立 fixture 覆蓋「preflight 拒絕／服務失敗」；Release B 另以同等規模的無字幕影片驗證，不列入 Release A 上線門檻：

| 指標 | 目標 |
| :--- | :--- |
| Preflight 回應 | P95 ≤ 2 秒；從 Server 收到 `POST /v1/parse-jobs` 到回應 |
| Release A caption 完成時間 | P95 ≤ 60 秒；從 `job_created_at` 到 `ready_at`，不含 Client polling 時間 |
| Release B STT 完成時間 | P95 ≤ 5 分鐘（影片 ≤15 分鐘）；僅在 Release B gate 後計算 |
| Release A 支援影片任務成功率 | ≥ 90%；分母為 preflight 通過且已建立的任務 |
| Release B 支援影片任務成功率 | ≥ 90%；條件式指標，不阻擋 Release A |
| 翻譯語意品質 | 20 支通過 Release A preflight 的影片 × 每支 10 句 × 2 位繁中 reviewer；至少 90% 評為可接受（4/5 以上） |
| 字幕同步誤差 | 取樣句子中 ≥ 95% 落在 ±300ms 內 |
| iOS Crash-free session | ≥ 99.5% |

若影片超出時限、第三方服務逾時或成本上限，系統應快速失敗並提供重試，不可無限等待。所有 latency 與成功率必須分開記錄 caption／STT、provider 版本與測試影片清單，不得混算成單一數字。

### 8.2 隱私與安全

- MVP 不要求登入、不錄音、不請求麥克風與語音辨識權限。
- 所有第三方 API 金鑰留在伺服器；後端實施基本 rate limit 與請求驗證。
- 原始音訊不永久保存，處理完成後刪除，最長 TTL 24 小時。
- 衍生的 `LearningDocument`／成功快取保留 7 天；每日執行 purge 並記錄刪除結果。
- 僅處理公開且允許嵌入的影片；不支援私人、需登入、直播、DRM 或不可嵌入內容。
- 不以 IP 輪替或其他方式繞過來源限制；音訊取得方式與 YouTube 平台政策須在開發前完成法務確認。

### 8.3 成本與匿名配額

- MVP 不要求登入；以隨機 installation token 識別匿名安裝，不使用廣告 ID。
- 同一 installation 同時最多 1 個進行中任務。
- 初始配額：每個 installation 每 24 小時最多送出 5 次 parse request；同一 IP 每 24 小時最多 20 次。
- 超過頻率限制回傳 `429 rate_limited` 與 `Retry-After`；超過配額回傳 `429 quota_exceeded`，在 reset 前不得重試；兩者都不得進入 STT／LLM。
- 單次任務成本上限由 D2 決定；超過上限時回傳不可重試的 `cost_limit_exceeded`，並記錄成本但不記錄原始內容。

### 8.4 UX 與可及性

- 主要畫面只保留「貼上網址／送出／重試／開始學習」等必要操作。
- 處理中狀態不顯示虛假的精確百分比。
- 支援 Dynamic Type、VoiceOver 可識別的主要按鈕與清楚的錯誤文案。
- 網路中斷、App 進背景與回到前景不應導致任務重複或資料遺失。

---

## 9. MVP 驗收標準

### AC-01：Preflight 與有字幕影片

**Given** 一支符合範圍且有可用英文字幕的公開影片，  
**When** 使用者貼上網址並送出，  
**Then** `POST /v1/parse-jobs` 回傳影片摘要與 `jobId`，任務在目標時間內完成，顯示英文字幕與逐句繁中翻譯，播放器可同步目前句子。

### AC-02A：Release A 無字幕影片

**Given** 一支符合範圍但沒有可用字幕的公開影片，  
**When** 使用者送出網址，  
**Then** 系統回傳 `captions_unavailable` 與不可重試標記，不建立 `jobId`，不下載音訊，也不呼叫 STT／LLM。

### AC-02B：Release B 無字幕影片（條件式）

**Given** D1／D2／D3 gate 已通過，且一支符合範圍但沒有可用字幕的公開影片，  
**When** 使用者送出網址，  
**Then** 系統進入 STT fallback，完成後仍可進入同一個雙語學習頁；若無 word timestamps，仍可正常使用句子級同步。

### AC-03：句子同步與跳轉

**Given** 學習頁已載入字幕，  
**When** 播放器播放或使用者點擊任一句子，  
**Then** 目前句子狀態與播放器時間一致，點擊後從該句起始時間播放，誤差符合 ±300ms 目標。

### AC-04：不支援來源

**Given** 私人、直播、不可嵌入、非英文、超過 15 分鐘或格式不合法的輸入，  
**When** 使用者送出，  
**Then** 系統回傳對應的 4xx `errorCode` 與可理解文案，不建立 `jobId`，也不進入 STT／LLM。

### AC-05：失敗與恢復

**Given** 任務遇到網路或第三方服務失敗，  
**When** 使用者返回 App 或點擊重試，  
**Then** 系統能恢復原任務狀態；若使用者重新送出，使用新的 `Idempotency-Key` 且不重複執行同一個 in-flight／ready dedupe key。

### AC-06：快取

**Given** 相同 Video ID、翻譯方向與 pipeline 版本已有成功結果，  
**When** 使用者再次送出，  
**Then** 系統直接使用快取，不重新呼叫 STT／LLM，並記錄 cache hit。

### AC-07：匿名配額

**Given** installation 或 IP 已達到本 PRD 的匿名配額，  
**When** 使用者再次送出網址，  
**Then** 系統回傳 `429 rate_limited` 或 `429 quota_exceeded`，顯示 reset／retry 資訊，不建立任務，也不呼叫 STT／LLM。

---

## 10. MVP 成功指標與驗證方法

### 10.1 North Star 行為

Primary North Star：`study_30s_reached`，定義為使用者在解析成功後實際播放並持續觀看／聆聽至少 30 秒。

Secondary behavior：`study_5_segments_reached`，定義為使用者完成至少 5 個字幕句子的播放區間。兩者分開統計，不以 OR 合併成單一完成事件。

### 10.2 初期驗證門檻

- 至少 80% 的內部測試者可在沒有口頭協助的情況下完成 Release A 的「貼連結 → ready → 開始播放」。
- 至少 60% 取得 Release A 成功結果的測試者達到 `study_30s_reached`。
- Release A 的任務成功率、完成時間、翻譯品質與同步誤差達到第 8 節目標。
- Release B 指標只在 D1／D2／D3 gate 通過後收集，不阻擋 Release A 上線。
- 針對失敗任務，使用者能看懂原因並成功完成重試；不得以空白畫面或無限 loading 結束。

### 10.3 必要事件

```text
url_submitted
job_created
job_ready
job_failed
study_started
study_30s_reached
study_5_segments_reached
subtitle_seek
cache_hit
```

事件不得包含原始音訊、完整影片內容或未必要的個人識別資訊。

---

## 11. 里程碑與交付物

| 階段 | 交付物 | 完成條件 |
| :--- | :--- | :--- |
| **M0：技術驗證** | 內嵌播放器、固定字幕 fixture、句子高亮與點擊跳轉 | 不接真實 AI，也能在本機完整走完學習頁流程。 |
| **M1：Release A 垂直切片** | Server preflight、網址輸入、caption 任務、逐句翻譯、雙語播放 | 一支有字幕影片可從貼連結走到 ready；無字幕影片明確回傳 `captions_unavailable`。 |
| **M2：Release A hardening** | 快取、事件追蹤、匿名配額、背景恢復、可及性、效能與 TestFlight | 通過 Release A 的 AC、品質、成本與第 8 節內部測試目標；可獨立上線。 |
| **M3：Release B gate 與 STT** | 法務／來源決策、STT provider、成本控制、無字幕測試與 fallback | 僅在 D1／D2／D3 通過後開啟；失敗不回頭阻擋 Release A。 |

MVP Release A 上線門檻是 M2 完成；Release B 是條件式擴充。word-level 高亮、A-B Loop、單字學習與口說評分不影響 Release A 是否上線。

---

## 12. 主要風險與對策

| 風險 | 影響 | MVP 對策 |
| :--- | :--- | :--- |
| YouTube 來源限制或政策變更 | 無法取得字幕／音訊 | Release A 只處理可取得字幕；Release B 必須先完成 D1 法務／來源決策；不做 IP 輪替。 |
| STT 成本與延遲過高 | 使用者等待、營運成本失控 | Release A 不依賴 STT；Release B 限制 15 分鐘、單次成本上限、配額與快取。 |
| LLM 回傳非預期格式 | 翻譯結果不可渲染 | JSON Schema 驗證、最多重試一次、失敗可觀測。 |
| 字幕時間軸品質不穩 | 播放與文字不同步 | MVP 以句子同步為最低保障；word timestamps 只作條件式增強。 |
| 播放器時間回傳不穩 | 高亮錯誤或 UI 卡頓 | 降低更新頻率至足夠的同步精度，播放器失聯時退化為靜態字幕。 |
| 匿名濫用或成本突增 | 服務被大量提交，超過 provider 預算 | installation／IP 配額、單一 in-flight 任務、429 error code、STT／LLM 前置攔截。 |
| Release A／B 契約混用 | 未核准的 STT 路徑進入正式版本 | 以 release flag、`transcriptSource` 與 D1／D2／D3 gate 控制；Release A 不產生 `stt`。 |
| 範圍持續擴大 | MVP 延期 | 任何新功能必須直接改善「首次學習閉環」或延後至 Post-MVP。 |

---

## 13. Post-MVP Backlog

### P1：核心體驗增強

- 單句 A-B Loop、循環次數、語速調整。
- 穩定的 word-level 高亮、單字點擊跳轉。
- 即點即查、生詞本、例句、發音音檔、CEFR 與片語。
- 剪貼簿提示、Share Extension、Shorts 與播放清單。
- 學習歷史、帳號與跨裝置同步。

### P2：進階學習與商業化

- 跟讀錄音、發音評分、流暢度分析。
- 多語言來源與目標語言、多模型 fallback。
- 離線字幕、離線音訊與更長影片。
- 會員、額度、付費與社群功能。

---

## 14. 待決策事項

以下項目必須有明確 owner、決策證據與 deadline；未完成時不得宣稱對應 Release 已支援：

| ID | 決策 | 阻擋版本 | Owner | Deadline |
| :--- | :--- | :--- | :--- | :--- |
| **D1** | 符合法務與平台政策的無字幕音訊取得方式 | Release B | PO + 法務 | M3 開始前 |
| **D2** | caption／LLM provider、STT provider（若開啟 B）、單次任務成本上限 | LLM：Release A；STT：Release B | PO + Uhura + R2D2 | LLM 在 M1 前；STT 在 M3 前 |
| **D3** | Release A／B 各 20 支標準化測試影片、語言品質 reviewer 與測試環境 | Release A／B 各自 | PO + QA | Release A 在 M1 前；Release B 在 M3 前 |
| **D4** | 匿名配額初始值：5 次／installation／24h、20 次／IP／24h、最多 1 個 in-flight job | Release A | PO + R2D2 | M2 上線前 |
| **D5** | raw audio 24 小時內刪除、衍生 learning cache 7 天 TTL 的 purge 證據 | Release A | Uhura + R2D2 | M2 上線前 |
| **D6** | 15 分鐘影片上限是否適用首批測試；若不足先調整測試資料，不直接放寬上限 | Release A／B | PO | M1 開始前 |

M1 只需完成 D2 的 LLM／caption 部分與 D3 的 Release A 測試資料；D1 與 STT 相關 D2／D3 僅阻擋 M3 Release B，不阻擋 Release A。

---

## 15. Release A contract freeze

#1717 的跨 iOS／Backend state、transition、error、async 與 idempotency 規格凍結於 [`docs/contracts/release-a-contract.md`](docs/contracts/release-a-contract.md)；machine-readable wire contract、fixtures 與 readback verifier 位於 [`contracts/release-a`](contracts/release-a)。該 package 只適用 Release A caption-first path，不代表 D1／D2／D3 已完成，也不得用來啟用 `transcribing` 或 STT。
