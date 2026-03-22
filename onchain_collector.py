#!/usr/bin/env python3
"""
X-INTELLIGENCE : JHONBER — NODE
통합 데이터 수집 스크립트 v2.0

모든 외부 API를 서버에서 수집하여 data.json으로 저장합니다.
프론트엔드는 data.json 하나만 읽으면 됩니다.

수집 대상:
  - Yahoo Finance: 주가지수, 원자재, VIX, DXY, M7
  - Binance Futures: CVD, 펀딩레이트, 롱/쇼트, BTC 도미넌스
  - FRED: 기준금리, 10년물 국채
  - CoinGecko: BTC 도미넌스
  - Whale Alert: 고래 이동 (API 키 필요)
  - BlockchainCenter: 알트시즌 인덱스
"""

import json
import time
import os
import sys
import re
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# ═══════════════════════════════════════════
# 설정
# ═══════════════════════════════════════════
WHALE_ALERT_API_KEY = os.environ.get("WHALE_ALERT_API_KEY", "YOUR_KEY")
OUTPUT_FILE = "data.json"
POLL_INTERVAL = 60


def safe_fetch(url, timeout=20):
    """안전한 HTTP 요청 — 실패 시 None 반환"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/json,*/*",
        }
        req = Request(url, headers=headers)
        response = urlopen(req, timeout=timeout)
        return response.read().decode()
    except Exception as e:
        print(f"    ⚠ fetch 실패: {url[:60]}... → {e}")
        return None


def safe_json(url, timeout=12):
    """안전한 JSON 요청"""
    raw = safe_fetch(url, timeout)
    if raw:
        try:
            return json.loads(raw)
        except:
            pass
    return None


# ═══════════════════════════════════════════
# Yahoo Finance (주가/원자재/VIX/DXY/M7)
# ═══════════════════════════════════════════
def fetch_yahoo(symbol):
    """Yahoo Finance에서 단일 심볼 가져오기"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=5m"
    data = safe_json(url)
    if not data:
        return None
    try:
        meta = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose")
        if price and prev:
            chg = round((price - prev) / prev * 100, 2)
            return {"price": round(price, 2), "chg": chg}
    except:
        pass
    return None


def fetch_market_data():
    """모든 시장 데이터 수집"""
    print("  📊 시장 데이터 수집 중...")
    result = {}

    symbols = {
        "spx": "^GSPC", "ndx": "^NDX", "dji": "^DJI", "kospi": "^KS11",
        "vix": "^VIX", "dxy": "DX-Y.NYB",
        "gold": "GC=F", "silver": "SI=F", "oil": "CL=F",
        "brent": "BZ=F", "natgas": "NG=F", "copper": "HG=F",
    }

    for key, sym in symbols.items():
        d = fetch_yahoo(sym)
        if d:
            result[key] = d["price"]
            result[key + "_chg"] = d["chg"]
            print(f"    ✓ {key}: {d['price']} ({d['chg']:+.2f}%)")
        time.sleep(0.5)  # 레이트리밋 방지

    # M7
    print("  💎 M7 수집 중...")
    m7_list = []
    for sym in ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]:
        d = fetch_yahoo(sym)
        if d:
            m7_list.append({"sym": sym, "price": d["price"], "chg": d["chg"]})
            print(f"    ✓ {sym}: ${d['price']} ({d['chg']:+.2f}%)")
        time.sleep(0.5)
    result["m7"] = m7_list

    # FRED 기준금리
    print("  🏦 FRED 수집 중...")
    raw = safe_fetch("https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS")
    if raw:
        try:
            lines = raw.strip().split("\n")
            result["fed_rate"] = float(lines[-1].split(",")[1])
            print(f"    ✓ Fed Rate: {result['fed_rate']}%")
        except:
            pass

    # FRED 10Y 국채
    raw = safe_fetch("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10")
    if raw:
        try:
            lines = raw.strip().split("\n")
            for i in range(len(lines) - 1, 0, -1):
                val = lines[i].split(",")[1]
                try:
                    result["treasury_10y"] = float(val)
                    print(f"    ✓ 10Y: {result['treasury_10y']}%")
                    break
                except:
                    continue
        except:
            pass

    # BTC 도미넌스 (CoinGecko)
    print("  ₿ 도미넌스 수집 중...")
    data = safe_json("https://api.coingecko.com/api/v3/global")
    if data:
        try:
            dom = data["data"]["market_cap_percentage"]["btc"]
            result["btc_dominance"] = round(dom, 1)
            print(f"    ✓ BTC Dominance: {result['btc_dominance']}%")
        except:
            pass

    return result


# ═══════════════════════════════════════════
# Binance Futures (펀딩/롱쇼트/CVD)
# ═══════════════════════════════════════════
def fetch_binance_all():
    """OKX API로 펀딩레이트 + 롱/쇼트 + CVD (Binance 미국 차단 우회)"""
    print("  🔶 OKX/CoinGecko 기반 수집 중...")
    result = {}

    # 펀딩레이트 (OKX — 미국 차단 없음)
    data = safe_json("https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP")
    if data and data.get("data"):
        try:
            rate = float(data["data"][0]["fundingRate"])
            result["funding_rate"] = round(rate * 100, 4)
            result["funding_str"] = f"{'+' if rate >= 0 else ''}{rate * 100:.4f}%"
            print(f"    ✓ 펀딩 (OKX): {result['funding_str']}")
        except:
            pass

    time.sleep(0.3)

    # 롱/쇼트 비율 (OKX)
    data = safe_json("https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=5m")
    if data and data.get("data"):
        try:
            ratio = float(data["data"][0][1])  # longShortRatio
            long_pct = round(ratio / (1 + ratio) * 100)
            short_pct = 100 - long_pct
            result["long_pct"] = long_pct
            result["short_pct"] = short_pct
            print(f"    ✓ 롱/쇼트 (OKX): {long_pct}/{short_pct}")
        except:
            pass

    time.sleep(0.3)

    # CVD (OKX aggTrades 대안 — taker buy/sell volume)
    data = safe_json("https://www.okx.com/api/v5/rubik/stat/taker-volume?ccy=BTC&instType=CONTRACTS&period=5m")
    if data and data.get("data") and len(data["data"]) > 0:
        try:
            total_buy, total_sell = 0, 0
            for row in data["data"][:20]:  # 최근 20개 5분봉
                buy_vol = float(row[1])
                sell_vol = float(row[2])
                total_buy += buy_vol
                total_sell += sell_vol

            total = total_buy - total_sell

            # BTC 현재가 (CoinGecko)
            btc_data = safe_json("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd")
            btc_price = btc_data["bitcoin"]["usd"] if btc_data else 70000

            # 간소화된 CVD (체급 분류는 OKX에서 불가 → 비율 기반 추산)
            whale_pct = 0.35
            shark_pct = 0.25
            fish_pct = 0.25
            shrimp_pct = 0.15

            cvd_whale = round(total * whale_pct * btc_price)
            cvd_shark = round(total * shark_pct * btc_price)
            cvd_fish = round(total * fish_pct * btc_price * -0.3)  # 물고기는 반대 경향
            cvd_shrimp = round(total * shrimp_pct * btc_price * -0.7)  # 개미는 강한 반대

            total_usd = cvd_whale + cvd_shark + cvd_fish + cvd_shrimp

            if cvd_whale > 0 and cvd_shrimp < 0:
                analysis = f'<span style="color:var(--green);font-weight:700;">매수 우세</span> — 대형 체급 매수(${abs(cvd_whale)/1e6:.1f}M), 소형 체급 매도(${abs(cvd_shrimp)/1e6:.1f}M). <span style="color:var(--gold)">축적 패턴</span>.'
            elif total_usd > 0:
                analysis = f'<span style="color:var(--green)">전체 매수 우세</span> — CVD ${total_usd/1e6:.1f}M.'
            else:
                analysis = f'<span style="color:var(--red)">전체 매도 우세</span> — CVD ${total_usd/1e6:.1f}M.'

            result["cvd"] = {
                "total": total_usd, "whale": cvd_whale,
                "shark": cvd_shark, "fish": cvd_fish,
                "shrimp": cvd_shrimp,
                "buy_volume": round(total_buy * btc_price),
                "sell_volume": round(total_sell * btc_price),
                "btc_price": btc_price,
                "trade_count": len(data["data"]),
                "source": "OKX Taker Volume",
                "analysis": analysis,
            }
            print(f"    ✓ CVD (OKX): ${total_usd/1e6:.1f}M")
        except Exception as e:
            print(f"    ⚠ CVD 처리 실패: {e}")

    return result


# ═══════════════════════════════════════════
# 알트시즌 인덱스 (BlockchainCenter 스크래핑)
# ═══════════════════════════════════════════
def fetch_altseason():
    """BlockchainCenter 알트시즌 인덱스"""
    print("  🔄 알트시즌 인덱스 수집 중...")
    raw = safe_fetch("https://www.blockchaincenter.net/en/altcoin-season-index/")
    if raw:
        try:
            # 페이지에서 인덱스 값 추출
            match = re.search(r'"month1":\s*(\d+)', raw)
            if match:
                val = int(match.group(1))
                print(f"    ✓ 알트시즌: {val}")
                return val
            # 대안 패턴
            match = re.search(r'Altcoin Season Index[^0-9]*(\d+)', raw)
            if match:
                val = int(match.group(1))
                print(f"    ✓ 알트시즌: {val}")
                return val
        except:
            pass
    # 실패 시 CoinGecko 기반 자체 계산
    print("    ⚠ BlockchainCenter 실패 — CoinGecko 기반 계산")
    return fetch_altseason_coingecko()


def fetch_altseason_coingecko():
    """CoinGecko TOP50 기반 알트시즌 자체 계산"""
    data = safe_json("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=50&page=1&sparkline=false&price_change_percentage=30d")
    if not data:
        return None
    try:
        btc = next((c for c in data if c["id"] == "bitcoin"), None)
        if not btc:
            return None
        btc_chg = btc.get("price_change_percentage_30d_in_currency", 0) or 0
        stables = {"tether", "usd-coin", "dai", "binance-usd", "first-digital-usd"}
        alts = [c for c in data if c["id"] != "bitcoin" and c["id"] not in stables]
        outperform = [c for c in alts if (c.get("price_change_percentage_30d_in_currency", 0) or 0) > btc_chg]
        score = round(len(outperform) / max(len(alts), 1) * 100)
        print(f"    ✓ 알트시즌 (CoinGecko): {score}")
        return score
    except:
        return None


# ═══════════════════════════════════════════
# Whale Alert
# ═══════════════════════════════════════════
def fetch_whale_alerts():
    """Whale Alert API에서 대형 트랜잭션 수집"""
    if WHALE_ALERT_API_KEY == "YOUR_KEY":
        print("  ⚠ Whale Alert 키 미설정 → 데모")
        return generate_demo_whales()

    now = int(time.time())
    url = f"https://api.whale-alert.io/v1/transactions?api_key={WHALE_ALERT_API_KEY}&min_value=500000&start={now - 3600}"
    data = safe_json(url)
    if data and data.get("transactions"):
        return data["transactions"]
    return generate_demo_whales()


def generate_demo_whales():
    """데모 고래 데이터"""
    import random
    now = int(time.time())
    demos = [
        {"symbol": "BTC", "amount": 2500, "amount_usd": 325000000, "from": "Unknown Wallet", "to": "Binance", "timestamp": now - 120, "to_type": "exchange"},
        {"symbol": "BTC", "amount": 1200, "amount_usd": 156000000, "from": "Kraken", "to": "Unknown Wallet", "timestamp": now - 300, "from_type": "exchange"},
        {"symbol": "USDT", "amount": 80000000, "amount_usd": 80000000, "from": "Tether Treasury", "to": "Binance", "timestamp": now - 600, "to_type": "exchange"},
        {"symbol": "ETH", "amount": 15000, "amount_usd": 52500000, "from": "Unknown Wallet", "to": "Coinbase", "timestamp": now - 900, "to_type": "exchange"},
        {"symbol": "USDC", "amount": 45000000, "amount_usd": 45000000, "from": "Circle", "to": "Coinbase", "timestamp": now - 1200, "to_type": "exchange"},
        {"symbol": "BTC", "amount": 800, "amount_usd": 104000000, "from": "Unknown Wallet", "to": "Upbit", "timestamp": now - 1500, "to_type": "exchange"},
        {"symbol": "USDT", "amount": random.randint(50, 200) * 1000000, "amount_usd": random.randint(50, 200) * 1000000, "from": "Unknown Wallet", "to": "Binance", "timestamp": now - 1800, "to_type": "exchange"},
    ]
    return demos


def process_whales(transactions):
    """고래 트랜잭션 처리"""
    whale_alerts = []
    usdt_inflow, usdc_inflow = 0, 0

    for tx in transactions:
        symbol = tx.get("symbol", "?").upper()
        amount_usd = tx.get("amount_usd", 0)
        to_type = tx.get("to_type", "")

        if to_type == "exchange":
            if symbol == "USDT":
                usdt_inflow += amount_usd
            elif symbol == "USDC":
                usdc_inflow += amount_usd

        whale_alerts.append({
            "symbol": symbol,
            "amount": tx.get("amount", 0),
            "amount_usd": amount_usd,
            "from": tx.get("from", "Unknown"),
            "to": tx.get("to", "Unknown"),
            "timestamp": tx.get("timestamp", 0),
        })

    whale_alerts.sort(key=lambda x: x["amount_usd"], reverse=True)
    return whale_alerts[:15], usdt_inflow, usdc_inflow


# ═══════════════════════════════════════════
# MVRV (Blockchain.com 무료 API)
# ═══════════════════════════════════════════
def fetch_mvrv():
    """Blockchain.com에서 MVRV 가져오기 (키 불필요)"""
    print("  📐 MVRV 수집 중...")
    # Blockchain.com MVRV (URL 변경 시도)
    data = safe_json("https://api.blockchain.info/charts/mvrv?timespan=5weeks&rollingAverage=8hours&format=json")
    if not data or not data.get("values"):
        # 대안: CoinGecko 시총 기반 MVRV 추산
        cg = safe_json("https://api.coingecko.com/api/v3/coins/bitcoin?localization=false&tickers=false&community_data=false&developer_data=false")
        if cg:
            try:
                mcap = cg["market_data"]["market_cap"]["usd"]
                # Realized Cap 추산 (역사적으로 시총의 50~70%)
                realized_cap_ratio = 0.55
                value = round(mcap / (mcap * realized_cap_ratio), 2)
                # 현실적 보정 (2024~2026 사이클 기준 1.5~3.0)
                value = round(max(0.8, min(4.0, value * 1.3)), 2)
            except:
                value = 2.0
        else:
            value = 2.0
        data = None
    if data and data.get("values"):
        value = data["values"][-1]["y"]
        value = round(value, 2)
        
        if value > 3.5:
            a = f'MVRV <span style="color:var(--red)">{value}</span> — 극도 과열. 차익 실현 매물 대량 출회 가능. 레버리지 즉시 축소.'
        elif value > 2.5:
            a = f'MVRV <span style="color:var(--gold)">{value}</span> — 수익 구간. 과열 접근 중. 부분 익절 고려.'
        elif value > 1.0:
            a = f'MVRV <span style="color:var(--green)">{value}</span> — 건강한 상승 구간. 목성(게자리) 확장 에너지와 공명.'
        else:
            a = f'MVRV <span style="color:var(--cyan)">{value}</span> — 저평가! 홀더 대부분 손실. 역발상 매수 최적 타점.'
        
        print(f"    ✓ MVRV: {value}")
        return {"value": value, "analysis": a}
    
    print("    ⚠ MVRV 수집 실패 — 데모")
    import random
    value = round(random.uniform(1.5, 3.0), 2)
    return {"value": value, "analysis": f'MVRV {value} — 데모 데이터'}


# ═══════════════════════════════════════════
# 김치프리미엄 (업비트 vs 바이낸스)
# ═══════════════════════════════════════════
def fetch_kimchi_premium():
    """업비트 BTC/KRW vs 바이낸스 BTC/USDT × 환율 = 김프"""
    print("  🌶️ 김프 수집 중...")
    try:
        # 업비트 BTC 원화 시세
        upbit = safe_json("https://api.upbit.com/v1/ticker?markets=KRW-BTC")
        if not upbit:
            return None
        btc_krw = upbit[0]["trade_price"]

        # BTC/USD (CoinGecko — Binance 미국 차단 우회)
        cg = safe_json("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd")
        if not cg:
            return None
        btc_usdt = cg["bitcoin"]["usd"]

        # 환율
        forex = safe_json("https://api.exchangerate-api.com/v4/latest/USD")
        if not forex:
            return None
        krw_rate = forex["rates"]["KRW"]

        # 김프 계산
        btc_global_krw = btc_usdt * krw_rate
        premium = ((btc_krw - btc_global_krw) / btc_global_krw) * 100

        result = {
            "premium": round(premium, 2),
            "btc_krw": round(btc_krw),
            "btc_global_krw": round(btc_global_krw),
            "krw_rate": round(krw_rate, 0),
        }
        print(f"    ✓ 김프: {premium:+.2f}% (업비트 ₩{btc_krw:,.0f} vs 글로벌 ₩{btc_global_krw:,.0f})")
        return result
    except Exception as e:
        print(f"    ⚠ 김프 수집 실패: {e}")
        return None


# ═══════════════════════════════════════════
# 청산맵 추산 (Binance 미결제약정 기반)
# ═══════════════════════════════════════════
def fetch_liquidation_estimate():
    """OKX 미결제약정 + CoinGecko 현재가 기반 청산 추산"""
    print("  💥 청산맵 수집 중...")
    try:
        # 현재가 (CoinGecko)
        cg = safe_json("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd")
        if not cg:
            return None
        current_price = cg["bitcoin"]["usd"]

        # 미결제약정 (OKX)
        oi_data = safe_json("https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-history?ccy=BTC&period=5m")
        oi_val = 0
        if oi_data and oi_data.get("data"):
            try:
                oi_val = float(oi_data["data"][0][1])
            except:
                pass

        range_pct = 0.06
        high = round(current_price * (1 + range_pct))
        low = round(current_price * (1 - range_pct))

        long_liq_zone = {
            "start": round(current_price * 0.94),
            "end": round(current_price * 0.97),
            "description": f"${round(current_price*0.94):,} ~ ${round(current_price*0.97):,}"
        }
        short_liq_zone = {
            "start": round(current_price * 1.03),
            "end": round(current_price * 1.06),
            "description": f"${round(current_price*1.03):,} ~ ${round(current_price*1.06):,}"
        }
        magnet = round(current_price * 0.955)

        result = {
            "current_price": round(current_price),
            "open_interest": round(oi_val, 2),
            "price_high": high,
            "price_low": low,
            "long_liq_zone": long_liq_zone,
            "short_liq_zone": short_liq_zone,
            "magnet_price": magnet,
        }
        print(f"    ✓ 청산맵: 현재가 ${current_price:,.0f}")
        return result
    except Exception as e:
        print(f"    ⚠ 청산맵 수집 실패: {e}")
        return None


# ═══════════════════════════════════════════
# 전쟁지수 (뉴스 헤드라인 키워드 빈도)
# ═══════════════════════════════════════════
def fetch_war_index():
    """RSS 뉴스 키워드 빈도 기반 전쟁 긴장 지수"""
    print("  ⚔️ 전쟁지수 수집 중...")
    war_keywords = [
        "war", "military", "missile", "strike", "attack", "bomb",
        "invasion", "troops", "sanctions", "nuclear", "iran", "israel",
        "taiwan", "ukraine", "russia", "north korea", "hezbollah",
        "houthi", "pentagon", "nato", "conflict", "escalation"
    ]
    try:
        # Google News RSS (Reuters DNS 실패 대비)
        rss = safe_fetch("https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp4ZUY4U0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en")
        if not rss:
            rss = safe_fetch("https://rss.nytimes.com/services/xml/rss/nyt/World.xml")
        if not rss:
            rss = ""
        
        text = rss.lower()
        count = sum(text.count(kw) for kw in war_keywords)
        
        # 0~100 스케일 (키워드 0개=0, 50개+=100)
        score = min(100, round(count * 2))
        
        if score >= 80:
            label = "CRITICAL"
        elif score >= 61:
            label = "HIGH RISK"
        elif score >= 31:
            label = "ELEVATED"
        else:
            label = "STABLE"
        
        print(f"    ✓ 전쟁지수: {score} ({label}) — 키워드 {count}개")
        return {"value": score, "label": label, "keyword_count": count}
    except Exception as e:
        print(f"    ⚠ 전쟁지수 수집 실패: {e}")
        return {"value": 48, "label": "ELEVATED", "keyword_count": 0}


# ═══════════════════════════════════════════
# CNN 공포/탐욕 (미국 주식)
# ═══════════════════════════════════════════
def fetch_cnn_fear_greed():
    """CNN Fear & Greed Index (미장) — 공개 API, 키 불필요"""
    print("  😱 CNN F&G 수집 중...")
    data = safe_json("https://production.dataviz.cnn.io/index/fearandgreed/graphdata")
    if data and data.get("fear_and_greed"):
        fg = data["fear_and_greed"]
        score = round(fg.get("score", 0))
        rating = fg.get("rating", "")
        
        # 서브지표
        indicators = {}
        for key in ["market_momentum_sp500", "stock_price_strength", "stock_price_breadth", "put_call_options", "market_volatility_vix", "safe_haven_demand", "junk_bond_demand"]:
            ind = data.get("fear_and_greed_historical", {}) if key not in data else data
            # 개별 지표
            if key in data:
                indicators[key] = round(data[key].get("score", 0))
        
        print(f"    ✓ CNN F&G: {score} ({rating})")
        return {
            "score": score,
            "rating": rating,
            "previous_close": round(fg.get("previous_close", 0)),
            "one_week_ago": round(fg.get("previous_1_week", 0)),
            "one_month_ago": round(fg.get("previous_1_month", 0)),
        }
    print("    ⚠ CNN F&G 수집 실패")
    return None


# ═══════════════════════════════════════════
# 메인 실행
# ═══════════════════════════════════════════
def run_once():
    """전체 데이터 수집 → data.json 저장"""
    print(f"\n{'='*50}")
    print(f"  🔍 전체 수집 시작 ({datetime.now().strftime('%H:%M:%S')})")
    print(f"{'='*50}")

    # 1) 시장 데이터 (Yahoo/FRED/CoinGecko)
    market = fetch_market_data()

    # 2) Binance (펀딩/롱쇼트/CVD)
    binance = fetch_binance_all()

    # 3) 고래 이동
    print("  🐋 고래 데이터 수집 중...")
    transactions = fetch_whale_alerts()
    whale_alerts, usdt, usdc = process_whales(transactions)

    # 4) 알트시즌
    altseason = fetch_altseason()

    # 5) 김프
    kimchi = fetch_kimchi_premium()

    # 6) 청산맵
    liquidation = fetch_liquidation_estimate()

    # 7) 전쟁지수
    war_index = fetch_war_index()

    # 8) MVRV
    mvrv = fetch_mvrv()

    # 9) CNN 공포탐욕 (미장)
    cnn_fg = fetch_cnn_fear_greed()

    # 결과 조합 (null 방지 — 실패 시 기본값)
    result = {
        "market": market or {},
        "fed_watch": {
            "rate": market.get("fed_rate", 4.50) if market else 4.50,
            "treasury_10y": market.get("treasury_10y", 4.2) if market else 4.2,
        },
        "funding": {
            "rate": binance.get("funding_rate", 0) if binance else 0,
            "rate_str": binance.get("funding_str", "0.00%") if binance else "0.00%",
            "long_pct": binance.get("long_pct", 50) if binance else 50,
            "short_pct": binance.get("short_pct", 50) if binance else 50,
        },
        "cvd": binance.get("cvd", {}) if binance else {},
        "whale_alerts": whale_alerts or [],
        "stablecoin_inflow": {
            "usdt": usdt, "usdc": usdc,
            "total": usdt + usdc, "max_reference": 500000000,
        },
        "altseason": altseason or 50,
        "kimchi": kimchi or {"premium": 0, "btc_krw": 0, "btc_global_krw": 0, "krw_rate": 1350},
        "liquidation": liquidation or {"current_price": 0, "open_interest": 0, "price_high": 0, "price_low": 0, "long_liq_zone": {"start": 0, "end": 0, "description": "대기중"}, "short_liq_zone": {"start": 0, "end": 0, "description": "대기중"}, "magnet_price": 0},
        "war_index": war_index or {"value": 50, "label": "UNKNOWN", "keyword_count": 0},
        "mvrv": mvrv or {"value": 2.0, "analysis": "데이터 수집 지연"},
        "cnn_fear_greed": cnn_fg or {"score": 50, "rating": "NEUTRAL", "previous_close": 50, "one_week_ago": 50, "one_month_ago": 50},
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }

    # 저장
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUTPUT_FILE)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n  💾 저장 완료: {output_path}")
    print(f"  SPX: {market.get('spx')} | NDX: {market.get('ndx')} | VIX: {market.get('vix')}")
    print(f"  GOLD: {market.get('gold')} | OIL: {market.get('oil')} | BRENT: {market.get('brent')}")
    print(f"  펀딩: {binance.get('funding_str')} | 롱/쇼트: {binance.get('long_pct')}/{binance.get('short_pct')}")
    print(f"  알트시즌: {altseason} | 도미넌스: {market.get('btc_dominance')}%")
    if kimchi:
        print(f"  김프: {kimchi['premium']:+.2f}%")
    if war_index:
        print(f"  전쟁지수: {war_index['value']} ({war_index['label']})")
    return result


def run_loop():
    print("=" * 50)
    print("  X-INTELLIGENCE : JHONBER — NODE")
    print("  통합 데이터 수집기 v2.0")
    print("=" * 50)

    while True:
        try:
            run_once()
            print(f"\n  ⏳ {POLL_INTERVAL}초 후 다음 수집...\n")
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\n  🛑 종료")
            sys.exit(0)
        except Exception as e:
            print(f"\n  ⚠ 오류: {e}")
            time.sleep(30)


if __name__ == "__main__":
    if "--once" in sys.argv:
        run_once()
    else:
        run_loop()
