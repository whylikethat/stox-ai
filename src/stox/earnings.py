"""Bounded earnings ingestion; revised vendor history is safe only after observation."""
import math
import numpy as np
import pandas as pd
from .storage import now_iso
from .security import SecurityMaster
from .providers.alpha import AlphaVantage


def parse_earnings(symbol, rows, observed):
    output=[]
    for r in rows:
        try:
            if pd.isna(pd.Timestamp(r['fiscalDateEnding'])) or pd.isna(pd.Timestamp(r['reportedDate'])):continue
            fiscal=pd.Timestamp(r['fiscalDateEnding']).date().isoformat()
            reported=pd.Timestamp(r['reportedDate']).date().isoformat()
            if reported<fiscal: continue
            value=float(r['surprisePercentage'])/100
            if not math.isfinite(value): continue
            # Date-only release metadata is conservatively available the following day.
            publication=(pd.Timestamp(reported)+pd.Timedelta(days=1)).tz_localize('America/New_York').tz_convert('UTC')
            available=max(publication,pd.Timestamp(observed))
            output.append({'symbol':symbol,'fiscal_end':fiscal,'reported_date':reported,'report_time':r.get('reportTime'),
                           'reported_eps':r.get('reportedEPS'),'estimated_eps':r.get('estimatedEPS'),
                           'surprise':value,'observed_at':observed,'publication_bound':publication.isoformat(),
                           'available_at':available.isoformat(),'source_url':'https://www.alphavantage.co/query?function=EARNINGS&symbol='+symbol})
        except (ValueError,TypeError,KeyError,OverflowError): continue
    return output


def ingest_earnings(cfg,store,symbols,stamp):
    client=AlphaVantage(cfg.secrets.get('ALPHAVANTAGE_API_KEY'),store,cfg.av_daily_budget)
    master=SecurityMaster(store)
    assets={r['symbol']:r for r in master.assets()}
    candidates=sorted([s for s in set(symbols) if assets.get(s,{}).get('security_type')=='common'],key=lambda s:(store.checkpoint('earnings-history:'+s) or store.checkpoint('earnings-attempt:'+s) or '',s))
    count=0;failures=0
    for symbol in candidates:
        if count>=cfg.earnings_symbols_per_run: break
        last=store.checkpoint('earnings-history:'+symbol)
        attempt=store.checkpoint('earnings-attempt:'+symbol)
        if last and pd.Timestamp(stamp)-pd.Timestamp(last)<pd.Timedelta(days=30):continue
        if attempt and attempt[:10]==stamp[:10]:continue
        count+=1
        try:
            ref=master.resolve(symbol) # Strict namespace resolution before ticker endpoint.
            raw=client.history(ref.ticker)
            observed=now_iso()
            rows=parse_earnings(symbol,raw,observed)
            with store.transaction():
                for r in rows:
                    identity=symbol+':'+r['fiscal_end']
                    prior=store.db.execute("SELECT payload FROM records WHERE kind='earnings_history' AND record_id=? ORDER BY ingested_at DESC LIMIT 1",(identity,)).fetchone()
                    if prior:
                        import json
                        old=json.loads(prior[0])
                        if all(old.get(k)==r.get(k) for k in ('reported_date','reported_eps','estimated_eps','surprise','report_time')):continue
                    store.record('earnings_history',identity,r,r['available_at'])
                store.advance('earnings-history:'+symbol,stamp)
        except (ValueError,RuntimeError) as exc:
            failures+=1
        finally:store.advance('earnings-attempt:'+symbol,stamp)
    store.health('earnings-history','WARN' if failures else 'PASS',f'{count} symbols attempted; {failures} unavailable. History usable only after observation.')



def enrich_earnings(frame,store,cfg):
    if cfg is not None and not cfg.enable_alpha_vantage:return frame
    records=store.records('earnings_history')
    for symbol,indices in frame.groupby('symbol').groups.items():
        events=sorted([r for r in records if r.get('symbol')==symbol],key=lambda r:r['available_at'])
        for idx in indices:
            cutoff=pd.Timestamp(frame.at[idx,'issue_at'])
            known={}
            for r in events:
                if pd.Timestamp(r['available_at'])<=cutoff:known[r['fiscal_end']]=r
            latest=sorted(known.values(),key=lambda r:r['fiscal_end'])[-4:]
            if latest:
                r=latest[-1];days=(cutoff-pd.Timestamp(r['publication_bound'])).total_seconds()/86400
                if 0<=days<=180:
                    frame.at[idx,'earnings_surprise']=np.clip(r['surprise'],-2,2)
                    frame.at[idx,'earnings_days_since']=days
                    frame.at[idx,'earnings_positive_fraction']=np.mean([r['surprise']>0 for r in latest])
            # Provider dates are estimates, not confirmed company announcements. Keep context-only.
    return frame
