# Vercel 함수 크기 제한 해결 방법

## 문제
```
Error: A Serverless Function has exceeded the unzipped maximum size of 250 MB.
```

## 해결 방법

### 1. 큰 패키지 버전 고정
- `pandas==2.0.3` (더 작은 버전)
- `numpy==1.24.3` (pandas 의존성)
- `chromadb==0.4.22` (더 작은 버전)

### 2. .vercelignore에 더 많은 파일 추가
- Python 캐시 파일
- 테스트 파일
- 불필요한 디렉토리

### 3. 대안 (여전히 작동하지 않으면)

#### 옵션 A: ChromaDB 기능을 별도 서비스로 분리
- ChromaDB 관련 기능을 별도 API 서버로 배포
- Vercel에서는 ChromaDB 없이 다른 기능만 배포

#### 옵션 B: 다른 플랫폼 사용
- **Railway**: 함수 크기 제한이 더 큼
- **Fly.io**: 컨테이너 기반 배포
- **AWS Lambda**: Layer 사용 가능
- **Google Cloud Run**: 컨테이너 기반

#### 옵션 C: Lazy Import 사용
- chromadb를 런타임에만 import
- 사용하지 않는 경우 import하지 않음

### 4. 최적화된 requirements.txt 생성
```bash
# 핵심 기능만 포함
pip install Flask flask-cors requests python-dotenv
# ChromaDB는 조건부로만 사용
```

