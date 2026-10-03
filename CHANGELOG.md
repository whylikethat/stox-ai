# Changelog

## 2.0.1 — 2026-10-03

- Fixed the SIP doctor query starting after daily bars' midnight timestamps; use five completed historical calendar sessions and a strict 16-minute safety margin, including immediately after close.
- Validate actual finite completed SIP OHLCV bars and explain empty/invalid HTTP 200 responses with sanitized request-window/count diagnostics.
- Replaced the combined FRED/ALFRED canary with a small DGS10 observation check; added optional independent `doctor --live --vintages` as-of validation.
- Preserve useful HTTP error messages while redacting request credentials, credential fields and encoded echoes; bound diagnostic output.
- Added offline regression coverage for temporal boundaries, valid/invalid observations, vintage isolation, provider restriction errors and credential redaction.

## 2.0.0 — 2026-10-03

- Clean-sheet local, on-demand application with 20/30/60/90-calendar-day forecasts.
- Added Alpaca/SEC/FRED and budgeted optional Alpha Vantage adapters, checkpointed ingestion and revision provenance.
- Added purged time-series modeling, separate calibration, holdout evaluation, qualification and champion/challenger tracking.
- Added immutable forecast history, next-open paper entries, per-horizon total-return outcomes and manual holdings reviews.
- Added terminal/HTML/JSON/Markdown/AI-review reports, operator commands, secret-safe setup, storage gates and offline tests.
- Documented unavailable live validation and remaining corporate-action, historical-universe, event and scale limitations.
