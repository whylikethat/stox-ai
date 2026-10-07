"""Repository defaults and process-scoped scratch space; never relocate user data."""
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile


def repository_root():
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / 'pyproject.toml').is_file() and (candidate / 'src' / 'stox').is_dir():
        return candidate
    # A non-editable wheel has no source checkout. Explicit --config/--root still work.
    return Path.cwd().resolve()


def default_config():
    return repository_root() / 'config.toml'


def locations(root):
    repository = repository_root()
    root = Path(root).resolve()
    return {
        'repository': str(repository),
        'virtual_environment': str(repository / '.venv'),
        'installer_cache': str(repository / '.stox-local' / 'pip-cache'),
        'installer_temporary': str(repository / '.stox-local' / 'tmp'),
        'data_root': str(root),
        'database': str(root / 'state.sqlite'),
        'runtime_cache': str(root / 'cache'),
        'runtime_temporary': str(root / 'tmp'),
        'data_inside_repository': root.is_relative_to(repository),
    }


@contextmanager
def runtime_environment(root):
    """Keep tempfile, SQLite, joblib and XDG caches beside the selected runtime state.

    Restore process globals for embedded callers/tests. The CLI uses one data root
    at a time; this context is not intended for concurrent roots in one process.
    """
    root = Path(root).resolve()
    temporary = root / 'tmp'
    cache = root / 'cache'
    joblib = temporary / 'joblib'
    for directory in (temporary, cache, joblib):
        if not directory.resolve().is_relative_to(root):
            raise ValueError(f'Runtime scratch path escapes the data root: {directory}')
        directory.mkdir(parents=True, exist_ok=True)
    values = {key: str(temporary) for key in ('TMPDIR', 'TMP', 'TEMP', 'SQLITE_TMPDIR')}
    values.update(XDG_CACHE_HOME=str(cache), JOBLIB_TEMP_FOLDER=str(joblib))
    previous = {key: os.environ.get(key) for key in values}
    previous_tempdir = tempfile.tempdir
    try:
        os.environ.update(values)
        tempfile.tempdir = str(temporary)
        yield
    finally:
        tempfile.tempdir = previous_tempdir
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
