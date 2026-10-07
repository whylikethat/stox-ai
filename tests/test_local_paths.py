"""Contain installer/runtime scratch space and preserve existing data on failures."""
import errno
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest
from stox.config import Config
from stox.paths import repository_root, runtime_environment


@pytest.fixture
def checkout(tmp_path):
    source = Path(__file__).resolve().parents[1]
    root = tmp_path / 'External volume 新加卷' / 'stox-ai'
    root.mkdir(parents=True)
    shutil.copytree(source / 'src', root / 'src', ignore=shutil.ignore_patterns('__pycache__','*.egg-info'))
    shutil.copytree(source / 'scripts', root / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('pyproject.toml','config.example.toml','providers.env.example','requirements.lock'):
        shutil.copy2(source / name, root / name)
    return root


def environment(root, tmp_path):
    env = dict(os.environ)
    for key in ('STOX_HOME','STOX_CONFIG','PYTHONPATH','PYTHONHOME','PYTHONPYCACHEPREFIX'):
        env.pop(key, None)
    internal = tmp_path / 'internal-home'
    internal.mkdir(exist_ok=True)
    env.update(HOME=str(internal), STOX_PYTHON=sys.executable,
               TMPDIR=str(internal), XDG_CACHE_HOME=str(internal / '.cache'),
               PIP_CACHE_DIR=str(internal / 'pip'),
               PIP_TARGET=str(internal / 'packages'), PIP_USER='true')
    return env


def setup(root, env, *args):
    return subprocess.run(['bash',str(root / 'scripts/setup.sh'),*args],env=env,
                          cwd=env['HOME'],capture_output=True,text=True)


def test_default_config_follows_checkout_not_launch_directory(tmp_path, monkeypatch):
    monkeypatch.delenv('STOX_CONFIG',raising=False)
    monkeypatch.delenv('STOX_HOME',raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path/'config.toml').write_text('[stox]\nroot="accidental-internal-state"\n')
    assert Config.load().root == repository_root()/'.stox'
    assert not (tmp_path/'accidental-internal-state').exists()


def test_explicit_config_and_root_overrides_preserve_state(tmp_path, monkeypatch):
    config = tmp_path/'config.toml'
    config.write_text('[stox]\nroot="original-state"\n')
    monkeypatch.setenv('STOX_CONFIG',str(config))
    assert Config.load().root == tmp_path/'original-state'
    monkeypatch.setenv('STOX_HOME','environment-state')
    assert Config.load().root == tmp_path/'environment-state'
    assert Config.load(root='explicit-state').root == tmp_path/'explicit-state'


def test_paths_and_status_from_outside_repo_are_readonly(checkout, tmp_path):
    env=environment(checkout,tmp_path)
    env.update(PYTHONPATH=str(checkout/'src'), PYTHONDONTWRITEBYTECODE='1')
    for command in ('paths','status'):
        result=subprocess.run([sys.executable,'-m','stox',command],env=env,cwd=env['HOME'],capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        payload=json.loads(result.stdout)
        if command=='paths':
            assert payload['data_root']==str(checkout/'.stox')
            assert payload['data_inside_repository']
        else:
            assert payload['state']=='not_initialized'
    assert not (checkout/'.stox').exists()
    assert not (checkout/'.stox-local').exists()
    assert not list(Path(env['HOME']).iterdir())


def test_runtime_scratch_overrides_internal_paths_and_restores_them(tmp_path, monkeypatch):
    root=tmp_path/'runtime'
    keys=('TMPDIR','TMP','TEMP','SQLITE_TMPDIR','JOBLIB_TEMP_FOLDER','XDG_CACHE_HOME')
    for key in keys: monkeypatch.setenv(key,'/internal-sentinel')
    original=tempfile.tempdir
    with pytest.raises(RuntimeError),runtime_environment(root):
        with tempfile.NamedTemporaryFile() as file:
            assert Path(file.name).parent==root/'tmp'
        assert all(Path(os.environ[key]).is_relative_to(root) for key in keys)
        raise RuntimeError('simulated provider failure')
    assert tempfile.tempdir==original
    assert all(os.environ[key]=='/internal-sentinel' for key in keys)


def test_runtime_refuses_scratch_symlink_outside_root(tmp_path):
    root=tmp_path/'runtime';root.mkdir()
    outside=tmp_path/'internal';outside.mkdir()
    (root/'tmp').symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError,match='escapes'):
        with runtime_environment(root): pass
    assert not list(outside.iterdir())


def test_setup_check_preserves_runtime_config_and_secrets(checkout, tmp_path):
    state=checkout/'.stox';state.mkdir()
    (state/'state.sqlite').write_bytes(b'expensive existing database fixture')
    (state/'state.sqlite-wal').write_bytes(b'valuable pending WAL')
    (checkout/'config.toml').write_text('[stox]\nroot=".stox"\n')
    secrets=checkout/'.secrets';secrets.mkdir()
    (secrets/'providers.env').write_text('ALPACA_API_KEY=never-print-this\n')
    before={p:p.read_bytes() for p in [state/'state.sqlite',state/'state.sqlite-wal',checkout/'config.toml',secrets/'providers.env']}
    env=environment(checkout,tmp_path)
    result=setup(checkout,env,'--check')
    assert result.returncode==0,result.stderr
    assert 'never-print-this' not in result.stdout+result.stderr
    assert all(p.read_bytes()==data for p,data in before.items())
    assert not (checkout/'.venv').exists()
    assert not list(Path(env['HOME']).iterdir())
    assert not list((checkout/'.stox-local/tmp').iterdir())


def test_setup_refuses_external_scratch_symlink(checkout,tmp_path):
    outside=tmp_path/'outside';outside.mkdir()
    (checkout/'.stox-local').symlink_to(outside,target_is_directory=True)
    result=setup(checkout,environment(checkout,tmp_path),'--check')
    assert result.returncode!=0
    assert 'outside the repository' in result.stderr
    assert not list(outside.iterdir())


def test_setup_preserves_broken_venv_instead_of_recreating(checkout,tmp_path):
    venv=checkout/'.venv';venv.mkdir()
    marker=venv/'preserve';marker.write_text('old environment')
    result=setup(checkout,environment(checkout,tmp_path))
    assert result.returncode!=0
    assert 'preserved' in result.stderr
    assert marker.read_text()=='old environment'


def fake_venv(root, fail_install=False):
    """Observe shell orchestration without network; real install is checked separately."""
    binary=root/'.venv/bin';binary.mkdir(parents=True)
    python=binary/'python'
    python.write_text('#!'+sys.executable+'\n'+'''
import json,os,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]
args=sys.argv[1:]
with (root/'calls.jsonl').open('a') as file:
    file.write(json.dumps({'args':args,'env':dict(os.environ)})+'\\n')
if args[:2]==['-m','pip'] or '--installed' in args:
    if FAIL and args[:3]==['-m','pip','install']:
        print('OSError: [Errno 5] Input/output error',file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(0)
if '-c' in args:
    raise SystemExit(0)  # shell orchestration fixture; real invalid environments tested below
os.execv(REAL,[REAL,*args])
'''.replace('FAIL',repr(fail_install)).replace('REAL',repr(sys.executable)))
    python.chmod(0o755)


def test_setup_existing_venv_routes_every_pip_call_inside_checkout(checkout,tmp_path):
    fake_venv(checkout)
    env=environment(checkout,tmp_path)
    env['STOX_PYTHON']='/missing/system-python-3.14'  # existing supported environment wins
    result=setup(checkout,env)
    assert result.returncode==0,result.stderr
    calls=[json.loads(line) for line in (checkout/'calls.jsonl').read_text().splitlines()]
    pip=[c for c in calls if c['args'][:2]==['-m','pip']]
    assert len(pip)==3 and pip[-1]['args']==['-m','pip','check']
    for call in pip:
        for key in ('TMPDIR','TMP','TEMP','PIP_CACHE_DIR','XDG_CACHE_HOME'):
            assert Path(call['env'][key]).is_relative_to(checkout)
        assert 'PIP_TARGET' not in call['env']
        assert call['env']['PIP_USER']=='false'
    assert any('--no-build-isolation' in c['args'] for c in pip)
    assert any('--installed' in c['args'] for c in calls)
    assert not list(Path(env['HOME']).iterdir())
    assert not (checkout/'.stox').exists()


def test_setup_io_failure_stops_without_opening_existing_database(checkout,tmp_path):
    fake_venv(checkout,fail_install=True)
    root=checkout/'.stox';root.mkdir()
    db=root/'state.sqlite';db.write_bytes(b'valuable legacy database')
    result=setup(checkout,environment(checkout,tmp_path))
    assert result.returncode!=0
    assert 'Input/output error' in result.stderr
    assert 'Do not start bootstrap' in result.stderr
    assert db.read_bytes()==b'valuable legacy database'
    assert not (checkout/'config.toml').exists()


def test_preflight_detects_fsync_failure_and_removes_only_its_probe(tmp_path, monkeypatch):
    script=Path(__file__).resolve().parents[1]/'scripts/check_setup.py'
    spec=importlib.util.spec_from_file_location('check_setup',script)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    sentinel=tmp_path/'keep';sentinel.write_bytes(b'keep')
    def failure(*args): raise OSError(errno.EIO,'Input/output error')
    monkeypatch.setattr(module.os,'fsync',failure)
    with pytest.raises(OSError): module.probe(tmp_path)
    assert list(tmp_path.iterdir())==[sentinel]


def test_setup_rejects_system_python_disguised_as_venv(checkout,tmp_path):
    binary=checkout/'.venv/bin';binary.mkdir(parents=True)
    (binary/'python').symlink_to(sys.executable)
    result=setup(checkout,environment(checkout,tmp_path))
    assert result.returncode!=0
    assert 'invalid' in result.stderr
    assert not (checkout/'.stox-local').exists()
