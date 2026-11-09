"""Run v1.0.27 safety scenario in its own interpreter to isolate database globals."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

ROOT=Path(__file__).resolve().parents[1]
SCENARIO=ROOT/'tests'/'financial_safety_scenario.py'


def scenario(url: str):
    env={**os.environ,'DATABASE_URL':url, 'PYTHONPATH':str(ROOT),
         'TOTP_ENCRYPTION_KEY':Fernet.generate_key().decode('ascii')}
    p=subprocess.run([sys.executable,str(SCENARIO)],cwd=ROOT,env=env,
                     capture_output=True,text=True,timeout=90)
    assert p.returncode==0,p.stdout+'\n'+p.stderr
    assert 'FINANCIAL SAFETY SCENARIO PASS' in p.stdout


def test_financial_idempotency_and_revisions_sqlite(tmp_path):
    scenario('sqlite:///'+str(tmp_path/'financial_safety.sqlite'))


def test_financial_concurrency_postgresql():
    url=os.getenv('DATABASE_URL_POSTGRES_TEST')
    if not url:
        pytest.skip('Requires a disposable PostgreSQL DB set by GitHub Actions CI')
    scenario(url)
