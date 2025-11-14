"""
Vercel 서버리스 함수 래퍼
Flask 앱을 Vercel 서버리스 함수로 변환
"""
import sys
import os

# 절대 경로로 변환
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
backend_path = os.path.join(project_root, 'backend', 'python')

# Python 경로 추가
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# 환경 변수 설정 확인
os.environ.setdefault('FLASK_APP', 'server.py')

# Flask 앱 import
try:
    from server import app
    
    # Vercel에서 Flask 앱을 사용하려면 WSGI 핸들러로 export
    # Vercel은 Flask 앱을 자동으로 WSGI 핸들러로 감지합니다
    handler = app
    
except Exception as e:
    # 디버깅용 에러 처리
    import traceback
    error_msg = str(e)
    traceback.print_exc()
    
    # 에러 발생 시 에러를 반환하는 Flask 앱 생성
    from flask import Flask, jsonify
    
    error_app = Flask(__name__)
    
    @error_app.route('/', defaults={'path': ''})
    @error_app.route('/<path:path>')
    def error_handler(path):
        return jsonify({
            'error': 'Import error',
            'message': error_msg,
            'path': path
        }), 500
    
    handler = error_app

