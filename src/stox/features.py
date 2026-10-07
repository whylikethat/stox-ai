from __future__ import annotations
import numpy as np
import pandas as pd
from collections import defaultdict
from pathlib import Path
from .actions import adjusted_history, relevant, total_return, UnresolvedAction
from .storage import digest
from .security import SecurityMaster

BASE_FEATURES = ['momentum_5','momentum_20','momentum_60','momentum_120','trend_50','trend_200','volatility','downside_vol','drawdown','volume_ratio','log_liquidity','gap','market_relative','beta','cross_rank']
FAMILIES = {'price':BASE_FEATURES,'news':['news_count','news_negative','filing_count'], 'macro':['macro_DGS10','macro_DGS2','macro_UNRATE','macro_CPIAUCSL','macro_BAMLC0A0CM'], 'fundamentals':['assets_log','leverage','profit_margin','revenue_growth']}
NEGATIVE = ('bankruptcy','fraud','recall','lawsuit','downgrade','investigation','default','misses')

def market_features(frame, actions, calendar):
    f = adjusted_history(frame,actions)
    w = f.wealth
    ret = w.pct_change()
    for n in (5,20,60,120):
        f[f'momentum_{n}'] = w.pct_change(n)
    for n in (50,200):
        f[f'trend_{n}'] = w/w.rolling(n).mean()-1
    f['volatility'] = ret.rolling(60).std()*np.sqrt(252)
    f['downside_vol'] = ret.clip(upper=0).rolling(60).std()*np.sqrt(252)
    f['drawdown'] = w/w.rolling(252,min_periods=60).max()-1
    f['volume_ratio'] = f.volume.shift(1)/f.volume.shift(1).rolling(20).median().replace(0,np.nan)
    f['dollar_volume'] = (f.close*f.volume).shift(1).rolling(60,min_periods=20).median()
    f['log_liquidity'] = np.log1p(f.dollar_volume)
    f['gap'] = [np.nan]+[total_return(a['close'],b['open'],a['session'],b['session'],actions,0) for a,b in zip(f.iloc[:-1].to_dict('records'),f.iloc[1:].to_dict('records'))]
    f['history_count'] = np.arange(1,len(f)+1)
    expected = calendar.sessions(f.iloc[0].session,f.iloc[-1].session)
    indexes = {s:i for i,s in enumerate(expected)}
    positions = f.session.map(indexes)
    f['missing_recent'] = (positions-positions.shift(59)!=59).astype(int)
    f['issue_at'] = f.session.map(lambda s:(calendar.close(s)+pd.Timedelta(minutes=20)).isoformat())
    f['return_1'] = ret
    return f

def build_features(store, symbols, calendar, cutoff, max_rows=250_000, progress=None):
    actions = store.records('actions')
    by_symbol=defaultdict(list)
    for a in actions:
        tickers=set(a.get('resolved_tickers',[])) | {a.get(k) for k in ('symbol','old_symbol','new_symbol','initiating_symbol','target_symbol')}
        for ticker in tickers-{None,''}: by_symbol[ticker].append(a)
    frames,errors = [],{}
    total_rows=sum(r[1] for r in store.warehouse_summary())
    stride=max(1,int(np.ceil(total_rows/max_rows)))
    reference=store.bars('SPY')
    benchmark=market_features(reference,by_symbol['SPY'],calendar).set_index('session') if not reference.empty else None
    master=SecurityMaster(store)
    for index,symbol in enumerate(symbols):
        if progress and index%25==0: progress.update(processed=index)
        try:
            master.resolve(symbol)
        except ValueError as exc:
            errors[symbol]=str(exc)
            continue
        bars = store.bars(symbol)
        if bars.empty:
            errors[symbol] = 'No market history'
            continue
        bars = bars[pd.to_datetime(bars.available_at,utc=True) <= pd.Timestamp(cutoff)]
        if bars.empty:
            continue
        try:
            import hashlib
            from pathlib import Path
            aa=by_symbol[symbol]
            key=digest([symbol,str(bars.iloc[-1].session),len(bars),aa,bars[['open','close','volume']].sum().to_dict(),'causal-v2'])
            cache=store.root/'cache'/('features-'+digest(symbol)[:20]+'.parquet')
            marker=cache.with_suffix('.key')
            if cache.exists() and marker.exists() and marker.read_text()==key:
                f=pd.read_parquet(cache)
            else:
                f=market_features(bars,aa,calendar)
                cache.parent.mkdir(exist_ok=True)
                temporary=cache.with_suffix('.tmp')
                f.to_parquet(temporary,index=False,compression='zstd')
                temporary.replace(cache)
                marker.write_text(key)
            if benchmark is not None:
                r=f.session.map(benchmark.return_1)
                f['market_relative']=f.momentum_20-f.session.map(benchmark.momentum_20)
                f['beta']=f.return_1.rolling(60).cov(r)/r.rolling(60).var().replace(0,np.nan)
            else:
                f['market_relative'],f['beta']=np.nan,np.nan
            if stride>1 and symbol not in ('SPY','QQQ'):
                mask=np.array([int(hashlib.sha256((symbol+day).encode()).hexdigest()[:12],16)%stride==0 for day in f.session])
                mask[-1]=True
                f=f.loc[mask].copy()
            frames.append(f)
        except UnresolvedAction as exc:
            errors[symbol] = str(exc)
    if not frames:
        raise RuntimeError('FORECASTING BLOCKED: no usable price histories')
    result = pd.concat(frames,ignore_index=True)
    result['cross_rank'] = result.groupby('session').momentum_20.rank(pct=True)
    # Optional families are constructed by timestamp-safe event joins, and selected only by ablation.
    result = enrich(result,store)
    result = result.sort_values(['session','symbol']).reset_index(drop=True)
    result['revision_safe']=True
    for correction in store.records('bar_correction'):
        day=pd.Timestamp(correction['session'])
        issues=pd.to_datetime(result.issue_at,utc=True)
        affected=(result.symbol==correction['symbol']) & (pd.to_datetime(result.session)>=day) & (pd.to_datetime(result.session)<=day+pd.Timedelta(days=370)) & (issues<pd.Timestamp(correction['correction_available_at']))
        result.loc[affected,'revision_safe']=False
    result['feature_version'] = 'causal-v2'
    if progress: progress.update(processed=len(symbols))
    return result,errors

def enrich(frame, store):
    result = frame.copy()
    news = store.records('news')
    filings = store.records('filings')
    macro = store.records('macro')
    facts = store.records('facts')
    news_by,filings_by,facts_by=defaultdict(list),defaultdict(list),defaultdict(list)
    for row in news:
        for symbol in set(row.get('symbols',[])): news_by[symbol].append(row)
    for row in filings: filings_by[row.get('symbol')].append(row)
    for row in facts:
        if row.get('namespace')=='us-gaap' and row.get('unit')=='USD': facts_by[row.get('symbol')].append(row)
    for name in sum([v for k,v in FAMILIES.items() if k!='price'],[]):
        result[name] = np.nan
    for symbol, indices in result.groupby('symbol').groups.items():
        idx = list(indices)
        times = pd.to_datetime(result.loc[idx,'issue_at'],utc=True)
        n = news_by[symbol]
        fs = filings_by[symbol]
        for field, rows, stamp_fn in (
            ('news_count',n,lambda r:r.get('updated_at') or r['created_at']),
            ('news_negative',[r for r in n if any(w in (r.get('headline','')+' '+r.get('summary','')).lower() for w in NEGATIVE)],lambda r:r.get('updated_at') or r['created_at']),
            ('filing_count',fs,lambda r:r['available_at'])):
            if rows:
                stamps = np.sort(pd.to_datetime([stamp_fn(r) for r in rows],utc=True).astype('int64'))
                vals = times.astype('int64').to_numpy()
                result.loc[idx,field] = np.searchsorted(stamps,vals,side='right')-np.searchsorted(stamps,vals-30*86400*10**9,side='right')
        ff = facts_by[symbol]
        if ff:
            # Facts with incomparable fiscal durations are excluded from margin/growth estimates.
            for concept,target in [('Assets','assets_log'),('Liabilities','liabilities')]:
                rows = [r for r in ff if r['concept']==concept and not r.get('start')]
                if rows:
                    series = asof_values(times,rows,'val')
                    if target=='assets_log':
                        result.loc[idx,target] = np.log1p(np.maximum(series,0))
                    else:
                        assets = np.expm1(result.loc[idx,'assets_log'].to_numpy())
                        result.loc[idx,'leverage'] = np.divide(series,assets,out=np.full(len(idx),np.nan),where=assets>0)
            # Annual report facts only; revisions keep accession-specific availability.
            revenues = [r for r in ff if r['concept'] in ('RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet') and r.get('start') and 330 <= (pd.Timestamp(r['end'])-pd.Timestamp(r['start'])).days <= 380]
            income = [r for r in ff if r['concept']=='NetIncomeLoss' and r.get('start') and 330 <= (pd.Timestamp(r['end'])-pd.Timestamp(r['start'])).days <= 380]
            if revenues and income:
                margins=[]
                growth=[]
                for rev in revenues:
                    match=next((v for v in income if (v.get('start'),v.get('end'),v.get('accn'))==(rev.get('start'),rev.get('end'),rev.get('accn'))),None)
                    if match and rev['val']:
                        margins.append({'end':rev['end'],'available_at':max(rev['available_at'],match['available_at']),'val':match['val']/rev['val']})
                    prior=[v for v in revenues if v['available_at']<=rev['available_at'] and 330 <= (pd.Timestamp(rev['end'])-pd.Timestamp(v['end'])).days <= 400 and v['val']>0]
                    if prior:
                        previous=max(prior,key=lambda v:(v['end'],v['available_at']))
                        growth.append({'end':rev['end'],'available_at':rev['available_at'],'val':rev['val']/previous['val']-1})
                if margins:
                    result.loc[idx,'profit_margin']=asof_values(times,margins,'val')
                if growth:
                    result.loc[idx,'revenue_growth']=asof_values(times,growth,'val')
    times = pd.to_datetime(result.issue_at,utc=True)
    for series in ('DGS10','DGS2','UNRATE','CPIAUCSL','BAMLC0A0CM'):
        rows = [r for r in macro if r['series']==series]
        if rows:
            result['macro_'+series] = asof_values(times,rows,'value',period='date')
    return result

def asof_values(times, rows, value, period='end'):
    # At each availability event, choose the latest economic/fiscal period known then.
    events = sorted(rows,key=lambda r:r['available_at'])
    state = {}
    timeline = []
    values = []
    for r in events:
        state[r.get(period,'')] = float(r[value])
        timeline.append(pd.Timestamp(r['available_at']).value)
        values.append(state[max(state)])
    pos = np.searchsorted(np.asarray(timeline),pd.to_datetime(times,utc=True).astype('int64'),side='right')-1
    return np.array([values[p] if p>=0 else np.nan for p in pos])

def make_labels(features, store, calendar, horizons, friction, progress=None):
    output = []
    actions = store.records('actions')
    for index,(symbol,g) in enumerate(features.groupby('symbol')):
        if progress: progress.update(processed=index)
        try:
            SecurityMaster(store).resolve(symbol)
        except ValueError:
            continue
        bars = store.bars(symbol).set_index('session')
        aa = relevant(actions,symbol)
        # A finished symbol's expensive labels are reusable after interruption. The key
        # includes all input features, prices, actions and label parameters, never just dates.
        key=digest([g.to_json(orient='split',date_format='iso'),bars.to_json(orient='split',date_format='iso'),aa,list(horizons),friction,'labels-v1'])
        cache=store.root/'cache'/('labels-'+digest(symbol)[:20]+'.parquet')
        marker=cache.with_suffix('.key')
        if cache.exists() and marker.exists() and marker.read_text()==key:
            output.extend(pd.read_parquet(cache).to_dict('records'))
            continue
        begin=len(output)
        for row in g.to_dict('records'):
            if not row.get('revision_safe',True):
                continue
            entry = calendar.next_open(row['issue_at'])
            if entry not in bars.index:
                continue
            for h in horizons:
                end = calendar.settle(entry,h)
                if end not in bars.index:
                    continue
                try:
                    y = total_return(float(bars.loc[entry,'open']),float(bars.loc[end,'close']),entry,end,aa,friction)
                except UnresolvedAction:
                    continue
                output.append({**row,'horizon':h,'entry_session':entry,'label_end':end,'label_available_at':calendar.close(end).isoformat(),'target':y})
        cache.parent.mkdir(parents=True,exist_ok=True)
        temporary=cache.with_suffix('.tmp')
        pd.DataFrame(output[begin:]).to_parquet(temporary,index=False)
        temporary.replace(cache)
        marker_tmp=marker.with_suffix('.tmp-key')
        marker_tmp.write_text(key)
        marker_tmp.replace(marker)
    if progress: progress.update(processed=features.symbol.nunique())
    result=pd.DataFrame(output)
    if not result.empty:
        for symbol in ('SPY','QQQ'):
            benchmark=result[result.symbol==symbol].set_index(['session','horizon']).target
            result['benchmark_'+symbol]=[benchmark.get((s,h),np.nan) for s,h in zip(result.session,result.horizon)]
    return result
