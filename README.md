# StockRadar V7 - GitHub Pages 靜態版

## 目標

不用開電腦、不用 Google Cloud 付費。

架構：

```text
GitHub Actions 每天自動執行 Python
↓
抓 TWSE + TPEx
↓
產生 JSON
↓
GitHub Pages 網站顯示
↓
手機直接開
```

## 第一次部署

1. 到 GitHub 建立新 Repository，例如：

```text
stockradar
```

2. 把這包所有內容上傳到 Repository。

3. 到 GitHub：

```text
Settings → Pages
```

設定：

```text
Source: Deploy from a branch
Branch: main
Folder: /docs
```

4. 到：

```text
Actions
```

允許 workflow。

5. 手動執行：

```text
Update StockRadar Data
```

6. 幾分鐘後打開 GitHub Pages 網址。

## 每天自動更新

`.github/workflows/update.yml` 已設定台灣時間約 17:10 更新。

也可以在 GitHub Actions 裡手動按：

```text
Run workflow
```

## 網站怎麼用最有價值

順序固定：

1. 先看大盤溫度。
2. 看 Momentum 第一的族群。
3. 看該族群是否有新高家數。
4. 點代表股，看個股溫度與收盤價線。
5. 找「剛轉強」而不是「已經最熱」的族群。

## 資料

- 上市：TWSE
- 上櫃：TPEx
- 每個交易日都算
- Top20 代表資金集中股
- 個股溫度：趨勢、5日動能、成交值放大、排行、新高

## 注意

這是研究工具，不是買賣建議。
