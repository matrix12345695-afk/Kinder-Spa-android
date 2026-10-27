from datetime import datetime, timedelta, timezone
import unittest
from kinder import policy as p


def at(value):
    return datetime.fromisoformat(value)


class PolicyTests(unittest.TestCase):
    def test_exact_pool_packages(self):
        for n in (4, 8, 12):
            self.assertEqual(p.packages({'pool': n}), {'pool': n})

    def test_combined_has_independent_allowances(self):
        self.assertEqual(p.packages({'pool': 8, 'massage': 10, 'hydromassage': 10}),
                         {'pool': 8, 'massage': 10, 'hydromassage': 10})

    def test_invalid_packages(self):
        for value in ({}, [], {'pool': True}, {'pool': 10}, {'massage': 4}, {'other': 10}, {'pool': 4.0}):
            with self.subTest(value=value), self.assertRaises(p.Rejected):
                p.packages(value)

    def test_pool45_includes_changing_time(self):
        a, b = p.appointment('pool', at('2026-11-02T09:00:00+05:00'), 45)
        self.assertEqual((b-a).total_seconds(), 2700)
        for n in (40, 50, True):
            with self.assertRaises(p.Rejected):
                p.appointment('pool', a, n)

    def test_last_pool_start18_15_is_valid(self):
        self.assertEqual(p.appointment('pool', at('2026-11-02T18:15:00+05:00'), 45)[1].hour, 19)

    def test_outside_hours_or_sunday_denied(self):
        for stamp in ('2026-11-01T09:00:00+05:00', '2026-11-02T08:59:59+05:00',
                      '2026-11-02T18:15:01+05:00', '2026-11-02T23:30:00+05:00'):
            with self.subTest(stamp=stamp), self.assertRaises(p.Rejected):
                p.appointment('pool', at(stamp), 45)

    def test_saturday_and_other_service_explicit_duration(self):
        p.appointment('massage', at('2026-11-07T18:30:00+05:00'), 30)
        p.appointment('hydromassage', at('2026-11-07T09:00:00+05:00'), 60)

    def test_naive_times_denied(self):
        with self.assertRaises(p.Rejected):
            p.appointment('pool', datetime(2026, 11, 2, 9), 45)

    def test_cutoff_strictly_before19_previous_calendar_day(self):
        start = at('2026-11-02T09:00:00+05:00')
        self.assertTrue(p.pool_refund(start, at('2026-11-01T18:59:59.999999+05:00')))
        self.assertFalse(p.pool_refund(start, at('2026-11-01T19:00:00+05:00')))
        self.assertFalse(p.pool_refund(start, at('2026-11-02T08:59:59+05:00')))

    def test_cutoff_uses_tashkent_even_on_sunday_and_utc_input(self):
        start = at('2026-11-02T04:00:00+00:00')
        self.assertTrue(p.pool_refund(start, at('2026-11-01T13:59:59+00:00')))
        self.assertFalse(p.pool_refund(start, at('2026-11-01T14:00:00+00:00')))

    def test_cancel_at_or_after_start_denied(self):
        start = at('2026-11-02T09:00:00+05:00')
        for now in (start, start+timedelta(seconds=1)):
            with self.assertRaises(p.Rejected):
                p.pool_refund(start, now)

    def test_reason_is_required_and_bounded(self):
        self.assertEqual(p.reason('  critical situation  '), 'critical situation')
        for value in ('', '  ', 'ab', 'x'*501, None, '\x00reason'):
            with self.assertRaises(p.Rejected):
                p.reason(value)


if __name__ == '__main__':
    unittest.main()
