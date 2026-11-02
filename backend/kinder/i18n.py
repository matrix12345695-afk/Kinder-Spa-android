"""Parent-facing texts of the Telegram bot in Russian and Uzbek (Latin script).

t(lang, key, **params): params may be plain values or {'ru': ..., 'uz': ...} dicts,
which are resolved for the target language (used for service names, dates, buttons).
"""
LANGS = ('ru', 'uz')

T = {
    # ------------------------------------------------------------ buttons
    'btn_qr': {'ru': '📱 QR-код', 'uz': '📱 QR-kod'},
    'btn_book': {'ru': '📅 Записаться', 'uz': '📅 Yozilish'},
    'btn_my_bookings': {'ru': '🗓 Мои записи', 'uz': '🗓 Yozuvlarim'},
    'btn_subs': {'ru': '🎫 Мои абонементы', 'uz': '🎫 Abonementlarim'},
    'btn_visits': {'ru': '🕘 Посещения', 'uz': '🕘 Tashriflar'},
    'btn_services': {'ru': '💆 Услуги', 'uz': '💆 Xizmatlar'},
    'btn_help': {'ru': '❓ Помощь', 'uz': '❓ Yordam'},
    'btn_lang': {'ru': '🌐 Язык', 'uz': '🌐 Til'},
    'btn_logout': {'ru': '🚪 Выйти', 'uz': '🚪 Chiqish'},
    'btn_new_code': {'ru': '🔄 Новый код', 'uz': '🔄 Yangi kod'},
    'btn_back': {'ru': '← Назад', 'uz': '← Orqaga'},
    'btn_cancel_booking': {'ru': 'Отменить запись', 'uz': 'Yozuvni bekor qilish'},
    'btn_yes_cancel': {'ru': 'Да, отменить', 'uz': 'Ha, bekor qilish'},
    'btn_no_keep': {'ru': 'Нет, приду', 'uz': "Yo'q, boraman"},

    # ------------------------------------------------------------ login
    'choose_lang': {'ru': 'Выберите язык / Tilni tanlang:', 'uz': 'Выберите язык / Tilni tanlang:'},
    'lang_set': {'ru': 'Язык: русский.', 'uz': "Til: o'zbekcha."},
    'welcome': {'ru': 'Здравствуйте! 👋 Добро пожаловать в <b>Kinder Spa</b> — детский центр массажа, гидромассажа и бассейна ❤️\n\n'
                      'Здесь можно записаться на занятие, показать QR-код на входе и следить за абонементом.\n\n'
                      'Чтобы войти, отправьте <b>логин</b>, который вам выдали на ресепшене.\nОтменить: /cancel',
                'uz': 'Assalomu alaykum! 👋 <b>Kinder Spa</b> — bolalar massaji, gidromassaj va basseyn markaziga xush kelibsiz ❤️\n\n'
                      "Bu yerda mashg'ulotga yozilish, kirishda QR-kodni ko'rsatish va abonementni kuzatish mumkin.\n\n"
                      'Kirish uchun qabulxonada berilgan <b>login</b>ni yuboring.\nBekor qilish: /cancel'},
    'bad_login': {'ru': 'Логин состоит из латинских букв и цифр, например <code>kid12</code>. Попробуйте ещё раз.',
                  'uz': "Login lotin harflari va raqamlardan iborat, masalan <code>kid12</code>. Qaytadan urinib ko'ring."},
    'ask_password': {'ru': 'Теперь отправьте <b>пароль</b>. Сообщение с паролем я сразу удалю.',
                     'uz': "Endi <b>parol</b>ni yuboring. Parolli xabarni darhol o'chirib tashlayman."},
    'too_many': {'ru': 'Слишком много попыток. Подождите 15 минут и отправьте /start',
                 'uz': "Urinishlar juda ko'p. 15 daqiqa kuting va /start yuboring"},
    'wrong_creds': {'ru': 'Неверный логин или пароль. Отправьте логин ещё раз или /cancel',
                    'uz': "Login yoki parol noto'g'ri. Loginni qayta yuboring yoki /cancel"},
    'access_disabled': {'ru': 'Доступ отключён. Обратитесь на ресепшен.', 'uz': "Kirish o'chirilgan. Qabulxonaga murojaat qiling."},
    'logged_in': {'ru': 'Готово, {name}! ✅ Рады видеть вас в Kinder Spa ❤️', 'uz': "Tayyor, {name}! ✅ Sizni Kinder Spa'da ko'rganimizdan xursandmiz ❤️"},
    'hello': {'ru': 'Здравствуйте, {name}! 👋 Рады снова видеть вас ❤️', 'uz': "Assalomu alaykum, {name}! 👋 Sizni yana ko'rganimizdan xursandmiz ❤️"},
    'site': {'ru': '🌐 Наш сайт: {url}', 'uz': '🌐 Saytimiz: {url}'},
    'access_changed': {'ru': 'Доступ изменился (например, сброшен пароль). Войдите заново: /start',
                       'uz': "Kirish ma'lumotlari o'zgardi (masalan, parol yangilandi). Qaytadan kiring: /start"},
    'cancelled': {'ru': 'Отменено.', 'uz': 'Bekor qilindi.'},
    'logged_out': {'ru': 'Вы вышли. Чтобы войти снова, отправьте /start', 'uz': 'Siz chiqdingiz. Qayta kirish uchun /start yuboring'},
    'choose_action': {'ru': 'Выберите действие в меню ниже 👇', 'uz': 'Quyidagi menyudan tanlang 👇'},
    'help': {'ru': '<b>Что умеет бот</b>\n\n'
                   '{qr} — покажите его на ресепшене, код действует 2 минуты.\n'
                   '{book} — выбрать услугу, день и время.\n{mine} — ваши записи и отмена.\n'
                   '{subs} — остаток посещений и срок.\n{visits} — история посещений.\n'
                   '{services} — массаж, гидромассаж, бассейн.\n\n'
                   'После каждого посещения сюда придёт уведомление, а за 3 дня до окончания абонемента — напоминание.',
             'uz': '<b>Bot nimalar qila oladi</b>\n\n'
                   "{qr} — uni qabulxonada ko'rsating, kod 2 daqiqa amal qiladi.\n"
                   '{book} — xizmat, kun va vaqtni tanlash.\n{mine} — yozuvlaringiz va bekor qilish.\n'
                   '{subs} — qolgan tashriflar va muddat.\n{visits} — tashriflar tarixi.\n'
                   '{services} — massaj, gidromassaj, basseyn.\n\n'
                   "Har bir tashrifdan keyin bu yerga xabar keladi, abonement tugashidan 3 kun oldin esa eslatma yuboriladi."},

    # ------------------------------------------------------------ client views
    'qr_caption': {'ru': 'Покажите этот QR-код на ресепшене.\nДействует <b>2 минуты</b> и только один раз.',
                   'uz': "Ushbu QR-kodni qabulxonada ko'rsating.\n<b>2 daqiqa</b> va faqat bir marta amal qiladi."},
    'no_subs': {'ru': 'Активных абонементов нет. Оформить можно на ресепшене.',
                'uz': "Faol abonementlar yo'q. Qabulxonada rasmiylashtirish mumkin."},
    'sub_valid': {'ru': 'Действует до {date} · {state}', 'uz': '{date} gacha amal qiladi · {state}'},
    'sub_frozen_since': {'ru': 'Заморожен с {date}', 'uz': '{date} dan muzlatilgan'},
    'sub_debt': {'ru': '💳 К оплате: {sum}', 'uz': "💳 To'lov qoldig'i: {sum}"},
    'item': {'ru': '{name}: <b>{rem}</b> из {quota}', 'uz': '{name}: <b>{rem}</b> / {quota}'},
    'no_visits': {'ru': 'Посещений пока нет.', 'uz': "Hozircha tashriflar yo'q."},
    'visits_title': {'ru': '🕘 <b>Последние посещения</b>', 'uz': "🕘 <b>So'nggi tashriflar</b>"},
    'visit_cancelled_mark': {'ru': 'отменено', 'uz': 'bekor qilingan'},
    'service_card': {'ru': '<b>{name}</b> · {min} мин\n{desc}', 'uz': '<b>{name}</b> · {min} daqiqa\n{desc}'},
    'specialists': {'ru': 'Специалисты: {names}', 'uz': 'Mutaxassislar: {names}'},
    'services_footer': {'ru': 'Записаться можно кнопкой «{book}». Абонемент оформляется на ресепшене.',
                        'uz': "«{book}» tugmasi orqali yozilishingiz mumkin. Abonement qabulxonada rasmiylashtiriladi."},

    # ------------------------------------------------------------ booking
    'book_title': {'ru': '📅 <b>Запись</b>\nВыберите услугу:', 'uz': '📅 <b>Yozilish</b>\nXizmatni tanlang:'},
    'no_slots': {'ru': 'Свободного времени по вашим абонементам пока нет. Уточните на ресепшене.',
                 'uz': "Abonementingiz bo'yicha bo'sh vaqt hozircha yo'q. Qabulxonadan so'rang."},
    'choose_day': {'ru': 'Выберите день:', 'uz': 'Kunni tanlang:'},
    'day_btn': {'ru': '{wd} {date} · {n} врем.', 'uz': '{wd} {date} · {n} ta vaqt'},
    'times_title': {'ru': 'Время на {date}:', 'uz': '{date} uchun vaqt:'},
    'slot_btn': {'ru': '{time}{spec} · мест: {n}', 'uz': '{time}{spec} · joy: {n}'},
    'who': {'ru': 'Кого записываем?', 'uz': 'Kimni yozamiz?'},
    'booked': {'ru': '✅ Вы записаны: <b>{service}</b>\n{when}{spec}{free}\nНакануне пришлю напоминание. Отменить: {mine}',
               'uz': '✅ Siz yozildingiz: <b>{service}</b>\n{when}{spec}{free}\nBir kun oldin eslatma yuboraman. Bekor qilish: {mine}'},
    'free_cancel_until': {'ru': '\nБесплатная отмена до {time}.', 'uz': '\n{time} gacha bepul bekor qilish mumkin.'},
    'no_bookings': {'ru': 'Активных записей нет. Записаться: {book}', 'uz': "Faol yozuvlar yo'q. Yozilish: {book}"},
    'specialist': {'ru': 'Специалист: {name}', 'uz': 'Mutaxassis: {name}'},
    'late_warn': {'ru': '⚠️ Бесплатная отмена уже недоступна (после 19:00 накануне). Если отменить, посещение будет списано. Отменить всё равно?',
                  'uz': "⚠️ Bepul bekor qilish muddati o'tdi (oldingi kuni soat 19:00 dan keyin). Bekor qilsangiz, tashrif hisobdan yechiladi. Baribir bekor qilinsinmi?"},
    'booking_cancelled': {'ru': 'Запись отменена.', 'uz': 'Yozuv bekor qilindi.'},
    'forfeited': {'ru': ' Посещение списано по правилам центра.', 'uz': " Markaz qoidalariga ko'ra tashrif hisobdan yechildi."},
    'not_forfeited': {'ru': ' Посещение не списано.', 'uz': ' Tashrif hisobdan yechilmadi.'},
    'booking_kept': {'ru': 'Хорошо, запись сохранена. Ждём вас!', 'uz': 'Yaxshi, yozuv saqlandi. Sizni kutamiz!'},
    'login_first': {'ru': 'Войдите в бота: /start', 'uz': 'Botga kiring: /start'},
    'err_generic': {'ru': 'Не получилось. Попробуйте ещё раз или обратитесь на ресепшен.',
                    'uz': "Bo'lmadi. Qaytadan urinib ko'ring yoki qabulxonaga murojaat qiling."},
    'err_slot_full': {'ru': 'На это время мест больше нет. Выберите другое.', 'uz': "Bu vaqtga joy qolmadi. Boshqa vaqtni tanlang."},
    'err_slot_in_past': {'ru': 'Это время уже прошло.', 'uz': "Bu vaqt o'tib ketgan."},
    'err_slot_cancelled': {'ru': 'Занятие отменено.', 'uz': "Mashg'ulot bekor qilingan."},
    'err_slot_not_found': {'ru': 'Занятие не найдено.', 'uz': "Mashg'ulot topilmadi."},
    'err_already_booked': {'ru': 'Вы уже записаны на это время.', 'uz': 'Siz bu vaqtga allaqachon yozilgansiz.'},
    'err_all_visits_reserved': {'ru': 'Все посещения абонемента уже распределены по записям.',
                                'uz': "Abonementdagi barcha tashriflar allaqachon yozuvlarga taqsimlangan."},
    'err_no_subscription_for_booking': {'ru': 'Нет активного абонемента на эту услугу и дату.',
                                        'uz': "Bu xizmat va sana uchun faol abonement yo'q."},
    'err_booking_not_active': {'ru': 'Эта запись уже не активна.', 'uz': 'Bu yozuv endi faol emas.'},
    'err_session_started': {'ru': 'Занятие уже началось, отменить нельзя.', 'uz': "Mashg'ulot boshlangan, bekor qilib bo'lmaydi."},

    # ------------------------------------------------------------ notifications
    'n_visit': {'ru': '✅ Посещение отмечено: <b>{service}</b>{who}\nОсталось: <b>{left}</b> из {quota} · абонемент до {ends}{tail}',
                'uz': '✅ Tashrif belgilandi: <b>{service}</b>{who}\nQoldi: <b>{left}</b> / {quota} · abonement {ends} gacha{tail}'},
    'n_visit_last': {'ru': '\n⚠️ Это было последнее посещение по этой услуге.', 'uz': "\n⚠️ Bu xizmat bo'yicha oxirgi tashrif edi."},
    'n_visit_one': {'ru': '\nОсталось одно посещение.', 'uz': '\nBitta tashrif qoldi.'},
    'n_visit_cancel': {'ru': '↩️ Посещение «{service}» от {at} отменено, оно возвращено на абонемент.',
                       'uz': '↩️ {at} dagi «{service}» tashrifi bekor qilindi va abonementga qaytarildi.'},
    'n_sub_created': {'ru': '🎉 Оформлен абонемент <b>{name}</b>\nДействует с {start} по {end}.{debt}',
                      'uz': '🎉 <b>{name}</b> abonementi rasmiylashtirildi\n{start} dan {end} gacha amal qiladi.{debt}'},
    'n_to_pay': {'ru': '\nК оплате: {sum}', 'uz': "\nTo'lov: {sum}"},
    'n_freeze': {'ru': '❄️ Абонемент <b>{name}</b> заморожен. Срок продлится на дни заморозки.',
                 'uz': '❄️ <b>{name}</b> abonementi muzlatildi. Muddat muzlatilgan kunlar soniga uzaytiriladi.'},
    'n_unfreeze': {'ru': '▶️ Абонемент <b>{name}</b> снова активен, действует до {end}.',
                   'uz': '▶️ <b>{name}</b> abonementi yana faol, {end} gacha amal qiladi.'},
    'n_extend': {'ru': '📅 Абонемент <b>{name}</b> продлён до {end}.', 'uz': '📅 <b>{name}</b> abonementi {end} gacha uzaytirildi.'},
    'n_payment': {'ru': '💳 Оплата получена: <b>{sum}</b> ({method}) — {name}\n{rest}',
                  'uz': "💳 To'lov qabul qilindi: <b>{sum}</b> ({method}) — {name}\n{rest}"},
    'n_payment_rest': {'ru': 'Остаток к оплате: {debt}', 'uz': "To'lov qoldig'i: {debt}"},
    'n_payment_full': {'ru': 'Абонемент оплачен полностью. Спасибо!', 'uz': "Abonement to'liq to'landi. Rahmat!"},
    'n_slot_cancel': {'ru': '❗ Занятие <b>{service}</b> {when} отменено центром.\nПричина: {reason}. Посещение не списано — запишитесь на другое время.',
                      'uz': "❗ {when} <b>{service}</b> mashg'uloti markaz tomonidan bekor qilindi.\nSabab: {reason}. Tashrif hisobdan yechilmadi — boshqa vaqtga yoziling."},
    'n_staff_booked': {'ru': '📅 Вы записаны: <b>{service}</b> {when}{spec}\nОтменить запись можно в боте: «{mine}».',
                       'uz': '📅 Siz yozildingiz: <b>{service}</b> {when}{spec}\nYozuvni botda bekor qilish mumkin: «{mine}».'},
    'n_staff_cancel': {'ru': '❗ Запись <b>{service}</b> {when} отменена центром.{reason}\nПосещение не списано.',
                       'uz': '❗ {when} <b>{service}</b> yozuvi markaz tomonidan bekor qilindi.{reason}\nTashrif hisobdan yechilmadi.'},
    'n_reason': {'ru': '\nПричина: {reason}', 'uz': '\nSabab: {reason}'},
    'n_no_show': {'ru': '😔 Вы не пришли на занятие <b>{service}</b> {when}. По правилам центра посещение списано.',
                  'uz': "😔 Siz {when} <b>{service}</b> mashg'ulotiga kelmadingiz. Markaz qoidalariga ko'ra tashrif hisobdan yechildi."},
    'n_ends_soon': {'ru': '⏳ Абонемент <b>{name}</b> заканчивается {when}.\nОсталось: {items}.\nЧтобы продлить, обратитесь на ресепшен.',
                    'uz': '⏳ <b>{name}</b> abonementi {when} tugaydi.\nQoldi: {items}.\nUzaytirish uchun qabulxonaga murojaat qiling.'},
    'n_expired': {'ru': '⌛ Срок абонемента <b>{name}</b> истёк, неиспользованных посещений: {left}.\nЕсли нужно продлить, обратитесь на ресепшен.',
                  'uz': "⌛ <b>{name}</b> abonementi muddati tugadi, foydalanilmagan tashriflar: {left}.\nUzaytirish kerak bo'lsa, qabulxonaga murojaat qiling."},
    'n_booking_reminder': {'ru': '🔔 Напоминаем: завтра <b>{service}</b>{who} в {time}.\nЕсли не получается, отмените запись: {mine}',
                           'uz': "🔔 Eslatma: ertaga soat {time} da <b>{service}</b>{who}.\nKela olmasangiz, yozuvni bekor qiling: {mine}"},
    'today': {'ru': 'сегодня', 'uz': 'bugun'},
    'tomorrow': {'ru': 'завтра', 'uz': 'ertaga'},
    'in_days': {'ru': 'через {n} дн. ({date})', 'uz': '{n} kundan keyin ({date})'},
}

STATES = {
    'ru': {'active': 'активен', 'frozen': 'заморожен', 'closed': 'закрыт', 'expired': 'истёк', 'used_up': 'использован', 'not_started': 'ещё не начался'},
    'uz': {'active': 'faol', 'frozen': 'muzlatilgan', 'closed': 'yopilgan', 'expired': 'muddati tugagan', 'used_up': 'tugagan', 'not_started': 'hali boshlanmagan'},
}
WEEKDAYS = {'ru': ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'], 'uz': ['Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh', 'Ya']}
METHODS = {'ru': {'cash': 'наличные', 'card': 'карта', 'click': 'Click', 'payme': 'Payme', 'transfer': 'перевод'},
           'uz': {'cash': 'naqd', 'card': 'karta', 'click': 'Click', 'payme': 'Payme', 'transfer': "o'tkazma"}}
CURRENCY = {'ru': 'сум', 'uz': "so'm"}


def norm(lang):
    return lang if lang in LANGS else 'ru'


def resolve(value, lang):
    if isinstance(value, dict) and set(value) <= set(LANGS) and value:
        return value.get(lang) or value.get('ru')
    return value


def t(lang, key, **params):
    lang = norm(lang)
    return T[key][lang].format(**{k: resolve(v, lang) for k, v in params.items()})


def both(key, **params):
    """Per-language dict of a rendered text, usable as a parameter of another template."""
    return {lang: t(lang, key, **params) for lang in LANGS}


def money(amount):
    v = f"{int(amount):,}".replace(',', ' ')
    return {lang: f'{v} {CURRENCY[lang]}' for lang in LANGS}


def when(dt_local):
    """'Пн 05.12 в 10:00' / 'Du 05.12 soat 10:00' for a local datetime."""
    wd, dm, hm = dt_local.weekday(), dt_local.strftime('%d.%m'), dt_local.strftime('%H:%M')
    return {'ru': f"{WEEKDAYS['ru'][wd]} {dm} в {hm}", 'uz': f"{WEEKDAYS['uz'][wd]} {dm} soat {hm}"}


def name(ru, uz):
    return {'ru': ru, 'uz': uz or ru}


def button_key(text):
    """Map a pressed reply-keyboard button (any language) to its key."""
    for key, labels in T.items():
        if key.startswith('btn_') and text in labels.values():
            return key
    return None
