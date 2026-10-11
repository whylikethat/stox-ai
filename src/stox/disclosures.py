"""Optional public disclosures. Observation time, never trade date, controls availability."""
from __future__ import annotations
import hashlib
import io
import json
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit
import requests

TERMS = 'https://disclosures-clerk.house.gov/FinancialDisclosure/ViewSearch'

def xml(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('XML declarations with entities are unsupported')
    return ET.fromstring(data)

def value(node, path):
    found=node.find(path)
    return ''.join(found.itertext()).strip() if found is not None else None

def sec_rows(data):
    root=xml(data)
    if root.tag != 'ownershipDocument':
        raise ValueError('Expected SEC ownershipDocument XML')
    form=value(root,'documentType')
    if form not in ('3','4','5','3/A','4/A','5/A'):
        raise ValueError('Unsupported ownership form')
    common={'form':form,'amendment':form.endswith('/A'), 'amends_date':value(root,'dateOfOriginalSubmission'),
            'issuer_cik':value(root,'issuer/issuerCik'),'issuer_name':value(root,'issuer/issuerName'),
            'reported_ticker':value(root,'issuer/issuerTradingSymbol'),
            'owners':[{e.tag:(e.text or '').strip() for e in owner.iter() if not list(e)} for owner in root.findall('reportingOwner')],
            'footnotes':{f.get('id'):''.join(f.itertext()) for f in root.findall('footnotes/footnote')}}
    rows=[]
    for table in ('nonDerivativeTable','derivativeTable'):
        for node in root.findall(table+'/*'):
            row={**common,'record_type':node.tag,'derivative':table=='derivativeTable',
                 'asset_name':value(node,'securityTitle/value'),'trade_date':value(node,'transactionDate/value'),
                 'transaction_code':value(node,'transactionCoding/transactionCode'),
                 'acquired_disposed':value(node,'transactionAmounts/transactionAcquiredDisposedCode/value'),
                 'shares':value(node,'transactionAmounts/transactionShares/value'),
                 'price':value(node,'transactionAmounts/transactionPricePerShare/value'),
                 'shares_after':value(node,'postTransactionAmounts/sharesOwnedFollowingTransaction/value'),
                 'ownership':value(node,'ownershipNature/directOrIndirectOwnership/value'),
                 'footnote_refs':[f.get('id') for f in node.iter('footnoteId')],
                 'fields':{e.tag:''.join(e.itertext()).strip() for e in node}}
            rows.append(row)
    return rows,'parsed'

class Tables(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self.row=[]; self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr': self.row=[]
        if tag in ('td','th'): self.cell=[]
    def handle_data(self,data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(' '.join(' '.join(self.cell).split())); self.cell=None
        if tag=='tr' and self.row: self.rows.append(self.row)

def amount(text):
    numbers=re.findall(r'\$([\d,]+)',text)
    return {'amount_text':text,'amount_low':int(numbers[0].replace(',','')) if numbers else None,
            'amount_high':int(numbers[1].replace(',','')) if len(numbers)>1 else None,
            'amount_range_status':'reported_range' if len(numbers)==2 else 'incomplete_or_open_ended'}

def senate_rows(data):
    parser=Tables(); parser.feed(data.decode('utf-8')); rows=[]; headers=None
    for cells in parser.rows:
        lower=[c.lower() for c in cells]
        if any('transaction date' in c for c in lower) and any('asset name' in c for c in lower):
            headers=lower; continue
        if headers and len(cells)==len(headers):
            fields=dict(zip(headers,cells))
            def get(term): return next((v for k,v in fields.items() if term in k),None)
            if not re.fullmatch(r'\d{2}/\d{2}/\d{4}',get('transaction date') or ''): continue
            rows.append({'record_type':'transaction','trade_date':get('transaction date'),'asset_name':get('asset name'),
                         'reported_ticker':get('ticker'),'owner':get('owner'),'transaction_code':fields.get('transaction type',fields.get('type')),
                         **amount(get('amount') or ''),'fields':fields})
    # Explicitly partial: HTML layouts and attachments can contain additional transactions.
    return rows,'partial' if rows else 'unparsed'

def house_pages(pages):
    rows=[]
    pattern=re.compile(r'^(.*?)\s{2,}(P|S(?: \(partial\))?|E)\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+(\$[\d,]+(?:\s*-\s*(?:\$[\d,]+)?)?)')
    for page in pages:
        current=None; asset_col=None; owner_col=None
        for line in page.splitlines():
            if 'Owner' in line and 'Asset' in line and 'Transaction' in line:
                owner_col=line.index('Owner'); asset_col=line.index('Asset')
            match=pattern.search(line)
            if match:
                prefix,code,date,notice,money=match.groups()
                # Layout columns come from this page's explicit table header.
                current={'record_type':'transaction','asset_name':prefix.strip(),'transaction_code':code,
                         'trade_date':date,'notification_date':notice,**amount(money),'raw_lines':[line],
                         'reported_ticker':None,'owner':None,'parse_warning':'Partial PDF extraction; consult original report'}
                if asset_col is not None:
                    current['owner']=prefix[owner_col:asset_col].strip() or None
                    current['asset_name']=prefix[asset_col:].strip()
                rows.append(current)
            elif current and line.strip():
                current['raw_lines'].append(line)
                # Only append continuation before labels; preserve all text for review.
                if not any(c in line for c in (':','\x00')) and '[' in line:
                    continuation=line[asset_col:] if asset_col is not None else line
                    current['asset_name']+=' '+continuation.strip()
                if current['amount_high'] is None and current['amount_text'].rstrip().endswith('-'):
                    continuation=re.search(r'\$[\d,]+',line)
                    if continuation: current.update(amount(current['amount_text']+' '+continuation.group()))
            if current:
                tickers=re.findall(r'\(([A-Z]{1,5}(?:[.-][A-Z])?)\)\s*\[ST\]',current['asset_name'])
                if len(tickers)==1: current['reported_ticker']=tickers[0]
    # PDF text can omit whole rows/pages. Never advertise complete PDF coverage.
    return rows,'partial' if rows else 'unparsed'

def parse(source,data):
    if source=='sec': return sec_rows(data)
    if source=='senate' and not data.startswith(b'%PDF'): return senate_rows(data)
    try:
        from pypdf import PdfReader
    except ImportError:
        return [],'unparsed: install stox-ai[disclosures] for PDF extraction'
    reader=PdfReader(io.BytesIO(data))
    if len(reader.pages)>100: raise ValueError('Disclosure exceeds 100 page bound')
    pages=[p.extract_text(extraction_mode='layout') or '' for p in reader.pages]
    if source=='house': return house_pages(pages)
    return [],'unparsed: Senate PDF retained for manual review; HTML table import supported'

def check_url(source,url):
    hosts={'sec':{'www.sec.gov'},'house':{'disclosures-clerk.house.gov'},'senate':{'efdsearch.senate.gov'}}
    p=urlsplit(url)
    if source not in hosts or p.scheme!='https' or p.hostname not in hosts[source] or p.username or p.password or p.port not in (None,443):
        raise ValueError('An official HTTPS disclosure source URL is required')

def sec_acceptance(raw):
    if not raw: return None
    stamp=datetime.fromisoformat(raw.replace('Z','+00:00'))
    if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=ZoneInfo('America/New_York'))
    return stamp.astimezone(timezone.utc).isoformat()

class Collector:
    def __init__(self,cfg,store,fetch=None):
        self.cfg=cfg; self.store=store; self.fetch=fetch or self.download; self.last=0
        self.documents={r['document_id']:r for r in store.records('disclosure_documents')}
    def download(self,url):
        host=urlsplit(url).hostname
        time.sleep(max(0,1-(time.monotonic()-self.last))); self.last=time.monotonic()
        headers={'User-Agent':self.cfg.secrets.get('SEC_USER_AGENT','STOX public-disclosure research')}
        if host=='www.sec.gov' and '@' not in headers['User-Agent']: raise ValueError('SEC_USER_AGENT contact email required')
        # Never follow redirects to login, third parties, or consent bypasses.
        with requests.get(url,headers=headers,timeout=(10,30),stream=True,allow_redirects=False) as response:
            if response.status_code!=200: raise ValueError(f'{host}: HTTP {response.status_code}; retry on a later run')
            parts=[]; size=0; began=time.monotonic()
            for part in response.iter_content(65536):
                if time.monotonic()-began>60: raise ValueError('Disclosure download exceeds time bound')
                size+=len(part)
                if size>20_000_000: raise ValueError('Disclosure download exceeds 20 MB bound')
                parts.append(part)
            return b''.join(parts)
    def ingest(self,source,url,data,metadata=None,observed=None):
        check_url(source,url)
        if source in ('house','senate') and not self.cfg.congressional_terms_acknowledged:
            raise ValueError('Review official House/Senate prohibited-use notices and set congressional_terms_acknowledged=true for permitted use')
        if len(data)>20_000_000: raise ValueError('Disclosure exceeds 20 MB bound')
        metadata=dict(metadata or {})
        for field in ('acceptance_at','publication_at'):
            if metadata.get(field):
                stamp=datetime.fromisoformat(metadata[field].replace('Z','+00:00'))
                if stamp.tzinfo is None: raise ValueError(field+' must include a timezone')
                metadata[field]=stamp.astimezone(timezone.utc).isoformat()
        if metadata.get('filing_date'): datetime.strptime(metadata['filing_date'],'%Y-%m-%d')
        observed=observed or datetime.now(timezone.utc).isoformat()
        if datetime.fromisoformat(observed).tzinfo is None: raise ValueError('Observation time must include timezone')
        key=hashlib.sha256(url.encode()).hexdigest(); digest=hashlib.sha256(data).hexdigest()
        prior=self.documents.get(key)
        if prior and prior['content_hash']==digest and prior['parser_version']==1 and not prior['parse_status'].startswith('unparsed: install'): return prior
        try:
            rows,status=parse(source,data)
        except Exception as exc:
            raise ValueError(f'Cannot parse {source} disclosure: {exc}') from exc
        directory=self.cfg.root/'cache'/'disclosures'; directory.mkdir(parents=True,exist_ok=True)
        target=directory/digest
        if not target.exists():
            tmp=directory/(digest+'.tmp'); tmp.write_bytes(data); tmp.replace(target)
        meta=dict(metadata or {})
        doc={**meta,'document_id':key,'source':source,'source_url':url,'content_hash':digest,'parser_version':1,
             'first_observed_at':prior['first_observed_at'] if prior else observed,'available_at':observed,
             'filing_date':meta.get('filing_date'),'acceptance_at':meta.get('acceptance_at'),
             'publication_at':meta.get('publication_at'),'parse_status':status,'row_count':len(rows),
             'supersedes_hash':prior['content_hash'] if prior else None,'context_only':True, 'amendment_policy':'Retain original and amended filings separately; do not sum them',
             'coverage_warning':'Public delayed disclosures only; absence of records is not absence of activity'}
        with self.store.transaction():
            for index,row in enumerate(rows):
                ticker=row.get('reported_ticker') or ''
                symbol=None
                if re.fullmatch(r'[A-Z]{1,5}(?:[.-][A-Z])?',ticker) and not row.get('derivative'):
                    found=self.store.db.execute('SELECT market_symbol FROM security_master WHERE market_symbol=? AND present=1 AND queryable=1',(ticker,)).fetchall()
                    if len(found)==1: symbol=ticker
                item={**doc,**row,'row_index':index,'symbol':symbol,
                      'resolution_confidence':'exact_reported_ticker_current_master' if symbol else 'unresolved',
                      'resolution_warning':'Current ticker identity is not a historical identity guarantee'}
                self.store.record('disclosure_transactions',f'{key}:{digest}:{index}',item,observed)
            self.store.record('disclosure_documents',key,doc,observed)
        self.documents[key]=doc
        return doc
    def sync(self):
        results=[]; now=datetime.now(timezone.utc); earliest=(now-timedelta(days=self.cfg.disclosure_lookback_days)).date().isoformat()
        if self.cfg.enable_insider_disclosures:
            filings=[r for r in self.store.records('filings') if r.get('form') in ('3','4','5','3/A','4/A','5/A') and r.get('filingDate','')>=earliest]
            for row in sorted(filings,key=lambda r:r.get('filingDate','')):
                cik=str(row.get('cik','')); acc=row.get('accessionNumber',''); name=row.get('primaryDocument','').split('/')[-1]
                if not cik.isdigit() or not re.fullmatch(r'\d{10}-\d{2}-\d{6}',acc) or not re.fullmatch(r'[\w.-]+\.xml',name): continue
                url=f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace("-", "")}/{name}'
                if self.done(url): continue
                results.append(self.attempt('sec',url,{'filing_date':row.get('filingDate'),'acceptance_at':sec_acceptance(row.get('acceptanceDateTime')),'acceptance_raw':row.get('acceptanceDateTime'),'accession':acc}))
                if len(results)>=self.cfg.disclosure_documents_per_run: return results
        if self.cfg.enable_house_disclosures:
            try: __import__('pypdf')
            except ImportError: raise ValueError('House PDF collection requires: pip install -e ".[disclosures]"') from None
            if not self.cfg.congressional_terms_acknowledged: raise ValueError('House disclosure terms acknowledgement required')
            # At most two yearly indexes, independent of price/model history.
            for year in range(datetime.fromisoformat(earliest).year,now.year+1):
                url=f'https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip'
                data=self.fetch(url)
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    info=archive.getinfo(f'{year}FD.xml')
                    if info.file_size>20_000_000: raise ValueError('House index exceeds size bound')
                    members=xml(archive.read(info)).findall('Member')
                for member in members:
                    if value(member,'FilingType')!='P': continue
                    date=datetime.strptime(value(member,'FilingDate'),'%m/%d/%Y').date().isoformat()
                    docid=value(member,'DocID') or ''
                    if date<earliest or not docid.isdigit(): continue
                    report=f'https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{docid}.pdf'
                    if self.done(report): continue
                    results.append(self.attempt('house',report,{'filing_date':date,'filer':' '.join(filter(None,[value(member,'First'),value(member,'Last')])),'official_document_id':docid}))
                    if len(results)>=self.cfg.disclosure_documents_per_run: return results
        return results
    def done(self,url):
        key=hashlib.sha256(url.encode()).hexdigest()
        doc=self.documents.get(key)
        if not doc or doc['parse_status'].startswith('unparsed: install'): return False
        checked=self.store.checkpoint('disclosure_checked:'+key) or doc['available_at']
        return datetime.now(timezone.utc)-datetime.fromisoformat(checked)<timedelta(days=7)
    def attempt(self,source,url,meta):
        try:
            doc=self.ingest(source,url,self.fetch(url),meta)
            self.store.advance('disclosure_checked:'+doc['document_id'],datetime.now(timezone.utc).isoformat())
            return {'url':url,'status':doc['parse_status'],'rows':doc['row_count']}
        except Exception as exc:
            return {'url':url,'status':'error','detail':str(exc)}

def context(store,symbol,cutoff,snapshots=None):
    def records(kind):
        return snapshots.get(kind,[]) if snapshots is not None else store.records(kind,cutoff)
    docs={r['document_id']:r for r in records('disclosure_documents')}
    return [r for r in records('disclosure_transactions') if r.get('symbol')==symbol and docs.get(r['document_id'],{}).get('content_hash')==r['content_hash']][-20:]
