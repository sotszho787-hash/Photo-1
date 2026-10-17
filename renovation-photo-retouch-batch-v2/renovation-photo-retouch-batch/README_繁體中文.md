# 裝修相片一鍵批量後製｜Renovation Photo Retouch Batch v2

Windows 10 / Windows 11。根據原有 `renovation-photo-retouch` Skill 製作的本機批量執行套件。

## 一次安裝、以後一鍵執相

1. **解壓縮整個 ZIP** 到例如 `C:\RenovationPhotoRetouchBatch`（路徑最好唔好放 OneDrive 即時同步目錄）。
2. Windows 安裝 **Python 3.10 或以上**（python.org；如需要，安裝時剔選 **Add Python to PATH**）。
3. 雙擊 `install_windows.bat`，第一次要上網安裝 Pillow、NumPy。安裝完成之後批量執相可以完全離線。
4. 將所有原始裝修相放入 `workspace\INPUT`，可以連子資料夾。**或者**將一個相片 ZIP / 資料夾拖落 `RUN_BATCH.bat`，就唔需要將相片複製去 INPUT。
5. 雙擊 `RUN_BATCH.bat`，等待批次完成。程式會逐張讀取、處理、寫入品質報告；唔會等待 ChatGPT 回應。
6. 喺 `workspace\OUTPUT` 搵到最新 `YYYYMMDD_HHMMSS_xxxxxx_MUJI_Batch.zip`，旁邊仲有同名批次資料夾供你逐張檢查。

注意：**先等相片或 ZIP 完全複製完**再啟動，A 模式唔係持續監察。每次執行都會新增一份批次，不會刪除舊批次，亦不會覆寫原相。如果 INPUT 放咗舊相，下次執行會再次處理佢哋；請自行搬走已完成批次相片。

## 成品結構

```text
workspace/OUTPUT/
  20261017_120000_abc123_MUJI_Batch.zip   <- 可以分享／備份嘅成品
  20261017_120000_abc123/
    Faithful/                  <- 版本 1：忠實 MUJI 低調調色
    Aesthetic/                 <- 版本 2：較光亮、唯美，但不造假陽光
    Before_After/
      Faithful/                <- 原圖對比忠實調色
      Aesthetic/               <- 原圖對比唯美調色
    Reports/
      Faithful/                <- 個別相片品質分析 JSON
      Aesthetic/
    Batch_Report.csv           <- Excel 可開啟；檢查失敗及提示
    Batch_Report.json          <- 完整檔案清單
    process.log                <- 簡短操作紀錄
```

預設支援 JPG/JPEG、PNG、WEBP、TIFF（單張、8-bit RGB/RGBA 等標準模式）。不支援 RAW/HEIC/16-bit TIFF/CMYK、超過 48 MP 大圖；這些會列入失敗清單而不會改動原圖。遇上壞檔仍會處理其餘圖片。ZIP 中只提取支援圖片，並拒絕路徑穿越和非一般檔案。

## 色彩與現場真實性

- **Faithful 忠實調色**：較低強度，改善曝光、灰階、自然木色，保留現場層次。
- **Aesthetic 較光唯美**：強度較高，仍使用相同非生成式像素運算；唔係 AI 重畫或變裝修效果圖。
- 保持原有幾何位置、傢俬、裝修、木紋、窗景。嚴禁 Inpainting、Generative Fill、添加裝飾、合成假陽光。
- 無法靠像素亮度可靠分辨「窗戶」、「白牆」同「燈具」，**因此自動執行時預設光源未知**，沒有人工確認不加方向性窗光。
- 需要確認真窗：用文字編輯器打開 `lighting_overrides.csv`，寫例如 `bedroom.jpg,window,right`。CSV 的 `filename` 可以係 INPUT 內相對路徑，如 `TuenMun/bedroom.jpg`。方向以相片畫面左右為準。**唔肯定就留空**。
- 原相永不覆寫。後製相保留肉眼觀看的尺寸、ICC profile（如適用），但為免方向標籤造成二次旋轉及傳遞 GPS 等私隱，**不複製 EXIF**。有些格式在 Pillow 輸出會重新編碼；影像不會位元組不變。建議用原檔另行保留工程記錄。
- QA 包括明暗統計、白平衡估計、疑似過曝、無法確認的光源提示。**自動檢查不能代替目視驗收**。尤其要核對燈源位置、木材實際顏色、窗外細節。

## Codex 配合方法

1. `install_windows.bat` 安裝完之後，如果想 Codex 自動識別 `$renovation-photo-retouch`，**可選擇**雙擊 `INSTALL_CODEX_SKILL.bat`：程式會問你是否安裝；假如已有相同名稱 Skill，會先備份再覆蓋。安裝位置是 `%USERPROFILE%\.agents\skills\renovation-photo-retouch`。
2. 喺 **本機可讀取照片資料夾** 的 Codex workspace 使用：

   ```text
   $renovation-photo-retouch 請在本機執行 Batch v2，
   輸入路徑 C:\Photos\Batch1.zip，勿改動任何原相。
   完成後只報告成功／失敗張數、需檢查嘅項目及成品 ZIP 路徑，
   唔好將相片 Base64 或完整執行 log 貼入對話。
   ```

3. 亦可直接在專案根目錄執行：

   ```powershell
   .\.venv\Scripts\python.exe -m app.batch --input "C:\Photos\Batch1.zip"
   ```

**重要：** Codex 雲端環境唔會自動存取你 Windows 硬碟。要用本機執行 Codex 或透過雲端可讀的工作區檔案；後者涉及上傳及其他平台限制。最穩定做法係直接雙擊 Windows 腳本，不需每張相都傳畀模型。

## 6.2MB / 4MB 訊息超限點解決？

原錯誤屬**模型／工具訊息解碼上限**（畫面上係 6,195,180 bytes vs 4,194,304 bytes），唔代表 Windows 無法開 6MB 相片。

本工具只傳 **檔案路徑** 畀本機 Python 執行，不在 Codex 對話嵌入圖片 Base64。`process.log` 同 Before/After 都直接落本機磁碟，不以工具結果大量輸出。就算圖片 ZIP 本身大過 4MB，亦唔會因此塞爆文字訊息；不過上傳到雲端服務另有各自附件大小限制。

## 命令行選項

```powershell
# 把 INPUT 整批處理：
.\.venv\Scripts\python.exe -m app.batch

# 指定單一相片 ZIP：
.\.venv\Scripts\python.exe -m app.batch --input "D:\SitePhotos\photos.zip"

# 指定輸出路徑：
.\.venv\Scripts\python.exe -m app.batch --input "D:\SitePhotos" --output "D:\Retouched"
```

`config.json` 可修改 `faithful_strength`（預設 0.45）、`aesthetic_strength`（預設 0.82）等；兩者 0–1，忠實強度需比唯美低。唔建議一開始過度提高。根據不同光源判斷再逐張人手 review 更可靠。

## 故障排查

- **Python/py is not recognized**：重新安裝 Python 3.10+，啟用 PATH，或使用 Python Launcher。
- **PermissionError**：不要放在受管制資料夾；確保可以讀照片、寫 OUTPUT；關閉佔用中的檔案。
- **輸入 ZIP 錯誤**：確保係正常 ZIP，完成複製，且非加密、不含危險路徑。
- **有失敗相**：睇 `Batch_Report.csv` 同 `process.log`；程式會繼續處理其餘圖片。
- **需要原始 RAW/HEIC**：先用具色彩管理工具匯出高質 JPG / PNG，再執行本批次。
- **出圖唔夠唯美**：先 review 5 張，用 `config.json` 微調強度，勿用虛構窗光代替真實攝影質感。

此工具係保守本機攝影調色助手，不保證每張光源的語義識別或專業人手後製質量。正式客戶交付前應目視檢查。
