import os
import aiohttp
import re
import json
import sqlite3
import requests
import asyncio
from yandex_music import ClientAsync
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from genre_map import GENRE_MAP


YANDEX_TOKEN = os.environ.get('YANDEX_TOKEN')
DB_PATH = os.environ.get('DB_PATH')
USER_AGENT = os.environ.get('USER_AGENT')
BASE_PATH = os.environ.get('BASE_PATH')
API_KEY = os.environ.get('API_KEY')
LIDARR_URL = os.environ.get('LIDARR_URL')
GENRES = list(set(GENRE_MAP.values()))
BASE_PATH_LIDARR = os.environ.get('BASE_PATH_LIDARR')
QUALITY_PROFILE_ID = 1
METADATA_PROFILE_ID = 1
print(YANDEX_TOKEN)

def sanitize_name(name):
    return re.sub(r'[\\/:*?"<>|]', '', name).strip()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS artists (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        id_track INTEGER,
        id_albom INTEGER,
        albom_name TEXT,
        yandex_genre TEXT,
        mb_genre TEXT,
        mb_present INTEGER DEFAULT 0,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        path_artist TEXT
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS albums (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        artist_name TEXT,
        id_albom INTEGER UNIQUE,
        albom_name TEXT,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    return conn

async def fetch_liked_tracks(conn):
    client = ClientAsync(YANDEX_TOKEN)
    await client.init()

    liked_short_tracklist = await client.users_likes_tracks()
    tasks = [item.fetch_track_async() for item in liked_short_tracklist]
    tracks = await asyncio.gather(*tasks, return_exceptions=True)

    cur = conn.cursor()
    seen = set(row[0] for row in cur.execute("SELECT name FROM artists").fetchall())
    new_artists = []

    for track in tracks:
        try:
            if isinstance(track, Exception):
                raise track
            if track and track.artists:
                artist_name = track.artists[0].name
                if artist_name not in seen:
                    seen.add(artist_name)
                    genre = track.albums[0].genre if track.albums else "unknown"
                    # Сохраняем в базу данных
                    sanitized_name = sanitize_name(artist_name)
                    new_artists.append((sanitized_name, genre))
                    print(f"Добавлен артист: {sanitized_name}")
                    await asyncio.sleep(2)

        except Exception as e:
            print(f"Ошибка при обработке трека: {e}")

    if new_artists:
        cur.executemany("INSERT OR IGNORE INTO artists (name, yandex_genre) VALUES (?, ?)", new_artists)
        conn.commit()

    print(f"\nУникальных исполнителей добавлено: {len(new_artists)}")


async def update_musicbrainz_info(conn):
    cur = conn.cursor()
    cur.execute("SELECT name FROM artists WHERE mb_present = 0")
    artists_to_update = [row[0] for row in cur.fetchall()]

    if not artists_to_update:
        print("Нет артистов для обновления MusicBrainz")
        return

    async with aiohttp.ClientSession() as session:
        for artist_name in artists_to_update:
            success = False
            for attempt in range(3):  # до 3 попыток
                try:
                    url = "https://musicbrainz.org/ws/2/artist/"
                    params = {"query": artist_name, "fmt": "json", "limit": 1}
                    headers = {"User-Agent": USER_AGENT}

                    async with session.get(url, params=params, headers=headers, timeout=10) as response:
                        print(f"Запрос к MusicBrainz для {artist_name}, статус: {response.status}")
                        if response.status == 503:
                            print(f"503 — сервер перегружен, повторная попытка {attempt+1}/3")
                            await asyncio.sleep(0.5 + attempt)
                            continue
                        if response.status != 200:
                            mb_genre = "unknown"
                            present = 0
                        else:
                            data = await response.json()
                            if not data.get('artists'):
                                mb_genre = "unknown"
                                present = 0
                            else:
                                artist = data['artists'][0]
                                tags = artist.get('tags', [])
                                if not tags:
                                    mb_genre = "unknown"
                                else:
                                    mb_genre = sorted(tags, key=lambda x: -x.get('count', 0))[0]['name'].lower()
                                present = 1

                        cur.execute(
                            "UPDATE artists SET mb_genre = ?, mb_present = ? WHERE name = ?",
                            (mb_genre, present, artist_name)
                        )
                        conn.commit()
                        print(f"Обновлён {artist_name} -> {mb_genre}")
                        success = True
                        break
                except Exception as e:
                    print(f"Ошибка запроса {artist_name}: {e}")
                    await asyncio.sleep(0.5 + attempt)
            if not success:
                print(f"Не удалось обновить {artist_name} после 3 попыток")
            await asyncio.sleep(0.5)  # пауза перед следующим артистом

def rebuild_folders(conn):
    cur = conn.cursor()
    cur.execute("SELECT name, yandex_genre, mb_genre FROM artists")
    for name, yandex, mb in cur.fetchall():
        genre_raw = mb if mb != "unknown" else yandex
        if not genre_raw:
            genre_raw = "unknown"
        mapped = GENRE_MAP.get(genre_raw.lower(), "Other")
        genre_folder = os.path.join(BASE_PATH, sanitize_name(mapped))
        artist_folder = os.path.join(genre_folder, sanitize_name(name))
        os.makedirs(os.path.join(artist_folder, '__EMPTY__'), exist_ok=True)

        cur.execute(
            "UPDATE artists SET path_artist = ? WHERE name = ?",
            (artist_folder, name)
        )
        conn.commit()



def add_root_folder():
    for genre in GENRES:
        path = f"{BASE_PATH_LIDARR}/{genre}"
        # Создаем папку на диске, если её нет
        os.makedirs(path, exist_ok=True)

        data = {
            "name": path,
            "path": path,
            "defaultQualityProfileId": 1,
            "defaultMetadataProfileId": 1,
            "defaultMonitor": "all",
            "defaultNewItemMonitor": "all",
            "defaultTags": []
        }

        r = requests.post(f"{LIDARR_URL}/rootFolder", params={"apikey": API_KEY}, json=data)
        if r.status_code == 201:
            print(f"Папка {path} успешно добавлена в Lidarr.")
        else:
            print(f"Ошибка при добавлении папки {path}: {r.text}")


def get_artist_id(artist_name):
    """Получаем ID артиста из Lidarr по имени."""
    url = "https://musicbrainz.org/ws/2/artist/"
    params = {"query": artist_name, "fmt": "json", "limit": 1}
    headers = {"User-Agent": USER_AGENT}
    r = requests.get(url, params=params, headers=headers)
    if r.status_code != 200:
        print(f"Ошибка запроса к MusicBrainz для {artist_name}: {r.status_code}")
        return None
    data = r.json()
    if not data.get('artists'):
        print(f"Артист {artist_name} не найден в MusicBrainz")
        return None
    return data['artists'][0]['id']


def search_artist_in_lidarr():
    # Цвета ANSI
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RESET = "\033[0m"


# --- Получаем root folders из Lidarr ---
    r = requests.get(f"{LIDARR_URL}/rootFolder", params={"apikey": API_KEY})
    rootfolders = {item['name'].split('/')[-1]: item['id'] for item in r.json()}  # genre -> id

    # --- Основной процесс ---
    for genre in os.listdir(BASE_PATH):
        genre_folder = os.path.join(BASE_PATH, genre)
        if not os.path.isdir(genre_folder):
            print(f"{genre_folder} не папка, пропускаем.")
            continue

        # Проверяем, есть ли rootFolder в Lidarr для жанра
        root_id = rootfolders.get(genre)
        if not root_id:
            print(f"Root folder для {genre} не найден в Lidarr. Пропускаем.")
            continue

        # Получаем артистов из подпапок
        artists = [name for name in os.listdir(genre_folder)
                if os.path.isdir(os.path.join(genre_folder, name))]

        for artist_name in artists:
            data = {
                "ArtistName": artist_name,
                "rootFolderPath": f"{BASE_PATH_LIDARR}/{genre}",    # старый параметр можно оставить None
                "qualityProfileId": QUALITY_PROFILE_ID,
                "metadataProfileId": METADATA_PROFILE_ID,
                "ForeignArtistId": get_artist_id(artist_name),  # получаем ID артиста из MusicBrainz
                "addOptions": {
                    "monitor": "all",
                    "searchForMissingAlbums": True
                },
                "path": f"{BASE_PATH_LIDARR}/{genre}/{artist_name}",               # Lidarr сам создаст путь внутри rootFolder
                "tags": [],
                "rootFolderId": root_id,     # важное поле — куда добавлять артиста
                "monitored": True,
                "monitorNewItems": "all",
            }
            r = requests.post(f"{LIDARR_URL}/artist", params={"apikey": API_KEY}, json=data)
            if r.status_code in [200, 201]:
                print(f"{GREEN}Артист добавлен: {artist_name}{RESET}")
            else:
                if r.status_code == 400 and "is already configured for an existing artist" in r.text:
                    print(f"{YELLOW}Артист {artist_name} уже существует в Lidarr, пропускаем.{RESET}")
                    continue
                try:
                    data = json.loads(r.text)
                    if isinstance(data, dict):
                        error_message = data.get("message", r.text)
                    else:
                        # если это список или что-то другое — просто выводим как есть
                        error_message = r.text
                except json.JSONDecodeError:
                    error_message = r.text

                print(f"{RED}Ошибка при добавлении {artist_name}: {r.status_code}, {error_message}{RESET}")


# ====== обёртки для меню ======
def run_fetch_liked_tracks():
    conn = init_db()
    asyncio.run(fetch_liked_tracks(conn))
    conn_close(conn)

def run_update_musicbrainz_info():
    conn = init_db()
    asyncio.run(update_musicbrainz_info(conn))
    conn_close(conn)

def run_rebuild_folders():
    conn = init_db()
    rebuild_folders(conn)
    conn_close(conn)

def run_add_root_folder():
    add_root_folder()

def run_search_artist_in_lidarr():
    search_artist_in_lidarr()

def conn_close(conn):
    print("Закрываю соединение с БД")
    conn.close()

# ====== текстовое меню для Windows ======
def main():
    menu_actions = {
        "1": ("Забрать треки из Яндекс.Музыки", run_fetch_liked_tracks),
        "2": ("Обновить информацию из MusicBrainz", run_update_musicbrainz_info),
        "3": ("Перестроить папки", run_rebuild_folders),
        "4": ("Добавить root папку в Lidarr", run_add_root_folder),
        "5": ("Поиск артиста в Lidarr", run_search_artist_in_lidarr),
        "0": ("Выход", exit),
    }

    while True:
        print("\n=== Главное меню ===")
        for key, (desc, _) in menu_actions.items():
            print(f"{key}. {desc}")

        choice = input("Выберите пункт: ").strip()
        if choice in menu_actions:
            _, action = menu_actions[choice]
            action()
        else:
            print("Неверный ввод, попробуйте ещё раз.")

if __name__ == "__main__":
    main()
