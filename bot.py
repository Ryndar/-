import telebot
from telebot import types
import requests
import random
import threading
import os
import libsql_client

TOKEN = os.environ.get('TOKEN')
KP_API_KEY = os.environ.get('KP_API_KEY')
TURSO_URL = os.environ.get('TURSO_URL')
TURSO_TOKEN = os.environ.get('TURSO_TOKEN')

bot = telebot.TeleBot(TOKEN)
db = libsql_client.create_client_sync(url=TURSO_URL, auth_token=TURSO_TOKEN)

# --- БАЗА ДАННЫХ (TURSO) ---
def init_db():
    db.execute('CREATE TABLE IF NOT EXISTS movies (chat_id INTEGER, title TEXT, genres TEXT, status TEXT, rating TEXT, UNIQUE(chat_id, title))')

def add_want(chat_id, title, genres):
    genres_str = ','.join(genres) if isinstance(genres, list) else str(genres)
    db.execute('INSERT OR REPLACE INTO movies (chat_id, title, genres, status, rating) VALUES (?, ?, ?, "want", "")', [chat_id, title, genres_str])

def add_watched(chat_id, title, rating="—"):
    res = db.execute('SELECT genres FROM movies WHERE chat_id=? AND title=?', [chat_id, title])
    genres = res.rows[0][0] if res.rows else ""
    db.execute('INSERT OR REPLACE INTO movies (chat_id, title, genres, status, rating) VALUES (?, ?, ?, "watched", ?)', [chat_id, title, genres, rating])

def get_want_list(chat_id):
    res = db.execute('SELECT title FROM movies WHERE chat_id=? AND status="want"', [chat_id])
    return [row[0] for row in res.rows]

def get_watched_list(chat_id):
    res = db.execute('SELECT title, rating FROM movies WHERE chat_id=? AND status="watched"', [chat_id])
    return {row[0]: row[1] for row in res.rows}

def remove_movie(chat_id, title):
    db.execute('DELETE FROM movies WHERE chat_id=? AND title=?', [chat_id, title])

# --- СОСТОЯНИЯ И КЭШ ---
movies_cache = {}
roulette_sessions = {}  # Исправляет баг с обрезкой названия фильма
tinder_sessions = {}

def search_movie_kp(query=None, random_popular=False):
    headers = {"X-API-KEY": KP_API_KEY, "Content-Type": "application/json"}
    url = f"https://kinopoiskapiunofficial.tech/api/v2.1/films/search-by-keyword?keyword={query}&page=1" if query else f"https://kinopoiskapiunofficial.tech/api/v2.2/films/collections?type=TOP_POPULAR_ALL&page={random.randint(1, 10)}"
    try:
        r = requests.get(url, headers=headers, timeout=5).json()
        items = r.get("films", []) or r.get("items", [])
        if items:
            m = random.choice(items) if random_popular else items[0]
            mid = str(m.get("filmId", m.get("kinopoiskId", random.randint(100000, 999999))))
            data = {
                "id": mid, 
                "title": m.get("nameRu", m.get("nameEn", "Без названия")), 
                "year": m.get("year", "—"), 
                "rating": m.get("rating", "0"), 
                "genres": [g.get("genre", "другое") for g in m.get("genres", [])], 
                "poster": m.get("posterUrl", None), 
                "overview": m.get("description", "—")
            }
            movies_cache[mid] = data
            return data
    except Exception as e:
        print(f"Ошибка API: {e}")
        return None

# --- МЕНЮ И ОБРАБОТЧИКИ ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔍 Найти фильм", "📋 Мои списки", "🎲 Рулетка", "🔥 Тиндер", "📊 Статистика")
    bot.send_message(message.chat.id, "🍿 Кино-дневник готов!", reply_markup=markup)

@bot.message_handler(content_types=['text'])
def handle_menu_text(message):
    if message.text == "🔍 Найти фильм":
        msg = bot.send_message(message.chat.id, "Введите название фильма:")
        bot.register_next_step_handler(msg, process_find_from_menu)
    elif message.text == "📋 Мои списки": 
        show_lists_menu(message.chat.id)
    elif message.text == "🎲 Рулетка": 
        send_roulette(message.chat.id)
    elif message.text == "🔥 Тиндер": 
        play_tinder(message.chat.id)
    elif message.text == "📊 Статистика": 
        show_statistics(message.chat.id)
    else: 
        process_find_from_menu(message)

def process_find_from_menu(message):
    if message.text in ["🔍 Найти фильм", "📋 Мои списки", "🎲 Рулетка", "🔥 Тиндер", "📊 Статистика"]:
        handle_menu_text(message)
        return
    movie = search_movie_kp(message.text.strip())
    if not movie: 
        bot.send_message(message.chat.id, "Ничего не нашлось. Попробуйте другое название.")
        return
    markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("📍 В 'Хочу'", callback_data=f"want|{movie['id']}"))
    bot.send_photo(message.chat.id, movie['poster'], caption=f"🎬 *{movie['title']}* ({movie['year']})\n⭐️ Рейтинг: {movie['rating']}", parse_mode="Markdown", reply_markup=markup)

def send_roulette(chat_id, message_id=None):
    want_list = get_want_list(chat_id)
    if not want_list: 
        bot.send_message(chat_id, "Ваш список 'Хочу' пуст! Сначала добавьте туда фильмы.")
        return
    choice = random.choice(want_list)
    roulette_sessions[chat_id] = choice  # Сохраняем выбор в сессию
    
    markup = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("✅ Посмотрел", callback_data="r_watch"), 
        types.InlineKeyboardButton("🔄 Другой", callback_data="r_reroll")
    )
    text = f"🎲 Предлагаю посмотреть:\n\n🍿 *{choice}*"
    if message_id: 
        bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown", reply_markup=markup)
    else: 
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)

def show_lists_menu(chat_id):
    markup = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("📍 Хочу посмотреть", callback_data="menu_want"), 
        types.InlineKeyboardButton("✅ Просмотрено", callback_data="menu_watched")
    )
    bot.send_message(chat_id, "Какой список открыть?", reply_markup=markup)

def show_statistics(chat_id):
    bot.send_message(chat_id, f"📊 *Ваша статистика:*\n\n📍 В планах: {len(get_want_list(chat_id))}\n✅ Просмотрено: {len(get_watched_list(chat_id))}", parse_mode="Markdown")

def play_tinder(chat_id):
    # Упрощенная заглушка для Тиндера (случайный популярный фильм)
    movie = search_movie_kp(random_popular=True)
    if not movie:
        bot.send_message(chat_id, "Не удалось загрузить фильм для Тиндера.")
        return
    markup = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("❌ Мимо", callback_data="tinder_skip"),
        types.InlineKeyboardButton("💚 Хочу!", callback_data=f"want|{movie['id']}")
    )
    bot.send_photo(chat_id, movie['poster'], caption=f"🔥 *Тиндер*\n\n🎬 *{movie['title']}*\n📝 {movie['overview'][:200]}...", parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    chat_id, msg_id = call.message.chat.id, call.message.message_id
    parts = call.data.split('|')
    cmd = parts[0]
    
    if cmd == "want":
        movie = movies_cache.get(parts[1])
        if movie:
            add_want(chat_id, movie['title'], movie['genres'])
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ В списке 'Хочу'", callback_data="none")))
            bot.answer_callback_query(call.id, "Добавлено!")
    
    elif cmd == "menu_want":
        data = get_want_list(chat_id)
        text = "📍 *Ваш список 'Хочу':*\n\n" + "\n".join([f"• {title}" for title in data]) if data else "Список 'Хочу' пока пуст."
        bot.edit_message_text(text, chat_id, msg_id, parse_mode="Markdown")
        
    elif cmd == "menu_watched":
        data = get_watched_list(chat_id)
        text = "✅ *Просмотренные фильмы:*\n\n" + "\n".join([f"• {t} (⭐️ {r})" for t, r in data.items()]) if data else "Вы еще не отметили ни одного фильма."
        bot.edit_message_text(text, chat_id, msg_id, parse_mode="Markdown")
        
    elif cmd == "r_reroll": 
        send_roulette(chat_id, msg_id)
        
    elif cmd == "r_watch":
        title = roulette_sessions.get(chat_id)
        if title:
            add_watched(chat_id, title, rating="Посмотрено")
            bot.edit_message_text(f"🎉 Отлично! Фильм *{title}* перенесен в просмотренные.", chat_id, msg_id, parse_mode="Markdown")
            roulette_sessions.pop(chat_id, None)
            
    elif cmd == "tinder_skip":
        bot.delete_message(chat_id, msg_id)
        play_tinder(chat_id)

if __name__ == '__main__':
    init_db()
    print("Бот успешно запущен!")
    bot.infinity_polling()
