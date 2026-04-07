# 🏆 Yahoo Fantasy MLB Bot — 設定指南

每天自動推送本季累積得分排名到 Discord，使用你聯盟的自訂計分規則。

---

## 📋 你的聯盟計分規則（已設定好）

### 打者
| 項目 | 分值 |
|------|------|
| Runs (R) | +1.0 |
| Singles (1B) | +2.6 |
| Doubles (2B) | +5.2 |
| Triples (3B) | +7.8 |
| Home Runs (HR) | +10.4 |
| RBI | +1.0 |
| Stolen Bases (SB) | +3.5 |
| Caught Stealing (CS) | -0.5 |
| Walks (BB) | +2.6 |
| Hit By Pitch (HBP) | +2.6 |
| Strikeouts (K) | -0.5 |
| GIDP | -1.0 |

### 投手
| 項目 | 分值 |
|------|------|
| Wins (W) | +3.0 |
| Saves (SV) | +6.0 |
| Outs (OUT) | +1.0 |
| Hits allowed (H) | -1.3 |
| Earned Runs (ER) | -2.5 |
| Walks (BB) | -1.3 |
| Hit Batters (HBP) | -1.3 |
| Strikeouts (K) | +2.0 |
| GIDP | +1.0 |
| Holds (HLD) | +5.0 |
| Quality Starts (QS) | +6.0 |

---

## 🚀 設定步驟

### 第一步：申請 Yahoo Fantasy API

1. 前往 [Yahoo Developer Network](https://developer.yahoo.com/apps/)
2. 點擊 **「Create an App」**
3. 填寫以下資訊：
   - **Application Name**：任意名稱（例如 `My Fantasy Bot`）
   - **Application Type**：選 `Installed Application`
   - **Callback Domain**：填 `oob`
   - **API Permissions**：勾選 `Fantasy Sports` → 選 `Read`
4. 建立完成後，你會得到：
   - `Client ID`（Consumer Key）
   - `Client Secret`（Consumer Secret）

---

### 第二步：取得 Refresh Token

在你的電腦執行：

```bash
pip install requests
python get_token.py
```

程式會：
1. 開啟瀏覽器讓你授權
2. 你貼上授權碼
3. 自動印出你的 `Refresh Token` 和 `League ID`

> ⚠️ Refresh Token 要妥善保存，不要公開！

---

### 第三步：建立 Discord Webhook

1. 開啟你的 Discord 伺服器
2. 選擇你想推送的頻道，點右鍵 → **「編輯頻道」**
3. 點選 **「整合」** → **「Webhook」** → **「建立 Webhook」**
4. 複製 **Webhook URL**（格式：`https://discord.com/api/webhooks/...`）

---

### 第四步：建立 GitHub Repository

1. 前往 [GitHub](https://github.com) 建立一個新的 **private** repository（建議設為私有）
2. 把以下檔案上傳到 repo 根目錄：
   ```
   yahoo_fantasy_bot.py
   get_token.py          （可選，本機用完可刪）
   .github/
     workflows/
       daily.yml
   ```

---

### 第五步：設定 GitHub Secrets

在你的 GitHub repo 頁面：
**Settings → Secrets and variables → Actions → New repository secret**

新增以下 5 個 Secrets：

| Secret 名稱 | 值 |
|------------|-----|
| `YAHOO_CLIENT_ID` | Yahoo App 的 Client ID |
| `YAHOO_CLIENT_SECRET` | Yahoo App 的 Client Secret |
| `YAHOO_REFRESH_TOKEN` | 第二步取得的 Refresh Token |
| `YAHOO_LEAGUE_ID` | 你的 League Key（格式如 `mlb.l.123456`） |
| `DISCORD_WEBHOOK_URL` | 第三步的 Discord Webhook URL |

---

### 第六步：測試執行

1. 在 GitHub repo 點選 **「Actions」** 標籤
2. 找到 **「Yahoo Fantasy MLB Daily Bot」**
3. 點 **「Run workflow」** → **「Run workflow」**
4. 等待約 1 分鐘後查看執行結果
5. 到你的 Discord 頻道確認訊息已送達！

---

## 📅 執行時間

程式設定為每天 **台灣時間早上 9:00** 自動執行。

如果想改時間，編輯 `.github/workflows/daily.yml` 中的 cron 設定：
```yaml
- cron: "0 1 * * *"   # UTC 01:00 = 台灣 09:00
```
[Cron 時間計算工具](https://crontab.guru/)

---

## 📱 Discord 訊息預覽

每天會收到 3 則 Embed 訊息：

```
📊 本季累積得分 TOP 10 | 2025/04/07
 1. 🏏 打 Shohei Ohtani (LAD)    542.3pts  🟢 ▲2
 2. ⚾ 投 Tarik Skubal (DET)     498.1pts  ⚪ –
 3. 🏏 打 Aaron Judge (NYY)      471.6pts  🔴 ▼1
...

🔥 今日得分 TOP 10
 1. 🏏 打 Fernando Tatis Jr. (SD)  +28.4pts
...

🥶 今日得分 BOTTOM 5（今日有上場）
 1. ⚾ 投 某投手 (TOR)  -15.2pts
...
```

---

## 🛠 常見問題

**Q: 出現 `401 Unauthorized` 錯誤？**
重新執行 `get_token.py` 取得新的 Refresh Token，更新 GitHub Secret。

**Q: 找不到球員或 League？**
確認 `YAHOO_LEAGUE_ID` 格式是否正確（應為 `mlb.l.xxxxxx`）。

**Q: 想改成每天幾點推送？**
修改 `.github/workflows/daily.yml` 的 cron 時間。

---

*由 Claude 自動生成 • Yahoo Fantasy MLB Bot*
