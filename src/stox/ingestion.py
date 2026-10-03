from __future__ import annotations
import pandas as pd
import re
import logging
from .calendar import utc
from .storage import digest, now_iso
from .providers.alpaca import Alpaca, parse_bar
from .providers.sec import SEC
from .providers.fred import FRED
from .providers.alpha import AlphaVantage
from .universe import classify
from .security import SecurityMaster
from .providers.http import ProviderError

class Ingestor:
    def __init__(self, cfg, store, calendar, alpaca=None):
        self.cfg,self.store,self.calendar = cfg,store,calendar
        self.alpaca = alpaca or Alpaca(cfg.secrets)

    def _start(self, scope, overlap=3):
        previous = self.store.checkpoint(scope)
        return max(self.cfg.history_start,(pd.Timestamp(previous)-pd.Timedelta(days=overlap)).date().isoformat()) if previous else self.cfg.history_start

    def run(self, timestamp):
        now = utc(timestamp)
        session,end = self.calendar.sip_end(now)
        stamp = now.isoformat()
        self.store.storage_check(self.cfg.soft_storage_gb,self.cfg.hard_storage_gb)
        assets = self.alpaca.assets()
        master=SecurityMaster(self.store)
        for asset in assets:
            self.store.record('assets',asset.get('id') or 'unresolved:'+digest(asset),{**asset,'security_type':classify(asset)},stamp)
        master.refresh(assets,stamp)
        master.resolve_holdings()
        self.store.advance('assets',stamp)
        # Upgrade cached event provenance without discarding downloaded events or bar checkpoints.
        if self.store.checkpoint('action_identifier_schema')!='2':
            for action in self.store.records('actions'):
                normalized=master.annotate_action(action)
                self.store.record('actions',action.get('id') or digest(action),normalized,stamp)
            self.store.advance('action_identifier_schema','2')
        requests=master.requests(self.cfg)
        warnings=[]
        def summarize():
            diagnostics=master.persist_diagnostics(self.cfg,session)
            print('Universe: '+', '.join(f'{k}={v}' for k,v in diagnostics.items() if isinstance(v,int)))
        summarize()
        try:
            master.check_failure_budget(self.cfg)
            if not requests:
                raise RuntimeError('Universe validation failed: no authoritative active tradable tickers; inspect stox universe')
            for reference in requests:
                symbol=reference.ticker
                scope='bars:'+symbol
                existing=self.store.bars(symbol)
                checkpoint=self.store.checkpoint(scope)
                master.bind_history(reference,stamp)
                # v1 sometimes advanced checkpoints for empty responses. Verify durable data before reuse.
                if checkpoint==session and not existing.empty and session in set(existing.session):
                    continue
                self.store.storage_check(self.cfg.soft_storage_gb,self.cfg.hard_storage_gb)
                start=self.cfg.history_start if existing.empty else self._start(scope)
                if not existing.empty and checkpoint and existing.session.max()<checkpoint:
                    start=max(self.cfg.history_start,(pd.Timestamp(existing.session.max())-pd.Timedelta(days=3)).date().isoformat())
                if checkpoint and (existing.empty or existing.session.max()<checkpoint):
                    self.store.invalidate_checkpoint(scope,'Checkpoint has no matching durable completed-session data')
                count=0
                try:
                    for page in self.alpaca.bars([reference],start,end):
                        if any(k!=symbol for k in page):
                            raise ProviderError('Alpaca bars returned an unexpected symbol; response not merged')
                        rows=[parse_bar(symbol,r,self.calendar,stamp) for r in page.get(symbol,[]) or []]
                        rows=[r for r in rows if r['session']<=session]
                        count+=len(rows)
                        self.store.put_bars(symbol,pd.DataFrame(rows))
                except ProviderError as exc:
                    if exc.status_code in (400,404,422) and re.search(r'invalid symbol|symbol[^;\n]*(?:not found|not valid|unknown)',str(exc),re.I):
                        reason='provider rejected ticker: '+str(exc)
                        master.quarantine(reference,reason,stamp)
                        warnings.append(f'{symbol}: quarantined; {reason}')
                        master.check_failure_budget(self.cfg)
                        continue
                    # Credentials, rate limits, network errors and malformed request parameters stay fatal.
                    raise
                durable=self.store.bars(symbol)
                if durable.empty or session not in set(durable.session):
                    reason='no-price-history' if durable.empty else 'latest completed session missing'
                    self.store.health(scope,'WARN',reason+'; checkpoint not advanced')
                    warnings.append(f'{symbol}: {reason}; retry on next run')
                    continue
                self.store.advance(scope,session)
                self.store.health(scope,'PASS',f'{count} bars returned; completed session verified')
            self.store.health('alpaca-bars','WARN' if warnings else 'PASS',f'Completed-session processing through {session}; {len(warnings)} isolated security notices')
        finally:
            summarize()
        # Only approved references are passed into optional per-security enrichment.
        symbols=[r.ticker for r in master.requests(self.cfg)]
        # Core total-return feed. Any failure propagates and blocks fresh forecasts.
        for rows in self.alpaca.actions(self._start('actions',35),stamp):
            for row in rows:
                normalized=master.annotate_action(row)
                self.store.record('actions',row.get('id',digest(row)),normalized,stamp)
        self.store.advance('actions',stamp)
        self.store.health('actions','PASS','Corporate-action pagination completed; late announcements remain a provider limitation')
        try:
            for rows in self.alpaca.news(self._start('news',7),stamp):
                for row in rows:
                    # Current revised text cannot be backdated to its original creation time.
                    available = max(row['created_at'],row.get('updated_at') or row['created_at'])
                    self.store.record('news',row['id'],row,available,stamp)
            self.store.advance('news',stamp)
            self.store.health('news','PASS','News pagination completed')
        except Exception as exc:
            warnings.append(f'News unavailable: {exc}')
            self.store.health('news','WARN',str(exc))
        self.optional(symbols,stamp,warnings)
        return session,warnings

    def optional(self, symbols, stamp, warnings):
        try:
            sec = SEC(self.cfg.secrets.get('SEC_USER_AGENT'))
            mapping = sec.mappings()
            for symbol in symbols:
                if symbol not in mapping:
                    continue
                cik = mapping[symbol]
                reference=SecurityMaster(self.store).resolve(symbol)
                SecurityMaster(self.store).identifier(reference.alpaca_asset_id,'sec_cik',cik,'sec_edgar','ticker_mapping',stamp)
                scope = 'sec:'+cik
                if self.store.checkpoint(scope) and self.store.checkpoint(scope)[:10] == stamp[:10]:
                    continue
                filings,facts = sec.company(cik)
                for row in filings:
                    row['symbol'] = symbol
                    self.store.record('filings',row['accessionNumber'],row,row['available_at'],stamp)
                for row in facts:
                    row['symbol'] = symbol
                    rid = digest([cik,row['concept'],row['unit'],row.get('start'),row.get('end'),row.get('accn')])
                    self.store.record('facts',rid,row,row['available_at'],stamp)
                self.store.advance(scope,stamp)
            self.store.advance('sec',stamp)
            self.store.health('sec','PASS','Filings and company facts updated')
        except Exception as exc:
            warnings.append(f'SEC unavailable: {exc}')
            self.store.health('sec','WARN',str(exc))
        try:
            fred = FRED(self.cfg.secrets.get('FRED_API_KEY'))
            for series in self.cfg.macro_series:
                if self.store.checkpoint('fred:'+series) and self.store.checkpoint('fred:'+series)[:10] == stamp[:10]:
                    continue
                for rows in fred.observations(series,self.cfg.history_start,stamp):
                    for row in rows:
                        self.store.record('macro',f'{series}:{row["date"]}:{row["realtime_start"]}',row,row['available_at'],stamp)
                self.store.advance('fred:'+series,stamp)
            self.store.advance('fred',stamp)
            self.store.health('fred','PASS','Vintage-aware history refreshed')
        except Exception as exc:
            warnings.append(f'Macro unavailable: {exc}')
            self.store.health('fred','WARN',str(exc))
        if self.cfg.secrets.get('ALPHAVANTAGE_API_KEY'):
            try:
                if (self.store.checkpoint('alpha') or '')[:10] != stamp[:10]:
                    alpha = AlphaVantage(self.cfg.secrets['ALPHAVANTAGE_API_KEY'],self.store,self.cfg.av_daily_budget)
                    for row in alpha.earnings():
                        self.store.record('earnings',row['symbol']+':'+row['reportDate'],row,stamp)
                    self.store.advance('alpha',stamp)
                self.store.health('alpha','PASS','Earnings enrichment updated or cached')
            except Exception as exc:
                warnings.append(f'Optional earnings enrichment unavailable: {exc}')
                self.store.health('alpha','WARN',str(exc))
        else:
            warnings.append('Optional earnings calendar unavailable: Alpha Vantage is not configured')
            self.store.health('alpha','WARN','Not configured; upcoming earnings dates may be unknown')
