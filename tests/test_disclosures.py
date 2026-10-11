import pytest
from stox.disclosures import Collector, sec_rows, senate_rows, house_pages, context, check_url

URL='https://www.sec.gov/Archives/edgar/data/1/000000000126000001/report.xml'
XML=b'''<ownershipDocument><documentType>4</documentType><issuer><issuerCik>1</issuerCik><issuerName>Example</issuerName><issuerTradingSymbol>037833100</issuerTradingSymbol></issuer><reportingOwner><reportingOwnerId><rptOwnerCik>2</rptOwnerCik><rptOwnerName>Owner</rptOwnerName></reportingOwnerId></reportingOwner><nonDerivativeTable><nonDerivativeTransaction><securityTitle><value>Common stock</value></securityTitle><transactionDate><value>2026-01-01</value></transactionDate><transactionCoding><transactionCode>P</transactionCode></transactionCoding><transactionAmounts><transactionShares><value>100</value></transactionShares><transactionPricePerShare><value>12.34</value><footnoteId id="F1"/></transactionPricePerShare><transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts></nonDerivativeTransaction></nonDerivativeTable><footnotes><footnote id="F1">Weighted average price</footnote></footnotes></ownershipDocument>'''

def test_sec_fields_and_amendment():
    rows,status=sec_rows(XML.replace(b'<documentType>4<',b'<documentType>4/A<'))
    assert status=='parsed'
    row=rows[0]
    assert row['amendment'] and row['issuer_cik']=='1'
    assert row['shares']=='100' and row['price']=='12.34'
    assert row['trade_date']=='2026-01-01' and row['footnote_refs']==['F1']
    assert row['footnotes']['F1']=='Weighted average price'
    assert not row['derivative']

def test_initial_holdings_are_not_transactions():
    rows,_=sec_rows(XML.replace(b'nonDerivativeTransaction',b'nonDerivativeHolding').replace(b'<documentType>4<',b'<documentType>3<'))
    assert rows[0]['record_type']=='nonDerivativeHolding'

def test_observation_idempotency_correction_and_identifier_separation(cfg,store):
    c=Collector(cfg,store)
    one=c.ingest('sec',URL,XML,{'filing_date':'2026-01-03','acceptance_at':'2026-01-03T10:00:00-05:00'},'2026-01-04T00:00:00+00:00')
    assert one['acceptance_at']=='2026-01-03T15:00:00+00:00'
    assert not store.records('disclosure_transactions','2026-01-03T23:59:59Z')
    assert store.records('disclosure_transactions')[0]['symbol'] is None
    assert c.ingest('sec',URL,XML,observed='2026-01-05T00:00:00+00:00')==one
    assert len(store.records('disclosure_transactions'))==1
    two=c.ingest('sec',URL,XML.replace(b'100</value>',b'200</value>'),observed='2026-01-06T00:00:00+00:00')
    assert two['supersedes_hash']==one['content_hash']
    assert two['first_observed_at']==one['first_observed_at']
    assert len(store.records('disclosure_transactions','2026-01-05T00:00:00Z'))==1
    assert len(store.records('disclosure_transactions'))==2

def test_transaction_rollback_resume(cfg,store,monkeypatch):
    c=Collector(cfg,store); original=store.record
    def interrupted(kind,*args,**kwargs):
        if kind=='disclosure_documents': raise KeyboardInterrupt()
        return original(kind,*args,**kwargs)
    monkeypatch.setattr(store,'record',interrupted)
    with pytest.raises(KeyboardInterrupt): c.ingest('sec',URL,XML)
    assert not store.records('disclosure_transactions')
    monkeypatch.setattr(store,'record',original)
    c.ingest('sec',URL,XML)
    assert len(store.records('disclosure_transactions'))==1

def test_senate_ranges_no_ticker_guess():
    data=b'''<table><tr><th>Transaction Date</th><th>Owner</th><th>Ticker</th><th>Asset Name</th><th>Transaction Type</th><th>Amount</th></tr><tr><td>01/01/2026</td><td>Spouse</td><td>--</td><td>Apple?</td><td>Purchase</td><td>$1,001 - $15,000</td></tr></table>'''
    rows,status=senate_rows(data)
    assert status=='partial' and rows[0]['amount_low']==1001 and rows[0]['amount_high']==15000
    assert rows[0]['reported_ticker']=='--' and rows[0]['owner']=='Spouse'

def test_house_partial_page_and_wrapped_range():
    rows,status=house_pages(['','  Common stock (ABC) [ST]      P      01/01/2026     01/03/2026    $100,001 -\n                                                                        $250,000'])
    assert status=='partial' and len(rows)==1
    assert rows[0]['amount_high']==250000 and rows[0]['reported_ticker']=='ABC'
    assert rows[0]['notification_date']=='01/03/2026'

def test_terms_and_official_urls(cfg,store):
    with pytest.raises(ValueError,match='prohibited-use'):
        Collector(cfg,store).ingest('senate','https://efdsearch.senate.gov/search/view/ptr/1/',b'<html/>')
    for url in ('https://www.sec.gov.evil.test/a','http://www.sec.gov/a','https://evil@www.sec.gov/a'):
        with pytest.raises(ValueError): check_url('sec',url)
    with pytest.raises(ValueError): sec_rows(b'<!DOCTYPE x [<!ENTITY y "z">]><ownershipDocument/>')

def test_sync_bound_resume_and_no_market_endpoint(cfg,store):
    cfg.enable_insider_disclosures=True; cfg.disclosure_documents_per_run=1
    from datetime import date
    for i in (1,2):
        store.record('filings',str(i),{'form':'4','filingDate':date.today().isoformat(),'cik':'1','accessionNumber':f'0000000001-26-{i:06d}','primaryDocument':'doc.xml'},'2026-01-01T00:00:00Z')
    calls=[]
    def fetch(url): calls.append(url); return XML
    c=Collector(cfg,store,fetch)
    assert len(c.sync())==1 and len(c.sync())==1 and not c.sync()
    assert len(calls)==2 and all(u.startswith('https://www.sec.gov/Archives/') for u in calls)

def test_bad_timestamp_not_backdated(cfg,store):
    with pytest.raises(ValueError,match='timezone'):
        Collector(cfg,store).ingest('sec',URL,XML,{'acceptance_at':'2026-01-01T12:00:00'})

def test_exact_ticker_context_correction_cutoff(cfg,store):
    from stox.security import SecurityMaster
    from test_security_master import asset
    SecurityMaster(store).refresh([asset('ABC')],'2026-01-01T00:00:00Z')
    data=XML.replace(b'037833100',b'ABC')
    c=Collector(cfg,store)
    c.ingest('sec',URL,data,observed='2026-01-04T00:00:00+00:00')
    c.ingest('sec',URL,data.replace(b'100</value>',b'200</value>'),observed='2026-01-06T00:00:00+00:00')
    assert context(store,'ABC','2026-01-05T00:00:00Z')[0]['shares']=='100'
    current=context(store,'ABC','2026-01-07T00:00:00Z')
    assert len(current)==1 and current[0]['shares']=='200'
    from stox.reporting import evidence
    assert evidence(store,'ABC','2026-01-07T00:00:00Z',cfg)['public_transactions']==current
    assert not list(store.db.execute('SELECT * FROM watchlist'))

def test_house_index_selection_bounded(cfg,store,monkeypatch):
    import sys,io,zipfile
    from datetime import datetime,timezone
    import stox.disclosures as module
    monkeypatch.setitem(sys.modules,'pypdf',object())
    monkeypatch.setattr(module,'parse',lambda source,data: ([], 'unparsed'))
    cfg.enable_house_disclosures=True; cfg.congressional_terms_acknowledged=True; cfg.disclosure_documents_per_run=1
    now=datetime.now(timezone.utc)
    index=f'<FinancialDisclosure><Member><FilingType>P</FilingType><FilingDate>{now:%m/%d/%Y}</FilingDate><DocID>12345</DocID><First>A</First><Last>B</Last></Member></FinancialDisclosure>'
    def fetch(url):
        if url.endswith('.pdf'): return b'%PDF-test'
        buffer=io.BytesIO()
        year=url.rsplit('/',1)[1][:4]
        with zipfile.ZipFile(buffer,'w') as archive: archive.writestr(year+'FD.xml',index)
        return buffer.getvalue()
    result=Collector(cfg,store,fetch).sync()
    assert len(result)==1 and result[0]['url'].endswith('/12345.pdf')
    assert store.records('disclosure_documents')[0]['filer']=='A B'

def test_sec_derivative_preserved_unresolved(cfg,store):
    from stox.security import SecurityMaster
    from test_security_master import asset
    SecurityMaster(store).refresh([asset('ABC')],'2026-01-01T00:00:00Z')
    data=XML.replace(b'037833100',b'ABC').replace(b'nonDerivative',b'derivative')
    Collector(cfg,store).ingest('sec',URL,data)
    row=store.records('disclosure_transactions')[0]
    assert row['derivative'] and row['symbol'] is None
