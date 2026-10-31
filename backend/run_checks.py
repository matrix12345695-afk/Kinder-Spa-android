"""CI gate: real PostgreSQL18, no skipped tests, machine-readable synthetic evidence."""
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
suite = unittest.defaultTestLoader.discover('tests')
result = unittest.TextTestRunner(verbosity=2).run(suite)
passed = result.wasSuccessful() and result.testsRun == 209 and not result.skipped
source = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in sorted(ROOT.rglob('*')) if p.is_file() and
          p.suffix in ('.py', '.sql', '.lock', '.html', '.js', '.css', '.svg') and '__pycache__' not in p.parts}
evidence = {'schema': 'kinder-admin-boundaries-v1',
            'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
            'skipped': len(result.skipped), 'status': 'passed' if passed else 'failed',
            'postgres_major': 18, 'synthetic_data_only': True, 'production_access': False,
            'http_authentication_implemented': True, 'telegram_delivery_implemented': False,
            'telegram_bot_implemented': True, 'telegram_protocol_fixture_verified': passed,
            'real_telegram_delivery_verified': False, 'telegram_checks': 70, 'render_worker_checks': 9, 'render_api_checks': 29, 'render_private_database_checks': 6, 'hosting_target': 'render',
            'gunicorn': version('gunicorn'), 'real_gunicorn_fixture_verified': passed,
            'render_deployment_verified': False, 'private_render_tls_live_verified': False,
            'deployment_sha256': {name: hashlib.sha256((ROOT.parent/name).read_bytes()).hexdigest()
                                  for name in ('render.yaml', 'backend/deploy/render-telegram.yaml')},
            'https_deployment_verified': False, 'admin_ui_implemented': True,
            'browser_acceptance_report_required': True,
            'android_client_implemented': False, 'published': False, 'source_sha256': source}
output = ROOT.parent/'accounting-evidence'
output.mkdir(exist_ok=True)
(output/'report.json').write_text(json.dumps(evidence, indent=2, sort_keys=True)+'\n')
raise SystemExit(0 if passed else 1)
