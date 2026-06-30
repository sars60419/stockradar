# StockRadar V8 Final

完成內容：
- GitHub Pages 靜態網站
- GitHub Actions 自動更新
- 不用開電腦、不用 Google Cloud
- TWSE + TPEx，上市 + 上櫃
- 每個交易日都算
- 大盤溫度、族群熱度、族群 Momentum
- 個股溫度、新高股票、收盤價線
- 今日劇本

## 上傳
上傳：
- docs
- scripts
- config
- README.md
- requirements.txt
- workflow_update.yml
- GITHUB_WORKFLOW_SETUP.md

## Pages
Settings → Pages：
- Source: Deploy from a branch
- Branch: main
- Folder: /docs

## Actions
依照 `GITHUB_WORKFLOW_SETUP.md` 建立 `.github/workflows/update.yml`。
