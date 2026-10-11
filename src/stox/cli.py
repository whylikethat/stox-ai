from __future__ import annotations
import argparse
import json
import sys
import sqlite3
from contextlib import nullcontext
from . import __version__
from .config import Config
from .paths import locations, runtime_environment


def parser():
    p=argparse.ArgumentParser(prog='stox',description='Local US-equity forecasting and evidence review')
    p.add_argument('--version',action='version',version=__version__)
    p.add_argument('--config',help='TOML config path; relative storage paths resolve beside this file')
    p.add_argument('--root',help='Override storage root')
    sub=p.add_subparsers(dest='command',required=True)
    for name in ('run','bootstrap'):
        s=sub.add_parser(name)
        s.add_argument('--offline',action='store_true',help='Research from cached data; no new official forecasts')
        s.add_argument('--retrain',action='store_true')
    s=sub.add_parser('demo',help='Deterministic isolated synthetic end-to-end demonstration')
    s.add_argument('--end',default='2025-12-19')
    s=sub.add_parser('doctor')
    s.add_argument('--live',action='store_true')
    s.add_argument('--vintages',action='store_true',help='With --live, separately test an ALFRED as-of snapshot')
    d=sub.add_parser('disclosures',help='Optional public transaction context; never model signals')
    ds=d.add_subparsers(dest='action',required=True)
    ds.add_parser('sync')
    ds.add_parser('list')
    a=ds.add_parser('import')
    a.add_argument('--source',choices=('sec','house','senate'),required=True)
    a.add_argument('--file',required=True)
    a.add_argument('--url',required=True,help='Official source URL for this report')
    a.add_argument('--filing-date')
    a.add_argument('--publication-at')
    a.add_argument('--acceptance-at')
    a.add_argument('--amends',help='Official URL or accession corrected by this report, if known')
    sub.add_parser('status')
    sub.add_parser('paths',help='Show resolved installation/data paths without opening the database')
    s=sub.add_parser('compact',help='Explicit stopped-writer SQLite integrity check and compaction')
    s.add_argument('--vacuum',action='store_true',required=True)
    sub.add_parser('upgrade',help='Non-destructive schema upgrade and legacy action receipt backfill')
    s=sub.add_parser('diagnose',help='Read-only local database diagnostics')
    s.add_argument('--deep',action='store_true',help='Opt-in table/index scans; may take time')
    s.add_argument('--integrity',action='store_true',help='Opt-in SQLite integrity check; stop bootstrap first')
    sub.add_parser('universe',help='Universe counts, unresolved references and quarantine reasons')
    s=sub.add_parser('report')
    s.add_argument('--format',choices=('html','json','md','ai'),default='html')
    w=sub.add_parser('watchlist',help='User-managed symbols; never populated automatically')
    ws=w.add_subparsers(dest='action',required=True)
    ws.add_parser('list')
    for action in ('add','remove'):
        ws.add_parser(action).add_argument('symbol')
    s=sub.add_parser('holdings')
    hs=s.add_subparsers(dest='action',required=True)
    a=hs.add_parser('add')
    a.add_argument('symbol')
    a.add_argument('--date')
    a.add_argument('--price',type=float)
    a.add_argument('--shares',type=float)
    hs.add_parser('list')
    a=hs.add_parser('remove')
    a.add_argument('id',type=int)
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        cfg=Config.load(args.config,args.root)
        if args.command=='upgrade' and not (cfg.root/'state.sqlite').is_file():
            raise ValueError(f'No existing state.sqlite at {cfg.root}; upgrade refuses to initialize empty state. Check your original config/root.')
        readonly = args.command in ('status','paths','report') or (args.command=='diagnose' and not cfg.root.exists())
        with nullcontext() if readonly else runtime_environment(cfg.root):
            return dispatch(args,cfg)
    except KeyboardInterrupt:
        print('Interrupted safely. Completed checkpoints retained; rerun the same command to resume.',file=sys.stderr)
        return 130
    except (ValueError,RuntimeError,OSError,sqlite3.Error) as exc:
        print(f'STOX-AI: {exc}',file=sys.stderr)
        return 1

def dispatch(args,cfg):
    if args.command=='paths':
        print(json.dumps(locations(cfg.root),indent=2))
    elif args.command=='demo':
        if not args.root:
            raise ValueError('Use --root with an isolated demo directory, e.g. stox --root ./demo-data demo')
        from .demo import seed
        from .engine import run
        if cfg.symbols:
            cfg.symbols=tuple(dict.fromkeys(('SPY','QQQ')+cfg.symbols))[:8]
        stamp=seed(cfg,args.end)
        report,path=run(cfg,offline=True,force_train=True,timestamp=stamp,synthetic=True)
        print('SYNTHETIC DEMONSTRATION: not live investment evidence')
        print(f'Completed {len(report["backtests"])} trained horizons. Reports: {path}')
    elif args.command in ('run','bootstrap'):
        from .engine import run
        report,path=run(cfg,offline=args.offline,force_train=args.retrain)
        from .reporting import terminal
        print(terminal(report))
        print(f'Reports: {path}')
    elif args.command=='disclosures':
        from pathlib import Path
        from .storage import Store
        from .disclosures import Collector
        cfg.initialize()
        store=Store(cfg.root)
        try:
            with store.lock():
                collector=Collector(cfg,store)
                if args.action=='sync': result=collector.sync()
                elif args.action=='list':
                    result={'documents':store.records('disclosure_documents'), 'transactions':store.records('disclosure_transactions')}
                else:
                    path=Path(args.file)
                    if path.stat().st_size>20_000_000: raise ValueError('Disclosure exceeds 20 MB bound')
                    result=collector.ingest(args.source,args.url,path.read_bytes(),
                        {'filing_date':args.filing_date,'publication_at':args.publication_at,'acceptance_at':args.acceptance_at,'amends':args.amends})
                print(json.dumps(result,indent=2))
        finally: store.close()
    elif args.command=='doctor':
        from .doctor import doctor
        if args.vintages and not args.live:
            raise ValueError('--vintages requires --live')
        results=doctor(cfg,args.live,args.vintages)
        for r in results:
            print(f'{r["status"]:4} {r["check"]}: {r["detail"]}')
        return 1 if any(r['status']=='FAIL' for r in results) else 0
    elif args.command in ('status','diagnose'):
        from .diagnostics import status,diagnose
        payload=status(cfg.root) if args.command=='status' else diagnose(cfg.root,args.deep,args.integrity)
        print(json.dumps(payload,indent=2))
        if payload.get('integrity_check', ['ok']) != ['ok']:
            return 1
    elif args.command=='compact':
        from .diagnostics import compact
        print(json.dumps(compact(cfg.root),indent=2))
    elif args.command=='upgrade':
        from .storage import Store
        from .security import SecurityMaster
        from .progress import Progress
        from .streams import reuse_legacy_actions
        if not (cfg.root/'state.sqlite').is_file():
            raise ValueError(f'No existing state.sqlite at {cfg.root}; upgrade refuses to initialize empty state. Check your original config/root.')
        cfg.initialize()
        store=Store(cfg.root)
        try:
            with store.lock():
                progress=Progress(store,'upgrade')
                with progress.stage('legacy-action-index'):
                    reuse_legacy_actions(store,SecurityMaster(store),progress)
            print('Upgrade complete. Existing bars, event revisions and checkpoints retained.')
        finally:
            store.close()
    elif args.command=='report':
        name={'html':'latest.html','json':'latest.json','md':'latest.md','ai':'latest_ai_review.md'}[args.format]
        path=cfg.root/'reports'/name
        if not path.exists():
            raise ValueError('No completed report yet. Run stox bootstrap or stox run.')
        print(path if args.format=='html' else path.read_text())
    else:
        from .storage import Store
        from .security import SecurityMaster
        cfg.initialize()
        store=Store(cfg.root)
        try:
            if args.command=='universe':
                master=SecurityMaster(store)
                master.ensure()
                print(json.dumps({'counts':master.diagnostics(cfg),'excluded':[dict(r) for r in store.db.execute("SELECT asset_id,provider_symbol,reason FROM security_master WHERE queryable=0")], 'unresolved_requests':[dict(r) for r in store.db.execute("SELECT * FROM health WHERE provider LIKE 'security-request:%' AND status='WARN'")]},indent=2))
            elif args.command=='watchlist':
                if args.action=='list':
                    print(json.dumps([r[0] for r in store.db.execute('SELECT symbol FROM watchlist ORDER BY symbol')]))
                else:
                    from .security import ticker_shape,identifier_kind
                    from .storage import now_iso
                    symbol=args.symbol.strip().upper()
                    if not ticker_shape(symbol) or identifier_kind(symbol):
                        raise ValueError('Watchlist requires a ticker, not a security identifier')
                    with store.lock(),store.transaction():
                        if args.action=='add':
                            store.db.execute('INSERT OR IGNORE INTO watchlist VALUES(?,?)',(symbol,now_iso()))
                        else:
                            store.db.execute('DELETE FROM watchlist WHERE symbol=?',(symbol,))
                    print('Watchlist updated.')
            elif args.action=='list':
                print(json.dumps([dict(r) for r in store.db.execute('SELECT * FROM holdings WHERE active=1')],indent=2))
            elif args.action=='add':
                from .holdings import add
                day=args.date or input('Purchase date (YYYY-MM-DD): ').strip()
                price=args.price if args.price is not None else float(input('Purchase price (USD): '))
                with store.lock():
                    hid=add(store,args.symbol,day,price,args.shares)
                print(f'Holding {hid} added.')
            elif args.action=='remove':
                with store.lock(),store.db:
                    n=store.db.execute('UPDATE holdings SET active=0 WHERE id=? AND active=1',(args.id,)).rowcount
                if not n:
                    raise ValueError('Active holding not found')
                print('Holding marked inactive; historical reviews preserved.')
        finally:
            store.close()
    return 0

if __name__=='__main__':
    raise SystemExit(main())

