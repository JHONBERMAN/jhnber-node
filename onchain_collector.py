#!/usr/bin/env python3
"""
X-INTELLIGENCE : JHONBER — NODE
통합 데이터 수집기 v3.0

핵심 설계:
  - BTC 가격은 Yahoo Finance에서 1번만 수집 → 김프/청산맵/CVD에 재활용
  - CoinGecko 호출은 도미넌스 1번만 (레이트리밋 방지)
  - 모든 필드에 null 방지 기본값
  - Binance 차단 → OKX 대체
"""
import json, time, os, sys, re
from datetime import datetime, timezone
from urllib.request import urlopen, Request

WHALE_ALERT_API_KEY = os.environ.get("WHALE_ALERT_API_KEY", "YOUR_KEY")
OUTPUT_FILE = "data.json"
POLL_INTERVAL = 60

def safe_fetch(url, timeout=20):
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept": "text/html,application/json,*/*"})
        return urlopen(req, timeout=timeout).read().decode()
    except Exception as e:
        print(f"    ⚠ fetch 실패: {url[:60]}... → {e}")
        return None

def safe_json(url, timeout=20):
    raw = safe_fetch(url, timeout)
    if raw:
        try: return json.loads(raw)
        except: pass
    return None

def fetch_market_data():
    print("  📊 시장 데이터 수집 중...")
    result = {}
    symbols = {"spx":"^GSPC","ndx":"^NDX","dji":"^DJI","kospi":"^KS11","vix":"^VIX","dxy":"DX-Y.NYB","gold":"GC=F","silver":"SI=F","oil":"CL=F","brent":"BZ=F","natgas":"NG=F","copper":"HG=F","btc_usd":"BTC-USD"}
    for key, sym in symbols.items():
        data = safe_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=5m")
        if data:
            try:
                meta = data["chart"]["result"][0]["meta"]
                p, prev = meta["regularMarketPrice"], meta["chartPreviousClose"]
                result[key] = round(p, 2)
                result[key+"_chg"] = round((p-prev)/prev*100, 2)
                print(f"    ✓ {key}: {result[key]} ({result[key+'_chg']:+.2f}%)")
            except: pass
        time.sleep(0.3)
    print("  💎 M7 수집 중...")
    m7 = []
    for sym in ["AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA"]:
        data = safe_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=5m")
        if data:
            try:
                meta = data["chart"]["result"][0]["meta"]
                p, prev = meta["regularMarketPrice"], meta["chartPreviousClose"]
                m7.append({"sym":sym,"price":round(p,2),"chg":round((p-prev)/prev*100,2)})
                print(f"    ✓ {sym}: ${round(p,2)}")
            except: pass
        time.sleep(0.3)
    result["m7"] = m7
    print("  🏦 FRED 수집 중...")
    raw = safe_fetch("https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS")
    if raw:
        try: result["fed_rate"] = float(raw.strip().split("\\n")[-1].split(",")[1]); print(f"    ✓ Fed: {result['fed_rate']}%")
        except: pass
    raw = safe_fetch("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10")
    if raw:
        for line in reversed(raw.strip().split("\\n")[1:]):
            try: result["treasury_10y"] = float(line.split(",")[1]); print(f"    ✓ 10Y: {result['treasury_10y']}%"); break
            except: continue
    print("  ₿ 도미넌스 수집 중...")
    cg = safe_json("https://api.coingecko.com/api/v3/global")
    if cg:
        try: result["btc_dominance"] = round(cg["data"]["market_cap_percentage"]["btc"], 1); print(f"    ✓ Dom: {result['btc_dominance']}%")
        except: pass
    return result

def fetch_derivatives(btc_price):
    print("  🔶 OKX 파생 수집 중...")
    result = {}
    data = safe_json("https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP")
    if data and data.get("data"):
        try:
            rate = float(data["data"][0]["fundingRate"])
            result["funding_rate"] = round(rate*100, 4)
            result["funding_str"] = f"{'+' if rate>=0 else ''}{rate*100:.4f}%"
            print(f"    ✓ 펀딩: {result['funding_str']}")
        except: pass
    time.sleep(0.3)
    data = safe_json("https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=5m")
    if data and data.get("data"):
        try:
            ratio = float(data["data"][0][1])
            result["long_pct"] = round(ratio/(1+ratio)*100)
            result["short_pct"] = 100-result["long_pct"]
            print(f"    ✓ 롱/쇼트: {result['long_pct']}/{result['short_pct']}")
        except: pass
    time.sleep(0.3)
    data = safe_json("https://www.okx.com/api/v5/rubik/stat/taker-volume?ccy=BTC&instType=CONTRACTS&period=5m")
    if data and data.get("data"):
        try:
            tb = sum(float(r[1]) for r in data["data"][:20])
            ts = sum(float(r[2]) for r in data["data"][:20])
            net = tb - ts
            w,sh,f,sr = net*0.35, net*0.25, net*-0.075, net*-0.105
            t = round((w+sh+f+sr)*btc_price)
            analysis = f'<span style="color:var(--green);font-weight:700;">매수 우세</span> — ${abs(round(w*btc_price))/1e6:.1f}M 대형 매수. <span style="color:var(--gold)">축적</span>.' if net>0 else f'<span style="color:var(--red);font-weight:700;">매도 우세</span> — ${abs(t)/1e6:.1f}M 매도 압력.'
            result["cvd"] = {"total":t,"whale":round(w*btc_price),"shark":round(sh*btc_price),"fish":round(f*btc_price),"shrimp":round(sr*btc_price),"buy_volume":round(tb*btc_price),"sell_volume":round(ts*btc_price),"btc_price":btc_price,"trade_count":len(data["data"]),"source":"OKX","analysis":analysis}
            print(f"    ✓ CVD: ${t/1e6:.1f}M")
        except Exception as e: print(f"    ⚠ CVD: {e}")
    return result

def fetch_kimchi_premium(btc_global_price):
    print("  🌶️ 김프 수집 중...")
    try:
        upbit = safe_json("https://api.upbit.com/v1/ticker?markets=KRW-BTC")
        forex = safe_json("https://api.exchangerate-api.com/v4/latest/USD")
        if upbit and forex:
            btc_krw = upbit[0]["trade_price"]
            krw = forex["rates"]["KRW"]
            g = btc_global_price * krw
            p = ((btc_krw - g) / g) * 100
            print(f"    ✓ 김프: {p:+.2f}%")
            return {"premium":round(p,2),"btc_krw":round(btc_krw),"btc_global_krw":round(g),"krw_rate":round(krw)}
    except Exception as e: print(f"    ⚠ 김프: {e}")
    return None

def fetch_liquidation_estimate(btc_price):
    print("  💥 청산맵 수집 중...")
    try:
        oi_data = safe_json("https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-history?ccy=BTC&period=5m")
        oi = float(oi_data["data"][0][1]) if oi_data and oi_data.get("data") else 0
        print(f"    ✓ 청산맵: ${btc_price:,.0f}")
        return {"current_price":round(btc_price),"open_interest":round(oi,2),"price_high":round(btc_price*1.06),"price_low":round(btc_price*0.94),"long_liq_zone":{"start":round(btc_price*0.94),"end":round(btc_price*0.97),"description":f"${round(btc_price*0.94):,}~${round(btc_price*0.97):,}"},"short_liq_zone":{"start":round(btc_price*1.03),"end":round(btc_price*1.06),"description":f"${round(btc_price*1.03):,}~${round(btc_price*1.06):,}"},"magnet_price":round(btc_price*0.955)}
    except Exception as e: print(f"    ⚠ 청산맵: {e}")
    return None

def fetch_war_index():
    print("  ⚔️ 전쟁지수 수집 중...")
    try:
        rss = safe_fetch("https://news.google.com/rss/headlines/section/topic/WORLD") or ""
        keywords = ["airstrike","nuclear","assassination","troops deployed","artillery","warship","missile launch","military operation","invasion","bombing","drone strike","naval blockade"]
        count = sum(rss.lower().count(kw) for kw in keywords)
        score = min(100, count*5)
        label = "CRITICAL" if score>=80 else "HIGH RISK" if score>=50 else "ELEVATED" if score>=20 else "STABLE"
        print(f"    ✓ 전쟁: {score} ({label})")
        return {"value":score,"label":label,"keyword_count":count}
    except: return None

def fetch_cnn_fear_greed():
    print("  😱 CNN F&G 수집 중...")
    data = safe_json("https://production.dataviz.cnn.io/index/fearandgreed/graphdata")
    if data and data.get("fear_and_greed"):
        try:
            fg = data["fear_and_greed"]
            s = round(fg.get("score",0))
            print(f"    ✓ CNN: {s} ({fg.get('rating','')})")
            return {"score":s,"rating":fg.get("rating",""),"previous_close":round(fg.get("previous_close",0)),"one_week_ago":round(fg.get("previous_1_week",0)),"one_month_ago":round(fg.get("previous_1_month",0))}
        except: pass
    print("    ⚠ CNN 실패")
    return None

def fetch_mvrv():
    print("  📐 MVRV 수집 중...")
    data = safe_json("https://api.blockchain.info/charts/mvrv?timespan=5weeks&rollingAverage=8hours&format=json")
    if data and data.get("values"):
        try:
            v = round(data["values"][-1]["y"], 2)
            a = f'MVRV <span style="color:var(--red)">{v}</span> — 과열.' if v>3.5 else f'MVRV <span style="color:var(--gold)">{v}</span> — 수익구간.' if v>2.5 else f'MVRV <span style="color:var(--green)">{v}</span> — 건강.' if v>1 else f'MVRV <span style="color:var(--cyan)">{v}</span> — 저평가!'
            print(f"    ✓ MVRV: {v}")
            return {"value":v,"analysis":a}
        except: pass
    return None

def fetch_altseason():
    print("  🔄 알트시즌 수집 중...")
    raw = safe_fetch("https://www.blockchaincenter.net/en/altcoin-season-index/")
    if raw:
        try:
            m = re.search(r'"month1":\s*(\d+)', raw)
            if m: v=int(m.group(1)); print(f"    ✓ 알트시즌: {v}"); return v
        except: pass
    print("    ⚠ 알트시즌 폴백")
    return 45

def fetch_whale_alerts():
    if WHALE_ALERT_API_KEY == "YOUR_KEY":
        print("  ⚠ Whale 키 미설정 → 데모")
        import random; now=int(time.time())
        return [{"symbol":"BTC","amount":2500,"amount_usd":325000000,"from":"Unknown","to":"Binance","timestamp":now-120,"to_type":"exchange"},{"symbol":"BTC","amount":1200,"amount_usd":156000000,"from":"Kraken","to":"Unknown","timestamp":now-300,"from_type":"exchange"},{"symbol":"USDT","amount":80000000,"amount_usd":80000000,"from":"Tether Treasury","to":"Binance","timestamp":now-600,"to_type":"exchange"},{"symbol":"ETH","amount":15000,"amount_usd":52500000,"from":"Unknown","to":"Coinbase","timestamp":now-900,"to_type":"exchange"},{"symbol":"USDC","amount":45000000,"amount_usd":45000000,"from":"Circle","to":"Coinbase","timestamp":now-1200,"to_type":"exchange"},{"symbol":"BTC","amount":800,"amount_usd":104000000,"from":"Unknown","to":"Upbit","timestamp":now-1500,"to_type":"exchange"},{"symbol":"USDT","amount":random.randint(50,200)*1000000,"amount_usd":random.randint(50,200)*1000000,"from":"Unknown","to":"Binance","timestamp":now-1800,"to_type":"exchange"}]
    data = safe_json(f"https://api.whale-alert.io/v1/transactions?api_key={WHALE_ALERT_API_KEY}&min_value=500000&start={int(time.time())-3600}")
    return data.get("transactions",[]) if data else []

def process_whales(txs):
    alerts, usdt, usdc = [], 0, 0
    for tx in (txs or []):
        s = tx.get("symbol","?").upper()
        u = tx.get("amount_usd",0)
        if tx.get("to_type")=="exchange":
            if s=="USDT": usdt+=u
            elif s=="USDC": usdc+=u
        alerts.append({"symbol":s,"amount":tx.get("amount",0),"amount_usd":u,"from":tx.get("from","?"),"to":tx.get("to","?"),"timestamp":tx.get("timestamp",0)})
    alerts.sort(key=lambda x:x["amount_usd"],reverse=True)
    return alerts[:15], usdt, usdc

def run_once():
    print(f"\n{'='*50}\n  🔍 v3.0 수집 시작 ({datetime.now().strftime('%H:%M:%S')})\n{'='*50}")
    market = fetch_market_data() or {}
    btc = market.get("btc_usd", 69000)
    print(f"\n  ★ BTC 기준가: ${btc:,.2f}")
    deriv = fetch_derivatives(btc) or {}
    txs = fetch_whale_alerts()
    whales, usdt, usdc = process_whales(txs)
    alt = fetch_altseason()
    kimchi = fetch_kimchi_premium(btc)
    liq = fetch_liquidation_estimate(btc)
    war = fetch_war_index()
    mvrv = fetch_mvrv()
    cnn = fetch_cnn_fear_greed()
    result = {
        "market": market,
        "fed_watch": {"rate":market.get("fed_rate",4.50),"treasury_10y":market.get("treasury_10y",4.2)},
        "funding": {"rate":deriv.get("funding_rate",0),"rate_str":deriv.get("funding_str","0.00%"),"long_pct":deriv.get("long_pct",50),"short_pct":deriv.get("short_pct",50)},
        "cvd": deriv.get("cvd",{"total":0,"analysis":"대기중"}),
        "whale_alerts": whales or [],
        "stablecoin_inflow": {"usdt":usdt,"usdc":usdc,"total":usdt+usdc,"max_reference":500000000},
        "altseason": alt or 50,
        "kimchi": kimchi or {"premium":0,"btc_krw":0,"btc_global_krw":0,"krw_rate":1350},
        "liquidation": liq or {"current_price":round(btc),"open_interest":0,"price_high":round(btc*1.06),"price_low":round(btc*0.94),"long_liq_zone":{"start":round(btc*0.94),"end":round(btc*0.97),"description":"대기중"},"short_liq_zone":{"start":round(btc*1.03),"end":round(btc*1.06),"description":"대기중"},"magnet_price":round(btc*0.955)},
        "war_index": war or {"value":50,"label":"UNKNOWN","keyword_count":0},
        "mvrv": mvrv or {"value":2.0,"analysis":"수집 지연"},
        "cnn_fear_greed": cnn or {"score":50,"rating":"NEUTRAL","previous_close":50,"one_week_ago":50,"one_month_ago":50},
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUTPUT_FILE)
    with open(path,"w",encoding="utf-8") as f: json.dump(result,f,ensure_ascii=False,indent=2)
    print(f"\n  💾 저장 완료")
    print(f"  BTC:${btc:,.0f} | SPX:{market.get('spx')} | VIX:{market.get('vix')} | GOLD:{market.get('gold')}")
    if kimchi: print(f"  김프:{kimchi['premium']:+.2f}%")
    if liq: print(f"  청산맵:${liq['current_price']:,}")

def run_loop():
    print("="*50+"\n  X-INTELLIGENCE : JHONBER — NODE v3.0\n"+"="*50)
    while True:
        try: run_once(); print(f"\n  ⏳ {POLL_INTERVAL}초 후...\n"); time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt: print("\n  🛑 종료"); sys.exit(0)
        except Exception as e: print(f"\n  ⚠ {e}"); time.sleep(30)

if __name__ == "__main__":
    if "--once" in sys.argv: run_once()
    else: run_loop()
