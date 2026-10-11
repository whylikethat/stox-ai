"""Recent, batched discovery; long history is reserved for the selected universe."""
from __future__ import annotations
import json
import re
import pandas as pd
from .storage import digest, encode
from .providers.alpaca import parse_bar
from .providers.http import ProviderError


def select_universe(ingestor, master, references, session, end, stamp):
    cfg,store=ingestor.cfg,ingestor.store
    floor=(pd.Timestamp(session)-pd.Timedelta(days=cfg.screen_lookback_days)).date().isoformat()
    missing=[]
    for ref in references:
        receipt=store.db.execute('SELECT session,asset_id FROM universe_screen WHERE symbol=?',(ref.ticker,)).fetchone()
        if not receipt or receipt['session']!=session or receipt['asset_id']!=ref.alpaca_asset_id:
            missing.append(ref)
    for offset in range(0,len(missing),cfg.screen_batch_size):
        batch=missing[offset:offset+cfg.screen_batch_size]
        allowed={r.ticker for r in batch}
        frames={s:[] for s in allowed}
        starts=[]
        for ref in batch:
            previous=store.db.execute('SELECT * FROM universe_screen WHERE symbol=?',(ref.ticker,)).fetchone()
            path=store.root/'cache'/'screen'/(digest(ref.ticker)[:20]+'.parquet')
            if previous and previous['asset_id']==ref.alpaca_asset_id and path.exists():
                cached=pd.read_parquet(path)
                frames[ref.ticker]=cached[cached.session>=floor].to_dict('records')
                starts.append(max(floor,(pd.Timestamp(previous['session'])-pd.Timedelta(days=3)).date().isoformat()))
            else:
                starts.append(floor)
        batch_start=min(starts)
        # Only this recent range is fetched for the broad market, never history_start.
        def pages(refs):
            try:
                yield from ingestor.alpaca.bars(refs,batch_start,end)
            except ProviderError as exc:
                if exc.status_code not in (400,404,422) or not re.search(r'invalid symbol|symbol.*(?:not found|not valid|unknown)',str(exc),re.I):
                    raise
                if len(refs)>1:
                    middle=len(refs)//2
                    yield from pages(refs[:middle])
                    yield from pages(refs[middle:])
                else:
                    master.quarantine(refs[0],'provider rejected ticker: '+str(exc),stamp)
                    master.check_failure_budget(cfg)
        for page in pages(batch):
            if set(page)-allowed:
                raise ProviderError('Unexpected ticker in universe screening response')
            for symbol,rows in page.items():
                frames[symbol].extend(parse_bar(symbol,r,ingestor.calendar,stamp) for r in rows)
        with store.transaction():
            for ref in batch:
                frame=pd.DataFrame(frames[ref.ticker])
                if not frame.empty:
                    frame=frame[frame.session.between(floor,session)].drop_duplicates('session',keep='last').sort_values('session')
                summary={'rows':len(frame),'close':None,'dollar_volume':None,'last_session':None}
                if not frame.empty:
                    summary.update(close=float(frame.iloc[-1].close),dollar_volume=float((frame.close*frame.volume).tail(60).median()),last_session=str(frame.iloc[-1].session))
                    directory=store.root/'cache'/'screen'
                    directory.mkdir(parents=True,exist_ok=True)
                    path=directory/(digest(ref.ticker)[:20]+'.parquet')
                    tmp=path.with_suffix('.tmp')
                    frame.to_parquet(tmp,index=False,compression='zstd')
                    tmp.replace(path)
                store.db.execute('INSERT OR REPLACE INTO universe_screen VALUES(?,?,?,?)',(ref.ticker,ref.alpaca_asset_id,session,encode(summary)))
        ingestor.progress.update(processed=min(offset+len(batch),len(missing)),total=len(missing))
    summaries={r['symbol']:json.loads(r['payload']) for r in store.db.execute('SELECT * FROM universe_screen WHERE session=?',(session,))}
    assets={a['symbol']:a for a in master.assets()}
    liquidity=max(cfg.min_dollar_volume,cfg.liquidity_reference_usd/cfg.max_participation)
    candidates=[]
    exclusions={}
    for ref in references:
        try:
            master.resolve(ref.ticker)
        except ValueError:
            exclusions[ref.ticker]=['quarantined or unresolved security']
            continue
        s=summaries.get(ref.ticker,{})
        reasons=[]
        if s.get('last_session')!=session: reasons.append('missing current completed session')
        if s.get('rows',0)<cfg.screen_min_sessions: reasons.append('insufficient recent sessions')
        if (s.get('close') or 0)<cfg.min_price: reasons.append('price below minimum')
        if (s.get('dollar_volume') or 0)<liquidity: reasons.append('insufficient recent median dollar liquidity')
        cap=assets.get(ref.ticker,{}).get('market_cap')
        if cap is not None and assets[ref.ticker]['security_type']=='common' and float(cap)<300_000_000:
            reasons.append('reported micro-cap')
        if reasons: exclusions[ref.ticker]=reasons
        else: candidates.append(ref)
    candidates.sort(key=lambda r:(-summaries[r.ticker]['dollar_volume'],r.ticker))
    mandatory=({'SPY','QQQ'}|set(__import__('stox.features',fromlist=['SECTOR_ETFS']).SECTOR_ETFS) if cfg.autonomous_universe else {'SPY','QQQ'})|set(cfg.symbols)|{r[0] for r in store.db.execute('SELECT symbol FROM holdings WHERE active=1')}|{r[0] for r in store.db.execute('SELECT symbol FROM watchlist')}
    selected={r.ticker:r for r in candidates[:cfg.universe_size]}
    for ref in references:
        if ref.ticker in mandatory:
            try: selected[ref.ticker]=master.resolve(ref.ticker)
            except ValueError: pass
    snapshot={'session':session,'symbols':sorted(selected),'screened':len(references),'liquid_candidates':len(candidates),
              'limit':cfg.universe_size,'mandatory_exceptions':{s:exclusions[s] for s in sorted(mandatory) if s in exclusions},
              'note':'Current-universe selection has survivorship bias. Alpaca does not guarantee market-cap metadata; price/liquidity screening is not proof of capitalization.'}
    store.meta('modeling_universe',snapshot)
    return [selected[s] for s in sorted(selected)]
