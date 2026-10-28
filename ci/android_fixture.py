"""Disposable LOCAL PostgreSQL18 fixture for native emulator tests. No real data.

Uses the same guarded synthetic schema helper as backend acceptance; binds only
127.0.0.1. No fixture routes, test-clock headers or credentials enter the real API.
"""
from datetime import timedelta
from pathlib import Path
import signal
import sys
from wsgiref.simple_server import make_server,WSGIRequestHandler
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'backend/tests')]
from auth_fixtures import Fixture,PASSWORD
from kinder.api import App
import test_postgres as accounting

class Server(ThreadingMixIn,WSGIServer):daemon_threads=True
class Quiet(WSGIRequestHandler):
    def log_message(self,*args):pass

fixture=Fixture();fixture.setUpClass();fixture.setUp()
try:
    salt,verifier=fixture.conn.execute('SELECT salt,verifier FROM credentials LIMIT 1').fetchone()
    for number in range(1,13):
        client=fixture.conn.execute("INSERT INTO accounts(role) VALUES('client') RETURNING id").fetchone()[0]
        fixture.conn.execute('INSERT INTO credentials(account_id,login,salt,verifier) VALUES(%s,%s,%s,%s)',(client,'android_fixture_'+str(number).zfill(2),salt,verifier))
        subscription=fixture.store.issue_subscription(fixture.admin,client,{'pool':4,'massage':10},'android_sub_'+str(number))['subscription_id']
        start=accounting.START+timedelta(days=1 if number==4 else 0)
        fixture.store.book(client,subscription,'pool',start,45,'android_book_'+str(number))
    fixture.now=accounting.START+timedelta(minutes=44,seconds=50)
    server=make_server('127.0.0.1',18763,App(fixture.factory,require_https=False,clock=lambda:fixture.now),server_class=Server,handler_class=Quiet)
    signal.signal(signal.SIGTERM,lambda *_:(_ for _ in ()).throw(KeyboardInterrupt()))
    print('android_fixture_ready=local_synthetic_postgres18',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
finally:fixture.tearDown()
