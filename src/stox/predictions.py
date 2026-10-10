from __future__ import annotations
import json
import numpy as np
from .actions import relevant, total_return, UnresolvedAction
from .storage import digest, encode, now_iso
from .calendar import utc


def issue(store,calendar,rows,issued_at,metadata):
    by_symbol={}
    for row in rows:
        by_symbol.setdefault(row['symbol'],[]).append(row)
    # No timestamp, rank or prose in identity: retries and A -> B -> A reuse A.
    fields=('symbol','horizon','session','model_id','p_gain','p_above_2','p_above_5',
            'expected_return','median_return','p_loss_5','p_loss_10','p_loss_20',
            'quantiles_10_50_90','qualified','model_validated','consistency_status','exclusions','close')
    signature=digest([metadata.get('run_mode',metadata.get('mode','live')),
                      metadata.get('market_session'),metadata.get('data_digest'),
                      metadata.get('friction_bps'),
                      [{k:r.get(k) for k in fields} for r in sorted(rows,key=lambda r:(r['symbol'],r['horizon']))]])
    ids=[]
    with store.transaction():
        previous=store.db.execute('SELECT forecast_id FROM forecast_snapshot_members WHERE signature=? ORDER BY symbol',(signature,)).fetchall()
        if previous:
            return [r[0] for r in previous]
        store.db.execute('INSERT OR IGNORE INTO forecast_snapshots VALUES(?,?,?)',(signature,issued_at,encode(metadata)))
        for symbol,forecasts in sorted(by_symbol.items()):
            entry=calendar.next_open(issued_at)
            payload={'forecasts':[{k:v for k,v in r.items() if k!='catalyst_context'} for r in forecasts],'catalyst_context':forecasts[0].get('catalyst_context',{}),'snapshot_signature':signature,
                     'metadata':{k:metadata[k] for k in ('run_mode','mode','friction_bps','fixture_only') if k in metadata},
                     'targets':{str(r['horizon']):calendar.settle(entry,r['horizon']) for r in forecasts},
                     'information_cutoff':metadata['event_cutoff'],'entry_session':entry}
            # A change elsewhere in the universe must not duplicate this symbol.
            # Values, qualification, model, session and friction identify its snapshot.
            fid=digest([metadata.get('run_mode',metadata.get('mode','live')),symbol,
                        metadata.get('friction_bps'),
                        [{k:r.get(k) for k in fields} for r in sorted(forecasts,key=lambda r:r['horizon'])]])[:32]
            store.db.execute('INSERT OR IGNORE INTO forecasts VALUES(?,?,?,?,?)',(fid,issued_at,symbol,entry,encode(payload)))
            store.db.execute('INSERT INTO forecast_snapshot_members VALUES(?,?,?)',(signature,symbol,fid))
            ids.append(fid)
    return ids

def settle(store,calendar,timestamp,friction):
    completed=calendar.completed(timestamp)
    actions=store.records('actions')
    settled,pending,warnings=0,0,[]
    cached_symbol=None
    bars=None
    benchmarks={s:store.bars(s) for s in ('SPY','QQQ')}
    benchmarks={s:b.set_index('session') for s,b in benchmarks.items() if not b.empty}
    # Completed snapshots need no price reads; group pending snapshots by security.
    query="SELECT f.* FROM forecasts f WHERE (SELECT count(*) FROM outcomes o WHERE o.forecast_id=f.id)<json_array_length(f.payload,'$.forecasts') ORDER BY f.symbol"
    for f in store.db.execute(query):
        if cached_symbol!=f['symbol']:
            bars=store.bars(f['symbol'])
            if not bars.empty: bars=bars.set_index('session')
            cached_symbol=f['symbol']
        if bars.empty:
            pending+=1
            continue
        entry=store.db.execute('SELECT * FROM entries WHERE forecast_id=?',(f['id'],)).fetchone()
        if entry is None and f['entry_session']<=completed and f['entry_session'] in bars.index:
            with store.db:
                store.db.execute('INSERT OR IGNORE INTO entries VALUES(?,?,?,?)',(f['id'],float(bars.loc[f['entry_session'],'open']),now_iso(),'alpaca:sip:raw:daily-open'))
            entry=store.db.execute('SELECT * FROM entries WHERE forecast_id=?',(f['id'],)).fetchone()
        if entry is None:
            pending+=1
            continue
        payload=json.loads(f['payload'])
        cost=payload.get('metadata',{}).get('friction_bps',friction)
        for h,end in payload['targets'].items():
            if end>completed or end not in bars.index:
                continue
            if store.db.execute('SELECT 1 FROM outcomes WHERE forecast_id=? AND horizon=?',(f['id'],int(h))).fetchone():
                continue
            try:
                ret=total_return(entry['price'],float(bars.loc[end,'close']),f['entry_session'],end,relevant(actions,f['symbol']),cost)
            except UnresolvedAction as exc:
                warnings.append(f'{f["symbol"]} {h}D outcome unresolved: {exc}')
                continue
            bench={}
            for symbol in ('SPY','QQQ'):
                b=benchmarks.get(symbol)
                if b is not None:
                    if f['entry_session'] in b.index and end in b.index:
                        try:
                            bench[symbol]=total_return(float(b.loc[f['entry_session'],'open']),float(b.loc[end,'close']),f['entry_session'],end,relevant(actions,symbol),cost)
                        except UnresolvedAction:
                            pass
            detail={'entry_price':entry['price'],'exit_price':float(bars.loc[end,'close']), 'friction_bps':cost,
                    'benchmarks':bench,'recorded_at':now_iso(),'actions_digest':digest(relevant(actions,f['symbol']))}
            with store.db:
                store.db.execute('INSERT INTO outcomes VALUES(?,?,?,?,?)',(f['id'],int(h),end,ret,encode(detail)))
            settled+=1
    return {'newly_settled':settled,'pending_entries':pending,'warnings':warnings}

def _performance(store, cohort):
    groups={}
    rows=store.db.execute('SELECT f.payload AS forecast_payload,f.issued_at,o.* FROM outcomes o JOIN forecasts f ON f.id=o.forecast_id')
    for r in rows:
        pred=next(p for p in json.loads(r['forecast_payload'])['forecasts'] if p['horizon']==r['horizon'])
        meta=json.loads(r['forecast_payload']).get('metadata',{})
        mode=meta.get('run_mode',meta.get('mode','live'))
        if mode in ('synthetic','offline') or meta.get('fixture_only'):
            continue
        if cohort=='qualified' and not pred['qualified']:
            continue
        if cohort=='research_only' and pred['qualified']:
            continue
        # Do not retain the repeated multi-horizon forecast/evidence payload per outcome.
        compact={k:r[k] for k in ('horizon','net_return','payload','issued_at','session')}
        prediction={k:pred.get(k) for k in ('p_gain','primary_rank','expected_return')}
        groups.setdefault(r['horizon'],[]).append((compact,prediction))
    output={}
    for h,pairs in groups.items():
        y=np.array([r['net_return'] for r,p in pairs])
        p=np.array([p['p_gain'] for r,p in pairs])
        first=[r['net_return'] for r,p in pairs if p.get('primary_rank')==1]
        top3=[r['net_return'] for r,p in pairs if (p.get('primary_rank') or 999)<=3]
        output[str(h)]={'n':len(y),'hit_rate':float((y>0).mean()),'brier':float(np.mean((p-(y>0))**2)),
                        'mean_return':float(y.mean()),'median_return':float(np.median(y)),'worst_loss':float(y.min()),
                        'top1_hit_rate':float(np.mean(np.array(first)>0)) if first else None,
                        'top3_hit_rate':float(np.mean(np.array(top3)>0)) if top3 else None,
                        'benchmark_excess':{s:float(np.mean([r['net_return']-json.loads(r['payload'])['benchmarks'][s] for r,p in pairs if s in json.loads(r['payload'])['benchmarks']])) if any(s in json.loads(r['payload'])['benchmarks'] for r,p in pairs) else None for s in ('SPY','QQQ')}}
        bucket_stats=[]
        for b in range(10):
            mask=np.minimum((p*10).astype(int),9)==b
            if mask.any():
                bucket_stats.append({'bucket':b,'n':int(mask.sum()),'probability':float(p[mask].mean()),'win_rate':float((y[mask]>0).mean())})
        output[str(h)]['calibration_buckets']=bucket_stats
        output[str(h)]['calibration_error']=sum(b['n']*abs(b['probability']-b['win_rate']) for b in bucket_stats)/len(y)
        expected=[pred.get('expected_return') for r,pred in pairs]
        valid=[i for i,e in enumerate(expected) if e is not None]
        output[str(h)]['return_mae']=float(np.mean([abs(expected[i]-y[i]) for i in valid])) if valid else None
        output[str(h)]['mean_expected_return']=float(np.mean([expected[i] for i in valid])) if valid else None
        output[str(h)]['loss_frequency_5_10_20']={str(t):float(np.mean(y < -t)) for t in (.05,.10,.20)}
        for k in (1,3):
            cohorts={}
            for r,pred in pairs:
                if (pred.get('primary_rank') or 999)<=k:
                    cohorts.setdefault(r['issued_at'],[]).append(r)
            last_exit='0000-00-00'
            values=[]
            for stamp,group in sorted(cohorts.items()):
                if stamp[:10]>last_exit:
                    values.append(float(np.mean([r['net_return'] for r in group])))
                    last_exit=max(r['session'] for r in group)
            equity=np.cumprod(1+np.array(values))
            output[str(h)][f'top{k}_nonoverlap_total_return']=float(equity[-1]-1) if len(equity) else None
            output[str(h)][f'top{k}_nonoverlap_max_drawdown']=float((equity/np.maximum.accumulate(np.r_[1,equity])[1:]-1).min()) if len(equity) else None
            output[str(h)][f'top{k}_nonoverlap_cohorts']=len(equity)
    return {'kind':'prospective','horizons':output,'cohort':cohort,'note':'Live prospective outcomes only; synthetic and historical backtests excluded.'}


def performance(store):
    qualified=_performance(store,'qualified')
    return {**qualified,'research_only':_performance(store,'research_only'),
            'all_research':_performance(store,'all'), 'qualified':qualified}
