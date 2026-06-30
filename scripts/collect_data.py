# -*- coding: utf-8 -*-
"""
StockRadar V7 Static Collector
輸出 GitHub Pages 可直接讀取的 JSON：
- docs/data/market.json
- docs/data/summary.json
- docs/data/sectors.json
- docs/data/stocks.json
- docs/data/new_high.json
- docs/data/price_history.json
- docs/data/meta.json

預設：今年 1/1 到昨天
市場：TWSE 上市 + TPEx 上櫃
每天都算：不再只抓 >80
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests


TWSE_MI_INDEX = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TWSE_FMTQIK = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
TPEX_DAILY = "https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php"


DEFAULT_SECTOR_MAP = [
    ("2330","台積電","半導體/晶圓代工"),("2454","聯發科","IC設計"),("2303","聯電","半導體/晶圓代工"),
    ("2337","旺宏","記憶體"),("2408","南亞科","記憶體"),("2344","華邦電","記憶體"),("4967","十銓","記憶體模組"),("6531","愛普*","記憶體/IP"),
    ("4958","臻鼎-KY","PCB"),("2313","華通","PCB"),("2368","金像電","PCB"),("3037","欣興","PCB/載板"),("3189","景碩","PCB/載板"),("8046","南電","PCB/載板"),
    ("2383","台光電","CCL/銅箔基板"),("6213","聯茂","CCL/銅箔基板"),("6274","台燿","CCL/銅箔基板"),
    ("2308","台達電","電源/散熱/AI供應鏈"),("3017","奇鋐","散熱"),("3324","雙鴻","散熱"),
    ("6669","緯穎","AI Server"),("2382","廣達","AI Server"),("3231","緯創","AI Server"),("2356","英業達","AI Server"),("2317","鴻海","AI Server/組裝"),
    ("3661","世芯-KY","ASIC/IP"),("3443","創意","ASIC/IP"),("3035","智原","ASIC/IP"),
    ("2345","智邦","網通/交換器"),("6285","啟碁","網通"),("3450","聯鈞","光通訊"),("3081","聯亞","光通訊"),("6442","光聖","光通訊"),("4979","華星光","光通訊"),
    ("3711","日月光投控","封測"),("2449","京元電子","封測"),("6147","頎邦","封測"),("2327","國巨*","被動元件"),("2492","華新科","被動元件"),
    ("1802","台玻","玻璃/材料"),("1303","南亞","塑化/材料"),("1717","長興","化工/材料"),
    ("2360","致茂","測試設備"),("6223","旺矽","測試介面"),("6187","萬潤","設備"),("3665","貿聯-KY","連接線/連接器"),("6279","胡連","連接器"),
    ("3714","富采","LED/光電"),("3481","群創","面板"),("2409","友達","面板"),("3008","大立光","光學鏡頭"),
    ("1605","華新","電線電纜"),("1513","中興電","重電"),("1514","亞力","重電"),("1504","東元","馬達/電機"),
    ("2603","長榮","航運"),("2609","陽明","航運"),("2615","萬海","航運"),("2002","中鋼","鋼鐵"),("2027","大成鋼","鋼鐵"),("2014","中鴻","鋼鐵"),
    ("2404","漢唐","工程/廠務"),("4919","新唐","MCU/IC設計"),
    ("6488","環球晶","矽晶圓"),("5483","中美晶","矽晶圓/太陽能"),("3105","穩懋","砷化鎵/PA"),("8086","宏捷科","砷化鎵/PA"),
    ("3260","威剛","記憶體模組"),("8299","群聯","記憶體控制IC"),("5347","世界","半導體/晶圓代工"),("3680","家登","半導體設備/材料"),
]


def log(msg: str) -> None:
    print(msg, flush=True)


def parse_date(v: str) -> pd.Timestamp:
    if v == "yesterday":
        return pd.Timestamp(date.today() - timedelta(days=1))
    if v == "today":
        return pd.Timestamp(date.today())
    return pd.Timestamp(v)


def num(x):
    if x is None:
        return np.nan
    s = str(x).replace(",", "").replace("--", "").replace("+", "").replace("X", "").strip()
    if not s:
        return np.nan
    try:
        return float(s)
    except Exception:
        return np.nan


def roc_date_to_timestamp(s):
    parts = str(s).split("/")
    if len(parts) != 3:
        return None
    return pd.Timestamp(int(parts[0]) + 1911, int(parts[1]), int(parts[2]))


def to_roc(dt: pd.Timestamp) -> str:
    dt = pd.Timestamp(dt)
    return f"{dt.year - 1911}/{dt.month:02d}/{dt.day:02d}"


def ym_iter(start: pd.Timestamp, end: pd.Timestamp):
    y, m = start.year, start.month
    while y < end.year or (y == end.year and m <= end.month):
        yield y, m
        m += 1
        if m == 13:
            y += 1
            m = 1


def ensure_sector_map(config_dir: Path) -> pd.DataFrame:
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "sector_map.csv"
    if not path.exists():
        pd.DataFrame(DEFAULT_SECTOR_MAP, columns=["stock_id", "stock_name", "sector"]).to_csv(path, index=False, encoding="utf-8-sig")
    df = pd.read_csv(path, dtype={"stock_id": str})
    df["stock_id"] = df["stock_id"].astype(str).str.zfill(4)
    return df


def get_json(url: str, params: dict, cache_path: Path, sleep_sec: float = 0.4):
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    headers = {
        "User-Agent": "Mozilla/5.0 StockRadar-V7",
        "Accept": "application/json,text/plain,*/*",
    }
    r = requests.get(url, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    time.sleep(sleep_sec)
    return data


def fetch_market_month(year: int, month: int, cache_dir: Path) -> pd.DataFrame:
    data = get_json(TWSE_FMTQIK, {"date": f"{year}{month:02d}01", "response": "json"}, cache_dir / f"FMTQIK_{year}{month:02d}.json")
    fields = data.get("fields", [])
    rows = []
    for row in data.get("data", []):
        d = dict(zip(fields, row))
        dt = roc_date_to_timestamp(d.get("日期") or row[0])
        if dt is None:
            continue
        rows.append({
            "date": dt,
            "trade_value": num(d.get("成交金額")),
            "taiex_close": num(d.get("發行量加權股價指數")),
            "taiex_change": num(d.get("漲跌點數")),
        })
    return pd.DataFrame(rows)


def calc_market_temperature(market: pd.DataFrame) -> pd.DataFrame:
    df = market.copy().sort_values("date")
    df["ma5"] = df["taiex_close"].rolling(5, min_periods=1).mean()
    df["ma10"] = df["taiex_close"].rolling(10, min_periods=1).mean()
    df["ret3"] = df["taiex_close"].pct_change(3).fillna(0)
    df["trade_value_ma5"] = df["trade_value"].rolling(5, min_periods=1).mean()
    sigmoid = lambda x: 1 / (1 + np.exp(-x))
    trend = 35 * (df["taiex_close"] > df["ma5"]).astype(float) + 20 * (df["ma5"] > df["ma10"]).astype(float)
    momentum = 25 * sigmoid(df["ret3"].fillna(0) * 50)
    value = 20 * sigmoid(((df["trade_value"] / df["trade_value_ma5"]) - 1).replace([np.inf, -np.inf], np.nan).fillna(0) * 4)
    df["temperature"] = (trend + momentum + value).clip(0, 100).ewm(alpha=0.35, adjust=False).mean().clip(0, 100)
    df["market_status"] = np.select([df["temperature"] >= 80, df["temperature"] >= 65], ["研究", "觀察"], default="保守")
    return df


def find_table(data, req):
    for t in data.get("tables", []) or []:
        f = t.get("fields", [])
        if all(x in f for x in req):
            return f, t.get("data", [])
    f = data.get("fields", [])
    if all(x in f for x in req):
        return f, data.get("data", [])
    raise RuntimeError("cannot find table")


def fetch_twse_daily(dt: pd.Timestamp, cache_dir: Path) -> pd.DataFrame:
    dt = pd.Timestamp(dt)
    data = get_json(
        TWSE_MI_INDEX,
        {"date": dt.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json"},
        cache_dir / f"TWSE_{dt.strftime('%Y%m%d')}.json",
    )
    fields, rows = find_table(data, ["證券代號", "證券名稱", "成交金額"])
    out = []
    for row in rows:
        d = dict(zip(fields, row))
        sid = str(d.get("證券代號", "")).strip()
        if not sid.isdigit() or len(sid) != 4:
            continue
        tv = num(d.get("成交金額"))
        if pd.isna(tv):
            continue
        out.append({
            "date": dt,
            "exchange": "TWSE",
            "stock_id": sid.zfill(4),
            "stock_name": str(d.get("證券名稱", "")).strip(),
            "trade_value": tv,
            "volume": num(d.get("成交股數")),
            "open": num(d.get("開盤價")),
            "high": num(d.get("最高價")),
            "low": num(d.get("最低價")),
            "close": num(d.get("收盤價")),
            "change": num(d.get("漲跌價差")),
        })
    return pd.DataFrame(out)


def fetch_tpex_daily(dt: pd.Timestamp, cache_dir: Path) -> pd.DataFrame:
    dt = pd.Timestamp(dt)
    data = get_json(
        TPEX_DAILY,
        {"l": "zh-tw", "o": "json", "d": to_roc(dt), "se": "EW", "s": "0,asc,0"},
        cache_dir / f"TPEX_{dt.strftime('%Y%m%d')}.json",
    )
    rows = data.get("aaData") or data.get("data") or []
    fields = data.get("fields")
    if not rows:
        return pd.DataFrame()
    if not isinstance(fields, list) or not fields or isinstance(fields[0], list):
        fields = ["代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低", "成交股數", "成交金額", "成交筆數"]
    out = []
    for row in rows:
        if not isinstance(row, list):
            continue
        d = dict(zip(fields, row))
        sid = str(d.get("代號", "")).strip()
        if not sid.isdigit() or len(sid) != 4:
            continue
        tv = num(d.get("成交金額"))
        if pd.isna(tv):
            continue
        out.append({
            "date": dt,
            "exchange": "TPEX",
            "stock_id": sid.zfill(4),
            "stock_name": str(d.get("名稱", "")).strip(),
            "trade_value": tv,
            "volume": num(d.get("成交股數")),
            "open": num(d.get("開盤")),
            "high": num(d.get("最高")),
            "low": num(d.get("最低")),
            "close": num(d.get("收盤")),
            "change": num(d.get("漲跌")),
        })
    return pd.DataFrame(out)


def fetch_all_daily(dt: pd.Timestamp, cache_dir: Path) -> pd.DataFrame:
    frames = []
    try:
        df = fetch_twse_daily(dt, cache_dir)
        if not df.empty:
            frames.append(df)
    except Exception as e:
        log(f"TWSE skip {dt.date()}: {e}")
    try:
        df = fetch_tpex_daily(dt, cache_dir)
        if not df.empty:
            frames.append(df)
    except Exception as e:
        log(f"TPEX skip {dt.date()}: {e}")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def add_indicators(all_daily: pd.DataFrame) -> pd.DataFrame:
    df = all_daily.sort_values(["stock_id", "date"]).copy()
    g = df.groupby("stock_id")
    df["ma5"] = g["close"].transform(lambda s: s.rolling(5, min_periods=1).mean())
    df["ma20"] = g["close"].transform(lambda s: s.rolling(20, min_periods=1).mean())
    df["ret5"] = g["close"].pct_change(5).fillna(0)
    df["trade_value_ma20"] = g["trade_value"].transform(lambda s: s.rolling(20, min_periods=1).mean())
    df["prev_20d_high"] = g["close"].transform(lambda s: s.shift(1).rolling(20, min_periods=5).max())
    df["prev_60d_high"] = g["close"].transform(lambda s: s.shift(1).rolling(60, min_periods=20).max())
    df["is_20d_high"] = (df["close"] > df["prev_20d_high"]).fillna(False)
    df["is_60d_high"] = (df["close"] > df["prev_60d_high"]).fillna(False)
    return df


def calc_stock_temperature(top_df: pd.DataFrame, n: int) -> pd.DataFrame:
    df = top_df.copy()
    sigmoid = lambda x: 1 / (1 + np.exp(-x))
    trend = 25 * (df["close"] > df["ma5"]).astype(float) + 20 * (df["ma5"] > df["ma20"]).astype(float)
    momentum = 20 * sigmoid(df["ret5"].fillna(0) * 25)
    volume = 20 * sigmoid(((df["trade_value"] / df["trade_value_ma20"]) - 1).replace([np.inf, -np.inf], np.nan).fillna(0) * 3)
    rank_strength = 10 * ((n + 1 - df["rank"]) / n).clip(0, 1)
    high_bonus = 15 * df["is_20d_high"].astype(float) + 10 * df["is_60d_high"].astype(float)
    df["stock_temperature"] = (trend + momentum + volume + rank_strength + high_bonus).clip(0, 100)
    return df


def daily_sector_heat(day_df: pd.DataFrame, n: int) -> pd.DataFrame:
    df = day_df[day_df["rank"] <= n].copy()
    if df.empty:
        return pd.DataFrame()
    df["rank_weight"] = n + 1 - df["rank"]
    df["trade_value_100m"] = df["trade_value"] / 100_000_000
    df["weighted_score"] = df["trade_value_100m"] * df["rank_weight"]
    sec = df.groupby(["date", "sector"], as_index=False).agg(
        stock_count=("stock_id", "nunique"),
        appear_rows=("stock_id", "count"),
        high20_count=("is_20d_high", "sum"),
        high60_count=("is_60d_high", "sum"),
        avg_stock_temperature=("stock_temperature", "mean"),
        total_trade_value_100m=("trade_value_100m", "sum"),
        weighted_score=("weighted_score", "sum"),
        avg_rank=("rank", "mean"),
        best_rank=("rank", "min"),
    )
    sec["score_base"] = sec["weighted_score"] / sec["weighted_score"].max() * 100
    sec["new_high_score"] = sec["high20_count"] + sec["high60_count"] * 1.5
    sec["score"] = sec["score_base"] * 0.65 + sec["avg_stock_temperature"].fillna(0) * 0.20 + (sec["new_high_score"] / max(1, sec["new_high_score"].max()) * 100) * 0.15
    return sec.sort_values(["date", "score"], ascending=[True, False])


def daily_stock_heat(day_df: pd.DataFrame, n: int) -> pd.DataFrame:
    df = day_df[day_df["rank"] <= n].copy()
    if df.empty:
        return pd.DataFrame()
    df["rank_weight"] = n + 1 - df["rank"]
    df["trade_value_100m"] = df["trade_value"] / 100_000_000
    df["weighted_score"] = df["trade_value_100m"] * df["rank_weight"]
    df["new_high_score"] = df["is_20d_high"].astype(int) + df["is_60d_high"].astype(int) * 1.5
    df["score_base"] = df["weighted_score"] / df["weighted_score"].max() * 100
    df["score"] = df["score_base"] * 0.50 + df["stock_temperature"] * 0.35 + (df["new_high_score"] / max(1, df["new_high_score"].max()) * 100) * 0.15
    return df.sort_values(["date", "score"], ascending=[True, False])


def add_momentum(sec: pd.DataFrame) -> pd.DataFrame:
    df = sec.copy().sort_values(["sector", "date"])
    df["prev_score"] = df.groupby("sector")["score"].shift(1)
    df["momentum"] = (df["score"] - df["prev_score"]).fillna(0)
    return df.sort_values(["date", "score"], ascending=[True, False])


def to_json_records(df: pd.DataFrame, path: Path):
    out = df.copy()
    for c in out.columns:
        if c == "date":
            out[c] = pd.to_datetime(out[c]).dt.strftime("%Y-%m-%d")
        if c == "stock_id":
            out[c] = out[c].astype(str).str.zfill(4)
    path.write_text(out.where(pd.notnull(out), None).to_json(orient="records", force_ascii=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=f"{date.today().year}-01-01")
    parser.add_argument("--end", default="yesterday")
    parser.add_argument("--top-n", type=int, default=120)
    parser.add_argument("--top-signal-n", type=int, default=20)
    parser.add_argument("--lookback-days", type=int, default=100)
    parser.add_argument("--out-dir", default="docs/data")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--cache-dir", default=".cache")
    args = parser.parse_args()

    start = parse_date(args.start)
    end = parse_date(args.end)
    out_dir = Path(args.out_dir)
    cache_dir = Path(args.cache_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sector_map = ensure_sector_map(Path(args.config_dir))

    log(f"StockRadar V7 static: {start.date()} ~ {end.date()}")

    market_frames = []
    for y, m in ym_iter(start, end):
        log(f"fetch market {y}-{m:02d}")
        market_frames.append(fetch_market_month(y, m, cache_dir))
    market = pd.concat(market_frames, ignore_index=True).drop_duplicates("date").sort_values("date")
    market = market[(market["date"] >= start) & (market["date"] <= end)]
    market = calc_market_temperature(market)

    all_start = start - pd.Timedelta(days=args.lookback_days)
    daily_frames = []
    for dt in pd.date_range(all_start, end, freq="D"):
        df = fetch_all_daily(dt, cache_dir)
        if not df.empty:
            daily_frames.append(df)
            log(f"daily {dt.date()} rows={len(df)}")
    all_daily = pd.concat(daily_frames, ignore_index=True)
    all_daily = all_daily.merge(sector_map[["stock_id", "sector"]], on="stock_id", how="left")
    all_daily["sector"] = all_daily["sector"].fillna("未分類")
    all_daily = add_indicators(all_daily)

    top_rows = []
    for dt in market["date"]:
        day = all_daily[all_daily["date"].eq(dt)].sort_values("trade_value", ascending=False).head(args.top_n).copy()
        if day.empty:
            continue
        day = day.reset_index(drop=True)
        day["rank"] = np.arange(1, len(day) + 1)
        top_rows.append(day)
    top_df = pd.concat(top_rows, ignore_index=True)
    top_df = calc_stock_temperature(top_df, args.top_signal_n)

    sec_days, stock_days = [], []
    for dt, group in top_df.groupby("date"):
        sec_days.append(daily_sector_heat(group, args.top_signal_n))
        stock_days.append(daily_stock_heat(group, args.top_signal_n))
    sectors = add_momentum(pd.concat(sec_days, ignore_index=True))
    stocks = pd.concat(stock_days, ignore_index=True)
    new_high = top_df[(top_df["rank"] <= args.top_signal_n) & ((top_df["is_20d_high"]) | (top_df["is_60d_high"]))].sort_values(["date", "rank"])

    focus_ids = stocks["stock_id"].astype(str).unique().tolist()
    price_history = all_daily[all_daily["stock_id"].astype(str).isin(focus_ids)].copy()

    summary_rows = []
    for _, mr in market.iterrows():
        dt = mr["date"]
        day_sec = sectors[sectors["date"].eq(dt)].sort_values("score", ascending=False)
        day_mom = sectors[sectors["date"].eq(dt)].sort_values("momentum", ascending=False)
        summary_rows.append({
            "date": pd.Timestamp(dt).strftime("%Y-%m-%d"),
            "market_temperature": float(mr["temperature"]),
            "market_status": mr["market_status"],
            "top_sector": day_sec.iloc[0]["sector"] if not day_sec.empty else "",
            "top_sector_score": day_sec.iloc[0]["score"] if not day_sec.empty else None,
            "top_momentum_sector": day_mom.iloc[0]["sector"] if not day_mom.empty else "",
            "top_momentum": day_mom.iloc[0]["momentum"] if not day_mom.empty else None,
            "new_high_count_top20": int(new_high[new_high["date"].eq(dt)].shape[0]),
        })
    summary = pd.DataFrame(summary_rows)

    to_json_records(market, out_dir / "market.json")
    to_json_records(summary, out_dir / "summary.json")
    to_json_records(sectors, out_dir / "sectors.json")
    to_json_records(stocks, out_dir / "stocks.json")
    to_json_records(new_high, out_dir / "new_high.json")
    to_json_records(price_history, out_dir / "price_history.json")

    meta = {
        "start": start.strftime("%Y-%m-%d"),
        "end": end.strftime("%Y-%m-%d"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "GitHub Pages static, TWSE+TPEX, all trade days, stock temperature",
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
