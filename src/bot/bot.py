# -*- coding: utf-8 -*-

import json
import os
import random
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

from src.scheduler.scheduler import start_scheduler


# ============================================================
# PATHS / ENV (железобетонно)
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[2]  # .../music-bot
DATA_DIR = BASE_DIR / "data"
COVERS_DIR = BASE_DIR / "covers"
CONFIG_DIR = BASE_DIR / "config"

ALBUMS_PATH = DATA_DIR / "albums.final.json"
USERS_PATH = DATA_DIR / "users.json"
SUBSCRIBERS_PATH = DATA_DIR / "subscribers.json"
SENT_PATH = DATA_DIR / "sent_albums.json"
RATINGS_PATH = DATA_DIR / "ratings.json"

DEFAULT_COVER_PATH = COVERS_DIR / "default.jpg"

ENV_PATH = CONFIG_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError(f"BOT_TOKEN not found in {ENV_PATH}")

bot = telebot.TeleBot(BOT_TOKEN)


# ============================================================
# JSON helpers (safe read/write)
# ============================================================

def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

def load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json_atomic(path: Path, data: Any) -> None:
    _ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ============================================================
# USERS (profiles)
# users.json: dict {"123": {...}}
# ============================================================

def load_users() -> Dict[str, Dict[str, Any]]:
    data = load_json(USERS_PATH, {})
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        # backward compat: [] or [id,id]
        return {str(x): {} for x in data}
    return {}

def upsert_user(message: telebot.types.Message) -> None:
    users = load_users()
    uid = str(message.chat.id)

    profile = users.get(uid, {})
    profile.update({
        "id": message.chat.id,
        "username": getattr(message.from_user, "username", None),
        "first_name": getattr(message.from_user, "first_name", None),
        "last_name": getattr(message.from_user, "last_name", None),
        "last_seen": message.date,
    })
    users[uid] = profile
    save_json_atomic(USERS_PATH, users)


# ============================================================
# SUBSCRIBERS
# поддерживаем 2 формата:
# 1) [123, 456]
# 2) {"123": {"active": true, ...}, ...}
# ============================================================

def load_subscribers_raw() -> Union[List[int], Dict[str, Any]]:
    return load_json(SUBSCRIBERS_PATH, [])

def load_subscribers_set() -> Set[int]:
    data = load_subscribers_raw()

    if isinstance(data, list):
        out = set()
        for x in data:
            try:
                out.add(int(x))
            except Exception:
                pass
        return out

    if isinstance(data, dict):
        out = set()
        for k, v in data.items():
            try:
                active = True
                if isinstance(v, dict):
                    active = v.get("active", True)
                if active:
                    out.add(int(k))
            except Exception:
                continue
        return out

    return set()

def save_subscribers(data: Union[List[int], Dict[str, Any]]) -> None:
    save_json_atomic(SUBSCRIBERS_PATH, data)

def subscribe(chat_id: int) -> None:
    data = load_subscribers_raw()

    if isinstance(data, list):
        if chat_id not in data:
            data.append(chat_id)
            save_subscribers(data)
        return

    if isinstance(data, dict):
        key = str(chat_id)
        entry = data.get(key, {})
        if not isinstance(entry, dict):
            entry = {}
        entry["active"] = True
        entry.setdefault("subscribed_at", None)
        data[key] = entry
        save_subscribers(data)
        return

    save_subscribers([chat_id])

def unsubscribe(chat_id: int) -> None:
    data = load_subscribers_raw()

    if isinstance(data, list):
        if chat_id in data:
            data = [x for x in data if x != chat_id]
            save_subscribers(data)
        return

    if isinstance(data, dict):
        key = str(chat_id)
        if key in data:
            if isinstance(data[key], dict):
                data[key]["active"] = False
            else:
                data[key] = {"active": False}
            save_subscribers(data)
        return


# ============================================================
# RATINGS
# ratings.json: {"user_id": {"album_ident": "bad|ok|super"}}
# ============================================================

def load_ratings() -> Dict[str, Dict[str, str]]:
    data = load_json(RATINGS_PATH, {})
    return data if isinstance(data, dict) else {}

def save_ratings(data: Dict[str, Dict[str, str]]) -> None:
    save_json_atomic(RATINGS_PATH, data)


# ============================================================
# ALBUMS + SENT
# albums.final.json содержит:
# artist, album, year, cover, links{spotify,apple,youtube}, id/key
# sent_albums.json: список идентификаторов (id/key)
# ============================================================

def load_albums() -> List[Dict[str, Any]]:
    albums = load_json(ALBUMS_PATH, [])
    return albums if isinstance(albums, list) else []

def load_sent() -> Set[str]:
    data = load_json(SENT_PATH, [])
    if isinstance(data, list):
        return set(str(x) for x in data)
    return set()

def save_sent(sent: Set[str]) -> None:
    save_json_atomic(SENT_PATH, sorted(list(sent)))

def album_ident(album: Dict[str, Any]) -> str:
    if album.get("id") is not None:
        return str(album["id"])
    if album.get("key"):
        return str(album["key"])
    return f"{album.get('artist','').strip()}__{album.get('album','').strip()}"

def resolve_cover_path(album: Dict[str, Any]) -> Path:
    raw = album.get("cover")
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = BASE_DIR / p
        if p.exists():
            return p
    return DEFAULT_COVER_PATH

def pick_two_unique_unsent() -> Optional[List[Dict[str, Any]]]:
    albums = load_albums()
    sent = load_sent()

    remaining = [a for a in albums if album_ident(a) not in sent]
    if len(remaining) < 2:
        return None

    chosen = random.sample(remaining, 2)
    for a in chosen:
        sent.add(album_ident(a))
    save_sent(sent)
    return chosen


# ============================================================
# UI: caption + keyboard
# ============================================================

def build_caption(album: Dict[str, Any]) -> str:
    # Требование: артист + альбом одной строкой
    artist = (album.get("artist") or "Unknown Artist").strip()
    title = (album.get("album") or "Unknown Album").strip()
    year = album.get("year")

    line = f"🎵 <b>{artist} — {title}</b>"
    if year:
        line += f" <i>({year})</i>"

    # Вторая строка (необязательно, но удобно)
    # Если хочешь вообще одной строкой — просто верни line
    return line

def build_keyboard(album: Dict[str, Any]) -> InlineKeyboardMarkup:
    """
    Всегда показываем 3 кнопки:
    - если есть прямые ссылки — используем их
    - иначе даём поиск (Spotify/Apple/YT Music)
    """
    markup = InlineKeyboardMarkup()

    artist = album.get("artist", "")
    title = album.get("album", "")
    q = urllib.parse.quote_plus(f"{artist} {title}")

    links = album.get("links") or {}

    spotify = links.get("spotify") or f"https://open.spotify.com/search/{q}"
    apple = links.get("apple") or f"https://music.apple.com/search?term={q}"
    youtube = links.get("youtube") or f"https://music.youtube.com/search?q={q}"

    markup.row(
        InlineKeyboardButton("Spotify", url=spotify),
        InlineKeyboardButton("Apple Music", url=apple),
        InlineKeyboardButton("YouTube Music", url=youtube),
    )

    ident = album_ident(album)
    markup.add(InlineKeyboardButton("🎧 Оценить", callback_data=f"rate|{ident}"))
    return markup


# ============================================================
# SEND album
# ============================================================

def send_album_to_user(user_id: int, album: Dict[str, Any]) -> None:
    cover_path = resolve_cover_path(album)
    caption = build_caption(album)
    markup = build_keyboard(album)

    try:
        with open(cover_path, "rb") as photo:
            bot.send_photo(
                user_id,
                photo,
                caption=caption,
                parse_mode="HTML",
                reply_markup=markup,
            )
    except Exception:
        bot.send_message(user_id, caption, parse_mode="HTML", reply_markup=markup)


# ============================================================
# DAILY SEND
# ============================================================

def send_daily_albums() -> None:
    subs = load_subscribers_set()
    if not subs:
        return

    pair = pick_two_unique_unsent()
    if not pair:
        for u in subs:
            bot.send_message(u, "📭 Альбомы закончились!")
        return

    for u in subs:
        for album in pair:
            send_album_to_user(u, album)


# ============================================================
# CALLBACKS: rating
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("rate|"))
def callback_rate(call):
    ident = call.data.split("|", 1)[1]

    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("❌ Не понравилось", callback_data=f"setrate|{ident}|bad"),
        InlineKeyboardButton("😐 Норм", callback_data=f"setrate|{ident}|ok"),
        InlineKeyboardButton("⭐ Супер", callback_data=f"setrate|{ident}|super"),
    )

    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup,
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("setrate|"))
def set_rating(call):
    _, ident, rating = call.data.split("|", 2)

    ratings = load_ratings()
    user = str(call.message.chat.id)

    if user not in ratings:
        ratings[user] = {}

    ratings[user][ident] = rating
    save_ratings(ratings)

    response = {"bad": "❌ Не понравилось", "ok": "😐 Норм", "super": "⭐ Супер"}[rating]
    bot.answer_callback_query(call.id, f"Оценка: {response}")


# ============================================================
# COMMANDS
# ============================================================

@bot.message_handler(commands=["start"])
def start_cmd(message):
    upsert_user(message)
    subscribe(message.chat.id)
    bot.send_message(
        message.chat.id,
        "✅ Ты подписан на ежедневные рекомендации!\n\n"
        "Команды:\n"
        "/random — получить 2 случайных альбома\n"
        "/list — список отправленных (с твоими оценками)\n"
        "/unsubscribe — отключить рассылку\n"
        "/subscribe — включить рассылку",
    )

@bot.message_handler(commands=["subscribe"])
def subscribe_cmd(message):
    upsert_user(message)
    subscribe(message.chat.id)
    bot.send_message(message.chat.id, "✅ Подписка включена.")

@bot.message_handler(commands=["unsubscribe"])
def unsubscribe_cmd(message):
    upsert_user(message)
    unsubscribe(message.chat.id)
    bot.send_message(message.chat.id, "🛑 Подписка отключена. Чтобы включить обратно: /subscribe")

@bot.message_handler(commands=["random"])
def random_cmd(message):
    upsert_user(message)

    albums = load_albums()
    if len(albums) < 2:
        bot.send_message(message.chat.id, "В базе слишком мало альбомов.")
        return

    pair = random.sample(albums, 2)
    for album in pair:
        send_album_to_user(message.chat.id, album)

@bot.message_handler(commands=["list"])
def list_cmd(message):
    upsert_user(message)

    sent = load_sent()
    ratings = load_ratings()
    user = str(message.chat.id)

    albums = load_albums()
    by_ident = {album_ident(a): a for a in albums}

    lines = []
    for ident in sent:
        a = by_ident.get(ident)
        label = ident if not a else f"{a.get('artist','')} — {a.get('album','')}"

        if user in ratings and ident in ratings[user]:
            r = ratings[user][ident]
            icon = {"bad": "❌", "ok": "😐", "super": "⭐"}[r]
            lines.append(f"{icon} {label}")
        else:
            lines.append(f"• {label}")

    bot.send_message(message.chat.id, "\n".join(lines) if lines else "Пока ничего не отправлялось.")


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    print("Bot started (local albums.final.json)")
    start_scheduler(send_daily_albums)
    bot.infinity_polling()
