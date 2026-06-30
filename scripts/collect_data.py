# -*- coding: utf-8 -*-
import argparse,json,time,requests
from pathlib import Path
from datetime import date,datetime,timedelta
import numpy as np,pandas as pd

TWSE_MI="https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TWSE_MK="https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
TPEX="https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php"

def log(x): print(x,flush=True)
def dparse(x):
    if x=="yesterday": return pd.Timestamp(date.today()-timedelta(days=1))
    if x=="today": return pd.Timestamp(date.today())
    return pd.Timestamp(x)
def n(x):
    s=str(x).replace(",","").replace("--","").replace("+","").replace("X","").strip()
    if not s or s=="nan": return np.nan
    try: return float(s)
    except: return np.nan
def roc(s):
    p=str(s).split("/")
    if len(p)!=3: return None
    return pd.Timestamp(int(p[0])+1911,int(p[1]),int(p[2]))
def toroc(dt):
    dt=pd.Timestamp(dt); return f"{dt.year-1911}/{dt.month:02d}/{dt.day:02d}"
def months(a,b):
    y,m=a.year,a.month
    while y<b.year or (y==b.year and m<=b.month):
        yield y,m
        m+=1
        if m==13: y+=1;m=1
def get(url,params,cache):
    cache.parent.mkdir(parents=True,exist_ok=True)
    if cache.exists(): return json.loads(cache.read_text(encoding="utf-8"))
    r=requests.get(url,params=params,headers={"User-Agent":"StockRadarV8","Accept":"application/json,*/*"},timeout=30)
    r.raise_for_status(); data=r.json()
    cache.write_text(json.dumps(data,ensure_ascii=False),encoding="utf-8")
    time.sleep(.35); return data
def market_month(y,m,cache):
    data=get(TWSE_MK,{"date":f"{y}{m:02d}01","response":"json"},cache/f"FMTQIK_{y}{m:02d}.json")
    f=data.get("fields",[]); rows=[]
    for row in data.get("data",[]):
        d=dict(zip(f,row)); dt=roc(d.get("日期") or row[0])
        if dt is not None: rows.append({"date":dt,"trade_value":n(d.get("成交金額")),"taiex_close":n(d.get("發行量加權股價指數")),"taiex_change":n(d.get("漲跌點數"))})
    return pd.DataFrame(rows)
def mtemp(m):
    df=m.copy().sort_values("date")
    df["ma5"]=df.taiex_close.rolling(5,min_periods=1).mean(); df["ma10"]=df.taiex_close.rolling(10,min_periods=1).mean()
    df["ret3"]=df.taiex_close.pct_change(3).fillna(0); df["tvma5"]=df.trade_value.rolling(5,min_periods=1).mean()
    sig=lambda x:1/(1+np.exp(-x))
    score=35*(df.taiex_close>df.ma5).astype(float)+20*(df.ma5>df.ma10).astype(float)+25*sig(df.ret3*50)+20*sig(((df.trade_value/df.tvma5)-1).replace([np.inf,-np.inf],np.nan).fillna(0)*4)
    df["temperature"]=score.clip(0,100).ewm(alpha=.35,adjust=False).mean().clip(0,100)
    df["market_status"]=np.select([df.temperature>=80,df.temperature>=65],["研究","觀察"],default="保守")
    return df
def find(data,req):
    for t in data.get("tables",[]) or []:
        f=t.get("fields",[])
        if all(x in f for x in req): return f,t.get("data",[])
    f=data.get("fields",[])
    if all(x in f for x in req): return f,data.get("data",[])
    raise RuntimeError("no table")
def twse(dt,cache):
    dt=pd.Timestamp(dt); data=get(TWSE_MI,{"date":dt.strftime("%Y%m%d"),"type":"ALLBUT0999","response":"json"},cache/f"TWSE_{dt.strftime('%Y%m%d')}.json")
    f,rows=find(data,["證券代號","證券名稱","成交金額"]); out=[]
    for row in rows:
        d=dict(zip(f,row)); sid=str(d.get("證券代號","")).strip()
        if not sid.isdigit() or len(sid)!=4: continue
        tv=n(d.get("成交金額"))
        if pd.isna(tv): continue
        out.append({"date":dt,"exchange":"TWSE","stock_id":sid.zfill(4),"stock_name":str(d.get("證券名稱","")).strip(),"trade_value":tv,"volume":n(d.get("成交股數")),"open":n(d.get("開盤價")),"high":n(d.get("最高價")),"low":n(d.get("最低價")),"close":n(d.get("收盤價")),"change":n(d.get("漲跌價差"))})
    return pd.DataFrame(out)
def tpex(dt,cache):
    dt=pd.Timestamp(dt); data=get(TPEX,{"l":"zh-tw","o":"json","d":toroc(dt),"se":"EW","s":"0,asc,0"},cache/f"TPEX_{dt.strftime('%Y%m%d')}.json")
    rows=data.get("aaData") or data.get("data") or []
    fields=data.get("fields")
    if not rows: return pd.DataFrame()
    if not isinstance(fields,list) or not fields or isinstance(fields[0],list):
        fields=["代號","名稱","收盤","漲跌","開盤","最高","最低","成交股數","成交金額","成交筆數"]
    out=[]
    for row in rows:
        if not isinstance(row,list): continue
        d=dict(zip(fields,row)); sid=str(d.get("代號","")).strip()
        if not sid.isdigit() or len(sid)!=4: continue
        tv=n(d.get("成交金額"))
        if pd.isna(tv): continue
        out.append({"date":dt,"exchange":"TPEX","stock_id":sid.zfill(4),"stock_name":str(d.get("名稱","")).strip(),"trade_value":tv,"volume":n(d.get("成交股數")),"open":n(d.get("開盤")),"high":n(d.get("最高")),"low":n(d.get("最低")),"close":n(d.get("收盤")),"change":n(d.get("漲跌"))})
    return pd.DataFrame(out)
def daily(dt,cache):
    arr=[]
    try:
        x=twse(dt,cache)
        if not x.empty: arr.append(x)
    except Exception as e: log(f"TWSE skip {pd.Timestamp(dt).date()} {e}")
    try:
        x=tpex(dt,cache)
        if not x.empty: arr.append(x)
    except Exception as e: log(f"TPEX skip {pd.Timestamp(dt).date()} {e}")
    return pd.concat(arr,ignore_index=True) if arr else pd.DataFrame()
def indicators(df):
    df=df.sort_values(["stock_id","date"]).copy(); g=df.groupby("stock_id")
    df["ma5"]=g.close.transform(lambda s:s.rolling(5,min_periods=1).mean()); df["ma20"]=g.close.transform(lambda s:s.rolling(20,min_periods=1).mean())
    df["ret5"]=g.close.pct_change(5).fillna(0); df["tvma20"]=g.trade_value.transform(lambda s:s.rolling(20,min_periods=1).mean())
    df["prev20"]=g.close.transform(lambda s:s.shift(1).rolling(20,min_periods=5).max()); df["prev60"]=g.close.transform(lambda s:s.shift(1).rolling(60,min_periods=20).max())
    df["is_20d_high"]=(df.close>df.prev20).fillna(False); df["is_60d_high"]=(df.close>df.prev60).fillna(False)
    return df
def stock_temp(df,n=20):
    df=df.copy(); sig=lambda x:1/(1+np.exp(-x))
    trend=25*(df.close>df.ma5).astype(float)+20*(df.ma5>df.ma20).astype(float)
    mom=20*sig(df.ret5.fillna(0)*25); vol=20*sig(((df.trade_value/df.tvma20)-1).replace([np.inf,-np.inf],np.nan).fillna(0)*3)
    rank=10*((n+1-df["rank"])/n).clip(0,1); high=15*df.is_20d_high.astype(float)+10*df.is_60d_high.astype(float)
    df["stock_temperature"]=(trend+mom+vol+rank+high).clip(0,100)
    return df
def sector_heat(day,n=20):
    df=day[day["rank"]<=n].copy()
    if df.empty: return pd.DataFrame()
    df["rw"]=n+1-df["rank"]; df["tv100"]=df.trade_value/100000000; df["ws"]=df.tv100*df.rw
    sec=df.groupby(["date","sector"],as_index=False).agg(stock_count=("stock_id","nunique"),appear_rows=("stock_id","count"),high20_count=("is_20d_high","sum"),high60_count=("is_60d_high","sum"),avg_stock_temperature=("stock_temperature","mean"),total_trade_value_100m=("tv100","sum"),weighted_score=("ws","sum"),avg_rank=("rank","mean"),best_rank=("rank","min"))
    sec["score_base"]=sec.weighted_score/sec.weighted_score.max()*100; sec["new_high_score"]=sec.high20_count+sec.high60_count*1.5
    sec["score"]=sec.score_base*.65+sec.avg_stock_temperature.fillna(0)*.20+(sec.new_high_score/max(1,sec.new_high_score.max())*100)*.15
    return sec.sort_values(["date","score"],ascending=[True,False])
def stock_heat(day,n=20):
    df=day[day["rank"]<=n].copy()
    if df.empty: return pd.DataFrame()
    df["rw"]=n+1-df["rank"]; df["tv100"]=df.trade_value/100000000; df["ws"]=df.tv100*df.rw
    df["nhs"]=df.is_20d_high.astype(int)+df.is_60d_high.astype(int)*1.5; df["score_base"]=df.ws/df.ws.max()*100
    df["score"]=df.score_base*.50+df.stock_temperature*.35+(df.nhs/max(1,df.nhs.max())*100)*.15
    return df.sort_values(["date","score"],ascending=[True,False])
def add_mom(sec):
    df=sec.copy().sort_values(["sector","date"]); df["prev_score"]=df.groupby("sector").score.shift(1); df["momentum"]=(df.score-df.prev_score).fillna(0)
    return df.sort_values(["date","score"],ascending=[True,False])
def outjson(df,path):
    d=df.copy()
    for c in d.columns:
        if c=="date": d[c]=pd.to_datetime(d[c]).dt.strftime("%Y-%m-%d")
        if c=="stock_id": d[c]=d[c].astype(str).str.zfill(4)
    path.write_text(d.where(pd.notnull(d),None).to_json(orient="records",force_ascii=False),encoding="utf-8")
def main():
    p=argparse.ArgumentParser(); p.add_argument("--start",default=f"{date.today().year}-01-01"); p.add_argument("--end",default="yesterday")
    p.add_argument("--top-n",type=int,default=120); p.add_argument("--top-signal-n",type=int,default=20); p.add_argument("--lookback-days",type=int,default=100)
    p.add_argument("--out-dir",default="docs/data"); p.add_argument("--config-dir",default="config"); p.add_argument("--cache-dir",default=".cache")
    a=p.parse_args(); start=dparse(a.start); end=dparse(a.end); out=Path(a.out_dir); cache=Path(a.cache_dir); out.mkdir(parents=True,exist_ok=True)
    smap=Path(a.config_dir)/"sector_map.csv"
    if not smap.exists(): raise FileNotFoundError("config/sector_map.csv missing")
    sm=pd.read_csv(smap,dtype={"stock_id":str}); sm["stock_id"]=sm.stock_id.astype(str).str.zfill(4)
    log(f"StockRadar V8 {start.date()} ~ {end.date()}")
    market=pd.concat([market_month(y,m,cache) for y,m in months(start,end)],ignore_index=True).drop_duplicates("date").sort_values("date")
    market=market[(market.date>=start)&(market.date<=end)]; market=mtemp(market)
    arr=[]
    for dt in pd.date_range(start-pd.Timedelta(days=a.lookback_days),end,freq="D"):
        x=daily(dt,cache)
        if not x.empty:
            arr.append(x); log(f"daily {dt.date()} {len(x)}")
    all_daily=pd.concat(arr,ignore_index=True).merge(sm[["stock_id","sector"]],on="stock_id",how="left")
    all_daily["sector"]=all_daily.sector.fillna("未分類"); all_daily=indicators(all_daily)
    tops=[]
    for dt in market.date:
        day=all_daily[all_daily.date.eq(dt)].sort_values("trade_value",ascending=False).head(a.top_n).copy()
        if day.empty: continue
        day=day.reset_index(drop=True); day["rank"]=np.arange(1,len(day)+1); tops.append(day)
    top=stock_temp(pd.concat(tops,ignore_index=True),a.top_signal_n)
    sectors=add_mom(pd.concat([sector_heat(g,a.top_signal_n) for _,g in top.groupby("date")],ignore_index=True))
    stocks=pd.concat([stock_heat(g,a.top_signal_n) for _,g in top.groupby("date")],ignore_index=True)
    nh=top[(top["rank"]<=a.top_signal_n)&((top.is_20d_high)|(top.is_60d_high))].sort_values(["date","rank"])
    focus=stocks.stock_id.astype(str).unique().tolist(); price=all_daily[all_daily.stock_id.astype(str).isin(focus)].copy()
    summary=[]
    for _,r in market.iterrows():
        ds=sectors[sectors.date.eq(r.date)].sort_values("score",ascending=False); dm=sectors[sectors.date.eq(r.date)].sort_values("momentum",ascending=False)
        summary.append({"date":r.date.strftime("%Y-%m-%d"),"market_temperature":float(r.temperature),"market_status":r.market_status,"top_sector":ds.iloc[0].sector if not ds.empty else "", "top_sector_score":ds.iloc[0].score if not ds.empty else None, "top_momentum_sector":dm.iloc[0].sector if not dm.empty else "", "top_momentum":dm.iloc[0].momentum if not dm.empty else None, "new_high_count_top20":int(nh[nh.date.eq(r.date)].shape[0])})
    summary=pd.DataFrame(summary)
    script=[]
    if not summary.empty:
        s=summary.iloc[-1]; ds=sectors[sectors.date.eq(pd.Timestamp(s.date))].sort_values("score",ascending=False).head(5); dm=sectors[sectors.date.eq(pd.Timestamp(s.date))].sort_values("momentum",ascending=False).head(1)
        script=[{"title":"今日市場","text":f"大盤溫度 {s.market_temperature:.0f}，狀態：{s.market_status}。"},{"title":"接棒族群","text":f"{dm.iloc[0].sector if not dm.empty else '--'} Momentum {dm.iloc[0].momentum:.1f}，優先觀察是否連續轉強。" if not dm.empty else "--"},{"title":"最熱族群","text":"、".join([f"{x.sector}({x.score:.0f})" for _,x in ds.iterrows()])},{"title":"新高狀態","text":f"Top20 內創 20/60 日新高共 {s.new_high_count_top20} 檔。"}]
    for name,df in [("market",market),("summary",summary),("sectors",sectors),("stocks",stocks),("new_high",nh),("price_history",price),("daily_script",pd.DataFrame(script))]:
        outjson(df,out/f"{name}.json")
    meta={"start":start.strftime("%Y-%m-%d"),"end":end.strftime("%Y-%m-%d"),"updated_at":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),"mode":"V8 Final GitHub Pages static, TWSE+TPEX"}
    (out/"meta.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
if __name__=="__main__": main()
