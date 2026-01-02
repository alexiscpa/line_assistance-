# LINE Echo Bot

一個簡單的 LINE Echo Bot，使用 Python 和 Flask 建立。

## 功能

- 接收用戶訊息並原封不動地回覆（Echo）

## 安裝步驟

### 1. 安裝 uv

如果你還沒有安裝 uv，請先安裝：

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. 安裝相依套件

```bash
uv pip install -e .
```

### 3. 設定環境變數

複製 `.env.example` 為 `.env` 並填入你的 LINE Channel 資訊：

```bash
cp .env.example .env
```

編輯 `.env` 檔案，填入以下資訊：

```
LINE_CHANNEL_ACCESS_TOKEN=你的_Channel_Access_Token
LINE_CHANNEL_SECRET=你的_Channel_Secret
PORT=5000
```

### 4. 取得 LINE Channel 資訊

1. 前往 [LINE Developers Console](https://developers.line.biz/console/)
2. 建立一個新的 Provider 或選擇現有的
3. 建立一個新的 Messaging API Channel
4. 在 Channel 設定頁面取得：
   - Channel Secret（在 Basic settings）
   - Channel Access Token（在 Messaging API，需要先發行）

### 5. 設定 Webhook URL

1. 在 LINE Developers Console 的 Messaging API 設定頁面
2. 設定 Webhook URL：`https://your-domain.com/callback`
3. 啟用 "Use webhook"
4. 關閉 "Auto-reply messages"（可選）

## 執行

```bash
python app.py
```

伺服器會在 `http://0.0.0.0:5000` 啟動。

## 部署

你需要將此應用部署到一個有公開 URL 的伺服器，因為 LINE 需要透過 Webhook 來傳送訊息。

推薦的部署選項：
- Railway
- Render
- Heroku
- Google Cloud Run
- AWS EC2

## 測試

1. 確保伺服器正在運行
2. 使用 LINE 官方帳號的 QR Code 加入好友
3. 傳送訊息給 Bot
4. Bot 會回覆相同的訊息

## 專案結構

```
line_bot_simple/
├── app.py              # 主程式
├── pyproject.toml      # uv 套件管理設定
├── .env.example        # 環境變數範例
└── README.md           # 說明文件
```
