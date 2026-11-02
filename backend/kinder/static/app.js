'use strict';
/* Kinder Spa admin panel. Plain JS, no build step. All text goes through textContent. */

const ERRORS = {
  invalid_credentials: 'Неверный логин или пароль', too_many_attempts: 'Слишком много попыток. Подождите 15 минут',
  unauthorized: 'Сессия истекла, войдите снова', forbidden: 'Недостаточно прав', not_found: 'Не найдено',
  field_required: 'Заполните обязательное поле', invalid_field: 'Некорректное значение', field_too_long: 'Слишком длинное значение',
  reason_required: 'Укажите причину (не короче 3 символов)', already_exists: 'Такая запись уже существует',
  invalid_data: 'Некорректные данные', invalid_login: 'Логин: латиница, цифры, точка, дефис; от 3 символов',
  subscription_frozen: 'Абонемент заморожен', subscription_closed: 'Абонемент закрыт',
  subscription_not_started: 'Абонемент ещё не начался', subscription_expired: 'Срок абонемента истёк',
  subscription_for_other_child: 'Абонемент оформлен на другого ребёнка', child_not_of_client: 'Ребёнок не принадлежит этому клиенту',
  service_not_in_subscription: 'Эта услуга не входит в абонемент', no_visits_left: 'Посещения закончились',
  already_visited_today: 'Сегодня уже есть такое посещение', not_enough_visits: 'Недостаточно посещений',
  not_active: 'Абонемент не активен', not_frozen: 'Абонемент не заморожен', closed: 'Абонемент закрыт', expired: 'Срок истёк',
  already_cancelled: 'Посещение уже отменено', qr_unknown: 'QR-код не найден', qr_already_used: 'QR-код уже использован',
  qr_expired: 'QR-код истёк, попросите обновить', qr_other_client: 'QR-код принадлежит другому клиенту', invalid_qr: 'Это не QR-код Kinder Spa',
  items_required: 'Добавьте хотя бы одну услугу', duplicate_service: 'Услуга повторяется', client_archived: 'Клиент в архиве',
  plan_not_found: 'Тариф не найден', client_not_found: 'Клиент не найден', unsupported_image: 'Только JPG, PNG или WEBP',
  invalid_image: 'Файл не похож на изображение', image_too_large: 'Фото больше 2 МБ', too_many_photos: 'Не больше 10 фото',
  overpayment: 'Сумма больше долга по абонементу', already_voided: 'Оплата уже отменена',
  void_needs_superadmin: 'Отменить можно только свою оплату за сегодня; остальные — главный администратор',
  cannot_disable_self: 'Нельзя отключить самого себя', wrong_current_password: 'Текущий пароль неверный',
  password_length: 'Пароль должен быть от 8 символов', invalid_period: 'Некорректный период', busy_retry: 'База занята, повторите',
  internal_error: 'Ошибка сервера', network: 'Нет связи с сервером', specialist_not_found: 'Специалист не найден',
};
const METHODS = { cash: 'Наличные', card: 'Карта', click: 'Click', payme: 'Payme', transfer: 'Перевод' };
const STATES = { active: 'Активен', frozen: 'Заморожен', closed: 'Закрыт', expired: 'Истёк', used_up: 'Использован', not_started: 'Не начался' };
const ACTIONS = {
  create_client: 'Новый клиент', update_client: 'Изменение клиента', create_child: 'Добавлен ребёнок', update_child: 'Изменение ребёнка',
  issue_client_login: 'Выдан доступ в приложение', disable_client_login: 'Отключён доступ в приложение', create_subscription: 'Оформлен абонемент',
  visit: 'Посещение', cancel_visit: 'Отмена посещения', freeze: 'Заморозка', unfreeze: 'Разморозка', extend: 'Продление',
  adjust: 'Корректировка', close: 'Закрытие', create_staff: 'Новый сотрудник', update_staff: 'Изменение сотрудника',
  reset_password: 'Сброс пароля', change_password: 'Смена пароля', create_service: 'Новая услуга', update_service: 'Изменение услуги',
  add_photo: 'Добавлено фото', delete_photo: 'Удалено фото', create_specialist: 'Новый специалист', update_specialist: 'Изменение специалиста',
  payment: 'Оплата', void_payment: 'Отмена оплаты', telegram_link: 'Вход в Telegram-бот',
  create_plan: 'Новый тариф', update_plan: 'Изменение тарифа', bootstrap_superadmin: 'Создан главный администратор',
};

const state = { token: localStorage.getItem('kinder_token'), me: null, page: 'today', cache: {} };

/* ------------------------------------------------------------- helpers */
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'value') el.value = v;
    else if (k === 'checked') el.checked = !!v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
const $ = (sel, root = document) => root.querySelector(sel);
function errText(e) { return (e && ERRORS[e.code]) || (e && e.code) || 'Ошибка'; }
let toastTimer;
function toast(msg, isError) {
  const t = $('#toast');
  t.textContent = msg; t.className = 'toast show' + (isError ? ' error' : '');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.className = 'toast'; }, isError ? 4500 : 2500);
}
const fmtDate = (s) => s ? new Date(s.length === 10 ? s + 'T00:00:00' : s).toLocaleDateString('ru-RU') : '—';
const fmtDateTime = (s) => s ? new Date(s).toLocaleString('ru-RU', { timeZone: 'Asia/Tashkent', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';
const fmtMoney = (v) => v === null || v === undefined ? '—' : Number(v).toLocaleString('ru-RU') + ' сум';
function todayISO(offsetDays = 0) {
  const d = new Date(Date.now() + offsetDays * 86400000);
  return d.toLocaleDateString('en-CA', { timeZone: 'Asia/Tashkent' });
}
function badge(st) { return h('span', { class: 'badge ' + st }, STATES[st] || st); }

async function api(method, path, body) {
  let res;
  try {
    res = await fetch('/api' + path, {
      method, headers: Object.assign({ 'Content-Type': 'application/json' }, state.token ? { Authorization: 'Bearer ' + state.token } : {}),
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (_) { throw { code: 'network' }; }
  let data = null;
  try { data = await res.json(); } catch (_) { /* empty */ }
  if (res.status === 401 && path !== '/login') { logout(true); throw { code: 'unauthorized' }; }
  if (!res.ok) throw { code: (data && data.error) || 'internal_error', detail: data && data.detail, status: res.status };
  return data;
}
async function guard(fn, okMsg) {
  try { const r = await fn(); if (okMsg) toast(okMsg); return r; } catch (e) { toast(errText(e), true); throw e; }
}
function field(label, input) { return h('label', { class: 'field' }, label, input); }
function readForm(root) {
  const out = {};
  root.querySelectorAll('[name]').forEach((el) => {
    if (el.type === 'checkbox') out[el.name] = el.checked;
    else out[el.name] = el.value.trim();
  });
  return out;
}

/* ------------------------------------------------------------- modal */
function modal(title, body, { okText = 'Сохранить', onOk, onCancel, danger = false, cancelText = 'Отмена', hideOk = false } = {}) {
  const root = $('#modal-root');
  let done = false;
  const close = () => { done = true; root.replaceChildren(); document.removeEventListener('keydown', onKey); };
  const cancel = () => { if (!done && onCancel) onCancel(); close(); };
  const onKey = (e) => { if (e.key === 'Escape') cancel(); };
  const err = h('div', { class: 'error-text' });
  const ok = h('button', { class: 'btn ' + (danger ? 'danger' : 'primary'), type: 'submit' }, okText);
  const form = h('form', { class: 'modal', onsubmit: async (e) => {
    e.preventDefault(); err.textContent = ''; ok.disabled = true;
    try { if (onOk) { const keep = await onOk(form); if (keep !== true) close(); } else close(); }
    catch (ex) { err.textContent = errText(ex); }
    finally { ok.disabled = false; }
  } }, h('h2', {}, title), body, err,
  h('div', { class: 'actions' }, h('button', { class: 'btn', type: 'button', onclick: cancel }, cancelText), hideOk ? null : ok));
  root.replaceChildren(h('div', { class: 'modal-backdrop', onmousedown: (e) => { if (e.target === e.currentTarget) cancel(); } }, form));
  document.addEventListener('keydown', onKey);
  const first = form.querySelector('input:not([type=hidden]), select, textarea');
  if (first) first.focus();
  return { close, form };
}
function showSecret(title, login, password, note) {
  modal(title, h('div', { class: 'stack' },
    h('p', {}, note || 'Передайте эти данные клиенту: с ними можно войти в Telegram-бот Kinder Spa и в приложение. Пароль показывается только один раз.'),
    h('div', { class: 'secret mono' }, h('div', {}, 'Логин: ', h('b', {}, login)), h('div', {}, 'Пароль: ', h('b', {}, password))),
  ), { hideOk: true, cancelText: 'Готово' });
}
function askReason(title, extraFields, onOk) {
  const body = h('div', { class: 'stack' }, extraFields || null, field('Причина *', h('textarea', { name: 'reason', required: true, minlength: 3, maxlength: 500 })));
  modal(title, body, { onOk: (f) => onOk(readForm(f)) });
}

/* ------------------------------------------------------------- reference data */
async function refs(force) {
  if (!force && state.cache.services) return state.cache;
  const [services, specialists, plans] = await Promise.all([api('GET', '/services'), api('GET', '/specialists'), api('GET', '/plans')]);
  Object.assign(state.cache, { services, specialists, plans });
  return state.cache;
}

/* ------------------------------------------------------------- auth & shell */
function logout(silent) {
  if (state.token && !silent) api('POST', '/logout').catch(() => {});
  state.token = null; state.me = null; localStorage.removeItem('kinder_token');
  renderLogin();
}
function renderLogin() {
  const err = h('div', { class: 'error-text' });
  const form = h('form', { class: 'card login', onsubmit: async (e) => {
    e.preventDefault(); err.textContent = '';
    const d = readForm(form);
    try {
      const r = await api('POST', '/login', { login: d.login, password: d.password });
      if (r.role === 'client') { err.textContent = 'Это вход для сотрудников. Клиенты пользуются приложением.'; state.token = r.token; await api('POST', '/logout').catch(() => {}); state.token = null; return; }
      state.token = r.token; localStorage.setItem('kinder_token', r.token); start();
    } catch (ex) { err.textContent = errText(ex); }
  } },
  h('div', { class: 'brand' }, h('img', { src: '/admin/static/icon.svg', alt: '' }), 'Kinder Spa'),
  h('div', { class: 'stack' },
    field('Логин', h('input', { name: 'login', autocomplete: 'username', required: true, autocapitalize: 'none' })),
    field('Пароль', h('input', { name: 'password', type: 'password', autocomplete: 'current-password', required: true })),
    err, h('button', { class: 'btn primary', type: 'submit' }, 'Войти')));
  $('#app').replaceChildren(h('div', { class: 'login-wrap' }, form));
}

const PAGES = [
  ['today', 'Сегодня'], ['scan', 'Сканер QR'], ['clients', 'Клиенты'], ['subscriptions', 'Абонементы'], ['visits', 'Посещения'], ['cash', 'Касса'],
  ['services', 'Услуги'], ['specialists', 'Специалисты'], ['plans', 'Тарифы'], ['reports', 'Отчёты'],
  ['staff', 'Сотрудники', 'superadmin'], ['audit', 'Журнал'],
];

function shell() {
  const sidebar = h('nav', { class: 'sidebar' },
    h('div', { class: 'brand' }, h('img', { src: '/admin/static/icon.svg', alt: '' }), 'Kinder Spa'),
    PAGES.filter((p) => !p[2] || p[2] === state.me.role).map(([id, title]) =>
      h('button', { class: 'nav-btn' + (state.page === id || (state.page === 'client' && id === 'clients') ? ' active' : ''), 'data-page': id, onclick: () => go(id) }, title)),
    h('div', { class: 'spacer' }),
    h('div', { class: 'user-box' }, h('div', { class: 'name' }, state.me.full_name || state.me.login),
      h('div', {}, state.me.role === 'superadmin' ? 'Главный администратор' : 'Администратор'),
      h('div', { class: 'row' }, h('button', { class: 'btn small', onclick: changePassword }, 'Пароль'),
        h('button', { class: 'btn small', onclick: () => logout() }, 'Выйти'))));
  const main = h('main', { class: 'main', id: 'main' });
  const top = h('div', { class: 'topbar' }, h('button', { onclick: () => sidebar.classList.toggle('open'), 'aria-label': 'Меню' }, '☰'), h('b', {}, 'Kinder Spa'));
  $('#app').replaceChildren(top, h('div', { class: 'layout' }, sidebar, main));
}
function changePassword() {
  modal('Смена пароля', h('div', { class: 'stack' },
    field('Текущий пароль', h('input', { name: 'current', type: 'password', required: true, autocomplete: 'current-password' })),
    field('Новый пароль (от 8 символов)', h('input', { name: 'new', type: 'password', required: true, minlength: 8, autocomplete: 'new-password' }))),
  { onOk: async (f) => { await api('POST', '/me/password', readForm(f)); toast('Пароль изменён, войдите снова'); logout(true); } });
}

let stopScanner = null;
function go(page, arg) {
  if (stopScanner) { stopScanner(); stopScanner = null; }
  state.page = page;
  state.key = page + (arg ? '/' + arg : '');
  if (location.hash.slice(1) !== state.key) location.hash = state.key;
  shell();
  const main = $('#main');
  main.append(h('div', { class: 'muted' }, 'Загрузка…'));
  const render = { today: pageToday, scan: pageScan, clients: pageClients, client: pageClient, subscriptions: pageSubscriptions,
    visits: pageVisits, cash: pageCash, services: pageServices, specialists: pageSpecialists, plans: pagePlans, reports: pageReports, staff: pageStaff, audit: pageAudit }[page] || pageToday;
  Promise.resolve(render(main, arg)).catch((e) => { main.replaceChildren(h('div', { class: 'card' }, errText(e))); });
}
async function start() {
  try { state.me = await api('GET', '/me'); } catch (_) { return renderLogin(); }
  if (state.me.role === 'client') return logout();
  const [page, arg] = (location.hash.slice(1) || 'today').split('/');
  if (page === 'client' && arg) {
    state.page = 'clients'; go('client', arg);
  } else go(PAGES.some((p) => p[0] === page) ? page : 'today');
}

/* ------------------------------------------------------------- pages: today */
async function pageToday(main) {
  const [rep, expiring, visits] = await Promise.all([
    api('GET', `/reports?from=${todayISO()}&to=${todayISO()}`), api('GET', '/subscriptions?state=expiring'), api('GET', '/visits')]);
  const cashToday = rep.received.total;
  const t = rep.totals;
  main.replaceChildren(
    h('div', { class: 'row between' }, h('h1', {}, 'Сегодня, ' + new Date().toLocaleDateString('ru-RU', { timeZone: 'Asia/Tashkent', day: 'numeric', month: 'long' })),
      h('div', { class: 'row' }, h('button', { class: 'btn primary', onclick: () => go('scan') }, 'Сканировать QR'),
        h('button', { class: 'btn', onclick: () => newClient() }, '+ Клиент'))),
    h('div', { class: 'grid stats' },
      stat(t.visits_today, 'посещений сегодня'), stat(t.active_subscriptions, 'активных абонементов'),
      stat(fmtMoney(cashToday), 'касса сегодня'), stat(fmtMoney(rep.debt_total), 'долг клиентов'), stat(t.clients, 'клиентов')),
    h('div', { class: 'grid two' },
      h('div', { class: 'card' }, h('h2', {}, 'Посещения сегодня'), visitsTable(visits, { compact: true, onChange: () => go('today') })),
      h('div', { class: 'card' }, h('h2', {}, 'Заканчиваются (7 дней или ≤1 визит)'), subsTable(expiring))));
}
function stat(value, label) { return h('div', { class: 'stat' }, h('div', { class: 'value' }, value ?? 0), h('div', { class: 'label' }, label)); }

/* ------------------------------------------------------------- pages: clients */
async function pageClients(main) {
  const list = h('div', {});
  const q = h('input', { class: 'search', type: 'search', placeholder: 'Имя родителя или ребёнка, телефон, номер', value: state.cache.clientQuery || '' });
  const archived = h('input', { type: 'checkbox' });
  let timer;
  const load = async () => {
    state.cache.clientQuery = q.value;
    const rows = await api('GET', `/clients?q=${encodeURIComponent(q.value)}${archived.checked ? '&archived=1' : ''}`);
    list.replaceChildren(rows.length ? h('div', { class: 'table-wrap' }, h('table', {},
      h('thead', {}, h('tr', {}, h('th', {}, '№'), h('th', {}, 'Родитель'), h('th', {}, 'Телефон'), h('th', {}, 'Дети'), h('th', {}, 'Абонементы'), h('th', {}, 'Приложение'))),
      h('tbody', {}, rows.map((r) => h('tr', { class: 'click', onclick: () => go('client', r.id) },
        h('td', { class: 'muted' }, r.id), h('td', {}, h('b', {}, r.full_name)), h('td', {}, r.phone || '—'), h('td', {}, r.children || '—'),
        h('td', {}, r.active_subscriptions ? h('span', { class: 'badge active' }, r.active_subscriptions) : h('span', { class: 'muted' }, '—')),
        h('td', {}, r.login ? (r.login_enabled ? h('span', { class: 'badge' }, r.login) : h('span', { class: 'badge bad' }, 'отключён')) : '—')))))) :
      h('div', { class: 'empty' }, q.value ? 'Ничего не найдено' : 'Клиентов пока нет'));
  };
  q.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(load, 250); });
  archived.addEventListener('change', load);
  main.replaceChildren(h('div', { class: 'row between' }, h('h1', {}, 'Клиенты'), h('button', { class: 'btn primary', onclick: () => newClient() }, '+ Новый клиент')),
    h('div', { class: 'card' }, h('div', { class: 'row' }, q, h('label', { class: 'check' }, archived, 'Архив')), list));
  await load();
  q.focus();
}
function newClient() {
  const kids = h('div', { class: 'stack' });
  const addKid = () => kids.append(h('div', { class: 'row kid' }, h('input', { placeholder: 'Имя ребёнка', 'data-kid': 'name' }), h('input', { type: 'date', 'data-kid': 'birth' })));
  addKid();
  modal('Новый клиент', h('div', { class: 'stack' },
    field('ФИО родителя *', h('input', { name: 'full_name', required: true, minlength: 2 })),
    field('Телефон', h('input', { name: 'phone', type: 'tel', placeholder: '+998 __ ___ __ __' })),
    field('Заметка', h('textarea', { name: 'note' })),
    h('h3', {}, 'Дети'), kids, h('button', { class: 'btn small', type: 'button', onclick: addKid }, '+ ещё ребёнок')),
  { okText: 'Создать', onOk: async (f) => {
    const d = readForm(f);
    d.children = [...kids.querySelectorAll('.kid')].map((k) => ({ full_name: k.querySelector('[data-kid=name]').value.trim(), birth_date: k.querySelector('[data-kid=birth]').value || null })).filter((k) => k.full_name);
    const r = await api('POST', '/clients', d);
    toast('Клиент создан'); go('client', r.id);
  } });
}

async function pageClient(main, id) {
  const [c, { plans, services, specialists }] = await Promise.all([api('GET', '/clients/' + id), refs()]);
  const reload = () => go('client', id);
  const activeKids = c.children.filter((k) => !k.archived);
  main.replaceChildren(
    h('div', { class: 'row between' }, h('div', {}, h('button', { class: 'btn small', onclick: () => go('clients') }, '← Клиенты'),
      h('h1', {}, c.full_name, ' ', c.archived ? h('span', { class: 'badge bad' }, 'архив') : null)),
    h('div', { class: 'row' }, h('button', { class: 'btn primary', onclick: () => newSubscription(c, plans, services, reload), disabled: c.archived }, '+ Абонемент'))),
    h('div', { class: 'grid two' },
      h('div', { class: 'card' }, h('div', { class: 'row between' }, h('h2', {}, 'Данные'), h('button', { class: 'btn small', onclick: () => editClient(c, reload) }, 'Изменить')),
        h('div', { class: 'stack' }, h('div', {}, h('span', { class: 'muted' }, 'Телефон: '), c.phone || '—'),
          h('div', {}, h('span', { class: 'muted' }, 'Заметка: '), c.note || '—'),
          h('div', { class: 'muted small' }, 'Клиент №', c.id, ' · с ', fmtDate(c.created_at)))),
      h('div', { class: 'card' }, h('div', { class: 'row between' }, h('h2', {}, 'Дети'), h('button', { class: 'btn small', onclick: () => editChild(c.id, null, reload) }, '+ Добавить')),
        c.children.length ? h('div', { class: 'stack' }, c.children.map((k) => h('div', { class: 'row between' },
          h('div', {}, h('b', {}, k.full_name), k.birth_date ? h('span', { class: 'muted' }, ' · ', fmtDate(k.birth_date), ' (', age(k.birth_date), ')') : null,
            k.archived ? h('span', { class: 'badge closed' }, ' архив') : null, k.note ? h('div', { class: 'small muted' }, k.note) : null),
          h('button', { class: 'btn small', onclick: () => editChild(c.id, k, reload) }, 'Изменить')))) : h('div', { class: 'muted' }, 'Не добавлены')),
      h('div', { class: 'card' }, h('h2', {}, 'Доступ в приложение'),
        c.login ? h('div', { class: 'stack' }, h('div', {}, 'Логин: ', h('b', { class: 'mono' }, c.login), ' ', c.login_enabled ? h('span', { class: 'badge active' }, 'активен') : h('span', { class: 'badge bad' }, 'отключён')),
          h('div', { class: 'small' }, 'Telegram-бот: ', c.telegram_chats ? h('span', { class: 'badge active' }, 'подключён') : h('span', { class: 'muted' }, 'не подключён (войти можно тем же логином)')),
          h('div', { class: 'row' }, h('button', { class: 'btn', onclick: () => issueLogin(c, reload) }, c.login_enabled ? 'Сбросить пароль' : 'Включить с новым паролем'),
            c.login_enabled ? h('button', { class: 'btn danger', onclick: () => disableLogin(c, reload) }, 'Отключить') : null))
          : h('div', { class: 'stack' }, h('div', { class: 'muted' }, 'Логин ещё не выдан'), h('button', { class: 'btn', onclick: () => issueLogin(c, reload), disabled: c.archived }, 'Выдать логин и пароль')))),
    h('div', { class: 'card' }, h('h2', {}, 'Абонементы'),
      c.subscriptions.length ? c.subscriptions.map((s) => subCard(s, activeKids, specialists, reload)) : h('div', { class: 'empty' }, 'Абонементов нет')),
    h('div', { class: 'card' }, h('h2', {}, 'Посещения'), visitsTable(c.visits, { onChange: reload, hideClient: true })));
}
function age(birth) {
  const b = new Date(birth + 'T00:00:00'); const n = new Date();
  let y = n.getFullYear() - b.getFullYear(); let m = n.getMonth() - b.getMonth();
  if (n.getDate() < b.getDate()) m -= 1;
  if (m < 0) { y -= 1; m += 12; }
  return y > 0 ? `${y} г. ${m} мес.` : `${m} мес.`;
}
function editClient(c, done) {
  modal('Данные клиента', h('div', { class: 'stack' },
    field('ФИО родителя *', h('input', { name: 'full_name', value: c.full_name, required: true })),
    field('Телефон', h('input', { name: 'phone', value: c.phone })),
    field('Заметка', h('textarea', { name: 'note' }, c.note)),
    h('label', { class: 'check' }, h('input', { type: 'checkbox', name: 'archived', checked: c.archived }), 'В архиве (отключит доступ в приложение)')),
  { onOk: async (f) => { await api('PATCH', '/clients/' + c.id, readForm(f)); toast('Сохранено'); done(); } });
}
function editChild(clientId, k, done) {
  modal(k ? 'Ребёнок' : 'Новый ребёнок', h('div', { class: 'stack' },
    field('Имя *', h('input', { name: 'full_name', value: k ? k.full_name : '', required: true })),
    field('Дата рождения', h('input', { name: 'birth_date', type: 'date', value: k ? (k.birth_date || '') : '' })),
    field('Заметка (без медицинских диагнозов)', h('textarea', { name: 'note' }, k ? k.note : '')),
    k ? h('label', { class: 'check' }, h('input', { type: 'checkbox', name: 'archived', checked: k.archived }), 'В архиве') : null),
  { onOk: async (f) => {
    const d = readForm(f); d.birth_date = d.birth_date || null;
    if (k) await api('PATCH', '/children/' + k.id, d); else await api('POST', `/clients/${clientId}/children`, d);
    toast('Сохранено'); done();
  } });
}
async function issueLogin(c, done) {
  const r = await guard(() => api('POST', `/clients/${c.id}/credentials`, {}));
  done();
  showSecret('Доступ в приложение', r.login, r.password);
}
function disableLogin(c, done) {
  modal('Отключить доступ?', h('p', {}, 'Клиент не сможет войти в приложение, пока вы не выдадите новый пароль.'),
    { okText: 'Отключить', danger: true, onOk: async () => { await api('DELETE', `/clients/${c.id}/credentials`); toast('Доступ отключён'); done(); } });
}

/* ------------------------------------------------------------- subscriptions */
function itemsView(items) {
  return h('div', { class: 'items' }, items.map((i) => h('div', { class: 'item' }, i.name_ru, ': ', h('b', {}, i.remaining), ' / ', i.quota,
    h('div', { class: 'bar' }, (() => { const b = h('i'); b.style.width = (i.quota ? Math.round(100 * i.remaining / i.quota) : 0) + '%'; return b; })()))));
}
function subCard(s, kids, specialists, reload) {
  const live = s.state === 'active';
  return h('div', { class: 'sub' + (['closed', 'expired', 'used_up'].includes(s.state) ? ' inactive' : '') },
    h('div', { class: 'row between' }, h('div', {}, h('b', {}, s.name), ' ', badge(s.state), s.child_name ? h('span', { class: 'muted' }, ' · для ', s.child_name) : null),
      h('div', { class: 'muted small' }, fmtDate(s.starts_on), ' — ', fmtDate(s.ends_on), s.frozen_since ? ` · заморожен с ${fmtDate(s.frozen_since)}` : '', ' · ', fmtMoney(s.price), ' ', payBadge(s))),
    itemsView(s.items),
    h('div', { class: 'row' },
      Number(s.debt) > 0 ? h('button', { class: 'btn small primary', onclick: () => takePayment(s, reload) }, 'Принять оплату') : null,
      live ? h('button', { class: 'btn primary small', onclick: () => markVisit(s, kids, specialists, reload) }, 'Отметить посещение') : null,
      s.status === 'active' && s.state !== 'expired' ? h('button', { class: 'btn small', onclick: () => askReason('Заморозить абонемент', null, async (d) => { await api('POST', `/subscriptions/${s.id}/freeze`, d); toast('Заморожен'); reload(); }) }, 'Заморозить') : null,
      s.status === 'frozen' ? h('button', { class: 'btn small', onclick: () => guard(async () => { const r = await api('POST', `/subscriptions/${s.id}/unfreeze`); toast(r.frozen_days ? `Разморожен, срок продлён на ${r.frozen_days} дн.` : 'Разморожен'); reload(); }) }, 'Разморозить') : null,
      s.status !== 'closed' ? h('button', { class: 'btn small', onclick: () => askReason('Продлить срок', field('На сколько дней', h('input', { name: 'days', type: 'number', min: 1, max: 365, value: 7, required: true })),
        async (d) => { await api('POST', `/subscriptions/${s.id}/extend`, { days: Number(d.days), reason: d.reason }); toast('Срок продлён'); reload(); }) }, 'Продлить') : null,
      s.status !== 'closed' ? h('button', { class: 'btn small', onclick: () => askReason('Корректировка посещений', h('div', { class: 'row' },
        field('Услуга', h('select', { name: 'service_id' }, s.items.map((i) => h('option', { value: i.service_id }, i.name_ru)))),
        field('Изменение (+/−)', h('input', { name: 'delta', type: 'number', min: -500, max: 500, value: 1, required: true }))),
      async (d) => { await api('POST', `/subscriptions/${s.id}/adjust`, { service_id: Number(d.service_id), delta: Number(d.delta), reason: d.reason }); toast('Скорректировано'); reload(); }) }, 'Корректировка') : null,
      h('button', { class: 'btn small', onclick: () => subHistory(s.id) }, 'История'),
      s.status !== 'closed' ? h('button', { class: 'btn small danger', onclick: () => askReason('Закрыть абонемент', h('p', { class: 'muted' }, 'Закрытый абонемент нельзя использовать.'), async (d) => { await api('POST', `/subscriptions/${s.id}/close`, d); toast('Закрыт'); reload(); }) }, 'Закрыть') : null));
}
function payBadge(s) {
  if (Number(s.price) === 0) return null;
  return Number(s.debt) > 0 ? h('span', { class: 'badge bad' }, 'долг ', fmtMoney(s.debt)) : h('span', { class: 'badge active' }, 'оплачен');
}
function takePayment(s, done) {
  modal('Принять оплату — ' + s.name, h('div', { class: 'stack' },
    h('p', { class: 'muted' }, `Цена ${fmtMoney(s.price)}, оплачено ${fmtMoney(s.paid)}, долг `, h('b', {}, fmtMoney(s.debt))),
    h('div', { class: 'row' }, field('Сумма, сум', h('input', { name: 'amount', type: 'number', min: 1, step: '0.01', max: s.debt, value: s.debt, required: true })),
      field('Способ', methodSelect('method'))),
    field('Комментарий', h('input', { name: 'note', maxlength: 300 }))),
  { okText: 'Принять', onOk: async (f) => { const d = readForm(f); const r = await api('POST', `/subscriptions/${s.id}/payments`, d); toast(Number(r.debt) > 0 ? `Оплата принята, долг ${fmtMoney(r.debt)}` : 'Оплачено полностью'); done(); } });
}
function methodSelect(name) { return h('select', { name }, Object.entries(METHODS).map(([k, v]) => h('option', { value: k }, v))); }
function voidPayment(p, done) {
  askReason(`Отменить оплату ${fmtMoney(p.amount)}?`, h('p', { class: 'muted' }, 'Оплата останется в журнале как отменённая, долг вернётся.'),
    async (d) => { await api('POST', `/payments/${p.id}/void`, d); toast('Оплата отменена'); done(); });
}
function paymentsTable(rows, { onChange, hideClient } = {}) {
  if (!rows.length) return h('div', { class: 'empty' }, 'Оплат нет');
  return h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, 'Когда'), hideClient ? null : h('th', {}, 'Клиент'), h('th', {}, 'Сумма'), h('th', {}, 'Способ'), h('th', {}, 'Принял'), h('th', {}, ''))),
    h('tbody', {}, rows.map((p) => h('tr', { class: p.voided_at ? 'cancelled' : '' },
      h('td', { class: 'small' }, fmtDateTime(p.paid_at)),
      hideClient ? null : h('td', {}, h('a', { href: '#client/' + p.client_id, onclick: (e) => { e.preventDefault(); go('client', p.client_id); } }, p.client_name), h('div', { class: 'small muted' }, p.subscription_name)),
      h('td', { class: 'num' }, fmtMoney(p.amount)), h('td', {}, METHODS[p.method] || p.method, p.note ? h('div', { class: 'small muted' }, p.note) : null),
      h('td', { class: 'small' }, p.staff_name),
      h('td', {}, p.voided_at ? h('span', { class: 'small muted', title: p.void_reason || '' }, 'отменена') : h('button', { class: 'btn small danger', onclick: () => voidPayment(p, onChange) }, 'Отменить')))))));
}
async function pageCash(main) {
  const from = h('input', { type: 'date', value: state.cache.cFrom || todayISO() });
  const to = h('input', { type: 'date', value: state.cache.cTo || todayISO() });
  const box = h('div', {});
  const load = async () => {
    state.cache.cFrom = from.value; state.cache.cTo = to.value;
    const r = await api('GET', `/payments?from=${from.value}&to=${to.value}`);
    box.replaceChildren(h('div', { class: 'grid stats' }, stat(fmtMoney(r.total), 'всего получено'),
      ...Object.entries(METHODS).filter(([k]) => Number(r.by_method[k]) > 0).map(([k, v]) => stat(fmtMoney(r.by_method[k]), v))),
    h('div', { class: 'card' }, paymentsTable(r.payments, { onChange: load })));
  };
  [from, to].forEach((el) => el.addEventListener('change', () => guard(load)));
  main.replaceChildren(h('h1', {}, 'Касса'), h('div', { class: 'card row' }, field('С', from), field('По', to)), box);
  await load();
}
async function subHistory(id) {
  const s = await guard(() => api('GET', '/subscriptions/' + id));
  const close = () => $('#modal-root').replaceChildren();
  modal('История: ' + s.name, h('div', { class: 'stack' }, h('h3', {}, 'Оплаты'), paymentsTable(s.payments, { hideClient: true, onChange: () => { close(); go(state.page, $('#main') && state.key.split('/')[1]); } }), h('h3', {}, 'Действия'), h('div', { class: 'table-wrap' }, h('table', {}, h('tbody', {}, s.history.map((e) => h('tr', {},
    h('td', { class: 'small muted' }, fmtDateTime(e.at)), h('td', {}, ACTIONS[e.action] || e.action, e.details && e.details.reason ? h('div', { class: 'small muted' }, e.details.reason) : null),
    h('td', { class: 'small' }, e.actor || '—'))))))), { hideOk: true, cancelText: 'Закрыть' });
}
function newSubscription(c, plans, services, done) {
  const activePlans = plans.filter((p) => p.active);
  const kids = c.children.filter((k) => !k.archived);
  const custom = h('div', { class: 'stack hidden' },
    field('Название *', h('input', { name: 'name', placeholder: 'Например, Комбо бассейн + массаж' })),
    field('Срок действия, дней *', h('input', { name: 'validity_days', type: 'number', min: 1, max: 730, value: 30 })),
    h('div', { class: 'stack' }, services.filter((s) => s.active).map((s) => h('div', { class: 'row' },
      h('label', { class: 'check' }, h('input', { type: 'checkbox', 'data-svc': s.id }), s.name_ru),
      h('input', { type: 'number', min: 1, max: 500, value: 10, 'data-visits': s.id, class: 'right' })))));
  const planSel = h('select', { name: 'plan_id', onchange: () => {
    custom.classList.toggle('hidden', planSel.value !== 'custom');
    const p = activePlans.find((x) => String(x.id) === planSel.value);
    price.value = p ? p.price : ''; paidNow.value = price.value;
  } }, activePlans.map((p) => h('option', { value: p.id }, `${p.name} — ${p.items.map((i) => i.visits + ' × ' + i.name_ru).join(', ')}, ${p.validity_days} дн.`)), h('option', { value: 'custom' }, 'Индивидуальный (вручную)…'));
  const price = h('input', { name: 'price', type: 'number', min: 0, step: '0.01', value: activePlans[0] ? activePlans[0].price : '' });
  const paidNow = h('input', { name: 'paid_amount', type: 'number', min: 0, step: '0.01', value: activePlans[0] ? activePlans[0].price : '' });
  price.addEventListener('input', () => { paidNow.value = price.value; });
  modal('Новый абонемент — ' + c.full_name, h('div', { class: 'stack' },
    field('Тариф', planSel), custom,
    field('Для ребёнка', h('select', { name: 'child_id' }, h('option', { value: '' }, 'Любой ребёнок семьи'), kids.map((k) => h('option', { value: k.id }, k.full_name)))),
    h('div', { class: 'row' }, field('Начало', h('input', { name: 'starts_on', type: 'date', value: todayISO() })), field('Цена, сум', price)),
    h('div', { class: 'row' }, field('Оплачено сейчас, сум', paidNow), field('Способ оплаты', methodSelect('paid_method')))),
  { okText: 'Оформить', onOk: async (f) => {
    const d = readForm(f);
    const body = { client_id: c.id, child_id: d.child_id ? Number(d.child_id) : null, starts_on: d.starts_on, price: d.price === '' ? null : d.price,
      paid_amount: d.paid_amount && Number(d.paid_amount) > 0 ? d.paid_amount : null, paid_method: d.paid_method };
    if (d.plan_id === 'custom') {
      body.name = d.name; body.validity_days = Number(d.validity_days);
      body.items = [...f.querySelectorAll('[data-svc]')].filter((x) => x.checked).map((x) => ({ service_id: Number(x.dataset.svc), visits: Number(f.querySelector(`[data-visits="${x.dataset.svc}"]`).value) }));
    } else body.plan_id = Number(d.plan_id);
    await api('POST', '/subscriptions', body); toast('Абонемент оформлен'); done();
  } });
}
function visitForm(s, kids, specialists) {
  const usable = s.items.filter((i) => i.remaining > 0);
  const svcSel = h('select', { name: 'service_id' }, usable.map((i) => h('option', { value: i.service_id }, `${i.name_ru} (осталось ${i.remaining})`)));
  const specSel = h('select', { name: 'specialist_id' });
  const fillSpecs = () => {
    const sid = Number(svcSel.value);
    specSel.replaceChildren(h('option', { value: '' }, '— не указан —'), ...specialists.filter((p) => p.active && p.service_ids.includes(sid)).map((p) => h('option', { value: p.id }, p.full_name)));
  };
  svcSel.addEventListener('change', fillSpecs); fillSpecs();
  return { usable, el: h('div', { class: 'stack' }, field('Услуга', svcSel),
    s.child_id ? h('div', { class: 'muted' }, 'Ребёнок: ', s.child_name) : field('Ребёнок', h('select', { name: 'child_id' }, kids.length ? null : h('option', { value: '' }, '—'), kids.map((k) => h('option', { value: k.id }, k.full_name)))),
    field('Специалист', specSel)) };
}
function visitBody(d) {
  return { service_id: Number(d.service_id), child_id: d.child_id ? Number(d.child_id) : null, specialist_id: d.specialist_id ? Number(d.specialist_id) : null };
}
/* Resolves with the retry result, or null if the user declines. */
async function confirmDuplicate(e, retry) {
  if (e.code !== 'already_visited_today') throw e;
  return new Promise((resolve) => {
    modal('Повторное посещение?', h('p', {}, 'Сегодня по этому абонементу уже отмечено такое посещение. Отметить ещё одно?'),
      { okText: 'Да, отметить', onCancel: () => resolve(null), onOk: async () => { resolve(await retry()); } });
  });
}
function markVisit(s, kids, specialists, done) {
  const f = visitForm(s, kids, specialists);
  if (!f.usable.length) { toast('Посещения закончились', true); return; }
  modal('Отметить посещение', f.el, { okText: 'Списать посещение', onOk: async (form) => {
    const body = Object.assign({ subscription_id: s.id }, visitBody(readForm(form)));
    let r;
    try { r = await api('POST', '/visits', body); } catch (e) {
      if (e.code !== 'already_visited_today') throw e;
      setTimeout(() => confirmDuplicate(e, () => api('POST', '/visits', Object.assign(body, { force: true })))
        .then((x) => { if (x) { toast(`Списано. Осталось: ${x.remaining}`); done(); } }), 0);
      return;
    }
    toast(`Списано. Осталось: ${r.remaining}`); done();
  } });
}
function subsTable(rows) {
  if (!rows.length) return h('div', { class: 'empty' }, 'Нет');
  return h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, 'Клиент'), h('th', {}, 'Абонемент'), h('th', {}, 'Остаток'), h('th', {}, 'До'), h('th', {}, 'Статус'))),
    h('tbody', {}, rows.map((s) => h('tr', { class: 'click', onclick: () => go('client', s.client_id) },
      h('td', {}, h('b', {}, s.client_name), s.child_name ? h('div', { class: 'small muted' }, s.child_name) : null), h('td', {}, s.name),
      h('td', {}, s.items.map((i) => `${i.name_ru}: ${i.remaining}/${i.quota}`).join(', ')), h('td', {}, fmtDate(s.ends_on)), h('td', {}, badge(s.state), ' ', payBadge(s)))))));
}
async function pageSubscriptions(main) {
  const tabs = [['expiring', 'Заканчиваются'], ['debt', 'С долгом'], ['frozen', 'Заморожены'], ['', 'Все действующие']];
  let current = state.cache.subTab ?? 'expiring';
  const box = h('div', {});
  const bar = h('div', { class: 'row' });
  const load = async () => {
    state.cache.subTab = current;
    bar.replaceChildren(...tabs.map(([k, t]) => h('button', { class: 'btn' + (k === current ? ' primary' : ''), onclick: () => { current = k; load(); } }, t)));
    box.replaceChildren(subsTable(await api('GET', '/subscriptions' + (current ? '?state=' + current : ''))));
  };
  main.replaceChildren(h('h1', {}, 'Абонементы'), h('div', { class: 'card stack' }, bar, box));
  await load();
}

/* ------------------------------------------------------------- visits */
function visitsTable(rows, { compact, onChange, hideClient } = {}) {
  if (!rows.length) return h('div', { class: 'empty' }, 'Посещений нет');
  return h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, 'Время'), hideClient ? null : h('th', {}, 'Клиент'), h('th', {}, 'Услуга'),
    compact ? null : h('th', {}, 'Специалист'), compact ? null : h('th', {}, 'Отметил'), h('th', {}, ''))),
  h('tbody', {}, rows.map((v) => h('tr', { class: v.cancelled_at ? 'cancelled' : '' },
    h('td', { class: 'small' }, fmtDateTime(v.visited_at), v.method === 'qr' ? h('span', { class: 'badge' }, ' QR') : null),
    hideClient ? null : h('td', {}, h('a', { href: '#client/' + v.client_id, onclick: (e) => { e.preventDefault(); go('client', v.client_id); } }, v.client_name), v.child_name ? h('div', { class: 'small muted' }, v.child_name) : null),
    h('td', {}, v.service_name, compact ? null : h('div', { class: 'small muted' }, v.subscription_name)),
    compact ? null : h('td', { class: 'small' }, v.specialist_name || '—'), compact ? null : h('td', { class: 'small' }, v.staff_name),
    h('td', {}, v.cancelled_at ? h('span', { class: 'small muted', title: v.cancel_reason || '' }, 'отменено') :
      h('button', { class: 'btn small danger', onclick: () => askReason('Отменить посещение', h('p', { class: 'muted' }, 'Посещение вернётся на абонемент.'),
        async (d) => { await api('POST', `/visits/${v.id}/cancel`, d); toast('Посещение отменено'); if (onChange) onChange(); }) }, 'Отменить')))))));
}
async function pageVisits(main) {
  const { services } = await refs();
  const from = h('input', { type: 'date', value: state.cache.vFrom || todayISO() });
  const to = h('input', { type: 'date', value: state.cache.vTo || todayISO() });
  const svc = h('select', {}, h('option', { value: '' }, 'Все услуги'), services.map((s) => h('option', { value: s.id }, s.name_ru)));
  const box = h('div', {});
  const load = async () => {
    state.cache.vFrom = from.value; state.cache.vTo = to.value;
    const rows = await api('GET', `/visits?from=${from.value}&to=${to.value}${svc.value ? '&service_id=' + svc.value : ''}`);
    const live = rows.filter((r) => !r.cancelled_at).length;
    box.replaceChildren(h('div', { class: 'muted' }, `Посещений: ${live}`, rows.length > live ? ` (+${rows.length - live} отменено)` : ''), visitsTable(rows, { onChange: load }));
  };
  [from, to, svc].forEach((el) => el.addEventListener('change', load));
  main.replaceChildren(h('h1', {}, 'Посещения'), h('div', { class: 'card stack' }, h('div', { class: 'row' }, field('С', from), field('По', to), field('Услуга', svc)), box));
  await load();
}

/* ------------------------------------------------------------- QR scanner */
async function pageScan(main) {
  const { specialists } = await refs();
  const result = h('div', {});
  const input = h('input', { class: 'scan-input', placeholder: 'Наведите сканер или вставьте код', autocomplete: 'off' });
  const video = h('video', { playsinline: true, muted: true, class: 'hidden' });
  const camBtn = h('button', { class: 'btn', type: 'button' }, 'Включить камеру');
  const camNote = h('div', { class: 'small muted' });
  let stream = null; let loop = null; let busy = false;
  const stopCam = () => { if (loop) clearInterval(loop); loop = null; if (stream) stream.getTracks().forEach((t) => t.stop()); stream = null; video.classList.add('hidden'); camBtn.textContent = 'Включить камеру'; };
  stopScanner = stopCam;

  const lookup = async (code) => {
    if (busy || !code) return; busy = true;
    try {
      const r = await api('POST', '/qr/lookup', { code });
      stopCam(); showClient(code, r.client);
    } catch (e) { result.replaceChildren(h('div', { class: 'card' }, h('span', { class: 'badge bad' }, errText(e)))); }
    finally { busy = false; input.value = ''; }
  };
  const showClient = (code, c) => {
    const kids = c.children.filter((k) => !k.archived);
    const subs = c.subscriptions.filter((s) => s.state === 'active');
    result.replaceChildren(h('div', { class: 'card stack' },
      h('div', { class: 'row between' }, h('h2', {}, c.full_name), h('a', { href: '#client/' + c.id, onclick: (e) => { e.preventDefault(); go('client', c.id); } }, 'Карточка клиента →')),
      kids.length ? h('div', { class: 'muted' }, 'Дети: ', kids.map((k) => k.full_name).join(', ')) : null,
      subs.length ? subs.map((s) => {
        const f = visitForm(s, kids, specialists);
        const btn = h('button', { class: 'btn primary', disabled: !f.usable.length }, f.usable.length ? 'Списать посещение' : 'Посещения закончились');
        const redeem = async (force) => api('POST', '/qr/redeem', Object.assign({ code, subscription_id: s.id, force }, visitBody(readForm(box))));
        const box = h('div', { class: 'sub' }, h('b', {}, s.name), s.child_name ? h('span', { class: 'muted' }, ' · для ', s.child_name) : null,
          h('span', { class: 'muted small' }, ' · до ', fmtDate(s.ends_on)), itemsView(s.items), f.usable.length ? f.el : null, h('div', { class: 'row' }, btn));
        btn.addEventListener('click', async () => {
          btn.disabled = true;
          try {
            let r;
            try { r = await redeem(false); } catch (e) { r = await confirmDuplicate(e, () => redeem(true)); }
            if (!r) { btn.disabled = false; return; }
            result.replaceChildren(h('div', { class: 'card' }, h('h2', {}, '✓ Посещение списано'), h('p', {}, `${c.full_name}: осталось ${r.remaining}.`),
              h('button', { class: 'btn primary', onclick: () => { result.replaceChildren(); input.focus(); } }, 'Следующий')));
          } catch (e) { toast(errText(e), true); btn.disabled = false; }
        });
        return box;
      }) : h('div', { class: 'empty' }, 'Нет активных абонементов. ', h('a', { href: '#', onclick: (e) => { e.preventDefault(); go('client', c.id); } }, 'Оформить')),
      h('button', { class: 'btn', onclick: () => { result.replaceChildren(); input.focus(); } }, 'Отмена')));
  };

  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); lookup(input.value.trim()); } });
  input.addEventListener('paste', () => setTimeout(() => { if (input.value.trim().startsWith('KSPA1:')) lookup(input.value.trim()); }, 0));
  camBtn.addEventListener('click', async () => {
    if (stream) return stopCam();
    if (!('BarcodeDetector' in window)) { camNote.textContent = 'Этот браузер не умеет распознавать QR с камеры. Используйте телефон с Chrome или USB-сканер.'; return; }
    try {
      const detector = new window.BarcodeDetector({ formats: ['qr_code'] });
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
      video.srcObject = stream; video.classList.remove('hidden'); await video.play(); camBtn.textContent = 'Выключить камеру';
      camNote.textContent = 'Изображение с камеры никуда не отправляется, распознаётся только код.';
      loop = setInterval(async () => {
        if (busy || video.readyState < 2) return;
        try { const codes = await detector.detect(video); const v = codes.find((x) => x.rawValue && x.rawValue.startsWith('KSPA1:')); if (v) lookup(v.rawValue); } catch (_) { /* frame skipped */ }
      }, 300);
    } catch (e) { camNote.textContent = 'Нет доступа к камере: ' + (e.name === 'NotAllowedError' ? 'разрешите доступ в браузере' : e.message); stopCam(); }
  });
  main.replaceChildren(h('h1', {}, 'Сканер QR'), h('div', { class: 'grid two' },
    h('div', { class: 'card stack scanner' }, h('p', { class: 'muted' }, 'Клиент открывает QR-код в приложении (код действует 2 минуты). Отсканируйте его USB-сканером или камерой.'),
      input, h('div', { class: 'row' }, camBtn), camNote, video), result));
  input.focus();
}

/* ------------------------------------------------------------- catalogue pages */
async function pageServices(main) {
  const { services } = await refs(true);
  const reload = () => { refs(true); go('services'); };
  main.replaceChildren(h('div', { class: 'row between' }, h('h1', {}, 'Услуги'), h('button', { class: 'btn primary', onclick: () => editService(null, reload) }, '+ Услуга')),
    ...services.map((s) => h('div', { class: 'card stack' },
      h('div', { class: 'row between' }, h('h2', {}, s.name_ru, ' ', s.active ? null : h('span', { class: 'badge closed' }, 'скрыта')), h('button', { class: 'btn small', onclick: () => editService(s, reload) }, 'Изменить')),
      h('div', { class: 'muted small' }, `${s.duration_min} мин · код ${s.code}`, s.name_uz ? ` · ${s.name_uz}` : ''),
      h('div', {}, s.description_ru || h('span', { class: 'muted' }, 'Нет описания')),
      h('div', { class: 'small muted' }, 'Специалисты: ', s.specialists.map((p) => p.full_name).join(', ') || '—'),
      h('div', { class: 'photos' }, s.photos.map((pid) => h('div', { class: 'photo' }, h('img', { src: '/api/photos/' + pid, alt: '' }),
        h('button', { class: 'btn small danger', onclick: () => modal('Удалить фото?', h('p', {}, 'Фото будет удалено из каталога.'), { okText: 'Удалить', danger: true, onOk: async () => { await api('DELETE', '/photos/' + pid); reload(); } }) }, '×'))),
      uploadButton(s.id, reload)))));
}
function uploadButton(serviceId, done) {
  const input = h('input', { type: 'file', accept: 'image/jpeg,image/png,image/webp', class: 'hidden' });
  input.addEventListener('change', async () => {
    const file = input.files[0]; if (!file) return;
    if (file.size > 2 * 1024 * 1024) { toast('Фото больше 2 МБ', true); return; }
    const data = await new Promise((res) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(',')[1]); r.readAsDataURL(file); });
    await guard(() => api('POST', `/services/${serviceId}/photos`, { content_type: file.type, data }), 'Фото добавлено'); done();
  });
  return h('div', {}, input, h('button', { class: 'btn small', onclick: () => input.click() }, '+ Фото (без лиц детей)'));
}
function editService(s, done) {
  modal(s ? 'Услуга' : 'Новая услуга', h('div', { class: 'stack' },
    s ? null : field('Код (латиница) *', h('input', { name: 'code', required: true, pattern: '[a-z][a-z0-9_]{1,30}' })),
    h('div', { class: 'row' }, field('Название (RU) *', h('input', { name: 'name_ru', value: s ? s.name_ru : '', required: true })), field('Название (UZ)', h('input', { name: 'name_uz', value: s ? s.name_uz : '' }))),
    field('Описание (RU)', h('textarea', { name: 'description_ru' }, s ? s.description_ru : '')),
    field('Описание (UZ)', h('textarea', { name: 'description_uz' }, s ? s.description_uz : '')),
    h('div', { class: 'row' }, field('Длительность, мин *', h('input', { name: 'duration_min', type: 'number', min: 5, max: 240, value: s ? s.duration_min : 30, required: true })),
      field('Порядок', h('input', { name: 'sort', type: 'number', value: s ? s.sort : 0 }))),
    h('label', { class: 'check' }, h('input', { type: 'checkbox', name: 'active', checked: s ? s.active : true }), 'Показывать клиентам')),
  { onOk: async (f) => {
    const d = readForm(f); d.duration_min = Number(d.duration_min); d.sort = Number(d.sort || 0);
    if (s) await api('PATCH', '/services/' + s.id, d); else await api('POST', '/services', d);
    toast('Сохранено'); done();
  } });
}
async function pageSpecialists(main) {
  const { specialists, services } = await refs(true);
  const reload = () => go('specialists');
  main.replaceChildren(h('div', { class: 'row between' }, h('h1', {}, 'Специалисты'), h('button', { class: 'btn primary', onclick: () => editSpecialist(null, services, reload) }, '+ Специалист')),
    h('div', { class: 'card' }, specialists.length ? h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, 'Имя'), h('th', {}, 'Телефон'), h('th', {}, 'Услуги'), h('th', {}, ''))),
      h('tbody', {}, specialists.map((p) => h('tr', {}, h('td', {}, h('b', {}, p.full_name), p.active ? null : h('span', { class: 'badge closed' }, ' неактивен'), p.bio ? h('div', { class: 'small muted' }, p.bio) : null),
        h('td', {}, p.phone || '—'), h('td', {}, services.filter((s) => p.service_ids.includes(s.id)).map((s) => s.name_ru).join(', ') || '—'),
        h('td', {}, h('button', { class: 'btn small', onclick: () => editSpecialist(p, services, reload) }, 'Изменить'))))))) : h('div', { class: 'empty' }, 'Специалистов пока нет')));
}
function editSpecialist(p, services, done) {
  modal(p ? 'Специалист' : 'Новый специалист', h('div', { class: 'stack' },
    field('Имя *', h('input', { name: 'full_name', value: p ? p.full_name : '', required: true })),
    field('Телефон (виден только сотрудникам)', h('input', { name: 'phone', value: p ? p.phone : '' })),
    field('О специалисте (видно клиентам)', h('textarea', { name: 'bio' }, p ? p.bio : '')),
    h('div', {}, h('div', { class: 'muted small' }, 'Услуги'), services.map((s) => h('label', { class: 'check' }, h('input', { type: 'checkbox', 'data-svc': s.id, checked: p ? p.service_ids.includes(s.id) : false }), s.name_ru))),
    p ? h('label', { class: 'check' }, h('input', { type: 'checkbox', name: 'active', checked: p.active }), 'Работает') : null),
  { onOk: async (f) => {
    const d = readForm(f);
    d.service_ids = [...f.querySelectorAll('[data-svc]')].filter((x) => x.checked).map((x) => Number(x.dataset.svc));
    if (p) await api('PATCH', '/specialists/' + p.id, d); else await api('POST', '/specialists', d);
    toast('Сохранено'); refs(true); done();
  } });
}
async function pagePlans(main) {
  const { plans, services } = await refs(true);
  const reload = () => go('plans');
  main.replaceChildren(h('div', { class: 'row between' }, h('h1', {}, 'Тарифы'), h('button', { class: 'btn primary', onclick: () => editPlan(null, services, reload) }, '+ Тариф')),
    h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, 'Название'), h('th', {}, 'Состав'), h('th', {}, 'Срок'), h('th', {}, 'Цена'), h('th', {}, ''))),
      h('tbody', {}, plans.map((p) => h('tr', {}, h('td', {}, h('b', {}, p.name), p.active ? null : h('span', { class: 'badge closed' }, ' архив')),
        h('td', {}, p.items.map((i) => `${i.visits} × ${i.name_ru}`).join(', ')), h('td', {}, p.validity_days, ' дн.'), h('td', {}, fmtMoney(p.price)),
        h('td', {}, h('button', { class: 'btn small', onclick: () => editPlan(p, services, reload) }, 'Изменить')))))))));
}
function editPlan(p, services, done) {
  const visits = (sid) => { const it = p && p.items.find((i) => i.service_id === sid); return it ? it.visits : ''; };
  modal(p ? 'Тариф' : 'Новый тариф', h('div', { class: 'stack' },
    field('Название *', h('input', { name: 'name', value: p ? p.name : '', required: true })),
    h('div', { class: 'row' }, field('Срок действия, дней *', h('input', { name: 'validity_days', type: 'number', min: 1, max: 730, value: p ? p.validity_days : 30, required: true })),
      field('Цена, сум', h('input', { name: 'price', type: 'number', min: 0, step: '0.01', value: p ? p.price : 0 }))),
    h('div', { class: 'muted small' }, 'Количество посещений по услугам (пусто — не входит):'),
    services.map((s) => h('div', { class: 'row' }, h('span', {}, s.name_ru), h('input', { type: 'number', min: 1, max: 500, 'data-plan-svc': s.id, value: visits(s.id), class: 'right' }))),
    p ? h('label', { class: 'check' }, h('input', { type: 'checkbox', name: 'active', checked: p.active }), 'Продаётся') : null,
    h('p', { class: 'small muted' }, 'Изменение тарифа не меняет уже оформленные абонементы.')),
  { onOk: async (f) => {
    const d = readForm(f);
    d.validity_days = Number(d.validity_days); d.price = d.price || '0';
    d.items = [...f.querySelectorAll('[data-plan-svc]')].filter((x) => x.value).map((x) => ({ service_id: Number(x.dataset.planSvc), visits: Number(x.value) }));
    if (p) await api('PATCH', '/plans/' + p.id, d); else await api('POST', '/plans', d);
    toast('Сохранено'); done();
  } });
}

/* ------------------------------------------------------------- reports, staff, audit */
async function pageReports(main) {
  const from = h('input', { type: 'date', value: state.cache.rFrom || todayISO().slice(0, 8) + '01' });
  const to = h('input', { type: 'date', value: state.cache.rTo || todayISO() });
  const box = h('div', {});
  const hbars = (rows, key) => {
    const max = Math.max(1, ...rows.map((r) => Number(r[key])));
    return rows.length ? rows.map((r) => { const i = h('i'); i.style.width = Math.round(100 * Number(r[key]) / max) + '%'; return h('div', { class: 'hbar' }, h('span', {}, r.name), h('div', { class: 'track' }, i), h('b', {}, r[key])); }) : h('div', { class: 'empty' }, 'Нет данных');
  };
  const load = async () => {
    state.cache.rFrom = from.value; state.cache.rTo = to.value;
    const r = await api('GET', `/reports?from=${from.value}&to=${to.value}`);
    const total = r.by_service.reduce((a, x) => a + Number(x.visits), 0);
    const maxDay = Math.max(1, ...r.by_day.map((d) => d.visits));
    box.replaceChildren(
      h('div', { class: 'grid stats' }, stat(total, 'посещений за период'), stat(r.sold.count, 'абонементов продано'), stat(fmtMoney(r.sold.revenue), 'продано на сумму'),
        stat(fmtMoney(r.received.total), 'получено в кассу'), stat(fmtMoney(r.debt_total), 'общий долг клиентов')),
      h('div', { class: 'card' }, h('h2', {}, 'Касса по способам оплаты'), hbars(Object.entries(METHODS).map(([k, v]) => ({ name: v, amount: Number(r.received.by_method[k]) })), 'amount')),
      h('div', { class: 'grid two' },
        h('div', { class: 'card' }, h('h2', {}, 'По услугам'), hbars(r.by_service, 'visits')),
        h('div', { class: 'card' }, h('h2', {}, 'По специалистам'), hbars(r.by_specialist, 'visits')),
        h('div', { class: 'card' }, h('h2', {}, 'По дням'), r.by_day.length ? h('div', { class: 'chart' }, r.by_day.map((d) => { const b = h('div', { title: `${fmtDate(d.day)}: ${d.visits}` }); b.style.height = Math.round(100 * d.visits / maxDay) + '%'; return b; })) : h('div', { class: 'empty' }, 'Нет данных')),
        h('div', { class: 'card' }, h('h2', {}, 'Продажи по тарифам'), r.sold_by_plan.length ? h('table', {}, h('tbody', {}, r.sold_by_plan.map((p) => h('tr', {}, h('td', {}, p.name), h('td', { class: 'num' }, p.count, ' шт.'), h('td', { class: 'num' }, fmtMoney(p.revenue)))))) : h('div', { class: 'empty' }, 'Нет продаж'))));
  };
  [from, to].forEach((el) => el.addEventListener('change', () => guard(load)));
  main.replaceChildren(h('h1', {}, 'Отчёты'), h('div', { class: 'card row' }, field('С', from), field('По', to)), box);
  await load();
}
async function pageStaff(main) {
  const rows = await api('GET', '/staff');
  const reload = () => go('staff');
  main.replaceChildren(h('div', { class: 'row between' }, h('h1', {}, 'Сотрудники'), h('button', { class: 'btn primary', onclick: () => newStaff(reload) }, '+ Сотрудник')),
    h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, 'Имя'), h('th', {}, 'Логин'), h('th', {}, 'Роль'), h('th', {}, 'Статус'), h('th', {}, ''))),
      h('tbody', {}, rows.map((u) => h('tr', {}, h('td', {}, h('b', {}, u.full_name)), h('td', { class: 'mono' }, u.login), h('td', {}, u.role === 'superadmin' ? 'Главный админ' : 'Администратор'),
        h('td', {}, u.enabled ? h('span', { class: 'badge active' }, 'активен') : h('span', { class: 'badge bad' }, 'отключён')),
        h('td', { class: 'row' }, h('button', { class: 'btn small', onclick: async () => { const r = await guard(() => api('POST', `/staff/${u.id}/reset-password`)); showSecret('Новый пароль сотрудника', u.login, r.password, 'Передайте новый пароль сотруднику. Старые сессии закрыты.'); } }, 'Сбросить пароль'),
          u.id !== state.me.id ? h('button', { class: 'btn small' + (u.enabled ? ' danger' : ''), onclick: () => guard(async () => { await api('PATCH', '/staff/' + u.id, { enabled: !u.enabled }); reload(); }, 'Сохранено') }, u.enabled ? 'Отключить' : 'Включить') : null))))))));
}
function newStaff(done) {
  modal('Новый сотрудник', h('div', { class: 'stack' },
    field('Имя *', h('input', { name: 'full_name', required: true })),
    field('Логин *', h('input', { name: 'login', required: true, pattern: '[a-z0-9][a-z0-9_.\\-]{2,63}', autocapitalize: 'none' })),
    field('Роль', h('select', { name: 'role' }, h('option', { value: 'admin' }, 'Администратор (ресепшен)'), h('option', { value: 'superadmin' }, 'Главный администратор')))),
  { okText: 'Создать', onOk: async (f) => { const d = readForm(f); const r = await api('POST', '/staff', d); done(); setTimeout(() => showSecret('Сотрудник создан', r.login, r.password, 'Передайте данные сотруднику, пароль показывается один раз.'), 50); } });
}
async function pageAudit(main) {
  const rows = await api('GET', '/audit?limit=300');
  const details = (e) => (e.details && Object.keys(e.details).length
    ? h('details', {}, h('summary', {}, e.details.reason || 'подробнее'), h('pre', { class: 'json' }, JSON.stringify(e.details, null, 1)))
    : '');
  const body = rows.map((e) => h('tr', {},
    h('td', { class: 'small' }, fmtDateTime(e.at)),
    h('td', { class: 'small' }, e.actor || 'система'),
    h('td', {}, ACTIONS[e.action] || e.action, h('div', { class: 'small muted' }, e.entity, ' #', e.entity_id)),
    h('td', {}, details(e))));
  const head = h('thead', {}, h('tr', {}, h('th', {}, 'Когда'), h('th', {}, 'Кто'), h('th', {}, 'Действие'), h('th', {}, 'Детали')));
  main.replaceChildren(h('h1', {}, 'Журнал действий'), h('div', { class: 'card' },
    h('p', { class: 'muted small' }, 'Записи журнала нельзя изменить или удалить.'),
    h('div', { class: 'table-wrap' }, h('table', {}, head, h('tbody', {}, body)))));
}

/* ------------------------------------------------------------- boot */
window.addEventListener('hashchange', () => {
  if (!state.me || location.hash.slice(1) === state.key) return;
  const [page, arg] = location.hash.slice(1).split('/');
  if (page === 'client' && arg) go('client', arg);
  else if (PAGES.some((p) => p[0] === page)) go(page);
});
if (state.token) start(); else renderLogin();
