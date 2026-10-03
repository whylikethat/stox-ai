from __future__ import annotations
import pandas as pd
from .calendar import utc
from .storage import digest, now_iso
from .providers.alpaca import Alpaca, parse_bar
from .providers.sec import SEC
from .providers.fred import FRED
from .providers.alpha import AlphaVantage
from .universe import classify

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
        for asset in assets:
            asset = {**asset,'security_type':classify(asset)}
            self.store.record('assets',asset['id'],asset,stamp)
        self.store.advance('assets',stamp)
        # Preserve inactive names for historical datasets; unknown instrument types stay excluded.
        candidates = [a for a in assets if classify(a) in ('common','etf')]
        symbols = sorted({a['symbol'] for a in candidates} | {'SPY','QQQ'} | {r[0] for r in self.store.db.execute('SELECT symbol FROM holdings WHERE active=1')})
        if self.cfg.symbols:
            symbols = sorted(set(self.cfg.symbols) | {'SPY','QQQ'} | {r[0] for r in self.store.db.execute('SELECT symbol FROM holdings WHERE active=1')})
        for symbol in symbols:
            scope = 'bars:'+symbol
            if self.store.checkpoint(scope) == session:
                continue
            self.store.storage_check(self.cfg.soft_storage_gb,self.cfg.hard_storage_gb)
            count = 0
            for page in self.alpaca.bars([symbol],self._start(scope),end):
                rows = [parse_bar(symbol,r,self.calendar,stamp) for r in page.get(symbol,[])]
                rows = [r for r in rows if r['session'] <= session]
                count += len(rows)
                self.store.put_bars(symbol,pd.DataFrame(rows))
            # An empty successful response may be an inactive security, but never grants eligibility.
            self.store.advance(scope,session)
            self.store.health(scope,'PASS' if count else 'WARN',f'{count} bars returned')
        self.store.health('alpaca-bars','PASS',f'SIP completed-session query through {session}')
        # Core total-return feed. Any failure propagates and blocks fresh forecasts.
        for rows in self.alpaca.actions(self._start('actions',35),stamp):
            for row in rows:
                self.store.record('actions',row.get('id',digest(row)),row,stamp)
        self.store.advance('actions',stamp)
        self.store.health('actions','PASS','Corporate-action pagination completed; late announcements remain a provider limitation')
        warnings = []
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
