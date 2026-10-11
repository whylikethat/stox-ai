from __future__ import annotations
import math

class UnresolvedAction(ValueError):
    pass

def action_date(action):
    return str(action.get('ex_date') or action.get('effective_date') or action.get('process_date') or '')[:10]

def role_matches(action, role, symbol):
    # Only ticker roles or authoritative resolved ticker references; never CUSIP text.
    return action.get(role)==symbol or any(
        r.get('role')==role and r.get('market_data_symbol')==symbol
        and r.get('kind')=='ticker' for r in action.get('security_references',[]))


def applies_to_returns(action, symbol):
    # Buying another company is context for the acquirer, not a conversion of
    # each existing acquirer share. Ambiguous/target-side events stay blocked.
    if kind(action) in ('cash_merger','stock_merger','stock_and_cash_merger'):
        if (action.get('acquiree_symbol') and role_matches(action,'acquirer_symbol',symbol)
                and not role_matches(action,'acquiree_symbol',symbol)
                and not (action.get('acquirer_cusip') and action.get('acquirer_cusip')==action.get('acquiree_cusip'))):
            return False
    return True


def relevant(actions, symbol, for_returns=True):
    matched=[a for a in actions if symbol in a.get('resolved_tickers',[]) or symbol in
             tuple(a.get(k) for k in ('symbol','old_symbol','new_symbol','initiating_symbol','target_symbol','acquirer_symbol','acquiree_symbol','source_symbol'))]
    return [a for a in matched if not for_returns or applies_to_returns(a,symbol)]


def kind(action):
    return action['action_type'].rstrip('s')

def split_ratio(action):
    old = float(action.get('old_rate',0))
    new = float(action.get('new_rate',0))
    if old <= 0 or new <= 0:
        raise UnresolvedAction('Split ratio is missing or invalid')
    return new/old

def total_return(entry_price, exit_price, entry_date, exit_date, actions, friction_bps=20):
    if entry_price <= 0 or exit_price <= 0:
        raise ValueError('Prices must be positive')
    units,cash = 1.,0.
    # Entry at the ex-date open does not earn that day's distribution/split adjustment.
    events = sorted([a for a in actions if entry_date < action_date(a) <= exit_date],key=lambda a:(action_date(a),0 if 'split' in kind(a) else 1))
    for a in events:
        k = kind(a)
        if a.get('currency','USD') not in ('USD',None,''):
            raise UnresolvedAction('Non-USD distribution requires verified conversion')
        if k in ('forward_split','reverse_split'):
            units *= split_ratio(a)
        elif k=='stock_dividend':
            try: multiplier=float(a['rate'])
            except (KeyError,TypeError,ValueError):
                raise UnresolvedAction('Stock dividend multiplier is missing or invalid')
            if not math.isfinite(multiplier) or multiplier<1:
                raise UnresolvedAction('Stock dividend multiplier is missing or invalid')
            units *= multiplier
        elif k in ('cash_dividend','capital_gains_distribution'):
            rate = a.get('rate',a.get('cash_amount'))
            if rate is None:
                raise UnresolvedAction('Cash distribution amount missing')
            cash += units * float(rate)
        elif k in ('name_change','symbol_change'):
            continue
        else:
            raise UnresolvedAction(f'Unresolved {k}: no numeric outcome until verified')
    return (units*exit_price+cash)/entry_price - 1 - friction_bps/10000

def adjusted_history(frame, actions):
    """Causal wealth index: only effective actions at/before each historical bar."""
    f = frame.sort_values('session').copy()
    wealth = [float(f.iloc[0]['close'])]
    for prev,row in zip(f.iloc[:-1].to_dict('records'),f.iloc[1:].to_dict('records')):
        ret = total_return(prev['close'],row['close'],prev['session'],row['session'],actions,0)
        wealth.append(wealth[-1]*(1+ret))
    f['wealth'] = wealth
    return f
