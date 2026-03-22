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

    # CVD (Taker Volume) — 24h 기준 순매수/순매도
    # OKX taker-volume 응답: [timestamp, buyVol(USD), sellVol(USD)]
    data = fetch_json("https://www.okx.com/api/v5/rubik/stat/taker-volume?ccy=BTC&instType=CONTRACTS&period=1D")
    if data and data.get("data"):
        try:
            row = data["data"][0]
            total_buy = safe_float(row[1])   # USD
            total_sell = safe_float(row[2])   # USD
            net = total_buy - total_sell      # USD 순매수

            # 체급별 추산 (비율 기반)
            whale = net * 0.45
            shark = net * 0.25
            fish = net * -0.10
            shrimp = net * -0.10
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

            out["cvd"] = {
                "total": net_usd,
                "whale": round(whale),
                "shark": round(shark),
                "fish": round(fish),
                "shrimp": round(shrimp),
                "buy_volume": round(total_buy),
                "sell_volume": round(total_sell),
                "btc_price": btc_price,
                "source": "OKX 24h",
                "analysis": analysis,
            }
            print(f"    ✓ CVD: ${net_usd / 1e6:.1f}M ({'매수' if net > 0 else '매도'})")
        except (IndexError, TypeError) as e:
            print(f"    ⚠ CVD 파싱 에러: {e}")

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
            planet_data(ephem.Mars(), "♅", "URANUS · 천왕성"),  # ephem has no Uranus, use placeholder
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
    """CNN Fear & Greed Index — 다중 폴백 전략
    
    1차: production.dataviz.cnn.io/index/fearandgreed/graphdata (기본)
    2차: 같은 URL + 날짜 파라미터 (봇 차단 우회)
    3차: /current 엔드포인트 시도
    """
    print("  😱 CNN F&G…")

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
                return {
                    "score": score,
                    "rating": rating,
                    "previous_close": round(fg.get("previous_close", 0)),
                    "one_week_ago": round(fg.get("previous_1_week", 0)),
                    "one_month_ago": round(fg.get("previous_1_month", 0)),
                }
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
            return {
                "score": score,
                "rating": rating,
                "previous_close": round(hist.get("1w", 0)),
                "one_week_ago": round(hist.get("1w", 0)),
                "one_month_ago": round(hist.get("1m", 0)),
            }
    except ImportError:
        print("    ⚠ fear-greed 미설치 — pip install fear-greed 필요")
    except Exception as e:
        print(f"    ⚠ fear-greed 패키지 에러: {e}")

    print("    ❌ CNN F&G 전체 실패")
    return None


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


def collect_whales():
    """고래 알림 수집 — 3단 폴백
    
    1차: Whale Alert API (키 있으면)
    2차: Whale Alert Twitter RSS (nitter 프록시)
    3차: 데모 데이터
    """

    # ── 1차: Whale Alert API (키 있으면) ──
    if WHALE_KEY and WHALE_KEY != "YOUR_KEY":
        since = int(time.time()) - 3600
        data = fetch_json(
            f"https://api.whale-alert.io/v1/transactions?"
            f"api_key={WHALE_KEY}&min_value=500000&start={since}"
        )
        txs = data.get("transactions", []) if data else []
        if txs:
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
                    "symbol": sym, "amount": tx.get("amount", 0),
                    "amount_usd": usd, "from": tx.get("from", "?"),
                    "to": tx.get("to", "?"), "timestamp": tx.get("timestamp", 0),
                })
            alerts.sort(key=lambda x: x["amount_usd"], reverse=True)
            print(f"    ✓ Whale Alert API: {len(alerts)}건")
            return alerts[:15], usdt_to_exchange, usdc_to_exchange

    # ── 2차: Whale Alert Twitter RSS 파싱 ──
    print("  🐋 Whale RSS 시도…")
    rss_urls = [
        "https://nitter.net/whale_alert/rss",
        "https://nitter.privacydev.net/whale_alert/rss",
        "https://nitter.poast.org/whale_alert/rss",
    ]
    
    for rss_url in rss_urls:
        raw = fetch_raw(rss_url, timeout=10)
        if not raw or "<item>" not in raw:
            continue
        
        try:
            alerts = []
            usdt_ex, usdc_ex = 0, 0
            now_ts = int(time.time())
            
            # XML 간이 파싱 (feedparser 없이)
            items = raw.split("<item>")[1:15]  # 최대 15개
            for item in items:
                title = ""
                t_match = re.search(r"<title>(.*?)</title>", item, re.DOTALL)
                if t_match:
                    title = t_match.group(1).strip()
                    # CDATA 제거
                    title = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", title)
                
                if not title:
                    continue
                
                # 트윗 파싱: "🚨 1,000 #BTC (69,000,000 USD) transferred from unknown wallet to #Binance"
                amount_match = re.search(r"([\d,]+)\s*#?(\w+)\s*\(([\d,]+)\s*USD\)", title)
                if not amount_match:
                    continue
                
                amount = int(amount_match.group(1).replace(",", ""))
                symbol = amount_match.group(2).upper()
                amount_usd = int(amount_match.group(3).replace(",", ""))
                
                if amount_usd < 500000:
                    continue
                
                # from/to 파싱
                from_addr = "Unknown"
                to_addr = "Unknown"
                from_match = re.search(r"from\s+(?:#?(\w+[\s\w]*))", title, re.I)
                to_match = re.search(r"to\s+(?:#?(\w+[\s\w]*))", title, re.I)
                if from_match:
                    from_addr = from_match.group(1).strip()[:20]
                if to_match:
                    to_addr = to_match.group(1).strip()[:20]
                
                # 타임스탬프
                pub_match = re.search(r"<pubDate>(.*?)</pubDate>", item)
                ts = now_ts
                if pub_match:
                    try:
                        from email.utils import parsedate_to_datetime
                        ts = int(parsedate_to_datetime(pub_match.group(1)).timestamp())
                    except Exception:
                        pass
                
                alert = {
                    "symbol": symbol, "amount": amount,
                    "amount_usd": amount_usd,
                    "from": from_addr, "to": to_addr,
                    "timestamp": ts,
                }
                
                # 스테이블코인 거래소 유입 추적
                to_lower = to_addr.lower()
                is_exchange = any(ex in to_lower for ex in ["binance", "coinbase", "kraken", "okx", "bybit", "huobi", "bitfinex", "upbit"])
                if is_exchange:
                    if symbol == "USDT":
                        usdt_ex += amount_usd
                    elif symbol == "USDC":
                        usdc_ex += amount_usd
                
                alerts.append(alert)
            
            if alerts:
                alerts.sort(key=lambda x: x["amount_usd"], reverse=True)
                print(f"    ✓ Whale RSS: {len(alerts)}건 파싱")
                return alerts[:15], usdt_ex, usdc_ex
        except Exception as e:
            print(f"    ⚠ RSS 파싱 에러: {e}")
            continue

    # ── 3차: 데모 데이터 (최후 폴백) ──
    print("    ⚠ Whale 전체 실패 — 데모 데이터")
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


# ── 메인 수집 루프 ────────────────────────────────────

def run_once():
    """1회 데이터 수집 + data.json 저장"""
    global _last_slow, _slow_cache

    now = time.time()
    do_slow = (now - _last_slow) >= SLOW_INTERVAL or not _slow_cache

    print(f"\n{'=' * 50}")
    print(f"  ⚡ v6.1 {'FULL' if do_slow else 'FAST'} ({datetime.now().strftime('%H:%M:%S')})")
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
        celestial = collect_celestial()
        cnn = collect_cnn_fg()
        mvrv = collect_mvrv()
        altseason = collect_altseason()
        stablecoin = collect_stablecoin_flow()
        wallstreet = collect_wallstreet_buzz()
        x_feed = collect_x_feed()
        whales, usdt_inflow, usdc_inflow = collect_whales()

        _slow_cache = {
            "yahoo": yahoo, "fred": fred, "okx": okx,
            "kimchi": kimchi, "liquidation": liquidation, "war": war,
            "celestial": celestial,
            "cnn": cnn, "mvrv": mvrv, "altseason": altseason,
            "stablecoin": stablecoin, "wallstreet": wallstreet,
            "x_feed": x_feed,
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

    # M7 변동률 적용 + Yahoo 폴백
    m7_changes = yahoo.get("_m7_changes", {})
    m7_fallback = yahoo.get("_m7_fallback", [])

    if market.get("m7") and len(market["m7"]) > 0:
        # HL에서 M7 가져온 경우: Yahoo 변동률만 적용
        for item in market["m7"]:
            if item["sym"] in m7_changes:
                item["chg"] = m7_changes[item["sym"]]
    elif m7_fallback:
        # HL에서 M7 못 가져온 경우: Yahoo 가격+변동률 전체 사용
        market["m7"] = m7_fallback
        print(f"    📈 M7: Yahoo 폴백 사용 ({len(m7_fallback)}개)")
    else:
        market["m7"] = []

    market.pop("_m7_changes", None)
    market.pop("_m7_fallback", None)

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
    print("  ⚡ JHONBER NODE v6.1")
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
