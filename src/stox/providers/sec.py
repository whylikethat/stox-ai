from __future__ import annotations
import pandas as pd
from .http import HTTP, ProviderError

class SEC:
    def __init__(self, user_agent, http=None):
        if not user_agent or '@' not in user_agent:
            raise ProviderError('SEC_USER_AGENT must identify the application and a contact email')
        self.headers = {'User-Agent':user_agent,'Accept-Encoding':'gzip, deflate'}
        self.http = http or HTTP()

    def get(self, url):
        return self.http.get(url, headers=self.headers, interval=.6)

    def mappings(self):
        raw = self.get('https://www.sec.gov/files/company_tickers.json')
        return {r['ticker']:str(r['cik_str']).zfill(10) for r in raw.values()}

    def company(self, cik):
        submissions = self.get(f'https://data.sec.gov/submissions/CIK{cik}.json')
        groups = [submissions.get('filings',{}).get('recent',{})]
        for file in submissions.get('filings',{}).get('files',[]):
            groups.append(self.get('https://data.sec.gov/submissions/' + file['name']))
        filings = []
        for raw in groups:
            for i, acc in enumerate(raw.get('accessionNumber',[])):
                row = {k:v[i] for k,v in raw.items() if isinstance(v,list) and len(v)>i}
                accepted = row.get('acceptanceDateTime')
                if accepted:
                    stamp = pd.Timestamp(accepted)
                    if stamp.tzinfo is None:
                        stamp = stamp.tz_localize('America/New_York',ambiguous='raise',nonexistent='raise')
                else:
                    # Date-only filing metadata is not assumed available at midnight that day.
                    stamp = (pd.Timestamp(row['filingDate'])+pd.Timedelta(days=1)).tz_localize('America/New_York')
                row.update(cik=cik,available_at=stamp.tz_convert('UTC').isoformat(),provider='sec')
                filings.append(row)
        facts = self.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json')
        by_acc = {r['accessionNumber']:r['available_at'] for r in filings}
        values = []
        for namespace, fields in facts.get('facts',{}).items():
            for concept, detail in fields.items():
                for unit, observations in detail.get('units',{}).items():
                    for r in observations:
                        stamp = by_acc.get(r.get('accn'))
                        if stamp is None and r.get('filed'):
                            stamp = (pd.Timestamp(r['filed'])+pd.Timedelta(days=1)).tz_localize('America/New_York').tz_convert('UTC').isoformat()
                        if stamp:
                            values.append({**r,'cik':cik,'concept':concept,'namespace':namespace,'unit':unit,'available_at':stamp,'provider':'sec'})
        return filings, values
