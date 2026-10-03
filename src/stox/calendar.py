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


    def historical_sip_window(self, now, count=5):
        """Small completed-day canary window; independent of production freshness gates.

        Daily bars are stamped at New York midnight, not the session open.
        Exclude the current local day and leave a 16-minute margin at the end.
        """
        now = utc(now)
        safe_end = now - pd.Timedelta(minutes=16)
        today = now.tz_convert('America/New_York').date()
        candidates = []
        for session in self.sessions((now - pd.Timedelta(days=40)).date(), today):
            midnight = pd.Timestamp(session).tz_localize('America/New_York')
            day_end = midnight + pd.DateOffset(days=1) - pd.Timedelta(microseconds=1)
            if midnight.date() < today and day_end <= safe_end and self.close(session) <= safe_end:
                candidates.append((session, midnight, day_end))
        if not candidates:
            raise ValueError('No safely completed historical SIP session in calendar window')
        selected = candidates[-count:]
        return ([r[0] for r in selected], selected[0][1].tz_convert('UTC').isoformat(),
                selected[-1][2].tz_convert('UTC').isoformat())
