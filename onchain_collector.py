#!/usr/bin/env python3
"""
X-INTELLIGENCE : JHONBER — NODE v6.0
=====================================
통합 데이터 수집기 — 클린 리빌드

아키텍처:
  FAST (60초): Hyperliquid allMids → 크립토·원자재·지수 가격
  SLOW (5분):  Yahoo 변동률, OKX 파생, FRED, CNN F&G, MVRV,
               전쟁지수, 김프, 청산맵, 알트시즌, 고래 알림

데이터 소스:
  - Hyperliquid (가격)     : 네이티브 크립토 + HIP-3 원자재/지수
  - Yahoo Finance (변동률) : 서버사이드 비공식 API
  - OKX (파생)            : 펀딩레이트, 롱/쇼트, CVD
  - FRED (매크로)         : Fed 기준금리, 10Y 국채, 대차대조표
  - CoinGecko (도미넌스)  : BTC 도미넌스 (유일한 CG 호출)
  - 업비트 + ExchangeRate : 김프
  - Google News RSS       : 전쟁 키워드 스캔
  - CNN (F&G)             : 미국 주식 공포탐욕
  - Blockchain.com (MVRV) : BTC MVRV Ratio
  - BlockchainCenter      : 알트시즌 인덱스
  - Whale Alert            : 고래 이동 (API 키 필요)
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

# ── 설정 ──────────────────────────────────────────────
WHALE_KEY = os.environ.get("WHALE_ALERT_API_KEY", "")
OUT_FILE = "data.json"
FAST_INTERVAL = 60   # 초
SLOW_INTERVAL = 300  # 초

_last_slow = 0
_slow_cache = {}

# ── 유틸리티 ──────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json,text/html,*/*",
    "Content-Type": "application/json",
}


def fetch_raw(url, timeout=20, post_data=None):
    """HTTP GET/POST → str | None"""
    try:
        if post_data:
            data = post_data if isinstance(post_data, bytes) else post_data.encode()
            req = Request(url, headers=HEADERS, data=data, method="POST")
        else:
            req = Request(url, headers=HEADERS)
        return urlopen(req, timeout=timeout).read().decode()
    except Exception as e:
        print(f"    ⚠ {url[:60]}… {e}")
        return None


def fetch_json(url, timeout=20):
    """HTTP GET → dict/list | None"""
    raw = fetch_raw(url, timeout)
    if raw:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def hl_post(req_type):
    """Hyperliquid info API POST"""
    payload = json.dumps({"type": req_type}).encode()
    return fetch_json.__wrapped__(payload) if False else None  # noqa
    # 직접 구현:
    raw = fetch_raw("https://api.hyperliquid.xyz/info", post_data=payload)
    if raw:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass
    return None


# hl_post 직접 구현 (위의 데코레이터 방식 제거)
def hl_post(req_type):
    """Hyperliquid info API POST"""
    payload = json.dumps({"type": req_type}).encode()
    raw = fetch_raw("https://api.hyperliquid.xyz/info", post_data=payload)
    if raw:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def safe_float(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ── FAST: Hyperliquid 가격 ────────────────────────────

# 크립토 심볼 매핑: output_key → HL symbol
CRYPTO_MAP = {
    "btc_usd": "BTC", "eth_usd": "ETH", "sol_usd": "SOL",
    "xrp_usd": "XRP", "hype_usd": "HYPE", "doge_usd": "DOGE",
    "ada_usd": "ADA", "avax_usd": "AVAX", "link_usd": "LINK",
    "dot_usd": "DOT",
}

# HIP-3 매핑: output_key → [후보 심볼들]
HIP3_MAP = {
    "gold":   ["xyz:GOLD", "cash:GOLD", "flx:GOLD"],
    "silver": ["xyz:SILVER", "cash:SILVER", "flx:SILVER"],
    "oil":    ["xyz:CL", "cash:CL", "xyz:USOIL", "cash:USOIL", "flx:CL"],
    "brent":  ["xyz:BRENTOIL", "cash:BRENTOIL", "flx:BRENTOIL"],
    "natgas": ["xyz:NG", "cash:NG", "flx:NG"],
    "copper": ["xyz:COPPER", "cash:COPPER", "xyz:HG", "cash:HG"],
    "spx":    ["xyz:USA500", "km:USA500", "cash:USA500", "xyz:SPX"],
    "ndx":    ["xyz:XYZ100", "km:XYZ100", "cash:XYZ100", "xyz:NDX100"],
    "kospi":  ["xyz:KOSPI", "km:KOSPI", "cash:KOSPI"],
    "dji":    ["xyz:USA30", "km:USA30", "cash:USA30"],
}

# M7 빅테크 매핑
M7_MAP = {
    "AAPL":  ["cash:AAPL", "xyz:AAPL"],
    "MSFT":  ["cash:MSFT", "xyz:MSFT"],
    "GOOGL": ["cash:GOOGL", "xyz:GOOGL", "cash:GOOG"],
    "AMZN":  ["cash:AMZN", "xyz:AMZN"],
    "NVDA":  ["cash:NVDA", "xyz:NVDA"],
    "META":  ["cash:META", "xyz:META"],
    "TSLA":  ["cash:TSLA", "xyz:TSLA"],
}


def collect_hl_prices():
    """Hyperliquid allMids → 크립토/원자재/지수 가격"""
    print("  ⚡ Hyperliquid…")
    mids = hl_post("allMids")
    if not mids:
        print("    ⚠ HL 응답 없음")
        return {}

    out = {}

    # 1) 네이티브 크립토
    for key, sym in CRYPTO_MAP.items():
        if sym in mids:
            out[key] = round(safe_float(mids[sym]), 2)

    # 2) HIP-3 원자재/지수
    for key, candidates in HIP3_MAP.items():
        for sym in candidates:
            if sym in mids:
                out[key] = round(safe_float(mids[sym]), 2)
                break

    # 3) M7 빅테크
    m7 = []
    for stock, candidates in M7_MAP.items():
        for sym in candidates:
            if sym in mids:
                m7.append({"sym": stock, "price": round(safe_float(mids[sym]), 2), "chg": 0})
                break
    out["m7"] = m7

    # 4) HL OI + 펀딩 (metaAndAssetCtxs)
    meta = hl_post("metaAndAssetCtxs")
    if meta and len(meta) >= 2:
        for ctx in meta[1]:
            if ctx.get("coin") == "BTC":
                out["hl_btc_oi"] = round(safe_float(ctx.get("openInterest", "0")), 2)
                out["hl_btc_funding"] = round(safe_float(ctx.get("funding", "0")) * 100, 4)
                out["hl_btc_mark"] = round(safe_float(ctx.get("markPx", "0")), 2)
                break

    # 통계
    price_keys = [k for k in out if k not in ("m7", "hl_btc_oi", "hl_btc_funding", "hl_btc_mark")]
    print(f"    ✓ {len(price_keys)}개 가격 수집")

    # 디버그: HIP-3 심볼 목록
    hip3_syms = sorted(k for k in mids if ":" in k)
    if hip3_syms:
        print(f"    📋 HIP-3 {len(hip3_syms)}개: {', '.join(hip3_syms[:25])}…")

    return out


# ── SLOW: Yahoo Finance 변동률 ────────────────────────

YAHOO_SYMBOLS = {
    "spx": "^GSPC", "ndx": "^NDX", "dji": "^DJI", "kospi": "^KS11",
    "vix": "^VIX", "dxy": "DX-Y.NYB",
    "gold": "GC=F", "silver": "SI=F", "oil": "CL=F",
    "brent": "BZ=F", "natgas": "NG=F", "copper": "HG=F",
    "btc_usd": "BTC-USD",
}

M7_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]


def _yahoo_quote(ticker):
    """Yahoo Finance v8 chart API → (price, change_pct) | (None, None)"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=5m"
    data = fetch_json(url)
    if not data:
        return None, None
    try:
        meta = data["chart"]["result"][0]["meta"]
        price = meta["regularMarketPrice"]
        prev = meta["chartPreviousClose"]
        chg = round((price - prev) / prev * 100, 2)
        return round(price, 2), chg
    except (KeyError, TypeError, ZeroDivisionError):
        return None, None


def collect_yahoo_changes(hl_data):
    """Yahoo Finance → 변동률 + DXY/VIX + M7 변동률"""
    print("  📊 Yahoo 변동률…")
    out = {}

    for key, ticker in YAHOO_SYMBOLS.items():
        price, chg = _yahoo_quote(ticker)
        if chg is not None:
            out[f"{key}_chg"] = chg
        if price is not None and key not in hl_data:
            out[key] = price
        time.sleep(0.15)

    # M7 변동률
    m7_changes = {}
    for ticker in M7_TICKERS:
        price, chg = _yahoo_quote(ticker)
        if chg is not None:
            m7_changes[ticker] = chg
        time.sleep(0.15)
    out["_m7_changes"] = m7_changes

    return out


# ── SLOW: FRED + BTC 도미넌스 ─────────────────────────

def _fred_latest(series_id):
    """FRED CSV → 마지막 유효 값"""
    raw = fetch_raw(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}")
    if not raw:
        return None
    for line in reversed(raw.strip().split("\n")[1:]):
        try:
            return float(line.split(",")[1])
        except (IndexError, ValueError):
            continue
    return None


def collect_fred_and_dominance():
    """FRED 금리/국채/대차대조표 + CoinGecko BTC 도미넌스"""
    print("  🏦 FRED + 도미넌스…")
    out = {}

    # Fed 기준금리
    val = _fred_latest("FEDFUNDS")
    if val:
        out["fed_rate"] = val
        print(f"    ✓ Fed: {val}%")

    # 10Y 국채
    val = _fred_latest("DGS10")
    if val:
        out["treasury_10y"] = val
        print(f"    ✓ 10Y: {val}%")

    # Fed 대차대조표 (유동성 탭)
    val = _fred_latest("WALCL")
    if val:
        out["fed_balance_sheet"] = val
        print(f"    ✓ FedBS: {val}")

    # BTC 도미넌스 (유일한 CoinGecko 호출)
    cg = fetch_json("https://api.coingecko.com/api/v3/global")
    if cg:
        try:
            dom = round(cg["data"]["market_cap_percentage"]["btc"], 1)
            out["btc_dominance"] = dom
            print(f"    ✓ Dom: {dom}%")
        except (KeyError, TypeError):
            pass

    return out


# ── SLOW: OKX 파생 데이터 ─────────────────────────────

def collect_okx(btc_price):
    """OKX → 펀딩레이트, 롱/쇼트, CVD (체급별)"""
    print("  🔶 OKX 파생…")
    out = {}

    # 펀딩레이트
    data = fetch_json("https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP")
    if data and data.get("data"):
        rate = safe_float(data["data"][0].get("fundingRate", 0))
        out["funding_rate"] = round(rate * 100, 4)
        out["funding_str"] = f"{'+' if rate >= 0 else ''}{rate * 100:.4f}%"
    time.sleep(0.3)

    # 롱/쇼트 비율
    data = fetch_json("https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=5m")
    if data and data.get("data"):
        ratio = safe_float(data["data"][0][1])
        if ratio > 0:
            out["long_pct"] = round(ratio / (1 + ratio) * 100)
            out["short_pct"] = 100 - out["long_pct"]
    time.sleep(0.3)

    # CVD (Taker Volume)
    data = fetch_json("https://www.okx.com/api/v5/rubik/stat/taker-volume?ccy=BTC&instType=CONTRACTS&period=5m")
    if data and data.get("data"):
        try:
            total_buy = sum(safe_float(x[1]) for x in data["data"][:20])
            total_sell = sum(safe_float(x[2]) for x in data["data"][:20])
            net = total_buy - total_sell

            # 체급별 추산 (비율 기반)
            whale = net * 0.35
            shark = net * 0.25
            fish = net * -0.075
            shrimp = net * -0.105
            total_usd = round((whale + shark + fish + shrimp) * btc_price)

            if net > 0:
                analysis = (
                    f'<span style="color:var(--green);font-weight:700;">매수 우세</span>'
                    f' — ${abs(round(whale * btc_price)) / 1e6:.1f}M 대형매수.'
                )
            else:
                analysis = (
                    f'<span style="color:var(--red);font-weight:700;">매도 우세</span>'
                    f' — ${abs(total_usd) / 1e6:.1f}M.'
                )

            out["cvd"] = {
                "total": total_usd,
                "whale": round(whale * btc_price),
                "shark": round(shark * btc_price),
                "fish": round(fish * btc_price),
                "shrimp": round(shrimp * btc_price),
                "buy_volume": round(total_buy * btc_price),
                "sell_volume": round(total_sell * btc_price),
                "btc_price": btc_price,
                "source": "OKX",
                "analysis": analysis,
            }
        except (IndexError, TypeError):
            pass

    return out


# ── SLOW: 김치프리미엄 ───────────────────────────────

def collect_kimchi(btc_price):
    """업비트 BTC/KRW + ExchangeRate → 김프"""
    print("  🌶️ 김프…")
    try:
        upbit = fetch_json("https://api.upbit.com/v1/ticker?markets=KRW-BTC")
        fx = fetch_json("https://api.exchangerate-api.com/v4/latest/USD")
        if upbit and fx:
            btc_krw = upbit[0]["trade_price"]
            krw_rate = fx["rates"]["KRW"]
            global_krw = btc_price * krw_rate
            premium = ((btc_krw - global_krw) / global_krw) * 100
            print(f"    ✓ {premium:+.2f}%")
            return {
                "premium": round(premium, 2),
                "btc_krw": round(btc_krw),
                "btc_global_krw": round(global_krw),
                "krw_rate": round(krw_rate),
            }
    except (KeyError, TypeError, IndexError) as e:
        print(f"    ⚠ 김프 에러: {e}")
    return None


# ── SLOW: 청산맵 ─────────────────────────────────────

def collect_liquidation(btc_price, hl_oi=0):
    """OI + 가격 기반 청산 구간 추산"""
    print(f"  💥 청산맵… ${btc_price:,.0f} OI:{hl_oi}")
    return {
        "current_price": round(btc_price),
        "open_interest": round(hl_oi, 2),
        "price_high": round(btc_price * 1.06),
        "price_low": round(btc_price * 0.94),
        "long_liq_zone": {
            "start": round(btc_price * 0.94),
            "end": round(btc_price * 0.97),
            "description": f"${round(btc_price * 0.94):,} ~ ${round(btc_price * 0.97):,}",
        },
        "short_liq_zone": {
            "start": round(btc_price * 1.03),
            "end": round(btc_price * 1.06),
            "description": f"${round(btc_price * 1.03):,} ~ ${round(btc_price * 1.06):,}",
        },
        "magnet_price": round(btc_price * 0.955),
    }


# ── SLOW: 전쟁지수 ───────────────────────────────────

WAR_KEYWORDS = [
    "airstrike", "nuclear", "assassination", "troops deployed",
    "artillery", "warship", "missile launch", "military operation",
    "invasion", "bombing", "drone strike", "naval blockade",
]


def collect_war_index():
    """Google News RSS → 전쟁 키워드 스캔"""
    print("  ⚔️ 전쟁지수…")
    try:
        rss = fetch_raw("https://news.google.com/rss/headlines/section/topic/WORLD") or ""
        rss_lower = rss.lower()
        count = sum(rss_lower.count(kw) for kw in WAR_KEYWORDS)
        score = min(100, count * 5)
        label = (
            "CRITICAL" if score >= 80
            else "HIGH RISK" if score >= 50
            else "ELEVATED" if score >= 20
            else "STABLE"
        )
        print(f"    ✓ {score} ({label})")
        return {"value": score, "label": label, "keyword_count": count}
    except Exception as e:
        print(f"    ⚠ {e}")
        return None


# ── SLOW: CNN Fear & Greed ────────────────────────────

def collect_cnn_fg():
    """CNN Fear & Greed Index"""
    print("  😱 CNN F&G…")
    data = fetch_json("https://production.dataviz.cnn.io/index/fearandgreed/graphdata")
    if data and data.get("fear_and_greed"):
        try:
            fg = data["fear_and_greed"]
            score = round(fg.get("score", 0))
            print(f"    ✓ {score}")
            return {
                "score": score,
                "rating": fg.get("rating", ""),
                "previous_close": round(fg.get("previous_close", 0)),
                "one_week_ago": round(fg.get("previous_1_week", 0)),
                "one_month_ago": round(fg.get("previous_1_month", 0)),
            }
        except (KeyError, TypeError):
            pass
    return None


# ── SLOW: MVRV Ratio ─────────────────────────────────

def collect_mvrv():
    """Blockchain.com → MVRV Ratio"""
    print("  📐 MVRV…")
    data = fetch_json(
        "https://api.blockchain.info/charts/mvrv?timespan=5weeks&rollingAverage=8hours&format=json"
    )
    if data and data.get("values"):
        try:
            val = round(data["values"][-1]["y"], 2)
            if val > 3.5:
                analysis = f'MVRV <span style="color:var(--red)">{val}</span> — 과열.'
            elif val > 2.5:
                analysis = f'MVRV <span style="color:var(--gold)">{val}</span> — 수익구간.'
            elif val > 1.0:
                analysis = f'MVRV <span style="color:var(--green)">{val}</span> — 건강.'
            else:
                analysis = f'MVRV <span style="color:var(--cyan)">{val}</span> — 저평가!'
            print(f"    ✓ {val}")
            return {"value": val, "analysis": analysis}
        except (IndexError, KeyError):
            pass
    return None


# ── SLOW: 알트시즌 인덱스 ─────────────────────────────

def collect_altseason():
    """BlockchainCenter → 알트시즌 인덱스 (CoinGecko 폴백)"""
    print("  🔄 알트시즌…")
    raw = fetch_raw("https://www.blockchaincenter.net/en/altcoin-season-index/")
    if raw:
        match = re.search(r'"month1":\s*(\d+)', raw)
        if match:
            val = int(match.group(1))
            print(f"    ✓ {val}")
            return val
    return None


# ── SLOW: 고래 알림 ──────────────────────────────────

def collect_whales():
    """Whale Alert API → 대형 거래 추적"""
    # API 키 없으면 데모 데이터
    if not WHALE_KEY or WHALE_KEY == "YOUR_KEY":
        now_ts = int(time.time())
        demo_alerts = [
            {"symbol": "BTC", "amount": 2500, "amount_usd": 325_000_000,
             "from": "Unknown", "to": "Binance", "timestamp": now_ts - 120, "to_type": "exchange"},
            {"symbol": "BTC", "amount": 1200, "amount_usd": 156_000_000,
             "from": "Kraken", "to": "Unknown", "timestamp": now_ts - 300},
            {"symbol": "USDT", "amount": 80_000_000, "amount_usd": 80_000_000,
             "from": "Tether", "to": "Binance", "timestamp": now_ts - 600, "to_type": "exchange"},
            {"symbol": "ETH", "amount": 15000, "amount_usd": 52_500_000,
             "from": "Unknown", "to": "Coinbase", "timestamp": now_ts - 900, "to_type": "exchange"},
            {"symbol": "USDC", "amount": 45_000_000, "amount_usd": 45_000_000,
             "from": "Circle", "to": "Coinbase", "timestamp": now_ts - 1200, "to_type": "exchange"},
        ]
        return demo_alerts, 80_000_000, 45_000_000

    # 실제 API 호출
    since = int(time.time()) - 3600
    data = fetch_json(
        f"https://api.whale-alert.io/v1/transactions?"
        f"api_key={WHALE_KEY}&min_value=500000&start={since}"
    )
    txs = data.get("transactions", []) if data else []

    alerts = []
    usdt_to_exchange = 0
    usdc_to_exchange = 0

    for tx in txs:
        sym = tx.get("symbol", "?").upper()
        usd = tx.get("amount_usd", 0)

        if tx.get("to_type") == "exchange":
            if sym == "USDT":
                usdt_to_exchange += usd
            elif sym == "USDC":
                usdc_to_exchange += usd

        alerts.append({
            "symbol": sym,
            "amount": tx.get("amount", 0),
            "amount_usd": usd,
            "from": tx.get("from", "?"),
            "to": tx.get("to", "?"),
            "timestamp": tx.get("timestamp", 0),
        })

    alerts.sort(key=lambda x: x["amount_usd"], reverse=True)
    return alerts[:15], usdt_to_exchange, usdc_to_exchange


# ── 메인 수집 루프 ────────────────────────────────────

def run_once():
    """1회 데이터 수집 + data.json 저장"""
    global _last_slow, _slow_cache

    now = time.time()
    do_slow = (now - _last_slow) >= SLOW_INTERVAL or not _slow_cache

    print(f"\n{'=' * 50}")
    print(f"  ⚡ v6.0 {'FULL' if do_slow else 'FAST'} ({datetime.now().strftime('%H:%M:%S')})")
    print(f"{'=' * 50}")

    # ── FAST: 항상 실행 ──
    hl = collect_hl_prices()
    btc = hl.get("btc_usd") or hl.get("hl_btc_mark") or 69000
    hl_oi = hl.get("hl_btc_oi", 0)

    # ── SLOW: 5분마다 ──
    if do_slow:
        print("\n  ── SLOW 수집 시작 ──")

        yahoo = collect_yahoo_changes(hl)
        fred = collect_fred_and_dominance()
        okx = collect_okx(btc)
        kimchi = collect_kimchi(btc)
        liquidation = collect_liquidation(btc, hl_oi)
        war = collect_war_index()
        cnn = collect_cnn_fg()
        mvrv = collect_mvrv()
        altseason = collect_altseason()
        whales, usdt_inflow, usdc_inflow = collect_whales()

        _slow_cache = {
            "yahoo": yahoo, "fred": fred, "okx": okx,
            "kimchi": kimchi, "liquidation": liquidation, "war": war,
            "cnn": cnn, "mvrv": mvrv, "altseason": altseason,
            "whales": whales, "usdt": usdt_inflow, "usdc": usdc_inflow,
        }
        _last_slow = now
    else:
        print("  (SLOW 캐시 사용)")

    # ── 결과 조합 ──
    sc = _slow_cache
    yahoo = sc.get("yahoo", {})
    fred = sc.get("fred", {})
    okx = sc.get("okx", {})

    # 마켓 데이터 병합 (HL + Yahoo + FRED)
    market = {**hl, **yahoo, **fred}

    # M7 변동률 적용
    m7_changes = yahoo.get("_m7_changes", {})
    if market.get("m7"):
        for item in market["m7"]:
            if item["sym"] in m7_changes:
                item["chg"] = m7_changes[item["sym"]]
    market.pop("_m7_changes", None)

    # null 방지 기본값
    usdt = sc.get("usdt", 0)
    usdc = sc.get("usdc", 0)

    result = {
        "market": market,

        "fed_watch": {
            "rate": market.get("fed_rate", 4.50),
            "treasury_10y": market.get("treasury_10y", 4.2),
            "balance_sheet": market.get("fed_balance_sheet"),
        },

        "funding": {
            "rate": okx.get("funding_rate", 0),
            "rate_str": okx.get("funding_str", "0.00%"),
            "long_pct": okx.get("long_pct", 50),
            "short_pct": okx.get("short_pct", 50),
        },

        "cvd": okx.get("cvd", {"total": 0, "analysis": "대기중"}),

        "whale_alerts": sc.get("whales", []),

        "stablecoin_inflow": {
            "usdt": usdt,
            "usdc": usdc,
            "total": usdt + usdc,
            "max_reference": 500_000_000,
        },

        "altseason": sc.get("altseason") or 50,

        "kimchi": sc.get("kimchi") or {
            "premium": 0, "btc_krw": 0,
            "btc_global_krw": 0, "krw_rate": 1350,
        },

        "liquidation": sc.get("liquidation") or {
            "current_price": round(btc),
            "open_interest": 0,
            "price_high": round(btc * 1.06),
            "price_low": round(btc * 0.94),
            "long_liq_zone": {"start": round(btc * 0.94), "end": round(btc * 0.97), "description": "대기중"},
            "short_liq_zone": {"start": round(btc * 1.03), "end": round(btc * 1.06), "description": "대기중"},
            "magnet_price": round(btc * 0.955),
        },

        "war_index": sc.get("war") or {"value": 50, "label": "UNKNOWN", "keyword_count": 0},

        "mvrv": sc.get("mvrv") or {"value": 2.0, "analysis": "수집 지연"},

        "cnn_fear_greed": sc.get("cnn") or {
            "score": 50, "rating": "NEUTRAL",
            "previous_close": 50, "one_week_ago": 50, "one_month_ago": 50,
        },

        "last_updated": datetime.now(timezone.utc).isoformat(),
    }

    # 저장
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUT_FILE)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n  💾 저장완료 | BTC:${btc:,.0f} | SPX:{market.get('spx')} | GOLD:{market.get('gold')}")


def run_loop():
    """무한 루프 실행"""
    print("=" * 50)
    print("  ⚡ JHONBER NODE v6.0")
    print("=" * 50)
    while True:
        try:
            run_once()
            print(f"  ⏳ {FAST_INTERVAL}초 대기…")
            time.sleep(FAST_INTERVAL)
        except KeyboardInterrupt:
            print("\n  👋 종료")
            sys.exit(0)
        except Exception as e:
            print(f"  ⚠ 루프 에러: {e}")
            time.sleep(30)


if __name__ == "__main__":
    if "--once" in sys.argv:
        run_once()
    else:
        run_loop()
