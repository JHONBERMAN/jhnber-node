#!/usr/bin/env python3
"""
X-INTELLIGENCE : JHONBER NODE — Flask API Server v6.1
=====================================================
data.json 서빙 + 캐시 헤더 최적화 + gzip + CORS

Railway Procfile: web: python server.py
"""

import gzip
import hashlib
import json
import os
import threading
import time
from flask import Flask, Response, request

app = Flask(__name__)

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
PORT = int(os.environ.get("PORT", 5000))

# ── 캐시된 응답 (메모리) ──
_cache = {"body": b"", "etag": "", "mtime": 0, "gzipped": b""}


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
        json.dumps({"service": "JHONBER NODE v6.1", "endpoints": ["/data.json", "/health"]}),
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
