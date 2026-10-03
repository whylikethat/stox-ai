from __future__ import annotations
import time
import html
import json
import re
from urllib.parse import urlsplit, parse_qsl, unquote_plus
import requests

class ProviderError(RuntimeError):
    pass

def sanitized_response(response, url='', params=None, headers=None):
    """Bounded diagnostics with request credentials and credential fields removed."""
    sensitive = re.compile(r'key|secret|token|authorization|password|credential', re.I)
    secrets = []
    pairs = list((params or {}).items()) + list((headers or {}).items()) + parse_qsl(urlsplit(url).query)
    for name, value in pairs:
        if sensitive.search(str(name)) and value:
            secrets.append(str(value))
    try:
        body = response.json()
        if isinstance(body, dict):
            chosen = {k: body[k] for k in ('error_code', 'code', 'error_message', 'message', 'error', 'detail') if k in body}
            body = chosen or body
        text = json.dumps(body, ensure_ascii=False)
    except (ValueError, AttributeError, TypeError):
        text = getattr(response, 'text', '') or '(empty response body)'
    # Normalize common echo encodings before removing secrets, and truncate only after redaction.
    for _ in range(2):
        text = html.unescape(unquote_plus(text))
    for secret in sorted(secrets, key=len, reverse=True):
        variants = {secret, unquote_plus(secret), json.dumps(secret)[1:-1]}
        for value in sorted(variants, key=len, reverse=True):
            if value:
                text = text.replace(value, '[REDACTED]')
    text = re.sub(r'(?i)((?:api[_-]?key|secret|token|password|authorization|credential|APCA-API-KEY-ID|APCA-API-SECRET-KEY)[\w-]*[\"\']?\s*[:=]\s*)(\"[^\"]*\"|\'[^\']*\'|[^\s&,}<>]+)', r'\1[REDACTED]', text)
    text = re.sub(r'[\x00-\x1f\x7f]', ' ', text)
    return ' '.join(text.split())[:1000]


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
                detail = sanitized_response(response, url, params, headers)
                raise ProviderError(f'{host}: HTTP {code}: {detail}')
            if raw:
                return response.text
            try:
                return response.json()
            except ValueError:
                raise ProviderError(f'{host}: invalid JSON response') from None
        raise ProviderError(f'{host}: retries exhausted')
