"""Approved service accounting rules; all business dates use Asia/Tashkent."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Asia/Tashkent')
PACKAGES = {'massage': {10}, 'hydromassage': {10}, 'pool': {4, 8, 12}}


class Rejected(ValueError):
    """Stable error code, without account data or credentials."""


def moment(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise Rejected('timezone_required')
    return value.astimezone(ZONE)


def packages(value):
    if not isinstance(value, dict) or not value or set(value) - PACKAGES.keys():
        raise Rejected('invalid_package')
    if any(type(n) is not int or n not in PACKAGES[k] for k, n in value.items()):
        raise Rejected('invalid_package')
    return dict(value)


def appointment(category, start, minutes):
    start = moment(start)
    if not isinstance(category, str) or category not in PACKAGES or type(minutes) is not int or not 5 <= minutes <= 120:
        raise Rejected('invalid_appointment')
    if category == 'pool' and minutes != 45:
        raise Rejected('pool_requires_45_minutes')
    end = start + timedelta(minutes=minutes)
    if (start.weekday() == 6 or start.date() != end.date() or
            start.time() < time(9) or end.time() > time(19)):
        raise Rejected('outside_opening_hours')
    return start, end


def pool_refund(start, cancelled_at):
    start, now = moment(start), moment(cancelled_at)
    if now >= start:
        raise Rejected('appointment_started')
    cutoff = datetime.combine(start.date() - timedelta(days=1), time(19), ZONE)
    return now < cutoff


def reason(value):
    if not isinstance(value, str) or not 3 <= len(value.strip()) <= 500 or '\x00' in value:
        raise Rejected('reason_required')
    return value.strip()
