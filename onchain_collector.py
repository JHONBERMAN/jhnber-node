#!/usr/bin/env python3
"""
X-INTELLIGENCE : JHONBER — NODE
온체인 데이터 수집 스크립트

Whale Alert API + CryptoQuant 대안으로 거래소 스테이블코인 유입량을 수집하여
data.json 파일로 저장합니다. HTML 대시보드가 이 파일을 fetch()로 읽어 표시합니다.

사용법:
    1) Whale Alert API 키 발급: https://whale-alert.io/signup (무료 플랜)
    2) 아래 WHALE_ALERT_API_KEY에 키 입력
    3) python onchain_collector.py 실행 (또는 cron/스케줄러로 1분마다 실행)
    4) data.json이 같은 디렉토리에 생성됨 → HTML에서 자동 연동

무료 플랜 제한:
    - $500,000 이상 트랜잭션만 조회 가능
    - 분당 10회 요청 제한
    - 최근 1시간 데이터만 조회 가능
"""

import json
import time
import os
import sys
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# ═══════════════════════════════════════════
# 설정
# ═══════════════════════════════════════════
WHALE_ALERT_API_KEY = "YOUR_WHALE_ALERT_API_KEY"  # ← 여기에 키 입력
OUTPUT_FILE = "data.json"  # HTML과 같은 디렉토리에 저장
MIN_USD_VALUE = 500000  # $500K 이상 트랜잭션 (무료 플랜 최소)
POLL_INTERVAL = 60  # 60초마다 폴링

# 주요 거래소 목록
EXCHANGES = {
    "binance", "coinbase", "kraken", "bitfinex", "huobi",
    "okex", "bybit", "kucoin", "gate.io", "crypto.com",
    "upbit", "bithumb", "gemini", "bitstamp"
}

# ═══════════════════════════════════════════
# Whale Alert API 호출
# ═══════════════════════════════════════════
def fetch_whale_alerts():
    """최근 1시간 내 대규모 트랜잭션을 가져옵니다."""
    if WHALE_ALERT_API_KEY == "YOUR_WHALE_ALERT_API_KEY":
        print("⚠  Whale Alert API 키가 설정되지 않았습니다. 데모 데이터를 생성합니다.")
        return generate_demo_data()

    start_time = int(time.time()) - 3600  # 1시간 전
    url = (
        f"https://api.whale-alert.io/v1/transactions"
        f"?api_key={WHALE_ALERT_API_KEY}"
        f"&min_value={MIN_USD_VALUE}"
        f"&start={start_time}"
        f"&cursor=0"
    )

    try:
        req = Request(url, headers={"User-Agent": "X-Intelligence/1.0"})
        with urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())

        if data.get("result") != "success":
            print(f"⚠  API 오류: {data.get('message', 'unknown')}")
            return generate_demo_data()

        transactions = data.get("transactions", [])
        print(f"✅  {len(transactions)}건의 고래 트랜잭션을 가져왔습니다.")
        return transactions

    except HTTPError as e:
        print(f"⚠  HTTP 오류 {e.code}: {e.reason}")
        return generate_demo_data()
    except URLError as e:
        print(f"⚠  네트워크 오류: {e.reason}")
        return generate_demo_data()
    except Exception as e:
        print(f"⚠  알 수 없는 오류: {e}")
        return generate_demo_data()


def generate_demo_data():
    """API 키가 없거나 오류 시 데모 데이터 생성"""
    now = int(time.time())
    return [
        {"symbol": "btc", "amount": 2500, "amount_usd": 325000000,
         "from": {"owner": "unknown", "owner_type": "unknown"},
         "to": {"owner": "binance", "owner_type": "exchange"},
         "timestamp": now - 120},
        {"symbol": "eth", "amount": 15000, "amount_usd": 52500000,
         "from": {"owner": "unknown", "owner_type": "unknown"},
         "to": {"owner": "coinbase", "owner_type": "exchange"},
         "timestamp": now - 300},
        {"symbol": "usdt", "amount": 80000000, "amount_usd": 80000000,
         "from": {"owner": "tether_treasury", "owner_type": "unknown"},
         "to": {"owner": "binance", "owner_type": "exchange"},
         "timestamp": now - 600},
        {"symbol": "btc", "amount": 1200, "amount_usd": 156000000,
         "from": {"owner": "kraken", "owner_type": "exchange"},
         "to": {"owner": "unknown", "owner_type": "unknown"},
         "timestamp": now - 900},
        {"symbol": "usdc", "amount": 45000000, "amount_usd": 45000000,
         "from": {"owner": "circle", "owner_type": "unknown"},
         "to": {"owner": "coinbase", "owner_type": "exchange"},
         "timestamp": now - 1200},
        {"symbol": "btc", "amount": 800, "amount_usd": 104000000,
         "from": {"owner": "unknown", "owner_type": "unknown"},
         "to": {"owner": "upbit", "owner_type": "exchange"},
         "timestamp": now - 1500},
        {"symbol": "usdt", "amount": 120000000, "amount_usd": 120000000,
         "from": {"owner": "unknown", "owner_type": "unknown"},
         "to": {"owner": "bybit", "owner_type": "exchange"},
         "timestamp": now - 1800},
    ]


# ═══════════════════════════════════════════
# 데이터 가공
# ═══════════════════════════════════════════
def process_transactions(transactions):
    """트랜잭션 데이터를 대시보드용으로 가공합니다."""

    whale_alerts = []
    usdt_inflow = 0
    usdc_inflow = 0

    for tx in transactions:
        # 기본 필드 추출
        symbol = tx.get("symbol", "").upper()
        amount = tx.get("amount", 0)
        amount_usd = tx.get("amount_usd", 0)
        timestamp = tx.get("timestamp", 0)

        # from/to 처리
        from_info = tx.get("from", {})
        to_info = tx.get("to", {})
        from_owner = from_info.get("owner", "unknown")
        to_owner = to_info.get("owner", "unknown")
        from_type = from_info.get("owner_type", "unknown")
        to_type = to_info.get("owner_type", "unknown")

        # 사람이 읽기 좋은 형태로
        from_label = from_owner.replace("_", " ").title() if from_owner != "unknown" else "Unknown Wallet"
        to_label = to_owner.replace("_", " ").title() if to_owner != "unknown" else "Unknown Wallet"

        whale_alerts.append({
            "symbol": symbol,
            "amount": amount,
            "amount_usd": amount_usd,
            "from": from_label,
            "to": to_label,
            "from_type": from_type,
            "to_type": to_type,
            "timestamp": timestamp,
        })

        # 거래소로 향하는 스테이블코인 유입량 집계
        is_to_exchange = to_type == "exchange" or to_owner.lower() in EXCHANGES
        if is_to_exchange:
            if symbol in ("USDT", "TETHER"):
                usdt_inflow += amount_usd
            elif symbol in ("USDC", "USD COIN"):
                usdc_inflow += amount_usd

    # 금액 큰 순으로 정렬
    whale_alerts.sort(key=lambda x: x["amount_usd"], reverse=True)

    return {
        "whale_alerts": whale_alerts[:15],
        "stablecoin_inflow": {
            "usdt": usdt_inflow,
            "usdc": usdc_inflow,
            "total": usdt_inflow + usdc_inflow,
            "max_reference": 500000000,
        },
        "mvrv": generate_mvrv(),
        "cvd": fetch_binance_cvd(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "analysis": generate_analysis(whale_alerts, usdt_inflow, usdc_inflow),
    }


def fetch_binance_cvd():
    """
    Binance Futures aggTrades에서 CVD(Cumulative Volume Delta)를 계산합니다.
    
    원리:
    - aggTrades의 'm' 필드: True = 매수자가 maker(= taker가 매도 = 매도 체결)
    -                       False = 매도자가 maker(= taker가 매수 = 매수 체결)
    - CVD = Σ(매수 체결량) - Σ(매도 체결량)
    
    체급 분류:
    - 🐋 100+ BTC: 고래 (기관/세력)
    - 🦈 10~100 BTC: 상어 (대형 개인)
    - 🐟 1~10 BTC: 물고기 (중형 개인)  
    - 🦐 <1 BTC: 새우 (소형 개인/개미)
    
    Binance API:
    - 엔드포인트: https://fapi.binance.com/fapi/v1/aggTrades
    - 무료, 키 불필요
    - 제한: 분당 2400 요청
    """
    try:
        # 최근 1시간 aggTrades (limit=1000, 최대)
        url = "https://fapi.binance.com/fapi/v1/aggTrades?symbol=BTCUSDT&limit=1000"
        req = Request(url, headers={"User-Agent": "JHONBER-NODE/1.0"})
        response = urlopen(req, timeout=15)
        trades = json.loads(response.read().decode())
        
        if not trades:
            return _demo_cvd()
        
        # BTC 현재가 추정 (마지막 체결가)
        btc_price = float(trades[-1]["p"])
        
        # 체급별 CVD 계산
        cvd_whale = 0.0    # 100+ BTC
        cvd_shark = 0.0    # 10~100 BTC
        cvd_fish = 0.0     # 1~10 BTC
        cvd_shrimp = 0.0   # <1 BTC
        
        total_buy_vol = 0.0
        total_sell_vol = 0.0
        
        for t in trades:
            qty = float(t["q"])       # BTC 수량
            price = float(t["p"])     # 체결가
            usd_val = qty * price
            is_sell = t["m"]          # True = taker가 매도
            
            if is_sell:
                total_sell_vol += usd_val
                delta = -usd_val
            else:
                total_buy_vol += usd_val
                delta = usd_val
            
            # 체급 분류
            if qty >= 100:
                cvd_whale += delta
            elif qty >= 10:
                cvd_shark += delta
            elif qty >= 1:
                cvd_fish += delta
            else:
                cvd_shrimp += delta
        
        total_cvd = cvd_whale + cvd_shark + cvd_fish + cvd_shrimp
        
        # 분석 텍스트 생성
        analysis = _generate_cvd_analysis(cvd_whale, cvd_shark, cvd_fish, cvd_shrimp, total_cvd)
        
        return {
            "total": round(total_cvd),
            "whale": round(cvd_whale),      # 100+ BTC
            "shark": round(cvd_shark),       # 10~100 BTC
            "fish": round(cvd_fish),         # 1~10 BTC
            "shrimp": round(cvd_shrimp),     # <1 BTC
            "buy_volume": round(total_buy_vol),
            "sell_volume": round(total_sell_vol),
            "btc_price": btc_price,
            "trade_count": len(trades),
            "source": "Binance Futures BTCUSDT",
            "analysis": analysis,
        }
        
    except Exception as e:
        print(f"⚠  Binance CVD 수집 실패: {e}")
        return _demo_cvd()


def _generate_cvd_analysis(whale, shark, fish, shrimp, total):
    """CVD 체급별 분석 텍스트"""
    
    whale_dir = "매수" if whale > 0 else "매도"
    shrimp_dir = "매수" if shrimp > 0 else "매도"
    
    # 고래 매수 + 개미 매도 = 전형적 바닥 축적
    if whale > 0 and shrimp < 0:
        signal = f'<span style="color:var(--green);font-weight:700;">고래 매수 우세</span> — 🐋 100+ BTC 체급이 적극 매수 중(${abs(whale)/1e6:.1f}M). 🦐 개미는 패닉셀 중(${abs(shrimp)/1e6:.1f}M). <span style="color:var(--gold)">전형적인 바닥 축적 패턴</span>. 스마트머니를 따라가세요.'
    # 고래 매도 + 개미 매수 = 물량 떠넘기기
    elif whale < 0 and shrimp > 0:
        signal = f'<span style="color:var(--red);font-weight:700;">고래 매도 우세</span> — 🐋 체급이 ${abs(whale)/1e6:.1f}M 매도 중. 🦐 개미가 매수로 받고 있음. <span style="color:var(--red)">물량 떠넘기기 패턴</span>. 추격 매수 위험.'
    # 전체 매수 우세
    elif total > 0:
        signal = f'<span style="color:var(--green)">전체 매수 우세</span> — 총 CVD ${total/1e6:.1f}M. 매수 모멘텀이 살아있는 구간.'
    # 전체 매도 우세
    else:
        signal = f'<span style="color:var(--red)">전체 매도 우세</span> — 총 CVD ${total/1e6:.1f}M. 매도 압력 지속 중. 관망 권장.'
    
    return signal


def _demo_cvd():
    """Binance 연결 실패 시 데모 CVD"""
    import random
    whale = random.randint(10_000_000, 50_000_000) * random.choice([1, -1])
    shark = random.randint(3_000_000, 15_000_000) * random.choice([1, -1])
    fish = random.randint(-10_000_000, 10_000_000)
    shrimp = random.randint(-20_000_000, -5_000_000)  # 개미는 보통 매도 우세
    total = whale + shark + fish + shrimp
    
    return {
        "total": total,
        "whale": whale,
        "shark": shark,
        "fish": fish,
        "shrimp": shrimp,
        "buy_volume": abs(total) + random.randint(50_000_000, 100_000_000),
        "sell_volume": abs(total) + random.randint(50_000_000, 100_000_000),
        "btc_price": 70000,
        "trade_count": 1000,
        "source": "Demo (Binance 연결 대기)",
        "analysis": _generate_cvd_analysis(whale, shark, fish, shrimp, total),
    }


def generate_mvrv():
    """
    MVRV Ratio 데이터.
    실제 연동 시 CryptoQuant API 또는 Glassnode API를 사용하세요.
    - CryptoQuant: https://cryptoquant.com/docs
    - Glassnode: https://docs.glassnode.com
    현재는 데모 값을 생성합니다.
    """
    import random
    # 데모: 1.5 ~ 3.0 사이 랜덤 (실제로는 API에서 가져옴)
    value = round(random.uniform(1.5, 3.0), 2)
    
    if value > 3.5:
        analysis = f'MVRV <span style="color:var(--red)">{value}</span> — 극도 과열. 대부분의 홀더가 큰 수익 구간. 차익 실현 매물 대량 출회 가능성. 레버리지 즉시 축소 권장.'
    elif value > 2.5:
        analysis = f'MVRV <span style="color:var(--gold)">{value}</span> — 수익 구간 진입. 과열까지는 여유 있으나 부분 익절 전략 고려. 토성의 보수적 에너지와 공명하여 리스크 관리 필요.'
    elif value > 1.0:
        analysis = f'MVRV <span style="color:var(--green)">{value}</span> — 건강한 상승 구간. 홀더 대부분 소폭 수익. 목성(게자리) 확장 에너지 아래 점진적 상승 트렌드 유지 가능.'
    else:
        analysis = f'MVRV <span style="color:var(--cyan)">{value}</span> — 저평가 구간! 홀더 대부분 손실. 역사적으로 최고의 진입 타점. 역발상 풀매수 시그널.'
    
    return {"value": value, "analysis": analysis}


def generate_analysis(alerts, usdt, usdc):
    """온체인 × 점성술 연계 분석 텍스트 생성"""
    total = usdt + usdc
    exchange_inflow = sum(1 for a in alerts if a.get("to_type") == "exchange")
    exchange_outflow = sum(1 for a in alerts if a.get("from_type") == "exchange")

    if total > 300000000:
        energy = "과열"
        astro = '<span style="color:var(--red)">화성의 파괴적 에너지</span>와 공명하는 대규모 자금 이동이 감지됩니다.'
    elif total > 150000000:
        energy = "고에너지"
        astro = '<span style="color:var(--gold)">목성(게자리)</span>의 확장 에너지 아래 기관급 자금이 활발히 이동하고 있습니다.'
    else:
        energy = "안정"
        astro = '<span style="color:var(--green)">금성</span>의 조화로운 에너지가 시장에 안정감을 부여하고 있습니다.'

    flow_text = ""
    if exchange_inflow > exchange_outflow:
        flow_text = "거래소 순유입 우세 → 단기 매도 압력 가능성에 주의하세요."
    elif exchange_outflow > exchange_inflow:
        flow_text = "거래소 순유출 우세 → 장기 보유(HODL) 심리 강화 신호입니다."
    else:
        flow_text = "유입/유출이 균형 → 관망 장세, 방향성 탐색 구간입니다."

    return (
        f"에너지 레벨: <span style='color:var(--gold)'>{energy}</span> — {astro} "
        f"스테이블코인 총 유입 <span style='color:var(--cyan)'>${total/1000000:.0f}M</span>. "
        f"{flow_text}"
    )


# ═══════════════════════════════════════════
# 메인 실행
# ═══════════════════════════════════════════
def run_once():
    """한 번 실행하여 data.json 저장"""
    print(f"🔍  전체 데이터 수집 중... ({datetime.now().strftime('%H:%M:%S')})")
    transactions = fetch_whale_alerts()
    result = process_transactions(transactions)
    
    # 시장 데이터 수집 (프록시 불필요 — 서버에서 직접 호출)
    result["market"] = fetch_market_data()
    result["funding"] = fetch_funding_data()
    
    # JSON 저장
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUTPUT_FILE)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"💾  {output_path} 저장 완료")
    print(f"    고래 알림: {len(result['whale_alerts'])}건")
    m = result.get("market", {})
    print(f"    SPX: {m.get('spx','N/A')} | NDX: {m.get('ndx','N/A')} | VIX: {m.get('vix','N/A')}")
    print(f"    GOLD: {m.get('gold','N/A')} | OIL: {m.get('oil','N/A')}")
    f_data = result.get("funding", {})
    print(f"    펀딩: {f_data.get('rate','N/A')} | 롱/쇼트: {f_data.get('long_pct','N/A')}/{f_data.get('short_pct','N/A')}")
    return result


def fetch_market_data():
    """Yahoo Finance에서 주가/원자재/VIX + FRED 금리 수집"""
    symbols = {
        'spx': '^GSPC',
        'ndx': '^NDX',
        'dji': '^DJI',
        'kospi': '^KS11',
        'vix': '^VIX',
        'dxy': 'DX-Y.NYB',
        'gold': 'GC=F',
        'silver': 'SI=F',
        'oil': 'CL=F',
        'brent': 'BZ=F',
        'natgas': 'NG=F',
        'copper': 'HG=F',
    }
    result = {}
    
    for key, sym in symbols.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=5m"
            req = Request(url, headers={"User-Agent": "JHONBER-NODE/1.0"})
            response = urlopen(req, timeout=10)
            data = json.loads(response.read().decode())
            meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
            price = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose")
            if price:
                chg = ((price - prev) / prev * 100) if prev else 0
                result[key] = round(price, 2)
                result[key + "_chg"] = round(chg, 2)
        except Exception as e:
            print(f"    ⚠ {key} 수집 실패: {e}")
    
    # M7 빅테크
    m7_symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA']
    m7_data = []
    for sym in m7_symbols:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=5m"
            req = Request(url, headers={"User-Agent": "JHONBER-NODE/1.0"})
            response = urlopen(req, timeout=10)
            data = json.loads(response.read().decode())
            meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
            price = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose")
            if price:
                chg = ((price - prev) / prev * 100) if prev else 0
                m7_data.append({"sym": sym, "price": round(price, 2), "chg": round(chg, 2)})
        except:
            pass
    result["m7"] = m7_data
    
    # FRED 기준금리 + 10년물
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS"
        req = Request(url, headers={"User-Agent": "JHONBER-NODE/1.0"})
        response = urlopen(req, timeout=10)
        text = response.read().decode()
        lines = text.strip().split('\n')
        last_val = lines[-1].split(',')[1]
        result["fed_rate"] = float(last_val)
    except Exception as e:
        print(f"    ⚠ FRED 금리 수집 실패: {e}")
    
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"
        req = Request(url, headers={"User-Agent": "JHONBER-NODE/1.0"})
        response = urlopen(req, timeout=10)
        text = response.read().decode()
        lines = text.strip().split('\n')
        for i in range(len(lines)-1, 0, -1):
            val = lines[i].split(',')[1]
            try:
                result["treasury_10y"] = float(val)
                break
            except:
                continue
    except Exception as e:
        print(f"    ⚠ FRED 10Y 수집 실패: {e}")
    
    return result


def fetch_funding_data():
    """Binance Futures 펀딩레이트 + 롱/쇼트 비율"""
    result = {}
    
    # 펀딩레이트
    try:
        url = "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=1"
        req = Request(url, headers={"User-Agent": "JHONBER-NODE/1.0"})
        response = urlopen(req, timeout=10)
        data = json.loads(response.read().decode())
        if data:
            rate = float(data[0]["fundingRate"])
            result["rate"] = round(rate * 100, 4)  # % 단위
            result["rate_str"] = f"{'+' if rate >= 0 else ''}{rate*100:.4f}%"
    except Exception as e:
        print(f"    ⚠ 펀딩레이트 수집 실패: {e}")
    
    # 롱/쇼트 비율
    try:
        url = "https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=5m&limit=1"
        req = Request(url, headers={"User-Agent": "JHONBER-NODE/1.0"})
        response = urlopen(req, timeout=10)
        data = json.loads(response.read().decode())
        if data:
            result["long_pct"] = round(float(data[0]["longAccount"]) * 100)
            result["short_pct"] = round(float(data[0]["shortAccount"]) * 100)
    except Exception as e:
        print(f"    ⚠ 롱/쇼트 수집 실패: {e}")
    
    return result


def run_loop():
    """무한 루프로 POLL_INTERVAL마다 실행"""
    print("=" * 50)
    print("  X-INTELLIGENCE : JHONBER — NODE")
    print("  온체인 데이터 수집기 v1.0")
    print("=" * 50)
    print(f"  폴링 간격: {POLL_INTERVAL}초")
    print(f"  최소 금액: ${MIN_USD_VALUE:,.0f}")
    print(f"  API 키: {'설정됨' if WHALE_ALERT_API_KEY != 'YOUR_WHALE_ALERT_API_KEY' else '미설정 (데모 모드)'}")
    print("=" * 50)
    print()

    while True:
        try:
            run_once()
            print(f"⏳  {POLL_INTERVAL}초 후 다음 폴링...\n")
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\n🛑  수집기 종료")
            sys.exit(0)
        except Exception as e:
            print(f"⚠  오류 발생: {e}")
            print(f"⏳  30초 후 재시도...\n")
            time.sleep(30)


if __name__ == "__main__":
    if "--once" in sys.argv:
        run_once()
    else:
        run_loop()
