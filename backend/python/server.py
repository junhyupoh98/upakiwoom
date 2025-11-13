from flask import Flask, jsonify, request
from flask_cors import CORS
import FinanceDataReader as fdr
from datetime import datetime, timedelta, timezone
import pandas as pd
import requests
import time
import re
import difflib
import os
import json
from urllib.parse import urlencode, urlparse
from typing import List, Dict, Optional, Union, Any, Tuple
from deep_translator import GoogleTranslator
from openai import OpenAI
from newspaper import Article, ArticleException
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

try:
    from .chroma_client import (
        fetch_us_stock_news,
        fetch_kr_stock_news,
        fetch_us_financials_from_chroma,
        fetch_kr_financials_from_chroma,
    )
except ImportError:
    from chroma_client import (  # type: ignore
        fetch_us_stock_news,
        fetch_kr_stock_news,
        fetch_us_financials_from_chroma,
        fetch_kr_financials_from_chroma,
    )

try:
    from .vision_bridge import analyze_product_from_image
except ImportError:
    from vision_bridge import analyze_product_from_image  # type: ignore
from pathlib import Path
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
# DART API는 requests로 직접 호출

app = Flask(__name__)
CORS(app)

# FMP API 키 (무료 티어 사용)
FMP_API_KEY = os.getenv("FMP_API_KEY")
# DART API 키 (https://opendart.fss.or.kr/ 에서 발급 필요)
DART_API_KEY = os.getenv("DART_API_KEY")
# 네이버 뉴스 API 키
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# API 키 설정 상태 로그
if FMP_API_KEY:
    print('[OK] FMP API 키가 설정되었습니다.')
else:
    print('[WARN] FMP API 키가 설정되지 않았습니다. 일부 해외 데이터가 제한될 수 있습니다.')

# DART API 초기화 확인
if DART_API_KEY:
    print('[OK] DART API 키가 설정되었습니다.')
else:
    print('[WARN] DART API 키가 설정되지 않았습니다.')

if NAVER_CLIENT_ID and NAVER_CLIENT_SECRET:
    print('[OK] 네이버 뉴스 API 키가 설정되었습니다.')
else:
    print('[WARN] 네이버 뉴스 API 키가 설정되지 않았습니다. 네이버 뉴스 검색 기능이 제한될 수 있습니다.')

# OpenAI 클라이언트 초기화
openai_client = None
if OPENAI_API_KEY:
    try:
        openai_client = OpenAI(api_key=OPENAI_API_KEY)
        print(f'[OK] OpenAI 클라이언트 초기화 성공')
    except Exception as e:
        print(f'[ERROR] OpenAI 클라이언트 초기화 실패: {e}')
        openai_client = None
else:
    print('[WARN] OpenAI API 키가 설정되지 않았습니다. 요약 기능이 작동하지 않습니다.')

# 한국 주식 심볼 코드 매핑 (일부 주요 종목)
KR_STOCK_MAP = {
    '삼성전자': '005930',
    'SK하이닉스': '000660',
    'NAVER': '035420',
    '카카오': '035720',
    'LG화학': '051910',
    '트랜스오션': '065350',
    '에스비비테크': '389500',
    '현대차': '005380',
    '기아': '000270',
    '셀트리온': '068270',
}

def search_kr_stock_symbol(query):
    """회사명으로 심볼 코드 찾기"""
    # 공백 제거 (예: "원익 홀딩스" → "원익홀딩스")
    query_normalized = query.strip().replace(' ', '').replace('\t', '')
    print(f'종목 검색 시작: "{query_normalized}" (원본: "{query}")')
    
    # 숫자 6자리면 그대로 반환
    if query_normalized.isdigit() and len(query_normalized) == 6:
        print(f'종목코드로 인식: {query_normalized}')
        return query_normalized
    
    # FinanceDataReader로 먼저 검색 (실제 데이터베이스 우선)
    try:
        print(f'KRX 리스트 검색 시도: {query_normalized}')
        # KRX 상장 종목 리스트 가져오기 (캐시 사용)
        krx_list = get_krx_list_cached()
        if krx_list is not None and not krx_list.empty:
            print(f'KRX 리스트 크기: {len(krx_list)}')
            # 정확한 매칭 먼저 시도
            symbol_col = 'Code' if 'Code' in krx_list.columns else ('Symbol' if 'Symbol' in krx_list.columns else None)
            name_col = 'Name' if 'Name' in krx_list.columns else '종목명'
            
            if symbol_col:
                # 정확한 이름 매칭
                exact_match = krx_list[krx_list[name_col].str.strip().str.lower() == query_normalized.lower()]
                if not exact_match.empty:
                    found_symbol = str(exact_match.iloc[0][symbol_col]).zfill(6)
                    found_name = exact_match.iloc[0][name_col]
                    print(f'KRX 정확 매칭 성공: {found_name} ({found_symbol})')
                    return found_symbol
                
                # 부분 매칭 (회사명에 포함된 경우)
                result = krx_list[krx_list[name_col].str.contains(query_normalized, case=False, na=False)]
                print(f'검색 결과 수: {len(result)}')
                if not result.empty:
                    found_symbol = str(result.iloc[0][symbol_col]).zfill(6)
                    found_name = result.iloc[0][name_col]
                    print(f'KRX에서 찾은 종목: {found_name} ({found_symbol})')
                    return found_symbol
                else:
                    print(f'KRX 리스트에서 "{query_normalized}"를 찾을 수 없음')
            else:
                print('KRX 리스트에 종목코드 컬럼이 없습니다')
        else:
            print('KRX 리스트가 비어있음')
    except Exception as e:
        print(f'KRX 검색 오류: {str(e)}')
        import traceback
        traceback.print_exc()
    
    # KRX 검색 실패 시에만 하드코딩된 매핑 확인 (폴백)
    print(f'하드코딩 매핑 확인 (폴백): {query_normalized}')
    query_lower = query_normalized.lower()
    for name, symbol in KR_STOCK_MAP.items():
        # 정확한 매칭만 확인 (부분 매칭 제거)
        if query_normalized == name or query_lower == name.lower():
            print(f'하드코딩 매핑에서 찾음: {name} -> {symbol}')
            return symbol
    
    return None

@app.route('/api/kr-stock/search/<query>', methods=['GET'])
def search_stock(query):
    """회사명으로 한국 주식 검색"""
    try:
        print(f'검색 요청: {query}')
        symbol = search_kr_stock_symbol(query)
        print(f'찾은 심볼: {symbol}')
        
        if not symbol:
            print(f'심볼을 찾을 수 없음: {query}')
            return jsonify({'error': f'"{query}"를 찾을 수 없습니다.'}), 404
        
        # 주가 정보 가져오기
        print(f'주가 정보 조회 시작: {symbol}')
        # 최근 1년 데이터 가져오기
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        df = fdr.DataReader(symbol, start_date, end_date)
        if df is None or df.empty:
            print(f'주가 정보를 가져올 수 없음: {symbol}')
            return jsonify({'error': '주가 정보를 가져올 수 없습니다.'}), 500
        print(f'주가 정보 조회 성공: {symbol} (데이터 수: {len(df)})')
        
        latest = df.iloc[-1]
        previous = df.iloc[-2] if len(df) > 1 else latest
        
        change = float(latest['Close'] - previous['Close'])
        change_percent = float((change / previous['Close']) * 100) if previous['Close'] != 0 else 0
        
        # 회사명 가져오기 (검색 과정에서 이미 찾았으므로 재검색 불필요)
        company_name = query
        # 매핑에서 찾은 경우 회사명 사용
        if symbol in KR_STOCK_MAP.values():
            for name, sym in KR_STOCK_MAP.items():
                if sym == symbol:
                    company_name = name
                    break
        else:
            # KRX 리스트에서 회사명 가져오기 (캐시 사용)
            try:
                krx_list = get_krx_list_cached()
                if krx_list is not None and not krx_list.empty:
                    # 컬럼명 확인 (Symbol 또는 Code일 수 있음)
                    symbol_col = 'Symbol' if 'Symbol' in krx_list.columns else 'Code'
                    name_col = 'Name' if 'Name' in krx_list.columns else '종목명'
                    company_info = krx_list[krx_list[symbol_col] == symbol]
                    if not company_info.empty:
                        company_name = company_info.iloc[0][name_col]
            except Exception as e:
                print(f'회사명 조회 오류: {str(e)}')
                pass
        
        # 뉴스는 버튼 클릭 시에만 가져오므로 여기서는 제외
        result = {
            'symbol': f'{symbol}.KS',
            'name': company_name,
            'price': float(latest['Close']),
            'change': float(change),
            'changePercent': round(change_percent, 2),
            'volume': int(latest['Volume']) if 'Volume' in latest else 0,
            'open': float(latest['Open']),
            'high': float(latest['High']),
            'low': float(latest['Low']),
            'currency': 'KRW',
            'exchange': 'KRX',
            'isKorean': True
        }
        
        return jsonify(result)
    except Exception as e:
        import traceback
        print(f'검색 오류: {str(e)}')
        traceback.print_exc()
        return jsonify({'error': f'주가 정보 조회 중 오류가 발생했습니다: {str(e)}'}), 500

@app.route('/api/kr-stock/<symbol>', methods=['GET'])
def get_stock(symbol):
    """심볼 코드로 한국 주식 정보 가져오기"""
    try:
        # 심볼 코드 정리 (.KS 제거)
        clean_symbol = symbol.replace('.KS', '').replace('.KQ', '')
        
        if not clean_symbol.isdigit() or len(clean_symbol) != 6:
            return jsonify({'error': '올바른 심볼 코드가 아닙니다.'}), 400
        
        # 주가 정보 가져오기
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        df = fdr.DataReader(clean_symbol, start_date, end_date)
        if df is None or df.empty:
            return jsonify({'error': '주가 정보를 가져올 수 없습니다.'}), 500
        
        latest = df.iloc[-1]
        previous = df.iloc[-2] if len(df) > 1 else latest
        
        change = float(latest['Close'] - previous['Close'])
        change_percent = float((change / previous['Close']) * 100) if previous['Close'] != 0 else 0
        
        # 회사명 가져오기 (캐시 사용)
        krx_list = get_krx_list_cached()
        company_name = clean_symbol
        if krx_list is not None and not krx_list.empty:
            symbol_col = 'Symbol' if 'Symbol' in krx_list.columns else 'Code'
            name_col = 'Name' if 'Name' in krx_list.columns else '종목명'
            company_info = krx_list[krx_list[symbol_col] == clean_symbol]
            if not company_info.empty:
                company_name = company_info.iloc[0][name_col]
        
        result = {
            'symbol': f'{clean_symbol}.KS',
            'name': company_name,
            'price': float(latest['Close']),
            'change': float(change),
            'changePercent': round(change_percent, 2),
            'volume': int(latest['Volume']) if 'Volume' in latest else 0,
            'open': float(latest['Open']),
            'high': float(latest['High']),
            'low': float(latest['Low']),
            'currency': 'KRW',
            'exchange': 'KRX',
            'isKorean': True
        }
        
        return jsonify(result)
    except Exception as e:
        print(f'오류: {str(e)}')
        return jsonify({'error': f'주가 정보 조회 중 오류가 발생했습니다: {str(e)}'}), 500

@app.route('/api/kr-stock/<symbol>/chart', methods=['GET'])
def get_stock_chart(symbol):
    """한국 주식 차트 데이터"""
    try:
        period = request.args.get('period', '1m')
        clean_symbol = symbol.replace('.KS', '').replace('.KQ', '')
        
        # 기간 설정
        if period == '1m':
            start_date = datetime.now() - timedelta(days=30)
        elif period == '3m':
            start_date = datetime.now() - timedelta(days=90)
        elif period == '6m':
            start_date = datetime.now() - timedelta(days=180)
        elif period == '1y':
            start_date = datetime.now() - timedelta(days=365)
        else:
            start_date = datetime.now() - timedelta(days=30)
        
        # 주가 데이터 가져오기
        end_date = datetime.now()
        df = fdr.DataReader(clean_symbol, start_date, end_date)
        if df is None or df.empty:
            return jsonify({'error': '차트 데이터를 가져올 수 없습니다.'}), 500
        
        chart_data = []
        for idx, row in df.iterrows():
            chart_data.append({
                'date': idx.strftime('%Y-%m-%d'),
                'open': float(row['Open']),
                'high': float(row['High']),
                'low': float(row['Low']),
                'close': float(row['Close']),
                'volume': int(row['Volume']) if 'Volume' in row else 0
            })
        
        return jsonify({
            'symbol': f'{clean_symbol}.KS',
            'period': period,
            'data': chart_data
        })
    except Exception as e:
        print(f'차트 오류: {str(e)}')
        return jsonify({'error': f'차트 데이터 조회 중 오류가 발생했습니다: {str(e)}'}), 500

# ============ 네이버 뉴스 API 설정 ============
NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"
NAVER_NEWS_TARGET_COUNT = 10
NAVER_NEWS_RECENT_DAYS = 60
NAVER_NEWS_PER_PAGE = 100
NAVER_NEWS_MAX_PAGES = 5
NAVER_NEWS_SLEEP_SEC = 0.03

# 화이트리스트(도메인)
NAVER_WHITELIST = {
    "chosun.com": "조선일보",
    "joongang.co.kr": "중앙일보",
    "donga.com": "동아일보",
    "kyunghyang.com": "경향신문",
    "hani.co.kr": "한겨레",
    "hankookilbo.com": "한국일보",
    "mk.co.kr": "매일경제",
    "hankyung.com": "한국경제",
    "sedaily.com": "서울경제",
    "mt.co.kr": "머니투데이",
    "fnnews.com": "파이낸셜뉴스",
    "asiae.co.kr": "아시아경제",
}
NAVER_WHITELIST_KEYS = set(NAVER_WHITELIST.keys())

PRESS_TO_DOMAIN = {
    "조선일보": "chosun.com",
    "중앙일보": "joongang.co.kr",
    "동아일보": "donga.com",
    "경향신문": "kyunghyang.com",
    "한겨레": "hani.co.kr",
    "한국일보": "hankookilbo.com",
    "매일경제": "mk.co.kr",
    "한국경제": "hankyung.com",
    "서울경제": "sedaily.com",
    "머니투데이": "mt.co.kr",
    "파이낸셜뉴스": "fnnews.com",
    "아시아경제": "asiae.co.kr",
}

# 언론사 추정 패턴
PRESS_META_PATTERNS = [
    re.compile(r'property=["\']og:article:author["\']\s+content=["\']([^"\']{2,20})["\']', re.I),
    re.compile(r'data-office-name=["\']([^"\']{2,20})["\']', re.I),
    re.compile(r'aria-label=["\']([^"\']{2,20})["\']', re.I),
    re.compile(r'"press_logo"[^>]*alt=["\']([^"\']{2,20})["\']', re.I),
]

# HTML 태그 제거 정규식
_TAG = re.compile(r"<.*?>")
_WS = re.compile(r"\s+")

KST = timezone(timedelta(hours=9))

# 네이버 뉴스 유틸 함수
def clean_html_naver(s: str) -> str:
    """HTML 태그 제거"""
    if not s:
        return ""
    s = _TAG.sub(" ", s).replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&")
    return _WS.sub(" ", s).strip()

def parse_dt_naver(rfc822_text: Optional[str]) -> Optional[datetime]:
    """RFC822 날짜 파싱"""
    if not rfc822_text:
        return None
    try:
        dt = datetime.strptime(rfc822_text, "%a, %d %b %Y %H:%M:%S %z")
        return dt.astimezone(KST)
    except Exception:
        return None

def netloc_domain_naver(url: str) -> str:
    """URL에서 도메인 추출"""
    try:
        netloc = urlparse(url).netloc.lower().replace("www.", "")
        return netloc
    except Exception:
        return ""

def normalize_korean_naver(s: str) -> str:
    """한글 정규화"""
    return re.sub(r"[\s\W_]+", "", s or "").lower()

def contains_company_naver(text: str, company: str) -> bool:
    """회사명 포함 여부 확인"""
    if not text or not company:
        return False
    base = company.strip()
    no_space = normalize_korean_naver(base)
    if re.search(re.escape(base), text, flags=re.IGNORECASE):
        return True
    if no_space and no_space in normalize_korean_naver(text):
        return True
    if re.search(r"(?:\(\s*주\s*\)\s*)?" + re.escape(base), text, flags=re.IGNORECASE):
        return True
    return False

def infer_press_from_naver(link: str, timeout: int = 4) -> Optional[str]:
    """네이버 링크에서 언론사 추정"""
    if not link:
        return None
    try:
        r = requests.get(link, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        if r.status_code >= 400:
            return None
        text = r.text[:200000]
        for pat in PRESS_META_PATTERNS:
            m = pat.search(text)
            if m:
                press = m.group(1).strip()
                press = re.sub(r"[\s\u200b]+", "", press)
                return press
    except Exception:
        return None
    return None

def summarize_naver_news(title: str, desc: str) -> str:
    """OpenAI로 뉴스 요약"""
    if not openai_client:
        return desc or ""
    prompt = f"""
아래 정보를 바탕으로 한국어 6~8줄 bullet 요약을 만들어줘.
- 확인된 사실/숫자/주체 중심, 과장/추측 금지
- 각 줄 20~40자권, 중복/광고 제거

제목: {title}
요약문: {desc}
"""
    try:
        resp = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "경제·금융 뉴스를 정확하게 한국어로 요약하는 분석가"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=420,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[WARN] 요약 실패: {e}")
        return desc or ""

def fetch_naver_news_raw(query: str, start: int, display: int, sort: str) -> List[Dict]:
    """네이버 뉴스 API 호출"""
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return []
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    params = {"query": query, "display": display, "start": start, "sort": sort}
    url = f"{NAVER_NEWS_API_URL}?{urlencode(params, safe=':/')}"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 429:
            print(f"[WARN] 네이버 API 호출 제한 도달 (429), 잠시 대기...")
            time.sleep(0.5)
            return []
        r.raise_for_status()
        data = r.json()
        return data.get("items", [])
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] 네이버 API 호출 실패: {e}")
        return []
    except Exception as e:
        print(f"[ERROR] 예상치 못한 오류: {e}")
        return []

def collect_naver_news(company: str, sort: str = "sim") -> List[Dict]:
    """네이버 뉴스 수집 (최적화: 요약 생략, 언론사 추정 최소화)"""
    query = f'"{company}"'
    cutoff = datetime.now(KST) - timedelta(days=NAVER_NEWS_RECENT_DAYS)
    rows: List[Dict] = []
    seen = set()
    start = 1

    print(f'네이버 뉴스 검색 중: {query} (최대 {NAVER_NEWS_TARGET_COUNT}개)')

    for page in range(1, NAVER_NEWS_MAX_PAGES + 1):
        items = fetch_naver_news_raw(query, start=start, display=NAVER_NEWS_PER_PAGE, sort=sort)
        if not items:
            break

        got_this_page = 0
        for it in items:
            title = clean_html_naver(it.get("title"))
            desc = clean_html_naver(it.get("description"))
            link = it.get("link") or ""
            origin = it.get("originallink") or ""
            pubdt = parse_dt_naver(it.get("pubDate"))
            if pubdt and pubdt < cutoff:
                continue

            key = origin or link
            if not key or key in seen:
                continue
            seen.add(key)

            # 회사명 필터
            if not (contains_company_naver(title, company) or contains_company_naver(desc, company)):
                continue

            # 매체 화이트리스트 (빠른 체크)
            host = netloc_domain_naver(origin)
            press_name = None
            domain_ok = False
            
            # 원본 링크에서 바로 확인
            if host in NAVER_WHITELIST_KEYS:
                domain_ok = True
                press_name = NAVER_WHITELIST[host]
            else:
                # 네이버 링크인 경우에만 언론사 추정 시도 (느린 작업)
                naver_host = netloc_domain_naver(link)
                if naver_host.endswith("naver.com") and len(rows) < NAVER_NEWS_TARGET_COUNT:
                    # 최대 10개만 언론사 추정 (느린 작업)
                    press_name = infer_press_from_naver(link, timeout=2)  # 타임아웃 단축
                    if press_name and press_name in PRESS_TO_DOMAIN:
                        mapped = PRESS_TO_DOMAIN[press_name]
                        if mapped in NAVER_WHITELIST_KEYS:
                            domain_ok = True
                            host = mapped

            if not domain_ok:
                continue

            # 요약은 나중에 또는 생략 (속도 우선)
            # summary = summarize_naver_news(title, desc)  # 느린 작업 - 생략
            summary = desc or ""  # 원본 요약문 사용
            date_kst = pubdt.strftime("%Y-%m-%d %H:%M") if pubdt else ""

            rows.append({
                'title': title,
                'summary': summary,
                'url': origin or link,
                'date': date_kst,
                'site': press_name or NAVER_WHITELIST.get(host, host)
            })
            got_this_page += 1

            print(f'  [{len(rows):02d}] {date_kst} | {press_name or NAVER_WHITELIST.get(host, host)} | {title[:50]}...')

            if len(rows) >= NAVER_NEWS_TARGET_COUNT:
                print(f'네이버 뉴스 {len(rows)}개 수집 완료')
                return rows

        if got_this_page == 0:
            break

        start += len(items)
        time.sleep(NAVER_NEWS_SLEEP_SEC)

    print(f'네이버 뉴스 {len(rows)}개 수집 완료')
    return rows

# 뉴스 수집 함수
def get_fmp_stock_news(ticker, api_key, limit=20):
    """FMP API로 주식 뉴스 가져오기"""
    print(f"\n--- [FMP] {ticker} 최신 뉴스 {limit}개 검색 ---")
    url = f"https://financialmodelingprep.com/api/v3/stock_news?tickers={ticker}&limit={limit}&apikey={api_key}"
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        data = res.json()
        if not data:
            print("뉴스 없음.")
            return []
        return data
    except Exception as e:
        print(f"FMP API 오류: {e}")
        return []

# 번역 함수
def translate_text(text, dest_lang='ko'):
    """텍스트 번역"""
    if not text:
        return ""
    MAX_CHARS = 4800
    text = text[:MAX_CHARS] if len(text) > MAX_CHARS else text
    try:
        time.sleep(0.5)
        return GoogleTranslator(source='auto', target=dest_lang).translate(text)
    except Exception:
        return "번역 실패"

# ChatGPT 요약 함수
def summarize_with_chatgpt(text):
    """ChatGPT로 뉴스 요약 (원본 로직 사용)"""
    if not text or text == "번역 실패":
        return None
    if not openai_client:
        return None
    try:
        system_prompt = (
            "당신은 월스트리트의 최고 금융 뉴스 분석가입니다. **최상의 정확성**을 유지해야 합니다.\n"
            "제공된 한국어 뉴스 기사 본문을 분석하여, 투자자가 알아야 할 **가장 중요하고 정확한 정보**만을 추출하여 **4~5 문장의 정밀한 요약문**을 작성해주세요.\n\n"
            "**🚨 최우선 주의사항 (치명적 오류 방지):**\n"
            "**1. 모든 수치, 날짜, 통화($, 원), 제품 이름 등 구체적 근거를 원문과 100% 일치시켜야 합니다. 절대로 추측하거나 틀린 정보를 생성하지 마세요.**\n"
            "**2. 기사에 명시되지 않은 미래 전망(예: 2025년 3분기)이나 개인적인 의견은 절대 포함하지 말 것.**\n\n"
            "**반드시 포함해야 할 내용:**\n"
            "1.  **핵심 사건/주장:** 이 기사의 가장 중요한 메시지나 사건은 무엇인가?\n"
            "2.  **구체적 근거 (수치/데이터):** 핵심 주장을 뒷받침하는 구체적인 숫자, 비율(%), 금액, 날짜 등이 있다면 **정확하게** 명시하라.\n"
            "3.  **관련 주체:** 이 사건의 핵심 인물, 회사, 기관은 누구인가?\n"
            "4.  **언급된 영향/전망:** 이 사건이 해당 회사, 산업, 또는 시장에 미칠 것으로 예상되는 긍정적/부정적 영향이나 향후 전망에 대한 언급이 있다면 포함하라.\n\n"
            "**출력 지침:** 불필요한 미사여구나 서론/결론은 생략하고 핵심만 간결하게 전달할 것."
        )
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[ERROR] ChatGPT 요약 오류: {e}")
        return None

def summarize_korean_text_basic(text, num_sentences=5):
    """기본 요약 함수"""
    sentences = re.split(r'(?<=[.?!])\s*', text)
    summary = ' '.join(sentences[:num_sentences])
    if summary and not summary[-1] in ('.', '?', '!'):
        return summary + '.'
    return summary

# 기사 분석 함수 (원본 로직)
PREFERRED_SOURCES = ['reuters', 'associated press', 'cnbc', 'forbes', 'business insider', 'korea']
NEWS_LIMIT = 10  # 테스트 단계: 10개로 제한

def source_score(site):
    """출처 점수 계산"""
    if not site:
        return 0
    site = site.lower()
    for i, s in enumerate(PREFERRED_SOURCES[::-1]):
        if s in site:
            return (i + 1) * 10
    return 1

def length_score(text_len):
    """길이 점수 계산"""
    if text_len > 3000:
        return 10
    elif text_len > 1500:
        return 7
    elif text_len > 700:
        return 4
    else:
        return 1

def find_and_process_high_scoring_articles(news_list, ticker_names):
    """고점수 기사 찾기 및 처리 (원본 로직)"""
    print(f"총 {len(news_list)}개 뉴스 중 베스트 기사 선별 중...")
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7'
    }
    
    scored_articles = []
    for i, art in enumerate(news_list[:NEWS_LIMIT]):
        url = art.get("url")
        site = art.get("site", "")
        current_title = art.get("title", "")
        art_meta = art
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            r.raise_for_status()
            article = Article(url)
            article.set_html(r.text)
            article.parse()
            article_text = article.text
            if len(article_text) < 200:
                continue
            rel_score = 0
            if current_title:
                current_title_lower = current_title.lower()
                for k in ticker_names:
                    if k.lower() in current_title_lower:
                        rel_score += 1
            score = (source_score(site) * 3 + length_score(len(article_text)) * 1.5 + rel_score * 2)
            scored_articles.append({'article_obj': article, 'meta': art, 'score': score})
            print(f"     [{i+1:02d}] {site:20s} | 점수: {score:4.1f} | 제목: {current_title[:40]}...")
        except Exception as e:
            print(f"     [ERROR] {site} 기사 로드 실패: {e}")
    
    if not scored_articles:
        print("[WARN] 유효한 기사 없음.")
        return []
    
    scored_articles.sort(key=lambda x: x['score'], reverse=True)
    processed_articles = []
    processed_titles_set = set()
    SCORE_THRESHOLD = 100
    SIMILARITY_THRESHOLD = 0.8
    
    print(f"\n--- {SCORE_THRESHOLD}점 이상 기사 선별 및 (1차)제목 중복 제거 ---")
    for article_data in scored_articles:
        score = article_data['score']
        art_meta = article_data['meta']
        article_obj = article_data['article_obj']
        proc_title = art_meta.get('title', '')
        if score < SCORE_THRESHOLD:
            continue
        is_duplicate = False
        for processed_title in processed_titles_set:
            similarity = difflib.SequenceMatcher(None, proc_title, processed_title).ratio()
            if similarity > SIMILARITY_THRESHOLD:
                is_duplicate = True
                print(f"     [1차 중복 감지] (점수: {score:.1f}) {proc_title[:50]}... (유사도: {similarity*100:.0f}%)")
                break
        if not is_duplicate:
            print(f"[OK] (점수: {score:.1f}) 기사 처리 중: {art_meta.get('site')} | {proc_title}")
            processed_titles_set.add(proc_title)
            text_ko = translate_text(article_obj.text)
            summary_ko = summarize_with_chatgpt(text_ko)
            if not summary_ko:
                summary_ko = summarize_korean_text_basic(text_ko)
            processed_articles.append({
                'date': pd.to_datetime(art_meta.get('publishedDate')).strftime('%Y-%m-%d %H:%M') if art_meta.get('publishedDate') else '',
                'site': art_meta.get('site'),
                'url': art_meta.get('url'),
                'title_ko': translate_text(article_obj.title),
                'summary_ko': summary_ko
            })
    
    # 100점 이상 기사가 없으면 점수 상관없이 상위 기사 반환 (테스트 단계)
    if not processed_articles:
        print("[WARN] 100점 이상인 유효한 기사가 없습니다. 점수 상관없이 상위 기사 반환 중...")
        processed_titles_set = set()
        for article_data in scored_articles[:5]:  # 상위 5개만
            score = article_data['score']
            art_meta = article_data['meta']
            article_obj = article_data['article_obj']
            proc_title = art_meta.get('title', '')
            
            is_duplicate = False
            for processed_title in processed_titles_set:
                similarity = difflib.SequenceMatcher(None, proc_title, processed_title).ratio()
                if similarity > SIMILARITY_THRESHOLD:
                    is_duplicate = True
                    break
            if not is_duplicate:
                print(f"[OK] (점수: {score:.1f}) 기사 처리 중: {art_meta.get('site')} | {proc_title}")
                processed_titles_set.add(proc_title)
                text_ko = translate_text(article_obj.text)
                summary_ko = summarize_with_chatgpt(text_ko)
                if not summary_ko:
                    summary_ko = summarize_korean_text_basic(text_ko)
                processed_articles.append({
                    'date': pd.to_datetime(art_meta.get('publishedDate')).strftime('%Y-%m-%d %H:%M') if art_meta.get('publishedDate') else '',
                    'site': art_meta.get('site'),
                    'url': art_meta.get('url'),
                    'title_ko': translate_text(article_obj.title),
                    'summary_ko': summary_ko
                })
    
    return processed_articles

# 뉴스 API 엔드포인트
@app.route('/api/stock/<symbol>/news', methods=['GET'])
def get_stock_news_api(symbol):
    """주식 뉴스 조회 API"""
    try:
        # 심볼 정리
        clean_symbol = symbol.replace('.KS', '').replace('.KQ', '').upper()
        
        # 한국 주식인 경우 심볼 변환 필요 없음
        if len(clean_symbol) == 6 and clean_symbol.isdigit():
            # 한국 주식은 FMP에서 지원하지 않을 수 있음
            return jsonify({'news': []})
        
        # ChromaDB에서 미리 정리된 뉴스 우선 조회
        news_from_chroma = []
        try:
            news_from_chroma = fetch_us_stock_news(clean_symbol, limit=3)
        except Exception as chroma_error:
            print(f"[WARN] Chroma 뉴스 조회 실패: {chroma_error}")

        if news_from_chroma:
            print(f"[INFO] Chroma에서 {len(news_from_chroma)}개 뉴스 가져옴 ({clean_symbol})")
            response_items = []
            for item in news_from_chroma:
                # 날짜 필드: date > published_at > date_int 변환
                date_str = item.get('date') or item.get('published_at') or ''
                if not date_str and item.get('date_int'):
                    # date_int를 날짜 문자열로 변환 (예: 20251024 -> 2025-10-24)
                    try:
                        date_int_str = str(item.get('date_int'))
                        if len(date_int_str) == 8:
                            date_str = f"{date_int_str[:4]}-{date_int_str[4:6]}-{date_int_str[6:8]}"
                    except:
                        pass
                
                response_items.append(
                    {
                        'title': item.get('title') or '',
                        'summary': item.get('summary') or '',
                        'url': item.get('url') or '',
                        'date': date_str,
                        'site': item.get('source') or item.get('site') or '',
                    }
                )
            print(f"[DEBUG] US news response items: {len(response_items)}개")
            return jsonify({'news': response_items})

        # 폴백: 기존 FMP 로직
        print(f'\n--- [INFO] {clean_symbol} 뉴스 분석 시작 (FMP 폴백) ---')
        ticker_names = [clean_symbol]
        news_list = get_fmp_stock_news(clean_symbol, FMP_API_KEY, limit=NEWS_LIMIT)
        
        if not news_list:
            print(f"[WARN] {clean_symbol}에 대한 FMP 뉴스가 없습니다.")
            return jsonify({'news': []})
        
        print(f"[INFO] FMP에서 {len(news_list)}개 뉴스 수집 완료")
        
        # 100점 이상 기사 선별, 번역, ChatGPT 요약 (없으면 점수 상관없이 상위 기사 반환)
        best_articles = find_and_process_high_scoring_articles(news_list, ticker_names)
        
        if not best_articles:
            print(f"[WARN] {clean_symbol}에 대한 뉴스 기사를 찾을 수 없습니다. (필터링 후 0개)")
            # 원본 뉴스 중 상위 5개를 간단히 반환 (번역 없이)
            print(f"[INFO] 원본 뉴스 {min(5, len(news_list))}개 반환 시도")
            processed_news = []
            for article in news_list[:5]:
                title = article.get('title', '')
                published_date = article.get('publishedDate', '')
                site = article.get('site', '')
                url = article.get('url', '')
                
                # 날짜 포맷팅
                date_str = ''
                if published_date:
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(published_date.replace('Z', '+00:00'))
                        date_str = dt.strftime('%Y-%m-%d %H:%M')
                    except:
                        date_str = published_date[:10] if len(published_date) >= 10 else published_date
                
                processed_news.append({
                    'title': title,
                    'summary': article.get('text', '')[:200] + '...' if article.get('text') else '',
                    'url': url,
                    'date': date_str,
                    'site': site or 'Unknown'
                })
            
            if processed_news:
                print(f"[OK] 원본 뉴스 {len(processed_news)}개 반환")
                return jsonify({'news': processed_news})
            else:
                return jsonify({'news': []})
        
        # 최대 10개 반환 (기존 5개에서 증가)
        processed_news = []
        for article in best_articles[:10]:
            processed_news.append({
                'title': article.get('title_ko', ''),
                'summary': article.get('summary_ko', ''),
                'url': article.get('url', ''),
                'date': article.get('date', ''),
                'site': article.get('site', '')
            })
        
        print(f"[OK] 처리된 뉴스 {len(processed_news)}개 반환")
        return jsonify({'news': processed_news})
    except Exception as e:
        print(f'뉴스 API 오류: {e}')
        return jsonify({'news': []})

# 한국 주식 뉴스 API 엔드포인트
@app.route('/api/kr-stock/<symbol>/news', methods=['GET'])
def get_kr_stock_news(symbol):
    """한국 주식 뉴스 조회 API (ChromaDB 우선, 네이버 뉴스 폴백, FMP 폴백)"""
    try:
        # 심볼 정리 (.KS 제거)
        clean_symbol = symbol.replace('.KS', '').replace('.KQ', '')
        
        if not clean_symbol.isdigit() or len(clean_symbol) != 6:
            return jsonify({'error': '올바른 심볼 코드가 아닙니다.'}), 400
        
        # ChromaDB에서 미리 정리된 뉴스 우선 조회
        news_from_chroma = []
        try:
            news_from_chroma = fetch_kr_stock_news(clean_symbol, limit=10)
        except Exception as chroma_error:
            print(f"[WARN] Chroma 뉴스 조회 실패 (KR): {chroma_error}")
        
        if news_from_chroma:
            print(f"[INFO] Chroma에서 {len(news_from_chroma)}개 뉴스 가져옴 (KR: {clean_symbol})")
            response_items = []
            for item in news_from_chroma:
                response_items.append(
                    {
                        'title': item.get('title') or '',
                        'summary': item.get('summary') or '',
                        'url': item.get('url') or '',
                        'date': item.get('date') or item.get('published_at') or '',
                        'site': item.get('source') or '',
                    }
                )
            return jsonify({'news': response_items})
        
        # 회사명 가져오기 (캐시 사용)
        krx_list = get_krx_list_cached()
        company_name = clean_symbol
        if krx_list is not None and not krx_list.empty:
            symbol_col = 'Code' if 'Code' in krx_list.columns else ('Symbol' if 'Symbol' in krx_list.columns else None)
            name_col = 'Name' if 'Name' in krx_list.columns else '종목명'
            if symbol_col:
                company_info = krx_list[krx_list[symbol_col] == clean_symbol]
                if not company_info.empty:
                    company_name = company_info.iloc[0][name_col]
        
        # 뉴스 정보 가져오기
        news = []
        
        # 1. 네이버 뉴스 우선 시도
        if NAVER_CLIENT_ID and NAVER_CLIENT_SECRET:
            try:
                print(f'\n--- [INFO] {company_name} ({clean_symbol}) 네이버 뉴스 수집 시작 ---')
                # 정확도 우선
                naver_news = collect_naver_news(company_name, sort="sim")
                
                # 부족하면 최신순 보충
                if len(naver_news) < NAVER_NEWS_TARGET_COUNT:
                    print(f'[INFO] 네이버 뉴스 {len(naver_news)}개 찾음, 최신순 보충 중...')
                    extra_news = collect_naver_news(company_name, sort="date")
                    existed_urls = set(n['url'] for n in naver_news)
                    for n in extra_news:
                        if n['url'] not in existed_urls:
                            naver_news.append(n)
                        if len(naver_news) >= NAVER_NEWS_TARGET_COUNT:
                            break
                
                if naver_news:
                    news = naver_news[:NAVER_NEWS_TARGET_COUNT]
                    print(f'[OK] 네이버 뉴스 {len(news)}개 수집 완료')
                else:
                    print(f'[WARN] 네이버 뉴스 0개 수집됨')
            except Exception as e:
                print(f'[ERROR] 네이버 뉴스 조회 오류: {e}')
                import traceback
                traceback.print_exc()
        else:
            print(f'[WARN] 네이버 API 키가 설정되지 않음 (CLIENT_ID: {bool(NAVER_CLIENT_ID)}, CLIENT_SECRET: {bool(NAVER_CLIENT_SECRET)})')
        
        # 2. 네이버 뉴스가 없거나 부족하면 FMP 뉴스로 보충
        if len(news) < 5:
            try:
                print(f'\n--- [INFO] {company_name} ({clean_symbol}) FMP 뉴스 보충 시도 ---')
                ticker_names = [company_name, clean_symbol]
                # 한국 주식은 .KS를 붙여서 FMP에 요청
                kr_symbol_fmp = f"{clean_symbol}.KS"
                news_list = get_fmp_stock_news(kr_symbol_fmp, FMP_API_KEY, limit=NEWS_LIMIT)
                
                if news_list:
                    print(f'[INFO] FMP에서 {len(news_list)}개 뉴스 수집')
                    best_articles = find_and_process_high_scoring_articles(news_list, ticker_names)
                    
                    if best_articles:
                        print(f'[INFO] FMP 뉴스 필터링 후 {len(best_articles)}개 기사')
                        existed_urls = set(n.get('url', '') for n in news)
                        for article in best_articles:
                            article_url = article.get('url', '')
                            if article_url and article_url not in existed_urls:
                                news.append({
                                    'title': article.get('title_ko', ''),
                                    'summary': article.get('summary_ko', ''),
                                    'url': article_url,
                                    'date': article.get('date', ''),
                                    'site': article.get('site', '')
                                })
                            if len(news) >= 10:
                                break
                    else:
                        print(f'[WARN] FMP 뉴스 필터링 후 0개 기사')
                else:
                    print(f'[WARN] FMP 뉴스 없음')
            except Exception as e:
                print(f'[ERROR] FMP 뉴스 조회 오류: {e}')
                import traceback
                traceback.print_exc()
        
        print(f'[INFO] 최종 뉴스 개수: {len(news)}개')
        return jsonify({'news': news[:10]})  # 최대 10개 반환
    except Exception as e:
        print(f'[ERROR] 한국 주식 뉴스 API 오류: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'news': []})

# ============ 세그먼트 분석 유틸 함수 ============
def extract_segment_revenue_recursively(
    data: Union[Dict, List],
    min_revenue_threshold: int = 1_000_000,
    segment_data: Optional[Dict[str, int]] = None
) -> Dict[str, int]:
    """재귀적으로 세그먼트 매출 데이터 추출"""
    if segment_data is None:
        segment_data = {}
    if isinstance(data, dict):
        for key, value in data.items():
            lower_key = str(key).lower()
            # 날짜/메타 필드 스킵
            if any(sub in lower_key for sub in [
                'date','year','id','total','sum','all','percentage','share','ratio',
                'filingdate','fillingdate','revenue_amount','asofdate','reported'
            ]):
                if isinstance(value, (dict, list)):
                    extract_segment_revenue_recursively(value, min_revenue_threshold, segment_data)
                continue
            if isinstance(value, (int, float)) and isinstance(key, str):
                if abs(value) >= min_revenue_threshold:
                    segment_data[key] = int(value)
            elif isinstance(value, (dict, list)):
                extract_segment_revenue_recursively(value, min_revenue_threshold, segment_data)
    elif isinstance(data, list):
        for item in data:
            extract_segment_revenue_recursively(item, min_revenue_threshold, segment_data)
    return segment_data

def normalize_segment_data(raw: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """세그먼트 데이터 정규화"""
    latest_date = None
    # 날짜 추출 시도
    for it in raw:
        if isinstance(it, dict):
            date_keys = ['date', 'fillingDate', 'filingDate', 'asOfDate', 'reportedDate', 'calendarYear']
            for dk in date_keys:
                if dk in it:
                    try:
                        dt = pd.to_datetime(it[dk], errors="coerce")
                        if pd.notna(dt):
                            if latest_date is None or dt > pd.to_datetime(latest_date):
                                latest_date = str(dt.date())
                    except:
                        pass
    
    has_rows = [it for it in raw if isinstance(it, dict)]
    count_struct = sum(1 for it in has_rows if ('category' in it or 'segment' in it) and ('revenue' in it))
    
    # 구조화된 데이터 (category/segment 필드 있음)
    if count_struct >= max(1, len(has_rows)//4):
        rows = []
        for it in has_rows:
            cat = it.get("category") or it.get("segment") or it.get("name") or it.get("type")
            rev = it.get("revenue")
            if cat is None or rev is None:
                continue
            try:
                rev = float(rev)
            except:
                continue
            rows.append({'segment': str(cat), 'revenue': rev})
        
        if rows:
            # 그룹화 및 합계
            df = pd.DataFrame(rows)
            df = df.groupby("segment", as_index=False)["revenue"].sum()
            total = df["revenue"].sum()
            if total <= 0:
                return [], latest_date
            df["percentage"] = df["revenue"] / total * 100.0
            df = df.sort_values("revenue", ascending=False).reset_index(drop=True)
            return df.to_dict('records'), latest_date
    
    # 비구조화된 데이터 (재귀 추출)
    seg_map = extract_segment_revenue_recursively(raw, min_revenue_threshold=1_000_000)
    if not seg_map:
        return [], latest_date
    
    df = pd.DataFrame(list(seg_map.items()), columns=["segment", "revenue"])
    df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce").fillna(0)
    df = df[df["revenue"] > 0]
    total = df["revenue"].sum()
    if total <= 0:
        return [], latest_date
    df["percentage"] = df["revenue"] / total * 100.0
    df = df.sort_values("revenue", ascending=False).reset_index(drop=True)
    return df.to_dict('records'), latest_date

def get_reported_currency(ticker: str) -> str:
    """보고 통화 가져오기"""
    try:
        url = f"https://financialmodelingprep.com/api/v3/income-statement/{ticker}"
        params = {"period": "quarter", "limit": 1, "apikey": FMP_API_KEY}
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data and isinstance(data, list) and len(data) > 0:
                cur = data[0].get("reportedCurrency") or data[0].get("currency")
                if cur:
                    return cur.upper()
    except:
        pass
    return "USD"

def fetch_segment_data(ticker: str) -> Optional[Dict[str, Any]]:
    """세그먼트 데이터 빠르게 가져오기 (타임아웃 짧게)"""
    try:
        url = "https://financialmodelingprep.com/api/v4/revenue-product-segmentation"
        params = {"symbol": ticker, "period": "quarter", "apikey": FMP_API_KEY}
        print(f'[INFO] 세그먼트 데이터 요청: {ticker}')
        response = requests.get(url, params=params, timeout=5)  # 타임아웃 5초로 증가
        
        if response.status_code != 200:
            print(f'[ERROR] 세그먼트 API 응답 오류: {response.status_code}')
            return None
        
        data = response.json()
        if not data:
            print(f'[WARN] 세그먼트 데이터가 비어있음: {ticker}')
            return None
        
        print(f'[INFO] 세그먼트 원본 데이터 수: {len(data) if isinstance(data, list) else "dict"}')
        segments, date_str = normalize_segment_data(data)
        
        if not segments:
            print(f'[WARN] 세그먼트 데이터 정규화 실패: {ticker}')
            return None
        
        print(f'[OK] 세그먼트 정규화 성공: {len(segments)}개')
        currency = get_reported_currency(ticker)
        
        return {
            'segments': segments,
            'date': date_str,
            'currency': currency
        }
    except requests.exceptions.Timeout:
        print(f'[TIMEOUT] 세그먼트 데이터 조회 타임아웃: {ticker}')
        return None
    except Exception as e:
        print(f'[ERROR] 세그먼트 데이터 조회 오류: {ticker} - {type(e).__name__}: {str(e)}')
        import traceback
        traceback.print_exc()
        return None

# 재무제표 API 엔드포인트
@app.route('/api/stock/<symbol>/financials', methods=['GET'])
def get_stock_financials(symbol):
    """주식 재무제표 조회 API"""
    try:
        # 심볼 정리
        clean_symbol = symbol.replace('.KS', '').replace('.KQ', '').upper()
        
        # 한국 주식인 경우 - DART API 사용
        if len(clean_symbol) == 6 and clean_symbol.isdigit():
            # DART API로 재무제표 가져오기
            if DART_API_KEY:
                try:
                    corp_code = find_dart_corp_code(clean_symbol)
                    if corp_code:
                        financials = get_dart_financials(corp_code, clean_symbol)
                        if financials:
                            return jsonify(financials)
                except Exception as e:
                    print(f'DART API 재무제표 조회 오류: {e}')
            
            # DART 실패 시 FMP API로 폴백
            try:
                kr_symbol = f"{clean_symbol}.KS"
                url = f"https://financialmodelingprep.com/api/v3/income-statement/{kr_symbol}?period=quarter&limit=4&apikey={FMP_API_KEY}"
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                income_statements = response.json()
                
                if isinstance(income_statements, dict) and 'Error Message' in income_statements:
                    raise Exception("FMP API에서 데이터를 찾을 수 없습니다.")
                
                if not income_statements or len(income_statements) == 0:
                    return jsonify({
                        'revenue': [],
                        'netIncome': [],
                        'operatingIncome': [],
                        'chartData': []
                    })
                
                # FMP 데이터 파싱
                chart_data = []
                revenue_data = []
                net_income_data = []
                operating_income_data = []
                
                for statement in reversed(income_statements):
                    year = statement.get('calendarYear', '')
                    quarter = statement.get('quarter', '')
                    revenue = statement.get('revenue', 0) or 0
                    net_income = statement.get('netIncome', 0) or 0
                    operating_income = statement.get('operatingIncome', 0) or 0
                    
                    if year and quarter:
                        label = f"{year} Q{quarter}"
                    else:
                        label = year if year else ''
                    
                    if label:
                        chart_data.append({
                            'year': label,
                            'revenue': revenue,
                            'netIncome': net_income,
                            'operatingIncome': operating_income
                        })
                        revenue_data.append({'year': label, 'value': revenue})
                        net_income_data.append({'year': label, 'value': net_income})
                        operating_income_data.append({'year': label, 'value': operating_income})
                
                latest = income_statements[0] if income_statements else {}
                latest_year = latest.get('calendarYear', '')
                latest_quarter = latest.get('quarter', '')
                latest_label = f"{latest_year} Q{latest_quarter}" if latest_year and latest_quarter else latest_year
                
                # 세그먼트 데이터 병렬로 가져오기 (선택적, 실패해도 무방)
                segment_data = None
                try:
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(fetch_segment_data, kr_symbol)
                        try:
                            segment_data = future.result(timeout=5)  # 타임아웃 5초로 증가
                            if segment_data:
                                print(f'[OK] 세그먼트 데이터 수집 성공: {kr_symbol} ({len(segment_data.get("segments", []))}개 세그먼트)')
                            else:
                                print(f'[WARN] 세그먼트 데이터 없음: {kr_symbol}')
                        except Exception as e:
                            print(f'[WARN] 세그먼트 데이터 조회 실패: {kr_symbol} - {str(e)}')
                except Exception as e:
                    print(f'[WARN] 세그먼트 데이터 조회 오류: {kr_symbol} - {str(e)}')
                
                result = {
                    'revenue': revenue_data,
                    'netIncome': net_income_data,
                    'operatingIncome': operating_income_data,
                    'chartData': chart_data,
                    'latest': {
                        'revenue': latest.get('revenue', 0) or 0,
                        'netIncome': latest.get('netIncome', 0) or 0,
                        'operatingIncome': latest.get('operatingIncome', 0) or 0,
                        'year': latest_label
                    }
                }
                
                # 세그먼트 데이터가 있으면 추가
                if segment_data:
                    result['segments'] = segment_data['segments']
                    result['segmentDate'] = segment_data['date']
                    result['segmentCurrency'] = segment_data['currency']
                
                return jsonify(result)
            except Exception as e:
                print(f'FMP 폴백 오류: {e}')
                return jsonify({
                    'revenue': [],
                    'netIncome': [],
                    'operatingIncome': [],
                    'chartData': []
                })
        
        # 해외 주식 재무제표 가져오기 (FMP API)
        try:
            chroma_financials = fetch_us_financials_from_chroma(clean_symbol)
            if chroma_financials:
                print(f'[INFO] ChromaDB 재무 데이터 사용: {clean_symbol}')
                return jsonify(chroma_financials)
        except Exception as e:
            print(f'[WARN] ChromaDB 재무 데이터 조회 실패: {clean_symbol} - {e}')

        try:
            # 분기별 재무제표 데이터
            url = f"https://financialmodelingprep.com/api/v3/income-statement/{clean_symbol}?period=quarter&limit=4&apikey={FMP_API_KEY}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            income_statements = response.json()
            
            if not income_statements or len(income_statements) == 0:
                return jsonify({
                    'revenue': [],
                    'netIncome': [],
                    'operatingIncome': [],
                    'chartData': []
                })
            
            # 데이터 정리 및 차트용 데이터 생성
            chart_data = []
            revenue_data = []
            net_income_data = []
            operating_income_data = []
            
            for statement in reversed(income_statements):  # 최신순으로 정렬
                # 분기별 데이터 처리
                year = statement.get('calendarYear', '')
                period = statement.get('period', '')
                quarter = statement.get('quarter', '')
                revenue = statement.get('revenue', 0) or 0
                net_income = statement.get('netIncome', 0) or 0
                operating_income = statement.get('operatingIncome', 0) or 0
                
                # 분기 레이블 생성 (예: 2024 Q1)
                if year and quarter:
                    label = f"{year} Q{quarter}"
                elif year and period:
                    label = f"{year} {period}"
                else:
                    label = year if year else ''
                
                if label:
                    chart_data.append({
                        'year': label,
                        'revenue': revenue,
                        'netIncome': net_income,
                        'operatingIncome': operating_income
                    })
                    revenue_data.append({'year': label, 'value': revenue})
                    net_income_data.append({'year': label, 'value': net_income})
                    operating_income_data.append({'year': label, 'value': operating_income})
            
            # 최신 데이터
            latest = income_statements[0] if income_statements else {}
            
            # 세그먼트 데이터 병렬로 가져오기 (선택적, 실패해도 무방)
            segment_data = None
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(fetch_segment_data, clean_symbol)
                    try:
                        segment_data = future.result(timeout=5)  # 타임아웃 5초로 증가
                        if segment_data:
                            print(f'[OK] 세그먼트 데이터 수집 성공: {clean_symbol} ({len(segment_data.get("segments", []))}개 세그먼트)')
                        else:
                            print(f'[WARN] 세그먼트 데이터 없음: {clean_symbol}')
                    except Exception as e:
                        print(f'[WARN] 세그먼트 데이터 조회 실패: {clean_symbol} - {str(e)}')
            except Exception as e:
                print(f'[WARN] 세그먼트 데이터 조회 오류: {clean_symbol} - {str(e)}')
            
            result = {
                'revenue': revenue_data,
                'netIncome': net_income_data,
                'operatingIncome': operating_income_data,
                'chartData': chart_data,
                'latest': {
                    'revenue': latest.get('revenue', 0) or 0,
                    'netIncome': latest.get('netIncome', 0) or 0,
                    'operatingIncome': latest.get('operatingIncome', 0) or 0,
                    'year': latest.get('calendarYear', '')
                }
            }
            
            # 세그먼트 데이터가 있으면 추가
            if segment_data:
                result['segments'] = segment_data['segments']
                result['segmentDate'] = segment_data['date']
                result['segmentCurrency'] = segment_data['currency']
            
            return jsonify(result)
        except Exception as e:
            print(f'FMP 재무제표 API 오류: {e}')
            return jsonify({
                'revenue': [],
                'netIncome': [],
                'operatingIncome': [],
                'chartData': []
            })
    except Exception as e:
        print(f'재무제표 API 오류: {e}')
        return jsonify({
            'revenue': [],
            'netIncome': [],
            'operatingIncome': [],
            'chartData': []
        })

# DART API 단일 조회 함수 (병렬 처리용)
def fetch_dart_quarter_data(corp_code, year, reprt_code, quarter, fs_div):
    """단일 분기/타입의 DART 재무제표 데이터 조회"""
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcnt.json"
    
    try:
        params = {
            'crtfc_key': DART_API_KEY,
            'corp_code': corp_code,
            'bsns_year': str(year),
            'reprt_code': reprt_code,
            'fs_div': fs_div
        }
        
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        status = data.get('status')
        if status != '000':
            return None
        
        account_list = data.get('list', [])
        if not account_list:
            return None
        
        revenue = 0
        operating_income = 0
        net_income = 0
        
        # 모든 계정에서 매출액, 영업이익, 당기순이익 찾기
        for account in account_list:
            account_nm = account.get('account_nm', '')
            account_id = account.get('account_id', '')
            thstrm_amount = account.get('thstrm_amount', '0')
            
            try:
                amount_str = thstrm_amount.replace(',', '') if thstrm_amount else '0'
                amount = float(amount_str) if amount_str else 0
            except:
                amount = 0
            
            if amount == 0:
                continue
            
            # 매출액 찾기
            if ('매출액' in account_nm or '매출' in account_nm) and '감가상각비' not in account_nm:
                if abs(amount) > abs(revenue) or revenue == 0:
                    revenue = amount
            
            # 영업이익 찾기
            elif '영업이익' in account_nm or account_id == 'ifrs-full_OperatingIncomeLoss':
                if abs(amount) > abs(operating_income) or operating_income == 0:
                    operating_income = amount
            
            # 당기순이익 찾기
            elif ('당기순이익' in account_nm or '순이익' in account_nm) and '종속기업' not in account_nm:
                if abs(amount) > abs(net_income) or net_income == 0:
                    net_income = amount
        
        if revenue != 0 or operating_income != 0 or net_income != 0:
            return {
                'year': year,
                'quarter': quarter,
                'reprt_code': reprt_code,
                'fs_div': fs_div,
                'revenue': revenue,
                'operating_income': operating_income,
                'net_income': net_income
            }
        
        return None
    except Exception as e:
        return None

# DART Open API로 한국 주식 재무제표 가져오기 (병렬 처리)
def get_dart_financials(corp_code, symbol):
    """DART Open API로 재무제표 데이터 가져오기 (병렬 처리)"""
    if not DART_API_KEY:
        return None
    
    try:
        current_year = datetime.now().year
        
        # 최근 4분기 재무제표 조회
        chart_data = []
        revenue_data = []
        net_income_data = []
        operating_income_data = []
        
        # 분기 코드 매핑: 1분기(11013), 반기(11012), 3분기(11014), 사업보고서(11011)
        reprt_codes = [
            ('11013', 1),  # 1분기
            ('11012', 2),  # 반기
            ('11014', 3),  # 3분기
            ('11011', 4)   # 사업보고서
        ]
        
        # 최신 분기부터 우선순위로 작업 준비 (CFS 우선, 없으면 OFS)
        # 최신 연도부터, 최신 분기부터 역순으로
        tasks_priority = []
        for year_offset in range(2):
            year = current_year - year_offset
            # 최신 분기부터 역순 (Q4 → Q3 → Q2 → Q1)
            for reprt_code, quarter in reversed(reprt_codes):
                # CFS 우선
                tasks_priority.append((year, reprt_code, quarter, 'CFS', True))  # True = 우선순위
        
        print(f'빠른 조회 시작: 최신 분기부터 우선순위 조회 (CFS 우선)')
        
        # 병렬 처리로 조회 실행
        collected_data = {}  # (year, quarter)를 키로 사용하여 중복 제거
        
        with ThreadPoolExecutor(max_workers=8) as executor:
            # 우선순위 작업부터 제출 (CFS만 먼저)
            futures_cfs = {}
            for year, reprt_code, quarter, fs_div, _ in tasks_priority:
                future = executor.submit(fetch_dart_quarter_data, corp_code, year, reprt_code, quarter, fs_div)
                futures_cfs[future] = (year, quarter, fs_div)
            
            # CFS 결과 처리
            for future in as_completed(futures_cfs):
                year, quarter, fs_div = futures_cfs[future]
                try:
                    result = future.result()
                    if result:
                        key = (result['year'], result['quarter'])
                        collected_data[key] = result
                        print(f'데이터 추출: {result["year"]} Q{result["quarter"]} ({result["fs_div"]}) - 매출액: {result["revenue"]:,.0f}, 영업이익: {result["operating_income"]:,.0f}, 당기순이익: {result["net_income"]:,.0f}')
                        
                        # 4개 분기 수집되면 즉시 중단
                        if len(collected_data) >= 4:
                            # 남은 CFS 작업 취소
                            for f in futures_cfs:
                                if not f.done():
                                    f.cancel()
                            break
                except Exception as e:
                    continue
            
            # CFS에서 4개를 못 찾았으면 OFS로 보완
            if len(collected_data) < 4:
                missing_quarters = []
                for year_offset in range(2):
                    year = current_year - year_offset
                    for reprt_code, quarter in reversed(reprt_codes):
                        key = (year, quarter)
                        if key not in collected_data:
                            missing_quarters.append((year, reprt_code, quarter))
                
                if missing_quarters:
                    print(f'CFS에서 {len(collected_data)}개 찾음, OFS로 보완 시도 중...')
                    futures_ofs = {}
                    for year, reprt_code, quarter in missing_quarters[:8]:  # 최대 8개만
                        future = executor.submit(fetch_dart_quarter_data, corp_code, year, reprt_code, quarter, 'OFS')
                        futures_ofs[future] = (year, quarter, 'OFS')
                    
                    for future in as_completed(futures_ofs):
                        year, quarter, fs_div = futures_ofs[future]
                        try:
                            result = future.result()
                            if result:
                                key = (result['year'], result['quarter'])
                                if key not in collected_data:  # CFS에 없는 경우만 추가
                                    collected_data[key] = result
                                    print(f'데이터 추출 (OFS): {result["year"]} Q{result["quarter"]} - 매출액: {result["revenue"]:,.0f}, 영업이익: {result["operating_income"]:,.0f}, 당기순이익: {result["net_income"]:,.0f}')
                                    
                                    if len(collected_data) >= 4:
                                        for f in futures_ofs:
                                            if not f.done():
                                                f.cancel()
                                        break
                        except Exception as e:
                            continue
        
        # 수집된 데이터를 시간순으로 정렬
        sorted_data = sorted(collected_data.values(), key=lambda x: (x['year'], x['quarter']), reverse=True)[:4]
        
        for data in sorted_data:
            label = f"{data['year']} Q{data['quarter']}"
            chart_data.append({
                'year': label,
                'revenue': data['revenue'],
                'netIncome': data['net_income'],
                'operatingIncome': data['operating_income']
            })
            revenue_data.append({'year': label, 'value': data['revenue']})
            net_income_data.append({'year': label, 'value': data['net_income']})
            operating_income_data.append({'year': label, 'value': data['operating_income']})
        
        if not chart_data:
            print(f'DART에서 재무제표를 찾을 수 없습니다: {symbol}')
            return None
        
        # 최신순으로 정렬 (이미 reverse=True로 정렬했으므로 다시 reverse)
        chart_data.reverse()
        revenue_data.reverse()
        net_income_data.reverse()
        operating_income_data.reverse()
        
        # 최신 데이터
        latest = chart_data[-1] if chart_data else {}
        
        return {
            'revenue': revenue_data,
            'netIncome': net_income_data,
            'operatingIncome': operating_income_data,
            'chartData': chart_data,
            'latest': {
                'revenue': latest.get('revenue', 0) or 0,
                'netIncome': latest.get('netIncome', 0) or 0,
                'operatingIncome': latest.get('operatingIncome', 0) or 0,
                'year': latest.get('year', '')
            }
        }
    except Exception as e:
        print(f'DART API 오류: {e}')
        import traceback
        traceback.print_exc()
        return None

# DART 회사코드 ZIP 파일 캐시 경로
# 캐시 디렉토리 설정 (프로젝트 루트 기준)
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'cache')
# 캐시 디렉토리가 없으면 생성
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR, exist_ok=True)
    print(f'캐시 디렉토리 생성: {CACHE_DIR}')

DART_CORPCODE_CACHE_FILE = os.path.join(CACHE_DIR, 'dart_corpcode_cache.zip')
DART_CORPCODE_CACHE_AGE_DAYS = 7  # 7일마다 갱신

# KRX 리스트 캐시 (전역 변수)
KRX_LIST_CACHE = None
KRX_LIST_CACHE_TIME = None
KRX_LIST_CACHE_AGE_SECONDS = 3600  # 1시간마다 갱신

def get_krx_list_cached():
    """KRX 리스트를 캐시하여 빠르게 반환"""
    global KRX_LIST_CACHE, KRX_LIST_CACHE_TIME
    from datetime import datetime, timedelta
    
    # 캐시가 있고 유효하면 반환
    if KRX_LIST_CACHE is not None and KRX_LIST_CACHE_TIME is not None:
        cache_age = (datetime.now() - KRX_LIST_CACHE_TIME).total_seconds()
        if cache_age < KRX_LIST_CACHE_AGE_SECONDS:
            print(f'KRX 리스트 캐시 사용 (캐시 나이: {cache_age:.0f}초)')
            return KRX_LIST_CACHE
    
    # 캐시가 없거나 오래되었으면 새로 다운로드
    print('KRX 리스트 다운로드 중...')
    try:
        KRX_LIST_CACHE = fdr.StockListing('KRX')
        KRX_LIST_CACHE_TIME = datetime.now()
        print(f'KRX 리스트 다운로드 완료: {len(KRX_LIST_CACHE) if KRX_LIST_CACHE is not None else 0}개 종목')
        return KRX_LIST_CACHE
    except Exception as e:
        print(f'KRX 리스트 다운로드 오류: {e}')
        return None

def download_dart_corpcode_file():
    """DART 회사코드 ZIP 파일 다운로드 및 저장"""
    if not DART_API_KEY:
        return None
    
    try:
        url = "https://opendart.fss.or.kr/api/corpCode.xml"
        params = {
            'crtfc_key': DART_API_KEY
        }
        
        print('DART 회사코드 ZIP 파일 다운로드 중...')
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        
        # ZIP 파일 저장
        with open(DART_CORPCODE_CACHE_FILE, 'wb') as f:
            f.write(response.content)
        
        print(f'DART 회사코드 ZIP 파일 저장 완료: {DART_CORPCODE_CACHE_FILE}')
        return response.content
    except Exception as e:
        print(f'DART 회사코드 ZIP 파일 다운로드 오류: {e}')
        return None

def load_dart_corpcode_from_cache():
    """저장된 ZIP 파일에서 회사코드 목록 로드"""
    import os
    import zipfile
    import io
    from datetime import datetime, timedelta
    
    # 캐시 파일이 없으면 다운로드
    if not os.path.exists(DART_CORPCODE_CACHE_FILE):
        print('캐시 파일 없음, 다운로드 시작...')
        download_dart_corpcode_file()
    
    # 캐시 파일이 너무 오래되었으면 갱신
    if os.path.exists(DART_CORPCODE_CACHE_FILE):
        file_age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(DART_CORPCODE_CACHE_FILE))
        if file_age.days > DART_CORPCODE_CACHE_AGE_DAYS:
            print(f'캐시 파일이 {file_age.days}일 경과, 갱신 중...')
            download_dart_corpcode_file()
    
    # 저장된 ZIP 파일 읽기
    try:
        with open(DART_CORPCODE_CACHE_FILE, 'rb') as f:
            zip_content = f.read()
        
        zip_file = zipfile.ZipFile(io.BytesIO(zip_content))
        xml_files = [f for f in zip_file.namelist() if f.endswith('.xml')]
        if not xml_files:
            print('ZIP 파일에 XML 파일이 없습니다.')
            return None
        
        xml_content = zip_file.read(xml_files[0])
        # 인코딩 처리
        try:
            xml_text = xml_content.decode('utf-8')
        except:
            xml_text = xml_content.decode('euc-kr')
        
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_text)
        return root
    except Exception as e:
        print(f'캐시 파일 읽기 오류: {e}')
        # 캐시 파일이 손상되었으면 다시 다운로드
        download_dart_corpcode_file()
        return None

# 종목코드로 DART 회사코드 찾기 (캐시된 ZIP 파일 사용)
def find_dart_corp_code(symbol):
    """종목코드로 DART 회사코드 찾기 (캐시된 파일 사용)"""
    if not DART_API_KEY:
        return None
    
    try:
        # KRX 리스트에서 회사명 가져오기
        krx_list = fdr.StockListing('KRX')
        if krx_list is None or krx_list.empty:
            return None
        
        symbol_col = 'Code' if 'Code' in krx_list.columns else ('Symbol' if 'Symbol' in krx_list.columns else None)
        name_col = 'Name' if 'Name' in krx_list.columns else '종목명'
        
        if not symbol_col:
            return None
        
        company_info = krx_list[krx_list[symbol_col] == symbol]
        if company_info.empty:
            return None
        
        company_name = company_info.iloc[0][name_col]
        print(f'회사명 찾음: {company_name} (종목코드: {symbol})')
        
        # 캐시된 ZIP 파일에서 XML 로드
        root = load_dart_corpcode_from_cache()
        if root is None:
            return None
        
        # 회사명으로 검색
        for corp in root.findall('list'):
            corp_name_elem = corp.find('corp_name')
            corp_code_elem = corp.find('corp_code')
            
            if corp_name_elem is not None and corp_code_elem is not None:
                corp_name = corp_name_elem.text
                if corp_name and company_name in corp_name:
                    corp_code = corp_code_elem.text
                    if corp_code:
                        print(f'DART 회사코드 찾음: {company_name} -> {corp_code}')
                        return corp_code
        
        print(f'DART에서 회사코드를 찾을 수 없음: {company_name}')
        return None
    except Exception as e:
        print(f'DART 회사코드 찾기 오류: {e}')
        import traceback
        traceback.print_exc()
        return None

# 한국 주식 재무제표 API 엔드포인트
@app.route('/api/kr-stock/<symbol>/financials', methods=['GET'])
def get_kr_stock_financials(symbol):
    """한국 주식 재무제표 조회 API (DART API 사용)"""
    try:
        # 심볼 정리 (.KS 제거)
        clean_symbol = symbol.replace('.KS', '').replace('.KQ', '')
        
        if not clean_symbol.isdigit() or len(clean_symbol) != 6:
            return jsonify({'error': '올바른 심볼 코드가 아닙니다.'}), 400

        try:
            chroma_financials = fetch_kr_financials_from_chroma(clean_symbol)
            if chroma_financials:
                print(f'[INFO] ChromaDB 재무 데이터 사용(KR): {clean_symbol}')
                return jsonify(chroma_financials)
        except Exception as e:
            print(f'[WARN] ChromaDB 재무 데이터 조회 실패(KR): {clean_symbol} - {e}')
            import traceback
            traceback.print_exc()
        
        # DART API로 재무제표 가져오기
        if DART_API_KEY:
            try:
                corp_code = find_dart_corp_code(clean_symbol)
                if corp_code:
                    print(f'DART 회사코드 찾음: {clean_symbol} -> {corp_code}')
                    financials = get_dart_financials(corp_code, clean_symbol)
                    if financials:
                        print(f'DART 재무제표 조회 성공: {clean_symbol}')
                        return jsonify(financials)
                    else:
                        print(f'DART 재무제표 데이터 없음: {clean_symbol}')
                else:
                    print(f'DART 회사코드를 찾을 수 없음: {clean_symbol}')
            except Exception as e:
                print(f'DART API 재무제표 조회 오류: {e}')
                import traceback
                traceback.print_exc()
        
        # DART 실패 시 FMP API로 폴백 (대형주만 지원)
        print(f'FMP API로 폴백 시도: {clean_symbol}')
        try:
            kr_symbol = f"{clean_symbol}.KS"
            url = f"https://financialmodelingprep.com/api/v3/income-statement/{kr_symbol}?period=quarter&limit=4&apikey={FMP_API_KEY}"
            print(f'FMP API 호출: {url[:80]}...')
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            income_statements = response.json()
            print(f'FMP API 응답: {len(income_statements) if isinstance(income_statements, list) else "dict"}')
            
            if isinstance(income_statements, dict) and 'Error Message' in income_statements:
                raise Exception("FMP API에서 데이터를 찾을 수 없습니다.")
            
            if not income_statements or len(income_statements) == 0:
                return jsonify({
                    'revenue': [],
                    'netIncome': [],
                    'operatingIncome': [],
                    'chartData': []
                })
            
            # FMP 데이터 파싱
            chart_data = []
            revenue_data = []
            net_income_data = []
            operating_income_data = []
            
            for statement in reversed(income_statements):
                year = statement.get('calendarYear', '')
                quarter = statement.get('quarter', '')
                revenue = statement.get('revenue', 0) or 0
                net_income = statement.get('netIncome', 0) or 0
                operating_income = statement.get('operatingIncome', 0) or 0
                
                if year and quarter:
                    label = f"{year} Q{quarter}"
                else:
                    label = year if year else ''
                
                if label:
                    chart_data.append({
                        'year': label,
                        'revenue': revenue,
                        'netIncome': net_income,
                        'operatingIncome': operating_income
                    })
                    revenue_data.append({'year': label, 'value': revenue})
                    net_income_data.append({'year': label, 'value': net_income})
                    operating_income_data.append({'year': label, 'value': operating_income})
            
            latest = income_statements[0] if income_statements else {}
            latest_year = latest.get('calendarYear', '')
            latest_quarter = latest.get('quarter', '')
            latest_label = f"{latest_year} Q{latest_quarter}" if latest_year and latest_quarter else latest_year
            
            return jsonify({
                'revenue': revenue_data,
                'netIncome': net_income_data,
                'operatingIncome': operating_income_data,
                'chartData': chart_data,
                'latest': {
                    'revenue': latest.get('revenue', 0) or 0,
                    'netIncome': latest.get('netIncome', 0) or 0,
                    'operatingIncome': latest.get('operatingIncome', 0) or 0,
                    'year': latest_label
                }
            })
        except Exception as e:
            print(f'FMP 폴백 오류: {e}')
        
        # 모든 방법 실패
        return jsonify({
            'revenue': [],
            'netIncome': [],
            'operatingIncome': [],
            'chartData': []
        })
    except Exception as e:
        print(f'한국 주식 재무제표 API 오류: {e}')
        return jsonify({
            'revenue': [],
            'netIncome': [],
            'operatingIncome': [],
            'chartData': []
        })

@app.route('/api/vision/analyze-image', methods=['POST'])
def analyze_image_route():
    """이미지를 Vision + Gemini로 분석하여 제품/브랜드 정보를 반환"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'file 필드에 이미지를 첨부해주세요.'}), 400

        image_file = request.files['file']
        image_bytes = image_file.read()

        if not image_bytes:
            return jsonify({'error': '빈 이미지입니다.'}), 400

        result = analyze_product_from_image(image_bytes)
        return jsonify(result)
    except Exception as e:
        print(f'[ERROR] Vision 분석 실패: {e}')
        return jsonify({'error': f'이미지 분석 중 오류가 발생했습니다: {e}'}), 500

@app.route('/api/parse-stock-query', methods=['POST'])
def parse_stock_query():
    """입력 문장에서 주식 검색 의도와 거래소/티커 추출"""
    try:
        data = request.json or {}
        user_message = (data.get('message') or '').strip()
        history_entries = data.get('history') or []

        contents = []
        for entry in history_entries:
            try:
                role = entry.get('role')
                text = (entry.get('content') or '').strip()
            except AttributeError:
                continue
            if not text:
                continue
            if role == 'assistant':
                gemini_role = 'model'
            else:
                gemini_role = 'user'
            contents.append({
                "role": gemini_role,
                "parts": [{"text": text}]
            })

        contents.append({
            "role": "user",
            "parts": [{"text": user_message}]
        })

        if not user_message:
            return jsonify({'error': '메시지가 필요합니다.'}), 400

        system_prompt = """역할: 주식/ETF 질의 파서
입력 문장은 한국어·영어 혼용일 수 있다. 출력은 JSON(object) 하나만 반환한다.

필수 필드:
- is_stock_query: true/false
- stock_name: 종목명 문자열 (모르면 null)
- is_korean: true/false/null (한국 상장주인지 여부)
- ticker: 상장 티커 문자열 (모르면 null)
- exchange: 거래소 문자열 (모르면 null)

판단 기준:
1. 문장에 '주가', '주식', '정보', '상황', '어때', '분석', '투자', '가격' 등 주식 관련 키워드가 있으면 기본적으로 is_stock_query=true로 본다.
2. 명시적으로 다른 의도가 보일 때만 is_stock_query=false를 반환한다.
3. 종목명을 추정할 때는 세계 주요 상장사를 폭넓게 고려하고, 한국어 표기를 영어 공식명으로 변환한다.
   - 예: "온다스 홀딩스" → "Ondas Holdings", "레일비전" → "Rail Vision".
4. 한국 상장 기업(한글 기업명, 6자리 숫자, .KS/.KQ 등)이라고 확신될 때만 is_korean=true. 조금이라도 불확실하면 null.
5. 한국 상장사가 아니라고 판단되면 is_korean=false로 두고 stock_name은 반드시 영어 공식명 또는 확실한 티커를 넣는다.
6. ticker, exchange는 확실한 경우만 채운다. 불확실하면 null.
7. 자신이 확신할 수 없으면 stock_name도 null로 두고 is_korean=null, ticker=null, exchange=null을 유지한다.
8. JSON 외 다른 텍스트를 절대 출력하지 않는다.

응답 예시:
{"is_stock_query": true, "stock_name": "Samsung Electronics", "is_korean": true, "ticker": "005930", "exchange": "KRX"}
{"is_stock_query": true, "stock_name": "Tesla", "is_korean": false, "ticker": "TSLA", "exchange": "NASDAQ"}
{"is_stock_query": true, "stock_name": "Ondas Holdings", "is_korean": false, "ticker": "ONDS", "exchange": "NASDAQ"}
{"is_stock_query": true, "stock_name": "Rail Vision", "is_korean": false, "ticker": "RVSN", "exchange": "NASDAQ"}
{"is_stock_query": false, "stock_name": null, "is_korean": null, "ticker": null, "exchange": null}
"""

        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")

        model_name = "gemini-2.5-pro"
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_name}:generateContent"
            f"?key={GEMINI_API_KEY}"
        )
        payload = {
            "contents": contents,
            "system_instruction": {
                "parts": [{"text": system_prompt}]
            },
            "generationConfig": {
                "temperature": 0,
                "topP": 0.1,
                "topK": 1,
                "responseMimeType": "application/json"
            }
        }
        ai_response_raw = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=20
        )
        ai_response_raw.raise_for_status()
        data_json = ai_response_raw.json()
        candidates = data_json.get("candidates", [])
        if not candidates:
            raise ValueError("Gemini 응답에 후보가 없습니다.")

        ai_text = ""
        for part in candidates[0].get("content", {}).get("parts", []):
            if "text" in part:
                ai_text += part["text"]

        result = json.loads(ai_text or "{}")

        # 기본 필드 보정
        if "ticker" not in result:
            result["ticker"] = None
        if "exchange" not in result:
            result["exchange"] = None

        # 한국 주식 판단 시 KRX에서 검증
        if (
            result.get("is_stock_query")
            and result.get("is_korean") is True
            and result.get("stock_name")
        ):
            try:
                check_symbol = search_kr_stock_symbol(result["stock_name"])
            except Exception:
                check_symbol = None

            if check_symbol:
                result["ticker"] = check_symbol
                result["exchange"] = "KRX"
            else:
                result["is_korean"] = False

        print(f"[AI 파서] 입력: {user_message} -> {result}")
        return jsonify(result)
    except json.JSONDecodeError:
        print("[AI 파서] JSON 파싱 실패")
        return jsonify({
            "is_stock_query": False,
            "stock_name": None,
            "is_korean": None,
            "ticker": None,
            "exchange": None
        })
    except requests.RequestException as e:
        print(f"[AI 파서] Gemini 호출 실패: {e}")
        return jsonify({
            "is_stock_query": False,
            "stock_name": None,
            "is_korean": None,
            "ticker": None,
            "exchange": None
        }), 500
    except Exception as e:
        print(f"[AI 파서] 오류: {e}")
        return jsonify({
            "is_stock_query": False,
            "stock_name": None,
            "is_korean": None,
            "ticker": None,
            "exchange": None
        }), 500


@app.route('/api/test/chat', methods=['POST'])
def test_chat():
    """
    Gemini 기본 응답을 확인하기 위한 테스트용 엔드포인트.
    시스템 프롬프트 없이 사용자 입력만 전달한다.
    """
    try:
        data = request.json or {}
        user_message = (data.get('message') or '').strip()

        if not user_message:
            return jsonify({'error': '메시지가 필요합니다.'}), 400

        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")

        model_name = "gemini-2.5-pro"
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_name}:generateContent"
            f"?key={GEMINI_API_KEY}"
        )

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_message}]
                }
            ]
        }

        ai_response = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=20
        )
        ai_response.raise_for_status()
        data_json = ai_response.json()

        candidates = data_json.get("candidates", [])
        if not candidates:
            raise ValueError("Gemini 응답에 후보가 없습니다.")

        reply_text = ""
        for part in candidates[0].get("content", {}).get("parts", []):
            if "text" in part:
                reply_text += part["text"]

        return jsonify({"reply": reply_text.strip()})
    except requests.RequestException as e:
        print(f"[테스트 챗봇] Gemini 호출 실패: {e}")
        return jsonify({"error": "모델 호출에 실패했습니다."}), 500
    except Exception as e:
        print(f"[테스트 챗봇] 오류: {e}")
        return jsonify({"error": "요청 처리 중 오류가 발생했습니다."}), 500


@app.route('/api/market-indices/<market>', methods=['GET'])
def get_market_indices(market):
    """국내/미국 주가지수 데이터 반환"""
    try:
        if market == 'kr':
            # 국내 지수: KOSPI, KOSDAQ, KOSPI200
            indices = ['KS11', 'KQ11', 'KS200']  # FinanceDataReader 코드
            index_names = {
                'KS11': '코스피',
                'KQ11': '코스닥',
                'KS200': '코스피200'
            }
        elif market == 'us':
            # 미국 지수: S&P 500, NASDAQ, Dow Jones
            indices = ['US500', 'IXIC', 'DJI']  # FinanceDataReader 코드
            index_names = {
                'US500': 'S&P 500',
                'IXIC': '나스닥',
                'DJI': '다우존스'
            }
        else:
            return jsonify({'error': 'Invalid market'}), 400
        
        result = []
        today = datetime.now().date()
        
        for idx_code in indices:
            try:
                # 최근 2일 데이터 가져오기 (전일 대비 계산용)
                df = fdr.DataReader(idx_code, today - timedelta(days=5), today)
                
                if df.empty:
                    continue
                
                # 최신 데이터
                latest = df.iloc[-1]
                prev = df.iloc[-2] if len(df) > 1 else latest
                
                current_value = float(latest['Close'])
                prev_value = float(prev['Close'])
                change = current_value - prev_value
                change_percent = (change / prev_value * 100) if prev_value != 0 else 0
                
                result.append({
                    'code': idx_code,
                    'name': index_names.get(idx_code, idx_code),
                    'value': round(current_value, 2),
                    'change': round(change, 2),
                    'changePercent': round(change_percent, 2)
                })
            except Exception as e:
                print(f'Error fetching {idx_code}: {e}')
                continue
        
        return jsonify({'indices': result})
    
    except Exception as e:
        print(f'Error in get_market_indices: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/top-stocks-by-market-cap', methods=['GET'])
def get_top_stocks_by_market_cap():
    """시가총액 기준 상위 5개 종목 반환"""
    try:
        # KRX 전체 종목 리스트 가져오기
        krx_list = fdr.StockListing('KRX')
        
        if krx_list is None or krx_list.empty:
            return jsonify({'error': '종목 데이터를 가져올 수 없습니다.'}), 500
        
        # 시가총액 컬럼 찾기 (영문/한글 모두 확인)
        market_cap_col = None
        for col in ['Marcap', '시가총액', 'MarketCap', 'market_cap']:
            if col in krx_list.columns:
                market_cap_col = col
                break
        
        if not market_cap_col:
            return jsonify({'error': '시가총액 정보를 찾을 수 없습니다.'}), 500
        
        # 종목명, 종목코드 컬럼 찾기
        name_col = 'Name' if 'Name' in krx_list.columns else ('종목명' if '종목명' in krx_list.columns else None)
        code_col = 'Code' if 'Code' in krx_list.columns else ('Symbol' if 'Symbol' in krx_list.columns else None)
        
        if not name_col or not code_col:
            return jsonify({'error': '종목 정보를 찾을 수 없습니다.'}), 500
        
        # 시가총액 기준으로 정렬 (내림차순)
        sorted_df = krx_list.sort_values(by=market_cap_col, ascending=False)
        
        # 상위 5개 선택
        top_5 = sorted_df.head(5)
        
        result = []
        for _, row in top_5.iterrows():
            try:
                symbol = str(row[code_col]).zfill(6)  # 6자리 종목코드
                name = str(row[name_col])
                market_cap = float(row[market_cap_col]) if pd.notna(row[market_cap_col]) else 0
                
                # 현재가 가져오기
                today = datetime.now().date()
                try:
                    price_df = fdr.DataReader(symbol, today - timedelta(days=2), today)
                    if not price_df.empty:
                        current_price = float(price_df.iloc[-1]['Close'])
                        prev_price = float(price_df.iloc[-2]['Close']) if len(price_df) > 1 else current_price
                        change = current_price - prev_price
                        change_percent = (change / prev_price * 100) if prev_price != 0 else 0
                    else:
                        current_price = 0
                        change = 0
                        change_percent = 0
                except:
                    current_price = 0
                    change = 0
                    change_percent = 0
                
                result.append({
                    'symbol': symbol,
                    'name': name,
                    'marketCap': round(market_cap / 100000000, 2),  # 억원 단위로 변환
                    'price': round(current_price, 0),
                    'change': round(change, 0),
                    'changePercent': round(change_percent, 2)
                })
            except Exception as e:
                print(f'Error processing stock {row.get(name_col, "unknown")}: {e}')
                continue
        
        return jsonify({'stocks': result})
    
    except Exception as e:
        print(f'Error in get_top_stocks_by_market_cap: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    print('Python 서버가 포트 5000에서 실행 중입니다.')
    app.run(host='0.0.0.0', port=5000, debug=True)

