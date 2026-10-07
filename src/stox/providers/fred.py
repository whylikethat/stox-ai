from __future__ import annotations
import pandas as pd
import math
from datetime import date
from .http import HTTP, ProviderError

class FRED:
    def __init__(self, key, http=None):
        if not key:
            raise ProviderError('FRED_API_KEY not configured; macro enrichment unavailable')
        self.key = key
        self.http = http or HTTP()

    def preflight(self, vintage=None):
        """Verify one finite DGS10 observation, without invoking bulk history ingestion."""
        params = {'series_id':'DGS10', 'api_key':self.key, 'file_type':'json',
                  'sort_order':'desc', 'limit':10}
        if vintage is not None:
            vintage = date.fromisoformat(vintage).isoformat()
            params.update(realtime_start=vintage, realtime_end=vintage, output_type=1)
        raw = self.http.get('https://api.stlouisfed.org/fred/series/observations', params=params)
        rows = raw.get('observations', []) if isinstance(raw, dict) else []
        if not isinstance(rows, list):
            raise ProviderError('FRED: HTTP 200 but observations is not a list')
        for row in rows:
            try:
                value = float(row['value'])
                observed = date.fromisoformat(row['date']).isoformat()
                if not math.isfinite(value):
                    continue
                if vintage is not None:
                    begin = date.fromisoformat(row['realtime_start']).isoformat()
                    end = date.fromisoformat(row['realtime_end']).isoformat()
                    if observed > vintage or not begin <= vintage <= end:
                        continue
                return f'DGS10 {observed}: {value:g}' + (f' (as of {vintage})' if vintage else '')
            except (KeyError, TypeError, ValueError):
                continue
        raise ProviderError(f'FRED: HTTP 200 but no valid DGS10 observation in {len(rows)} returned rows')

    def observations(self, series, start, end):
        for rows,_,_ in self.observation_pages(series,start,end):
            yield rows

    def observation_pages(self, series, start, end, offset=0, vintage_start='1776-07-04'):
        while True:
            raw = self.http.get('https://api.stlouisfed.org/fred/series/observations',params={
                'api_key':self.key,'file_type':'json','series_id':series,'observation_start':start[:10],
                'realtime_start':vintage_start[:10],'realtime_end':end[:10], 'output_type':1,'limit':1000,'offset':offset})
            if 'observations' not in raw:
                raise ProviderError('FRED: observations missing')
            result = []
            for r in raw['observations']:
                if r['value'] == '.':
                    continue
                # ALFRED supplies vintage dates, not intraday release timestamps. Lag one day conservatively.
                available = (pd.Timestamp(r['realtime_start'])+pd.Timedelta(days=1)).tz_localize('America/New_York').tz_convert('UTC').isoformat()
                result.append({**r,'series':series,'value':float(r['value']),'available_at':available,'provider':'alfred'})
            offset += len(raw['observations'])
            done=offset >= int(raw.get('count',offset))
            if not raw['observations'] and not done:
                raise ProviderError('FRED: empty page before expected count')
            yield result,offset,done
            if done: break
