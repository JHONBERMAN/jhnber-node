#!/usr/bin/env python3
"""
X-INTELLIGENCE : JHONBER NODE — Flask API Server v7.0
=====================================================
data.json 서빙 + 캐시 헤더 최적화 + gzip + CORS
+ 실시간 방문자 카운터 + CDS 데이터

Railway Procfile: web: python server.py
"""

import gzip
import hashlib
import json
import os
import threading
import time
from collections import defaultdict
from flask import Flask, Response, request

app = Flask(__name__)

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
PORT = int(os.environ.get("PORT", 5000))

# ── 캐시된 응답 (메모리) ──
_cache = {"body": b"", "etag": "", "mtime": 0, "gzipped": b""}

# ── 실시간 방문자 추적 (메모리 + 파일 영속) ──
VISITOR_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "visitor_count.json")

def _load_visitor_persist():
    """영속 저장된 방문자 카운트 로드"""
    try:
        if os.path.exists(VISITOR_FILE):
            with open(VISITOR_FILE, "r") as f:
                data = json.load(f)
            return data.get("total_all", 0), data.get("today_date", ""), data.get("total_today", 0), data.get("peak_today", 0)
    except Exception:
        pass
    return 0, "", 0, 0

def _save_visitor_persist():
    """방문자 카운트 파일에 영속 저장"""
    try:
        with open(VISITOR_FILE, "w") as f:
            json.dump({
                "total_all": _visitors["total_all"],
                "total_today": _visitors["total_today"],
                "today_date": _visitors["today_date"],
                "peak_today": _visitors["peak_today"],
            }, f)
    except Exception:
        pass

# 서버 시작 시 영속 데이터 복원
_persisted = _load_visitor_persist()
_visitors = {
    "active": {},
    "total_all": _persisted[0],
    "today_date": _persisted[1],
    "total_today": _persisted[2],
    "peak_today": _persisted[3],
    "country_count": defaultdict(int),
}
_visitors_lock = threading.Lock()
VISITOR_TIMEOUT = 120  # 2분 내 ping 없으면 이탈로 간주


def _refresh_cache():
    """data.json이 변경됐으면 캐시 갱신"""
    try:
        mtime = os.path.getmtime(DATA_FILE)
        if mtime <= _cache["mtime"]:
            return  # 변경 없음

        with open(DATA_FILE, "rb") as f:
            raw = f.read()

        etag = hashlib.md5(raw).hexdigest()[:12]
        gz = gzip.compress(raw, compresslevel=6)

        _cache["body"] = raw
        _cache["etag"] = etag
        _cache["mtime"] = mtime
        _cache["gzipped"] = gz
    except FileNotFoundError:
        pass


@app.route("/data.json")
def serve_data():
    _refresh_cache()

    if not _cache["body"]:
        return Response('{"error":"data.json not ready"}',
                        status=503, mimetype="application/json")

    # ETag 304 체크
    client_etag = request.headers.get("If-None-Match", "")
    if client_etag == _cache["etag"]:
        return Response(status=304)

    # gzip 지원 여부
    accept_enc = request.headers.get("Accept-Encoding", "")
    use_gzip = "gzip" in accept_enc

    body = _cache["gzipped"] if use_gzip else _cache["body"]

    resp = Response(body, mimetype="application/json")
    resp.headers["ETag"] = _cache["etag"]
    resp.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=60"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    if use_gzip:
        resp.headers["Content-Encoding"] = "gzip"

    return resp


def _cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }


def _clean_stale_visitors():
    """타임아웃된 방문자 제거"""
    now = time.time()
    stale = [vid for vid, ts in _visitors["active"].items() if now - ts > VISITOR_TIMEOUT]
    for vid in stale:
        del _visitors["active"][vid]


def _check_today_reset():
    """날짜 변경 시 today 카운터 리셋"""
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _visitors["today_date"] != today:
        _visitors["today_date"] = today
        _visitors["total_today"] = 0
        _visitors["peak_today"] = 0
        _visitors["country_count"] = defaultdict(int)


@app.route("/api/visitors/ping", methods=["POST", "OPTIONS"])
def visitor_ping():
    """방문자 heartbeat — 프론트에서 60초마다 호출"""
    if request.method == "OPTIONS":
        return Response("", headers=_cors_headers())

    with _visitors_lock:
        _check_today_reset()
        _clean_stale_visitors()

        data = request.get_json(silent=True) or {}
        vid = data.get("vid", request.remote_addr or "unknown")
        lang = data.get("lang", "unknown")[:5]
        is_new = vid not in _visitors["active"]

        _visitors["active"][vid] = time.time()

        if is_new:
            _visitors["total_today"] += 1
            _visitors["total_all"] += 1
            # 간이 국가 추정 (Accept-Language 기반)
            accept_lang = request.headers.get("Accept-Language", "")[:2].upper()
            country = accept_lang if accept_lang else lang[:2].upper()
            if country:
                _visitors["country_count"][country] += 1

        active_count = len(_visitors["active"])
        if active_count > _visitors["peak_today"]:
            _visitors["peak_today"] = active_count

        # 새 방문자면 영속 저장 (토탈 유지)
        if is_new:
            _save_visitor_persist()

        return Response(
            json.dumps({
                "active": active_count,
                "today": _visitors["total_today"],
                "total": _visitors["total_all"],
                "peak": _visitors["peak_today"],
            }),
            mimetype="application/json",
            headers=_cors_headers(),
        )


@app.route("/api/visitors")
def visitor_stats():
    """현재 방문자 통계 (읽기 전용)"""
    with _visitors_lock:
        _check_today_reset()
        _clean_stale_visitors()
        return Response(
            json.dumps({
                "active": len(_visitors["active"]),
                "today": _visitors["total_today"],
                "total": _visitors["total_all"],
                "peak_today": _visitors["peak_today"],
            }),
            mimetype="application/json",
            headers=_cors_headers(),
        )


@app.route("/health")
def health():
    exists = os.path.exists(DATA_FILE)
    age = int(time.time() - os.path.getmtime(DATA_FILE)) if exists else -1
    return Response(
        json.dumps({"status": "ok" if exists else "no_data", "data_age_sec": age}),
        mimetype="application/json",
        headers={"Access-Control-Allow-Origin": "*"},
    )


@app.route("/")
def root():
    return Response(
        json.dumps({"service": "JHONBER NODE v7.0", "endpoints": [
            "/data.json", "/health", "/api/visitors", "/api/visitors/ping"
        ]}),
        mimetype="application/json",
        headers={"Access-Control-Allow-Origin": "*"},
    )


# ── Collector를 백그라운드 스레드로 실행 ──
def _run_collector():
    """onchain_collector.py의 run_loop()를 백그라운드에서 실행"""
    time.sleep(3)  # Flask 서버 먼저 뜨게 대기
    try:
        from onchain_collector import run_loop
        run_loop()
    except Exception as e:
        print(f"⚠ Collector thread error: {e}")


if __name__ == "__main__":
    # Collector 백그라운드 스레드 시작
    t = threading.Thread(target=_run_collector, daemon=True)
    t.start()

    print(f"🚀 JHONBER NODE server on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
