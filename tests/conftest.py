import socket
import pytest
from stox.config import Config
from stox.storage import Store
from stox.calendar import MarketCalendar

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args,**kwargs):
        raise AssertionError('Offline tests must not contact any network')
    monkeypatch.setattr(socket.socket,'connect',blocked)

@pytest.fixture
def cfg(tmp_path):
    c=Config(tmp_path/'state')
    # Legacy provider fixtures exercise ingestion itself with two daily bars.
    # Autonomous screening has dedicated realistic batched fixtures.
    c.autonomous_universe=False
    c.history_window_days=31
    c.initialize()
    return c

@pytest.fixture
def store(cfg):
    s=Store(cfg.root)
    yield s
    s.close()

@pytest.fixture(scope='session')
def calendar():
    return MarketCalendar()

