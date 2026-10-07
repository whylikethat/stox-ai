from __future__ import annotations
import re

DISALLOWED = re.compile(r'\b(warrant|warrants|rights|units?|preferred|depositary|depositary shares|adr|ads|etn|leveraged|inverse|ultra|ultrapro|ultrashort|short|bear|bull|2x|3x|4x|5x|1\.5x)\b',re.I)

def classify(asset):
    name = asset.get('name','')
    screened = re.sub(r'\bunit investment trust\b', 'investment trust', name, flags=re.I)
    if DISALLOWED.search(screened) or any(x in asset.get('attributes',[]) for x in ('ptp_no_exception','ptp_with_exception')):
        return 'excluded'
    if asset.get('class') != 'us_equity' or asset.get('exchange') not in ('NYSE','NASDAQ','ARCA','AMEX','BATS','NYSEARCA'):
        return 'excluded'
    # Accept explicit fund metadata or recognizable listed investment-trust share structures.
    # No ticker allowlist: QQQ's legacy provider name is 'Invesco QQQ Trust, Series 1'.
    if asset.get('security_type') in ('etf','ETF') or re.search(r'\b(ETF|exchange.traded fund|unit investment trust)\b|\btrust[,\s]+series\s+\d+\b',name,re.I):
        return 'etf'
    if re.search(r'\b(common|ordinary|capital stock)\b',name,re.I):
        return 'common'
    return 'unclassified'

def eligible(asset, row, cfg):
    reasons = []
    if asset.get('security_type',classify(asset)) not in ('common','etf'):
        reasons.append('security type is excluded or unverified')
    if asset.get('queryable') is not True or asset.get('tradable') is not True:
        reasons.append('security master has not verified a queryable tradable ticker')
    if asset.get('status') != 'active':
        reasons.append('inactive security')
    if row['close'] < cfg.min_price:
        reasons.append('price below minimum')
    threshold = max(cfg.min_dollar_volume,cfg.liquidity_reference_usd/cfg.max_participation)
    if row.get('dollar_volume',0) < threshold:
        reasons.append('insufficient median dollar liquidity')
    if row.get('history_count',0) < cfg.min_history:
        reasons.append('insufficient history')
    if row.get('missing_recent',1):
        reasons.append('missing recent regular sessions')
    return reasons
