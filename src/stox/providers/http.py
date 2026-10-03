from __future__ import annotations
import time
from urllib.parse import urlsplit
import requests

class ProviderError(RuntimeError):
    pass

class HTTP:
    def __init__(self, session=None, sleep=time.sleep):
        self.session = session or requests.Session()
        self.sleep = sleep
        self.last = {}

    def get(self, url, params=None, headers=None, interval=.35, raw=False):
        host = urlsplit(url).hostname
        for attempt in range(4):
            self.sleep(max(0, interval - (time.monotonic() - self.last.get(host, 0))))
            self.last[host] = time.monotonic()
            try:
                response = self.session.get(url,params=params,headers=headers,timeout=(10,60))
            except requests.RequestException:
                if attempt == 3:
                    raise ProviderError(f'{host}: connection failed after retries') from None
                self.sleep(2 ** attempt)
                continue
            code = response.status_code
            if code == 429 or code >= 500:
                if attempt < 3:
                    retry = response.headers.get('Retry-After','')
                    delay = float(retry) if retry.replace('.','',1).isdigit() else 2 ** attempt
                    self.sleep(min(60,max(delay,2 ** attempt)))
                    continue
            if code != 200:
                # Never print response bodies or request URLs: either may contain credentials.
                raise ProviderError(f'{host}: HTTP {code}')
            if raw:
                return response.text
            try:
                return response.json()
            except ValueError:
                raise ProviderError(f'{host}: invalid JSON response') from None
        raise ProviderError(f'{host}: retries exhausted')
