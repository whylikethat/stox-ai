"""Small installation preflight; does not open SQLite or touch existing runtime files."""
import importlib.metadata
import os
from pathlib import Path
import sys
import tempfile


def probe(directory):
    """Catch immediate write/fsync/rename/read failures, not certify disk health."""
    fd, name = tempfile.mkstemp(prefix='stox-probe-', dir=directory)
    original = Path(name)
    renamed = original.with_suffix('.renamed')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(b'STOX setup I/O probe\n')
            stream.flush()
            os.fsync(stream.fileno())
        original.replace(renamed)
        if renamed.read_bytes() != b'STOX setup I/O probe\n':
            raise OSError('Setup I/O probe read-back mismatch')
    finally:
        original.unlink(missing_ok=True)
        renamed.unlink(missing_ok=True)


def main():
    repo = Path(__file__).resolve().parents[1]
    for relative in ('.venv', '.stox-local', '.stox-local/tmp', '.stox-local/pip-cache', '.stox-local/cache'):
        path = repo / relative
        if not path.resolve().is_relative_to(repo):
            raise ValueError(f'{path} points outside the repository; setup refuses to install there')
    for relative in ('.stox-local/tmp', '.stox-local/pip-cache', '.stox-local/cache'):
        (repo / relative).mkdir(parents=True, exist_ok=True)
    probe(repo / '.stox-local/tmp')
    sys.path.insert(0, str(repo / 'src'))
    from stox import __version__
    from stox.config import Config
    from stox.paths import locations
    cfg = Config.load()
    print(f'Python: {sys.version.split()[0]} ({sys.executable})', flush=True)
    for name, value in locations(cfg.root).items():
        print(f'{name}: {value}', flush=True)
    if not cfg.root.is_relative_to(repo):
        print('NOTE: your explicit data-root override is outside this repository; existing state has not been moved.', flush=True)
    if '--installed' in sys.argv:
        if Path(sys.prefix).resolve() != (repo / '.venv').resolve():
            raise ValueError('Installation check is not running in the repository .venv')
        installed = importlib.metadata.version('stox-ai')
        if installed != __version__:
            raise ValueError(f'Installed package {installed} differs from source {__version__}')
        print(f'Installed STOX-AI {installed} verified.', flush=True)
    print('Repository I/O probe passed. This small probe does not certify drive health.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, importlib.metadata.PackageNotFoundError) as exc:
        print(f'STOX setup: {exc}', file=sys.stderr)
        raise SystemExit(1)
