"""
X-INTELLIGENCE : JHONBER — NODE
Railway 서버 — data.json API + 백그라운드 온체인 수집기

이 파일을 GitHub 레포에 올리면 Railway가 자동으로 감지하여 실행합니다.
"""
from flask import Flask, jsonify, send_from_directory
import json
import os
import threading
import time

app = Flask(__name__)

@app.route('/data.json')
def get_data():
    """data.json을 API로 제공"""
    try:
        with open('data.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        response = jsonify(data)
        # CORS 허용 (Vercel 프론트엔드에서 접근 가능하도록)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET'
        return response
    except Exception as e:
        return jsonify({"error": str(e), "status": "데이터 준비 중"}), 500

@app.route('/')
def health():
    """헬스체크"""
    return jsonify({
        "status": "running",
        "service": "X-INTELLIGENCE : JHONBER — NODE API",
        "endpoints": {
            "/data.json": "온체인 + CVD + MVRV 데이터"
        }
    })

def collector_loop():
    """백그라운드에서 온체인 수집기 실행"""
    time.sleep(5)  # 서버 시작 후 5초 대기
    try:
        from onchain_collector import run_loop
        run_loop()
    except Exception as e:
        print(f"수집기 오류: {e}")

if __name__ == '__main__':
    # 백그라운드 수집기 시작
    t = threading.Thread(target=collector_loop, daemon=True)
    t.start()
    
    # Flask 서버 시작
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
