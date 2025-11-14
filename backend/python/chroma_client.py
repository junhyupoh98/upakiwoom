import json
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection

# 환경 변수 로드 시 로그 추가 (디버깅용)
print('[DEBUG] chroma_client.py 모듈 로드 시작')
print(f'[DEBUG] 환경 변수 확인 - CHROMADB_API_KEY: {bool(os.getenv("CHROMADB_API_KEY"))}')
print(f'[DEBUG] 환경 변수 확인 - CHROMADB_TENANT: {bool(os.getenv("CHROMADB_TENANT"))}')
print(f'[DEBUG] 환경 변수 확인 - CHROMADB_DATABASE: {bool(os.getenv("CHROMADB_DATABASE"))}')

CHROMADB_API_KEY = os.getenv(
    "CHROMADB_API_KEY",
    "ck-BGYLZPX4So3TCKT9MLwvDB3GSdbGJzgv4eM4Lpca9f8s",
)
CHROMADB_TENANT = os.getenv(
    "CHROMADB_TENANT",
    "2f8c70eb-2e37-4645-bdf7-676a3324e684",
)
CHROMADB_DATABASE = os.getenv(
    "CHROMADB_DATABASE",
    "project_pic",
)

print(f'[DEBUG] ChromaDB 설정 값 - API_KEY 설정됨: {bool(CHROMADB_API_KEY)}')
print(f'[DEBUG] ChromaDB 설정 값 - TENANT 설정됨: {bool(CHROMADB_TENANT)}')
print(f'[DEBUG] ChromaDB 설정 값 - DATABASE 설정됨: {bool(CHROMADB_DATABASE)}')
US_NEWS_COLLECTION = os.getenv(
    "CHROMADB_US_NEWS_COLLECTION",
    "USnews_summary_ko",
)
KR_NEWS_COLLECTION = os.getenv(
    "CHROMADB_KR_NEWS_COLLECTION",
    "KRnews_summary_ko",
)

US_FIN_COLLECTION = os.getenv("CHROMADB_US_FIN_COLLECTION", "USfund_financials")
KR_FIN_COLLECTION = os.getenv("CHROMADB_KR_FIN_COLLECTION", "KRfund_financials")
EARNINGS_CALL_COLLECTION = os.getenv("CHROMADB_EARNINGS_CALL_COLLECTION", "earnings_call_summary_ko")

_client: Optional[ClientAPI] = None
_us_news_collection: Optional[Collection] = None
_kr_news_collection: Optional[Collection] = None
_us_fin_collection: Optional[Collection] = None
_kr_fin_collection: Optional[Collection] = None
_earnings_call_collection: Optional[Collection] = None


def get_chroma_client() -> ClientAPI:
    """지연 초기화된 Chroma CloudClient 반환"""
    global _client
    if _client is None:
        print(f'[DEBUG] ChromaDB 클라이언트 초기화 시작...')
        print(f'[DEBUG] CHROMADB_API_KEY 설정 여부: {bool(CHROMADB_API_KEY)}')
        print(f'[DEBUG] CHROMADB_TENANT 설정 여부: {bool(CHROMADB_TENANT)}')
        print(f'[DEBUG] CHROMADB_DATABASE 설정 여부: {bool(CHROMADB_DATABASE)}')
        
        if not CHROMADB_API_KEY:
            raise RuntimeError("CHROMADB_API_KEY 환경 변수가 설정되어 있지 않습니다.")
        if not CHROMADB_TENANT:
            raise RuntimeError("CHROMADB_TENANT 환경 변수가 설정되어 있지 않습니다.")
        if not CHROMADB_DATABASE:
            raise RuntimeError("CHROMADB_DATABASE 환경 변수가 설정되어 있지 않습니다.")

        try:
            print(f'[DEBUG] ChromaDB CloudClient 생성 시도...')
            _client = chromadb.CloudClient(
                api_key=CHROMADB_API_KEY,
                tenant=CHROMADB_TENANT,
                database=CHROMADB_DATABASE,
            )
            print(f'[OK] ChromaDB 클라이언트 생성 성공')
        except Exception as e:
            print(f'[ERROR] ChromaDB 클라이언트 생성 실패: {e}')
            import traceback
            traceback.print_exc()
            raise

    return _client


def get_us_news_collection() -> Collection:
    """미국 주식 뉴스 요약이 저장된 컬렉션 핸들 반환"""
    global _us_news_collection
    if _us_news_collection is None:
        client = get_chroma_client()
        _us_news_collection = client.get_collection(US_NEWS_COLLECTION)
    return _us_news_collection


def get_kr_news_collection() -> Collection:
    """한국 주식 뉴스 요약이 저장된 컬렉션 핸들 반환"""
    global _kr_news_collection
    if _kr_news_collection is None:
        print(f'[DEBUG] KR 뉴스 컬렉션 로드 시도: {KR_NEWS_COLLECTION}')
        try:
            client = get_chroma_client()
            _kr_news_collection = client.get_collection(KR_NEWS_COLLECTION)
            print(f'[OK] KR 뉴스 컬렉션 로드 성공: {KR_NEWS_COLLECTION}')
        except Exception as e:
            print(f'[ERROR] KR 뉴스 컬렉션 로드 실패: {e}')
            import traceback
            traceback.print_exc()
            raise
    return _kr_news_collection

def get_earnings_call_collection() -> Collection:
    """실적발표 요약이 저장된 컬렉션 핸들 반환"""
    global _earnings_call_collection
    if _earnings_call_collection is None:
        client = get_chroma_client()
        try:
            _earnings_call_collection = client.get_collection(EARNINGS_CALL_COLLECTION)
        except Exception as exc:
            print(f"[WARN] Earnings call collection 로드 실패: {exc}")
            raise
    return _earnings_call_collection


def get_us_fin_collection() -> Collection:
    """미국 주식 재무 데이터가 저장된 컬렉션 핸들 반환"""
    global _us_fin_collection
    if _us_fin_collection is None:
        client = get_chroma_client()
        try:
            # 기본 컬렉션 이름으로 시도
            _us_fin_collection = client.get_collection(US_FIN_COLLECTION)
            print(f"[DEBUG] US financial collection loaded: {US_FIN_COLLECTION}")
        except Exception as exc:
            print(f"[WARN] Failed to load US financial collection '{US_FIN_COLLECTION}': {exc}")
            # 사용 가능한 컬렉션 목록 확인하여 자동으로 찾기
            try:
                collections = client.list_collections()
                collection_names = [c.name for c in collections]
                print(f"[DEBUG] Available collections: {collection_names}")
                
                # US로 시작하는 financial 관련 컬렉션 찾기
                us_fin_collections = [
                    name for name in collection_names 
                    if 'US' in name and ('fund' in name.lower() or 'fin' in name.lower())
                ]
                print(f"[DEBUG] US financial-related collections: {us_fin_collections}")
                
                if us_fin_collections:
                    # 우선순위: USfund_financials > USfund_charts > 기타
                    priority_names = ["USfund_financials", "USfund_charts"]
                    for priority_name in priority_names:
                        if priority_name in us_fin_collections:
                            print(f"[INFO] Using collection: {priority_name}")
                            _us_fin_collection = client.get_collection(priority_name)
                            break
                    else:
                        # 우선순위 컬렉션이 없으면 첫 번째로 찾은 컬렉션 사용
                        collection_name = us_fin_collections[0]
                        print(f"[INFO] Using first available collection: {collection_name}")
                        _us_fin_collection = client.get_collection(collection_name)
                else:
                    print(f"[ERROR] No US financial collection found in available collections")
                    raise exc
            except Exception as e2:
                print(f"[ERROR] Could not find any US financial collection: {e2}")
                raise exc
    return _us_fin_collection


def get_kr_fin_collection() -> Collection:
    """한국 주식 재무 데이터가 저장된 컬렉션 핸들 반환"""
    global _kr_fin_collection
    if _kr_fin_collection is None:
        print(f'[DEBUG] KR 재무 컬렉션 로드 시도: {KR_FIN_COLLECTION}')
        try:
            client = get_chroma_client()
            _kr_fin_collection = client.get_collection(KR_FIN_COLLECTION)
            print(f'[OK] KR 재무 컬렉션 로드 성공: {KR_FIN_COLLECTION}')
        except Exception as e:
            print(f'[ERROR] KR 재무 컬렉션 로드 실패: {e}')
            import traceback
            traceback.print_exc()
            raise
    return _kr_fin_collection

def _parse_date_for_sort(metadata: Dict[str, Any]) -> Any:
    """정렬용 날짜 키 추출 (date_int > published_at > date)"""
    if "date_int" in metadata:
        return metadata["date_int"]
    if "published_at" in metadata:
        return metadata["published_at"]
    if "date" in metadata:
        return metadata["date"]
    return ""


def fetch_us_stock_news(symbol: str, limit: int = 3) -> List[Dict[str, Any]]:
    """
    종목별 미국 주식 뉴스 요약 리스트 반환.

    Args:
        symbol: 조회할 티커(예: TSLA, AAPL). 대소문자 무관.
        limit: 최대 반환 개수.

    Returns:
        title/summary/url 등의 정보를 담은 dict 리스트.
    """
    if not symbol:
        return []

    collection = get_us_news_collection()
    where_filter = {"ticker": symbol.upper()}

    # 충분한 개수를 가져와 날짜 기준으로 최신순 정렬
    # ChromaDB는 기본적으로 삽입 순서나 임의 순서로 반환할 수 있으므로 충분히 가져와서 정렬 필요
    fetch_limit = max(limit * 10, 50)  # 최신 뉴스를 놓치지 않도록 충분히 가져오기
    result = collection.get(where=where_filter, limit=fetch_limit)
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []

    print("[DEBUG] Chroma financial documents sample:", documents[:1])
    print("[DEBUG] Chroma financial metadatas sample:", metadatas[:1])
    ids = result.get("ids") or []

    news_items: List[Dict[str, Any]] = []
    for idx, doc in enumerate(documents):
        metadata = metadatas[idx] if idx < len(metadatas) else {}
        news_items.append(
            {
                "id": ids[idx] if idx < len(ids) else None,
                "ticker": metadata.get("ticker") or metadata.get("fmp_ticker"),
                "title": metadata.get("title"),
                "summary": doc,
                "url": metadata.get("url"),
                "published_at": metadata.get("published_at") or metadata.get("date"),
                "source": metadata.get("source") or metadata.get("site"),
                "date_int": metadata.get("date_int"),
                "raw_metadata": metadata,
            }
        )

    # 날짜 기준으로 정렬 (date_int > published_at > date)
    # date_int가 None이면 0으로 처리하여 최신순 정렬 보장
    news_items.sort(
        key=lambda item: (
            item.get("date_int") if item.get("date_int") is not None else 0,
            item.get("published_at") or "",
            item.get("raw_metadata", {}).get("date") or "",
        ),
        reverse=True,
    )

    return news_items[:limit]


def fetch_kr_stock_news(symbol: str, limit: int = 3) -> List[Dict[str, Any]]:
    """
    종목별 한국 주식 뉴스 요약 리스트 반환.

    Args:
        symbol: 조회할 티커(6자리 숫자, 예: 403550). .KS, .KQ 제거된 형태.
        limit: 최대 반환 개수.

    Returns:
        title/summary/url 등의 정보를 담은 dict 리스트.
    """
    if not symbol:
        return []

    # 심볼 정리 (.KS, .KQ 제거, 숫자만)
    clean_symbol = symbol.replace('.KS', '').replace('.KQ', '').strip()
    if not clean_symbol.isdigit() or len(clean_symbol) != 6:
        return []

    try:
        print(f'[DEBUG] KR 뉴스 컬렉션 로드 시도 (심볼: {clean_symbol})')
        collection = get_kr_news_collection()
        print(f'[OK] KR 뉴스 컬렉션 로드 성공')
    except Exception as exc:
        print(f"[ERROR] KR Chroma news collection init error: {exc}")
        import traceback
        traceback.print_exc()
        return []

    # ticker6로 필터링 (6자리 티커)
    where_filter = {"ticker6": clean_symbol}

    # 충분한 개수를 가져와 날짜 기준으로 최신순 정렬
    # ChromaDB는 기본적으로 삽입 순서나 임의 순서로 반환할 수 있으므로 충분히 가져와서 정렬 필요
    fetch_limit = max(limit * 10, 50)  # 최신 뉴스를 놓치지 않도록 충분히 가져오기
    try:
        result = collection.get(where=where_filter, limit=fetch_limit)
    except Exception as exc:
        print(f"[DEBUG] KR Chroma news get() error: {exc}")
        return []

    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []
    ids = result.get("ids") or []

    print(f"[DEBUG] KR Chroma news documents sample: {documents[:1] if documents else '[]'}")
    print(f"[DEBUG] KR Chroma news metadatas sample: {metadatas[:1] if metadatas else '[]'}")

    news_items: List[Dict[str, Any]] = []
    for idx, doc in enumerate(documents):
        metadata = metadatas[idx] if idx < len(metadatas) else {}
        news_items.append(
            {
                "id": ids[idx] if idx < len(ids) else None,
                "ticker": metadata.get("ticker6") or metadata.get("ticker_full"),
                "title": metadata.get("title"),
                "summary": doc,
                "url": metadata.get("url"),
                "published_at": metadata.get("date") or metadata.get("published_at"),
                "source": metadata.get("source") or metadata.get("site"),
                "date": metadata.get("date"),
                "date_int": metadata.get("date_int"),
                "company": metadata.get("company"),
                "raw_metadata": metadata,
            }
        )

    # 날짜 기준으로 정렬 (date_int > date > published_at)
    news_items.sort(
        key=lambda item: (
            item.get("date_int") or 0,
            item.get("date") or "",
            item.get("published_at") or "",
        ),
        reverse=True,
    )

    return news_items[:limit]


def fetch_earnings_call_summary(symbol: str) -> Optional[Dict[str, Any]]:
    """
    실적발표 요약 데이터 반환 (최신 1개)
    
    Args:
        symbol: 조회할 티커(예: AAPL, TSLA). 대소문자 무관.
    
    Returns:
        실적발표 요약 정보를 담은 dict 또는 None
    """
    if not symbol:
        return None
    
    try:
        collection = get_earnings_call_collection()
    except Exception as exc:
        print(f"[WARN] Earnings call collection 조회 실패: {exc}")
        return None
    
    where_filter = {"symbol": symbol.upper()}
    
    try:
        # 충분히 가져와서 날짜 기준 최신순 정렬
        result = collection.get(where=where_filter, limit=10)
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []
        
        if not documents or not metadatas:
            return None
        
        # 날짜 기준으로 정렬 (최신순)
        items = []
        for idx, doc in enumerate(documents):
            metadata_item = metadatas[idx] if idx < len(metadatas) else {}
            items.append({
                "metadata": metadata_item,
                "document": doc,
                "date": metadata_item.get("date") or "",
                "year": metadata_item.get("year") or "",
                "quarter": metadata_item.get("quarter") or "",
            })
        
        # 날짜 기준 내림차순 정렬
        items.sort(
            key=lambda x: (
                x["year"] or "",
                x["quarter"] or "",
                x["date"] or "",
            ),
            reverse=True
        )
        
        # 최신 1개 선택
        if not items:
            return None
        
        metadata = items[0]["metadata"]
        document = items[0]["document"]
        
        # JSON 필드 파싱
        def parse_json_field(field_value):
            if not field_value:
                return []
            if isinstance(field_value, str):
                try:
                    return json.loads(field_value)
                except:
                    return []
            return field_value if isinstance(field_value, list) else []
        
        earnings_data = {
            "symbol": metadata.get("symbol"),
            "date": metadata.get("date"),
            "year": metadata.get("year"),
            "quarter": metadata.get("quarter"),
            "section_summary": metadata.get("section_summary") or document,
            "core_summary": parse_json_field(metadata.get("core_summary_json")),
            "investor_points": parse_json_field(metadata.get("investor_points_json")),
            "guidance": parse_json_field(metadata.get("guidance_json")),
            "release": parse_json_field(metadata.get("release_json")),
            "qa": parse_json_field(metadata.get("qa_json")),
            "source_url": metadata.get("source_url"),
            "raw_metadata": metadata,
        }
        
        return earnings_data
    except Exception as e:
        print(f"[ERROR] Earnings call 조회 오류: {symbol} - {e}")
        return None


def _parse_numeric(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        stripped = str(value).replace(",", "").strip()
        if stripped == "":
            return None
        return float(stripped)
    except (ValueError, TypeError):
        return None


def _extract_row_value(row: Dict[str, Any], candidates: Iterable[str]) -> Optional[float]:
    lowered = {str(k).lower(): v for k, v in row.items()}
    for candidate in candidates:
        key = candidate.lower()
        if key in lowered:
            parsed = _parse_numeric(lowered[key])
            if parsed is not None:
                return parsed
    return None


def _extract_year(row: Dict[str, Any]) -> Optional[str]:
    candidates = ["year", "period", "label", "date", "fiscal_year"]
    for candidate in candidates:
        value = row.get(candidate) or row.get(candidate.upper()) or row.get(candidate.capitalize())
        if value:
            text = str(value).strip()
            if len(text) >= 4:
                # 연도만 추출
                return text[:10]
    return None


def _normalize_financial_rows(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    processed: List[Tuple[str, Dict[str, float]]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        year = _extract_year(row)
        if not year:
            continue
        revenue = _extract_row_value(row, ["revenue", "sales", "total_revenue"])
        operating_income = _extract_row_value(row, ["operatingincome", "operating_income", "ebit"])
        net_income = _extract_row_value(row, ["netincome", "net_income", "profit"])

        if revenue is None and operating_income is None and net_income is None:
            continue

        processed.append(
            (
                year,
                {
                    "revenue": revenue,
                    "operatingIncome": operating_income,
                    "netIncome": net_income,
                },
            )
        )

    if not processed:
        return None

    processed.sort(key=lambda item: item[0])
    chart_data = []
    revenue_series = []
    net_income_series = []
    operating_income_series = []

    for year, metrics in processed:
        revenue = metrics.get("revenue") or 0.0
        operating_income = metrics.get("operatingIncome") or 0.0
        net_income = metrics.get("netIncome") or 0.0

        chart_data.append(
            {
                "year": year,
                "revenue": revenue,
                "operatingIncome": operating_income,
                "netIncome": net_income,
            }
        )
        revenue_series.append({"year": year, "value": revenue})
        net_income_series.append({"year": year, "value": net_income})
        operating_income_series.append({"year": year, "value": operating_income})

    latest_entry = chart_data[-1]

    return {
        "chartData": chart_data,
        "revenue": revenue_series,
        "netIncome": net_income_series,
        "operatingIncome": operating_income_series,
        "latest": {
            "year": latest_entry.get("year"),
            "revenue": latest_entry.get("revenue", 0.0),
            "operatingIncome": latest_entry.get("operatingIncome", 0.0),
            "netIncome": latest_entry.get("netIncome", 0.0),
        },
    }


def _parse_financial_document(document: Any) -> Optional[Dict[str, Any]]:
    payload: Any = document
    if isinstance(document, str):
        try:
            payload = json.loads(document)
        except json.JSONDecodeError:
            return None

    if isinstance(payload, dict):
        if isinstance(payload.get("rows"), list):
            return _normalize_financial_rows(payload["rows"])
        if isinstance(payload.get("data"), list):
            return _normalize_financial_rows(payload["data"])
        if isinstance(payload.get("series"), list):
            # series 형태를 rows로 변환 (각 시리즈가 동일한 길이를 가진다고 가정)
            rows_map: Dict[int, Dict[str, Any]] = {}
            for series in payload["series"]:
                name = series.get("name") or series.get("label")
                values = series.get("values") or series.get("data")
                if not name or not isinstance(values, list):
                    continue
                for idx, value in enumerate(values):
                    rows_map.setdefault(idx, {})
                    rows_map[idx][name] = value
            rows = list(rows_map.values())
            return _normalize_financial_rows(rows)
    elif isinstance(payload, list):
        return _normalize_financial_rows(payload)

    return None


def fetch_us_financials_from_chroma(symbol: str) -> Optional[Dict[str, Any]]:
    """
    미국 주식 재무 데이터를 Chroma에서 조회하여 프론트에서 사용하는 형식으로 변환
    새로운 형식: Document에 y4(연도별), q4(분기별) 배열이 포함된 JSON
    """
    if not symbol:
        return None

    print(f"[DEBUG] US Chroma fetch start: {symbol} (collection: {US_FIN_COLLECTION})")

    try:
        collection = get_us_fin_collection()
    except Exception as exc:
        print(f"[ERROR] US Chroma client init error: {exc}")
        return None

    try:
        result = collection.get(
            where={"symbol": symbol.upper()},
            limit=1,
            include=["metadatas", "documents"],
        )
        print(f"[DEBUG] US Chroma query result: {len(result.get('documents', []))} documents found")
    except Exception as exc:
        print(f"[ERROR] US Chroma get() error: {exc}")
        return None

    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []
    if not documents:
        print(f"[DEBUG] US Chroma financial docs missing: {symbol}")
        return None

    raw_doc = documents[0]
    metadata = metadatas[0] if metadatas else {}

    try:
        payload = json.loads(raw_doc) if isinstance(raw_doc, str) else raw_doc
    except (json.JSONDecodeError, TypeError) as e:
        print(f"[ERROR] US Chroma JSON parse error: {e}")
        print(f"[DEBUG] Raw document type: {type(raw_doc)}, sample: {str(raw_doc)[:200]}")
        return None

    if not isinstance(payload, dict):
        print(f"[ERROR] US Chroma payload is not a dict: {type(payload)}")
        return None

    print(f"[DEBUG] US Chroma payload keys: {list(payload.keys())}")
    print(f"[DEBUG] US Chroma payload has y4: {bool(payload.get('y4'))}, q4: {bool(payload.get('q4'))}")

    # Helper to parse numeric values (USD는 이미 올바른 단위)
    def parse_value(value: Any) -> float:
        if value is None:
            return 0.0
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0

    def quarter_key(label: str) -> Tuple[int, int]:
        """분기 문자열을 정렬 가능한 튜플로 변환 (예: "2025Q3" -> (2025, 3))"""
        match = re.match(r"(\d{4})Q(\d)", str(label))
        if match:
            return int(match.group(1)), int(match.group(2))
        return (0, 0)

    # 분기별 데이터 처리
    quarter_rows: List[Dict[str, Any]] = []
    quarter_revenue: List[Dict[str, Any]] = []
    quarter_net_income: List[Dict[str, Any]] = []
    quarter_operating: List[Dict[str, Any]] = []
    quarters = payload.get("q4") or []
    print(f"[DEBUG] Processing {len(quarters)} quarters")
    for idx, item in enumerate(quarters):
        if not isinstance(item, dict):
            print(f"[WARN] Quarter item {idx} is not a dict: {type(item)}")
            continue
        
        # 분기 레이블: "분기" 필드 직접 사용 (예: "2025Q3")
        label = item.get("분기") or ""
        if not label:
            print(f"[WARN] Quarter item {idx} missing '분기' field: {item}")
            continue
        
        # 재무 데이터 추출 (한국어 필드명 사용)
        revenue = parse_value(item.get("매출액"))
        operating = parse_value(item.get("영업이익"))
        net_income = parse_value(item.get("당기순이익"))
        
        if revenue == 0.0 and operating == 0.0 and net_income == 0.0:
            print(f"[WARN] Quarter {label} has all zero values, skipping")
            continue
        
        print(f"[DEBUG] Quarter {label}: revenue={revenue}, operating={operating}, net_income={net_income}")
        
        quarter_rows.append(
            {
                "year": label,
                "revenue": revenue,
                "operatingIncome": operating,
                "netIncome": net_income,
            }
        )
        quarter_revenue.append({"year": label, "value": revenue})
        quarter_net_income.append({"year": label, "value": net_income})
        quarter_operating.append({"year": label, "value": operating})

    quarter_rows.sort(key=lambda row: quarter_key(row["year"]))
    quarter_revenue.sort(key=lambda row: quarter_key(row["year"]))
    quarter_net_income.sort(key=lambda row: quarter_key(row["year"]))
    quarter_operating.sort(key=lambda row: quarter_key(row["year"]))

    # 연도별 데이터 처리
    year_rows: List[Dict[str, Any]] = []
    year_revenue: List[Dict[str, Any]] = []
    year_net_income: List[Dict[str, Any]] = []
    year_operating: List[Dict[str, Any]] = []
    years = payload.get("y4") or []
    print(f"[DEBUG] Processing {len(years)} years")
    for idx, item in enumerate(years):
        if not isinstance(item, dict):
            print(f"[WARN] Year item {idx} is not a dict: {type(item)}")
            continue
        
        # 연도 레이블: "연도" 필드 직접 사용 (예: 2024 -> "2024")
        year_value = item.get("연도")
        if year_value is None:
            print(f"[WARN] Year item {idx} missing '연도' field: {item}")
            continue
        
        label = str(year_value)
        
        # 재무 데이터 추출 (한국어 필드명 사용)
        revenue = parse_value(item.get("매출액"))
        operating = parse_value(item.get("영업이익"))
        net_income = parse_value(item.get("당기순이익"))
        
        if revenue == 0.0 and operating == 0.0 and net_income == 0.0:
            print(f"[WARN] Year {label} has all zero values, skipping")
            continue
        
        print(f"[DEBUG] Year {label}: revenue={revenue}, operating={operating}, net_income={net_income}")
        
        year_rows.append(
            {
                "year": label,
                "revenue": revenue,
                "operatingIncome": operating,
                "netIncome": net_income,
            }
        )
        year_revenue.append({"year": label, "value": revenue})
        year_net_income.append({"year": label, "value": net_income})
        year_operating.append({"year": label, "value": operating})

    year_rows.sort(key=lambda row: row["year"])
    year_revenue.sort(key=lambda row: row["year"])
    year_net_income.sort(key=lambda row: row["year"])
    year_operating.sort(key=lambda row: row["year"])

    # 데이터가 없으면 None 반환
    if not quarter_rows and not year_rows:
        print(f"[WARN] No financial data found for {symbol}")
        return None

    # 분기와 연도 데이터 합치기
    chart_rows = quarter_rows + year_rows
    revenue_series = quarter_revenue + year_revenue
    net_income_series = quarter_net_income + year_net_income
    operating_series = quarter_operating + year_operating

    # 최신 데이터 찾기 (분기 우선, 없으면 연도)
    latest_entry = quarter_rows[-1] if quarter_rows else (year_rows[-1] if year_rows else {})
    print(f"[DEBUG] Latest entry: {latest_entry}")

    response: Dict[str, Any] = {
        "revenue": revenue_series,
        "netIncome": net_income_series,
        "operatingIncome": operating_series,
        "chartData": chart_rows,
        "latest": {
            "year": latest_entry.get("year", ""),
            "revenue": latest_entry.get("revenue", 0.0),
            "operatingIncome": latest_entry.get("operatingIncome", 0.0),
            "netIncome": latest_entry.get("netIncome", 0.0),
        },
    }

    # 통화 정보
    currency = payload.get("currency") or metadata.get("currency") or "USD"
    response["currency"] = currency

    # 데이터 기준일
    as_of = payload.get("as_of") or metadata.get("as_of")
    if as_of:
        response["asOf"] = as_of

    # 출처 정보
    source = payload.get("source") or metadata.get("source")
    response["source"] = {
        "collection": US_FIN_COLLECTION,
        "doc_id": metadata.get("doc_id"),
        "source": source,
    }

    # 세그먼트 정보 처리
    segments_pct = payload.get("segments_pct")
    segments_asof = payload.get("segments_asof")
    if segments_pct and isinstance(segments_pct, dict):
        segments_list = []
        # 최신 분기 또는 연도의 매출액을 사용하여 세그먼트별 매출액 계산
        total_revenue = latest_entry.get("revenue", 0.0)
        for name, percentage in segments_pct.items():
            percentage_value = float(percentage) if percentage else 0.0
            segment_revenue = (total_revenue * percentage_value / 100.0) if total_revenue > 0 else 0.0
            segments_list.append(
                {
                    "segment": name,
                    "revenue": segment_revenue,
                    "percentage": percentage_value,
                }
            )
        segments_list.sort(key=lambda item: item["percentage"], reverse=True)
        response["segments"] = segments_list
        response["segmentCurrency"] = currency
        if segments_asof:
            response["segmentDate"] = segments_asof
        else:
            # segments_asof가 없으면 as_of 사용
            if as_of:
                response["segmentDate"] = as_of

    return response


def fetch_kr_financials_from_chroma(symbol: str) -> Optional[Dict[str, Any]]:
    """
    한국 주식 재무 데이터를 Chroma에서 조회하여 프론트에서 사용하는 형식으로 변환
    """
    if not symbol or not symbol.isdigit():
        return None

    try:
        print(f'[DEBUG] KR 재무 컬렉션 로드 시도 (심볼: {symbol})')
        collection = get_kr_fin_collection()
        print(f'[OK] KR 재무 컬렉션 로드 성공')
    except Exception as exc:
        print(f"[ERROR] KR Chroma client init error: {exc}")
        import traceback
        traceback.print_exc()
        return None

    try:
        result = collection.get(
            where={"stock_code": symbol},
            limit=1,
            include=["metadatas", "documents"],
        )
    except Exception as exc:
        print(f"[DEBUG] KR Chroma get() error: {exc}")
        return None

    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []
    if not documents:
        return None

    raw_doc = documents[0]
    metadata = metadatas[0] if metadatas else {}

    try:
        payload = json.loads(raw_doc) if isinstance(raw_doc, str) else raw_doc
    except (json.JSONDecodeError, TypeError):
        return None

    # Helper to convert 억 원 → 원 단위
    def to_won(value: Any) -> float:
        if value is None:
            return 0.0
        try:
            return float(str(value).replace(",", "")) * 100_000_000.0
        except ValueError:
            return 0.0

    def quarter_key(label: str) -> Tuple[int, int]:
        match = re.match(r"(\d{4})Q(\d)", str(label))
        if match:
            return int(match.group(1)), int(match.group(2))
        return (0, 0)

    quarter_rows: List[Dict[str, Any]] = []
    quarter_revenue: List[Dict[str, Any]] = []
    quarter_net_income: List[Dict[str, Any]] = []
    quarter_operating: List[Dict[str, Any]] = []
    quarters = payload.get("q4") or []
    for item in quarters:
        label = item.get("분기") or f"{item.get('연도', '')}Q"
        revenue = to_won(item.get("매출액(억 원)"))
        operating = to_won(item.get("영업이익(억 원)"))
        net_income = to_won(item.get("당기순이익(억 원)"))
        quarter_rows.append(
            {
                "year": label,
                "revenue": revenue,
                "operatingIncome": operating,
                "netIncome": net_income,
            }
        )
        quarter_revenue.append({"year": label, "value": revenue})
        quarter_net_income.append({"year": label, "value": net_income})
        quarter_operating.append({"year": label, "value": operating})

    quarter_rows.sort(key=lambda row: quarter_key(row["year"]))
    quarter_revenue.sort(key=lambda row: quarter_key(row["year"]))
    quarter_net_income.sort(key=lambda row: quarter_key(row["year"]))
    quarter_operating.sort(key=lambda row: quarter_key(row["year"]))

    year_rows: List[Dict[str, Any]] = []
    year_revenue: List[Dict[str, Any]] = []
    year_net_income: List[Dict[str, Any]] = []
    year_operating: List[Dict[str, Any]] = []
    years = payload.get("y4") or []
    for item in years:
        label = str(item.get("연도"))
        revenue = to_won(item.get("매출액(억 원)"))
        operating = to_won(item.get("영업이익(억 원)"))
        net_income = to_won(item.get("당기순이익(억 원)"))
        year_rows.append(
            {
                "year": label,
                "revenue": revenue,
                "operatingIncome": operating,
                "netIncome": net_income,
            }
        )
        year_revenue.append({"year": label, "value": revenue})
        year_net_income.append({"year": label, "value": net_income})
        year_operating.append({"year": label, "value": operating})

    year_rows.sort(key=lambda row: row["year"])
    year_revenue.sort(key=lambda row: row["year"])
    year_net_income.sort(key=lambda row: row["year"])
    year_operating.sort(key=lambda row: row["year"])

    chart_rows = quarter_rows + year_rows
    revenue_series = quarter_revenue + year_revenue
    net_income_series = quarter_net_income + year_net_income
    operating_series = quarter_operating + year_operating

    latest_entry = quarter_rows[-1] if quarter_rows else (year_rows[-1] if year_rows else {})

    response: Dict[str, Any] = {
        "revenue": revenue_series,
        "netIncome": net_income_series,
        "operatingIncome": operating_series,
        "chartData": chart_rows,
        "latest": {
            "year": latest_entry.get("year", ""),
            "revenue": latest_entry.get("revenue", 0.0),
            "operatingIncome": latest_entry.get("operatingIncome", 0.0),
            "netIncome": latest_entry.get("netIncome", 0.0),
        },
        "currency": "KRW",
    }

    as_of = payload.get("as_of") or metadata.get("as_of")
    if as_of:
        response["asOf"] = as_of

    segments = payload.get("segments") or {}
    if isinstance(segments, dict) and segments:
        segment_rows = []
        total_value = 0.0
        converted_segments: Dict[str, float] = {}
        for name, value in segments.items():
            try:
                amount = float(str(value).replace(",", ""))
            except ValueError:
                continue
            converted_segments[name] = amount
            total_value += amount

        for name, amount in converted_segments.items():
            segment_rows.append(
                {
                    "segment": name,
                    "revenue": amount,
                    "percentage": (amount / total_value * 100.0) if total_value else 0.0,
                }
            )

        if segment_rows:
            segment_rows.sort(key=lambda item: item["revenue"], reverse=True)
            response["segments"] = segment_rows
            response["segmentCurrency"] = "KRW"
            if as_of:
                response["segmentDate"] = as_of

    response["source"] = {
        "collection": KR_FIN_COLLECTION,
        "doc_id": metadata.get("doc_id"),
    }

    return response


__all__ = [
    "fetch_us_stock_news",
    "fetch_kr_stock_news",
    "fetch_earnings_call_summary",
    "get_us_news_collection",
    "get_kr_news_collection",
    "get_chroma_client",
    "fetch_us_financials_from_chroma",
    "fetch_kr_financials_from_chroma",
    "get_us_fin_collection",
    "get_kr_fin_collection",
]

