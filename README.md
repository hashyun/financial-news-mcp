# 📊 금융 데이터 분석 MCP 서버

Claude Desktop과 연동하여 **거시경제, 주식 시장, 개별 기업, 산업별 분석**을 제공하는 Model Context Protocol (MCP) 서버입니다.
금융 뉴스, 주가 차트, 경제지표, 공시정보를 자동으로 수집하고 아티팩트(표, 차트) 형태로 종합 분석 리포트를 생성합니다.

## 주요 기능

### 1. 🌍 거시경제 종합 분석
- **미국 경제지표**: GDP, 실업률, CPI/PPI, 연방기금금리, 국채수익률, 제조업지표 (FRED API)
- **한국 경제지표**: GDP, 실업률, 소비자물가, 기준금리, 수출입 (ECOS API)
- **글로벌 시장**: 환율, 달러인덱스, 원자재(원유/금/구리), VIX 공포지수
- 경제 뉴스와 함께 아티팩트로 대시보드 제공

### 2. 📈 시장 분석
- **한국 시장**: KOSPI/KOSPI200 차트, 원/달러 환율, 한국 국채금리, 뉴스
- **미국 시장**: S&P500/NASDAQ/DOW 차트, VIX, 미국 국채금리, 달러인덱스, 뉴스
- 시장 개요 테이블 및 시계열 차트로 투자 인사이트 제공

### 3. 🏢 개별 기업 심층 분석
- **주가 분석**: 차트, 기술적 지표, 옵션 체인 (미국 주식)
- **재무/공시**: DART 공시 자동 조회 (한국 상장기업 필수), 재무제표 분석
- **성장성 평가**: 매출/이익 증가율, R&D 투자, 신규 사업 계획
- 티커 또는 기업명 입력 시 자동 분석 리포트 생성

### 4. 🏭 산업별 분석
- **성장 가능성 높은 기업 발굴**: 재무 건전성 + 성장성 + 발전 가능성
- **지원 산업**: 반도체, 화장품, 자동차, 배터리, 바이오, 금융, 화학, 제약, 건설, 유통 등
- 각 기업의 DART 공시 분석, 주가 차트, 밸류에이션
- 산업 동향, 성장 기회, 투자 포인트 제공

## 🚀 빠른 시작

### 1. 설치
```bash
# 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt
```

### 2. API 키 설정 (선택사항)
`.env` 파일을 생성하여 API 키를 설정합니다 (`.env.example` 참고):

```bash
# DART (한국 공시 정보) - 필수 권장
DART_API_KEY=your_dart_api_key

# FRED (미국 경제지표) - 선택
FRED_API_KEY=your_fred_api_key

# BOK ECOS (한국 경제지표) - 선택
BOK_API_KEY=your_bok_api_key
```

**API 키 발급:**
- DART: https://opendart.fss.or.kr/
- FRED: https://fred.stlouisfed.org/docs/api/api_key.html
- BOK ECOS: https://ecos.bok.or.kr/

### 3. MCP 서버 실행
```bash
python server.py
```

## 🔗 Claude Desktop 연동

### 1. 설정 파일 수정
Claude Desktop 설정 파일을 열어 MCP 서버를 등록합니다:

**설정 파일 위치:**
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

**설정 추가:**
```json
{
  "mcpServers": {
    "finance-news": {
      "command": "python",
      "args": ["Your path\\server.py"],
      "description": "금융 데이터 분석 MCP 서버",
	  "env":{
		  "FRED_API_KEY":"Enter API KEY",
		  "BOK_API_KEY":"Enter API KEY",
		  "DART_API_KEY":"Enter API KEY"

	  }
    }
  }
}
```

> **주의**: `args`의 경로는 실제 `server.py` 파일의 **절대 경로**로 수정하세요.

### 2. Claude Desktop 재시작
설정 완료 후 Claude Desktop을 재시작하면 다음 프롬프트 버튼들이 나타납니다:

#### 📊 사용 가능한 프롬프트
- **🌍 거시경제 종합 분석** - 미국/한국 경제지표, 환율, 원자재 등 종합 분석
- **🇰🇷 한국 주식 시장 분석** - KOSPI, 환율, 국채금리 분석
- **🇺🇸 미국 주식 시장 분석** - S&P500, NASDAQ, VIX, 국채금리 분석
- **🏢 개별 기업 심층 분석** - 티커 입력 → 주가/재무/공시 종합 분석
- **🏭 산업별 분석** - 산업명 입력 → 성장 가능성 높은 기업 발굴

## 📖 사용 예시

### 예시 1: 반도체 산업 분석
1. **🏭 산업별 분석** 버튼 클릭
2. `industry` 필드에 "반도체" 입력
3. Claude가 자동으로:
   - 최근 뉴스 및 산업 동향 분석
   - 재무 건전성과 성장성 높은 기업 TOP 3 추천
   - 각 기업의 DART 공시, 주가 차트 분석
   - 아티팩트로 종합 리포트 생성

### 예시 2: 삼성전자 기업 분석
1. **🏢 개별 기업 심층 분석** 버튼 클릭
2. `ticker` 필드에 "005930.KS" 또는 "삼성전자" 입력
3. `period` 필드에 "1y" 입력 (1년 차트)
4. Claude가 자동으로:
   - 주가 차트 및 기술적 분석
   - DART 공시 정보 조회 (최근 실적, 신규 사업 등)
   - 재무제표 기반 성장성 평가
   - 투자 의견 및 목표가 제시

### 예시 3: 미국 시장 분석
1. **🇺🇸 미국 주식 시장 분석** 버튼 클릭
2. Claude가 자동으로:
   - S&P500, NASDAQ, DOW 차트
   - VIX 공포지수, 미국 10년물 국채금리
   - 달러인덱스, 최신 뉴스
   - 아티팩트로 시장 대시보드 생성

## 🛠️ 제공되는 MCP 도구

| 도구 이름 | 설명 |
|----------|------|
| `fetch_chart` | Yahoo Finance에서 주가 차트 (OHLCV) 데이터 조회 |
| `latest_news` | RSS 피드에서 최신 뉴스 수집 및 중복 제거 |
| `options_chain` | Yahoo Finance 옵션 체인 조회 (미국 주식) |
| `fred_series` | FRED API를 통한 미국 경제지표 조회 |
| `ecos_series` | 한국은행 ECOS API를 통한 한국 경제지표 조회 |
| `dart_filings` | DART API를 통한 한국 기업 공시 조회 |
| `industry_recommendations` | 산업별 재무제표 기반 기업 추천 |
| `list_industries` | 사용 가능한 산업 목록 조회 |

## ⚙️ 커스터마이징

### 뉴스 피드 추가
`feeds.yaml` 파일을 수정하여 RSS 피드를 추가/제거할 수 있습니다:

```yaml
sources:
  - name: "Reuters"
    url: "https://feeds.reuters.com/reuters/businessNews"
  - name: "한국경제"
    url: "https://www.hankyung.com/feed/economy"
```

### 심볼 맵 확장
`finance_news/data_sources.py`에서 티커 심볼 매핑을 추가할 수 있습니다:

```python
EQUITY_MAP = {
    "삼성전자": "005930.KS",
    "네이버": "035420.KS",
    # 추가...
}
```

## 🔒 보안 설정
- **HTTPS 전용**: 모든 외부 요청은 HTTPS로 제한
- **호스트 화이트리스트**: Yahoo Finance, Google News, FRED, ECOS, DART 등 신뢰된 도메인만 허용
- **환경변수로 보안 설정 가능**:
  - `FINANCE_NEWS_STRICT_SECURITY=1` (기본값, 화이트리스트 강제)
  - `FINANCE_NEWS_ALLOWED_HOSTS="host1,host2"` (추가 호스트 허용)

## 📝 라이선스 및 주의사항
API 키는 반드시 `.env` 파일에 저장하고 외부에 노출되지 않도록 주의하세요.
