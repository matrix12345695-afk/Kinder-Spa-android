from datetime import datetime, timedelta, timezone

from conftest import Client
from test_api import mk_client, plan_id, service_id

TZ = timezone(timedelta(hours=5))


def setup_family(owner, server, name, plan='Бассейн — 4 занятия', children=('Али',), starts='2026-12-01'):
    cl = mk_client(owner, name, children=children)
    _, r = owner.post('/api/subscriptions', {'client_id': cl['id'], 'plan_id': plan_id(owner, plan), 'starts_on': starts}, expect=200)
    _, cred = owner.post(f"/api/clients/{cl['id']}/credentials", expect=200)
    return cl, r['id'], Client(server).login(cred['login'], cred['password'])


def test_slots_booking_cancellation_rules(owner, server, clock):
    clock(datetime(2026, 12, 1, 9, 0, tzinfo=TZ))   # Tuesday
    pool = service_id(owner, 'pool')
    _, gen = owner.post('/api/slots/generate', {'service_id': pool, 'from': '2026-12-01', 'to': '2026-12-07',
                                                'weekdays': [0, 1, 2, 3, 4, 5], 'times': ['10:00', '17:30'], 'capacity': 2}, expect=200)
    assert gen['created'] == 12        # 6 days x 2 (Sunday excluded); 01.12 10:00 is in the future (now 09:00)
    _, again = owner.post('/api/slots/generate', {'service_id': pool, 'from': '2026-12-01', 'to': '2026-12-07',
                                                  'weekdays': [0, 1, 2, 3, 4, 5], 'times': ['10:00', '17:30'], 'capacity': 2}, expect=200)
    assert again == {'created': 0, 'skipped': 12}
    _, slots = owner.get('/api/slots?from=2026-12-03&to=2026-12-03', expect=200)
    thu10 = next(s for s in slots if '10:00' in s['starts_at'] or s['starts_at'].endswith('05:00:00+00:00'))

    cl, sid, parent = setup_family(owner, server, 'Запись Семья')
    _, free = parent.get(f'/api/my/slots?service_id={pool}', expect=200)
    assert any(s['id'] == thu10['id'] for s in free) and all('capacity' not in s for s in free)
    _, b = parent.post('/api/my/bookings', {'slot_id': thu10['id']}, expect=200)
    assert parent.post('/api/my/bookings', {'slot_id': thu10['id']})[1]['error'] == 'already_booked'
    _, mine = parent.get('/api/my/bookings', expect=200)
    assert mine[0]['id'] == b['id'] and mine[0]['child_name'] == 'Али'

    # capacity 2: two more families -> third one sees slot_full
    _, _, p2 = setup_family(owner, server, 'Вторая Семья')
    p2.post('/api/my/bookings', {'slot_id': thu10['id']}, expect=200)
    _, _, p3 = setup_family(owner, server, 'Третья Семья')
    assert p3.post('/api/my/bookings', {'slot_id': thu10['id']})[1]['error'] == 'slot_full'
    assert all(s['id'] != thu10['id'] for s in p3.get(f'/api/my/slots?service_id={pool}')[1])

    # reservations: 4 visits -> at most 4 future bookings
    other = [s for s in owner.get('/api/slots?from=2026-12-02&to=2026-12-07')[1] if s['id'] != thu10['id']]
    for s in other[:3]:
        parent.post('/api/my/bookings', {'slot_id': s['id']}, expect=200)
    assert parent.post('/api/my/bookings', {'slot_id': other[3]['id']})[1]['error'] == 'all_visits_reserved'

    # free cancellation before 19:00 the day before
    parent.post(f"/api/my/bookings/{b['id']}/cancel", {}, expect=200)
    rebook = parent.post('/api/my/bookings', {'slot_id': thu10['id']}, expect=200)[1]
    # late (after 19:00 on Wednesday): needs confirmation and burns a visit
    clock(datetime(2026, 12, 2, 19, 30, tzinfo=TZ))
    r = parent.post(f"/api/my/bookings/{rebook['id']}/cancel", {})
    assert r[1]['error'] == 'late_cancel_confirm'
    _, res = parent.post(f"/api/my/bookings/{rebook['id']}/cancel", {'confirm_late': True}, expect=200)
    assert res['forfeited'] is True
    _, sub = owner.get(f'/api/subscriptions/{sid}')
    assert sub['items'][0]['remaining'] == 3 and sub['visits'][0]['method'] == 'late_cancel'


def test_attendance_no_show_and_slot_cancel(owner, server, clock, fake_telegram):
    clock(datetime(2026, 12, 14, 8, 0, tzinfo=TZ))  # Monday
    pool, massage = service_id(owner, 'pool'), service_id(owner, 'massage')
    owner.post('/api/slots', {'service_id': pool, 'date': '2026-12-14', 'time': '10:00', 'capacity': 5}, expect=200)
    owner.post('/api/slots', {'service_id': pool, 'date': '2026-12-14', 'time': '12:00', 'capacity': 5}, expect=200)
    _, m = owner.post('/api/slots', {'service_id': massage, 'date': '2026-12-15', 'time': '11:00'}, expect=200)
    assert owner.post('/api/slots', {'service_id': pool, 'date': '2026-12-14', 'time': '10:00'})[1]['error'] == 'slot_exists'
    slots = owner.get('/api/slots?from=2026-12-14&to=2026-12-14')[1]
    s10, s12 = slots[0], slots[1]

    cl, sid, parent = setup_family(owner, server, 'Посещаемость', starts='2026-12-14', children=('Мила', 'Тим'))
    mila, tim = (c['id'] for c in cl['children'])
    assert owner.post('/api/bookings', {'slot_id': s10['id'], 'client_id': cl['id']})[1]['error'] == 'choose_child'
    _, b1 = owner.post('/api/bookings', {'slot_id': s10['id'], 'client_id': cl['id'], 'child_id': mila}, expect=200)
    _, b2 = owner.post('/api/bookings', {'slot_id': s12['id'], 'client_id': cl['id'], 'child_id': tim}, expect=200)
    # QR/manual visit of Mila today marks her booking attended
    clock(datetime(2026, 12, 14, 9, 55, tzinfo=TZ))
    owner.post('/api/visits', {'subscription_id': sid, 'service_id': pool, 'child_id': mila}, expect=200)
    bookings = owner.get(f"/api/clients/{cl['id']}/bookings")[1]
    assert {b['id']: b['status'] for b in bookings}[b1['id']] == 'attended'
    # Tim did not come: no-show after start burns a pool visit
    assert owner.post(f"/api/bookings/{b2['id']}/no-show")[1]['error'] == 'session_not_started'
    clock(datetime(2026, 12, 14, 12, 30, tzinfo=TZ))
    _, ns = owner.post(f"/api/bookings/{b2['id']}/no-show", expect=200)
    assert ns['forfeited'] is True
    _, sub = owner.get(f'/api/subscriptions/{sid}')
    assert sub['items'][0]['remaining'] == 2

    # massage subscription: attend from schedule, then centre cancels another slot -> parent notified
    _, ms = owner.post('/api/subscriptions', {'client_id': cl['id'], 'plan_id': plan_id(owner, 'Массаж — 10 сеансов')}, expect=200)
    _, bm = owner.post('/api/bookings', {'slot_id': m['id'], 'client_id': cl['id'], 'child_id': mila}, expect=200)
    assert owner.post(f"/api/bookings/{bm['id']}/attend")[1]['error'] == 'booking_not_today'
    clock(datetime(2026, 12, 15, 11, 0, tzinfo=TZ))
    _, at = owner.post(f"/api/bookings/{bm['id']}/attend", expect=200)
    assert at['remaining'] == 9
    _, s2 = owner.post('/api/slots', {'service_id': massage, 'date': '2026-12-16', 'time': '11:00'}, expect=200)
    owner.post('/api/bookings', {'slot_id': s2['id'], 'client_id': cl['id'], 'child_id': tim}, expect=200)
    _, c = owner.post(f"/api/slots/{s2['id']}/cancel", {'reason': 'специалист заболел'}, expect=200)
    assert c['bookings_cancelled'] == 1
    assert owner.patch(f"/api/slots/{s10['id']}", {'capacity': 1})[0] == 200
