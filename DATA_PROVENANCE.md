# Data provenance and contracts

Provider contracts were inspected on 2026-10-03. This is documentation review, not credentialed endpoint validation. Run `stox doctor --live` locally to test actual entitlements.

| Source | Uses | Availability treatment |
|---|---|---|
| Alpaca historical SIP bars | Raw daily OHLCV, paper-price references, benchmarks | Completed XNYS session; end older than 16 minutes; raw prices, no hidden dividend adjustments |
| Alpaca assets | Active/inactive identity provenance; only verified active/tradable tickers authorize new bars | First local observation and changed snapshots; not retroactively certified historical membership |
| Alpaca corporate actions | Splits, distributions, event context | Full revision payload retained; effective/ex-date separated from local observation |
| Alpaca news | Provider-delivered headlines/summaries, IDs, authors, URLs, symbols | Revised text available no earlier than `updated_at`; original locally observed payloads retained |
| SEC submissions | Accessions, forms, accepted times, historical submission pages | Acceptance time; date-only records conservatively delayed to the next day |
| SEC company facts | Accession-specific US-GAAP values and periods | Join accession to acceptance; never replace all earlier facts with a restatement |
| FRED/ALFRED | Rates, curve, labor, inflation and credit | Vintage dates with a one-day lag; later revisions remain distinct |
| Alpha Vantage | Optional three-month earnings calendar | First observation; persisted daily request budget, including failed calls |

## Calendar and returns

For issuance at time `t`, select the first XNYS session with `open > t`. The horizon target is that session's date plus the configured number of calendar days. Settle at the first XNYS close on/after the target date. The same clock is used for training and prospective accounting.

Start with one share purchased at raw daily open `P0`. For ex-dates strictly after entry and through settlement, multiply units by verified split ratios and accrue cash distributions per then-held unit. Net total return is `(ending units * raw settlement close + accrued distributions) / P0 - 1 - friction_bps / 10000`. Entry on an ex-date does not receive that distribution. No dividend reinvestment, FX or personal tax assumptions. Complex corporate transformations without a verified successor valuation are unresolved, not zero-return outcomes.

Daily SIP bars are trade-condition aggregates, not a certified exchange-auction fill. Alpaca's documentation excludes extended-hours conditions from daily prices but includes them in volume. Accordingly, production price/volume features lag volume one session. This avoids using a finalized evening volume in an earlier historical after-close decision. Exact official auction-price verification remains a limitation of the daily-reference convention.

## Revision handling and limits

Each normalized event has its provider payload, stable identity, availability timestamp, ingestion timestamp and payload hash. First locally observed values and revisions remain separate. Bar rewrites preserve the previous observed row; historical feature windows affected by locally discovered corrections are excluded until correction availability. This cannot reconstruct unobserved earlier revisions in a newly downloaded history.

News replay uses a seven-day overlap; corporate-action replay uses a 35-day overlap. All missed pages over the offline gap are fetched. These windows catch ordinary overlapping updates, not arbitrary edits to remote history outside the replay interval. Per-feed gaps and optional failures remain visible in health state.

Historical asset coverage and security-type classification are approximations. No assumption of perfect delisting, merger or ticker-chain reconstruction is warranted. Symbol mapping is disabled in bar queries to avoid silently relabeling an entity's entire history under today's ticker. This reduces renamed-security history rather than inventing it.

## Primary references

- [Alpaca historical bars](https://docs.alpaca.markets/us/reference/stockbars)
- [Alpaca aggregation and SIP-delay rules](https://docs.alpaca.markets/us/docs/market-data-faq)
- [Alpaca news](https://docs.alpaca.markets/us/reference/news-3)
- [Alpaca corporate actions](https://docs.alpaca.markets/us/reference/corporateactions-1)
- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [FRED/ALFRED observations](https://fred.stlouisfed.org/docs/api/fred/series_observations.html)
- [Alpha Vantage documentation](https://www.alphavantage.co/documentation/)


## Typed identifier provenance (2.0.2)

Corporate-action IDs and CUSIP/ISIN/FIGI/asset references are not ticker fields. Raw payloads remain available, while normalized `security_references` identify type, role, authoritative asset mapping (if any) and queryability. Old/new identifiers in distributions, renames and reverse splits do not automatically alter the universe. A CUSIP may resolve to a ticker only via an explicit authoritative asset mapping; it is never submitted to stock historical-bars `symbols`. SEC CIK enrichment and event-only mappings cannot authorize price queries. Historical identifiers retain provenance without implying a reconstructed ticker chain.


## Resume receipts (2.0.3)

Provider action identity excludes derived local security annotations. Original raw
versions, effective dates, first-seen/availability timestamps and typed references
are retained. Legacy rows do not establish provider pagination completeness; a
receipt backfill supports safe reuse without guessing a completed range. Date windows
and correction overlaps do not guarantee capture of revisions announced outside
provider coverage/lookback. See [BOOTSTRAP_REPAIR](docs/BOOTSTRAP_REPAIR.md).

Reference contracts reviewed for this repair:
- [Alpaca corporate actions](https://docs.alpaca.markets/us/v1.1/reference/corporateactions-1)
- [SEC prospectus describing the QQQ Trust Series 1 structure](https://www.sec.gov/Archives/edgar/data/1067839/000119312524187704/d733468d497.htm)
