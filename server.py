from flask import Flask, jsonify
import json, os, threading, time

app = Flask(__name__)

@app.route('/data.json')
def get_data():
    try:
        with open('data.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        response = jsonify(data)
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/')
def health():
    return jsonify({"status": "running", "service": "JHONBER-NODE API"})

def collector_loop():
    time.sleep(5)
    try:
        from onchain_collector import run_loop
        run_loop()
    except Exception as e:
        print(f"collector error: {e}")

if __name__ == '__main__':
    t = threading.Thread(target=collector_loop, daemon=True)
    t.start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
