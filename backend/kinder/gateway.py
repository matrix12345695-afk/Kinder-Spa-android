"""Fixed Gunicorn gateway; no access logs, config-file execution or env overrides."""
from gunicorn.app.base import BaseApplication
from gunicorn.glogging import Logger


class SafeLogger(Logger):
    def critical(self, *args, **kwargs): self.error_log.critical('kinder_gateway_critical')
    def error(self, *args, **kwargs): self.error_log.error('kinder_gateway_error')
    def warning(self, *args, **kwargs): self.error_log.warning('kinder_gateway_warning')
    def info(self, *args, **kwargs): self.error_log.info('kinder_gateway_event')
    def debug(self, *args, **kwargs): pass
    def exception(self, *args, **kwargs): self.error_log.error('kinder_gateway_exception')
    def access(self, *args, **kwargs): pass
    def log(self, *args, **kwargs): self.error_log.error('kinder_gateway_event')


class Server(BaseApplication):
    def __init__(self, app, port):
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError('valid_port_required')
        self.application, self.port = app, port
        super().__init__()

    def load_config(self):
        # BaseApplication does not load gunicorn.conf.py or GUNICORN_CMD_ARGS.
        # Explicit values also override WEB_CONCURRENCY's default-setting hook.
        settings = {
            'bind': '0.0.0.0:' + str(self.port), 'workers': 1,
            'worker_class': 'sync', 'threads': 1, 'timeout': 30,
            'graceful_timeout': 30, 'keepalive': 2, 'backlog': 32,
            'limit_request_line': 2048, 'limit_request_fields': 32,
            'limit_request_field_size': 4096,
            'max_requests': 1000, 'max_requests_jitter': 100,
            'forwarded_allow_ips': '', 'secure_scheme_headers': {},
            'proxy_protocol': False, 'accesslog': None,
            'errorlog': '-', 'loglevel': 'info', 'logger_class': SafeLogger,
            'capture_output': False, 'preload_app': False,
        }
        for key, value in settings.items():
            self.cfg.set(key, value)

    def load(self):
        return self.application
