from __future__ import annotations
import csv
import io
from .http import HTTP, ProviderError

class AlphaVantage:
    def __init__(self, key, store, budget, http=None):
        self.key,self.store,self.maximum = key,store,budget
        self.http = http or HTTP()

    def history(self, symbol):
        if not self.key or not self.store.budget('alphavantage',self.maximum):
            raise ProviderError('Alpha Vantage unavailable or daily budget exhausted')
        raw=self.http.get('https://www.alphavantage.co/query',params={'function':'EARNINGS','symbol':symbol,'apikey':self.key},interval=12.5)
        if not isinstance(raw,dict) or not isinstance(raw.get('quarterlyEarnings'),list):
            raise ProviderError('Alpha Vantage earnings history unavailable (quota, entitlement or schema)')
        if raw.get('symbol')!=symbol:
            raise ProviderError('Alpha Vantage earnings symbol mismatch')
        return raw['quarterlyEarnings']

    def earnings(self):
        if not self.key:
            raise ProviderError('Alpha Vantage not configured')
        if not self.store.budget('alphavantage',self.maximum):
            raise ProviderError('Alpha Vantage daily budget exhausted')
        text = self.http.get('https://www.alphavantage.co/query',params={'function':'EARNINGS_CALENDAR','horizon':'3month','apikey':self.key},raw=True)
        if text.lstrip().startswith('{'):
            raise ProviderError('Alpha Vantage returned a quota/entitlement/error response')
        rows = list(csv.DictReader(io.StringIO(text)))
        if rows and ('symbol' not in rows[0] or 'reportDate' not in rows[0]):
            raise ProviderError('Alpha Vantage: invalid earnings schema')
        return rows
