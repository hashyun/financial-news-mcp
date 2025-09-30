from __future__ import annotations

# Minimal‑risk version of tools.py (no async, minimal typing, no new deps)
import logging
from typing import List, Optional

from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP

from .data_sources import (
    _fetch_yahoo_chart,
    _news_all,
    _yahoo_options_chain,
    _fred_fetch,
    _ecos_fetch,
    _dart_filings,
    _get_industry_recommendations,
    INDUSTRY_MAP,
)

# -----------------------------------------------------------------------------
# MCP App
# -----------------------------------------------------------------------------
app = FastMCP(
    name="finance-news"
)

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
class ChartArgs(BaseModel):
    symbol: str = Field(..., description="Ticker symbol or index alias (e.g., AAPL, ^GSPC, KRW=X)")
    range: str = Field("1mo", description="Yahoo Finance range, e.g., 1d, 5d, 1mo, 6mo, 1y, 5y, max")
    interval: str = Field("1d", description="Yahoo Finance interval, e.g., 1m, 5m, 15m, 1d, 1wk, 1mo")


class OptionsArgs(BaseModel):
    symbol: str = Field(..., description="Ticker symbol, e.g., AAPL")
    expiration: Optional[str] = Field(None, description="YYYY-MM-DD (optional)")


class FREDArgs(BaseModel):
    series_ids: List[str] = Field(..., description="FRED series IDs")
    start: Optional[str] = Field(None, description="YYYY-MM-DD")
    end: Optional[str] = Field(None, description="YYYY-MM-DD")
    frequency: Optional[str] = Field(None, description="e.g., m, q")
    aggregation_method: Optional[str] = Field(None, description="e.g., avg, sum")
    # Artifact-friendly options
    tidy: bool = Field(True, description="표(아티팩트)로 보기 좋게 가공")
    drop_na: bool = Field(True, description="value가 비어있는 관측치 제거")
    value_as_float: bool = Field(True, description="값을 float로 파싱 시도")


class EcosArgs(BaseModel):
    stat_code: str = Field(..., description="ECOS 통계 코드 (e.g., 722Y001)")
    start: str = Field(..., description="시작 (주기별 포맷: YYYY, YYYYMM 등)")
    end: str = Field(..., description="끝 (주기별 포맷)")
    cycle: str = Field(..., description="주기: D/M/Q/Y")
    item_code1: Optional[str] = Field(None)
    item_code2: Optional[str] = Field(None)
    item_code3: Optional[str] = Field(None)


class DartArgs(BaseModel):
    corp_name: Optional[str] = Field(None, description="기업명 (fallback 검색)")
    corp_code: Optional[str] = Field(None, description="DART 기업 코드 (정식 API용)")
    bgn_de: Optional[str] = Field(None, description="YYYYMMDD")
    end_de: Optional[str] = Field(None, description="YYYYMMDD")
    page_count: int = Field(10, description="가져올 문서 개수")


class IndustryRecommendArgs(BaseModel):
    industry: str = Field(..., description="산업군 (예: 반도체, 화장품, 자동차, 배터리, 바이오, 금융 등)")
    year: int = Field(2023, description="재무제표 조회 년도")
    top_n: int = Field(3, description="추천할 상위 기업 수")


# -----------------------------------------------------------------------------
# Tools
# -----------------------------------------------------------------------------
@app.tool()
def fetch_chart(args: ChartArgs):
    """Fetch historical price chart for a symbol."""
    return _fetch_yahoo_chart(args.symbol, args.range, args.interval)


@app.tool()
def latest_news(limit: int = 10):
    """Return the latest news items from configured feeds."""
    items = _news_all()[:limit]
    return {"items": items}


@app.tool()
def options_chain(args: OptionsArgs):
    """Yahoo options chain for a symbol."""
    return _yahoo_options_chain(args.symbol, args.expiration)


@app.tool()
def fred_series(args: FREDArgs):
    """Fetch FRED series observations; returns artifact‑friendly table + raw JSON."""
    raw = _fred_fetch(args)

    # tidy=False면 원본만 반환
    if not args.tidy:
        return {"raw": raw}

    def _parse_value(v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str) and v.strip() == ".":
            return None
        try:
            return float(v)
        except Exception:
            return None

    rows = []
    for sid, payload in (raw or {}).items():
        obs = (payload or {}).get("observations") or []
        for o in obs:
            date_str = o.get("date")
            val_raw = o.get("value")
            val = _parse_value(val_raw) if args.value_as_float else val_raw
            if args.drop_na and (val is None or val == ""):
                continue
            rows.append({
                "series_id": sid,
                "date": date_str,
                "value": val,
            })

    chart_hint = {
        "x": "date",
        "y": "value",
        "group": "series_id" if len(args.series_ids) > 1 else None,
    }

    return {
        "rows": rows,          # ← Claude에서 표/시계열 아티팩트로 보기 좋게 렌더
        "chart_hint": chart_hint,
        "raw": raw,            # ← 원본도 같이 반환
    }


@app.tool()
def ecos_series(args: EcosArgs):
    """Fetch ECOS(BOK) series as-is."""
    try:
        data = _ecos_fetch(args)
        return data
    except Exception as e:
        logging.exception("ecos_series failed")
        return {"error": str(e)}


@app.tool()
def dart_filings(args: DartArgs):
    """Fetch DART filing list (API with corp_code, or fallback news search by corp_name)."""
    try:
        return _dart_filings(
            corp_name=args.corp_name,
            corp_code=args.corp_code,
            bgn_de=args.bgn_de,
            end_de=args.end_de,
            page_count=args.page_count,
        )
    except Exception as e:
        logging.exception("dart_filings failed")
        return {"error": str(e)}


@app.tool()
def industry_recommendations(args: IndustryRecommendArgs):
    """산업군별 재무제표 기반 우량 기업 추천. 사용 가능한 산업군: 반도체, 화장품, 자동차, 배터리, 바이오, 금융, 화학, 제약, 건설, 유통"""
    try:
        return _get_industry_recommendations(
            industry=args.industry,
            year=args.year,
            top_n=args.top_n,
        )
    except Exception as e:
        logging.exception("industry_recommendations failed")
        return {"error": str(e)}


@app.tool()
def list_industries():
    """사용 가능한 산업군 목록 조회"""
    return {
        "available_industries": list(INDUSTRY_MAP.keys()),
        "industries": INDUSTRY_MAP,
    }


# -----------------------------------------------------------------------------
# Prompts (시장/산업 분석 버튼)
# -----------------------------------------------------------------------------

# === 1. 거시경제 분석 ===
@app.prompt()
def analyze_macro_economy():
    """🌍 거시경제 종합 분석"""
    return """
글로벌 거시경제를 종합 분석하고, 결과를 아티팩트(표, 차트)로 제공해주세요:

**📊 미국 경제지표 (FRED API 활용):**
- GDP 성장률: GDP, GDPC1
- 실업률: UNRATE
- 인플레이션: CPIAUCSL (CPI), PPIACO (PPI)
- 금리: FEDFUNDS (연방기금금리), DGS10 (10년물 국채), DGS2 (2년물 국채)
- 제조업: MANEMP (제조업 고용)
- 소비: PCE (개인소비지출)
- 주택: HOUST (주택착공)

**📊 한국 경제지표 (ECOS API 활용):**
- GDP 성장률: 통계코드 조회
- 실업률
- 소비자물가지수
- 기준금리
- 수출입 데이터
- 제조업 생산지수

**📊 글로벌 시장지표 (fetch_chart 활용):**
- 환율: KRW=X (원/달러), EURUSD=X, JPY=X
- 달러인덱스: DX=F
- 원자재: CL=F (WTI 원유), GC=F (금), HG=F (구리)
- VIX 공포지수

**📰 최근 동향:**
- 최신 경제 뉴스 (latest_news)

**📈 종합 분석 리포트 (아티팩트로 작성):**
1. 주요 지표 대시보드 테이블
2. 시계열 차트 (최근 6개월~1년)
3. 지역별 경제 상황 요약
4. 투자 시사점 및 리스크 요인
5. 향후 전망
"""


# === 2. 시장 분석 ===
@app.prompt()
def analyze_korean_market():
    """🇰🇷 한국 주식 시장 분석"""
    return """
한국 주식 시장을 다음 항목으로 종합 분석하고, 결과를 아티팩트(표, 차트)로 제공해주세요:

**1. 주요 지표 분석**
- KOSPI, KOSPI200 차트 (fetch_chart 활용, range="1mo")
- 원/달러 환율 차트 (fetch_chart 활용, symbol="KRW=X")
- 한국 국채 금리 (ecos_series 활용, 적절한 통계코드 사용)

**2. 최근 시장 동향**
- 최신 금융 뉴스 (latest_news 활용, limit=20)
- 주요 이슈 및 시장 심리 파악

**3. 종합 분석 리포트**
결과를 다음 형식의 아티팩트로 작성:
- 시장 개요 테이블 (지수, 환율, 금리 현황)
- 차트 (시계열 데이터)
- 투자 인사이트 및 주요 리스크 요인
"""


@app.prompt()
def analyze_us_market():
    """🇺🇸 미국 주식 시장 분석"""
    return """
미국 주식 시장을 다음 항목으로 종합 분석하고, 결과를 아티팩트(표, 차트)로 제공해주세요:

**1. 주요 지표 분석**
- S&P 500, NASDAQ100, DOW 차트 (fetch_chart 활용, range="1mo")
- VIX 공포지수 차트 (fetch_chart 활용)
- 미국 10년물 국채 금리 (fred_series 활용, series_ids=["DGS10"])
- 달러 인덱스 (fetch_chart 활용, symbol="DX=F")

**2. 최근 시장 동향**
- 최신 금융 뉴스 (latest_news 활용, limit=20)
- 주요 이슈 및 시장 심리 파악

**3. 종합 분석 리포트**
결과를 다음 형식의 아티팩트로 작성:
- 시장 개요 테이블 (지수, 금리, VIX 현황)
- 차트 (시계열 데이터)
- 투자 인사이트 및 주요 리스크 요인
"""


# === 3. 개별 기업 분석 ===
@app.prompt()
def analyze_company(
    ticker: str,
    period: str = "6mo"
):
    """🏢 개별 기업 심층 분석

    Args:
        ticker: 티커 심볼 또는 기업명 (예: AAPL, 005930.KS, 삼성전자)
        period: 차트 기간 (1mo, 3mo, 6mo, 1y, 5y)
    """
    return f"""
**{ticker}** 기업을 다음 항목으로 심층 분석하고 아티팩트로 제공해주세요:

**1. 기업 정보 확인**
- 티커 심볼로 상장 여부 확인
- 한국 상장기업인지 판단 (티커에 .KS, .KQ 포함 또는 한글 기업명)

**2. 주가 분석**
- 최근 {period} 차트 분석 (fetch_chart, range="{period}")
- 옵션 체인 분석 (options_chain, 미국 주식인 경우)
- 주요 기술적 지표 및 추세

**3. 재무/공시 정보 (필수)**
- **한국 상장기업인 경우 DART 공시 필수 조회** (dart_filings)
  - corp_name 또는 corp_code로 최근 공시 정보 조회
  - 주요 공시 내용 요약 (실적 발표, 신규 사업, 투자 계획 등)
- 재무제표 주요 지표 분석
  - 매출 성장률, 영업이익률
  - ROE, 부채비율, 유동비율
  - **성장성 지표: 매출 증가 추세, R&D 투자 비중**
- 관련 뉴스 분석 (latest_news)

**4. 종합 리포트 (아티팩트로 작성)**
- 기업 개요 및 사업 모델
- 주가 동향 및 기술적 분석
- **재무 건전성 및 성장 가능성 평가**
  - 안정적인 재무구조
  - 매출/이익 성장 추세
  - 신규 사업 및 성장 동력
- **최근 공시 분석 (한국 상장기업 필수)**
- 투자 의견 및 목표가
- **위험 요인 및 모니터링 포인트**

*주의: 한국 상장기업의 경우 DART 공시 조회는 필수입니다. 비상장 기업이거나 미국/해외 기업인 경우 생략 가능합니다.
"""


# === 4. 산업별 분석 ===
@app.prompt()
def analyze_industry(
    industry: str
):
    """🏭 산업별 분석

    Args:
        industry: 산업명 (예: 반도체, 화장품, 자동차, 배터리, 바이오, 금융, 화학, 제약, 건설, 유통, 엔터테인먼트, 항공, 게임 등)
    """

    # 주요 산업 목록
    major_industries = ["반도체", "화장품", "자동차", "배터리", "바이오", "금융", "화학", "제약", "건설", "유통"]

    industry_note = ""
    if industry in major_industries:
        industry_note = f"\n*{industry}는 재무제표 기반 기업 추천이 가능한 산업입니다."

    return f"""
**{industry} 산업**을 다음 항목으로 종합 분석하고 아티팩트로 제공해주세요:{industry_note}

**1. 산업 동향**
- 최근 뉴스 및 이슈 분석 (latest_news)
- 시장 규모 및 성장성
- 주요 트렌드 및 변화
- 산업 내 성장 기회 요인

**2. 성장 가능성 높은 기업 발굴**
- 재무제표 기반 기업 분석 (industry_recommendations, industry="{industry}", 가능한 경우)
- **선정 기준:**
  - ✅ 재무 건전성: ROE, 부채비율, 유동비율
  - ✅ 성장성: 매출 증가율, 영업이익 성장 추세
  - ✅ 발전 가능성: 신규 사업, R&D 투자, 시장 확대 전략
- 각 기업의 재무 지표 비교 테이블
- 시장 점유율 및 경쟁 구도

**3. 추천 기업 심층 분석 (필수)**
- 주가 차트 및 모멘텀 분석 (fetch_chart)
- **각 기업의 DART 공시 정보 필수 조회** (dart_filings)
  - 최근 주요 공시: 실적 발표, 신규 사업 계획, 투자 유치
  - 성장 전략 및 사업 확장 계획
- 밸류에이션 분석 (PER, PBR, PSR 등)
- **성장 동력 분석**

**4. 투자 인사이트 (아티팩트로 작성)**
- 산업 전망 및 성장 기회
- **추천 기업별 투자 포인트**
  - 재무적 강점
  - 성장 가능성 (신규 사업, 시장 확대)
  - 밸류에이션 매력도
- 리스크 요인 및 모니터링 포인트
- **공시 기반 최근 이슈 및 향후 주목할 이벤트**

*주의: 추천된 한국 상장기업들의 DART 공시 조회는 필수입니다.
"""


__all__ = [
    "app",
    "fetch_chart",
    "latest_news",
    "options_chain",
    "fred_series",
    "ecos_series",
    "dart_filings",
    "industry_recommendations",
    "list_industries",
]
