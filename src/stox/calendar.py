from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
import exchange_calendars as xc
import pandas as pd
from functools import lru_cache

UTC = timezone.utc

def utc(value=None) -> pd.Timestamp:
    t = pd.Timestamp(value or datetime.now(UTC))
    if t.tzinfo is None:
        raise ValueError('Timestamp must have an explicit timezone')
    return t.tz_convert('UTC')

class MarketCalendar:
    def __init__(self, start='1990-01-01', end='2035-12-31'):
        self.cal = xc.get_calendar('XNYS', start=start, end=end)

    @lru_cache(maxsize=100000)
    def sessions(self, start, end):
        return [t.date().isoformat() for t in self.cal.sessions_in_range(str(start)[:10], str(end)[:10])]

    @lru_cache(maxsize=100000)
    def open(self, session):
        return self.cal.session_open(session)

    @lru_cache(maxsize=100000)
    def close(self, session):
        return self.cal.session_close(session)

    def completed(self, now):
        now = utc(now)
        sessions = self.sessions((now - pd.Timedelta(days=14)).date(), now.date())
        return next(s for s in reversed(sessions) if self.close(s) <= now)

    @lru_cache(maxsize=100000)
    def next_open(self, issued):
        now = utc(issued)
        return next(s for s in self.sessions(now.date(), (now + pd.Timedelta(days=14)).date()) if self.open(s) > now)

    @lru_cache(maxsize=100000)
    def settle(self, entry, horizon):
        target = date.fromisoformat(str(entry)[:10]) + timedelta(days=int(horizon))
        return self.cal.date_to_session(target.isoformat(), direction='next').date().isoformat()

    def sip_end(self, now):
        now = utc(now)
        session = self.completed(now)
        if self.close(session) > now - pd.Timedelta(minutes=16):
            raise ValueError('Latest regular close is inside the SIP delay window; retry after close + 16 minutes.')
        return session, self.close(session).isoformat()
