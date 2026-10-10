"""Typed security identity; only authoritative active asset tickers reach price APIs."""
from __future__ import annotations
from dataclasses import dataclass
import json
import logging
import re
import uuid
import pandas as pd
from .storage import digest, encode, now_iso
from .universe import classify

IDENTIFIER_FIELDS={'id':'alpaca_asset_id','asset_id':'alpaca_asset_id','cusip':'cusip','isin':'isin',
                   'figi':'figi','cik':'sec_cik','cik_str':'sec_cik','provider_id':'provider_id'}


def identifier_kind(value):
    """Defensive recognition, NOT ticker authorization. Metadata grants authorization."""
    if not isinstance(value,str) or not value:
        return None
    try:
        uuid.UUID(value)
        return 'provider_asset_id'
    except (ValueError,AttributeError):
        pass
    if re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}[0-9]',value):
        return 'isin'
    if re.fullmatch(r'BBG[A-Z0-9]{9}',value):
        return 'figi'
    if re.fullmatch(r'[A-Z0-9*@#]{8}[0-9]',value):
        alphabet='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ*@#'
        nums=[alphabet.index(c)*(1+i%2) for i,c in enumerate(value[:8])]
        checksum=(10-sum(n//10+n%10 for n in nums)%10)%10
        if checksum==int(value[-1]):
            return 'cusip'
    return None


def ticker_shape(value):
    # Broad syntax: no five-character cap or blanket nine-character exclusion.
    return isinstance(value,str) and bool(value) and bool(re.fullmatch(r'[A-Za-z][A-Za-z0-9.\-/]*',value))


@dataclass(frozen=True)
class MarketDataSymbol:
    ticker: str
    alpaca_asset_id: str
    authority: str = 'alpaca_assets'

    def __post_init__(self):
        if not self.alpaca_asset_id or not ticker_shape(self.ticker) or identifier_kind(self.ticker):
            raise ValueError('MarketDataSymbol requires a validated ticker, not another identifier')
        if self.authority not in ('alpaca_assets','known_preflight'):
            raise ValueError('Unrecognized ticker authority')
        if self.authority=='known_preflight' and self.ticker not in ('SPY','QQQ'):
            raise ValueError('Only fixed liquid canary tickers may bypass the local master')


class SecurityMaster:
    def __init__(self,store):
        self.store=store
        self.db=store.db
        self._resolution_cache = {}

    def identifier(self,entity,kind,value,source,role='',effective=''):
        if value is None or value=='':
            return
        with self.store.transaction():
            self.db.execute('INSERT OR IGNORE INTO security_identifiers VALUES(?,?,?,?,?,?,?)',
                            (entity,kind,str(value),source,role,str(effective or ''),now_iso()))

    def refresh(self,assets,stamp):
        with self.store.transaction():
            self._refresh(assets,stamp)

    def _refresh(self,assets,stamp):
        """Snapshot validation. Raw asset/event records and existing prices stay untouched."""
        if not isinstance(assets,list) or not assets:
            raise RuntimeError('Universe validation failed: asset snapshot is empty or invalid')
        by_id = {}
        snapshot_conflicts=set()
        for a in assets:
            key = str(a.get('id') or 'unresolved:'+digest(a))
            previous = by_id.get(key)
            if previous and previous.get('status') == 'active' and a.get('status') != 'active':
                continue
            if previous and previous.get('status') == a.get('status') and previous != a:
                snapshot_conflicts.add(key)
            by_id[key] = a
        assets = list(by_id.values())
        known_ids={str(a[k]) for a in assets for k in IDENTIFIER_FIELDS if k!='provider_id' and a.get(k)}
        # Only this authoritative asset snapshot can define namespace conflicts.
        # Event-only identifiers must not pollute future ticker validation.
        counts={}
        for a in assets:
            if a.get('status')=='active' and a.get('tradable') is True:
                counts[a.get('symbol')]=counts.get(a.get('symbol'),0)+1
        with self.store.transaction():
            self.db.execute("UPDATE security_master SET queryable=0,reason='absent from current asset snapshot',present=0")
        for a in assets:
            aid=str(a.get('id') or 'unresolved:'+digest(a))
            token=a.get('symbol')
            kind=identifier_kind(token)
            if token in known_ids:
                kind=kind or 'non_ticker_identifier'
            category=classify(a)
            intended=(category in ('common','etf') and a.get('status')=='active' and a.get('tradable') is True)
            valid_ticker=bool(a.get('id')) and ticker_shape(token) and not kind
            reasons=[]
            if aid in snapshot_conflicts: reasons.append('identifier-resolution failure: conflicting provider metadata for same asset ID')
            if category not in ('common','etf'): reasons.append('excluded asset class/exchange or unverified security type')
            if a.get('status')!='active': reasons.append('inactive/unlisted')
            if a.get('tradable') is not True: reasons.append('non-tradable or tradability unverified')
            if not valid_ticker: reasons.append('identifier-resolution failure: '+(kind or 'missing/invalid ticker or asset ID'))
            if counts.get(token,0)>1: reasons.append('identifier-resolution failure: ambiguous active ticker')
            mh=digest(a)
            quarantine=self.db.execute('SELECT * FROM security_quarantine WHERE asset_id=?',(aid,)).fetchone()
            if quarantine:
                if quarantine['metadata_hash']==mh and pd.Timestamp(quarantine['retry_after'])>pd.Timestamp(stamp):
                    reasons.append(quarantine['reason'])
                else:
                    with self.store.transaction(): self.db.execute('DELETE FROM security_quarantine WHERE asset_id=?',(aid,))
            prior=self.db.execute('SELECT market_symbol FROM security_master WHERE asset_id=?',(aid,)).fetchone()
            if prior and prior[0] and prior[0]!=token:
                self.identifier(aid,'historical_ticker',prior[0],'alpaca_assets','prior_ticker',stamp)
            owner=self.db.execute('SELECT asset_id FROM price_history_owners WHERE ticker=?',(token,)).fetchone() if valid_ticker else None
            if owner and owner[0]!=aid:
                reasons.append('identifier-resolution failure: ticker belongs to different archived asset; history not merged')
            reason='; '.join(reasons)
            ticker=token if valid_ticker else None
            with self.store.transaction():
                self.db.execute('INSERT OR REPLACE INTO security_master VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                (aid,ticker,str(token or ''),category,a.get('status','unknown'),int(a.get('tradable') is True),int(not reasons),reason,mh,encode(a),stamp,1,int(intended)))
            self.store.record('security_snapshots',aid,{'asset_id':aid,'market_data_symbol':ticker,'queryable':not reasons,'reason':reason,'metadata':a},stamp)
            for field,id_kind in IDENTIFIER_FIELDS.items():
                if a.get(field): self.identifier(aid,id_kind,a[field],'alpaca_assets',field)
            if ticker: self.identifier(aid,'ticker',ticker,'alpaca_assets','current_ticker',stamp) if not prior or prior[0]!=ticker else None
            elif token: self.identifier(aid,kind or 'unresolved_provider_symbol',token,'alpaca_assets','symbol')

        self.store.advance('security_master',stamp)
        self._resolution_cache = {}

    def ensure(self,cutoff=None):
        if not self.db.execute('SELECT 1 FROM security_master LIMIT 1').fetchone():
            assets=self.store.records('assets',cutoff)
            if assets:
                self.refresh(assets,cutoff or now_iso())

    def resolve(self,ticker):
        # No CUSIP -> ticker guessing, regex-only authorization, or automatic alias substitution.
        rows=self.db.execute('SELECT * FROM security_master WHERE market_symbol=? AND queryable=1 AND present=1',(ticker,)).fetchall()
        if len(rows)!=1:
            raise ValueError(f'{ticker}: no unique active tradable market-data ticker in the security master')
        return MarketDataSymbol(rows[0]['market_symbol'],rows[0]['asset_id'])

    def resolve_identifier(self,kind,value):
        """Explicitly typed mapping for callers that genuinely have an identifier, not a ticker."""
        rows=self.db.execute('SELECT DISTINCT s.market_symbol FROM security_identifiers i INDEXED BY asset_identifier_lookup JOIN security_master s ON s.asset_id=i.entity_id WHERE i.kind=? AND i.value=? AND i.source=\'alpaca_assets\' AND s.queryable=1 AND s.present=1',(kind,str(value))).fetchall()
        if len(rows)!=1:
            raise ValueError(f'No unique authoritative {kind} mapping')
        return self.resolve(rows[0][0])

    def requests(self,cfg, discovery=False):
        with self.store.transaction():
            self.db.execute("UPDATE health SET status='INACTIVE' WHERE provider LIKE 'security-request:%'")
        requested=set(cfg.symbols)|{'SPY','QQQ'}|{r[0] for r in self.db.execute('SELECT symbol FROM holdings WHERE active=1')}|{r[0] for r in self.db.execute('SELECT symbol FROM watchlist')}
        if not cfg.symbols:
            selected=self.db.execute("SELECT value FROM runtime_meta WHERE key='modeling_universe'").fetchone()
            if selected and not discovery:
                requested.update(json.loads(selected[0])['symbols'])
            else:
                requested.update(r[0] for r in self.db.execute('SELECT market_symbol FROM security_master WHERE queryable=1 AND present=1'))
        result=[]
        for ticker in sorted(requested):
            try: result.append(self.resolve(ticker))
            except ValueError as exc:
                self.store.health('security-request:'+ticker,'WARN',str(exc))
                self.store.record('unresolved_security_requests',ticker,{'requested_ticker':ticker,'reason':str(exc)},now_iso())
                logging.getLogger('stox').warning(encode({'stage':'universe','requested_ticker':ticker,'reason':str(exc)}))
        return result

    def assets(self):
        return [{**json.loads(r['payload']),'symbol':r['market_symbol'],'market_data_symbol':r['market_symbol'],
                 'asset_id':r['asset_id'],'security_type':r['security_type'],'queryable':bool(r['queryable']),
                 'resolution_reason':r['reason']} for r in self.db.execute('SELECT * FROM security_master WHERE market_symbol IS NOT NULL AND present=1 AND queryable=1')]

    def quarantine(self,reference,reason,stamp):
        row=self.db.execute('SELECT metadata_hash FROM security_master WHERE asset_id=?',(reference.alpaca_asset_id,)).fetchone()
        with self.store.transaction():
            self.db.execute('INSERT OR REPLACE INTO security_quarantine VALUES(?,?,?,?,?)',
                            (reference.alpaca_asset_id,row[0],reason,stamp,(pd.Timestamp(stamp)+pd.Timedelta(days=7)).isoformat()))
            self.db.execute('UPDATE security_master SET queryable=0,reason=? WHERE asset_id=?',(reason,reference.alpaca_asset_id))
        self.store.health('bars:'+reference.ticker,'WARN',reason)
        logging.getLogger('stox').warning(encode({'stage':'quarantine','ticker':reference.ticker,'asset_id':reference.alpaca_asset_id,'reason':reason}))

    def bind_history(self,reference,stamp):
        if self.db.execute('SELECT 1 FROM price_history_owners WHERE ticker=?',(reference.ticker,)).fetchone(): return
        with self.store.transaction():
            self.db.execute('INSERT OR IGNORE INTO price_history_owners VALUES(?,?,?)',(reference.ticker,reference.alpaca_asset_id,stamp))

    def annotate_action(self,action):
        """Preserve every event identifier; only resolved asset tickers may annotate events."""
        event_id=str(action.get('id') or digest(action))
        entity='corporate-action:'+event_id
        refs=[]
        effective=action.get('ex_date') or action.get('effective_date') or action.get('process_date') or ''
        for field,value in action.items():
            if not isinstance(value,str) or not value: continue
            if field=='id': kind='corporate_action_id'
            elif 'cusip' in field.lower(): kind='cusip'
            elif 'isin' in field.lower(): kind='isin'
            elif 'figi' in field.lower(): kind='figi'
            elif 'asset_id' in field.lower(): kind='alpaca_asset_id'
            elif 'symbol' in field.lower(): kind=identifier_kind(value) or 'provider_symbol'
            else: continue
            cache_key=(kind,value)
            if cache_key not in self._resolution_cache:
                resolved=None
                try:
                    if kind=='provider_symbol': resolved=self.resolve(value)
                    elif kind in ('cusip','isin','figi','alpaca_asset_id'): resolved=self.resolve_identifier(kind,value)
                except ValueError: pass
                if len(self._resolution_cache)>=10000: self._resolution_cache.clear()
                self._resolution_cache[cache_key]=resolved
            resolved=self._resolution_cache[cache_key]
            stored_kind='ticker' if resolved and kind=='provider_symbol' else kind
            if kind=='provider_symbol' and ('old' in field or 'prior' in field) and self.db.execute('SELECT 1 FROM security_master WHERE market_symbol=?',(value,)).fetchone():
                stored_kind='historical_ticker'
            self.identifier(entity,stored_kind,value,'alpaca_corporate_actions',field,effective)
            refs.append({'role':field,'kind':stored_kind,'value':value,'asset_id':resolved.alpaca_asset_id if resolved else None,
                         'market_data_symbol':resolved.ticker if resolved else None,'queryable':bool(resolved)})
        # An event's new ticker does not authorize rewriting historical price series or holdings.
        return {**action,'security_references':refs,'resolved_tickers':sorted({r['market_data_symbol'] for r in refs if r['market_data_symbol']}),
                'identifier_resolution':'resolved' if any(r['queryable'] for r in refs) else 'non-queryable/unresolved'}

    def diagnostics(self,cfg,session=None):
        rows=self.db.execute('SELECT * FROM security_master WHERE present=1').fetchall()
        result={'assets_discovered':len(rows),'eligible_equities_etfs':0,'excluded_asset_classes':0,'inactive_unlisted':0,
                'below_minimum_price':0,'non_tradable_non_queryable':0,'identifier_resolution_failures':0,
                'no_price_history':0,'insufficient_liquidity_data':0,'final_eligible_universe':0,'queryable_tickers':0,
                'intended_query_candidates':sum(r['intended_candidate'] for r in rows),'systemic_identifier_failures':0}
        for r in rows:
            if r['security_type'] in ('common','etf'): result['eligible_equities_etfs']+=1
            else: result['excluded_asset_classes']+=1
            if r['status']!='active': result['inactive_unlisted']+=1
            if not r['queryable']: result['non_tradable_non_queryable']+=1
            failure='identifier-resolution failure' in r['reason'] or 'provider rejected ticker' in r['reason']
            if failure:
                result['identifier_resolution_failures']+=1
                if r['intended_candidate']: result['systemic_identifier_failures']+=1
            if not r['queryable']: continue
            result['queryable_tickers']+=1
            summary=self.store.bar_summary(r['market_symbol'])
            if summary is None:
                result['no_price_history']+=1
                continue
            if summary['close'] < cfg.min_price:
                result['below_minimum_price']+=1
                continue
            threshold=max(cfg.min_dollar_volume,cfg.liquidity_reference_usd/cfg.max_participation)
            if summary['rows']<cfg.min_history or summary['dollar_volume']<threshold or (session and summary['last_session']!=session):
                result['insufficient_liquidity_data']+=1
                continue
            result['final_eligible_universe']+=1
        result['requested_unresolved']=self.db.execute("SELECT count(*) FROM health WHERE provider LIKE 'security-request:%' AND status='WARN'").fetchone()[0]
        result['count_note']='Categories overlap; final eligible requires observed price/history/liquidity. Forecast gates also check missing sessions and models.'
        return result

    def persist_diagnostics(self,cfg,session=None):
        result=self.diagnostics(cfg,session)
        self.store.meta('universe',result)
        self.store.record('universe_diagnostics','latest',result,now_iso())
        logging.getLogger('stox').info(encode({'stage':'universe-summary',**result}))
        return result

    def check_failure_budget(self,cfg):
        row=self.db.execute("SELECT count(*),sum(CASE WHEN reason LIKE '%identifier-resolution failure%' OR reason LIKE '%provider rejected ticker%' THEN 1 ELSE 0 END) FROM security_master WHERE present=1 AND intended_candidate=1").fetchone()
        n,failed=row[0],row[1] or 0
        if failed>=cfg.min_identifier_failures and failed/max(1,n)>cfg.max_identifier_failure_fraction:
            raise RuntimeError(f'Universe identifier-resolution failure: {failed}/{n} intended active tradable securities ({failed/max(1,n):.1%}) exceed {cfg.max_identifier_failure_fraction:.1%}; inspect stox universe. Completed valid checkpoints retained.')

    def resolve_holdings(self):
        for h in self.db.execute('SELECT id,symbol FROM holdings WHERE active=1').fetchall():
            try:
                ref=self.resolve(h['symbol']); aid,status=ref.alpaca_asset_id,'resolved'
            except ValueError:
                aid,status=None,'unresolved/non-queryable'
            with self.store.transaction():
                self.db.execute('UPDATE holdings SET security_id=?,resolution_status=?,input_kind=? WHERE id=?',
                                (aid,status,identifier_kind(h['symbol']) or 'ticker',h['id']))

