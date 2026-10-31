'use strict';
(() => {
  const ru = {
    center:'Детский оздоровительный центр',welcomeLabel:'ПРОСТРАНСТВО ЗАБОТЫ',welcome:'Больше внимания детям.\nМеньше рутины.',welcomeText:'Клиенты, абонементы и посещения — в одном спокойном рабочем пространстве.',care:'Всё важное для вашей команды',signIn:'Добро пожаловать',signInText:'Войдите в панель администратора',login:'Логин',password:'Пароль',enter:'Войти в панель →',issued:'Доступ выдаётся администратором центра. Самостоятельной регистрации нет.',workspace:'РАБОЧЕЕ ПРОСТРАНСТВО',overview:'Обзор',clients:'Клиенты',subscriptions:'Абонементы',bookings:'Записи',history:'История',team:'Команда Kinder Spa',logout:'Выйти',refresh:'↻ Обновить',todayLabel:'КАЖДЫЙ СЕАНС ИМЕЕТ ЗНАЧЕНИЕ',hero:'Всё под рукой.\nВсё в порядке.',heroText:'Следите за посещениями и помогайте семьям планировать заботу о детях.',openBookings:'Перейти к записям →',loaded:'в загруженной выборке',poolRule:'Бассейн · 45 минут',poolTime:'5 минут на переодевание и 40 минут плавания.',cancelRule:'Отмена до 19:00',cancelTime:'Предыдущего дня. При поздней отмене сеанс сгорает.',hoursRule:'Пн–сб · 09:00–19:00',hoursText:'Воскресенье — выходной. Время центра: Ташкент.',clientList:'Клиенты центра',staffOnly:'Для команды',more:'Загрузить ещё',newClient:'Новый клиент',newClientText:'Выдайте семье логин и начальный пароль.',initialPassword:'Начальный пароль',passwordHint:'Не менее 12 символов. Передайте пароль семье лично.',createClient:'Создать клиента',newSubscription:'Выдать абонемент',client:'Клиент',service:'Услуга',pool:'Бассейн',massage:'Детский массаж',hydromassage:'Гидромассаж',sessions:'Сеансов',issue:'Выдать абонемент',visitList:'Записи и посещения',newBooking:'Новая запись',subscription:'Абонемент и услуга',startsAt:'Дата и время · Ташкент',duration:'Продолжительность, минут',durationHint:'Бассейн — 45 минут. Для массажа укажите согласованную длительность.',book:'Сохранить запись',auditTitle:'История действий',audited:'Сохранено в журнале',back:'Назад',confirm:'Подтвердить',empty:'Записей пока нет.',choose:'Выберите…',admin:'Администратор',superadmin:'Суперадминистратор',active:'Доступ открыт',disabled:'Доступ закрыт',remaining:'Осталось',reserved:'Записан',consumed:'Посещение учтено',cancelled:'Отменён с возвратом',forfeited:'Сеанс списан',no_show:'Неявка',restored:'Сеанс восстановлен',cancel:'Отменить запись',restore:'Восстановить',redeem:'Отметить визит',reset:'Сбросить пароль',reason:'Причина восстановления',reasonHint:'Укажите причину. Не добавляйте медицинские сведения и личные данные ребёнка.',qr:'Код из QR клиента',qrHint:'Введите полный одноразовый код из QR клиента. Он действителен только во время сеанса.',scanQr:'Сканировать QR камерой',scanReady:'Наведите камеру на QR-код. После сканирования подтвердите посещение.',scanUnsupported:'Камера или сканирование QR недоступны. Введите код вручную.',scanFailed:'Нет доступа к камере или сканирование завершено. Введите код вручную.',scanAccepted:'QR-код считан. Подтвердите посещение.',resetHint:'Все сессии клиента будут завершены. Передайте новый пароль семье лично.',cancelHint:'Для бассейна возврат возможен строго до 19:00 предыдущего дня. При поздней отмене сеанс сгорит.',noShowHint:'Отметка доступна после окончания сеанса бассейна.',created:'Клиент создан.',issuedOk:'Абонемент выдан.',booked:'Запись сохранена.',actionOk:'Изменение сохранено.',restoredOk:'Сеанс восстановлен. Запрос уведомления сохранён в очереди.',queue:'Уведомление в очереди · доставка ещё не подтверждена',actor:'Сотрудник',object:'Запись',reasonLabel:'Причина',authError:'Проверьте логин и пароль. Доступ должен быть выдан сотруднику.',staffRequired:'Эта панель доступна только администраторам.',rate:'Слишком много попыток входа. Повторите через 10 минут.',network:'Нет подтверждения от сервера. Результат операции пока неизвестен.',unknownWrite:'Ответ не получен. Проверьте список или историю. Для учётной операции можно повторить тот же запрос, не меняя поля.',unknownCredentials:'Результат неизвестен. Проверьте клиента или вход с новым паролем перед повторной операцией. Эта форма заблокирована до нового входа.',pendingChanged:'Сначала проверьте предыдущую операцию. Для повтора сохраните прежние поля.',rejected:'Операция не принята. Проверьте данные, права, баланс и время сеанса.',expired:'Сессия завершена. Войдите снова.',savedButReadFailed:'Изменение сохранено, но обновить списки не удалось. Нажмите «Обновить».',refreshed:'Данные обновлены.',loadFailed:'Не удалось загрузить часть данных. Повторите обновление.',localExit:'Вы вышли на этом устройстве. Завершение серверной сессии не подтверждено.',unsafeId:'Эту запись нельзя безопасно обработать в панели.',maxRows:'Загружено 500 записей. Дальнейшая выборка в этой вкладке ограничена.',loginEvent:'Вход сотрудника',logoutEvent:'Выход',create_client_login:'Выдан логин клиента',create_client:'Создан клиент',issue_subscription:'Выдан абонемент',reset_client_password:'Сброшен пароль клиента',bookEvent:'Создана запись',restore_pool:'Восстановлен сеанс',cancel_pool:'Отменена запись',mark_no_show:'Отмечена неявка',redeemEvent:'Учтено посещение',issue_qr:'Выдан одноразовый QR',operator_bootstrap:'Настроен первый суперадминистратор'
  };
  const uz = {
    center:'Bolalar sog‘lomlashtirish markazi',welcomeLabel:'G‘AMXO‘RLIK MASKANI',welcome:'Bolalarga ko‘proq e’tibor.\nKamroq kundalik ish.',welcomeText:'Mijozlar, abonementlar va tashriflar — barchasi bir ish maydonida.',care:'Jamoangiz uchun barcha muhim ma’lumotlar',signIn:'Xush kelibsiz',signInText:'Administrator paneliga kiring',login:'Login',password:'Parol',enter:'Panelga kirish →',issued:'Kirish ma’lumotlarini markaz administratori beradi. Mustaqil ro‘yxatdan o‘tish yo‘q.',workspace:'ISH MAYDONI',overview:'Umumiy',clients:'Mijozlar',subscriptions:'Abonementlar',bookings:'Yozuvlar',history:'Tarix',team:'Kinder Spa jamoasi',logout:'Chiqish',refresh:'↻ Yangilash',todayLabel:'HAR BIR SEANS MUHIM',hero:'Barchasi qo‘l ostida.\nBarchasi tartibda.',heroText:'Tashriflarni kuzating va oilalarga bolalar parvarishini rejalashtirishda yordam bering.',openBookings:'Yozuvlarga o‘tish →',loaded:'yuklangan tanlovda',poolRule:'Basseyn · 45 daqiqa',poolTime:'Kiyinish uchun 5 daqiqa, suzish uchun 40 daqiqa.',cancelRule:'Soat 19:00 gacha bekor qilish',cancelTime:'Oldingi kuni. Kech bekor qilinsa, seans hisobdan chiqariladi.',hoursRule:'Du–Shan · 09:00–19:00',hoursText:'Yakshanba — dam olish. Markaz vaqti: Toshkent.',clientList:'Markaz mijozlari',staffOnly:'Jamoa uchun',more:'Yana yuklash',newClient:'Yangi mijoz',newClientText:'Oilaga login va boshlang‘ich parol bering.',initialPassword:'Boshlang‘ich parol',passwordHint:'Kamida 12 belgi. Parolni oilaga shaxsan yetkazing.',createClient:'Mijoz yaratish',newSubscription:'Abonement berish',client:'Mijoz',service:'Xizmat',pool:'Basseyn',massage:'Bolalar massaji',hydromassage:'Gidromassaj',sessions:'Seanslar',issue:'Abonement berish',visitList:'Yozuvlar va tashriflar',newBooking:'Yangi yozuv',subscription:'Abonement va xizmat',startsAt:'Sana va vaqt · Toshkent',duration:'Davomiyligi, daqiqa',durationHint:'Basseyn — 45 daqiqa. Massaj uchun kelishilgan davomiylikni kiriting.',book:'Yozuvni saqlash',auditTitle:'Harakatlar tarixi',audited:'Jurnalda saqlangan',back:'Orqaga',confirm:'Tasdiqlash',empty:'Hozircha yozuvlar yo‘q.',choose:'Tanlang…',admin:'Administrator',superadmin:'Superadministrator',active:'Kirish ochiq',disabled:'Kirish yopiq',remaining:'Qoldiq',reserved:'Yozilgan',consumed:'Tashrif hisobga olindi',cancelled:'Qaytarib bekor qilindi',forfeited:'Seans hisobdan chiqarildi',no_show:'Kelmagan',restored:'Seans tiklandi',cancel:'Yozuvni bekor qilish',restore:'Tiklash',redeem:'Tashrifni belgilash',reset:'Parolni yangilash',reason:'Tiklash sababi',reasonHint:'Sababni yozing. Bolaning tibbiy yoki shaxsiy ma’lumotlarini kiritmang.',qr:'Mijoz QR kodi',qrHint:'Mijoz QR kodidagi to‘liq bir martalik kodni kiriting. U faqat seans vaqtida amal qiladi.',scanQr:'QR kodni kamera bilan skanerlash',scanReady:'Kamerani QR kodga qarating. Skanerdan keyin tashrifni tasdiqlang.',scanUnsupported:'Kamera yoki QR skaner mavjud emas. Kodni qo‘lda kiriting.',scanFailed:'Kamera ishlamayapti yoki skanerlash to‘xtadi. Kodni qo‘lda kiriting.',scanAccepted:'QR kod o‘qildi. Tashrifni tasdiqlang.',resetHint:'Mijozning barcha sessiyalari tugatiladi. Yangi parolni oilaga shaxsan yetkazing.',cancelHint:'Basseyn seansi faqat oldingi kuni soat 19:00 dan oldin qaytariladi. Kech bekor qilinsa, seans hisobdan chiqariladi.',noShowHint:'Basseyn seansi tugagandan keyin belgilash mumkin.',created:'Mijoz yaratildi.',issuedOk:'Abonement berildi.',booked:'Yozuv saqlandi.',actionOk:'O‘zgarish saqlandi.',restoredOk:'Seans tiklandi. Xabarnoma so‘rovi navbatga saqlandi.',queue:'Xabarnoma navbatda · yetkazilishi hali tasdiqlanmagan',actor:'Xodim',object:'Yozuv',reasonLabel:'Sabab',authError:'Login va parolni tekshiring. Kirish xodimga berilgan bo‘lishi kerak.',staffRequired:'Bu panel faqat administratorlar uchun.',rate:'Kirish urinishlari ko‘p. 10 daqiqadan keyin takrorlang.',network:'Server tasdig‘i olinmadi. Amal natijasi hozircha noma’lum.',unknownWrite:'Javob olinmadi. Ro‘yxat yoki tarixni tekshiring. Hisob amalini maydonlarni o‘zgartirmasdan qayta yuborish mumkin.',unknownCredentials:'Natija noma’lum. Qayta urinishdan oldin mijozni yoki yangi parol bilan kirishni tekshiring. Forma qayta kirguncha bloklangan.',pendingChanged:'Avval oldingi amalni tekshiring. Qayta yuborish uchun oldingi maydonlarni saqlang.',rejected:'Amal qabul qilinmadi. Ma’lumot, huquq, qoldiq va seans vaqtini tekshiring.',expired:'Sessiya tugadi. Qayta kiring.',savedButReadFailed:'O‘zgarish saqlandi, lekin ro‘yxatlar yangilanmadi. Yangilashni bosing.',refreshed:'Ma’lumotlar yangilandi.',loadFailed:'Ma’lumotlarning bir qismi yuklanmadi. Yangilashni takrorlang.',localExit:'Ushbu qurilmadan chiqdingiz. Server sessiyasi tugashi tasdiqlanmadi.',unsafeId:'Bu yozuvni panelda xavfsiz qayta ishlash imkoni yo‘q.',maxRows:'500 ta yozuv yuklandi. Bu oynada keyingi yuklash cheklangan.',loginEvent:'Xodim kirdi',logoutEvent:'Chiqish',create_client_login:'Mijozga login berildi',create_client:'Mijoz yaratildi',issue_subscription:'Abonement berildi',reset_client_password:'Mijoz paroli yangilandi',bookEvent:'Yozuv yaratildi',restore_pool:'Seans tiklandi',cancel_pool:'Yozuv bekor qilindi',mark_no_show:'Kelmagan deb belgilandi',redeemEvent:'Tashrif hisobga olindi',issue_qr:'Bir martalik QR berildi',operator_bootstrap:'Birinchi superadministrator sozlandi'
  };
  let lang = 'ru', token = '', generation = 0, tab = 'overview', action = null;
  let scanStream = null, scanTimer = null, scanGeneration = 0;
  let records = {clients:null,subscriptions:null,bookings:null,audit:null};
  const pending = new Map(), $ = (id) => document.getElementById(id), t = (key) => (lang === 'uz' ? uz : ru)[key] || key;
  class Stale extends Error {}
  class RequestError extends Error { constructor(code, uncertain=false) {super(code); this.uncertain=uncertain;} }
  const id = (n) => { if(!Number.isSafeInteger(n) || n < 1) throw new RequestError('unsafeId'); return n; };
  const node = (tag,text,cls) => { const n=document.createElement(tag); if(text!==undefined)n.textContent=String(text); if(cls)n.className=cls; return n; };
  const values = (form) => Object.fromEntries([...form.elements].filter(e=>e.name).map(e=>[e.name,e.value]));
  const date = (at) => {const parts=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23',timeZone:'Asia/Tashkent'}).formatToParts(new Date(at)).map(p=>[p.type,p.value]));return parts.day+'.'+parts.month+'.'+parts.year+', '+parts.hour+':'+parts.minute;};
  const notice = (key,error=false) => { $('notice').textContent=t(key); $('notice').classList.toggle('error',error); };

  function scanStatus(key) {
    $('qr-scan-status').dataset.scanStatus = key || '';
    $('qr-scan-status').textContent = key ? t(key) : '';
  }
  function stopScanner() {
    scanGeneration++;
    if (scanTimer !== null) { clearTimeout(scanTimer); scanTimer = null; }
    if (scanStream) {
      for (const track of scanStream.getTracks()) track.stop();
      scanStream = null;
    }
    const video = $('qr-scan-video');
    video.pause();
    video.srcObject = null;
    video.hidden = true;
    $('start-qr-scan').disabled = false;
  }
  async function startScanner() {
    const supported = window.isSecureContext && typeof window.BarcodeDetector === 'function'
      && !!navigator.mediaDevices?.getUserMedia;
    if (!supported || action?.kind !== 'redeem' || !$('action-dialog').open || scanStream) {
      if (!supported) scanStatus('scanUnsupported');
      return;
    }
    const epoch = ++scanGeneration;
    $('start-qr-scan').disabled = true;
    scanStatus('');
    try {
      const detector = new window.BarcodeDetector({formats:['qr_code']});
      const stream = await navigator.mediaDevices.getUserMedia({
        audio:false, video:{facingMode:{ideal:'environment'}}
      });
      if (epoch !== scanGeneration || !$('action-dialog').open || action?.kind !== 'redeem') {
        for (const track of stream.getTracks()) track.stop();
        return;
      }
      scanStream = stream;
      const video = $('qr-scan-video');
      video.srcObject = stream;
      video.hidden = false;
      await video.play();
      if (epoch !== scanGeneration) return;
      scanStatus('scanReady');
      async function detect() {
        if (epoch !== scanGeneration || !$('action-dialog').open) return;
        try {
          const results = await detector.detect(video);
          if (epoch !== scanGeneration) return;
          const raw = results.find(item => typeof item.rawValue === 'string'
            && /^[A-Za-z0-9_-]{43}$/.test(item.rawValue))?.rawValue;
          if (raw) {
            stopScanner();
            $('action-input').value = raw;
            $('action-input').dispatchEvent(new Event('input',{bubbles:true}));
            scanStatus('scanAccepted');
            return;
          }
        } catch {
          if (epoch === scanGeneration) { stopScanner(); scanStatus('scanFailed'); }
          return;
        }
        if (epoch === scanGeneration) scanTimer = setTimeout(detect, 180);
      }
      await detect();
    } catch {
      if (epoch === scanGeneration) { stopScanner(); scanStatus('scanFailed'); }
    } finally {
      if (epoch === scanGeneration && !scanStream) $('start-qr-scan').disabled = false;
    }
  }

  function busy(form,state){form.querySelector('button[type=submit],button.primary').disabled=state;}
  function lock(form,state){for(const e of form.elements)if(e.tagName!=='BUTTON')e.disabled=state;}
  function clearSession(){stopScanner();generation++;token='';records={clients:null,subscriptions:null,bookings:null,audit:null};pending.clear();action=null;$('action-dialog').close();$('workspace').hidden=true;$('login-page').hidden=false;$('logout').hidden=true;for(const form of document.forms){form.reset();lock(form,false);for(const b of form.querySelectorAll('button'))b.disabled=false;}for(const key of Object.keys(records))$(key+'-list').replaceChildren();$('notice').textContent='';$('identity').textContent='';delete $('identity').dataset.role;delete $('identity').dataset.account;for(const name of ['clients','subscriptions','bookings'])$('count-'+name).textContent='—';$('subscription-form').elements.client_id.replaceChildren();$('booking-form').elements.allowance.replaceChildren();for(const name of ['action-title','action-copy','action-error'])$(name).textContent='';}
  async function api(path,body){
    const epoch=generation, current=token, controller=new AbortController(), timer=setTimeout(()=>controller.abort(),12000);
    try {
      const headers={};if(current)headers.Authorization='Bearer '+current;if(body!==undefined)headers['Content-Type']='application/json';
      const response=await fetch(path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body),credentials:'omit',cache:'no-store',redirect:'error',mode:'same-origin',signal:controller.signal});
      const raw=await response.text();if(epoch!==generation)throw new Stale();
      if(raw.length>100000)throw new RequestError('network',true);
      let result;try{result=JSON.parse(raw);}catch{throw new RequestError('network',true);}
      if(response.status===401){clearSession();$('login-message').textContent=t('expired');throw new Stale();}
      if(!response.ok)throw new RequestError(response.status===429?'rate':response.status>=500?'network':'rejected',response.status>=500);
      return result;
    } catch(e){if(e instanceof Stale || e instanceof RequestError)throw e;if(epoch!==generation)throw new Stale();throw new RequestError('network',true);}finally{clearTimeout(timer);}
  }
  function choose(select,options){const previous=select.value;select.replaceChildren(node('option',t('choose')));select.firstChild.value='';for(const [value,label] of options){const o=node('option',label);o.value=value;select.append(o);}if([...select.options].some(o=>o.value===previous))select.value=previous;}
  function quotaOptions(){const f=$('subscription-form'), category=f.elements.category.value, old=f.elements.quota.value;f.elements.quota.replaceChildren(...(category==='pool'?[4,8,12]:[10]).map(n=>{const o=node('option',n);o.value=n;return o;}));if([...f.elements.quota.options].some(o=>o.value===old))f.elements.quota.value=old;}
  function minutes(){const f=$('booking-form'), category=f.elements.allowance.value.split(':')[1];f.elements.minutes.readOnly=category==='pool';if(category==='pool')f.elements.minutes.value='45';else if(!f.elements.minutes.disabled)f.elements.minutes.value='';}
  function selections(){choose($('subscription-form').elements.client_id,(records.clients||[]).filter(c=>c.enabled).map(c=>[id(c.client_id),c.login+' · #'+c.client_id]));choose($('booking-form').elements.allowance,(records.subscriptions||[]).flatMap(s=>s.allowances.filter(a=>a.remaining>0).map(a=>[id(s.subscription_id)+':'+a.category,'#'+s.subscription_id+' · '+t(a.category)+' · '+t('remaining')+' '+a.remaining])));quotaOptions();}
  function button(label,callback,danger=false){const b=node('button',t(label),'secondary'+(danger?' danger':''));b.type='button';b.addEventListener('click',callback);return b;}
  function render(){
    for(const name of ['clients','subscriptions','bookings'])$('count-'+name).textContent=records[name]===null?'—':String(records[name].length);
    for(const name of Object.keys(records)){
      const list=$(name+'-list');list.replaceChildren();const rows=records[name];
      document.querySelector('[data-more="'+name+'"]').hidden=!rows || rows.length===0 || rows.length%50!==0 || rows.length>=500;
      if(!rows || !rows.length){list.append(node('p',rows===null?t('loadFailed'):t('empty'),'empty'));continue;}
      for(const row of rows){
        const card=node('article',undefined,'record');
        if(name==='clients'){id(row.client_id);card.append(node('strong',row.login),node('p','#'+row.client_id+' · '+t(row.enabled?'active':'disabled')));const actions=node('div',undefined,'actions');actions.append(button('reset',()=>openAction('reset',row.client_id)));card.append(actions);}
        if(name==='subscriptions'){id(row.subscription_id);card.append(node('strong','#'+row.subscription_id+' · '+t('client')+' #'+id(row.client_id)));const balances=node('div');for(const a of row.allowances){const b=node('span',t(a.category)+' ','balance');b.append(node('b',a.remaining+' / '+a.quota));balances.append(b);}card.append(balances);}
        if(name==='bookings'){id(row.booking_id);card.append(node('strong',t(row.category)+' · #'+row.booking_id),node('p',date(row.starts_at)+' · '+t('subscription')+' #'+id(row.subscription_id)),node('span',t(row.state),'state'));const actions=node('div',undefined,'actions');if(row.state==='reserved'){actions.append(button('redeem',()=>openAction('redeem',row.booking_id)));if(row.category==='pool'){actions.append(button('cancel',()=>openAction('cancel',row.booking_id),true));if(new Date(row.ends_at).getTime()<=Date.now())actions.append(button('no_show',()=>openAction('no-show',row.booking_id)));}}if(row.category==='pool' && ['forfeited','no_show'].includes(row.state))actions.append(button('restore',()=>openAction('restore',row.booking_id)));card.append(actions);}
        if(name==='audit'){id(row.event_id);const key={login:'loginEvent',logout:'logoutEvent',book:'bookEvent',redeem:'redeemEvent'}[row.operation]||row.operation;card.append(node('strong',t(key)),node('p',date(row.at)+' · '+t('actor')+' #'+id(row.actor_id)+' · '+t('object')+' #'+id(row.entity_id)));if(row.details && typeof row.details.reason==='string')card.append(node('p',t('reasonLabel')+': '+row.details.reason));if(row.notification_queued)card.append(node('p',t('queue'),'queue'));}
        list.append(card);
      }
    }
    selections();
  }
  async function load(name,more=false){const epoch=generation,old=records[name]||[];if(more && old.length>=500)throw new RequestError('maxRows');const last=more&&old.length?old.at(-1)[{clients:'client_id',subscriptions:'subscription_id',bookings:'booking_id',audit:'event_id'}[name]]:0;const data=await api('/v1/'+name+(last?'?after='+id(last):''));if(epoch!==generation)throw new Stale();if(!Array.isArray(data.items)||data.items.length>50)throw new RequestError('network',true);records[name]=more?[...old,...data.items]:data.items;}
  async function refresh(message=false){const epoch=generation;const outcomes=await Promise.allSettled(Object.keys(records).map(async name=>{try{await load(name);}catch(e){if(!(e instanceof Stale))records[name]=null;throw e;}}));if(epoch!==generation)return;try{render();}catch(e){notice(e.message,true);return false;}if(outcomes.some(r=>r.status==='rejected')){notice('loadFailed',true);return false;}if(message)notice('refreshed');return true;}
  function translate(){document.documentElement.lang=lang;document.title='Kinder Spa · '+t('workspace');for(const el of document.querySelectorAll('[data-i18n]'))el.textContent=t(el.dataset.i18n);for(const el of document.querySelectorAll('[data-i18n-title]')){el.title=t(el.dataset.i18nTitle);el.setAttribute('aria-label',t(el.dataset.i18nTitle));}for(const b of document.querySelectorAll('[data-lang]'))b.setAttribute('aria-pressed',String(b.dataset.lang===lang));if($('qr-scan-status').dataset.scanStatus)scanStatus($('qr-scan-status').dataset.scanStatus);$('today').textContent=lang==='uz'?date(Date.now()).split(',')[0]+' · Toshkent':new Intl.DateTimeFormat('ru-RU',{dateStyle:'long',timeZone:'Asia/Tashkent'}).format(new Date());$('page-title').textContent=t(tab==='audit'?'history':tab);if(token){$('identity').textContent=t($('identity').dataset.role)+' #'+$('identity').dataset.account;render();}else quotaOptions();}
  function openTab(name){tab=name;for(const section of document.querySelectorAll('.tab'))section.hidden=section.id!=='tab-'+name;for(const b of document.querySelectorAll('[data-tab]')){if(b.dataset.tab===name)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');}$('page-title').textContent=t(name==='audit'?'history':name);}
  async function mutate(scope,path,data,unkeyed=false){const previous=pending.get(scope),fingerprint=JSON.stringify(data);if(previous&&(previous.blocked||previous.fingerprint!==fingerprint))throw new RequestError(previous.blocked?'unknownCredentials':'pendingChanged',true);const item=previous||{fingerprint,key:crypto.randomUUID()};pending.set(scope,item);try{const result=await api(path,unkeyed?data:{...data,key:item.key});pending.delete(scope);return result;}catch(e){if(e instanceof RequestError&&e.uncertain){if(unkeyed)pending.set(scope,{blocked:true});throw new RequestError(unkeyed?'unknownCredentials':'unknownWrite',true);}if(!(e instanceof Stale))pending.delete(scope);throw e;}}
  function openAction(kind,record){stopScanner();action={kind,record};const dialog=$('action-dialog'),input=$('action-input');$('action-form').reset();$('action-error').textContent='';input.disabled=false;input.readOnly=false;input.type=kind==='reset'?'password':'text';input.autocomplete=kind==='reset'?'new-password':'off';input.required=['reset','restore','redeem'].includes(kind);input.minLength=kind==='reset'?12:kind==='restore'?3:kind==='redeem'?43:0;input.maxLength=kind==='reset'?128:kind==='redeem'?43:500;$('action-input-label').hidden=!input.required;$('action-title').textContent=t(kind==='no-show'?'no_show':kind)+' · #'+record;$('action-copy').textContent=t(({reset:'resetHint',restore:'reasonHint',redeem:'qrHint',cancel:'cancelHint','no-show':'noShowHint'})[kind]);$('action-input-caption').textContent=t(kind==='reset'?'initialPassword':kind==='restore'?'reason':'qr');$('confirm-action').disabled=!!pending.get('action:'+kind+':'+record)?.blocked;$('qr-scan-controls').hidden=kind!=='redeem';$('start-qr-scan').hidden=!(window.isSecureContext && typeof window.BarcodeDetector==='function' && !!navigator.mediaDevices?.getUserMedia);scanStatus(kind==='redeem' && $('start-qr-scan').hidden?'scanUnsupported':'');dialog.showModal();}
  $('login-form').addEventListener('submit',async e=>{e.preventDefault();const form=e.currentTarget;busy(form,true);$('login-message').textContent='';const attempt=++generation;const data=values(form);try{const result=await api('/v1/login',data);if(attempt!==generation)return;token=result.access_token;const who=await api('/v1/me');if(!['admin','superadmin'].includes(who.role)){try{await api('/v1/logout',{});}finally{clearSession();$('login-message').textContent=t('staffRequired');}return;}$('identity').dataset.role=who.role;$('identity').dataset.account=id(who.account_id);$('identity').textContent=t(who.role)+' #'+id(who.account_id);$('login-page').hidden=true;$('workspace').hidden=false;$('logout').hidden=false;openTab('overview');await refresh();}catch(e){if(!(e instanceof Stale)){token='';$('login-message').textContent=t(e.message==='rate'?'rate':e.message==='network'?'network':'authError');}else if(!token)$('login-message').textContent=t('authError');}finally{form.elements.password.value='';busy(form,false);}});
  $('logout').addEventListener('click',async()=>{const old=token;clearSession();const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);try{const r=await fetch('/v1/logout',{method:'POST',headers:{Authorization:'Bearer '+old,'Content-Type':'application/json'},body:'{}',credentials:'omit',cache:'no-store',redirect:'error',signal:controller.signal});if(!r.ok&&r.status!==401)$('login-message').textContent=t('localExit');}catch{$('login-message').textContent=t('localExit');}finally{clearTimeout(timer);}});
  function formHandler(formId,path,scope,build,success,unkeyed=false){const form=$(formId);form.addEventListener('submit',async e=>{e.preventDefault();busy(form,true);const epoch=generation;try{await mutate(scope,path,build(values(form)),unkeyed);if(epoch!==generation)return;lock(form,false);form.reset();const updated=await refresh();if(epoch===generation)notice(updated?success:'savedButReadFailed',!updated);}catch(err){if(err instanceof Stale)return;notice(err.message,true);if(err.uncertain){lock(form,true);if(unkeyed)busy(form,true);}}finally{if(unkeyed)for(const input of form.querySelectorAll('input[type=password]'))input.value='';if(epoch===generation&&!pending.get(scope)?.blocked)busy(form,false);}});}
  formHandler('client-form','/v1/clients','new-client',v=>({login:v.login,password:v.password}),'created',true);
  formHandler('subscription-form','/v1/subscriptions','new-subscription',v=>({client_id:id(Number(v.client_id)),quotas:{[v.category]:Number(v.quota)}}),'issuedOk');
  formHandler('booking-form','/v1/bookings','new-booking',v=>{const [sub,category]=v.allowance.split(':');return{subscription_id:id(Number(sub)),category,starts_at:v.starts_at+':00+05:00',minutes:Number(v.minutes)};},'booked');
  $('action-form').addEventListener('submit',async e=>{e.preventDefault();if(!action)return;const form=e.currentTarget,epoch=generation,{kind,record}=action;busy(form,true);let data={},path='/v1/bookings/'+record+'/'+kind;const value=$('action-input').value;if(kind==='reset'){data={password:value};path='/v1/clients/'+record+'/password';}if(kind==='restore')data={reason:value.trim()};if(kind==='redeem')data={token:value.trim()};try{await mutate('action:'+kind+':'+record,path,data,kind==='reset');if(epoch!==generation)return;$('action-input').value='';$('action-dialog').close();const updated=await refresh();if(epoch===generation)notice(updated?(kind==='restore'?'restoredOk':'actionOk'):'savedButReadFailed',!updated);}catch(err){if(!(err instanceof Stale)){$('action-error').textContent=t(err.message);if(err.uncertain)$('action-input').readOnly=true;}}finally{if(kind==='reset')$('action-input').value='';if(epoch===generation&&!pending.get('action:'+kind+':'+record)?.blocked)busy(form,false);}});
  $('start-qr-scan').addEventListener('click',startScanner);
  $('action-dialog').addEventListener('close',()=>{stopScanner();$('action-input').value='';action=null;});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stopScanner();});
  for(const id of ['cancel-dialog','close-dialog'])$(id).addEventListener('click',()=>{$('action-dialog').close();$('action-input').value='';});
  $('refresh').addEventListener('click',()=>refresh(true).catch(e=>{if(!(e instanceof Stale))notice('loadFailed',true);}));
  for(const button of document.querySelectorAll('[data-tab]'))button.addEventListener('click',()=>openTab(button.dataset.tab));
  for(const button of document.querySelectorAll('[data-go]'))button.addEventListener('click',()=>openTab(button.dataset.go));
  for(const button of document.querySelectorAll('[data-lang]'))button.addEventListener('click',()=>{lang=button.dataset.lang;translate();});
  for(const button of document.querySelectorAll('[data-more]'))button.addEventListener('click',async()=>{button.disabled=true;try{await load(button.dataset.more,true);render();}catch(e){if(!(e instanceof Stale))notice(e.message,true);}finally{button.disabled=false;}});
  $('subscription-form').elements.category.addEventListener('change',quotaOptions);$('booking-form').elements.allowance.addEventListener('change',minutes);
  window.addEventListener('beforeunload',e=>{if(pending.size){e.preventDefault();e.returnValue='';}});
  window.addEventListener('pageshow',e=>{if(e.persisted)clearSession();});
  translate();
})();
