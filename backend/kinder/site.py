"""Public website of the centre (server-rendered, RU/UZ). Data comes from the catalogue and centre settings."""
from html import escape as e

from starlette.concurrency import run_in_threadpool
from starlette.responses import HTMLResponse

from . import i18n

TEXT = {
    'ru': {
        'title': 'Kinder Spa — детский массаж, гидромассаж и бассейн',
        'h1': 'Массаж, гидромассаж и бассейн для детей',
        'book': 'Записаться в Telegram', 'call': 'Позвонить', 'other_lang': "O'zbekcha", 'other_code': 'uz',
        'services': 'Услуги', 'minutes': 'мин', 'from': 'от', 'specialists_of': 'Ведут', 'prices': 'Абонементы и цены',
        'visits': 'посещений', 'days': 'дней', 'price_ask': 'Стоимость уточняйте у администратора.',
        'how': 'Как это работает',
        'steps': ['Оформите абонемент на ресепшене и получите логин и пароль.',
                  'Откройте наш Telegram-бот и войдите — там остаток посещений и история.',
                  'Запишитесь на удобный день и время прямо в боте.',
                  'Покажите QR-код из бота на ресепшене — посещение отметится само.'],
        'team': 'Специалисты', 'contacts': 'Ждём вас', 'address': 'Адрес', 'hours': 'Часы работы', 'phone': 'Телефон',
        'map': 'Открыть на карте', 'staff': 'Вход для сотрудников', 'rules': 'Отмена записи в бассейн — бесплатно до 19:00 накануне.',
        'meta': 'Детский оздоровительный центр: массаж, гидромассаж и бассейн. Запись и абонементы в Telegram-боте.',
    },
    'uz': {
        'title': 'Kinder Spa — bolalar massaji, gidromassaj va basseyn',
        'h1': 'Bolalar uchun massaj, gidromassaj va basseyn',
        'book': 'Telegram orqali yozilish', 'call': "Qo'ng'iroq qilish", 'other_lang': 'Русский', 'other_code': 'ru',
        'services': 'Xizmatlar', 'minutes': 'daqiqa', 'from': '', 'specialists_of': 'Mutaxassislar', 'prices': 'Abonementlar va narxlar',
        'visits': 'ta tashrif', 'days': 'kun', 'price_ask': "Narxni administratordan so'rang.",
        'how': 'Qanday ishlaydi',
        'steps': ['Qabulxonada abonement rasmiylashtiring va login hamda parol oling.',
                  'Telegram botimizni oching va kiring — u yerda qolgan tashriflar va tarix bor.',
                  'Botning o‘zida qulay kun va vaqtga yoziling.',
                  "Qabulxonada botdagi QR-kodni ko'rsating — tashrif avtomatik belgilanadi."],
        'team': 'Mutaxassislar', 'contacts': 'Sizni kutamiz', 'address': 'Manzil', 'hours': 'Ish vaqti', 'phone': 'Telefon',
        'map': "Xaritada ko'rish", 'staff': 'Xodimlar uchun kirish', 'rules': "Basseynga yozuvni oldingi kuni soat 19:00 gacha bepul bekor qilish mumkin.",
        'meta': "Bolalar sog'lomlashtirish markazi: massaj, gidromassaj va basseyn. Yozilish va abonementlar Telegram botda.",
    },
}

RIPPLES = '''<svg class="ripples" viewBox="0 0 600 600" aria-hidden="true" focusable="false">
  <circle class="r r5" cx="300" cy="300" r="290"/><circle class="r r4" cx="300" cy="300" r="236"/>
  <circle class="r r3" cx="300" cy="300" r="182"/><circle class="r r2" cx="300" cy="300" r="128"/>
  <circle class="r r1" cx="300" cy="300" r="76"/>
  <circle class="bubble b1" cx="468" cy="148" r="16"/><circle class="bubble b2" cx="512" cy="214" r="8"/>
  <circle class="bubble b3" cx="118" cy="452" r="12"/><circle class="bubble b4" cx="152" cy="506" r="6"/>
  <path class="drop" d="M300 252c0 0-34 40-34 64a34 34 0 0 0 68 0c0-24-34-64-34-64z"/>
</svg>'''


def money(v, lang):
    return f"{int(v):,}".replace(',', ' ') + ' ' + i18n.CURRENCY[lang]


def render(data, lang, public_url):
    T = TEXT[lang]
    s = data['settings']
    bot = data['bot_username']
    book_url = f'https://t.me/{bot}' if bot else ''
    phone_href = 'tel:' + ''.join(ch for ch in s['phone'] if ch.isdigit() or ch == '+') if s['phone'] else ''
    about = s['about_uz'] if lang == 'uz' and s['about_uz'] else s['about_ru']

    def nm(row, field='name'):
        return (row.get(field + '_uz') if lang == 'uz' else None) or row.get(field + '_ru') or row.get(field, '')

    cta = []
    if book_url:
        cta.append(f'<a class="btn btn-primary" href="{e(book_url)}" rel="noopener">{T["book"]}</a>')
    if phone_href:
        cta.append(f'<a class="btn btn-ghost" href="{e(phone_href)}">{T["call"]}</a>')

    # cheapest plan per service (only single-service plans count as "from")
    from_price = {}
    for p in data['plans']:
        if len(p['items']) == 1 and p['price'] > 0:
            sid = p['items'][0]['service_id']
            from_price[sid] = min(from_price.get(sid, p['price']), p['price'])

    services_html = []
    for sv in data['services']:
        photo = (f'<img src="/api/photos/{sv["photos"][0]}" alt="" loading="lazy">' if sv['photos']
                 else '<div class="svc-art" aria-hidden="true"><span></span><span></span><span></span></div>')
        specs = ', '.join(e(p['full_name']) for p in sv['specialists'])
        price = (f'<p class="svc-price">{T["from"]} {money(from_price[sv["id"]], lang)}</p>'.replace('> ', '>')
                 if sv['id'] in from_price else '')
        services_html.append(f'''<article class="svc">
  <div class="svc-media">{photo}</div>
  <div class="svc-body">
    <h3>{e(nm(sv))}</h3>
    <p class="svc-meta">{sv["duration_min"]} {T["minutes"]}</p>
    <p>{e(nm(sv, "description"))}</p>
    {f'<p class="svc-team">{T["specialists_of"]}: {specs}</p>' if specs else ''}
    {price}
  </div>
</article>''')

    order = {sv['id']: (sv['sort'], sv['id']) for sv in data['services']}
    plans = sorted((p for p in data['plans'] if p['price'] > 0),
                   key=lambda p: (len(p['items']) > 1, order.get(p['items'][0]['service_id'], (99, 0)) if p['items'] else (99, 0), p['price']))
    if plans:
        rows = ''.join(f'''<li class="plan">
  <div><h3>{e(p["name"])}</h3><p>{"; ".join(f'{e(service_name(data, i["service_id"], lang))}, {i["visits"]} {T["visits"]}' for i in p["items"])}</p></div>
  <div class="plan-side"><strong>{money(p["price"], lang)}</strong><span>{p["validity_days"]} {T["days"]}</span></div>
</li>''' for p in plans)
        prices_html = f'<ul class="plans">{rows}</ul>'
    else:
        prices_html = f'<p class="muted">{T["price_ask"]}</p>'

    team = [p for p in data['specialists'] if p.get('active', True)]
    team_html = ''
    if team:
        team_html = f'''<section class="team wrap" aria-labelledby="team-h">
  <h2 id="team-h">{T["team"]}</h2>
  <ul class="people">{"".join(f'<li><div class="avatar" aria-hidden="true">{e(p["full_name"][:1])}</div><div><h3>{e(p["full_name"])}</h3><p class="muted">{", ".join(e(service_name(data, sid, lang)) for sid in p["service_ids"])}</p>{f"<p>{e(p['bio'])}</p>" if p.get("bio") else ""}</div></li>' for p in team)}</ul>
</section>'''

    contacts = []
    if s['address']:
        contacts.append(f'<div><dt>{T["address"]}</dt><dd>{e(s["address"])}'
                        + (f'<a class="map" href="{e(s["map_url"])}" rel="noopener">{T["map"]}</a>' if s['map_url'] else '') + '</dd></div>')
    if s['hours']:
        contacts.append(f'<div><dt>{T["hours"]}</dt><dd>{e(s["hours"])}</dd></div>')
    if s['phone']:
        contacts.append(f'<div><dt>{T["phone"]}</dt><dd><a href="{e(phone_href)}">{e(s["phone"])}</a></dd></div>')
    if s['instagram']:
        handle = s['instagram'].rstrip('/').rsplit('/', 1)[-1]
        contacts.append(f'<div><dt>Instagram</dt><dd><a href="{e(s["instagram"])}" rel="noopener">@{e(handle)}</a></dd></div>')

    steps = ''.join(f'<li><span class="step-n">{n}</span><p>{e(txt)}</p></li>' for n, txt in enumerate(T['steps'], 1))
    og = f'{public_url}/assets/img/welcome-{lang}.png' if public_url else ''
    return f'''<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{T["title"]}</title>
<meta name="description" content="{e(T["meta"])}">
<meta property="og:title" content="{e(T["title"])}">
<meta property="og:description" content="{e(T["meta"])}">
{f'<meta property="og:image" content="{e(og)}">' if og else ''}
<meta name="theme-color" content="#FF8A80">
<link rel="icon" href="/admin/static/icon.svg" type="image/svg+xml">
<link rel="preload" href="/assets/fonts/Nunito.ttf" as="font" type="font/ttf" crossorigin>
<link rel="stylesheet" href="/assets/site.css">
</head>
<body>
<header class="top wrap">
  <a class="logo" href="/?lang={lang}"><img src="/admin/static/icon.svg" alt="" width="36" height="36">Kinder Spa</a>
  <nav class="top-nav">
    <a href="#services">{T["services"]}</a><a href="#prices">{T["prices"].split()[0]}</a><a href="#contacts">{T["contacts"]}</a>
    <a class="lang" href="/?lang={T["other_code"]}" hreflang="{T["other_code"]}">{T["other_lang"]}</a>
  </nav>
</header>
<main>
<section class="hero wrap">
  <div class="hero-text">
    <h1>{T["h1"]}</h1>
    <p class="lead">{e(about)}</p>
    <div class="cta">{"".join(cta)}</div>
    {f'<p class="hours">{e(s["hours"])}</p>' if s["hours"] else ''}
  </div>
  <div class="hero-art">{RIPPLES}</div>
</section>
<section id="services" class="wrap" aria-labelledby="svc-h">
  <h2 id="svc-h">{T["services"]}</h2>
  <div class="svcs">{"".join(services_html)}</div>
</section>
<section id="prices" class="prices wrap" aria-labelledby="price-h">
  <h2 id="price-h">{T["prices"]}</h2>
  {prices_html}
  <p class="note">{T["rules"]}</p>
</section>
<section class="how wrap" aria-labelledby="how-h">
  <h2 id="how-h">{T["how"]}</h2>
  <ol class="steps">{steps}</ol>
</section>
{team_html}
<section id="contacts" class="contacts" aria-labelledby="c-h">
  <div class="wrap contacts-inner">
    <div>
      <h2 id="c-h">{T["contacts"]}</h2>
      <dl>{"".join(contacts)}</dl>
    </div>
    <div class="cta">{"".join(cta)}</div>
  </div>
</section>
</main>
<footer class="foot wrap">
  <span>© Kinder Spa</span>
  <a href="/admin/">{T["staff"]}</a>
</footer>
</body>
</html>'''


def service_name(data, sid, lang):
    for sv in data['services']:
        if sv['id'] == sid:
            return (sv.get('name_uz') if lang == 'uz' else None) or sv['name_ru']
    return ''


def load(db, bot_username):
    from . import app as A
    from .telegram import DbCtx
    with db.conn() as c:
        x = DbCtx(c)
        return {'services': [s for s in A.services_list(x) if s['active']], 'specialists': A.specialists_list(x),
                'plans': A.plans_query(x, True), 'settings': A.load_settings(x), 'bot_username': bot_username}


async def home(request):
    lang = request.query_params.get('lang')
    if lang not in i18n.LANGS:
        accept = request.headers.get('accept-language', '')
        lang = 'uz' if accept.lower().startswith('uz') else 'ru'
    st = request.app.state
    data = await run_in_threadpool(load, st.db, getattr(st, 'bot_username', '') or '')
    return HTMLResponse(render(data, lang, st.public_url), headers={'Cache-Control': 'no-cache'})
