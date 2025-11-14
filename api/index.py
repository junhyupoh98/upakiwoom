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
    
    # Vercel이 Flask 앱을 자동으로 WSGI 핸들러로 변환
    # Flask 앱을 직접 export
    handler = app
except Exception as e:
    # 디버깅용 에러 처리
    print(f"Error importing Flask app: {e}")
    import traceback
    traceback.print_exc()
    
    # 에러 발생 시 간단한 Flask 앱 반환
    from flask import Flask, jsonify
    error_app = Flask(__name__)
    @error_app.route('/<path:path>')
    def error_handler(path):
        return jsonify({'error': f'Import error: {str(e)}', 'path': path}), 500
    @error_app.route('/')
    def root_error():
        return jsonify({'error': f'Import error: {str(e)}'}), 500
    handler = error_app

