---
name: a-share-mainline-analysis
description: Analyze China A-share market structure and produce weekly/monthly mainline, secondary themes, core leaders, sentiment cycle, sustainability, next-day watchlist, and candidate stocks. Use when the user asks what the A-share market is trading, which sectors may lead this week or month, how to combine main-force capital flow with domestic/international news, or how to generate a short-term swing-trading stock pool.
---

# A-Share Mainline Analysis

Use the repository implementation in `mainline_analysis.py`. It combines existing
pywencai and AkShare adapters with `international_news.py`, using NewsAPI as the
active international-news provider.

## Workflow

1. Collect two capital-flow windows: from the current week's Monday and from
   the first day of the current month. The international news lookback defaults
   to seven days.
2. Collect AkShare industry/concept performance, sector fund flow, market breadth,
   and domestic finance news. The collector also attempts the CLS 7x24 feed.
3. Fetch international finance news from NewsAPI for the recent seven-day
   window. The mainline workflow does not call GDELT.
4. Normalize source records, remove duplicate news, and retain source status.
5. Merge fine-grained industries into compact directions such as agriculture,
   metals, mining, oil and gas, technology, chip/semiconductor, and storage.
   Score themes with capital flow as the primary evidence, then combine industry
   breadth/performance, concept cross-confirmation, domestic news, and
   international-news matches. The current sector fund-flow signal is included
   separately from the weekly/monthly stock-flow window. News is a catalyst,
   not proof of capital commitment.
6. Build up to ten candidates separately for each leading sector and separately
   for `weekly` and `monthly`. Keep only stock codes beginning with `6` or `3`;
   never invent a symbol, price, or statistic.
7. Use the supplied market-structure prompt for optional DeepSeek synthesis.
   Treat the deterministic result as the fallback when the API key or any data
   source is unavailable.
   When higher-quality synthesis is needed, enable DeepSeek thinking mode with
   `reasoning_effort=low|high|max`. Keep the model's internal reasoning hidden;
   only parse and display the final JSON conclusion. For structured output,
   request JSON output from the API and keep the deterministic stock-pool
   constraints after the model response.
8. The Streamlit page presents a compact result: the top weekly and monthly
   sectors, the strongest sector in each window, and up to ten eligible stocks
   under each sector. The detailed eight-section report remains available to
   programmatic/CLI consumers.

## Commands

Run a deterministic analysis without an LLM:

```bash
python mainline_analysis.py --no-ai --no-newsapi --output data/mainline/latest.json
```

Run with NewsAPI:

```bash
python mainline_analysis.py --output data/mainline/latest.json
```

Run with DeepSeek thinking mode:

```bash
python mainline_analysis.py --thinking --reasoning-effort high \
  --output data/mainline/latest.json
```

Use `--query` to narrow international coverage, for example:

```bash
python mainline_analysis.py --query "(China OR Chinese) (semiconductor OR AI OR tariffs)"
```

## Output Rules

- Lead with market structure, not with the most sensational headline.
- Separate a real mainline from a one-day pulse, a secondary theme, and a
  follow-through group.
- Label candidate roles as emotion leader, trend core, or lower-position
  observation candidate only when the available data supports it.
- State when 连板高度, 炸板率, or成交额数据 is unavailable.
- A high news count is a catalyst signal, not proof of capital commitment.
- Weekly means capital flow from the current Monday; monthly means capital flow
  from the first day of the current month. The default news window is seven days
  and must be labeled as recent catalyst evidence for both periods.
- Keep domestic and international news evidence separate, and distinguish
  industry sectors from concept themes.
- If weekly and monthly leaders do not overlap, lower confidence and describe the
  market as rotation-prone.
- If no theme clears the baseline evidence threshold, output exactly:
  `主线不清、轮动为主、降低预期`.
- Recommendations are a research watchlist, not a buy/sell instruction.

Read `references/data-sources.md` when changing providers, query windows,
normalization rules, or environment variables.
