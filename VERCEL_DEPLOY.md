# Vercel 배포 가이드

## 1. Vercel CLI 설치 (로컬에서 배포할 경우)

```bash
npm install -g vercel
```

## 2. Vercel 로그인

```bash
vercel login
```

## 3. 배포

### 방법 1: Vercel CLI 사용 (터미널)

```bash
# 프로젝트 루트에서 실행
vercel

# 프로덕션 배포
vercel --prod
```

### 방법 2: GitHub 연동 (권장)

1. [Vercel 대시보드](https://vercel.com/dashboard) 접속
2. "Add New Project" 클릭
3. GitHub 저장소 선택 (`junhyupoh98/upakiwoom`)
4. 프로젝트 설정:
   - **Framework Preset**: Other
   - **Root Directory**: `.` (루트)
   - **Build Command**: (비워두기)
   - **Output Directory**: (비워두기)
5. Environment Variables 추가:
   ```
   FMP_API_KEY=your_api_key
   DART_API_KEY=your_api_key
   NAVER_CLIENT_ID=your_client_id
   NAVER_CLIENT_SECRET=your_client_secret
   OPENAI_API_KEY=your_api_key
   GEMINI_API_KEY=your_api_key
   CHROMADB_API_KEY=your_api_key
   CHROMADB_TENANT=your_tenant
   CHROMADB_DATABASE=your_database
   GOOGLE_APPLICATION_CREDENTIALS=path/to/credentials.json
   ```
6. "Deploy" 클릭

## 4. 주요 설정 파일

- `vercel.json`: Vercel 라우팅 및 빌드 설정
- `api/index.py`: Flask 앱을 서버리스 함수로 래핑
- `requirements.txt`: Python 의존성

## 5. 환경 변수 설정

Vercel 대시보드에서 Environment Variables 설정:
- Settings → Environment Variables
- 프로덕션, 프리뷰, 개발 환경별로 설정 가능

## 6. 트러블슈팅

### 문제: Python 모듈을 찾을 수 없음
- `requirements.txt`에 모든 의존성이 포함되어 있는지 확인
- Vercel은 `requirements.txt`를 자동으로 인식하여 설치

### 문제: 환경 변수 누락
- Vercel 대시보드에서 환경 변수가 제대로 설정되었는지 확인
- `.env` 파일은 Vercel에 업로드되지 않으므로 대시보드에서 설정 필요

### 문제: 정적 파일이 로드되지 않음
- `frontend/` 폴더의 파일들이 정적 파일로 제공되도록 `vercel.json` 설정 확인
- 프론트엔드에서 API 호출 시 상대 경로 대신 절대 경로 사용 고려

## 7. 배포 후 확인

배포 완료 후:
- 프론트엔드: `https://your-project.vercel.app/`
- API 엔드포인트: `https://your-project.vercel.app/api/...`

