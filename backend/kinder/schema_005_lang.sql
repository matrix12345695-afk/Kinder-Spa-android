-- Kinder Spa schema, version 5: bot language per chat.
SET LOCAL search_path TO kinder;
ALTER TABLE telegram_chats ADD COLUMN lang text NOT NULL DEFAULT 'ru' CHECK (lang IN ('ru','uz'));
ALTER TABLE telegram_chats ADD COLUMN lang_chosen boolean NOT NULL DEFAULT false;
