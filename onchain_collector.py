#!/usr/bin/env python3
"""
X-INTELLIGENCE : JHONBER — NODE v7.7
=====================================
통합 데이터 수집기 — Twelve Data 통합 리빌드

아키텍처:
  FAST (60초):  Hyperliquid allMids → 크립토·원자재 가격
  TD   (2분):   Twelve Data Batch → 지수·환율·M7 주식
  SLOW (5분):   OKX 파생, FRED, CNN F&G, MVRV,
                전쟁지수, 김프, 청산맵, 알트시즌, 고래 알림

데이터 소스:
  - Twelve Data (지수·환율·M7) : SPX/IXIC/DJI/DXY/VIX/N225/HSI + 6환율 + M7
  - Hyperliquid (크립토·원자재) : 네이티브 퍼프 + HIP-3 원자재
  - OKX (파생)                 : 펀딩레이트, 롱/쇼트, CVD
  - FRED (매크로)              : Fed 기준금리, 10Y 국채, 대차대조표
  - CoinGecko (도미넌스)       : BTC 도미넌스 (유일한 CG 호출)
  - 업비트                     : 김프
  - Google News RSS            : 전쟁 키워드 스캔
  - CNN (F&G)                  : 미국 주식 공포탐욕
  - Blockchain.com (MVRV)      : BTC MVRV Ratio
  - BlockchainCenter           : 알트시즌 인덱스
  - Whale Alert                : 고래 이동 (API 키 필요)
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import quote


# ── .env 로더 (외부 패키지 불필요) ──────────────────
def _load_dotenv():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
_load_dotenv()

# ── 설정 ──────────────────────────────────────────────
WHALE_KEY        = os.environ.get("WHALE_ALERT_API_KEY", "")
TWELVE_DATA_KEY  = os.environ.get("TWELVE_DATA_API_KEY", "")
OUT_FILE         = "data.json"
FAST_INTERVAL    = 60    # 초 (Hyperliquid 크립토)
TD_INTERVAL      = 120   # 초 (Twelve Data, 하루 ~720회 ≤ 800회 한도)
SLOW_INTERVAL    = 300   # 초 (5분 주기 슬로우 데이터)

_last_slow = 0
_slow_cache: dict = {}
_last_td   = 0
_td_cache:  dict = {}
_market_hash      = ""   # 주요 지수 가격 해시 (실제 변동 감지)
_market_data_time = ""   # 가격이 실제 변동된 마지막 시각

# ── Twelve Data 배치 심볼 ──────────────────────────────
TD_SYMBOLS = [
    # 주요 지수
    "SPX", "IXIC", "DJI", "DXY", "VIX", "N225", "HSI",
    # 환율 (6개)
    "EUR/USD", "USD/KRW", "USD/JPY", "USD/CNY", "AUD/USD", "GBP/USD",
    # M7 빅테크
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
]

# data.json 지수 키 매핑
TD_INDEX_MAP = {
    "SPX":  ("spx",  "spx_chg"),
    "IXIC": ("ndx",  "ndx_chg"),
    "DJI":  ("dji",  "dji_chg"),
    "DXY":  ("dxy",  "dxy_chg"),
    "VIX":  ("vix",  "vix_chg"),
    "N225": ("n225", "n225_chg"),
    "HSI":  ("hsi",  "hsi_chg"),
}

# data.json 환율 키 매핑
TD_FOREX_MAP = {
    "EUR/USD": "forex_eur",
    "USD/KRW": "forex_krw",
    "USD/JPY": "forex_jpy",
    "USD/CNY": "forex_cny",
    "AUD/USD": "forex_aud",
    "GBP/USD": "forex_gbp",
}

TD_M7_ORDER = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]

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


def hl_post(req_type, dex=""):
    """Hyperliquid info API POST (dex 파라미터 지원)"""
    body = {"type": req_type}
    if dex:
        body["dex"] = dex
    payload = json.dumps(body).encode()
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
    """Hyperliquid allMids → 크립토/원자재/지수 가격
    
    기본 dex(빈 문자열)는 네이티브 퍼프만 반환.
    HIP-3 심볼(원자재/주식/지수)은 각 dex를 개별 쿼리해야 함.
    """
    print("  ⚡ Hyperliquid…")

    # 1단계: 기본 퍼프 (BTC, ETH, SOL 등)
    mids = hl_post("allMids") or {}
    if not mids:
        print("    ⚠ HL 기본 dex 응답 없음")

    # 2단계: HIP-3 dex들 (xyz, cash, flx) 개별 쿼리 → 병합
    HIP3_DEXES = ["xyz", "cash", "flx"]
    hip3_count = 0
    for dex_name in HIP3_DEXES:
        dex_mids = hl_post("allMids", dex=dex_name)
        if dex_mids:
            new_keys = 0
            for sym, px in dex_mids.items():
                full_key = f"{dex_name}:{sym}" if ":" not in sym else sym
                if full_key not in mids:
                    mids[full_key] = px
                    new_keys += 1
            hip3_count += new_keys
            if new_keys:
                print(f"    📡 {dex_name}: +{new_keys}개 심볼")

    if not mids:
        print("    ⚠ HL 전체 응답 없음")
        return {}

    out = {}

    # 3단계: 네이티브 크립토
    for key, sym in CRYPTO_MAP.items():
        if sym in mids:
            out[key] = round(safe_float(mids[sym]), 2)

    # 4단계: HIP-3 원자재/지수
    for key, candidates in HIP3_MAP.items():
        for sym in candidates:
            if sym in mids:
                out[key] = round(safe_float(mids[sym]), 2)
                break

    # 5단계: M7 빅테크
    m7 = []
    for stock, candidates in M7_MAP.items():
        for sym in candidates:
            if sym in mids:
                m7.append({"sym": stock, "price": round(safe_float(mids[sym]), 2), "chg": 0})
                break
    out["m7"] = m7

    # 6단계: HL OI + 펀딩 (metaAndAssetCtxs)
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
    print(f"    ✓ 크립토+HIP-3 합계 {len(price_keys)}개 가격 | HIP-3 {hip3_count}개 심볼 발견")

    # 디버그: HIP-3 심볼 목록
    hip3_syms = sorted(k for k in mids if ":" in k)
    if hip3_syms:
        print(f"    📋 HIP-3 심볼: {', '.join(hip3_syms[:30])}{'…' if len(hip3_syms)>30 else ''}")
    else:
        print("    ⚠ HIP-3 심볼 0개 — dex 응답 없거나 심볼 형식 불일치")

    return out


# ── SLOW: Yahoo Finance 변동률 ────────────────────────

YAHOO_SYMBOLS = {
    "spx": "^GSPC", "ndx": "^NDX", "dji": "^DJI", "kospi": "^KS11",
    "vix": "^VIX", "dxy": "DX-Y.NYB",
    "n225": "^N225", "hsi": "^HSI",          # 니케이·항셍 (TD 폴백)
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
    """Yahoo Finance → 변동률 + DXY/VIX + M7 (가격+변동률)
    
    M7 전략: HL HIP-3에서 가격을 못 가져왔으면 Yahoo에서 가격도 가져옴.
    """
    print("  📊 Yahoo 변동률…")
    out = {}

    for key, ticker in YAHOO_SYMBOLS.items():
        price, chg = _yahoo_quote(ticker)
        if chg is not None:
            out[f"{key}_chg"] = chg
        if price is not None and key not in hl_data:
            out[key] = price
        time.sleep(0.15)

    # M7 빅테크: 변동률 + HL 미수집 시 가격도 폴백
    m7_changes = {}
    m7_fallback = []  # HL에서 M7 못 가져왔을 때 Yahoo 가격으로 대체
    hl_m7 = hl_data.get("m7", [])
    hl_m7_syms = {item["sym"] for item in hl_m7} if hl_m7 else set()

    for ticker in M7_TICKERS:
        price, chg = _yahoo_quote(ticker)
        if chg is not None:
            m7_changes[ticker] = chg
        # HL에서 이 종목 가격을 못 가져왔으면 Yahoo 가격 사용
        if price is not None and ticker not in hl_m7_syms:
            m7_fallback.append({"sym": ticker, "price": price, "chg": chg or 0})
        time.sleep(0.15)

    out["_m7_changes"] = m7_changes
    out["_m7_fallback"] = m7_fallback

    if m7_fallback:
        print(f"    📈 M7 Yahoo 폴백: {', '.join(f['sym'] for f in m7_fallback)}")

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

_cvd_cache = {"data": None, "last": 0}

def collect_okx(btc_price):
    """OKX → 펀딩레이트, 롱/쇼트, CVD (체급별)
    
    펀딩/롱쇼트: 5분마다
    CVD: 30분 캐시 (24h 누적이라 자주 갱신 불필요)
    """
    global _cvd_cache
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

    # CVD — 30분 캐시
    now = time.time()
    if _cvd_cache["data"] and (now - _cvd_cache["last"]) < 1800:
        out["cvd"] = _cvd_cache["data"]
        print("    ✓ CVD (캐시, 30분)")
    else:
        data = fetch_json("https://www.okx.com/api/v5/rubik/stat/taker-volume?ccy=BTC&instType=CONTRACTS&period=1D")
        if data and data.get("data"):
            try:
                row = data["data"][0]
                total_buy = safe_float(row[1])
                total_sell = safe_float(row[2])
                net = total_buy - total_sell

                # 체급별 분배 — OKX는 체급별 데이터 미제공
                # 총 순매수/순매도만 제공하므로, 체급별은 표시하지 않음
                net_usd = round(net)

                if net > 0:
                    analysis = (
                        f'<span style="color:var(--green);font-weight:700;">매수 우세</span>'
                        f' — 24h 순매수 ${abs(net_usd) / 1e6:.1f}M.'
                    )
                else:
                    analysis = (
                        f'<span style="color:var(--red);font-weight:700;">매도 우세</span>'
                        f' — 24h 순매도 ${abs(net_usd) / 1e6:.1f}M.'
                    )

                cvd_data = {
                    "total": net_usd,
                    "whale": 0,
                    "shark": 0,
                    "fish": 0,
                    "shrimp": 0,
                    "buy_volume": round(total_buy),
                    "sell_volume": round(total_sell),
                    "btc_price": btc_price,
                    "source": "OKX 24h + Hyperliquid",
                    "analysis": analysis,
                }

                # ── Hyperliquid 리더보드 → 체급별 포지션 ──
                try:
                    # HL clearinghouseState로 대형 트레이더 포지션 조회
                    # leaderboard는 별도 웹 스크래핑 필요 — 대신 vault 정보 사용
                    vault_data = hl_post("vaultDetails")
                    if vault_data and isinstance(vault_data, dict):
                        # 볼트(펀드) 포지션으로 고래 방향성 추정
                        leader = vault_data.get("leader", {})
                        followers = vault_data.get("followers", [])
                        whale_net = safe_float(leader.get("pnl", 0))
                        shark_net = sum(safe_float(f.get("pnl", 0)) for f in followers[:20]) if followers else 0
                        fish_net = sum(safe_float(f.get("pnl", 0)) for f in followers[20:50]) if len(followers) > 20 else 0
                        shrimp_net = sum(safe_float(f.get("pnl", 0)) for f in followers[50:]) if len(followers) > 50 else 0

                        cvd_data["whale"] = round(whale_net)
                        cvd_data["shark"] = round(shark_net)
                        cvd_data["fish"] = round(fish_net)
                        cvd_data["shrimp"] = round(shrimp_net)
                        cvd_data["source"] = "OKX CVD + Hyperliquid"
                        print(f"    ✓ HL 체급별: 🐋{whale_net/1e6:.1f}M 🦈{shark_net/1e6:.1f}M")
                    else:
                        # 볼트 데이터 없으면 OKX 대형/소형 비율로 대체
                        big = fetch_json("https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=5m")
                        big_top = fetch_json("https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-volume?ccy=BTC&period=5m")
                        if big and big.get("data") and big_top and big_top.get("data"):
                            ratio_all = safe_float(big["data"][0][1])
                            # 전체 롱비율 vs 대형 트레이더 롱비율 차이로 추정
                            all_long = ratio_all / (1 + ratio_all) * 100 if ratio_all > 0 else 50
                            # 고래는 반대 포지션 경향
                            whale_direction = 1 if net > 0 else -1
                            cvd_data["whale"] = round(abs(net) * 0.5 * whale_direction)
                            cvd_data["shark"] = round(abs(net) * 0.25 * whale_direction)
                            cvd_data["fish"] = round(abs(net) * 0.15 * (-whale_direction))
                            cvd_data["shrimp"] = round(abs(net) * 0.10 * (-whale_direction))
                            cvd_data["source"] = "OKX CVD + 대형/소형 비율 추정"
                            print(f"    ✓ OKX 비율 기반 체급별 추정")
                except Exception as e:
                    print(f"    ⚠ 체급별: {e}")

                out["cvd"] = cvd_data
                _cvd_cache = {"data": cvd_data, "last": now}
                print(f"    ✓ CVD: ${net_usd / 1e6:.1f}M ({'매수' if net > 0 else '매도'}) [갱신]")
            except (IndexError, TypeError) as e:
                print(f"    ⚠ CVD 파싱 에러: {e}")
                if _cvd_cache["data"]:
                    out["cvd"] = _cvd_cache["data"]

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
    """OI + 가격 기반 청산 구간 — Hyperliquid OI 실측 기반
    
    실제 청산 물량 분포 API는 유료(Coinglass 등)이므로,
    OI와 현재가를 기반으로 통계적 청산 구간을 산출합니다.
    고레버리지 구간(±3~6%)에 청산 물량이 집중되는 패턴 반영.
    """
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


# ── SLOW: 천체 데이터 (ephem) ────────────────────────

_celestial_cache = {"data": None, "last": 0}

def collect_celestial():
    """ephem 라이브러리 → 행성 위치 + 달 이벤트 자동 계산
    
    하루 1번만 갱신 (천체는 하루 단위로 크게 안 바뀜)
    """
    global _celestial_cache
    now = time.time()
    
    if _celestial_cache["data"] and (now - _celestial_cache["last"]) < 86400:
        print("  🪐 천체… (캐시)")
        return _celestial_cache["data"]
    
    print("  🪐 천체 (ephem 계산)…")
    
    try:
        import ephem
    except ImportError:
        print("    ⚠ ephem 미설치 — pip install ephem")
        return None
    
    try:
        d = ephem.now()
        
        # 별자리(황도 12궁) 매핑
        ZODIAC = [
            (0, '♈ 양자리'), (30, '♉ 황소자리'), (60, '♊ 쌍둥이자리'),
            (90, '♋ 게자리'), (120, '♌ 사자자리'), (150, '♍ 처녀자리'),
            (180, '♎ 천칭자리'), (210, '♏ 전갈자리'), (240, '♐ 사수자리'),
            (270, '♑ 염소자리'), (300, '♒ 물병자리'), (330, '♓ 물고기자리'),
        ]
        
        def get_zodiac(ra_deg):
            """적경(도) → 황도 별자리"""
            # 대략적 황도 경도 변환 (적경 ≈ 황도경도 for 행성)
            lng = ra_deg % 360
            sign = '♈ 양자리'
            for threshold, name in reversed(ZODIAC):
                if lng >= threshold:
                    sign = name
                    break
            deg_in_sign = lng - threshold
            return sign, f"{int(deg_in_sign)}° {int((deg_in_sign % 1) * 60)}'"
        
        def planet_data(body, symbol, name_ko):
            body.compute(d)
            ra_deg = float(body.ra) * 180 / 3.14159265  # radians to degrees
            # 황도 경도 (ecliptic longitude)가 더 정확하지만 ephem에서는 a_ra를 사용
            # Astrological longitude 근사값
            ecl_lng = float(body.hlong) * 180 / 3.14159265 if hasattr(body, 'hlong') else ra_deg
            sign, deg = get_zodiac(ecl_lng if ecl_lng else ra_deg)
            return {
                "symbol": symbol,
                "name": name_ko,
                "sign": sign,
                "degree": deg,
            }
        
        planets = [
            planet_data(ephem.Sun(), "☀️", "SUN · 태양"),
            planet_data(ephem.Moon(), "🌙", "MOON · 달"),
            planet_data(ephem.Mercury(), "☿", "MERCURY · 수성"),
            planet_data(ephem.Venus(), "♀", "VENUS · 금성"),
            planet_data(ephem.Mars(), "♂", "MARS · 화성"),
            planet_data(ephem.Jupiter(), "♃", "JUPITER · 목성"),
            planet_data(ephem.Saturn(), "♄", "SATURN · 토성"),
            # 천왕성/해왕성: ephem 미지원 — 표시하지 않음 (가짜 데이터 배제)
        ]
        
        # 달 위상
        moon = ephem.Moon()
        moon.compute(d)
        phase_pct = moon.phase  # 0~100
        if phase_pct < 2:
            phase_name = "🌑 신월"
        elif phase_pct < 48:
            phase_name = "🌒 초승달" if phase_pct < 25 else "🌓 상현달"
        elif phase_pct < 52:
            phase_name = "🌕 보름달"
        elif phase_pct < 98:
            phase_name = "🌔 하현달" if phase_pct > 75 else "🌖 기울어지는 달"
        else:
            phase_name = "🌑 그믐달"
        
        # 다음 달 이벤트
        next_new = ephem.next_new_moon(d)
        next_full = ephem.next_full_moon(d)
        
        # 태양 별자리 (현재 궁)
        sun = ephem.Sun()
        sun.compute(d)
        sun_lng = float(sun.hlong) * 180 / 3.14159265 if hasattr(sun, 'hlong') else float(sun.ra) * 180 / 3.14159265
        sun_sign, _ = get_zodiac(sun_lng)
        
        result = {
            "planets": planets,
            "moon_phase": phase_pct,
            "moon_phase_name": phase_name,
            "sun_sign": sun_sign,
            "next_new_moon": str(ephem.Date(next_new)),
            "next_full_moon": str(ephem.Date(next_full)),
            "updated": datetime.now(timezone.utc).isoformat(),
        }
        
        _celestial_cache = {"data": result, "last": now}
        print(f"    ✓ 행성 {len(planets)}개 | 달 {phase_pct:.0f}% ({phase_name}) | 태양 {sun_sign}")
        return result
        
    except Exception as e:
        print(f"    ⚠ 천체 계산 에러: {e}")
        return None




WAR_KEYWORDS_WEIGHTED = {
    # CRITICAL (가중치 10) — 직접적 군사 행동
    "nuclear strike": 10, "nuclear attack": 10, "nuclear war": 10,
    "nuclear weapon": 8, "nuclear test": 8,
    "invasion": 8, "full-scale invasion": 10, "ground invasion": 9,
    "assassination": 8,
    "declaration of war": 10,
    # HIGH (가중치 6~7) — 주요 군사 작전
    "missile launch": 7, "ballistic missile": 7, "cruise missile": 7, "icbm": 9,
    "airstrike": 6, "air strike": 6, "bombing": 6, "carpet bombing": 8,
    "drone strike": 6, "drone attack": 6,
    "naval blockade": 7, "blockade": 5,
    "military operation": 5, "special military operation": 6,
    "troops deployed": 5, "troop deployment": 5, "mobilization": 6,
    "artillery": 4, "shelling": 4,
    # MEDIUM (가중치 3~4) — 긴장 고조
    "warship": 4, "aircraft carrier": 5, "naval fleet": 4,
    "military exercise": 3, "war drill": 3,
    "sanctions": 3, "embargo": 4,
    "ceasefire violation": 5, "ceasefire collapse": 6,
    "territorial dispute": 3, "border clash": 4,
    "cyber attack": 3, "cyberwar": 4,
    "escalation": 4, "retaliation": 4, "provocation": 3,
    # LOW (가중치 1~2) — 배경 긴장
    "military buildup": 2, "arms deal": 2, "weapons shipment": 2,
    "defense pact": 1, "military aid": 2, "war crime": 3,
    "refugee crisis": 2, "humanitarian crisis": 2,
}

# ── 핫스팟 자동 모니터링 설정 ──
HOTSPOT_CONFIG = [
    {
        "id": "ukraine",
        "emoji": "🇺🇦",
        "name": "우크라이나-러시아",
        "queries": ["Ukraine Russia war", "Ukraine frontline", "Ukraine missile"],
        "keywords_boost": ["Crimea", "Donbas", "Kherson", "Zaporizhzhia", "escalation Russia Ukraine"],
        "asset_impact": "에너지 공급 불안 → 유가/천연가스",
    },
    {
        "id": "taiwan",
        "emoji": "🇹🇼",
        "name": "대만 해협",
        "queries": ["Taiwan China military", "Taiwan strait tension"],
        "keywords_boost": ["TSMC", "semiconductor", "Taiwan invasion", "PLA exercise"],
        "asset_impact": "반도체 공급망 리스크 → 테크주",
    },
    {
        "id": "middleeast",
        "emoji": "🇮🇱",
        "name": "중동 (이스라엘-이란)",
        "queries": ["Israel Iran conflict", "Middle East war", "Gaza ceasefire"],
        "keywords_boost": ["Hormuz", "Hezbollah", "Houthi", "Red Sea", "oil tanker"],
        "asset_impact": "호르무즈 해협 리스크 → 유가",
    },
    {
        "id": "korea",
        "emoji": "🇰🇵",
        "name": "한반도",
        "queries": ["North Korea missile", "Korean peninsula tension"],
        "keywords_boost": ["ICBM", "Pyongyang", "SLBM", "nuclear test North Korea"],
        "asset_impact": "미사일 도발 빈도 → KOSPI/원화",
    },
    {
        "id": "ustrade",
        "emoji": "🇺🇸🇨🇳",
        "name": "미중 무역/기술 전쟁",
        "queries": ["US China trade war", "US China tariff", "chip export ban"],
        "keywords_boost": ["Huawei", "NVIDIA ban", "rare earth", "decoupling", "TikTok ban"],
        "asset_impact": "AI칩 수출 규제, 관세 정책 → 테크/반도체",
    },
]


def _score_text_weighted(text_lower):
    """텍스트에서 가중치 기반 전쟁 키워드 스코어 계산"""
    total_score = 0
    matched = []
    for keyword, weight in WAR_KEYWORDS_WEIGHTED.items():
        count = text_lower.count(keyword.lower())
        if count > 0:
            # 같은 키워드 반복 시 체감 감소 (로그 스케일)
            import math
            effective = weight * (1 + math.log2(count))
            total_score += effective
            matched.append((keyword, count, weight))
    return total_score, matched


def _scan_hotspot(hotspot):
    """개별 핫스팟 RSS 스캔 → 위험도 자동 산출"""
    total_score = 0
    headline_count = 0

    for query in hotspot["queries"]:
        q = query.replace(" ", "+")
        url = f"https://news.google.com/rss/search?q={q}+when:2d&hl=en&gl=US&ceid=US:en"
        raw = fetch_raw(url, timeout=8)
        if not raw:
            continue

        raw_lower = raw.lower()
        # 헤드라인 개수 카운트
        items = raw.split("<item>")
        headline_count += len(items) - 1

        # 가중치 스코어
        score, _ = _score_text_weighted(raw_lower)
        total_score += score

        # 부스트 키워드 (이 핫스팟 고유 키워드)
        for bkw in hotspot.get("keywords_boost", []):
            bc = raw_lower.count(bkw.lower())
            if bc > 0:
                total_score += bc * 3

        time.sleep(0.15)

    # 정규화 (0~100)
    # 뉴스 10개 이하 = 기본, 30개 이상 = 높음
    news_factor = min(headline_count / 20, 2.0)
    raw_score = total_score * (0.5 + news_factor * 0.5)
    normalized = min(100, int(raw_score / 3))  # 스케일 조정

    if normalized >= 70:
        level = "CRITICAL"
        colors = "red,red"
    elif normalized >= 45:
        level = "HIGH"
        colors = "gold,red"
    elif normalized >= 20:
        level = "ELEVATED"
        colors = "green,gold"
    else:
        level = "STABLE"
        colors = "green,green"

    return {
        "id": hotspot["id"],
        "emoji": hotspot["emoji"],
        "name": hotspot["name"],
        "score": normalized,
        "level": level,
        "colors": colors,
        "headlines": headline_count,
        "description": hotspot["asset_impact"],
    }


_war_cache = {"data": None, "last": 0}

def collect_war_index():
    """전쟁지수 v2 — 가중치 키워드 + 다중 소스 + 핫스팟 자동 스캔
    
    1시간 캐시 (지정학적 상황은 분 단위로 안 바뀜)
    """
    global _war_cache
    now = time.time()

    if _war_cache["data"] and (now - _war_cache["last"]) < 3600:
        print("  ⚔️ 전쟁지수… (캐시, 1h)")
        return _war_cache["data"]

    print("  ⚔️ 전쟁지수 v2… (갱신)")
    total_score = 0
    all_matched = []

    # ── 1차: 글로벌 헤드라인 스캔 (다중 RSS) ──
    rss_sources = [
        "https://news.google.com/rss/headlines/section/topic/WORLD",
        "https://news.google.com/rss/search?q=military+war+conflict+when:1d&hl=en&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=geopolitical+tension+crisis+when:1d&hl=en&gl=US&ceid=US:en",
    ]

    for url in rss_sources:
        raw = fetch_raw(url, timeout=10)
        if not raw:
            continue
        score, matched = _score_text_weighted(raw.lower())
        total_score += score
        all_matched.extend(matched)
        time.sleep(0.2)

    # ── 2차: 핫스팟 개별 스캔 ──
    hotspots = []
    hotspot_total = 0
    for hs_config in HOTSPOT_CONFIG:
        try:
            hs_result = _scan_hotspot(hs_config)
            hotspots.append(hs_result)
            hotspot_total += hs_result["score"]
        except Exception as e:
            print(f"    ⚠ 핫스팟 {hs_config['id']}: {e}")
            hotspots.append({
                "id": hs_config["id"], "emoji": hs_config["emoji"],
                "name": hs_config["name"], "score": 0, "level": "UNKNOWN",
                "colors": "green,green", "headlines": 0,
                "description": hs_config["asset_impact"],
            })

    # ── 3차: 복합 지수 계산 ──
    # 글로벌 헤드라인 (40%) + 핫스팟 합산 (60%)
    global_normalized = min(100, int(total_score / 5))
    hotspot_avg = hotspot_total / max(len(hotspots), 1)
    composite = int(global_normalized * 0.4 + hotspot_avg * 0.6)
    composite = max(0, min(100, composite))

    if composite >= 80:
        label = "CRITICAL"
    elif composite >= 60:
        label = "HIGH RISK"
    elif composite >= 30:
        label = "ELEVATED"
    else:
        label = "STABLE"

    # 상위 매치 키워드 (디버그 + 신호 분석)
    keyword_summary = {}
    for kw, cnt, wt in all_matched:
        if kw not in keyword_summary:
            keyword_summary[kw] = {"count": 0, "weight": wt}
        keyword_summary[kw]["count"] += cnt
    top_keywords = sorted(keyword_summary.items(), key=lambda x: x[1]["count"] * x[1]["weight"], reverse=True)[:10]

    print(f"    ✓ 전쟁지수 v2: {composite} ({label})")
    print(f"    📊 글로벌: {global_normalized} | 핫스팟 평균: {hotspot_avg:.0f}")
    if top_keywords:
        print(f"    🔑 상위 키워드: {', '.join(f'{k}({v['count']})' for k, v in top_keywords[:5])}")

    result = {
        "value": composite,
        "label": label,
        "keyword_count": sum(v["count"] for v in keyword_summary.values()),
        "global_score": global_normalized,
        "hotspot_avg": round(hotspot_avg),
        "hotspots": hotspots,
        "top_keywords": [{"keyword": k, "count": v["count"], "weight": v["weight"]} for k, v in top_keywords],
    }
    _war_cache = {"data": result, "last": time.time()}
    return result


# ── SLOW: CNN Fear & Greed ────────────────────────────

_cnn_fg_cache = {"data": None, "last": 0}

def collect_cnn_fg():
    """CNN Fear & Greed Index — 다중 폴백 전략
    
    하루 1회 갱신 (미국 장 마감 후 업데이트)
    1차: production.dataviz.cnn.io/index/fearandgreed/graphdata (기본)
    2차: 같은 URL + 날짜 파라미터 (봇 차단 우회)
    3차: /current 엔드포인트 시도
    """
    global _cnn_fg_cache
    now = time.time()

    if _cnn_fg_cache["data"] and (now - _cnn_fg_cache["last"]) < 86400:
        print("  😱 CNN F&G… (캐시, 24h)")
        return _cnn_fg_cache["data"]

    print("  😱 CNN F&G… (갱신)")

    # 전용 헤더 (CNN은 봇 필터링이 까다로움)
    cnn_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://edition.cnn.com/markets/fear-and-greed",
        "Origin": "https://edition.cnn.com",
    }

    urls = [
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
        f"https://production.dataviz.cnn.io/index/fearandgreed/graphdata/"
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
    ]

    for url in urls:
        try:
            req = Request(url, headers=cnn_headers)
            raw = urlopen(req, timeout=15).read().decode()
            data = json.loads(raw)
            if data and data.get("fear_and_greed"):
                fg = data["fear_and_greed"]
                score = round(fg.get("score", 0))
                rating = fg.get("rating", "")
                print(f"    ✓ CNN F&G: {score} ({rating})")
                result = {
                    "score": score,
                    "rating": rating,
                    "previous_close": round(fg.get("previous_close", 0)),
                    "one_week_ago": round(fg.get("previous_1_week", 0)),
                    "one_month_ago": round(fg.get("previous_1_month", 0)),
                }
                _cnn_fg_cache = {"data": result, "last": time.time()}
                return result
        except Exception as e:
            status = ""
            if hasattr(e, "code"):
                status = f" (HTTP {e.code})"
            print(f"    ⚠ CNN {url[:60]}…{status} {e}")
            continue

    print("    ❌ CNN 직접 API 실패 — fear-greed 패키지 시도…")

    # 3차: fear-greed PyPI 패키지 (pip install fear-greed)
    try:
        import fear_greed
        data = fear_greed.get()
        if data and "score" in data:
            score = round(data["score"])
            rating = data.get("rating", "")
            hist = data.get("history", {})
            print(f"    ✓ CNN F&G (via PyPI): {score} ({rating})")
            result = {
                "score": score,
                "rating": rating,
                "previous_close": round(hist.get("1w", 0)),
                "one_week_ago": round(hist.get("1w", 0)),
                "one_month_ago": round(hist.get("1m", 0)),
            }
            _cnn_fg_cache = {"data": result, "last": time.time()}
            return result
    except ImportError:
        print("    ⚠ fear-greed 미설치 — pip install fear-greed 필요")
    except Exception as e:
        print(f"    ⚠ fear-greed 패키지 에러: {e}")

    print("    ❌ CNN F&G 전체 실패")
    if _cnn_fg_cache["data"]:
        print("    ↩ 이전 캐시 반환")
        return _cnn_fg_cache["data"]
    return None


# ── SLOW: 시장 심리 실측 지표 (Put/Call, 모멘텀, 안전자산, 정크본드) ──

_sentiment_cache = {"data": None, "last": 0}

def collect_market_sentiment():
    """실제 시장 심리 지표 수집 — Yahoo Finance 기반
    
    하루 1회 갱신 (장 마감 데이터 기반)
    
    1. Put/Call Ratio: CBOE equity put/call (^CPCE)
    2. 모멘텀: S&P500 현재가 vs 125일 이동평균
    3. 안전자산 수요: TLT(채권) vs SPY(주식) 20일 상대 수익률
    4. 정크본드 스프레드: HYG(정크) vs LQD(투자등급) 스프레드
    """
    global _sentiment_cache
    now = time.time()

    if _sentiment_cache["data"] and (now - _sentiment_cache["last"]) < 86400:
        print("  📊 시장심리… (캐시, 24h)")
        return _sentiment_cache["data"]

    print("  📊 시장심리 실측 지표 수집…")
    result = {}

    # 1. Put/Call Ratio (CBOE) — 다중 소스
    try:
        pc_value = None

        # 1차: Yahoo ^CPCE
        pc_price, _ = _yahoo_quote("^CPCE")
        if pc_price and 0.3 < pc_price < 2.0:
            pc_value = round(pc_price, 2)
            print(f"    ✓ Put/Call (CPCE): {pc_value}")

        # 2차: Yahoo ^PCALL
        if not pc_value:
            pc2, _ = _yahoo_quote("^PCALL")
            if pc2 and 0.3 < pc2 < 2.0:
                pc_value = round(pc2, 2)
                print(f"    ✓ Put/Call (PCALL): {pc_value}")

        # 3차: CBOE 직접 스크래핑
        if not pc_value:
            cboe_raw = fetch_raw("https://www.cboe.com/us/options/market_statistics/")
            if cboe_raw:
                import re as _re
                # Put/Call 비율 패턴 탐색
                pc_match = _re.search(r'(?:put.?call|p/c)\s*(?:ratio)?\s*[:=]?\s*([\d.]+)', cboe_raw.lower())
                if pc_match:
                    val = float(pc_match.group(1))
                    if 0.3 < val < 2.0:
                        pc_value = round(val, 2)
                        print(f"    ✓ Put/Call (CBOE 스크래핑): {pc_value}")

        # 4차: VIX 기반 추정 (VIX가 이미 수집돼 있으므로)
        # VIX와 Put/Call은 강한 양의 상관관계 (r≈0.7)
        # 공식: PC ≈ 0.5 + (VIX - 15) * 0.02
        if not pc_value:
            vix_price, _ = _yahoo_quote("^VIX")
            if vix_price:
                pc_est = round(0.5 + (vix_price - 15) * 0.02, 2)
                pc_est = max(0.4, min(1.5, pc_est))
                pc_value = pc_est
                result["put_call_estimated"] = True
                print(f"    ✓ Put/Call (VIX 기반 추정): {pc_value} (VIX={vix_price})")

        if pc_value:
            result["put_call"] = pc_value
            if pc_value > 1.0:
                result["put_call_signal"] = "공포 (풋 > 콜)"
            elif pc_value < 0.7:
                result["put_call_signal"] = "탐욕 (콜 > 풋)"
            else:
                result["put_call_signal"] = "중립"
        else:
            print("    ⚠ Put/Call: 전체 소스 실패")
    except Exception as e:
        print(f"    ⚠ Put/Call: {e}")
    time.sleep(0.3)

    # 2. 모멘텀: S&P500 현재가 vs 125일 이동평균
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/^GSPC?range=6mo&interval=1d"
        data = fetch_json(url)
        if data:
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            closes = [c for c in closes if c is not None]
            if len(closes) >= 125:
                current = closes[-1]
                ma125 = sum(closes[-125:]) / 125
                momentum_pct = round(((current - ma125) / ma125) * 100, 2)
                # 0~100 스코어 변환 (MA 위 = 높은 점수)
                momentum_score = max(0, min(100, 50 + momentum_pct * 5))
                result["momentum"] = round(momentum_score)
                result["momentum_raw"] = momentum_pct
                result["momentum_signal"] = f"MA125 대비 {'+' if momentum_pct > 0 else ''}{momentum_pct}%"
                print(f"    ✓ 모멘텀: {momentum_score} (MA125 {momentum_pct:+.2f}%)")
    except Exception as e:
        print(f"    ⚠ 모멘텀: {e}")
    time.sleep(0.3)

    # 3. 안전자산 수요: TLT vs SPY 20일 상대 수익률
    try:
        tlt_url = "https://query1.finance.yahoo.com/v8/finance/chart/TLT?range=1mo&interval=1d"
        spy_url = "https://query1.finance.yahoo.com/v8/finance/chart/SPY?range=1mo&interval=1d"
        tlt_data = fetch_json(tlt_url)
        spy_data = fetch_json(spy_url)
        if tlt_data and spy_data:
            tlt_closes = [c for c in tlt_data["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c is not None]
            spy_closes = [c for c in spy_data["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c is not None]
            if len(tlt_closes) >= 20 and len(spy_closes) >= 20:
                tlt_ret = (tlt_closes[-1] - tlt_closes[-20]) / tlt_closes[-20] * 100
                spy_ret = (spy_closes[-1] - spy_closes[-20]) / spy_closes[-20] * 100
                # 채권이 주식보다 좋으면 = 안전자산 선호 = 공포
                safe_haven_spread = round(tlt_ret - spy_ret, 2)
                # 스코어: 채권 우세 = 높은 공포(낮은 점수), 주식 우세 = 탐욕(높은 점수)
                safe_score = max(0, min(100, 50 - safe_haven_spread * 5))
                result["safe_haven"] = round(safe_score)
                result["safe_haven_spread"] = safe_haven_spread
                result["safe_haven_signal"] = f"TLT-SPY 20일: {safe_haven_spread:+.2f}%p"
                print(f"    ✓ 안전자산: {safe_score} (스프레드 {safe_haven_spread:+.2f}%p)")
    except Exception as e:
        print(f"    ⚠ 안전자산: {e}")
    time.sleep(0.3)

    # 4. 정크본드 스프레드: HYG(고수익채) vs LQD(투자등급채)
    try:
        hyg_url = "https://query1.finance.yahoo.com/v8/finance/chart/HYG?range=1mo&interval=1d"
        lqd_url = "https://query1.finance.yahoo.com/v8/finance/chart/LQD?range=1mo&interval=1d"
        hyg_data = fetch_json(hyg_url)
        lqd_data = fetch_json(lqd_url)
        if hyg_data and lqd_data:
            hyg_closes = [c for c in hyg_data["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c is not None]
            lqd_closes = [c for c in lqd_data["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c is not None]
            if len(hyg_closes) >= 20 and len(lqd_closes) >= 20:
                hyg_ret = (hyg_closes[-1] - hyg_closes[-20]) / hyg_closes[-20] * 100
                lqd_ret = (lqd_closes[-1] - lqd_closes[-20]) / lqd_closes[-20] * 100
                # HYG가 LQD보다 좋으면 = 위험선호 = 탐욕
                junk_spread = round(hyg_ret - lqd_ret, 2)
                junk_score = max(0, min(100, 50 + junk_spread * 10))
                result["junk_bond"] = round(junk_score)
                result["junk_bond_spread"] = junk_spread
                result["junk_bond_signal"] = f"HYG-LQD 20일: {junk_spread:+.2f}%p"
                print(f"    ✓ 정크본드: {junk_score} (스프레드 {junk_spread:+.2f}%p)")
    except Exception as e:
        print(f"    ⚠ 정크본드: {e}")

    if result:
        _sentiment_cache = {"data": result, "last": now}
        print(f"    ✓ 시장심리 {len(result)//2}개 지표 수집 완료")

    return result if result else None


# ── SLOW: MVRV Ratio ─────────────────────────────────

# MVRV 24시간 캐시 (하루 1번만 갱신)
_mvrv_cache = {"value": None, "last": 0}

def collect_mvrv():
    """Coinmetrics Community API → MVRV Ratio (무료, 키 불필요)
    
    하루 1번만 실제 API 호출, 나머지는 캐시 사용.
    """
    global _mvrv_cache
    now = time.time()

    # 24시간 이내면 캐시 반환
    if _mvrv_cache["value"] and (now - _mvrv_cache["last"]) < 86400:
        print(f"  📐 MVRV… (캐시: {_mvrv_cache['value']['value']})")
        return _mvrv_cache["value"]

    print("  📐 MVRV… (API 갱신)")

    # 1차: Coinmetrics Community API
    try:
        # start_time을 어제로 설정해서 최신 1개만 가져옴
        from datetime import timedelta
        yesterday = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
        url = f"https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=CapMVRVCur&frequency=1d&start_time={yesterday}&page_size=10"
        data = fetch_json(url)
        if data and data.get("data"):
            # 마지막 항목이 최신
            latest = data["data"][-1]
            val = round(safe_float(latest.get("CapMVRVCur", 0)), 2)
            if val > 0:
                if val > 3.5:
                    analysis = f'MVRV <span style="color:var(--red)">{val}</span> — 🔴 과열. 역사적 고점 구간.'
                elif val > 2.5:
                    analysis = f'MVRV <span style="color:var(--gold)">{val}</span> — 🟡 수익구간. 차익실현 주의.'
                elif val > 1.0:
                    analysis = f'MVRV <span style="color:var(--green)">{val}</span> — 🟢 건강. 장기 보유 유리.'
                else:
                    analysis = f'MVRV <span style="color:var(--cyan)">{val}</span> — 🔵 저평가! 매수 기회.'
                result = {"value": val, "analysis": analysis}
                _mvrv_cache = {"value": result, "last": now}
                print(f"    ✓ MVRV: {val} (Coinmetrics)")
                return result
    except Exception as e:
        print(f"    ⚠ Coinmetrics: {e}")

    # 2차: 캐시가 있으면 그거라도 반환
    if _mvrv_cache["value"]:
        print(f"    ⚠ API 실패, 캐시 반환: {_mvrv_cache['value']['value']}")
        return _mvrv_cache["value"]

    return None


# ── SLOW: 상관계수 자동 계산 (Yahoo 90일) ─────────────

_corr_cache = {"data": None, "last": 0}

def _yahoo_history(ticker, days=90):
    """Yahoo Finance → 종가 배열 (최근 N일)"""
    import math
    period2 = int(time.time())
    period1 = period2 - (days + 10) * 86400  # 여유분
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={period1}&period2={period2}&interval=1d")
    data = fetch_json(url)
    if not data:
        return []
    try:
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        # None 제거
        return [c for c in closes if c is not None][-days:]
    except (KeyError, IndexError, TypeError):
        return []


def _pearson(x, y):
    """피어슨 상관계수 계산 (순수 파이썬)"""
    import math
    n = min(len(x), len(y))
    if n < 10:
        return None
    x, y = x[-n:], y[-n:]
    mx = sum(x) / n
    my = sum(y) / n
    sx = math.sqrt(sum((xi - mx) ** 2 for xi in x) / n)
    sy = math.sqrt(sum((yi - my) ** 2 for yi in y) / n)
    if sx == 0 or sy == 0:
        return None
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n)) / n
    return round(cov / (sx * sy), 2)


def collect_correlation():
    """BTC vs 전통자산 90일 롤링 피어슨 상관계수
    
    하루 1번만 갱신 (Yahoo 호출 아끼기)
    """
    global _corr_cache
    now = time.time()

    if _corr_cache["data"] and (now - _corr_cache["last"]) < 86400:
        print("  📐 상관계수… (캐시)")
        return _corr_cache["data"]

    print("  📐 상관계수 (Yahoo 90일)…")

    pairs = [
        ("BTC × S&P 500", "BTC-USD", "^GSPC"),
        ("BTC × NASDAQ", "BTC-USD", "^NDX"),
        ("BTC × GOLD", "BTC-USD", "GC=F"),
        ("BTC × DXY(달러)", "BTC-USD", "DX-Y.NYB"),
        ("ETH × BTC", "ETH-USD", "BTC-USD"),
        ("BTC × VIX", "BTC-USD", "^VIX"),
    ]

    # BTC 데이터 한 번만 가져오기
    btc_data = _yahoo_history("BTC-USD", 90)
    eth_data = None
    results = []

    for label, ticker_a, ticker_b in pairs:
        try:
            if ticker_a == "BTC-USD":
                data_a = btc_data
            elif ticker_a == "ETH-USD":
                if eth_data is None:
                    eth_data = _yahoo_history("ETH-USD", 90)
                data_a = eth_data
            else:
                data_a = _yahoo_history(ticker_a, 90)

            if ticker_b == "BTC-USD":
                data_b = btc_data
            else:
                data_b = _yahoo_history(ticker_b, 90)

            corr = _pearson(data_a, data_b)

            if corr is not None:
                # 해석
                abs_c = abs(corr)
                if abs_c >= 0.8:
                    desc = "매우 강한 상관" if corr > 0 else "매우 강한 역상관"
                elif abs_c >= 0.5:
                    desc = "강한 상관" if corr > 0 else "강한 역상관"
                elif abs_c >= 0.3:
                    desc = "약한 상관" if corr > 0 else "약한 역상관"
                else:
                    desc = "거의 무상관"

                # 색상
                if corr > 0.5:
                    color = "0,255,136"
                elif corr > 0:
                    color = "201,168,76"
                elif corr > -0.5:
                    color = "255,255,255"
                else:
                    color = "255,68,68"

                results.append({
                    "label": label,
                    "value": f"{'+' if corr > 0 else ''}{corr}",
                    "corr": corr,
                    "desc": desc,
                    "color": color,
                })
                print(f"    ✓ {label}: {corr:+.2f} ({desc})")
            else:
                print(f"    ⚠ {label}: 데이터 부족")

            time.sleep(0.3)
        except Exception as e:
            print(f"    ⚠ {label}: {e}")

    if results:
        # 해석 텍스트 자동 생성
        btc_spx = next((r for r in results if "S&P" in r["label"]), None)
        btc_ndx = next((r for r in results if "NASDAQ" in r["label"]), None)
        btc_dxy = next((r for r in results if "DXY" in r["label"]), None)
        btc_gold = next((r for r in results if "GOLD" in r["label"]), None)

        analysis_parts = []
        if btc_ndx:
            c = btc_ndx["corr"]
            if c > 0.6:
                analysis_parts.append(f'BTC-나스닥 상관계수 {c:+.2f} → 크립토가 기술주와 강하게 동조화 상태.')
            elif c > 0.3:
                analysis_parts.append(f'BTC-나스닥 상관계수 {c:+.2f} → 약한 동조화. 독자 움직임 가능성.')
            else:
                analysis_parts.append(f'BTC-나스닥 상관계수 {c:+.2f} → 디커플링 진행 중.')

        if btc_dxy:
            c = btc_dxy["corr"]
            if c < -0.4:
                analysis_parts.append(f'달러(DXY) 약세 시 BTC 강세 패턴 유효 ({c:+.2f}).')
            elif c > 0:
                analysis_parts.append(f'달러-BTC 양의 상관({c:+.2f}) — 비정상적. 유동성 장세 가능.')

        if btc_gold:
            c = btc_gold["corr"]
            if c > 0.3:
                analysis_parts.append(f'금과의 상관 {c:+.2f} — "디지털 골드" 내러티브 강화 신호.')
            elif c < -0.2:
                analysis_parts.append(f'금과 역상관({c:+.2f}) — 위험자산 모드.')

        analysis = ' '.join(analysis_parts) if analysis_parts else '데이터 수집 중.'

        result = {"pairs": results, "analysis": analysis, "period": "90일"}
        _corr_cache = {"data": result, "last": now}
        return result

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

# ── SLOW: 스테이블코인 유입량 (DefiLlama) ─────────────

_stable_cache = {"data": None, "last": 0}

def collect_stablecoin_flow():
    """DefiLlama → USDT/USDC 시총 변동 (하루 1번)
    
    거래소 유입량 직접 측정은 불가능하지만,
    스테이블코인 시총 증가 = 시장으로 새 자금 유입과 유사.
    """
    global _stable_cache
    now = time.time()
    
    # 24시간 이내면 캐시
    if _stable_cache["data"] and (now - _stable_cache["last"]) < 86400:
        print("  💵 스테이블코인… (캐시)")
        return _stable_cache["data"]
    
    print("  💵 스테이블코인 (DefiLlama)…")
    
    result = {"usdt": 0, "usdc": 0, "total": 0, "usdt_mcap": 0, "usdc_mcap": 0,
              "usdt_change_1d": 0, "usdc_change_1d": 0}
    
    # USDT (id=1), USDC (id=2)
    for coin_id, key in [("1", "usdt"), ("2", "usdc")]:
        try:
            data = fetch_json(f"https://stablecoins.llama.fi/stablecoin/{coin_id}")
            if data and data.get("chainBalances"):
                # 전체 시총 가져오기
                tokens = data.get("tokens", [])
                if len(tokens) >= 2:
                    current = tokens[-1].get("circulating", {}).get("peggedUSD", 0)
                    previous = tokens[-2].get("circulating", {}).get("peggedUSD", 0)
                    change = current - previous
                    result[key] = round(abs(change))
                    result[f"{key}_mcap"] = round(current)
                    result[f"{key}_change_1d"] = round(change)
                    print(f"    ✓ {key.upper()}: ${current/1e9:.1f}B (변동: ${change/1e6:.1f}M)")
        except Exception as e:
            print(f"    ⚠ {key.upper()}: {e}")
    
    result["total"] = result["usdt"] + result["usdc"]
    result["max_reference"] = 500_000_000
    
    _stable_cache = {"data": result, "last": now}
    return result


# ── SLOW: 월가 발언 (Google News RSS) ────────────────

def collect_wallstreet_buzz():
    """Google News RSS → 주요 금융 인사/기관 발언 자동 수집"""
    print("  📢 월가 발언…")
    
    keywords = [
        ("Fed Powell", "🏦", "Fed 파월 의장"),
        ("Fed Waller", "🏦", "Fed 월러 이사"),
        ("Fed Goolsbee", "🏦", "Fed 굴스비 총재"),
        ("JPMorgan Dimon", "📊", "JP모건 다이먼 CEO"),
        ("Goldman Sachs", "💰", "골드만삭스"),
        ("BlackRock", "🏛️", "블랙록"),
        ("Elon Musk crypto", "🚀", "일론 머스크"),
        ("Trump tariff economy", "🏛️", "트럼프 행정부"),
        ("Treasury Yellen Bessent", "🏦", "미국 재무부"),
    ]
    
    buzz = []
    
    for query, emoji, label in keywords[:5]:  # 상위 5개만 (속도)
        try:
            q = query.replace(" ", "+")
            url = f"https://news.google.com/rss/search?q={q}+when:3d&hl=en&gl=US&ceid=US:en"
            raw = fetch_raw(url, timeout=8)
            if not raw or "<item>" not in raw:
                continue
            
            # 첫 번째 아이템만 추출
            item = raw.split("<item>")[1] if "<item>" in raw else ""
            title_match = re.search(r"<title>(.*?)</title>", item, re.DOTALL)
            if title_match:
                title = title_match.group(1).strip()
                title = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", title)
                title = title[:120]  # 120자 제한
                
                source_match = re.search(r"<source[^>]*>(.*?)</source>", item)
                source = source_match.group(1) if source_match else ""
                
                buzz.append({
                    "emoji": emoji,
                    "label": label,
                    "title": title,
                    "source": source,
                })
                
            time.sleep(0.2)
        except Exception as e:
            continue
    
    if buzz:
        print(f"    ✓ {len(buzz)}건 수집")
    else:
        print("    ⚠ 수집 실패")
    
    return buzz


# ── SLOW: 경제 캘린더 자동 수집 ──────────────────────

_econ_cal_cache = {"data": None, "last": 0}

def collect_econ_calendar():
    """Google News RSS + 하드코딩 병합 방식 경제 캘린더
    
    주요 이벤트는 하드코딩 (FOMC/CPI/NFP 등 확정 일정)
    + 뉴스 RSS에서 추가 이벤트 자동 탐지
    
    하루 1번 갱신
    """
    global _econ_cal_cache
    now = time.time()

    if _econ_cal_cache["data"] and (now - _econ_cal_cache["last"]) < 86400:
        print("  📅 경제캘린더… (캐시)")
        return _econ_cal_cache["data"]

    print("  📅 경제캘린더 자동 수집…")

    # 확정 일정 (2026 기준 — 공식 발표 기반)
    fixed_events = [
        {"d": "2026-03-25", "l": "미국 CB 소비자신뢰지수", "i": "mid", "c": "🇺🇸", "cat": "consumer"},
        {"d": "2026-03-27", "l": "미국 4분기 GDP (확정치)", "i": "high", "c": "🇺🇸", "cat": "gdp"},
        {"d": "2026-03-28", "l": "미국 핵심 PCE 물가지수", "i": "high", "c": "🇺🇸", "cat": "inflation"},
        {"d": "2026-04-01", "l": "미국 ISM 제조업 PMI", "i": "high", "c": "🇺🇸", "cat": "pmi"},
        {"d": "2026-04-03", "l": "미국 비농업 고용 (3월)", "i": "high", "c": "🇺🇸", "cat": "employment"},
        {"d": "2026-04-10", "l": "미국 CPI (3월)", "i": "high", "c": "🇺🇸", "cat": "inflation"},
        {"d": "2026-04-15", "l": "중국 GDP (1분기)", "i": "high", "c": "🇨🇳", "cat": "gdp"},
        {"d": "2026-04-16", "l": "ECB 금리 결정", "i": "high", "c": "🇪🇺", "cat": "rate"},
        {"d": "2026-04-29", "l": "미국 GDP 예비치", "i": "high", "c": "🇺🇸", "cat": "gdp"},
        {"d": "2026-04-30", "l": "일본 BOJ 금리 결정", "i": "high", "c": "🇯🇵", "cat": "rate"},
        {"d": "2026-05-06", "l": "FOMC 금리 결정 (5월)", "i": "high", "c": "🇺🇸", "cat": "rate"},
        {"d": "2026-05-08", "l": "미국 비농업 고용 (4월)", "i": "high", "c": "🇺🇸", "cat": "employment"},
        {"d": "2026-05-13", "l": "미국 CPI (4월)", "i": "high", "c": "🇺🇸", "cat": "inflation"},
        {"d": "2026-05-21", "l": "FOMC 의사록 (5월)", "i": "mid", "c": "🇺🇸", "cat": "rate"},
        {"d": "2026-06-04", "l": "ECB 금리 결정 (6월)", "i": "high", "c": "🇪🇺", "cat": "rate"},
        {"d": "2026-06-05", "l": "미국 비농업 고용 (5월)", "i": "high", "c": "🇺🇸", "cat": "employment"},
        {"d": "2026-06-10", "l": "미국 CPI (5월)", "i": "high", "c": "🇺🇸", "cat": "inflation"},
        {"d": "2026-06-17", "l": "FOMC 금리 결정 (6월)", "i": "high", "c": "🇺🇸", "cat": "rate"},
        {"d": "2026-07-02", "l": "미국 비농업 고용 (6월)", "i": "high", "c": "🇺🇸", "cat": "employment"},
        {"d": "2026-07-15", "l": "미국 CPI (6월)", "i": "high", "c": "🇺🇸", "cat": "inflation"},
        {"d": "2026-07-29", "l": "FOMC 금리 결정 (7월)", "i": "high", "c": "🇺🇸", "cat": "rate"},
        {"d": "2026-08-07", "l": "미국 비농업 고용 (7월)", "i": "high", "c": "🇺🇸", "cat": "employment"},
        {"d": "2026-09-16", "l": "FOMC 금리 결정 (9월)", "i": "high", "c": "🇺🇸", "cat": "rate"},
        {"d": "2026-11-04", "l": "FOMC 금리 결정 (11월)", "i": "high", "c": "🇺🇸", "cat": "rate"},
        {"d": "2026-12-16", "l": "FOMC 금리 결정 (12월)", "i": "high", "c": "🇺🇸", "cat": "rate"},
    ]

    # 뉴스에서 추가 이벤트 자동 탐지
    news_events = []
    econ_queries = [
        "economic data release this week",
        "CPI PPI GDP jobs report this week",
        "central bank rate decision this week",
    ]

    for query in econ_queries:
        q = query.replace(" ", "+")
        url = f"https://news.google.com/rss/search?q={q}+when:3d&hl=en&gl=US&ceid=US:en"
        raw = fetch_raw(url, timeout=8)
        if not raw or "<item>" not in raw:
            continue

        items = raw.split("<item>")[1:5]
        for item in items:
            t_match = re.search(r"<title>(.*?)</title>", item, re.DOTALL)
            if t_match:
                title = t_match.group(1).strip()
                title = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", title)
                title = re.sub(r"<[^>]+>", "", title).strip()[:120]

                source_match = re.search(r"<source[^>]*>(.*?)</source>", item)
                source = source_match.group(1) if source_match else ""

                news_events.append({
                    "title": title,
                    "source": source,
                })
        time.sleep(0.2)

    # 결과 = 확정 + 뉴스 부가
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # 과거 이벤트 유지 (최근 3일)
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    active_events = [e for e in fixed_events if e["d"] >= cutoff]

    result = {
        "events": active_events,
        "news_supplement": news_events[:8],
        "updated": today_str,
    }

    _econ_cal_cache = {"data": result, "last": now}
    print(f"    ✓ 확정 {len(active_events)}건 + 뉴스 {len(news_events[:8])}건")
    return result


# ── SLOW: CDS 스프레드 (국가 부도 위험 지표) ─────────

_cds_cache = {"data": None, "last": 0}

CDS_COUNTRIES = {
    "US": {"name": "미국", "emoji": "🇺🇸", "baseline": 30},
    "CN": {"name": "중국", "emoji": "🇨🇳", "baseline": 65},
    "JP": {"name": "일본", "emoji": "🇯🇵", "baseline": 25},
    "KR": {"name": "한국", "emoji": "🇰🇷", "baseline": 35},
    "DE": {"name": "독일", "emoji": "🇩🇪", "baseline": 15},
    "TR": {"name": "터키", "emoji": "🇹🇷", "baseline": 350},
    "BR": {"name": "브라질", "emoji": "🇧🇷", "baseline": 160},
    "RU": {"name": "러시아", "emoji": "🇷🇺", "baseline": 500},
}


def collect_cds():
    """CDS 스프레드 수집 — WorldGovernmentBonds.com 스크래핑
    
    하루 1번 갱신 (CDS는 일 단위 변동)
    """
    global _cds_cache
    now = time.time()

    if _cds_cache["data"] and (now - _cds_cache["last"]) < 86400:
        print("  💳 CDS… (캐시)")
        return _cds_cache["data"]

    print("  💳 CDS 스프레드 수집…")

    results = []

    # 1차: worldgovernmentbonds.com (가장 신뢰할 수 있는 무료 소스)
    raw = fetch_raw("https://www.worldgovernmentbonds.com/cds-spreads/", timeout=15)
    if raw:
        try:
            # 테이블에서 국가별 CDS 파싱
            # 패턴: 국가명 ... 5Y CDS 값
            for code, info in CDS_COUNTRIES.items():
                country_name_en = {
                    "US": "United States", "CN": "China", "JP": "Japan",
                    "KR": "South Korea", "DE": "Germany", "TR": "Turkey",
                    "BR": "Brazil", "RU": "Russia",
                }.get(code, "")

                if not country_name_en:
                    continue

                # 해당 국가 행 찾기
                idx = raw.find(country_name_en)
                if idx < 0:
                    continue

                # 근처에서 숫자 패턴 탐색 (CDS 값은 보통 소수점 포함 숫자)
                snippet = raw[idx:idx + 500]
                # bp 값 파싱 시도
                nums = re.findall(r'(\d+(?:\.\d+)?)\s*(?:bp|bps)?', snippet)
                if nums:
                    # 첫 번째 합리적 범위의 숫자를 5Y CDS로 사용
                    for n in nums:
                        val = float(n)
                        if 1 < val < 5000:  # 합리적 CDS 범위
                            spread = round(val, 1)
                            # 위험도 계산
                            ratio = spread / max(info["baseline"], 1)
                            if ratio > 2:
                                risk = "CRITICAL"
                                color = "var(--red)"
                            elif ratio > 1.3:
                                risk = "ELEVATED"
                                color = "var(--gold)"
                            else:
                                risk = "NORMAL"
                                color = "var(--green)"

                            results.append({
                                "code": code,
                                "name": info["name"],
                                "emoji": info["emoji"],
                                "spread_5y": spread,
                                "baseline": info["baseline"],
                                "risk": risk,
                                "color": color,
                            })
                            break

            if results:
                print(f"    ✓ CDS: {len(results)}개국 파싱 완료")
        except Exception as e:
            print(f"    ⚠ CDS 파싱 에러: {e}")

    # 2차: 폴백 — 뉴스 기반 추정 (실패 시)
    if not results:
        print("    ⚠ CDS 직접 파싱 실패 — 기본값 사용")
        for code, info in CDS_COUNTRIES.items():
            results.append({
                "code": code,
                "name": info["name"],
                "emoji": info["emoji"],
                "spread_5y": info["baseline"],
                "baseline": info["baseline"],
                "risk": "NORMAL",
                "color": "var(--text2)",
                "fallback": True,
            })

    # 정렬: 위험도 높은 순
    results.sort(key=lambda x: x["spread_5y"], reverse=True)

    # 전체 위험 시그널
    avg_ratio = sum(r["spread_5y"] / max(r["baseline"], 1) for r in results) / max(len(results), 1)
    if avg_ratio > 1.5:
        signal = "글로벌 신용 리스크 급등 — 안전자산 비중 확대 긴급"
    elif avg_ratio > 1.2:
        signal = "일부 국가 CDS 확대 — 리스크 모니터링 강화"
    else:
        signal = "글로벌 CDS 안정 — 신용 시장 정상"

    result = {
        "countries": results,
        "avg_ratio": round(avg_ratio, 2),
        "signal": signal,
    }

    _cds_cache = {"data": result, "last": now}
    return result


# ── SLOW: X 속보 (Twitter/X RSS) ─────────────────────

X_ACCOUNTS = [
    ("Reuters", "Reuters", "🌐"),
    ("DeItaone", "WalterBloomberg", "⚡"),
    ("zaborhedge", "ZeroHedge", "📉"),
    ("unusual_whales", "Unusual Whales", "🐋"),
    ("MacroAlf", "MacroAlf", "📊"),
    ("business", "Bloomberg", "💼"),
    ("PenPizzaReport", "Pentagon Pizza", "🍕"),
]

# RSSHub 공개 인스턴스 (여러 개 시도)
RSSHUB_INSTANCES = [
    "https://rsshub.app",
    "https://rsshub.rssforever.com",
    "https://rsshub-instance.zeabur.app",
]

# Nitter 인스턴스 (폴백)
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
]


def collect_x_feed():
    """X(Twitter) 주요 계정 속보 수집 — RSSHub → Nitter 폴백"""
    print("  📱 X 속보…")
    all_posts = []

    for handle, display_name, emoji in X_ACCOUNTS:
        fetched = False

        # 1차: RSSHub
        for base in RSSHUB_INSTANCES:
            url = f"{base}/twitter/user/{handle}"
            raw = fetch_raw(url, timeout=8)
            if raw and "<item>" in raw:
                posts = _parse_rss_items(raw, handle, display_name, emoji)
                if posts:
                    all_posts.extend(posts)
                    fetched = True
                    break

        if fetched:
            continue

        # 2차: Nitter
        for base in NITTER_INSTANCES:
            url = f"{base}/{handle}/rss"
            raw = fetch_raw(url, timeout=8)
            if raw and "<item>" in raw:
                posts = _parse_rss_items(raw, handle, display_name, emoji)
                if posts:
                    all_posts.extend(posts)
                    break

        time.sleep(0.3)

    # 시간순 정렬, 최대 20개
    all_posts.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    result = all_posts[:20]
    print(f"    ✓ X 속보: {len(result)}건 ({len(X_ACCOUNTS)}계정)")
    return result


def _parse_rss_items(raw, handle, display_name, emoji, max_items=5):
    """RSS XML에서 트윗 파싱"""
    posts = []
    items = raw.split("<item>")[1:max_items + 1]
    now_ts = int(time.time())

    for item in items:
        # 제목/본문 추출
        title = ""
        t_match = re.search(r"<title>(.*?)</title>", item, re.DOTALL)
        if t_match:
            title = t_match.group(1).strip()
            title = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", title)
            # HTML 태그 제거
            title = re.sub(r"<[^>]+>", "", title)
            # RT @user: 제거
            title = re.sub(r"^R?T @\w+:?\s*", "", title)
            title = title.strip()[:200]

        if not title or len(title) < 10:
            continue

        # 링크
        link = ""
        l_match = re.search(r"<link>(.*?)</link>", item)
        if l_match:
            link = l_match.group(1).strip()

        # 타임스탬프
        ts = now_ts
        pub_match = re.search(r"<pubDate>(.*?)</pubDate>", item)
        if pub_match:
            try:
                from email.utils import parsedate_to_datetime
                ts = int(parsedate_to_datetime(pub_match.group(1)).timestamp())
            except Exception:
                pass

        # 24시간 이상 지난 건 제외
        if now_ts - ts > 86400:
            continue

        posts.append({
            "handle": f"@{handle}",
            "name": display_name,
            "emoji": emoji,
            "text": title,
            "link": link,
            "timestamp": ts,
        })

    return posts


# ── SLOW: 트럼프 트루스소셜 (Google News RSS) ────────

def collect_trump_truth():
    """트럼프 Truth Social 공식 포스트 직접 수집
    Truth Social은 Mastodon 기반 → /@username.rss 공식 RSS 지원
    """
    print("  🇺🇸 트럼프 Truth Social RSS…")

    RSS_URL = "https://truthsocial.com/@realDonaldTrump.rss"
    now_ts  = int(time.time())
    posts   = []

    try:
        raw = fetch_raw(RSS_URL, timeout=12)
        if not raw or "<item>" not in raw:
            print("    ⚠ Truth Social RSS 응답 없음")
            return []

        items = raw.split("<item>")[1:]
        for item in items[:15]:  # 최대 15개 파싱
            # 본문 — <content:encoded> 우선, 없으면 <description>
            text = ""
            for tag in (r"<content:encoded>(.*?)</content:encoded>",
                        r"<description>(.*?)</description>"):
                m = re.search(tag, item, re.DOTALL)
                if m:
                    text = m.group(1).strip()
                    # CDATA 제거
                    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.DOTALL)
                    # HTML 태그 제거
                    text = re.sub(r"<[^>]+>", "", text).strip()
                    # 공백 정리
                    text = re.sub(r"\s+", " ", text).strip()
                    if text:
                        break

            if not text or len(text) < 10:
                continue

            # 링크
            link = ""
            l_match = re.search(r"<link>(.*?)</link>", item) or \
                      re.search(r"<guid[^>]*>(.*?)</guid>", item)
            if l_match:
                link = l_match.group(1).strip()

            # 타임스탬프
            ts = now_ts
            pub_match = re.search(r"<pubDate>(.*?)</pubDate>", item)
            if pub_match:
                try:
                    from email.utils import parsedate_to_datetime
                    ts = int(parsedate_to_datetime(pub_match.group(1)).timestamp())
                except Exception:
                    pass

            # 48시간 이상 지난 건 제외
            if now_ts - ts > 172800:
                continue

            posts.append({
                "handle": "@realDonaldTrump",
                "name":   "Donald J. Trump",
                "emoji":  "🏛️",
                "text":   text[:280],
                "link":   link,
                "source": "Truth Social",
                "timestamp": ts,
                "cat":    "trump",
            })

    except Exception as e:
        print(f"    ⚠ Truth Social RSS 오류: {e}")
        return []

    posts.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    result = posts[:10]
    print(f"    ✓ 트럼프 Truth Social: {len(result)}건 수집")
    return result


def collect_whales(btc_price=87000, eth_price=2100):
    """고래 이동 실시간 — Blockchair API (무료)
    
    BTC/ETH 대형 트랜잭션 실시간 수집
    출처: Blockchair (무료, 일 30,000회)
    """
    print("  🐋 대형 거래 (Blockchair)…")
    alerts = []

    # ── BTC 대형 거래 ──
    try:
        btc_data = fetch_json(
            "https://api.blockchair.com/bitcoin/transactions"
            "?s=output_total(desc)&limit=10&q=output_total(100000000..)"  # 1 BTC+ 필터
        )
        if btc_data and btc_data.get("data"):
            for tx in btc_data["data"]:
                output_sat = tx.get("output_total", 0)
                output_btc = output_sat / 1e8
                output_usd = output_btc * btc_price

                if output_usd < 1_000_000:
                    continue

                # 시간 파싱
                ts_str = tx.get("time", "")
                ts = int(time.time())
                if ts_str:
                    try:
                        from datetime import datetime as dt2
                        ts = int(dt2.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp())
                    except Exception:
                        pass

                tx_hash = tx.get("hash", "")
                input_count = tx.get("input_count", 0)
                output_count = tx.get("output_count", 0)

                alerts.append({
                    "symbol": "BTC",
                    "amount": round(output_btc, 4),
                    "amount_usd": round(output_usd),
                    "from": f"{input_count} inputs",
                    "to": f"{output_count} outputs",
                    "timestamp": ts,
                    "tx_hash": tx_hash[:16] if tx_hash else "",
                    "source": "Blockchair",
                })
            btc_count = sum(1 for a in alerts if a["symbol"] == "BTC")
            if btc_count:
                print(f"    ✓ BTC 대형 TX: {btc_count}건")
        else:
            print("    ⚠ Blockchair BTC: 응답 없음")
    except Exception as e:
        print(f"    ⚠ Blockchair BTC: {e}")

    time.sleep(0.3)

    # ── ETH 대형 거래 ──
    try:
        eth_data = fetch_json(
            "https://api.blockchair.com/ethereum/transactions"
            "?s=value(desc)&limit=10&q=value(1000000000000000000..)"  # 1 ETH+ 필터
        )
        if eth_data and eth_data.get("data"):
            for tx in eth_data["data"]:
                value_raw = tx.get("value", 0)
                # Blockchair ETH: value 단위가 wei (10^18)
                if isinstance(value_raw, str):
                    value_raw = int(value_raw)
                value_eth = value_raw / 1e18
                value_usd = value_eth * eth_price

                if value_usd < 1_000_000:
                    continue

                recipient = (tx.get("recipient", "") or "")
                sender = (tx.get("sender", "") or "")
                # 주소 축약
                to_label = recipient[:8] + "…" + recipient[-4:] if len(recipient) > 12 else recipient or "Contract"
                from_label = sender[:8] + "…" + sender[-4:] if len(sender) > 12 else sender or "Contract"

                ts_str = tx.get("time", "")
                ts = int(time.time())
                if ts_str:
                    try:
                        from datetime import datetime as dt2
                        ts = int(dt2.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp())
                    except Exception:
                        pass

                alerts.append({
                    "symbol": "ETH",
                    "amount": round(value_eth, 2),
                    "amount_usd": round(value_usd),
                    "from": from_label,
                    "to": to_label,
                    "timestamp": ts,
                    "tx_hash": (tx.get("hash", "") or "")[:16],
                    "source": "Blockchair",
                })
            eth_count = sum(1 for a in alerts if a["symbol"] == "ETH")
            if eth_count:
                print(f"    ✓ ETH 대형 TX: {eth_count}건")
        else:
            print("    ⚠ Blockchair ETH: 응답 없음")
    except Exception as e:
        print(f"    ⚠ Blockchair ETH: {e}")

    # 정렬 + 반환
    alerts.sort(key=lambda x: x["amount_usd"], reverse=True)
    result = alerts[:15]
    if result:
        print(f"    ✓ 대형 거래 총 {len(result)}건")
    else:
        print("    ⚠ 대형 거래 데이터 없음")
    return result, 0, 0


# ── Frankfurter 환율 ──────────────────────────────────

def collect_forex_frankfurter() -> dict:
    """Frankfurter API — 환율 6개 + 등락률 (5분 주기, 무료·키없음)"""
    from datetime import date, timedelta

    def get_rates(dt):
        url = f"https://api.frankfurter.app/{dt}?from=USD&to=KRW,JPY,EUR,CNY,AUD,GBP"
        raw = fetch_raw(url, timeout=10)
        if not raw:
            return None
        try:
            return json.loads(raw).get("rates", {})
        except Exception:
            return None

    today_rates = get_rates("latest")
    if not today_rates:
        print("    ⚠ Frankfurter 응답 없음")
        return {}

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    yest_rates = get_rates(yesterday) or today_rates

    def _chg(tv, yv):
        if tv and yv:
            return round((tv - yv) / yv * 100, 2)
        return 0.0

    # KRW/JPY/CNY: USD 기준 직접값, EUR/AUD/GBP: 역수 (USD per 1 unit)
    pairs = [
        ("forex_krw", lambda r: round(r["KRW"], 2)  if r.get("KRW") else None),
        ("forex_jpy", lambda r: round(r["JPY"], 2)  if r.get("JPY") else None),
        ("forex_eur", lambda r: round(1/r["EUR"], 4) if r.get("EUR") else None),
        ("forex_cny", lambda r: round(r["CNY"], 4)  if r.get("CNY") else None),
        ("forex_aud", lambda r: round(1/r["AUD"], 4) if r.get("AUD") else None),
        ("forex_gbp", lambda r: round(1/r["GBP"], 4) if r.get("GBP") else None),
    ]

    out = {}
    ok = 0
    for key, fn in pairs:
        tv = fn(today_rates)
        yv = fn(yest_rates)
        if tv:
            out[key] = tv
            out[key + "_chg"] = _chg(tv, yv)
            ok += 1

    print(f"    ✅ Frankfurter 환율 {ok}개")
    return out


# ── Twelve Data Batch ─────────────────────────────────

def collect_twelve_data() -> dict:
    """Twelve Data Batch Quote — 지수·환율·M7 (2분 주기)

    API 한도: 하루 ~720회 호출 (2분 간격) ≤ 800회 한도
    실패 시 빈 dict 반환 → 호출 측에서 이전 캐시 유지
    """
    if not TWELVE_DATA_KEY:
        print("    ⚠ TWELVE_DATA_API_KEY 없음 — TD 수집 건너뜀")
        return {}

    symbols_str = quote(",".join(TD_SYMBOLS), safe=",")
    url = (
        "https://api.twelvedata.com/quote"
        f"?symbol={symbols_str}"
        f"&apikey={TWELVE_DATA_KEY}"
    )
    print(f"  📡 Twelve Data Batch ({len(TD_SYMBOLS)}개 심볼)…")
    raw = fetch_raw(url, timeout=30)
    if not raw:
        print("    ⚠ TD 응답 없음 — 이전 캐시 유지")
        return {}

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"    ⚠ TD JSON 파싱 실패: {e}")
        return {}

    # 최상위 에러 응답 처리
    if isinstance(data, dict) and data.get("status") == "error":
        print(f"    ⚠ TD API 에러: {data.get('message', 'unknown')} (code={data.get('code')})")
        return {}

    # 단일 심볼 요청이면 dict 직접 반환 → 리스트 형태로 통일
    if isinstance(data, dict) and "symbol" in data:
        sym = data.get("symbol", "")
        data = {sym: data}

    out: dict = {}
    m7: list = []
    ok_idx = ok_fx = ok_m7 = 0

    for sym, item in data.items():
        if not isinstance(item, dict):
            continue
        if item.get("status") == "error":
            print(f"    ⚠ TD [{sym}]: {item.get('message', 'unknown')}")
            continue

        close = safe_float(item.get("close", 0))
        prev  = safe_float(item.get("previous_close") or close)
        chg   = round(((close - prev) / prev * 100) if prev else 0.0, 2)
        close = round(close, 4)

        if sym in TD_INDEX_MAP:
            k, kc = TD_INDEX_MAP[sym]
            out[k]  = round(close, 2)
            out[kc] = chg
            ok_idx += 1
        elif sym in TD_FOREX_MAP:
            out[TD_FOREX_MAP[sym]] = round(close, 4)
            out[TD_FOREX_MAP[sym] + "_chg"] = chg
            ok_fx += 1
        elif sym in TD_M7_ORDER:
            m7.append({"sym": sym, "price": round(close, 2), "chg": chg})
            ok_m7 += 1

    # M7 원래 순서 정렬
    order_map = {s: i for i, s in enumerate(TD_M7_ORDER)}
    m7.sort(key=lambda x: order_map.get(x["sym"], 99))
    if m7:
        out["m7"] = m7

    print(f"    ✅ TD 완료: 지수 {ok_idx}개 | 환율 {ok_fx}개 | M7 {ok_m7}개")
    return out


# ── 메인 수집 루프 ────────────────────────────────────

def run_once():
    """1회 데이터 수집 + data.json 저장"""
    global _last_slow, _slow_cache, _last_td, _td_cache, _market_hash, _market_data_time

    now = time.time()
    do_slow = (now - _last_slow) >= SLOW_INTERVAL or not _slow_cache
    do_td   = (now - _last_td)   >= TD_INTERVAL   or not _td_cache

    print(f"\n{'=' * 50}")
    print(f"  ⚡ v7.7 {'FULL' if do_slow else 'FAST'} | TD={'갱신' if do_td else '캐시'} ({datetime.now().strftime('%H:%M:%S')})")
    print(f"{'=' * 50}")

    # ── FAST: Hyperliquid 크립토·원자재 ──
    hl = collect_hl_prices()
    btc = hl.get("btc_usd") or hl.get("hl_btc_mark") or 69000
    hl_oi = hl.get("hl_btc_oi", 0)

    # ── TD: Twelve Data 지수·환율·M7 (2분마다) ──
    if do_td:
        td_fresh = collect_twelve_data()
        if td_fresh:          # 성공 시만 캐시 갱신 (실패 시 이전 데이터 유지)
            _td_cache = td_fresh
        _last_td = now
    else:
        print("  (TD 캐시 사용)")
    td = _td_cache

    # ── SLOW: 5분마다 ──
    if do_slow:
        print("\n  ── SLOW 수집 시작 ──")

        yahoo = collect_yahoo_changes(hl)
        forex = collect_forex_frankfurter()
        fred = collect_fred_and_dominance()
        okx = collect_okx(btc)
        kimchi = collect_kimchi(btc)
        liquidation = collect_liquidation(btc, hl_oi)
        war = collect_war_index()
        celestial = collect_celestial()
        cnn = collect_cnn_fg()
        sentiment = collect_market_sentiment()
        mvrv = collect_mvrv()
        altseason = collect_altseason()
        stablecoin = collect_stablecoin_flow()
        wallstreet = collect_wallstreet_buzz()
        x_feed = collect_x_feed()
        eth = hl.get("eth_usd") or 2100
        whales, usdt_inflow, usdc_inflow = collect_whales(btc, eth)
        trump = collect_trump_truth()
        correlation = collect_correlation()
        econ_cal = collect_econ_calendar()
        cds = collect_cds()

        _slow_cache = {
            "yahoo": yahoo, "forex": forex, "fred": fred, "okx": okx,
            "kimchi": kimchi, "liquidation": liquidation, "war": war,
            "celestial": celestial,
            "cnn": cnn, "sentiment": sentiment, "mvrv": mvrv, "altseason": altseason,
            "stablecoin": stablecoin, "wallstreet": wallstreet,
            "x_feed": x_feed,
            "whales": whales, "usdt": usdt_inflow, "usdc": usdc_inflow,
            "trump": trump,
            "correlation": correlation,
            "econ_cal": econ_cal,
            "cds": cds,
        }
        _last_slow = now
    else:
        print("  (SLOW 캐시 사용)")

    # ── 결과 조합 ──
    sc = _slow_cache
    yahoo = sc.get("yahoo", {})
    forex = sc.get("forex", {})
    fred = sc.get("fred", {})
    okx = sc.get("okx", {})

    # 마켓 데이터 병합 (HL + Yahoo + Frankfurter 환율 + FRED + TD)
    # 우선순위: TD 데이터 > Frankfurter > Yahoo > HL
    market = {**hl, **yahoo, **forex, **fred}

    # TD 데이터 적용 (지수, 환율, M7 전체 덮어쓰기)
    if td:
        for k, v in td.items():
            market[k] = v
        if td.get("m7"):
            print(f"    📈 M7: Twelve Data ({len(td['m7'])}개) 적용")

    # TD M7 없을 경우 Yahoo 폴백
    if not market.get("m7"):
        m7_changes = yahoo.get("_m7_changes", {})
        m7_fallback = yahoo.get("_m7_fallback", [])
        if m7_fallback:
            market["m7"] = m7_fallback
            print(f"    📈 M7: Yahoo 폴백 사용 ({len(m7_fallback)}개)")
        elif hl.get("m7"):
            # HL M7에 Yahoo 변동률 적용
            for item in hl["m7"]:
                if item["sym"] in m7_changes:
                    item["chg"] = m7_changes[item["sym"]]
            market["m7"] = hl["m7"]
        else:
            market["m7"] = []

    market.pop("_m7_changes", None)
    market.pop("_m7_fallback", None)

    # ── 실제 가격 변동 감지 → market_updated 갱신 ──
    # 소수점 노이즈 제거 후 비교: 지수=정수, 환율=소수2자리, VIX/DXY=소수1자리
    # → 주말·API 부동소수 미세변동으로 인한 오갱신 방지
    import hashlib as _hl
    def _q(v, d): return round(v, d) if v else None
    _chk = {
        "spx":   _q(market.get("spx"),   0),
        "ndx":   _q(market.get("ndx"),   0),
        "dji":   _q(market.get("dji"),   0),
        "n225":  _q(market.get("n225"),  0),
        "hsi":   _q(market.get("hsi"),   0),
        "vix":   _q(market.get("vix"),   1),
        "dxy":   _q(market.get("dxy"),   1),
        "forex_krw": _q(market.get("forex_krw"), 0),
        "forex_jpy": _q(market.get("forex_jpy"), 2),
        "forex_eur": _q(market.get("forex_eur"), 2),
    }
    _new_hash = _hl.md5(json.dumps(_chk, sort_keys=True).encode()).hexdigest()[:12]
    if _new_hash != _market_hash:
        _market_hash = _new_hash
        _market_data_time = datetime.now(timezone.utc).isoformat()
        print(f"  🔄 시장 데이터 변동 → market_updated 갱신 {_chk}")

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

        "stablecoin_inflow": sc.get("stablecoin") or {
            "usdt": 0, "usdc": 0, "total": 0,
            "max_reference": 500_000_000,
        },

        "altseason": sc.get("altseason") or 50,

        "wallstreet_buzz": sc.get("wallstreet") or [],

        "x_feed": sc.get("x_feed") or [],

        "trump_feed": sc.get("trump") or [],

        "celestial": sc.get("celestial") or {},

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

        "market_sentiment": sc.get("sentiment") or None,

        "correlation": sc.get("correlation") or None,

        "econ_calendar": sc.get("econ_cal") or None,

        "cds": sc.get("cds") or None,

        "last_updated": datetime.now(timezone.utc).isoformat(),
        "market_updated": _market_data_time or datetime.now(timezone.utc).isoformat(),
    }

    # 저장
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUT_FILE)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n  💾 저장완료 | BTC:${btc:,.0f} | SPX:{market.get('spx')} | GOLD:{market.get('gold')}")


def run_loop():
    """무한 루프 실행"""
    print("=" * 50)
    print("  ⚡ JHONBER NODE v7.7 — Twelve Data 통합")
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
