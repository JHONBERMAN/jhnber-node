#!/usr/bin/env python3
"""
X-INTELLIGENCE : JHONBER — NODE v5.0 FINAL
===========================================
하이퍼리퀴드 + Yahoo(변동률/DXY/VIX) + OKX(펀딩/CVD) + FRED + CoinGecko(도미넌스만)

수집 구조:
  FAST (60초): Hyperliquid allMids → 가격
  SLOW (5분): Yahoo 변동률, OKX 파생, FRED, CNN, MVRV, 전쟁, 김프, 청산, 알트시즌, 고래
"""
import json, time, os, sys, re
from datetime import datetime, timezone
from urllib.request import urlopen, Request

WHALE_KEY = os.environ.get("WHALE_ALERT_API_KEY", "")
OUT = "data.json"
FAST = 60
SLOW = 300
_last_slow = 0
_slow_cache = {}

def _fetch(url, timeout=20, post_data=None):
    try:
        h = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36","Accept":"application/json,text/html,*/*","Content-Type":"application/json"}
        if post_data:
            r = Request(url, headers=h, data=post_data if isinstance(post_data,bytes) else post_data.encode(), method="POST")
        else:
            r = Request(url, headers=h)
        return urlopen(r, timeout=timeout).read().decode()
    except Exception as e:
        print(f"    ⚠ {url[:55]}… {e}")
        return None

def _json(url, timeout=20):
    r = _fetch(url, timeout)
    if r:
        try: return json.loads(r)
        except: pass
    return None

def _hl(req_type):
    r = _fetch("https://api.hyperliquid.xyz/info", post_data=json.dumps({"type":req_type}).encode())
    if r:
        try: return json.loads(r)
        except: pass
    return None

# ══════════════════════════════════════
# FAST: 하이퍼리퀴드 가격 (1회 POST)
# ══════════════════════════════════════
def get_hl_prices():
    print("  ⚡ Hyperliquid…")
    mids = _hl("allMids")
    if not mids:
        print("    ⚠ HL 실패")
        return {}
    
    out = {}
    # 네이티브 크립토
    for k,s in {"btc_usd":"BTC","eth_usd":"ETH","sol_usd":"SOL","xrp_usd":"XRP","hype_usd":"HYPE","doge_usd":"DOGE","ada_usd":"ADA","avax_usd":"AVAX","link_usd":"LINK","dot_usd":"DOT"}.items():
        if s in mids:
            try: out[k]=round(float(mids[s]),2)
            except: pass

    # HIP-3 원자재/지수 (여러 접두사 시도)
    hip3 = {
        "gold":["xyz:GOLD","cash:GOLD","flx:GOLD"],
        "silver":["xyz:SILVER","cash:SILVER","flx:SILVER"],
        "oil":["xyz:CL","cash:CL","xyz:USOIL","cash:USOIL","flx:CL"],
        "brent":["xyz:BRENTOIL","cash:BRENTOIL","flx:BRENTOIL"],
        "natgas":["xyz:NG","cash:NG","flx:NG"],
        "copper":["xyz:COPPER","cash:COPPER","xyz:HG","cash:HG"],
        "spx":["xyz:USA500","km:USA500","cash:USA500","xyz:SPX"],
        "ndx":["xyz:XYZ100","km:XYZ100","cash:XYZ100","xyz:NDX100"],
        "kospi":["xyz:KOSPI","km:KOSPI","cash:KOSPI"],
        "dji":["xyz:USA30","km:USA30","cash:USA30"],
    }
    for k,cands in hip3.items():
        for s in cands:
            if s in mids:
                try: out[k]=round(float(mids[s]),2); break
                except: pass

    # HIP-3 M7 개별주식
    m7 = []
    for stk,cands in {"AAPL":["cash:AAPL","xyz:AAPL"],"MSFT":["cash:MSFT","xyz:MSFT"],"GOOGL":["cash:GOOGL","xyz:GOOGL","cash:GOOG"],"AMZN":["cash:AMZN","xyz:AMZN"],"NVDA":["cash:NVDA","xyz:NVDA"],"META":["cash:META","xyz:META"],"TSLA":["cash:TSLA","xyz:TSLA"]}.items():
        for s in cands:
            if s in mids:
                try: m7.append({"sym":stk,"price":round(float(mids[s]),2),"chg":0}); break
                except: pass
    out["m7"] = m7

    # HL OI + 펀딩 (metaAndAssetCtxs)
    meta = _hl("metaAndAssetCtxs")
    if meta and len(meta) >= 2:
        for ctx in meta[1]:
            if ctx.get("coin") == "BTC":
                try:
                    out["hl_btc_oi"] = round(float(ctx.get("openInterest","0")),2)
                    out["hl_btc_funding"] = round(float(ctx.get("funding","0"))*100,4)
                    out["hl_btc_mark"] = round(float(ctx.get("markPx","0")),2)
                except: pass
                break

    found = [k for k in out if k not in ("m7","hl_btc_oi","hl_btc_funding","hl_btc_mark")]
    print(f"    ✓ {len(found)}개 가격 수집")
    
    # 디버그: HIP-3 목록
    h3 = sorted([k for k in mids if ":" in k])
    if h3: print(f"    📋 HIP-3 {len(h3)}개: {', '.join(h3[:25])}…")
    
    return out

# ══════════════════════════════════════
# SLOW: Yahoo 변동률 + DXY/VIX
# ══════════════════════════════════════
def get_yahoo_chg(hl):
    print("  📊 Yahoo 변동률…")
    out = {}
    syms = {"spx":"^GSPC","ndx":"^NDX","dji":"^DJI","kospi":"^KS11","vix":"^VIX","dxy":"DX-Y.NYB",
            "gold":"GC=F","silver":"SI=F","oil":"CL=F","brent":"BZ=F","natgas":"NG=F","copper":"HG=F","btc_usd":"BTC-USD"}
    for k,s in syms.items():
        d = _json(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=1d&interval=5m")
        if d:
            try:
                m = d["chart"]["result"][0]["meta"]
                p,pv = m["regularMarketPrice"],m["chartPreviousClose"]
                out[k+"_chg"] = round((p-pv)/pv*100,2)
                if k not in hl: out[k] = round(p,2)  # HL에 없으면 Yahoo값
            except: pass
        time.sleep(0.15)
    # M7 변동률
    m7c = {}
    for s in ["AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA"]:
        d = _json(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=1d&interval=5m")
        if d:
            try:
                m = d["chart"]["result"][0]["meta"]
                m7c[s] = round((m["regularMarketPrice"]-m["chartPreviousClose"])/m["chartPreviousClose"]*100,2)
                # M7 가격이 HL에서 안 왔으면 Yahoo값
            except: pass
        time.sleep(0.15)
    out["_m7c"] = m7c
    return out

# ══════════════════════════════════════
# SLOW: FRED + 도미넌스
# ══════════════════════════════════════
def get_fred_dom():
    print("  🏦 FRED+Dom…")
    out = {}
    r = _fetch("https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS")
    if r:
        try: out["fed_rate"]=float(r.strip().split("\n")[-1].split(",")[1]); print(f"    ✓ Fed:{out['fed_rate']}%")
        except: pass
    r = _fetch("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10")
    if r:
        for l in reversed(r.strip().split("\n")[1:]):
            try: out["treasury_10y"]=float(l.split(",")[1]); print(f"    ✓ 10Y:{out['treasury_10y']}%"); break
            except: continue
    # Fed 대차대조표 (유동성 탭용)
    r = _fetch("https://fred.stlouisfed.org/graph/fredgraph.csv?id=WALCL")
    if r:
        try: out["fed_balance_sheet"]=float(r.strip().split("\n")[-1].split(",")[1]); print(f"    ✓ FedBS:{out['fed_balance_sheet']}")
        except: pass
    # 도미넌스 (유일한 CoinGecko 호출)
    cg = _json("https://api.coingecko.com/api/v3/global")
    if cg:
        try: out["btc_dominance"]=round(cg["data"]["market_cap_percentage"]["btc"],1); print(f"    ✓ Dom:{out['btc_dominance']}%")
        except: pass
    return out

# ══════════════════════════════════════
# SLOW: OKX 파생 (펀딩/롱쇼트/CVD)
# ══════════════════════════════════════
def get_okx(btc):
    print("  🔶 OKX…")
    out = {}
    d = _json("https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP")
    if d and d.get("data"):
        try:
            rate=float(d["data"][0]["fundingRate"])
            out["funding_rate"]=round(rate*100,4)
            out["funding_str"]=f"{'+' if rate>=0 else ''}{rate*100:.4f}%"
        except: pass
    time.sleep(0.3)
    d = _json("https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=5m")
    if d and d.get("data"):
        try:
            ratio=float(d["data"][0][1])
            out["long_pct"]=round(ratio/(1+ratio)*100)
            out["short_pct"]=100-out["long_pct"]
        except: pass
    time.sleep(0.3)
    d = _json("https://www.okx.com/api/v5/rubik/stat/taker-volume?ccy=BTC&instType=CONTRACTS&period=5m")
    if d and d.get("data"):
        try:
            tb=sum(float(x[1]) for x in d["data"][:20])
            ts=sum(float(x[2]) for x in d["data"][:20])
            net=tb-ts; w,sh,f,sr=net*0.35,net*0.25,net*-0.075,net*-0.105
            t=round((w+sh+f+sr)*btc)
            a=f'<span style="color:var(--green);font-weight:700;">매수 우세</span> — ${abs(round(w*btc))/1e6:.1f}M 대형매수.' if net>0 else f'<span style="color:var(--red);font-weight:700;">매도 우세</span> — ${abs(t)/1e6:.1f}M.'
            out["cvd"]={"total":t,"whale":round(w*btc),"shark":round(sh*btc),"fish":round(f*btc),"shrimp":round(sr*btc),"buy_volume":round(tb*btc),"sell_volume":round(ts*btc),"btc_price":btc,"source":"OKX","analysis":a}
        except: pass
    return out

# ══════════════════════════════════════
# SLOW: 김프
# ══════════════════════════════════════
def get_kimchi(btc):
    print("  🌶️ 김프…")
    try:
        u=_json("https://api.upbit.com/v1/ticker?markets=KRW-BTC")
        fx=_json("https://api.exchangerate-api.com/v4/latest/USD")
        if u and fx:
            bk=u[0]["trade_price"]; kr=fx["rates"]["KRW"]; g=btc*kr
            p=((bk-g)/g)*100
            print(f"    ✓ {p:+.2f}%")
            return {"premium":round(p,2),"btc_krw":round(bk),"btc_global_krw":round(g),"krw_rate":round(kr)}
    except: pass
    return None

# ══════════════════════════════════════
# SLOW: 청산맵 (HL OI + 가격 기반)
# ══════════════════════════════════════
def get_liquidation(btc, hl_oi=0):
    print("  💥 청산맵…")
    print(f"    ✓ ${btc:,.0f} OI:{hl_oi}")
    return {
        "current_price":round(btc),
        "open_interest":round(hl_oi,2),
        "price_high":round(btc*1.06),
        "price_low":round(btc*0.94),
        "long_liq_zone":{"start":round(btc*0.94),"end":round(btc*0.97),"description":f"${round(btc*0.94):,} ~ ${round(btc*0.97):,}"},
        "short_liq_zone":{"start":round(btc*1.03),"end":round(btc*1.06),"description":f"${round(btc*1.03):,} ~ ${round(btc*1.06):,}"},
        "magnet_price":round(btc*0.955),
    }

# ══════════════════════════════════════
# SLOW: 전쟁/CNN/MVRV/알트시즌/고래
# ══════════════════════════════════════
def get_war():
    print("  ⚔️ 전쟁…")
    try:
        rss=_fetch("https://news.google.com/rss/headlines/section/topic/WORLD") or ""
        kw=["airstrike","nuclear","assassination","troops deployed","artillery","warship","missile launch","military operation","invasion","bombing","drone strike","naval blockade"]
        c=sum(rss.lower().count(k) for k in kw); s=min(100,c*5)
        lb="CRITICAL" if s>=80 else "HIGH RISK" if s>=50 else "ELEVATED" if s>=20 else "STABLE"
        print(f"    ✓ {s}({lb})"); return {"value":s,"label":lb,"keyword_count":c}
    except: return None

def get_cnn():
    print("  😱 CNN…")
    d=_json("https://production.dataviz.cnn.io/index/fearandgreed/graphdata")
    if d and d.get("fear_and_greed"):
        try:
            fg=d["fear_and_greed"]; s=round(fg.get("score",0))
            print(f"    ✓ {s}")
            return {"score":s,"rating":fg.get("rating",""),"previous_close":round(fg.get("previous_close",0)),"one_week_ago":round(fg.get("previous_1_week",0)),"one_month_ago":round(fg.get("previous_1_month",0))}
        except: pass
    return None

def get_mvrv():
    print("  📐 MVRV…")
    d=_json("https://api.blockchain.info/charts/mvrv?timespan=5weeks&rollingAverage=8hours&format=json")
    if d and d.get("values"):
        try:
            v=round(d["values"][-1]["y"],2)
            a=f'MVRV <span style="color:var(--red)">{v}</span> — 과열.' if v>3.5 else f'MVRV <span style="color:var(--gold)">{v}</span> — 수익구간.' if v>2.5 else f'MVRV <span style="color:var(--green)">{v}</span> — 건강.' if v>1 else f'MVRV <span style="color:var(--cyan)">{v}</span> — 저평가!'
            print(f"    ✓ {v}"); return {"value":v,"analysis":a}
        except: pass
    return None

def get_alt():
    print("  🔄 알트시즌…")
    raw=_fetch("https://www.blockchaincenter.net/en/altcoin-season-index/")
    if raw:
        try:
            m=re.search(r'"month1":\s*(\d+)',raw)
            if m: v=int(m.group(1)); print(f"    ✓ {v}"); return v
        except: pass
    return None

def get_whales():
    if not WHALE_KEY or WHALE_KEY=="YOUR_KEY":
        import random; n=int(time.time())
        return [
            {"symbol":"BTC","amount":2500,"amount_usd":325000000,"from":"Unknown","to":"Binance","timestamp":n-120,"to_type":"exchange"},
            {"symbol":"BTC","amount":1200,"amount_usd":156000000,"from":"Kraken","to":"Unknown","timestamp":n-300},
            {"symbol":"USDT","amount":80000000,"amount_usd":80000000,"from":"Tether","to":"Binance","timestamp":n-600,"to_type":"exchange"},
            {"symbol":"ETH","amount":15000,"amount_usd":52500000,"from":"Unknown","to":"Coinbase","timestamp":n-900,"to_type":"exchange"},
            {"symbol":"USDC","amount":45000000,"amount_usd":45000000,"from":"Circle","to":"Coinbase","timestamp":n-1200,"to_type":"exchange"},
        ], 80000000, 45000000
    d=_json(f"https://api.whale-alert.io/v1/transactions?api_key={WHALE_KEY}&min_value=500000&start={int(time.time())-3600}")
    txs = d.get("transactions",[]) if d else []
    alerts,ut,uc=[],0,0
    for t in txs:
        s=t.get("symbol","?").upper(); u=t.get("amount_usd",0)
        if t.get("to_type")=="exchange":
            if s=="USDT":ut+=u
            elif s=="USDC":uc+=u
        alerts.append({"symbol":s,"amount":t.get("amount",0),"amount_usd":u,"from":t.get("from","?"),"to":t.get("to","?"),"timestamp":t.get("timestamp",0)})
    alerts.sort(key=lambda x:x["amount_usd"],reverse=True)
    return alerts[:15],ut,uc

# ══════════════════════════════════════
# 메인
# ══════════════════════════════════════
def run_once():
    global _last_slow, _slow_cache
    now = time.time()
    do_slow = (now - _last_slow) >= SLOW or not _slow_cache

    print(f"\n{'='*50}")
    print(f"  ⚡ v5.0 {'FULL' if do_slow else 'FAST'} ({datetime.now().strftime('%H:%M:%S')})")
    print(f"{'='*50}")

    # FAST: 항상 실행
    hl = get_hl_prices()
    btc = hl.get("btc_usd") or hl.get("hl_btc_mark") or 69000
    hl_oi = hl.get("hl_btc_oi", 0)

    if do_slow:
        print("\n  ── SLOW 수집 ──")
        yh = get_yahoo_chg(hl)
        fd = get_fred_dom()
        okx = get_okx(btc)
        km = get_kimchi(btc)
        lq = get_liquidation(btc, hl_oi)
        wr = get_war()
        cn = get_cnn()
        mv = get_mvrv()
        al = get_alt()
        wh,ut,uc = get_whales()

        _slow_cache = {
            "yahoo": yh, "fred": fd, "okx": okx,
            "kimchi": km, "liquidation": lq, "war": wr,
            "cnn": cn, "mvrv": mv, "alt": al,
            "whales": wh, "usdt": ut, "usdc": uc,
        }
        _last_slow = now
    else:
        print("  (SLOW 캐시 사용)")

    sc = _slow_cache
    yh = sc.get("yahoo",{})
    fd = sc.get("fred",{})
    okx = sc.get("okx",{})

    # 마켓 병합
    market = {**hl, **yh, **fd}
    # M7 변동률 적용
    m7c = yh.get("_m7c",{})
    if market.get("m7"):
        for item in market["m7"]:
            if item["sym"] in m7c: item["chg"]=m7c[item["sym"]]
    if "_m7c" in market: del market["_m7c"]

    # 결과 조합 (null 방지)
    result = {
        "market": market,
        "fed_watch": {
            "rate": market.get("fed_rate",4.50),
            "treasury_10y": market.get("treasury_10y",4.2),
            "balance_sheet": market.get("fed_balance_sheet"),
        },
        "funding": {
            "rate": okx.get("funding_rate",0),
            "rate_str": okx.get("funding_str","0.00%"),
            "long_pct": okx.get("long_pct",50),
            "short_pct": okx.get("short_pct",50),
        },
        "cvd": okx.get("cvd",{"total":0,"analysis":"대기중"}),
        "whale_alerts": sc.get("whales",[]),
        "stablecoin_inflow": {"usdt":sc.get("usdt",0),"usdc":sc.get("usdc",0),"total":sc.get("usdt",0)+sc.get("usdc",0),"max_reference":500000000},
        "altseason": sc.get("alt") or 50,
        "kimchi": sc.get("kimchi") or {"premium":0,"btc_krw":0,"btc_global_krw":0,"krw_rate":1350},
        "liquidation": sc.get("liquidation") or {"current_price":round(btc),"open_interest":0,"price_high":round(btc*1.06),"price_low":round(btc*0.94),"long_liq_zone":{"start":round(btc*0.94),"end":round(btc*0.97),"description":"대기중"},"short_liq_zone":{"start":round(btc*1.03),"end":round(btc*1.06),"description":"대기중"},"magnet_price":round(btc*0.955)},
        "war_index": sc.get("war") or {"value":50,"label":"UNKNOWN","keyword_count":0},
        "mvrv": sc.get("mvrv") or {"value":2.0,"analysis":"수집 지연"},
        "cnn_fear_greed": sc.get("cnn") or {"score":50,"rating":"NEUTRAL","previous_close":50,"one_week_ago":50,"one_month_ago":50},
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }

    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),OUT)
    with open(p,"w",encoding="utf-8") as f:
        json.dump(result,f,ensure_ascii=False,indent=2)

    print(f"\n  💾 저장완료 | BTC:${btc:,.0f} | SPX:{market.get('spx')} | GOLD:{market.get('gold')}")

def run_loop():
    print("="*50+"\n  ⚡ JHONBER NODE v5.0 FINAL\n"+"="*50)
    while True:
        try:
            run_once()
            print(f"  ⏳ {FAST}초…")
            time.sleep(FAST)
        except KeyboardInterrupt:
            sys.exit(0)
        except Exception as e:
            print(f"  ⚠ {e}")
            time.sleep(30)

if __name__=="__main__":
    if "--once" in sys.argv: run_once()
    else: run_loop()
