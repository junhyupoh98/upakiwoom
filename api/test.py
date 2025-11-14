"""
간단한 테스트 서버리스 함수
"""
from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/')
def test():
    return jsonify({'message': 'Test endpoint works!', 'status': 'ok'})

# Vercel 핸들러
handler = app
