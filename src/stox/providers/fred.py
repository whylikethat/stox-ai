from __future__ import annotations
import pandas as pd
from .http import HTTP, ProviderError

class FRED:
    def __init__(self, key, http=None):
        if not key:
            raise ProviderError('FRED_API_KEY not configured; macro enrichment unavailable')
        self.key = key
        self.http = http or HTTP()

    def observations(self, series, start, end):
        offset = 0
        while True:
            raw = self.http.get('https://api.stlouisfed.org/fred/series/observations',params={
                'api_key':self.key,'file_type':'json','series_id':series,'observation_start':start[:10],
                'realtime_start':'1776-07-04','realtime_end':end[:10], 'output_type':1,'limit':100000,'offset':offset})
            if 'observations' not in raw:
                raise ProviderError('FRED: observations missing')
            result = []
            for r in raw['observations']:
                if r['value'] == '.':
                    continue
                # ALFRED supplies vintage dates, not intraday release timestamps. Lag one day conservatively.
                available = (pd.Timestamp(r['realtime_start'])+pd.Timedelta(days=1)).tz_localize('America/New_York').tz_convert('UTC').isoformat()
                result.append({**r,'series':series,'value':float(r['value']),'available_at':available,'provider':'alfred'})
            yield result
            offset += len(raw['observations'])
            if offset >= int(raw.get('count',offset)):
                break
            if not raw['observations']:
                raise ProviderError('FRED: empty page before expected count')
