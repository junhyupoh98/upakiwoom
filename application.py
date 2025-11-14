"""
AWS Elastic Beanstalk entry point
Elastic Beanstalk looks for 'application' variable
"""
import sys
import os

# Add Python path for imports
backend_path = os.path.join(os.path.dirname(__file__), 'backend', 'python')
root_path = os.path.dirname(__file__)

# Add paths to sys.path
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)
if root_path not in sys.path:
    sys.path.insert(0, root_path)

print(f'[INFO] Python paths: {sys.path[:3]}')
print(f'[INFO] Backend path: {backend_path}')
print(f'[INFO] Root path: {root_path}')

# Import Flask app
# Change to backend.python.server to use absolute import
try:
    from server import app
    print('[OK] Flask app imported from server module')
except ImportError as e:
    print(f'[ERROR] Failed to import from server: {e}')
    # Try absolute import
    try:
        from backend.python.server import app
        print('[OK] Flask app imported from backend.python.server')
    except ImportError as e2:
        print(f'[ERROR] Failed to import from backend.python.server: {e2}')
        raise

# Elastic Beanstalk uses 'application' variable
application = app

if __name__ == "__main__":
    application.run(host='0.0.0.0', port=5000)

