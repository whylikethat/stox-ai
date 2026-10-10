from __future__ import annotations
import pandas as pd
from datetime import date, timedelta
from .http import HTTP, ProviderError
from ..security import MarketDataSymbol

class Alpaca:
    base = 'https://data.alpaca.markets'
    def __init__(self, secrets, http=None):
        if not secrets.get('ALPACA_API_KEY') or not secrets.get('ALPACA_API_SECRET'):
            raise ProviderError('Set ALPACA_API_KEY and ALPACA_API_SECRET locally')
        self.headers = {'APCA-API-KEY-ID':secrets['ALPACA_API_KEY'], 'APCA-API-SECRET-KEY':secrets['ALPACA_API_SECRET']}
        self.http = http or HTTP()

    def pages(self, path, params):
        params = dict(params)
        seen = set()
        while True:
            page = self.http.get(self.base + path, params=params, headers=self.headers)
            if not isinstance(page,dict):
                raise ProviderError('Alpaca: expected a JSON object')
            yield page
            token = page.get('next_page_token')
            if not token:
                break
            if token in seen:
                raise ProviderError('Alpaca: repeated pagination token')
            seen.add(token)
            params['page_token'] = token

    def assets(self):
        result = []
        for status in ('active','inactive'):
            rows = self.http.get('https://paper-api.alpaca.markets/v2/assets',params={'status':status,'asset_class':'us_equity'},headers=self.headers)
            if not isinstance(rows,list):
                raise ProviderError('Alpaca: invalid asset metadata')
            result.extend(rows)
        return result

    def bars(self, symbols, start, end):
        if not symbols or any(not isinstance(s,MarketDataSymbol) for s in symbols):
            raise ValueError('Alpaca bars require security-master validated MarketDataSymbol references')
        params = {'symbols':','.join(sorted({s.ticker for s in symbols})), 'start':start,'end':end,
                  'timeframe':'1Day','adjustment':'raw','feed':'sip','asof':'-', 'limit':10000,'sort':'asc'}
        for page in self.pages('/v2/stocks/bars',params):
            if 'bars' not in page:
                raise ProviderError('Alpaca: bars field missing')
            yield page.get('bars') or {}

    def news(self, start, end):
        for page in self.pages('/v1beta1/news', {'start':start,'end':end,'limit':50,'sort':'asc','include_content':'false'}):
            if 'news' not in page:
                raise ProviderError('Alpaca: news field missing')
            yield page.get('news') or []

    def event_page(self, feed, start, end, cursor=None, snapshot=None, symbols=None):
        if feed not in ('actions','news'):
            raise ValueError('Unsupported event feed')
        params={'start':start,'end':end,'sort':'asc','limit':1000 if feed=='actions' else 50}
        path='/v1/corporate-actions' if feed=='actions' else '/v1beta1/news'
        if feed=='news':
            params['start']=start+'T00:00:00Z'
            # Adjacent news windows overlap at midnight, avoiding sub-microsecond gaps.
            boundary=(date.fromisoformat(end)+timedelta(days=1)).isoformat()+'T00:00:00Z'
            params['end']=min(boundary,snapshot or boundary)
            params['include_content']='false'
        if symbols is not None:
            if feed!='actions' or not symbols or any(not isinstance(s,MarketDataSymbol) for s in symbols):
                raise ValueError('Corporate-action filters require authoritative MarketDataSymbol references')
            params['symbols']=','.join(sorted({s.ticker for s in symbols}))
        if cursor: params['page_token']=cursor
        raw=self.http.get(self.base+path,params=params,headers=self.headers)
        key='corporate_actions' if feed=='actions' else 'news'
        if not isinstance(raw,dict) or key not in raw:
            raise ProviderError(f'Alpaca: {key} field missing')
        content=raw[key] or ({} if feed=='actions' else [])
        if feed=='actions':
            if not isinstance(content,dict) or any(not isinstance(v,list) for v in content.values()):
                raise ProviderError('Alpaca: malformed corporate_actions page')
            rows=[{**row,'action_type':kind} for kind,group in content.items() for row in group]
        else:
            if not isinstance(content,list): raise ProviderError('Alpaca: malformed news page')
            rows=content
        token=raw.get('next_page_token')
        if token is not None and not isinstance(token,str):
            raise ProviderError('Alpaca: invalid page token type')
        return rows,token or None

    def actions(self, start, end):
        for page in self.pages('/v1/corporate-actions',{'start':start[:10],'end':end[:10],'limit':1000,'sort':'asc'}):
            if 'corporate_actions' not in page:
                raise ProviderError('Alpaca: corporate_actions field missing')
            groups = page.get('corporate_actions') or {}
            rows = []
            for kind, actions in groups.items():
                for action in actions:
                    rows.append({**action,'action_type':kind})
            yield rows

def parse_bar(symbol, row, calendar, ingested):
    session = pd.Timestamp(row['t']).tz_convert('America/New_York').date().isoformat()
    result = {'symbol':symbol,'session':session,'open':float(row['o']),'high':float(row['h']),
              'low':float(row['l']),'close':float(row['c']),'volume':float(row['v']),
              'available_at':calendar.close(session).isoformat(),'ingested_at':ingested,'provider':'alpaca:sip:raw'}
    if not all(pd.notna(result[k]) and result[k]>0 for k in ('open','high','low','close')) or result['volume'] < 0:
        raise ProviderError(f'Invalid prices/volume for {symbol} {session}')
    if result['low'] > min(result['open'],result['close']) or result['high'] < max(result['open'],result['close']):
        raise ProviderError(f'Invalid OHLC range for {symbol} {session}')
    return result
