import json
import numpy as np
import pandas as pd
import pytest
from stox.demo import seed
from stox.engine import run
from stox.models import BinaryModel,Sigmoid,metrics
from stox.predictions import issue,settle
from stox.holdings import review
from stox.reporting import write_reports
from stox.storage import Store
from stox.cli import main


def test_constant_classifier_and_calibration():
    X=np.ones((50,2))
    model=BinaryModel('logistic').fit(X,np.zeros(50))
    assert np.all(model.predict(X)==0)
    cal=Sigmoid().fit(np.full(50,.99),np.zeros(50))
    assert np.all(cal.predict(np.full(10,.99))==0)


def test_cli_offline(cfg,capsys):
    assert main(['--root',str(cfg.root),'doctor'])==0
    assert 'Not contacted' in capsys.readouterr().out
    assert main(['--root',str(cfg.root),'holdings','add','AAPL','--date','2025-01-01','--price','100','--shares','5'])==0
    assert main(['--root',str(cfg.root),'holdings','list'])==0
    assert 'AAPL' in capsys.readouterr().out
    assert main(['--root',str(cfg.root),'holdings','remove','1'])==0
    assert main(['--root',str(cfg.root),'status'])==0


def test_end_to_end_synthetic(cfg,calendar):
    stamp=seed(cfg)
    report,path=run(cfg,offline=True,force_train=True,timestamp=stamp,synthetic=True)
    assert set(report['backtests'])=={'20','30','60','90'}
    assert len(report['research_candidates'])==32
    assert all((path/f).exists() for f in ['report.html','report.md','report.json','ai_review.md'])
    assert report['synthetic']
    assert 'SYNTHETIC' in (path/'report.html').read_text()
    assert 'SUPPORTIVE' in (path/'ai_review.md').read_text()
    assert 'John' not in (path/'report.md').read_text()
    assert len(report['holdings'])==1
    # Exercise issuance and settlement using an explicitly manufactured synthetic fixture.
    # These probabilities are NOT presented as validated model selections.
    store=Store(cfg.root)
    fixture=[dict(r,qualified=True,fixture_only=True,primary_rank=1 if r['horizon']==30 else None) for r in report['research_candidates'] if r['symbol']=='DEMOA']
    ids=issue(store,calendar,fixture,'2025-06-07T15:00:00Z',{'event_cutoff':'2025-06-07T15:00:00Z','fixture_only':True,'mode':'synthetic'})
    assert ids
    result=settle(store,calendar,stamp,cfg.friction_bps)
    assert result['newly_settled']>=4
    old=fixture[1]
    from stox.holdings import add
    hid=add(store,'DEMOA','2025-06-09',100,5)
    deterioration=[dict(r,model_validated=True,expected_return=-.10,p_gain=.2,p_loss_20=.2) for r in fixture]
    reviews=review(store,deterioration,'negative-test')
    assert any(r['status']=='MATERIAL NEGATIVE CHANGE' for r in reviews)
    before=store.db.execute('SELECT count(*) FROM forecasts').fetchone()[0]
    issue(store,calendar,fixture,'2025-06-07T15:00:00Z',{'event_cutoff':'2025-06-07T15:00:00Z','fixture_only':True,'mode':'synthetic'})
    assert store.db.execute('SELECT count(*) FROM forecasts').fetchone()[0]==before
    store.close()


def test_feature_causality(cfg,calendar):
    from stox.features import market_features
    from stox.demo import seed
    seed(cfg,end='2016-12-30')
    store=Store(cfg.root)
    bars=store.bars('DEMOA')
    first=market_features(bars,[],calendar)
    changed=bars.copy()
    changed.loc[changed.index[-10:],'close']*=1.5
    second=market_features(changed,[],calendar)
    pd.testing.assert_frame_equal(first.iloc[:-10],second.iloc[:-10])
    store.close()
