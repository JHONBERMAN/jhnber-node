#!/usr/bin/env python3
"""X-INTELLIGENCE : JHONBER — NODE v4.0 — Hyperliquid Edition"""
import json, time, os, sys, re
from datetime import datetime, timezone
from urllib.request import urlopen, Request

WHALE_ALERT_API_KEY = os.environ.get("WHALE_ALERT_API_KEY", "YOUR_KEY")
OUTPUT_FILE = "data.json"
POLL_INTERVAL = 60

def safe_fetch(url, timeout=20, method="GET", data=None):
    try:
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Content-Type": "application/json"}
        if data: req = Request(url, headers=headers, data=data if isinstance(data,bytes) else data.encode(), method="POST")
        else: req = Request(url, headers=headers)
        return urlopen(req, timeout=timeout).read().decode()
    except Exception as e:
        print(f"    ⚠ {url[:50]}... → {e}"); return None

def safe_json(url, timeout=20):
    raw = safe_fetch(url, timeout)
    if raw:
        try: return json.loads(raw)
        except: pass
    return None

def hl_post(req_type):
    body = json.dumps({"type": req_type}).encode()
    raw = safe_fetch("https://api.hyperliquid.xyz/info", data=body)
    if raw:
        try: return json.loads(raw)
        except: pass
    return None

def fetch_hl_prices():
    print("  ⚡ Hyperliquid allMids...")
    mids = hl_post("allMids")
    if not mids: print("    ⚠ HL 실패"); return {}
    r = {}
    for k,s in {"btc_usd":"BTC","eth_usd":"ETH","sol_usd":"SOL","xrp_usd":"XRP"}.items():
        if s in mids:
            try: r[k]=round(float(mids[s]),2); print(f"    ✓ {k}:${r[k]}")
            except: pass
    for k,cands in {"gold":["xyz:GOLD","cash:GOLD"],"silver":["xyz:SILVER","cash:SILVER"],"oil":["xyz:CL","cash:CL","xyz:USOIL"],"brent":["xyz:BRENTOIL","cash:BRENTOIL"],"natgas":["xyz:NG","cash:NG"],"copper":["xyz:COPPER","cash:COPPER","xyz:HG"],"spx":["xyz:USA500","km:USA500"],"ndx":["xyz:XYZ100","km:XYZ100"]}.items():
        for s in cands:
            if s in mids:
                try: r[k]=round(float(mids[s]),2); print(f"    ✓ {k}:${r[k]} ({s})"); break
                except: pass
    for k,cands in {"kospi":["xyz:KOSPI","km:KOSPI"]}.items():
        for s in cands:
            if s in mids:
                try: r[k]=round(float(mids[s]),2); print(f"    ✓ {k}:{r[k]} ({s})"); break
                except: pass
    m7=[]
    for stk,cands in {"AAPL":["cash:AAPL","xyz:AAPL"],"MSFT":["cash:MSFT","xyz:MSFT"],"GOOGL":["cash:GOOGL","xyz:GOOGL"],"AMZN":["cash:AMZN","xyz:AMZN"],"NVDA":["cash:NVDA","xyz:NVDA"],"META":["cash:META","xyz:META"],"TSLA":["cash:TSLA","xyz:TSLA"]}.items():
        for s in cands:
            if s in mids:
                try: p=round(float(mids[s]),2); m7.append({"sym":stk,"price":p,"chg":0}); print(f"    ✓ {stk}:${p}({s})"); break
                except: pass
    r["m7"]=m7
    hip3=[k for k in mids if ":" in k]
    if hip3: print(f"    📋 HIP-3: {len(hip3)}개 — {', '.join(hip3[:20])}...")
    return r

def fetch_yahoo_chg(hl):
    print("  📊 Yahoo 변동률...")
    r={}
    syms={"spx":"^GSPC","ndx":"^NDX","dji":"^DJI","kospi":"^KS11","vix":"^VIX","dxy":"DX-Y.NYB","gold":"GC=F","silver":"SI=F","oil":"CL=F","brent":"BZ=F","natgas":"NG=F","copper":"HG=F","btc_usd":"BTC-USD"}
    for k,s in syms.items():
        d=safe_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=1d&interval=5m")
        if d:
            try:
                m=d["chart"]["result"][0]["meta"]; p=m["regularMarketPrice"]; pv=m["chartPreviousClose"]
                r[k+"_chg"]=round((p-pv)/pv*100,2)
                if k not in hl: r[k]=round(p,2)
            except: pass
        time.sleep(0.15)
    m7c={}
    for s in ["AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA"]:
        d=safe_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=1d&interval=5m")
        if d:
            try: m=d["chart"]["result"][0]["meta"]; m7c[s]=round((m["regularMarketPrice"]-m["chartPreviousClose"])/m["chartPreviousClose"]*100,2)
            except: pass
        time.sleep(0.15)
    r["_m7_chg"]=m7c
    return r

def fetch_fred_dom():
    print("  🏦 FRED+도미넌스...")
    r={}
    raw=safe_fetch("https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS")
    if raw:
        try: r["fed_rate"]=float(raw.strip().split("\n")[-1].split(",")[1]); print(f"    ✓ Fed:{r['fed_rate']}%")
        except: pass
    raw=safe_fetch("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10")
    if raw:
        for l in reversed(raw.strip().split("\n")[1:]):
            try: r["treasury_10y"]=float(l.split(",")[1]); print(f"    ✓ 10Y:{r['treasury_10y']}%"); break
            except: continue
    cg=safe_json("https://api.coingecko.com/api/v3/global")
    if cg:
        try: r["btc_dominance"]=round(cg["data"]["market_cap_percentage"]["btc"],1); print(f"    ✓ Dom:{r['btc_dominance']}%")
        except: pass
    return r

def fetch_deriv(btc):
    print("  🔶 OKX 파생...")
    r={}
    d=safe_json("https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP")
    if d and d.get("data"):
        try: rate=float(d["data"][0]["fundingRate"]); r["funding_rate"]=round(rate*100,4); r["funding_str"]=f"{'+' if rate>=0 else ''}{rate*100:.4f}%"; print(f"    ✓ 펀딩:{r['funding_str']}")
        except: pass
    time.sleep(0.3)
    d=safe_json("https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=5m")
    if d and d.get("data"):
        try: ratio=float(d["data"][0][1]); r["long_pct"]=round(ratio/(1+ratio)*100); r["short_pct"]=100-r["long_pct"]; print(f"    ✓ 롱쇼:{r['long_pct']}/{r['short_pct']}")
        except: pass
    time.sleep(0.3)
    d=safe_json("https://www.okx.com/api/v5/rubik/stat/taker-volume?ccy=BTC&instType=CONTRACTS&period=5m")
    if d and d.get("data"):
        try:
            tb=sum(float(x[1]) for x in d["data"][:20]); ts=sum(float(x[2]) for x in d["data"][:20]); net=tb-ts
            w,sh,f,sr=net*0.35,net*0.25,net*-0.075,net*-0.105; t=round((w+sh+f+sr)*btc)
            a=f'<span style="color:var(--green);font-weight:700;">매수 우세</span> — ${abs(round(w*btc))/1e6:.1f}M 대형매수.' if net>0 else f'<span style="color:var(--red);font-weight:700;">매도 우세</span> — ${abs(t)/1e6:.1f}M.'
            r["cvd"]={"total":t,"whale":round(w*btc),"shark":round(sh*btc),"fish":round(f*btc),"shrimp":round(sr*btc),"buy_volume":round(tb*btc),"sell_volume":round(ts*btc),"btc_price":btc,"source":"OKX","analysis":a}
            print(f"    ✓ CVD:${t/1e6:.1f}M")
        except: pass
    return r

def fetch_kimchi(btc):
    print("  🌶️ 김프...")
    try:
        u=safe_json("https://api.upbit.com/v1/ticker?markets=KRW-BTC"); fx=safe_json("https://api.exchangerate-api.com/v4/latest/USD")
        if u and fx:
            bk=u[0]["trade_price"]; kr=fx["rates"]["KRW"]; g=btc*kr; p=((bk-g)/g)*100
            print(f"    ✓ 김프:{p:+.2f}%"); return {"premium":round(p,2),"btc_krw":round(bk),"btc_global_krw":round(g),"krw_rate":round(kr)}
    except: pass; return None

def fetch_liq(btc):
    print("  💥 청산맵...")
    try:
        oi=safe_json("https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-history?ccy=BTC&period=5m")
        ov=float(oi["data"][0][1]) if oi and oi.get("data") else 0
        print(f"    ✓ 청산:${btc:,.0f}")
        return {"current_price":round(btc),"open_interest":round(ov,2),"price_high":round(btc*1.06),"price_low":round(btc*0.94),"long_liq_zone":{"start":round(btc*0.94),"end":round(btc*0.97),"description":f"${round(btc*0.94):,}~${round(btc*0.97):,}"},"short_liq_zone":{"start":round(btc*1.03),"end":round(btc*1.06),"description":f"${round(btc*1.03):,}~${round(btc*1.06):,}"},"magnet_price":round(btc*0.955)}
    except: return None

def fetch_war():
    print("  ⚔️ 전쟁지수...")
    try:
        rss=safe_fetch("https://news.google.com/rss/headlines/section/topic/WORLD") or ""
        kw=["airstrike","nuclear","assassination","troops deployed","artillery","warship","missile launch","military operation","invasion","bombing","drone strike","naval blockade"]
        c=sum(rss.lower().count(k) for k in kw); s=min(100,c*5)
        lb="CRITICAL" if s>=80 else "HIGH RISK" if s>=50 else "ELEVATED" if s>=20 else "STABLE"
        print(f"    ✓ 전쟁:{s}({lb})"); return {"value":s,"label":lb,"keyword_count":c}
    except: return None

def fetch_cnn():
    print("  😱 CNN...")
    d=safe_json("https://production.dataviz.cnn.io/index/fearandgreed/graphdata")
    if d and d.get("fear_and_greed"):
        try: fg=d["fear_and_greed"]; s=round(fg.get("score",0)); print(f"    ✓ CNN:{s}"); return {"score":s,"rating":fg.get("rating",""),"previous_close":round(fg.get("previous_close",0)),"one_week_ago":round(fg.get("previous_1_week",0)),"one_month_ago":round(fg.get("previous_1_month",0))}
        except: pass
    return None

def fetch_mvrv():
    print("  📐 MVRV...")
    d=safe_json("https://api.blockchain.info/charts/mvrv?timespan=5weeks&rollingAverage=8hours&format=json")
    if d and d.get("values"):
        try:
            v=round(d["values"][-1]["y"],2)
            a=f'MVRV <span style="color:var(--red)">{v}</span> — 과열.' if v>3.5 else f'MVRV <span style="color:var(--gold)">{v}</span> — 수익.' if v>2.5 else f'MVRV <span style="color:var(--green)">{v}</span> — 건강.' if v>1 else f'MVRV <span style="color:var(--cyan)">{v}</span> — 저평가!'
            print(f"    ✓ MVRV:{v}"); return {"value":v,"analysis":a}
        except: pass
    return None

def fetch_alt():
    print("  🔄 알트시즌...")
    raw=safe_fetch("https://www.blockchaincenter.net/en/altcoin-season-index/")
    if raw:
        try:
            m=re.search(r'"month1":\s*(\d+)',raw)
            if m: v=int(m.group(1)); print(f"    ✓ 알트:{v}"); return v
        except: pass
    return 45

def fetch_whales():
    if WHALE_ALERT_API_KEY=="YOUR_KEY":
        import random; n=int(time.time())
        return [{"symbol":"BTC","amount":2500,"amount_usd":325000000,"from":"Unknown","to":"Binance","timestamp":n-120,"to_type":"exchange"},{"symbol":"BTC","amount":1200,"amount_usd":156000000,"from":"Kraken","to":"Unknown","timestamp":n-300},{"symbol":"USDT","amount":80000000,"amount_usd":80000000,"from":"Tether","to":"Binance","timestamp":n-600,"to_type":"exchange"},{"symbol":"ETH","amount":15000,"amount_usd":52500000,"from":"Unknown","to":"Coinbase","timestamp":n-900,"to_type":"exchange"},{"symbol":"USDC","amount":45000000,"amount_usd":45000000,"from":"Circle","to":"Coinbase","timestamp":n-1200,"to_type":"exchange"}]
    d=safe_json(f"https://api.whale-alert.io/v1/transactions?api_key={WHALE_ALERT_API_KEY}&min_value=500000&start={int(time.time())-3600}")
    return d.get("transactions",[]) if d else []

def proc_whales(txs):
    a,ut,uc=[],0,0
    for t in(txs or[]):
        s=t.get("symbol","?").upper(); u=t.get("amount_usd",0)
        if t.get("to_type")=="exchange":
            if s=="USDT":ut+=u
            elif s=="USDC":uc+=u
        a.append({"symbol":s,"amount":t.get("amount",0),"amount_usd":u,"from":t.get("from","?"),"to":t.get("to","?"),"timestamp":t.get("timestamp",0)})
    a.sort(key=lambda x:x["amount_usd"],reverse=True)
    return a[:15],ut,uc

def run_once():
    print(f"\n{'='*50}\n  ⚡ v4.0 Hyperliquid ({datetime.now().strftime('%H:%M:%S')})\n{'='*50}")
    hl=fetch_hl_prices()
    yh=fetch_yahoo_chg(hl)
    fd=fetch_fred_dom()
    market={**hl,**yh,**fd}
    if market.get("m7") and yh.get("_m7_chg"):
        for i in market["m7"]:
            if i["sym"] in yh["_m7_chg"]: i["chg"]=yh["_m7_chg"][i["sym"]]
    if "_m7_chg" in market: del market["_m7_chg"]
    btc=market.get("btc_usd",69000)
    print(f"\n  ★ BTC:${btc:,.2f}")
    dv=fetch_deriv(btc) or {}
    wh,ut,uc=proc_whales(fetch_whales())
    al=fetch_alt(); km=fetch_kimchi(btc); lq=fetch_liq(btc); wr=fetch_war(); mv=fetch_mvrv(); cn=fetch_cnn()
    result={"market":market,"fed_watch":{"rate":market.get("fed_rate",4.50),"treasury_10y":market.get("treasury_10y",4.2)},"funding":{"rate":dv.get("funding_rate",0),"rate_str":dv.get("funding_str","0.00%"),"long_pct":dv.get("long_pct",50),"short_pct":dv.get("short_pct",50)},"cvd":dv.get("cvd",{"total":0,"analysis":"대기중"}),"whale_alerts":wh,"stablecoin_inflow":{"usdt":ut,"usdc":uc,"total":ut+uc,"max_reference":500000000},"altseason":al or 50,"kimchi":km or{"premium":0,"btc_krw":0,"btc_global_krw":0,"krw_rate":1350},"liquidation":lq or{"current_price":round(btc),"open_interest":0,"price_high":round(btc*1.06),"price_low":round(btc*0.94),"long_liq_zone":{"start":round(btc*0.94),"end":round(btc*0.97),"description":"대기중"},"short_liq_zone":{"start":round(btc*1.03),"end":round(btc*1.06),"description":"대기중"},"magnet_price":round(btc*0.955)},"war_index":wr or{"value":50,"label":"UNKNOWN","keyword_count":0},"mvrv":mv or{"value":2.0,"analysis":"수집 지연"},"cnn_fear_greed":cn or{"score":50,"rating":"NEUTRAL","previous_close":50,"one_week_ago":50,"one_month_ago":50},"last_updated":datetime.now(timezone.utc).isoformat()}
    p=os.path.join(os.path.dirname(os.path.abspath(__file__)),OUTPUT_FILE)
    with open(p,"w",encoding="utf-8") as f: json.dump(result,f,ensure_ascii=False,indent=2)
    print(f"\n  💾 저장완료\n  BTC:${btc:,.0f}|SPX:{market.get('spx')}|GOLD:{market.get('gold')}|VIX:{market.get('vix')}")
    if km: print(f"  김프:{km['premium']:+.2f}%")

def run_loop():
    print("="*50+"\n  ⚡ JHONBER NODE v4.0 Hyperliquid\n"+"="*50)
    while True:
        try: run_once(); print(f"\n  ⏳ {POLL_INTERVAL}초...\n"); time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt: sys.exit(0)
        except Exception as e: print(f"  ⚠{e}"); time.sleep(30)

if __name__=="__main__":
    if "--once" in sys.argv: run_once()
    else: run_loop()
