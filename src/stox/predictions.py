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
    ids=[]
    with store.db:
        for symbol,forecasts in by_symbol.items():
            if not any(r['qualified'] for r in forecasts):
                continue
            entry=calendar.next_open(issued_at)
            payload={'forecasts':forecasts,'metadata':metadata,'targets':{str(r['horizon']):calendar.settle(entry,r['horizon']) for r in forecasts},
                     'information_cutoff':metadata['event_cutoff'],'entry_session':entry}
            fid=digest([issued_at,symbol,entry,payload])[:32]
            store.db.execute('INSERT OR IGNORE INTO forecasts VALUES(?,?,?,?,?)',(fid,issued_at,symbol,entry,encode(payload)))
            ids.append(fid)
    return ids

def settle(store,calendar,timestamp,friction):
    completed=calendar.completed(timestamp)
    actions=store.records('actions')
    settled,pending,warnings=0,0,[]
    for f in store.db.execute('SELECT * FROM forecasts').fetchall():
        bars=store.bars(f['symbol'])
        if bars.empty:
            pending+=1
            continue
        bars=bars.set_index('session')
        entry=store.db.execute('SELECT * FROM entries WHERE forecast_id=?',(f['id'],)).fetchone()
        if entry is None and f['entry_session']<=completed and f['entry_session'] in bars.index:
            with store.db:
                store.db.execute('INSERT OR IGNORE INTO entries VALUES(?,?,?,?)',(f['id'],float(bars.loc[f['entry_session'],'open']),now_iso(),'alpaca:sip:raw:daily-open'))
            entry=store.db.execute('SELECT * FROM entries WHERE forecast_id=?',(f['id'],)).fetchone()
        if entry is None:
            pending+=1
            continue
        payload=json.loads(f['payload'])
        for h,end in payload['targets'].items():
            if end>completed or end not in bars.index:
                continue
            if store.db.execute('SELECT 1 FROM outcomes WHERE forecast_id=? AND horizon=?',(f['id'],int(h))).fetchone():
                continue
            try:
                ret=total_return(entry['price'],float(bars.loc[end,'close']),f['entry_session'],end,relevant(actions,f['symbol']),friction)
            except UnresolvedAction as exc:
                warnings.append(f'{f["symbol"]} {h}D outcome unresolved: {exc}')
                continue
            bench={}
            for symbol in ('SPY','QQQ'):
                b=store.bars(symbol)
                if not b.empty:
                    b=b.set_index('session')
                    if f['entry_session'] in b.index and end in b.index:
                        try:
                            bench[symbol]=total_return(float(b.loc[f['entry_session'],'open']),float(b.loc[end,'close']),f['entry_session'],end,relevant(actions,symbol),friction)
                        except UnresolvedAction:
                            pass
            detail={'entry_price':entry['price'],'exit_price':float(bars.loc[end,'close']), 'friction_bps':friction,
                    'benchmarks':bench,'recorded_at':now_iso(),'actions_digest':digest(relevant(actions,f['symbol']))}
            with store.db:
                store.db.execute('INSERT INTO outcomes VALUES(?,?,?,?,?)',(f['id'],int(h),end,ret,encode(detail)))
            settled+=1
    return {'newly_settled':settled,'pending_entries':pending,'warnings':warnings}

def performance(store):
    groups={}
    rows=store.db.execute('SELECT f.payload AS forecast_payload,f.issued_at,o.* FROM outcomes o JOIN forecasts f ON f.id=o.forecast_id').fetchall()
    for r in rows:
        pred=next(p for p in json.loads(r['forecast_payload'])['forecasts'] if p['horizon']==r['horizon'])
        if not pred['qualified']:
            continue
        groups.setdefault(r['horizon'],[]).append((r,pred))
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
    return {'kind':'prospective','horizons':output,'note':'Only qualified forecast/horizon outcomes; no backtest predictions included.'}
