"""Render-only API entrypoint with an inert HTTP standby gate.

A new review web service can be deployed with zero database credentials and
KINDER_API_LIVE=disabled. The only successful endpoint is process liveness;
there is NO authentication, customer route, Telegram, DB or external call.

Only the reviewed explicit 'approved' flag invokes the existing live API
module, which independently checks dedicated Render identity, least privilege
PostgreSQL metadata and full schema readiness before accepting requests.
"""
import json
import os
import re

from .gateway import Server

_LIVENESS = b'{"service":"kinder-spa-api","process":"alive","mode":"standby","accepting_customer_data":false}'
_NOT_READY = b'{"ready":false,"mode":"standby"}'
_UNAVAILABLE = b'{"error":"service_not_released"}'


def standby_app(environ, start_response):
    method = environ.get('REQUEST_METHOD')
    path = environ.get('PATH_INFO')
    if method == 'GET' and path == '/health':
        code, raw = '200 OK', _LIVENESS
    elif method == 'GET' and path == '/ready':
        code, raw = '503 Service Unavailable', _NOT_READY
    else:
        code, raw = '503 Service Unavailable', _UNAVAILABLE
    start_response(code, [
        ('Content-Type', 'application/json; charset=utf-8'),
        ('Content-Length', str(len(raw))),
        ('Cache-Control', 'no-store'),
        ('Pragma', 'no-cache'),
        ('X-Content-Type-Options', 'nosniff'),
        ('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'"),
        ('Referrer-Policy', 'no-referrer'),
        ('X-Frame-Options', 'DENY'),
    ])
    return [raw]


def main(environ=None):
    e = os.environ if environ is None else environ
    if (e.get('RENDER') != 'true'
            or e.get('RENDER_SERVICE_TYPE') != 'web'
            or e.get('RENDER_SERVICE_NAME') != 'kinder-spa-api'
            or not re.fullmatch(r'srv-[a-z0-9]{10,40}', e.get('RENDER_SERVICE_ID', ''))):
        print('kinder_api_entry=refused; dedicated_render_web_required', flush=True)
        return 2
    mode = e.get('KINDER_API_LIVE', 'disabled')
    if mode == 'approved':
        # No compatibility shortcuts: the existing live entrypoint still
        # requires approved credentials, canonical Render origin, PostgreSQL18
        # schema, exact table/role permissions and safety-object integrity.
        from .render_api import main as live_main
        return live_main(['--run'])
    if mode != 'disabled':
        print('kinder_api_entry=refused; invalid_release_gate', flush=True)
        return 2
    port = e.get('PORT', '10000')
    if (not re.fullmatch(r'[1-9][0-9]{3,4}', port)
            or not 1024 <= int(port) <= 65535
            or int(port) in (18012, 18013, 19099)):
        print('kinder_api_entry=refused; invalid_port', flush=True)
        return 2
    print('kinder_api_mode=standby; production_db=disconnected; telegram=off', flush=True)
    Server(standby_app, int(port)).run()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
