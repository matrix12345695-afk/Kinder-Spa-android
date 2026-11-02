-- Kinder Spa schema, version 6: centre settings shown on the public site and in the bot.
SET LOCAL search_path TO kinder;
CREATE TABLE center_settings (
    key    text PRIMARY KEY CHECK (key IN ('phone','address','hours','instagram','map_url','about_ru','about_uz')),
    value  text NOT NULL DEFAULT '' CHECK (length(value) <= 2000)
);
INSERT INTO center_settings(key, value) VALUES
 ('hours', 'Пн–Сб, 9:00–19:00'),
 ('about_ru', 'Детский оздоровительный центр: массаж, гидромассаж и бассейн для малышей и детей постарше. Бережно, по записи, с опытными специалистами.'),
 ('about_uz', 'Bolalar sog''lomlashtirish markazi: chaqaloqlar va kattaroq bolalar uchun massaj, gidromassaj va basseyn. Ehtiyotkorlik bilan, oldindan yozilish orqali, tajribali mutaxassislar bilan.');

-- Uzbek descriptions for the default catalogue (only where still untouched).
UPDATE services SET description_uz = 'Bolalar uchun sog''lomlashtiruvchi massaj.' WHERE code = 'massage' AND description_uz = '';
UPDATE services SET description_uz = 'Bolalar uchun gidromassaj vannasi.' WHERE code = 'hydromassage' AND description_uz = '';
UPDATE services SET description_uz = 'Instruktor bilan basseyndagi mashg''ulot.' WHERE code = 'pool' AND description_uz = '';
