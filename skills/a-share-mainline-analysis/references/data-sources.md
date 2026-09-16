# Data Sources

## Domestic

The implementation reuses repository code instead of creating duplicate clients:

- `main_force_selector.py`: pywencai queries for stock-level main-force flow and
  industry labels. It may require an iwencai browser session when direct calls
  return 403.
- `sector_strategy_data.py`: AkShare industry/concept performance, sector fund
  flow, market breadth, index snapshot, and Eastmoney global finance news. The
  mainline collector keeps the recent seven-day domestic news window when the
  publication time can be parsed, while retaining undated rows with provenance.
- `ak.stock_info_global_cls()`: CLS 7x24 news when the installed AkShare version
  exposes the endpoint.

The domestic collector isolates each request. A missing sector table should not
discard a valid capital-flow or news result.

## International

`international_news.py` uses public HTTP JSON endpoints:

- NewsAPI Everything: `https://newsapi.org/v2/everything`
  - Requires `NEWSAPI_API_KEY`.
  - The module requests English articles and passes the configured date window.
  - Free plans can restrict historical range or rate limits; failures are
    recorded and do not stop the report.
- GDELT DOC remains as a compatibility adapter, but is disabled by default and
  is not called by the mainline workflow.

Relevant environment variables:

```text
NEWSAPI_API_KEY=
NEWSAPI_BASE_URL=https://newsapi.org/v2/everything
GDELT_DOC_API_URL=https://api.gdeltproject.org/api/v2/doc/doc
INTERNATIONAL_NEWS_TIMEOUT=15
INTERNATIONAL_NEWS_QUERY=
```

## Evidence Handling

Each normalized international article keeps provider, source/domain, title,
description, URL, publication time, language, and topic tags. Domestic news
keeps title, content, publication time, source, and URL. Theme evidence keeps
domestic and international hit counts separately, plus up to five matching
titles per source.

The scoring layer uses keyword matches only as an evidence count. Concept
performance and breadth are cross-confirmation, not a replacement for
stock-level flow. The current sector fund-flow row is kept separately from the
weekly/monthly cumulative stock-flow window. The LLM must not turn counts into
an asserted event unless the source title/content supports it. A theme is
stronger when its stock-level flow, latest sector flow, industry breadth,
concept performance, and news evidence agree.
