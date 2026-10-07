from __future__ import annotations
import pandas as pd
import re
from .calendar import utc
from .storage import digest, now_iso
from .providers.alpaca import Alpaca, parse_bar
from .providers.sec import SEC
from .providers.fred import FRED
from .providers.alpha import AlphaVantage
from .universe import classify
from .security import SecurityMaster
from .providers.http import ProviderError
from .progress import Progress
from .streams import ingest_feed, reuse_legacy_actions, action_raw

class Ingestor:
    def __init__(self, cfg, store, calendar, alpaca=None, progress=None):
        self.cfg,self.store,self.calendar = cfg,store,calendar
        self.alpaca = alpaca or Alpaca(cfg.secrets)
        self.progress=progress or Progress(store,'ingestion-'+now_iso())

    def _start(self, scope, overlap=3):
        previous = self.store.checkpoint(scope)
        return max(self.cfg.history_start,(pd.Timestamp(previous)-pd.Timedelta(days=overlap)).date().isoformat()) if previous else self.cfg.history_start

    def run(self, timestamp):
        now = utc(timestamp)
        session,end = self.calendar.sip_end(now)
        stamp = now.isoformat()
        self.store.storage_check(self.cfg.soft_storage_gb,self.cfg.hard_storage_gb)
        master=SecurityMaster(self.store)
        with self.progress.stage('assets'):
            assets = self.alpaca.assets()
            with self.store.transaction():
                for asset in assets:
                    self.store.record('assets',asset.get('id') or 'unresolved:'+digest(asset),{**asset,'security_type':classify(asset)},stamp)
                master.refresh(assets,stamp)
                master.resolve_holdings()
                self.store.advance('assets',stamp)
            self.progress.update(processed=len(assets))
        requests=master.requests(self.cfg)
        warnings=[]
        def summarize():
            diagnostics=master.persist_diagnostics(self.cfg,session)
            print('Universe: '+', '.join(f'{k}={v}' for k,v in diagnostics.items() if isinstance(v,int)),flush=True)
        with self.progress.stage('universe'):
            summarize()
            master.check_failure_budget(self.cfg)
            if not requests:
                raise RuntimeError('Universe validation failed: no authoritative active tradable tickers; inspect stox universe')
        with self.progress.stage('bars',total=len(requests)):
            try:
                self.bars(requests,master,session,end,stamp,warnings)
            finally:
                summarize()
        with self.progress.stage('legacy-action-index'):
            reuse_legacy_actions(self.store,master,self.progress)
        symbols=[r.ticker for r in master.requests(self.cfg)]
        with self.progress.stage('corporate-actions'):
            self.events('actions',master,stamp,session)
        try:
            with self.progress.stage('news'):
                self.events('news',master,stamp,session)
        except Exception as exc:
            warnings.append(f'News unavailable: {exc}')
            self.store.health('news','WARN',str(exc))
        self.optional(symbols,stamp,warnings)
        return session,warnings

    def bars(self,requests,master,session,end,stamp,warnings):
        skipped=0
        for index,reference in enumerate(requests):
            symbol=reference.ticker
            scope='bars:'+symbol
            summary=self.store.bar_summary(symbol)
            checkpoint=self.store.checkpoint(scope)
            master.bind_history(reference,stamp)
            if checkpoint==session and summary and summary['last_session']==session:
                skipped+=1
                if index%100==0: self.progress.update(processed=index+1,skipped=skipped)
                continue
            self.store.storage_check(self.cfg.soft_storage_gb,self.cfg.hard_storage_gb)
            # Even an interrupted first-ever symbol download has durable partial Parquet.
            # Resume with a bounded overlap, not history_start when no final checkpoint exists.
            start=self.cfg.history_start if not summary else max(self.cfg.history_start,
                (pd.Timestamp(summary['last_session'])-pd.Timedelta(days=3)).date().isoformat())
            if checkpoint and (not summary or summary['last_session']<checkpoint):
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
                    self.progress.update(processed=index+1,skipped=skipped,errors=len(warnings))
                    continue
                raise
            durable=self.store.bar_summary(symbol)
            if not durable or durable['last_session']!=session:
                reason='no-price-history' if not durable else 'latest completed session missing'
                self.store.health(scope,'WARN',reason+'; checkpoint not advanced')
                warnings.append(f'{symbol}: {reason}; retry on next run')
            else:
                with self.store.transaction():
                    self.store.advance(scope,session)
                    self.store.health(scope,'PASS',f'{count} bars returned; completed session verified')
            self.progress.update(processed=index+1,skipped=skipped,errors=len(warnings))
        self.progress.update(processed=len(requests),skipped=skipped,errors=len(warnings))
        self.store.meta('warehouse',{'symbols':len(requests),'skipped_completed':skipped,'session':session})
        self.store.health('alpaca-bars','WARN' if warnings else 'PASS',f'Completed-session processing through {session}; {len(warnings)} isolated security notices')

    def events(self,feed,master,stamp,session):
        def consume(rows):
            inserted=skipped=0
            for row in rows:
                if feed=='actions':
                    raw=action_raw(row)
                    rid=str(raw.get('id') or digest(raw)); raw_hash=digest(raw)
                    if self.store.db.execute('SELECT 1 FROM action_sources WHERE record_id=? AND raw_hash=?',(rid,raw_hash)).fetchone():
                        skipped+=1
                        continue
                    normalized=master.annotate_action(raw)
                    # Availability is actual observation, never the start of a multi-day run.
                    available=now_iso()
                    revision=self.store.record('actions',rid,normalized,available,available)
                    self.store.db.execute('INSERT INTO action_sources VALUES(?,?,?,?)',(rid,raw_hash,revision,available))
                    inserted+=1
                else:
                    available=max(row['created_at'],row.get('updated_at') or row['created_at'])
                    revision=digest(row)
                    if self.store.db.execute('SELECT 1 FROM records WHERE kind=? AND record_id=? AND revision=?',('news',str(row['id']),revision)).fetchone():
                        skipped+=1
                    else:
                        self.store.record('news',row['id'],row,available)
                        inserted+=1
            return inserted,skipped
        checkpoint=self.store.checkpoint(feed)
        pending=self.store.db.execute('SELECT status FROM feed_jobs WHERE scope=?',(feed,)).fetchone()
        # Brief repeat invocations reuse a covered snapshot. Later runs poll bounded
        # correction overlaps; metadata exposes the precise provider cutoff.
        if checkpoint and utc(checkpoint)>=utc(stamp)-pd.Timedelta(minutes=self.cfg.event_refresh_minutes) and (feed!='actions' or utc(checkpoint)>=self.calendar.close(session)) and not (pending and pending[0]=='running'):
            self.progress.update(skipped=1,note='completed snapshot reused')
            return
        overlap=35 if feed=='actions' else 7
        completed=ingest_feed(self.store,self.alpaca,feed,self._start(feed,overlap),stamp,consume,self.progress)
        # A multi-day interrupted job must finish its frozen request before catching up to now.
        if completed[:10]<stamp[:10]:
            ingest_feed(self.store,self.alpaca,feed,self._start(feed,overlap),stamp,consume,self.progress)

    def optional(self, symbols, stamp, warnings):
        try:
            with self.progress.stage('sec',total=len(symbols)):
                sec = SEC(self.cfg.secrets.get('SEC_USER_AGENT'))
                mapping = sec.mappings()
                sec_target=self.store.checkpoint('sec:target') or stamp
                self.store.advance('sec:target',sec_target)
                master=SecurityMaster(self.store)
                for index,symbol in enumerate(symbols):
                    if symbol not in mapping: continue
                    cik = mapping[symbol]
                    reference=master.resolve(symbol)
                    # Stable observation, not a new effective-date row on every run.
                    master.identifier(reference.alpaca_asset_id,'sec_cik',cik,'sec_edgar','ticker_mapping')
                    scope = 'sec:'+cik
                    if self.store.checkpoint(scope) and self.store.checkpoint(scope)[:10] == sec_target[:10]:
                        self.progress.update(processed=index+1)
                        continue
                    filings,facts = sec.company(cik,store=self.store,snapshot=sec_target[:10])
                    rows=[('filings',r['accessionNumber'],r) for r in filings]
                    rows.extend(('facts',digest([cik,r['concept'],r['unit'],r.get('start'),r.get('end'),r.get('accn')]),r) for r in facts)
                    for offset in range(0,len(rows),1000):
                        with self.store.transaction():
                            for kind,rid,row in rows[offset:offset+1000]:
                                row['symbol']=symbol
                                self.store.record(kind,rid,row,row['available_at'])
                    self.store.advance(scope,sec_target)
                    self.progress.update(processed=index+1)
                with self.store.transaction():
                    self.store.advance('sec',sec_target)
                    self.store.db.execute("DELETE FROM checkpoints WHERE scope='sec:target'")
                self.store.health('sec','PASS','Filings and company facts updated')
        except Exception as exc:
            warnings.append(f'SEC unavailable: {exc}')
            self.store.health('sec','WARN',str(exc))
        try:
            with self.progress.stage('fred',total=len(self.cfg.macro_series)):
                fred = FRED(self.cfg.secrets.get('FRED_API_KEY'))
                for index,series in enumerate(self.cfg.macro_series):
                    scope='fred:'+series
                    if self.store.checkpoint(scope) and self.store.checkpoint(scope)[:10] == stamp[:10]: continue
                    while not self.store.checkpoint(scope) or self.store.checkpoint(scope)[:10] < stamp[:10]:
                        # Provider page offset and frozen vintage cutoff are persisted atomically.
                        target=self.store.checkpoint(scope+':target') or stamp
                        offset=int(self.store.checkpoint(scope+':offset') or 0)
                        vintage_start=self.store.checkpoint(scope) or '1776-07-04'
                        for rows,next_offset,done in fred.observation_pages(series,self.cfg.history_start,target,offset,vintage_start):
                            with self.store.transaction():
                                for row in rows:
                                    self.store.record('macro',f'{series}:{row["date"]}:{row["realtime_start"]}',row,row['available_at'])
                                self.store.advance(scope+':target',target)
                                self.store.advance(scope+':offset',next_offset)
                                if done:
                                    self.store.advance(scope,target)
                                    self.store.db.execute('DELETE FROM checkpoints WHERE scope IN (?,?)',(scope+':target',scope+':offset'))
                                self.progress.update(processed=index,pages=self.progress.counters['pages']+1)
                self.store.advance('fred',stamp)
                self.store.health('fred','PASS','Vintage-aware history refreshed')
        except Exception as exc:
            warnings.append(f'Macro unavailable: {exc}')
            self.store.health('fred','WARN',str(exc))
        with self.progress.stage('earnings'):
            if self.cfg.secrets.get('ALPHAVANTAGE_API_KEY'):
                try:
                    if (self.store.checkpoint('alpha') or '')[:10] != stamp[:10]:
                        alpha = AlphaVantage(self.cfg.secrets['ALPHAVANTAGE_API_KEY'],self.store,self.cfg.av_daily_budget)
                        rows=alpha.earnings()
                        with self.store.transaction():
                            for row in rows:
                                self.store.record('earnings',row['symbol']+':'+row['reportDate'],row,now_iso())
                            self.store.advance('alpha',stamp)
                    self.store.health('alpha','PASS','Earnings enrichment updated or cached')
                except Exception as exc:
                    self.progress.update(errors=1)
                    warnings.append(f'Optional earnings enrichment unavailable: {exc}')
                    self.store.health('alpha','WARN',str(exc))
            else:
                warnings.append('Optional earnings calendar unavailable: Alpha Vantage is not configured')
                self.store.health('alpha','WARN','Not configured; upcoming earnings dates may be unknown')
