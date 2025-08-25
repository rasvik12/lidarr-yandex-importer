Вот компактная версия README.md, сразу с описанием меню и структуры папок:

# Yandex to Lidarr Importer

Автоматизирует добавление музыки из Яндекс.Музыки в **Lidarr**, с поддержкой MusicBrainz и структурой папок по жанрам.

---

## Требования

- Python 3.11+
- Библиотеки:
    pip install aiohttp yandex-music requests

- Настроенный Lidarr сервер и API ключ.
- Yandex Music token.

- Переменные окружения:
YANDEX_TOKEN	Токен Яндекс.Музыки
DB_PATH	Путь к SQLite базе данных
USER_AGENT	User-Agent для MusicBrainz
BASE_PATH	Локальный медиакаталог
API_KEY	API ключ Lidarr
LIDARR_URL	URL сервера Lidarr
BASE_PATH_LIDARR	Root-папки в Lidarr

Меню
1. Забрать треки из Яндекс.Музыки
2. Обновить информацию из MusicBrainz
3. Перестроить папки
4. Добавить root папку в Lidarr
5. Поиск артиста в Lidarr
0. Выход


1 — добавляет новых артистов и жанры из Яндекс.Музыки.

2 — обновляет жанры из MusicBrainz (асинхронно, с паузами).

3 — перестраивает папки жанр/артист/__EMPTY__.

4 — создаёт root-папки в Lidarr.

5 — добавляет артистов в Lidarr с цветным выводом:




Структура папок
BASE_PATH/
├── Rock/
│   ├── Lumen/
│   │   └── __EMPTY__/
│   ├── Би-2/
│   │   └── __EMPTY__/
├── Metal/
│   ├── Munruthel/
│   │   └── __EMPTY__/
└── Other/
    └── UnknownArtist/
        └── __EMPTY__/


Использование
python main.py


Выберите пункт меню и следуйте инструкциям.

Особенности

Асинхронная обработка треков и запросов к MusicBrainz.

Паузы между запросами для предотвращения 503 ошибок MusicBrainz.