import telebot
from telebot import types
import requests
import random
import threading
import sqlite3
import os

TOKEN = os.environ.get('TOKEN')
KP_API_KEY = os.environ.get('KP_API_KEY')
bot = telebot.TeleBot(TOKEN)

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS movies (chat_id INTEGER, title TEXT, genres TEXT, status TEXT, rating TEXT, UNIQUE(chat_id, title))')
    conn.commit()
    conn.close()

# --- ФУНКЦИИ-ПОМОЩНИКИ ---
def get_stars(rating_str):
    try:
        rating = int(float(rating_str.replace(',', '.')))
        return "⭐️" * (rating // 2) + "🌑" * (5 - (rating // 2))
    except: return "🌑🌑🌑🌑🌑"

def get_want_list(chat_id):
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute('SELECT title, genres FROM movies WHERE chat_id=? AND status="want"', (chat_id,))
    res = {row[0]: row[1].split(',') if row[1] else [] for row in c.fetchall()}
    conn.close()
    return res

def get_watched_list(chat_id):
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute('SELECT title, rating FROM movies WHERE chat_id=? AND status="watched"', (chat_id,))
    res = {row[0]: row[1] for row in c.fetchall()}
    conn.close()
    return res

def is_in_lists(chat_id, title):
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute('SELECT status FROM movies WHERE chat_id=? AND title=?', (chat_id, title))
    res = c.fetchone()
    conn.close()
    return res is not None

def add_want(chat_id, title, genres):
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO movies (chat_id, title, genres, status, rating) VALUES (?, ?, ?, "want", "")', (chat_id, title, ','.join(genres)))
    conn.commit()
    conn.close()

def add_watched(chat_id, title, rating):
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute('SELECT genres FROM movies WHERE chat_id=? AND title=?', (chat_id, title))
    row = c.fetchone()
    genres = row[0] if row else ""
    c.execute('INSERT OR REPLACE INTO movies (chat_id, title, genres, status, rating) VALUES (?, ?, ?, "watched", ?)', (chat_id, title, genres, rating))
    conn.commit()
    conn.close()

def remove_movie(chat_id, title):
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute('DELETE FROM movies WHERE chat_id=? AND title=?', (chat_id, title))
    conn.commit()
    conn.close()

# --- ПОИСК И ВСПОМОГАТЕЛЬНЫЕ ---
movies_cache = {}
tinder_sessions = {}

def delete_after(chat_id, message_id, delay=10):
    def delete_task():
        try: bot.delete_message(chat_id, message_id)
        except: pass
    threading.Timer(delay, delete_task).start()

def search_movie_kp(query=None, random_popular=False):
    headers = {"X-API-KEY": KP_API_KEY, "Content-Type": "application/json"}
    url = f"https://kinopoiskapiunofficial.tech/api/v2.1/films/search-by-keyword?keyword={query}&page=1" if query else f"https://kinopoiskapiunofficial.tech/api/v2.2/films/collections?type=TOP_POPULAR_ALL&page={random.randint(1, 10)}"
    try:
        r = requests.get(url, headers=headers, timeout=5).json()
        items = r.get("films", []) or r.get("items", [])
        if items:
            m = random.choice(items) if random_popular else items[0]
            mid = str(m.get("filmId", m.get("kinopoiskId", random.randint(100000, 999999))))
            data = {"id": mid, "title": m.get("nameRu", m.get("nameOriginal", "Без названия")), "year": m.get("year", "—"), "rating": m.get("rating", m.get("ratingKinopoisk", "0")), "genres": [g.get("genre", "—") for g in m.get("genres", [])], "poster": m.get("posterUrl", None), "overview": m.get("description", "—")}
            movies_cache[mid] = data
            return data
    except: return None

# --- ОСНОВНАЯ ЛОГИКА ---
@bot.message_handler(commands=['start'])
def start(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔍 Найти фильм", "📋 Мои списки", "🎲 Рулетка", "🔥 Тиндер", "📊 Статистика")
    bot.send_message(message.chat.id, "🍿 Кино-дневник готов!", reply_markup=markup)

@bot.message_handler(content_types=['text'])
def handle_menu_text(message):
    chat_id = message.chat.id
    if message.text == "🔍 Найти фильм":
        msg = bot.send_message(chat_id, "Введите название:")
        bot.register_next_step_handler(msg, process_find_from_menu)
    elif message.text == "📋 Мои списки": show_lists_menu(chat_id)
    elif message.text == "🎲 Рулетка": send_roulette(chat_id)
    elif message.text == "🔥 Тиндер": play_tinder(message)
    elif message.text == "📊 Статистика": show_statistics(chat_id)
    else: process_find_from_menu(message)

def process_find_from_menu(message):
    movie = search_movie_kp(message.text.strip())
    if not movie: bot.send_message(message.chat.id, "Ничего не нашел."); return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📍 В 'Хочу'", callback_data=f"want|{movie['id']}"))
    bot.send_photo(message.chat.id, movie['poster'], caption=f"🎬 {movie['title']} ({movie['year']})", reply_markup=markup)

def send_roulette(chat_id, message_id=None):
    want_list = list(get_want_list(chat_id).keys())
    if not want_list: bot.send_message(chat_id, "Список 'Хочу' пуст!"); return
    choice = random.choice(want_list)
    text = f"🎲 *Кино-рулетка сделала выбор!*\n\nПредлагаю посмотреть:\n🎬 *{choice}*"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Посмотрели (Оценить)", callback_data=f"r_watch|{choice[:30]}"),
               types.InlineKeyboardButton("🎬 Трейлер", url=f"https://www.youtube.com/results?search_query={choice}+трейлер"),
               types.InlineKeyboardButton("🔄 Другой", callback_data="r_reroll"))
    if message_id: bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown", reply_markup=markup)
    else: bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)

def show_lists_menu(chat_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📍 Хочу", callback_data="menu_want"),
               types.InlineKeyboardButton("✅ Просмотрено", callback_data="menu_watched"))
    bot.send_message(chat_id, "Выберите список:", reply_markup=markup)

def play_tinder(message):
    movie = search_movie_kp(random_popular=True)
    msg = bot.send_photo(message.chat.id, movie['poster'], caption=f"🔥 {movie['title']}", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("👍", callback_data="tyes"), types.InlineKeyboardButton("👎", callback_data="tno")))
    tinder_sessions[msg.message_id] = {'title': movie['title'], 'genres': movie['genres']}

def show_statistics(chat_id):
    bot.send_message(chat_id, f"📊 Статистика:\n📍 Планы: {len(get_want_list(chat_id))}\n✅ Просмотрено: {len(get_watched_list(chat_id))}")

@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    chat_id, msg_id = call.message.chat.id, call.message.message_id
    parts = call.data.split('|')
    cmd = parts[0]
    
    if cmd == "want":
        movie = movies_cache.get(parts[1])
        if movie:
            add_want(chat_id, movie['title'], movie['genres'])
            new_m = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ Добавлено", callback_data="none"))
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=new_m)
            
    elif cmd == "menu_watched":
        data = get_watched_list(chat_id)
        text = "✅ *Просмотрено:*\n" + "".join([f"{t} | {get_stars(r)}\n" for t, r in data.items()])
        bot.edit_message_text(text or "Пусто", chat_id, msg_id, parse_mode="Markdown")
        
    elif cmd == "r_reroll": send_roulette(chat_id, msg_id)
    elif cmd == "r_watch":
        msg = bot.send_message(chat_id, f"Оценка (1-10) для {parts[1]}:")
        bot.register_next_step_handler(msg, lambda m: process_rating(m, parts[1]))

def process_rating(message, title):
    add_watched(message.chat.id, title, message.text)
    bot.send_message(message.chat.id, "✅ Сохранено!")

if __name__ == '__main__':
    init_db()
    bot.infinity_polling()
