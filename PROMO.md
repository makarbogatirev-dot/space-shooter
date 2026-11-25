# Реклама Space Shooter — готовые материалы

> Постить от твоего имени я не могу. Здесь — то, что можно скопировать и опубликовать за 15 минут,
> и куда именно публиковать, чтобы получить игроков.

**Ссылка для всех материалов:**
`https://makarbogatirev-dot.github.io/space-shooter/site/`

---

## 1. Куда публиковать (по приоритету отдачи)

| Площадка | Что даёт | Сложность |
|---|---|---|
| **itch.io** | Готовая аудитория инди-игр, бесплатно, индексируется Google | 10 мин |
| **Telegram-каналы об играх** | Живые игроки, если попасть в подборку | 5 мин на пост |
| **VK: группы по Python/Pygame** | Русская аудитория, лояльная к самоделкам | 5 мин |
| **Пикабу** | «Сделал игру на Python» — стабильно заходит | 15 мин |
| **Reddit** r/WebGames, r/pygame | Англоязычный трафик | 5 мин (нужен англ. текст) |
| **Хабр (Q&A / блог)** | Техническая аудитория, долгий трафик | 30 мин |
| **Google Search Console** | Индексация в поиске — база всего | 5 мин |

**Что НЕ сработает:** спам ссылкой в чатах, закупка ботов, «накрутка» рейтинга. Забанят аккаунт, а игроков не будет.

---

## 2. Готовый пост для Telegram / VK

```
🚀 Space Shooter — космический шутер, который я сделал сам

Уворачивайся от метеоритов, собирай бонусы и бей рекорды.

Что внутри:
🎮 Играй прямо в браузере — без установки
💾 Или скачай .exe для Windows (портативная версия)
⚡ Бонусы: Speed, God, Penetration
👥 Друзья, чат и таблица лидеров
🔐 Аккаунты с 2FA — без спама и рекламы

Игра бесплатная, без рекламы и доната.
👉 https://makarbogatirev-dot.github.io/space-shooter/site/

Скажи в комментариях, сколько набрал — интересно сравнить 😄
```

---

## 3. Пост для Пикабу (там важен «человеческий» тон)

**Заголовок:** Сделал космический шутер на Python и выложил в браузер. Хочу критики

```
Всем привет!

Учу Python и решил сделать что-то большее, чем калькулятор. Так появился
Space Shooter — аркадный шутер в духе классики: летаешь, стреляешь по
метеоритам, собираешь бонусы.

Что уже есть:
— Браузерная версия (можно играть без установки)
— .exe для Windows
— Аккаунты, таблица лидеров, друзья и чат
— Бонусы: ускорение, неуязвимость, пробивающие выстрелы
— 2FA на почту, чтобы аккаунты не угоняли

Делал на Pygame, сервер на Python + PostgreSQL, сайт на чистом JS.

Чего не хватает — звука получше, мобильного управления, баланса сложности.
Буду рад любой критике, особенно по геймплею.

Ссылка: https://makarbogatirev-dot.github.io/space-shooter/site/
```

---

## 4. itch.io — описание проекта

**Title:** Space Shooter
**Short description (до 200 символов):**
```
Аркадный космический шутер: уворачивайся от метеоритов, собирай бонусы, бей рекорды. Играй в браузере или скачай для Windows. Бесплатно, без рекламы.
```
**Genre:** Shooter / Arcade
**Tags:** `space`, `arcade`, `shooter`, `singleplayer`, `2d`, `free`, `browser`
**Pricing:** No payments (free)
**Uploads:** `SpaceShooter_v1.1.exe` (Windows), `SpaceShooter_Setup_v1.1.exe` (installer)
**Cover image:** `site/assets/screenshots/og-cover.png` (1200×630)
**Screenshots:** gameplay1.png, gameplay2.png, gameplay3.png

---

## 5. Reddit (английский)

```
[Free] Space Shooter — a space arcade game I built with Python + Pygame

I wanted to learn game dev, so I built this: dodge meteors, grab power-ups
(Speed / God / Penetration), and chase the leaderboard.

- Play in browser, no install
- Windows .exe also available
- Accounts with 2FA, friends list and chat
- Completely free, no ads, no monetization

Would love feedback on game feel and difficulty balance.
https://makarbogatirev-dot.github.io/space-shooter/site/
```

---

## 6. Обязательный шаг: Google Search Console

Без этого сайт может месяцами не появляться в поиске.

1. Открой https://search.google.com/search-console
2. «Добавить ресурс» → «Префикс URL» → `https://makarbogatirev-dot.github.io/space-shooter/site/`
3. Подтверди владение: положи файл `google34f967cadc2f78f6.html` уже есть в `site/` — выбери способ «HTML-файл», он должен открыться по адресу `.../site/google34f967cadc2f78f6.html`
4. После подтверждения: **Индексирование → Файлы Sitemap → добавить** `sitemap.xml`
5. **Проверка URL** → вставь адрес сайта → «Запросить индексирование»

**Важно:** `robots.txt` работает только в корне домена (`makarbogatirev-dot.github.io/robots.txt`), а у тебя проект в подпапке — этот файл поисковик не увидит. Поэтому sitemap нужно добавить в Search Console вручную (шаг 4).

---

## 7. Что уже сделано на сайте (технически)

- `title` с ключевыми словами + `meta description`
- Open Graph — превью с картинкой при отправке ссылки в Telegram/VK/Discord
- Twitter Card
- JSON-LD `VideoGame` — Google понимает, что это игра
- `canonical` — защита от дублей
- `sitemap.xml` с `lastmod` и картинками
- `og-cover.png` 1200×630
- Кнопки «Поделиться» в футере (Telegram / VK / WhatsApp / копировать)

---

## 8. Что реально увеличит удержание (идеи на потом)

1. **Мобильное управление** — половина трафика с телефонов, сейчас играть неудобно.
2. **Ссылка «бросить вызов другу»** — `?challenge=ник&score=506` в URL. Приводит друзей напрямую.
3. **Ежедневный рекорд дня** — повод возвращаться.
4. **Своя ссылка на профиль** — игрок делится `?player=ник`.
5. **Звук в браузерной версии** — сейчас тихо, а звук сильно влияет на «сочность».

Из этого списка пункт 2 — самый дешёвый и самый вирусный. Скажи — сделаю.
