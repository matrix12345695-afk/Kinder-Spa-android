"""Passwords, tokens and login throttling."""
import hashlib
import hmac
import re
import secrets

SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)
LOGIN_RE = re.compile(r'^[a-z0-9][a-z0-9_.-]{2,63}$')
SESSION_HOURS = {'superadmin': 12, 'admin': 12, 'client': 24 * 30}
QR_SECONDS = 120
THROTTLE_WINDOW_MIN = 15
THROTTLE_MAX = 10


class AuthError(Exception):
    pass


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    return salt, hashlib.scrypt(password.encode('utf-8'), salt=salt, **SCRYPT)


def verify_password(password, salt, verifier):
    _, candidate = hash_password(password, bytes(salt))
    return hmac.compare_digest(candidate, bytes(verifier))


def check_new_password(password):
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise ValueError('password_length')


def normalize_login(value):
    value = (value or '').strip().lower()
    if not LOGIN_RE.fullmatch(value):
        raise ValueError('invalid_login')
    return value


def generate_password():
    alphabet = 'abcdefghjkmnpqrstuvwxyz23456789'
    return '-'.join(''.join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


def new_token():
    return secrets.token_urlsafe(32)


def token_hash(token):
    return hashlib.sha256(token.encode('ascii', 'ignore')).hexdigest()


# Constant-time-ish dummy verifier so unknown logins cost the same as wrong passwords.
_DUMMY = hash_password('dummy-password-for-timing')
