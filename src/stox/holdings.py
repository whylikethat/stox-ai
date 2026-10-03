from __future__ import annotations
import json
import pandas as pd
from datetime import date
from .actions import total_return,relevant,UnresolvedAction
from .storage import encode
from .security import identifier_kind, ticker_shape, SecurityMaster


def add(store,symbol,purchased,price,shares=None):
    symbol=symbol.upper().strip()
    if identifier_kind(symbol):
        raise ValueError('Holdings require a ticker, not a CUSIP/ISIN/FIGI/provider ID')
    if not ticker_shape(symbol):
        raise ValueError('Invalid symbol')
    day=date.fromisoformat(purchased)
    if day>date.today() or price<=0 or (shares is not None and shares<=0):
        raise ValueError('Purchase date/price/shares are invalid')
    linked=store.db.execute('SELECT id,issued_at FROM forecasts WHERE symbol=? AND substr(issued_at,1,10)<=? ORDER BY issued_at DESC LIMIT 1',(symbol,purchased)).fetchone()
    fid=linked['id'] if linked and (day-date.fromisoformat(linked['issued_at'][:10])).days<=7 else None
    with store.db:
        cur=store.db.execute('INSERT INTO holdings(symbol,purchased,price,shares,forecast_id) VALUES(?,?,?,?,?)',(symbol,purchased,price,shares,fid))
    hid=cur.lastrowid
    SecurityMaster(store).resolve_holdings()
    return hid

def review(store,forecasts,run_id):
    results=[]
    for h in store.db.execute('SELECT * FROM holdings WHERE active=1').fetchall():
        current=[r for r in forecasts if r['symbol']==h['symbol']]
        original=[]
        if h['forecast_id']:
            row=store.db.execute('SELECT payload FROM forecasts WHERE id=?',(h['forecast_id'],)).fetchone()
            original=json.loads(row[0])['forecasts'] if row else []
        old=next((r for r in original if r['horizon']==30),None)
        present=next((r for r in current if r['horizon']==30),None)
        status,reason='WARNING','Current outlook unavailable or unvalidated'
        delta=None
        if h['resolution_status']=='resolved' and present and present['model_validated'] and not any('unavailable' in r or 'degraded' in r or 'stale' in r for r in present.get('exclusions',[])):
            status,reason='HEALTHY','No material deterioration under the configured review rules'
            if old:
                delta=present['p_gain']-old['p_gain']
                resolution=max(present['probability_resolution'],old['probability_resolution'])
                if delta < -resolution:
                    status,reason='DETERIORATING','Probability decline exceeds reported calibration resolution'
            if present['expected_return']<0:
                status,reason='EXIT REVIEW','Expected net return has become negative'
            if present['p_loss_20']>.10:
                status,reason='MATERIAL NEGATIVE CHANGE','Catastrophic downside estimate exceeds risk policy'
        ret=None
        bars=store.bars(h['symbol']) if h['resolution_status']=='resolved' else pd.DataFrame()
        if not bars.empty:
            last=bars.sort_values('session').iloc[-1]
            try:
                if h['purchased']>last['session']:
                    raise UnresolvedAction('No price after purchase date')
                ret=total_return(h['price'],last['close'],h['purchased'],last['session'],relevant(store.records('actions'),h['symbol']),0)
            except UnresolvedAction:
                reason+='; P/L unavailable because a corporate action is unresolved'
        result={**dict(h),'status':status,'reason':reason,'current_forecasts':current,'original_forecasts':original,
                'probability_change':delta,'total_return':ret,'dollar_pl':ret*h['price']*h['shares'] if ret is not None and h['shares'] else None,
                'link_status':'linked original prediction' if h['forecast_id'] else 'manual holding without original forecast',
                'pl_note':'USD total return before personal tax/fees; dividends accrued, not reinvested'}
        with store.db:
            store.db.execute('INSERT OR REPLACE INTO holding_reviews VALUES(?,?,?)',(run_id,h['id'],encode(result)))
        results.append(result)
    return results
