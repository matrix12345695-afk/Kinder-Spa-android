"""Fail-closed real browser acceptance, synthetic data and screenshots only."""
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'browser')]
import suite
result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(suite.BrowserTests))
expected=['clients-desktop-ru.png','login-desktop-ru.png','login-mobile-uz.png','overview-desktop-ru.png','overview-mobile-uz.png','subscriptions-mobile-uz.png']
passed=result.wasSuccessful() and result.testsRun==26 and not result.skipped and sorted(suite.SHOTS)==expected
out=ROOT.parent/'admin-evidence';out.mkdir(exist_ok=True)
pins={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.sql','.lock','.html','.js','.css','.svg')}
report={'schema':'kinder-admin-ui-v1','revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'status':'passed' if passed else 'failed',
        'browser_version':suite.BROWSER_VERSION,'playwright':version('playwright'),'screenshots':expected,'source_sha256':pins,
        'real_wsgi_and_postgres':True,'synthetic_data_only':True,'fault_responses_injected':True,
        'production_access':False,'https_deployment_verified':False,'android_client_implemented':False,'telegram_delivery_implemented':False,'published':False}
(out/'browser-report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
raise SystemExit(0 if passed else 1)
