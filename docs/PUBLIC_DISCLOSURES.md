# Public transaction disclosures

These are delayed public filings, not nonpublic information or trading signals. No disclosure fields enter features, model training, ranking, probability calibration, or qualification gates. No paid vendor or additional API subscription is used. Network/storage and local processing still have costs.

## Enable

From the existing checkout and activated virtual environment:

```bash
python -m pip install -e '.[disclosures]'
```

Add these keys inside the existing `[stox]` section of your config (do not replace the file):

```toml
enable_insider_disclosures = true
enable_house_disclosures = false
congressional_terms_acknowledged = false
disclosure_documents_per_run = 10
disclosure_lookback_days = 90
```

SEC collection uses already ingested SEC filing metadata. Keep `enable_sec = true` and configure `SEC_USER_AGENT` with your application/contact email in the existing provider secrets file. `sec_symbols_per_run` still controls filing metadata coverage; enabling ownership collection does not instantly cover every issuer.

Review the official House and Senate terms before enabling congressional collection or importing their reports. Only for a permitted use, set `congressional_terms_acknowledged = true`; set `enable_house_disclosures = true` for automatic House collection. This acknowledgement is not a license or a legal determination that your use is permitted. The app cannot enforce downstream use restrictions.

```bash
stox disclosures sync
stox disclosures list
stox run
```

Normal online runs also perform the enabled bounded collection stage. Offline runs do not fetch disclosures. First-observed timestamps control context availability; a document fetched after a run's initial cutoff appears in a subsequent report. Unresolved assets remain visible through `disclosures list`; they are not assigned to a forecast by name similarity.

## Actual coverage

* **SEC:** official `www.sec.gov/Archives/edgar/data/` ownership XML discovered from existing local SEC submissions metadata. Forms 3, 4, 5 and `/A` amendments; nonderivative and derivative holdings/transactions. Issuer CIK/name/reported ticker, reporting-owner identifiers/relationships, security title, transaction date/code, acquired/disposed, shares, price, post-transaction holdings, ownership nature, referenced footnotes and original XML field values. Form 3 holdings retain a distinct record type. The transaction code, not a guessed buy/sell label, is retained. Decimal quantities/prices stay strings. Derivatives are never assigned to a common-stock ticker for report context.
* **House:** official annual `financial-pdfs/{year}FD.zip` XML indexes, `FilingType=P`, and `ptr-pdfs/{year}/{DocID}.pdf`. Filer/index filing date/document ID; extractable transaction type, date, notification date, asset text, owner column and dollar range. Explicit `(TICKER) [ST]` can match the current security master. PDF extraction is **always labeled partial**: scanned pages, layouts, wrapped names and other row fields can be missing. Original bytes and row text are retained. No OCR or fabricated fields. Annual/non-P reports are excluded; amendment discovery completeness is not guaranteed.
* **Senate:** import saved official report HTML with a recognized transaction table. Transaction date, owner, explicit ticker, asset name, transaction type, dollar range and original table fields. HTML is conservatively labeled partial because attachments/layouts can be missed. PDF imports are retained as unparsed. **No automatic Senate discovery:** the official site returned HTTP 403 in this environment; no consent/access controls are bypassed. Download reports manually only as the site permits.

Example Senate import (replace placeholders with the actual file, official report URL, and filing date):

```bash
stox disclosures import --source senate --file /path/to/report.html \
  --url 'https://efdsearch.senate.gov/search/view/ptr/ACTUAL-REPORT-ID/' \
  --filing-date YYYY-MM-DD
```

Imports also support `--source sec` or `house`, `--acceptance-at` and `--publication-at` (ISO timestamps with timezone), and `--amends` (known original accession or official URL). Do not supply a trade date as a filing/publication timestamp. Congress filing dates do not establish an exact publication time; unknown timestamps remain null. SEC acceptance times without offsets are interpreted in America/New_York, following the existing submissions convention. Acceptance is distinct from publication and observation.

## Availability, identity, revisions, and limits

All records retain source URL, source hash, first observation and revision availability. Availability is conservatively local observation time even when the transaction is much older. Imports therefore cannot manufacture historical backtest knowledge. Amendments remain separate filings, with SEC `/A` and original submission date retained; explicit `--amends` can link other corrections. Original and amended transactions must not be summed. Same-URL content changes create new immutable rows; current report context selects the latest observed content. Reimporting identical content is a no-op. Metadata-only corrections on identical bytes are not currently applied.

Only an explicit ticker that uniquely matches the active, queryable current master can resolve. No issuer-name guessing, CUSIP/CIK conversion, Alpaca symbol requests, watchlist changes, or identity inference from politician names. Current ticker matches are not guarantees of historical identity. Source URLs/import metadata are caller-supplied provenance, not authentication of locally supplied bytes.

At most 1–100 document attempts per sync (default 10); 1–365 days of disclosure lookback independently of prices/news; at most two annual House indexes; one request per second, 10/30-second connect/read timeouts, 20 MB response/import cap and 100 PDF pages. Failed requests are retried on later runs; HTTP redirects/access refusals are not bypassed. Each completed document is committed atomically. Successful URLs are revisited after seven days for corrections within the lookback window. Ctrl-C rolls back an incomplete document; rerunning resumes completed-document receipts. No paid fallbacks. Persistent failures can delay later documents under the per-run cap.

No schema migration or data reset is required: existing versioned `records` and checkpoints store metadata/rows. Content-addressed original documents live under `.stox/cache/disclosures/`. Originals are intentionally retained for audit; there is no automatic evidence deletion. This adds disk usage over time. Optional failures warn and allow the core forecast pipeline to continue. Parser errors/unparsed documents are not evidence that no transactions occurred.

JSON, Markdown, HTML and terminal forecast context include resolved records under `public_transactions`. `stox disclosures list` shows document coverage and all transaction revisions, including unresolved rows. No aggregated insider/congressional performance claims are made. No new status-time network calls are added.

## Official sources and terms

* [SEC Form 4](https://www.sec.gov/files/form4.pdf)
* [SEC developer access policy](https://www.sec.gov/about/developer-resources)
* [House financial disclosure downloads](https://disclosures-clerk.house.gov/FinancialDisclosure)
* [House prohibited-use notice](https://disclosures-clerk.house.gov/FinancialDisclosure/ViewSearch)
* [Senate disclosure search and use notice](https://efdsearch.senate.gov/search/home/)

Congressional disclosures are free to access, not unrestricted commercial data. Notices prohibit unlawful uses, commercial purposes (with the stated news/communications exception), determining credit ratings, and solicitations for political, charitable or other purposes. Read the complete current official notices; no automatic agreement or submission is performed by this collector. Commercial redistribution/use is outside the intended implementation.

## Files changed for this addition

New: `src/stox/disclosures.py`, `tests/test_disclosures.py`, `docs/PUBLIC_DISCLOSURES.md`.

Updated: `src/stox/cli.py`, `src/stox/config.py`, `src/stox/ingestion.py`, `src/stox/engine.py`, `src/stox/reporting.py`, `pyproject.toml`, `config.example.toml`, `README.md`. Existing unrelated edits remain in place. No user runtime configuration, schema, models, or live `.stox` data was changed for this implementation.
