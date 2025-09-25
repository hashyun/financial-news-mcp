from dotenv import load_dotenv

# .env 파일에 정의된 환경 변수를 불러옵니다.
# 이 코드는 다른 import 구문들보다 먼저 실행되어야 합니다.
load_dotenv()

from finance_news import (
    app,
    _http_get,
    _fetch_yahoo_chart,
    _google_news_rss,
    _normalize_article,
    _yahoo_options_chain,
    _fred_fetch,
    _ecos_fetch,
    _dart_filings,
)

__all__ = [
    "app",
    "_http_get",
    "_fetch_yahoo_chart",
    "_google_news_rss",
    "_normalize_article",
    "_yahoo_options_chain",
    "_fred_fetch",
    "_ecos_fetch",
    "_dart_filings",
]


if __name__ == "__main__":
    app.run()
