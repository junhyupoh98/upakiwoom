import io
import json
import os
import re
import logging
from typing import Dict, Optional, Tuple, List, Any, Callable

from dotenv import load_dotenv
from google.cloud import vision
from google.cloud.vision_v1 import types as vision_types
from PIL import Image

try:
    import google.generativeai as genai
except ImportError:  # pragma: no cover - 설치 누락 시 호출 영역에서 처리
    genai = None

# 환경 변수 로드 (프로젝트 루트 .env)
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))

logger = logging.getLogger(__name__)

# pic_me에서 개선된 프롬프트
GEMINI_JSON_GUIDE = """{
  "object": "여기에 주요 물체 이름 입력 (예: 노트북)",
  "brand": "여기에 소비자에게 알려진 브랜드 이름 입력 (예: 몽쉘)",
  "company": "해당 브랜드를 소유/제조하는 실제 법인명 입력 (예: 롯데웰푸드)",
  "company_market": "해당 법인이 상장된 거래소 이름 (예: KRX, NASDAQ, 비상장)",
  "company_ticker": "해당 법인의 티커(종목코드). 비상장이라면 '비상장'으로 기입"
}

중요:
- object: 이미지에서 보이는 주요 물체나 제품의 일반적인 이름 (예: 노트북, 자동차, 스마트폰, 운동화 등)
- brand: 소비자가 인지하는 브랜드명 (없으면 null)
- company: 브랜드를 실제로 제조/판매하는 법인명(그룹명보다 구체적인 법인명).
- company_market & company_ticker: 상장 거래소 및 종목코드를 정확히 기입하세요. 비상장이라면 두 필드 모두 "비상장"으로 작성하고, 확실하지 않으면 null.
- brand나 company 관련 정보는 신뢰할 수 있는 자료를 참고해 검증한 뒤 답변하세요.
- 추측하거나 부정확한 정보를 제공하지 마세요.
- JSON 형식만 반환하세요."""

# 밸류체인 가이드 (pic_me)
VALUE_CHAIN_GUIDE = """{
  "components": [
    {
      "component": "핵심 공급요소 또는 부품명 (예: OEM/ODM, 주요 원료, 포장재, SoC, 디스플레이 등)",
      "supplier_company": "공급사 법인명(예: 한국콜마, 코스맥스, TSMC, LG Display 등)",
      "supplier_exchange": "상장 거래소 코드 또는 '비상장' (예: NASDAQ, NYSE, KOSPI, KOSDAQ, TSE, 비상장)",
      "supplier_ticker": "정확한 티커(상장일 경우). 비상장일 경우 null",
      "confidence": 0.0-1.0,
      "evidence_url": "공식/신뢰 가능한 출처 URL (선택)"
    }
  ]
}

지침:
- 제품 카테고리를 먼저 파악하고, 해당 카테고리에서 영향도가 큰 공급요소를 최대 2개만 반환하세요.
- 예시) 화장품: OEM/ODM(제조사), 주요 원료 공급사, 포장재 공급사. 전자제품: SoC/CPU/GPU, 디스플레이, 메모리. 의류: 원단, 봉제 OEM. 식음료: 주요 원재료, 용기/포장.
- 불확실하면 해당 항목을 생략하거나 confidence를 낮게 설정합니다.
- 거래소 코드는 TSE/KOSPI/KOSDAQ/NASDAQ/NYSE 등 표준 축약형을 사용하고, 비상장이면 '비상장'으로 표기하세요.
"""

# 지주회사 해석 가이드 (pic_me)
HOLDING_RESOLUTION_GUIDE = """{
  "holding_company": "지주회사(상장 법인) 정식 명칭",
  "holding_market": "상장 시장 (예: KRX, KOSDAQ, NASDAQ, NYSE, 비상장)",
  "holding_ticker": "정확한 티커 코드 (예: 090430, AAPL). 비상장/불명확 시 null",
  "confidence": "0.0~1.0 사이 신뢰도(float)",
  "sources": ["근거가 된 공개 출처 링크 또는 간단한 출처 설명 1~3개"]
}

지침:
- 입력 brand/company가 비상장일 경우, 그 지배/상표권을 보유한 상장 지주회사(또는 실질 상장 법인)를 찾으세요.
- 출처를 반드시 포함하고, 확실하지 않으면 confidence를 낮게 설정하고 holding_* 필드를 null로 두세요.
- 상장 거래소는 KRX/KOSDAQ/NASDAQ/NYSE/TSE 중 하나일 가능성을 우선 고려하세요. 아닌 경우 정직하게 기입하세요."""

# 지주회사 매핑 (pic_me)
HOLDING_MAP = {
    # 비상장 자회사 -> 상장 지주회사 정보
    "동아제약": {
        "holding_company": "동아쏘시오홀딩스",
        "holding_market": "KRX",
        "holding_ticker": "000640",
    },
    "오설록": {
        "holding_company": "아모레퍼시픽",
        "holding_market": "KRX",
        "holding_ticker": "090430",
    },
    "osulloc": {
        "holding_company": "아모레퍼시픽",
        "holding_market": "KRX",
        "holding_ticker": "090430",
    },
}

_ALLOWED_MARKETS = {"KRX", "KOSDAQ", "KOSPI", "NASDAQ", "NYSE", "TSE"}
_HOLDING_CACHE: Dict[str, Dict[str, Any]] = {}
_HOLDING_CACHE_MAX = 256


class VisionGeminiError(Exception):
    """Vision 또는 Gemini 호출 실패"""


def get_candidate_models(selected_model: Optional[str], available_models_clean: List[str]) -> List[str]:
    """사용할 Gemini 모델 후보 목록 생성 (pic_me 스타일)"""
    model_names: List[str] = []
    # 항상 사용자가 선택한 모델을 최우선으로 시도 (목록에 없더라도)
    if selected_model:
        model_names.append(selected_model)

    if available_models_clean:
        preferred = [
            "gemini-2.5-pro-preview-03-25",
            "gemini-2.5-pro-preview",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
            "gemini-pro",
        ]
        for name in (n for n in preferred if n in available_models_clean and n not in model_names):
            model_names.append(name)
        for candidate in available_models_clean:
            if candidate not in model_names and "gemini" in candidate.lower():
                model_names.append(candidate)

    if not model_names:
        model_names = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-pro"]

    return model_names


def prepare_gemini_client(api_key: Optional[str] = None, selected_model: Optional[str] = None):
    """Gemini API 클라이언트를 준비하고 사용할 모델 후보를 반환 (pic_me 스타일)"""
    try:
        import google.generativeai as genai
    except ImportError:
        return None, None, [], "google-generativeai 패키지가 설치되지 않았습니다."

    key_to_use = api_key or os.getenv("GEMINI_API_KEY")
    if not key_to_use:
        return None, None, [], "GEMINI_API_KEY 환경 변수가 설정되지 않았습니다."

    genai.configure(api_key=key_to_use)

    try:
        available_models = [m.name for m in genai.list_models()
                            if 'generateContent' in m.supported_generation_methods]
        available_models_clean = [m.replace('models/', '') for m in available_models]
    except Exception:
        available_models_clean = []

    model_names = get_candidate_models(selected_model, available_models_clean)
    if not model_names:
        return None, None, [], "사용 가능한 모델을 찾을 수 없습니다."

    return genai, selected_model, available_models_clean, None


def extract_json_from_response_text(response_text: str) -> Tuple[Optional[Dict], Optional[str]]:
    """Gemini 응답에서 JSON 추출 (pic_me 스타일 - 개선된 에러 처리)"""
    if not response_text:
        return None, "빈 응답입니다."

    json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response_text, re.DOTALL)
    if not json_match:
        return None, f'JSON을 찾을 수 없습니다: {response_text[:200]}'

    json_str = json_match.group(0)
    try:
        return json.loads(json_str), None
    except json.JSONDecodeError as exc:
        return None, f'JSON 파싱 오류: {str(exc)}'


def _normalize_exchange_name(name: Optional[str]) -> Optional[str]:
    """거래소 이름 정규화 (pic_me 스타일)"""
    if not name:
        return name
    n = str(name).strip().upper()
    # 일본 거래소 표기 정규화
    if n in {"TYO", "TSE", "TOKYO", "TOKYO STOCK EXCHANGE", "JPX"}:
        return "TSE"
    # 한국 표기 정규화
    if n in {"KOSPI PRIME", "KOSPIKOSPI"}:
        return "KOSPI"
    return n


def _normalize_company_name(name: str) -> str:
    """회사명 정규화 (pic_me 스타일)"""
    return (name or "").strip().casefold()


def resolve_holding_company(
    brand: Optional[str],
    company: Optional[str],
    brand_candidates: Optional[List[str]] = None,
    api_key: Optional[str] = None,
    selected_model: Optional[str] = None,
    min_confidence: float = 0.6,
) -> Dict[str, Any]:
    """비상장 브랜드/회사에 대해 Gemini로 상장 지주회사 정보를 탐색 (pic_me 스타일)"""
    brand_norm = (brand or "").strip()
    company_norm = (company or "").strip()
    cand_key = ",".join(sorted(set(brand_candidates or [])))
    cache_key = f"{brand_norm}|{company_norm}|{cand_key}".casefold()
    if cache_key in _HOLDING_CACHE:
        return _HOLDING_CACHE[cache_key]

    genai, selected_model, available_models_clean, error_message = prepare_gemini_client(api_key, selected_model)
    if error_message:
        logger.warning("resolve_holding_company: prepare client error: %s", error_message)
        return {}

    model_names = get_candidate_models(selected_model, available_models_clean)
    generation_config = {"temperature": 0.2, "top_p": 0.9, "top_k": 40}

    parts = []
    if brand_norm:
        parts.append(f"brand: {brand_norm}")
    if company_norm:
        parts.append(f"company: {company_norm}")
    if brand_candidates:
        parts.append("candidates: " + ", ".join(sorted(set(brand_candidates))))
    context = "\n".join(parts) if parts else "(no signals)"

    prompt = f"""다음 정보를 바탕으로, 비상장일 가능성이 있는 브랜드/회사에 대해 상장 지주회사(또는 실질 상장 법인)를 찾아주세요. 반드시 아래 JSON 스키마만 반환합니다.

정보:
{context}

JSON 스키마:
{HOLDING_RESOLUTION_GUIDE}
"""
    last_error = None
    response = None
    used_model = None
    for model_name in model_names:
        try:
            model = genai.GenerativeModel(model_name, generation_config=generation_config)
            response = model.generate_content(prompt)
            used_model = model_name
            break
        except Exception as exc:
            last_error = str(exc)
            logger.warning("resolve_holding_company: model %s failed: %s", model_name, last_error)
            response = None

    if response is None:
        return {}

    result, parse_error = extract_json_from_response_text(response.text.strip())
    if parse_error:
        logger.warning("resolve_holding_company: parse error: %s", parse_error)
        return {}

    holding_company = (result.get("holding_company") or "").strip()
    holding_market = (result.get("holding_market") or "").strip()
    holding_ticker = (result.get("holding_ticker") or "").strip()
    confidence = float(result.get("confidence") or 0.0)
    sources = result.get("sources") or []

    if not holding_company or confidence < min_confidence:
        return {}
    if holding_market and holding_market.upper() not in _ALLOWED_MARKETS and holding_market != "비상장":
        return {}
    if holding_market != "비상장" and not holding_ticker:
        return {}

    resolved = {
        "holding_company": holding_company,
        "holding_market": holding_market or None,
        "holding_ticker": holding_ticker or None,
        "holding_sources": sources if isinstance(sources, list) else [],
        "holding_model": used_model,
        "holding_confidence": confidence,
    }
    if len(_HOLDING_CACHE) >= _HOLDING_CACHE_MAX:
        _HOLDING_CACHE.pop(next(iter(_HOLDING_CACHE)))
    _HOLDING_CACHE[cache_key] = resolved
    return resolved


def augment_with_holding_info(
    result: Dict[str, Any],
    resolver: Optional[Callable[..., Dict[str, Any]]] = None,
    api_key: Optional[str] = None,
    selected_model: Optional[str] = None,
    brand_candidates: Optional[List[str]] = None,
    min_confidence: float = 0.6,
) -> Dict[str, Any]:
    """Gemini 결과에 지주회사 상장 정보를 보강 (pic_me 스타일)"""
    if not result:
        return result

    company = result.get("company")
    market = result.get("company_market")

    is_private = (market is None) or (str(market).strip().lower() == "비상장")

    if company and is_private:
        key = _normalize_company_name(company)
        holding = HOLDING_MAP.get(key) or HOLDING_MAP.get(company) or HOLDING_MAP.get(company.strip())
        if holding:
            result = dict(result)
            result.update({
                "holding_company": holding.get("holding_company"),
                "holding_market": holding.get("holding_market"),
                "holding_ticker": holding.get("holding_ticker"),
            })
            return result
        # 매핑 실패: 동적 해석 시도
        if resolver:
            resolved = resolver(
                brand=result.get("brand"),
                company=company,
                brand_candidates=brand_candidates,
                api_key=api_key,
                selected_model=selected_model,
                min_confidence=min_confidence,
            )
            if resolved and resolved.get("holding_company"):
                result = dict(result)
                result.update({
                    "holding_company": resolved.get("holding_company"),
                    "holding_market": resolved.get("holding_market"),
                    "holding_ticker": resolved.get("holding_ticker"),
                })
                if resolved.get("holding_sources"):
                    result["holding_sources"] = resolved["holding_sources"]
                if resolved.get("holding_model"):
                    result["holding_model"] = resolved["holding_model"]
                if resolved.get("holding_confidence") is not None:
                    result["holding_confidence"] = resolved["holding_confidence"]

    return result


def suggest_value_chain_suppliers(
    *,
    object_name: Optional[str],
    brand: Optional[str],
    text_hint: Optional[str] = None,
    supplier_candidates: Optional[List[str]] = None,
    api_key: Optional[str] = None,
    selected_model: Optional[str] = None,
    top_k: int = 2,
) -> List[Dict[str, Any]]:
    """제품의 핵심 부품(Value Chain) 공급사 정보를 최대 2개까지 제안 (pic_me 스타일)"""
    genai, sel, available, err = prepare_gemini_client(api_key, selected_model)
    if err:
        return []

    models = get_candidate_models(sel, available)

    ctx_parts: List[str] = []
    if object_name:
        ctx_parts.append(f"Object: {object_name}")
    if isinstance(brand, str) and brand:
        ctx_parts.append(f"Brand: {brand}")
    if isinstance(text_hint, str) and text_hint:
        ctx_parts.append(f"TextHint: {text_hint[:300]}")
    if supplier_candidates:
        uniq = sorted(set(supplier_candidates))
        if uniq:
            ctx_parts.append("SupplierCandidates: " + ", ".join(uniq))
    ctx = "\n".join(ctx_parts) if ctx_parts else "(no extra hints)"

    prompt = (
        "아래 맥락을 바탕으로 이 제품 카테고리에 적합한 핵심 공급요소/부품의 공급사 상장정보를 "
        f"중요도 순으로 최대 {top_k}개 제시하세요. 반드시 JSON 형식만 반환하세요.\n\n"
        "예시) 화장품: OEM/ODM(제조사), 주요 원료 공급사, 포장재 공급사. "
        "전자제품: SoC/CPU/GPU, 디스플레이, 메모리. 의류: 원단, 봉제 OEM. 식음료: 주요 원재료, 용기/포장.\n\n"
        f"맥락:\n{ctx}\n\n스키마:\n{VALUE_CHAIN_GUIDE}"
    )

    gen_cfg = {"temperature": 0.2, "top_p": 0.9, "top_k": 40}

    resp = None
    used = None
    for m in models:
        try:
            model = genai.GenerativeModel(m, generation_config=gen_cfg)
            r = model.generate_content(prompt)
            if getattr(r, "text", None):
                resp = r
                used = m
                break
        except Exception:
            continue

    if resp is None:
        return []

    data, perr = extract_json_from_response_text(resp.text.strip())
    if perr or not isinstance(data, dict):
        return []

    items = data.get("components") or []
    out: List[Dict[str, Any]] = []
    for it in items:
        ctype = str(it.get("component", "")).strip()
        supplier = (it.get("supplier_company") or "").strip()
        exch_raw = (it.get("supplier_exchange") or "").strip()
        exch = _normalize_exchange_name(exch_raw)
        ticker = (it.get("supplier_ticker") or "").strip()
        conf = it.get("confidence")
        evid = it.get("evidence_url") or it.get("evidence")
        if not ctype:
            continue
        if not supplier:
            continue
        if exch and exch.upper() not in _ALLOWED_MARKETS and exch != "비상장":
            continue
        out.append({
            "component": ctype,
            "supplier_company": supplier,
            "supplier_exchange": exch or None,
            "supplier_ticker": ticker or None,
            "confidence": conf,
            "evidence_url": evid or None,
        })
        if len(out) >= top_k:
            break

    return out


def suggest_related_public_companies(
    object_name: Optional[str],
    brand: Optional[str],
    api_key: Optional[str] = None,
    selected_model: Optional[str] = None,
    top_k: int = 3,
) -> Dict[str, Any]:
    """제품 관련 상장사 추천 (pic_me 스타일 - 간소화 버전)"""
    genai, selected_model, available_models_clean, error_message = prepare_gemini_client(api_key, selected_model)
    if error_message:
        logger.warning("suggest_related_public_companies: prepare client error: %s", error_message)
        return {"companies": []}

    model_names = get_candidate_models(selected_model, available_models_clean)
    generation_config = {"temperature": 0.2, "top_p": 0.9, "top_k": 40}

    comp_prompt = f"""이 제품은 {brand or '(unknown brand)'}의 {object_name or '(unknown object)'}입니다.
같은 제품군(Category)에 속한 경쟁 상장사 {top_k}개를 추천하세요.
시장 규모(매출 또는 시가총액)와 제품 카테고리 내 인지도/점유율을 함께 고려해 중요도 순으로 정렬하고 JSON으로만 응답하세요.

JSON ONLY:
{{
  "companies": [
    {{"company": "정식 법인명", "market": "KRX/KOSDAQ/KOSPI/NASDAQ/NYSE/TSE", "ticker": "티커"}},
    ...
  ]
}}
"""

    last_error = None
    response = None
    used_model = None
    for model_name in model_names:
        try:
            model = genai.GenerativeModel(model_name, generation_config=generation_config)
            response = model.generate_content(comp_prompt)
            used_model = model_name
            break
        except Exception as exc:
            last_error = str(exc)
            logger.warning("suggest_related_public_companies: model %s failed: %s", model_name, last_error)
            response = None

    if response is None or not getattr(response, "text", None):
        return {"companies": []}

    result, parse_error = extract_json_from_response_text(response.text.strip())
    if parse_error or not isinstance(result, dict):
        logger.warning("suggest_related_public_companies: parse error: %s", parse_error)
        return {"companies": []}

    items = result.get("companies") or []
    cleaned: List[Dict[str, Any]] = []
    for it in items:
        company = (it.get("company") or "").strip()
        market_raw = (it.get("market") or "").strip()
        market_norm = _normalize_exchange_name(market_raw)
        ticker = (it.get("ticker") or "").strip()
        if not company or not market_norm or not ticker:
            continue
        if market_norm.upper() not in _ALLOWED_MARKETS:
            continue
        cleaned.append({"company": company, "market": market_norm, "ticker": ticker})
        if len(cleaned) >= top_k:
            break

    return {"companies": cleaned}


def _summarize_vision_response(response) -> str:
    parts = []

    if getattr(response, "label_annotations", None):
        labels = sorted(response.label_annotations, key=lambda l: l.score, reverse=True)
        parts.append(
            "Labels: "
            + ", ".join(f"{label.description} ({label.score:.0%})" for label in labels[:5])
        )

    if getattr(response, "localized_object_annotations", None):
        objects = sorted(response.localized_object_annotations, key=lambda o: o.score, reverse=True)
        parts.append(
            "Objects: "
            + ", ".join(f"{obj.name} ({obj.score:.0%})" for obj in objects[:5])
        )

    if getattr(response, "logo_annotations", None):
        logos = sorted(response.logo_annotations, key=lambda l: l.score, reverse=True)
        parts.append(
            "Logos: "
            + ", ".join(f"{logo.description} ({logo.score:.0%})" for logo in logos[:5])
        )

    if getattr(response, "text_annotations", None):
        text = response.text_annotations[0].description.strip()
        if text:
            preview = text.replace("\n", " ")
            if len(preview) > 300:
                preview = preview[:300] + "..."
            parts.append(f"OCR Text: {preview}")

    return "\n".join(parts) if parts else "Vision API에서 유의미한 정보를 찾지 못했습니다."


def _call_gemini_with_text(summary: str, api_key: Optional[str] = None, selected_model: Optional[str] = None) -> Tuple[Optional[Dict], Optional[str], Optional[str]]:
    """Vision 분석 요약을 Gemini에 전달하여 object/brand/company 판단 (pic_me 스타일)"""
    genai, selected_model, available_models_clean, error_message = prepare_gemini_client(api_key, selected_model)
    if error_message:
        return None, None, error_message

    model_names = get_candidate_models(selected_model, available_models_clean)

    prompt = f"""다음 Google Cloud Vision 분석 결과를 기반으로 이미지 속 주요 물체와 그 브랜드(기업)를 판단하세요. 결과는 반드시 JSON으로만 응답해야 합니다.

Vision 분석 요약:
{summary}

JSON 형식:
{GEMINI_JSON_GUIDE}

지침:
- Vision 라벨/객체 정보를 우선적으로 참고하되, 텍스트/로고 등 보조 정보도 고려하세요.
- 브랜드가 확인되면 그 브랜드를 실제로 제조하거나 판매하는 법인명을 정확히 기입하세요(예: 롯데자일리톨 → 롯데웰푸드). 그룹명만 알 수 있을 때는 추가 근거를 찾아보고, 끝까지 확실하지 않으면 company는 null로 두세요.
- company_market에는 상장 거래소(예: KRX, NASDAQ 등), company_ticker에는 정확한 티커를 기입하세요. 비상장이면 두 필드 모두 "비상장"으로 작성하고, 확실하지 않으면 null로 두세요.
- 추측하거나 부정확한 정보를 제공하지 마세요."""

    last_error = None
    used_model = None
    response = None

    generation_config = {
        "temperature": 0.2,
        "top_p": 0.9,
        "top_k": 40,
    }

    for model_name in model_names:
        try:
            model = genai.GenerativeModel(model_name, generation_config=generation_config)
            response = model.generate_content(prompt)
            used_model = model_name
            break
        except Exception as exc:
            last_error = str(exc)
            logger.warning("Gemini generate_content 실패 (model=%s): %s", model_name, last_error)
            response = None

    if response is None:
        return None, None, f'모든 모델 시도 실패: {last_error}'

    result, parse_error = extract_json_from_response_text(response.text.strip())
    if parse_error:
        return None, None, parse_error

    return result, used_model, None


def _call_gemini_with_image(image_bytes: bytes, api_key: Optional[str] = None, selected_model: Optional[str] = None) -> Tuple[Optional[Dict], Optional[str], Optional[str]]:
    """Gemini API에 이미지를 직접 전송하여 분석 (pic_me 스타일)"""
    genai, selected_model, available_models_clean, error_message = prepare_gemini_client(api_key, selected_model)
    if error_message:
        return None, None, error_message

    model_names = get_candidate_models(selected_model, available_models_clean)

    prompt = f"""이 이미지를 분석하여 다음 JSON 형식으로 답변해주세요:

{GEMINI_JSON_GUIDE}

추가 지침:
- 이미지에서 가장 중심이 되는 물체를 우선적으로 판단하세요.
- 텍스트나 배경 요소는 보조 정보입니다.
- 브랜드를 확인하면 해당 브랜드를 소유/제조하는 실제 법인명(예: 롯데웰푸드, 애플코리아 등)을 정확히 기입하세요. 그룹명만 알 수 있을 경우, 법인을 확실히 찾을 때까지 추가 근거를 탐색하고 그래도 없으면 company는 null로 두세요.
- 상장된 회사라면 company_market에는 거래소(예: KRX, NASDAQ, NYSE 등), company_ticker에는 정확한 티커를 적으세요. 비상장이면 두 필드 모두 "비상장"으로 기입하고, 확실하지 않으면 null로 두세요.
- 추측하거나 부정확한 정보를 제공하지 마세요."""

    try:
        from PIL import Image
        image = Image.open(io.BytesIO(image_bytes))
    except Exception as exc:
        return None, None, f'이미지 로드 오류: {str(exc)}'

    last_error = None
    used_model = None
    response = None

    generation_config = {
        "temperature": 0.2,
        "top_p": 0.9,
        "top_k": 40,
    }

    for model_name in model_names:
        try:
            model = genai.GenerativeModel(model_name, generation_config=generation_config)
            response = model.generate_content([prompt, image])
            used_model = model_name
            break
        except Exception as exc:
            last_error = str(exc)
            logger.warning("Gemini generate_content 실패 (model=%s): %s", model_name, last_error)
            response = None

    if response is None:
        error_detail = f"사용 가능한 모델: {', '.join(available_models_clean) if available_models_clean else '없음'}"
        return None, None, f'모든 모델 시도 실패: {last_error}. {error_detail}'

    result, parse_error = extract_json_from_response_text(response.text.strip())
    if parse_error:
        return None, None, parse_error

    return result, used_model, None


def analyze_product_from_image(image_bytes: bytes) -> Dict:
    """
    Vision API + Gemini(텍스트) 기반으로 제품/브랜드 정보를 추출한다.
    실패 시 Gemini 직접 이미지 분석 결과를 함께 반환한다.

    Returns:
        {
            "vision_summary": str,
            "primary": {...},  # Vision → Gemini 결과
            "fallback": {...}, # Gemini 직접 분석 결과 (옵션)
            "used_fallback": bool,
        }
    """

    client = vision.ImageAnnotatorClient()
    image = vision_types.Image(content=image_bytes)
    features = [
        {"type_": vision_types.Feature.Type.LABEL_DETECTION},
        {"type_": vision_types.Feature.Type.TEXT_DETECTION},
        {"type_": vision_types.Feature.Type.LOGO_DETECTION},
        {"type_": vision_types.Feature.Type.OBJECT_LOCALIZATION},
    ]

    vision_response = client.annotate_image({"image": image, "features": features})
    summary = _summarize_vision_response(vision_response)

    # API 키는 환경 변수에서 가져옴
    api_key = os.getenv("GEMINI_API_KEY")
    selected_model = None  # 필요시 파라미터로 받을 수 있음

    primary_data, primary_model, primary_error = _call_gemini_with_text(summary, api_key=api_key, selected_model=selected_model)
    primary_result = {
        "model": primary_model,
        "object": None,
        "brand": None,
        "company": None,
        "company_market": None,
        "company_ticker": None,
        "error": primary_error,
    }
    if primary_data:
        primary_result.update(
            {
                "object": primary_data.get("object"),
                "brand": primary_data.get("brand"),
                "company": primary_data.get("company"),
                "company_market": _normalize_exchange_name(primary_data.get("company_market")),
                "company_ticker": primary_data.get("company_ticker"),
            }
        )

    fallback_result = None
    used_fallback = False

    if primary_error or not primary_data:
        fallback_data, fallback_model, fallback_error = _call_gemini_with_image(image_bytes, api_key=api_key, selected_model=selected_model)
        fallback_result = {
            "model": fallback_model,
            "object": None,
            "brand": None,
            "company": None,
            "company_market": None,
            "company_ticker": None,
            "error": fallback_error,
        }
        if fallback_data:
            fallback_result.update(
                {
                    "object": fallback_data.get("object"),
                    "brand": fallback_data.get("brand"),
                    "company": fallback_data.get("company"),
                    "company_market": _normalize_exchange_name(fallback_data.get("company_market")),
                    "company_ticker": fallback_data.get("company_ticker"),
                }
            )
        used_fallback = bool(fallback_data and not primary_data)

    # 기본 결과 구성
    final_result = {
        "vision_summary": summary,
        "primary": primary_result,
        "fallback": fallback_result,
        "used_fallback": used_fallback,
    }

    # 보강 정보 추가 (개발 단계에서 확인용)
    # primary 또는 fallback 중 성공한 결과 사용
    base_data = primary_data if primary_data else fallback_data
    if base_data:
        # 1) 지주회사 정보 보강
        try:
            enriched = augment_with_holding_info(
                base_data,
                resolver=resolve_holding_company,
                api_key=api_key,
                selected_model=selected_model,
                brand_candidates=None,
            )
            if enriched and enriched.get("holding_company"):
                final_result["holding_company"] = {
                    "holding_company": enriched.get("holding_company"),
                    "holding_market": enriched.get("holding_market"),
                    "holding_ticker": enriched.get("holding_ticker"),
                    "holding_sources": enriched.get("holding_sources", []),
                    "holding_confidence": enriched.get("holding_confidence"),
                }
        except Exception as e:
            logger.warning("지주회사 보강 실패: %s", str(e))

        # 2) 밸류체인 공급사 제안 (최대 2개)
        try:
            vc = suggest_value_chain_suppliers(
                object_name=base_data.get("object"),
                brand=base_data.get("brand"),
                text_hint=summary[:500] if summary else None,
                supplier_candidates=None,
                api_key=api_key,
                selected_model=selected_model,
                top_k=2,
            )
            if vc:
                final_result["value_chain"] = vc
        except Exception as e:
            logger.warning("밸류체인 제안 실패: %s", str(e))

        # 3) 관련 상장사 제안 (최대 3개)
        try:
            def _is_null(v):
                return (v is None) or (str(v).strip() == "") or (str(v).lower() == "null")
            if not (_is_null(base_data.get('object')) and _is_null(base_data.get('brand')) and _is_null(base_data.get('company'))):
                related = suggest_related_public_companies(
                    object_name=base_data.get("object"),
                    brand=base_data.get("brand"),
                    api_key=api_key,
                    selected_model=selected_model,
                    top_k=3,
                )
                if related and related.get("companies"):
                    final_result["related_public_companies"] = related.get("companies")
        except Exception as e:
            logger.warning("관련 상장사 제안 실패: %s", str(e))

    return final_result



