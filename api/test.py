"""
간단한 테스트 서버리스 함수
Vercel 배포가 제대로 작동하는지 확인
"""
def handler(request):
    from flask import Flask, jsonify
    app = Flask(__name__)
    
    @app.route('/')
    def index():
        return jsonify({'message': 'Test function works!', 'status': 'ok'})
    
    return app

