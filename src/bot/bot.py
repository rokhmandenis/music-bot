# -*- coding: utf-8 -*-
import json
import random
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import BOT_TOKEN
from spotify_apple_api import fetch_album_data
from scheduler import start_scheduler

bot = telebot.TeleBot(BOT_TOKEN)


# ============================================================
# USERS
# ============================================================

def load_users():
    try:
        with open("users.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def save_users(users):
    with open("users.json", "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)


def add_user(chat_id):
    users = load_users()
    if chat_id not in users:
        users.append(chat_id)
        save_users(users)


# ============================================================
# RATINGS
# ============================================================

def load_ratings():
    try:
        with open("ratings.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_ratings(data):
    with open("ratings.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ============================================================
# ALBUM STORAGE
# ============================================================

def load_albums():
    with open("albums.json", "r", encoding="utf-8") as f:
        return json.load(f)


def load_sent():
    try:
        with open("sent_albums.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def save_sent(sent):
    with open("sent_albums.json", "w", encoding="utf-8") as f:
        json.dump(sent, f, indent=2, ensure_ascii=False)


def pick_two_unique():
    albums = load_albums()
    sent = load_sent()

    remaining = [a for a in albums if a not in sent]

    if len(remaining) < 2:
        return None

    chosen = random.sample(remaining, 2)
    sent.extend(chosen)
    save_sent(sent)

    return chosen


# ============================================================
# MESSAGE FORMATTER
# ============================================================

def format_message(info):
    msg = f"🎵 <b>{info['artist']} — {info['title']}</b>\n"

    if info.get("release_date"):
        msg += f"Дата выхода: {info['release_date']}\n"

    if info.get("spotify_url"):
        msg += f"<a href='{info['spotify_url']}'>Spotify</a>\n"

    if info.get("apple_url"):
        msg += f"<a href='{info['apple_url']}'>Apple Music</a>\n"

    if info.get("youtube_music_url"):
        msg += f"<a href='{info['youtube_music_url']}'>YouTube Music</a>\n"

    return msg


# ============================================================
# SEND SINGLE ALBUM TO USER
# ============================================================

def send_album_to_user(user_id, album):
    album_name = album["album"]

    info = fetch_album_data(
        album["album"],
        artist=album["artist"],
        year=album["year"]
    )

    if not info:
        bot.send_message(user_id, f"Не нашёл: {album_name}")
        return

    caption = format_message(info)

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton(
            "🎧 Послушано",
            callback_data=f"rate_{info['artist']}|{info['title']}"
        )
    )

    bot.send_photo(
        user_id,
        info["cover"],
        caption=caption,
        parse_mode="HTML",
        reply_markup=markup
    )


# ============================================================
# DAILY SEND
# ============================================================

def send_daily_albums():
    users = load_users()
    if not users:
        return

    pair = pick_two_unique()
    if not pair:
        for u in users:
            bot.send_message(u, "📭 Альбомы закончились!")
        return

    for album in pair:
        for u in users:
            send_album_to_user(u, album)


# ============================================================
# CALLBACK HANDLERS (RATING)
# ============================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("rate_"))
def callback_rate(call):
    artist, title = call.data[5:].split("|")

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("❌ Не понравилось", callback_data=f"setrate_{artist}|{title}|bad"),
        InlineKeyboardButton("😐 Норм", callback_data=f"setrate_{artist}|{title}|ok"),
        InlineKeyboardButton("⭐ Супер", callback_data=f"setrate_{artist}|{title}|super"),
    )

    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("setrate_"))
def set_rating(call):
    artist, title, rating = call.data[8:].split("|")
    album_key = f"{artist} — {title}"

    ratings = load_ratings()
    user = str(call.message.chat.id)

    if user not in ratings:
        ratings[user] = {}

    ratings[user][album_key] = rating
    save_ratings(ratings)

    response = {"bad": "❌ Не понравилось", "ok": "😐 Норм", "super": "⭐ Супер"}[rating]
    bot.answer_callback_query(call.id, f"Оценка: {response}")


# ============================================================
# COMMANDS
# ============================================================

@bot.message_handler(commands=["start"])
def start(message):
    add_user(message.chat.id)
    bot.send_message(message.chat.id, "Ты подписан на ежедневные рекомендации!")


@bot.message_handler(commands=["list"])
def list_cmd(message):
    sent = load_sent()
    ratings = load_ratings()
    user = str(message.chat.id)

    text = ""

    for album in sent:
        key = f"{album['artist']} — {album['album']}"

        if user in ratings and key in ratings[user]:
            r = ratings[user][key]
            icon = {"bad": "❌", "ok": "😐", "super": "⭐"}[r]
            text += f"{icon} {key}\n"
        else:
            text += f"• {key}\n"

    bot.send_message(message.chat.id, text or "Пока ничего не отправлялось.")


@bot.message_handler(commands=["random"])
def random_cmd(message):
    albums = load_albums()
    pair = random.sample(albums, 2)

    for album in pair:
        send_album_to_user(message.chat.id, album)


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":
    print("Bot started")
    start_scheduler(send_daily_albums)
    bot.infinity_polling()
