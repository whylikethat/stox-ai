from __future__ import annotations
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

SECRET_NAMES = ('ALPACA_API_KEY', 'ALPACA_API_SECRET', 'FRED_API_KEY', 'ALPHAVANTAGE_API_KEY', 'SEC_USER_AGENT')

@dataclass
class Config:
    root: Path
    horizons: tuple[int, ...] = (20, 30, 60, 90)
    history_start: str = '2016-01-01'
    friction_bps: float = 20
    min_price: float = 5
    min_dollar_volume: float = 20_000_000
    min_history: int = 252
    min_core_coverage: float = .90
    max_identifier_failure_fraction: float = .05
    min_identifier_failures: int = 2
    max_participation: float = .005
    liquidity_reference_usd: float = 100_000
    soft_storage_gb: float = 100
    hard_storage_gb: float = 150
    av_daily_budget: int = 20
    event_refresh_minutes: int = 15
    retrain_days: int = 30
    min_new_labels: int = 500
    max_training_rows: int = 250_000
    min_validation_blocks: int = 8
    min_bucket_samples: int = 100
    max_calibration_error: float = .10
    max_tail_probability: float = .10
    threads: int = 2
    symbols: tuple[str, ...] = ()
    macro_series: tuple[str, ...] = ('DGS10', 'DGS2', 'UNRATE', 'CPIAUCSL', 'BAMLC0A0CM')
    secrets: dict[str, str] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, path: str | None = None, root: str | None = None):
        config_path = Path(path or os.environ.get('STOX_CONFIG', 'config.toml')).expanduser().resolve()
        raw = tomllib.loads(config_path.read_text()) if config_path.exists() else {}
        base = config_path.parent
        values = raw.get('stox', {})
        location = Path(root or os.environ.get('STOX_HOME') or values.pop('root', '.stox')).expanduser()
        if not location.is_absolute():
            location = base / location
        for key in ('horizons', 'symbols', 'macro_series'):
            if key in values:
                values[key] = tuple(values[key])
        cfg = cls(root=location.resolve(), **values)
        if 30 not in cfg.horizons or any(h <= 0 for h in cfg.horizons) or len(set(cfg.horizons)) != len(cfg.horizons):
            raise ValueError('Horizons must be unique positive calendar-day values including 30.')
        if not 0 <= cfg.event_refresh_minutes <= 1440:
            raise ValueError('event_refresh_minutes must be between 0 and 1440')
        if cfg.friction_bps < 0 or not 0 < cfg.soft_storage_gb < cfg.hard_storage_gb:
            raise ValueError('Invalid friction or storage limits.')
        if not 0 < cfg.max_identifier_failure_fraction <= 1 or cfg.min_identifier_failures < 2:
            raise ValueError('Invalid universe identifier-failure limits.')
        secrets_path = base / '.secrets' / 'providers.env'
        if secrets_path.exists():
            for line in secrets_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    if key.strip() in SECRET_NAMES:
                        cfg.secrets[key.strip()] = value.strip().strip('\"\'')
        cfg.secrets.update({k: os.environ[k] for k in SECRET_NAMES if os.environ.get(k)})
        return cfg

    def initialize(self):
        for folder in ('warehouse', 'models', 'reports/runs', 'logs', 'cache'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)

    def public(self):
        return {k: str(v) if isinstance(v, Path) else v for k, v in vars(self).items() if k != 'secrets'}
