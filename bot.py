import telebot
from telebot import types
import requests
import random
import os
import gspread
from google.oauth2.service_account import Credentials
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from collections import Counter

# --- ФЕЙКОВЫЙ СЕРВЕР ДЛЯ RENDER ---
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is alive and well!")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()

def keep_alive():
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.environ.get('TOKEN')
KP_API_KEY = os.environ.get('KP_API_KEY')
GOOGLE_CREDENTIALS = os.environ.get('GOOGLE_CREDENTIALS')

bot = telebot.TeleBot(TOKEN)
sheet = None

# --- ИНИЦИАЛИЗАЦИЯ GOOGLE ТАБЛИЦЫ ---
try:
    creds_dict = json.loads(GOOGLE_CREDENTIALS)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    
    # Укажи здесь ID своей таблицы:
    sheet = gc.open_by_key("1rrIF_fxUQzkmFkgY6FWYmrTBNC4ryuoiM3hUXwk98e0").sheet1
    print("✅ Успешное подключение к Google Таблице!")
except Exception as e:
    print(f"❌ Ошибка подключения к Google Таблицам: {e}")
    sheet = None

# --- ФУНКЦИИ РАБОТЫ С ТАБЛИЦЕЙ ---
def init_db():
    if not sheet: return
    if len(sheet.get_all_values()) == 0:
        sheet.append_row(["chat_id", "title", "genres", "status", "rating"])

def add_want(chat_id, title, genres):
    if not sheet: return
    genres_str = ','.join(genres) if isinstance(genres, list) else str(genres)
    rows = sheet.get_all_values()
    
    for idx, row in enumerate(rows, start=1):
        if len(row) >= 2 and str(row[0]) == str(chat_id) and str(row[1]) == str(title):
            sheet.update_cell(idx, 4, "want")
            return
            
    sheet.append_row([str(chat_id), str(title), genres_str, "want", "—"])

def add_watched(chat_id, title, rating="—"):
    if not sheet: return
    rows = sheet.get_all_values()
    
    for idx, row in enumerate(rows, start=1):
        if len(row) >= 2 and str(row[0]) == str(chat_id) and str(row[1]) == str(title):
            sheet.update_cell(idx, 4, "watched")
            sheet.update_cell(idx, 5, str(rating))
            return
            
    sheet.append_row([str(chat_id), str(title), "", "watched", str(rating)])

def get_want_list(chat_id):
    if not sheet: return []
    rows = sheet.get_all_values()
    if len(rows) <= 1: return []
    return [row[1] for row in rows[1:] if len(row) >= 4 and str(row[0]) == str(chat_id) and str(row[3]) == "want"]

def get_watched_list(chat_id):
    if not sheet: return {}
    rows = sheet.get_all_values()
    if len(rows) <= 1: return {}
    return {row[1]: row[4] for row in rows[1:] if len(row) >= 5 and str(row[0]) == str(chat_id) and str(row[3]) == "watched"}

def get_favorite_genre(chat_id):
    if not sheet: return "Не определен"
    rows = sheet.get_all_values()
    if len(rows) <= 1: return "Нет данных"
    
    all_genres = []
    for row in rows[1:]:
        if str(row[0]) == str(chat_id) and len(row) >= 3 and row[2]:
            all_genres.extend([g.strip().lower() for g in row[2].split(',') if g.strip()])
            
    if not all_genres: return "Киноман без предвзятостей"
    most_common = Counter(all_genres).most_common(1)
    return most_common[0][0].capitalize() if most_common else "Не определен"

# --- ДВИЖОК ПОИСКА КИНОПОИСКА ---
movies_cache = {}
roulette_sessions = {}

def search_movie_kp(query=None, random_popular=False):
    headers = {"X-API-KEY": KP_API_KEY, "Content-Type": "application/json"}
    url = f"https://kinopoiskapiunofficial.tech/api/v2.1/films/search-by-keyword?keyword={query}&page=1" if query else f"https://kinopoiskapiunofficial.tech/api/v2.2/films/collections?type=TOP_POPULAR_ALL&page={random.randint(1, 3)}"
    try:
        r = requests.get(url, headers=headers, timeout=5).json()
        items = r.get("films", []) or r.get("items", [])
        if items:
            m = random.choice(items) if random_popular else items[0]
            mid = str(m.get("filmId", m.get("kinopoiskId", random.randint(100000, 999999))))
            
            genres_list = [g.get("genre", "другое") for g in m.get("genres", [])]
            desc = m.get("description", "Описание сюжета отсутствует.")
            if desc:
                desc = desc.replace('*', '').replace('_', '').replace('`', '').strip()
            
            data = {
                "id": mid, 
                "title": m.get("nameRu", m.get("nameEn", "Без названия")), 
                "year": m.get("year", "—"), 
                "rating": m.get("rating", "0"), 
                "genres": genres_list, 
                "poster": m.get("posterUrl", None),
                "description": desc
            }
            movies_cache[mid] = data
            return data
    except Exception as e:
        print(f"Ошибка API Кинопоиска: {e}")
        return None

# --- КОМАНДЫ И МЕНЮ ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("🔍 Найти фильм", "📋 Мои списки", "🎲 Рулетка", "🔥 Тиндер", "📊 Статистика")
    
    welcome_text = (
        "✨ *ДОБРО ПОЖАЛОВАТЬ В КИНО-ДНЕВНИК* ✨\n"
        "═════════════════════════════\n"
        "Твой персональный гид по кинематографу и трекер просмотренных фильмов.\n\n"
        "▫️ Помогаю выбирать случайные фильмы\n"
        "▫️ Храню подробные описания и сюжеты\n"
        "▫️ Синхронизирую всё с твоей Google Таблицей\n"
        "═════════════════════════════\n"
        " Используй нижнее меню для навигации 👇"
    )
    bot.send_message(message.chat.id, welcome_text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(content_types=['text'])
def handle_menu_text(message):
    if message.text == "🔍 Найти фильм":
        msg = bot.send_message(message.chat.id, "🎬 Напиши название фильма или сериала:")
        bot.register_next_step_handler(msg, process_find_from_menu)
    elif message.text == "📋 Мои списки": show_lists_menu(message.chat.id)
    elif message.text == "🎲 Рулетка": send_roulette(message.chat.id)
    elif message.text == "🔥 Тиндер": play_tinder(message.chat.id)
    elif message.text == "📊 Статистика": show_statistics(message.chat.id)
    else: process_find_from_menu(message)

def process_find_from_menu(message):
    if message.text in ["🔍 Найти фильм", "📋 Мои списки", "🎲 Рулетка", "🔥 Тиндер", "📊 Статистика"]:
        handle_menu_text(message)
        return
        
    waiting = bot.send_message(message.chat.id, "⚡ Ищу фильм в базе данных...")
    movie = search_movie_kp(message.text.strip())
    bot.delete_message(message.chat.id, waiting.message_id)
    
    if not movie: 
        bot.send_message(message.chat.id, "❌ Ничего не нашлось. Попробуй другое название.")
        return
        
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📍 Добавить в 'Хочу'", callback_data=f"want|{movie['id']}"))
    
    short_desc = movie['description'][:450] + "..." if len(movie['description']) > 450 else movie['description']
    caption = (
        f"🎬 *{movie['title']}*\n"
        f"═══════════════════════════\n"
        f"📅 Год выпуска: `{movie['year']}`\n"
        f"📈 Рейтинг КП: `{movie['rating']}`\n"
        f"🎭 Жанры: _{', '.join(movie['genres'])}_\n"
        f"═══════════════════════════\n"
        f"📝 *Сюжет:* {short_desc}"
    )
    bot.send_photo(message.chat.id, movie['poster'], caption=caption, parse_mode="Markdown", reply_markup=markup)

def send_roulette(chat_id, message_id=None):
    want_list = get_want_list(chat_id)
    if not want_list: 
        bot.send_message(chat_id, "🫙 Твой список 'Хочу смотреть' пуст! Добавь туда фильмы через поиск.")
        return
        
    choice = random.choice(want_list)
    roulette_sessions[chat_id] = choice
    
    movie = search_movie_kp(choice)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Посмотрел", callback_data="r_watch"), 
        types.InlineKeyboardButton("🔄 Крутить ещё", callback_data="r_reroll")
    )
    
    if movie:
        short_desc = movie['description'][:450] + "..." if len(movie['description']) > 450 else movie['description']
        caption = (
            f"🎲 *РУЛЕТКА ВЫБРАЛА ФИЛЬМ:*\n"
            f"🌟 *{movie['title']}* ({movie['year']})\n"
            f"═══════════════════════════\n"
            f"📈 Рейтинг: `{movie['rating']}`\n"
            f"🎭 Жанры: _{', '.join(movie['genres'])}_\n"
            f"═══════════════════════════\n"
            f"📝 *Сюжет:* {short_desc}"
        )
        if message_id:
            try: bot.delete_message(chat_id, message_id)
            except: pass
            bot.send_photo(chat_id, movie['poster'], caption=caption, parse_mode="Markdown", reply_markup=markup)
        else:
            bot.send_photo(chat_id, movie['poster'], caption=caption, parse_mode="Markdown", reply_markup=markup)
    else:
        text = f"🎲 *Рулетка выбрала:* *{choice}*\n\n_(Не удалось загрузить постер и синопсис)_"
        if message_id: bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown", reply_markup=markup)
        else: bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)

def show_lists_menu(chat_id, message_id=None):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📍 Хочу посмотреть", callback_data="menu_want"), 
        types.InlineKeyboardButton("✅ Просмотрено", callback_data="menu_watched")
    )
    text = "📂 *Выберите интересующую вас категорию подборок:*"
    if message_id:
        bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown", reply_markup=markup)
    else:
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)

def show_statistics(chat_id):
    w_count = len(get_want_list(chat_id))
    d_count = len(get_watched_list(chat_id))
    fav_genre = get_favorite_genre(chat_id)
    
    stats_text = (
        f"📊 *ЛИЧНАЯ КИНО-СТАТИСТИКА*\n"
        f"═══════════════════════════\n"
        f"📌 В планах посмотреть: `{w_count}` фильмов\n"
        f"🎬 Уже просмотрено: `{d_count}` фильмов\n"
        f"🔥 Любимый жанр: *{fav_genre}*\n"
        f"═══════════════════════════\n"
        f"🍿 _Продолжай наполнять свой дневник!_"
    )
    bot.send_message(chat_id, stats_text, parse_mode="Markdown")

def play_tinder(chat_id, message_id=None):
    movie = search_movie_kp(random_popular=True)
    if not movie: 
        bot.send_message(chat_id, "⚠️ Не удалось загрузить фильм. Попробуй еще раз.")
        return
        
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("👎 Пропустить", callback_data="tinder_skip"),
        types.InlineKeyboardButton("💚 Хочу смотреть", callback_data=f"want|{movie['id']}")
    )
    
    short_desc = movie['description'][:400] + "..." if len(movie['description']) > 400 else movie['description']
    caption = (
        f"🔥 *КИНО-ТИНДЕР*\n"
        f"═══════════════════════════\n"
        f"🎬 *{movie['title']}* ({movie['year']})\n"
        f"📈 Рейтинг: `{movie['rating']}`\n"
        f"🎭 Жанры: _{', '.join(movie['genres'])}_\n"
        f"═══════════════════════════\n"
        f"📝 *Сюжет:* {short_desc}"
    )
    if message_id:
        try: bot.delete_message(chat_id, message_id)
        except: pass
    bot.send_photo(chat_id, movie['poster'], caption=caption, parse_mode="Markdown", reply_markup=markup)

# --- ОБРАБОТЧИК НАЖАТИЙ НА КНОПКИ ---
@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    chat_id, msg_id = call.message.chat.id, call.message.message_id
    parts = call.data.split('|')
    cmd = parts[0]
    
    if cmd == "want":
        movie = movies_cache.get(parts[1])
        if movie:
            add_want(chat_id, movie['title'], movie['genres'])
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("✅ Фильм добавлен в планы", callback_data="none")
            ))
        bot.answer_callback_query(call.id, "Добавлено!")
    
    elif cmd == "menu_want":
        data = get_want_list(chat_id)
        text = "📌 *ТВОЙ СПИСОК ЖЕЛАЕМОГО:*\n═══════════════════════════\n" + "\n".join([f"🍿 {t}" for t in data]) if data else "Твой список желаемого пока пуст 🎬"
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Назад к категориям", callback_data="back_to_lists"))
        bot.edit_message_text(text, chat_id, msg_id, parse_mode="Markdown", reply_markup=markup)
        bot.answer_callback_query(call.id)
        
    elif cmd == "menu_watched":
        data = get_watched_list(chat_id)
        text = "🎬 *ПРОСМОТРЕННЫЕ ШЕДЕВРЫ:*\n═══════════════════════════\n" + "\n".join([f"🔹 {t} — *{r}*" for t, r in data.items()]) if data else "Ты еще не отметил ни одного фильма."
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Назад к категориям", callback_data="back_to_lists"))
        bot.edit_message_text(text, chat_id, msg_id, parse_mode="Markdown", reply_markup=markup)
        bot.answer_callback_query(call.id)
        
    elif cmd == "back_to_lists":
        show_lists_menu(chat_id, msg_id)
        bot.answer_callback_query(call.id)
        
    elif cmd == "r_reroll": 
        send_roulette(chat_id, msg_id)
        bot.answer_callback_query(call.id)
        
    elif cmd == "r_watch":
        title = roulette_sessions.get(chat_id)
        if not title:
            bot.send_message(chat_id, "⚠️ Сессия истекла. Запусти рулетку заново.")
            bot.answer_callback_query(call.id)
            return
            
        # 10-БАЛЛЬНАЯ СИСТЕМА ОЦЕНОК (Выстраивается в 2 ряда по 5 кнопок автоматически)
        markup = types.InlineKeyboardMarkup(row_width=5)
        markup.add(
            types.InlineKeyboardButton("1️⃣", callback_data="rate|1"),
            types.InlineKeyboardButton("2️⃣", callback_data="rate|2"),
            types.InlineKeyboardButton("3️⃣", callback_data="rate|3"),
            types.InlineKeyboardButton("4️⃣", callback_data="rate|4"),
            types.InlineKeyboardButton("5️⃣", callback_data="rate|5"),
            types.InlineKeyboardButton("6️⃣", callback_data="rate|6"),
            types.InlineKeyboardButton("7️⃣", callback_data="rate|7"),
            types.InlineKeyboardButton("8️⃣", callback_data="rate|8"),
            types.InlineKeyboardButton("9️⃣", callback_data="rate|9"),
            types.InlineKeyboardButton("🔟", callback_data="rate|10")
        )
        try: bot.delete_message(chat_id, msg_id)
        except: pass
        bot.send_message(chat_id, f"⭐ *Оцени фильм по 10-балльной шкале:*\n\n🍿 Какую оценку заслуживает *{title}*?", parse_mode="Markdown", reply_markup=markup)
        bot.answer_callback_query(call.id)

    elif cmd == "rate":
        # Форматируем красивый вывод оценки
        rating_score = f"⭐ {parts[1]}/10"
        title = roulette_sessions.get(chat_id)
        
        if title:
            add_watched(chat_id, title, rating=rating_score)
            bot.edit_message_text(f"🎉 Отлично! Фильм *{title}* перенесен в архив с оценкой *{rating_score}*!", chat_id, msg_id, parse_mode="Markdown")
            roulette_sessions.pop(chat_id, None)
        bot.answer_callback_query(call.id, "Оценка зафиксирована!")
            
    elif cmd == "tinder_skip":
        play_tinder(chat_id, msg_id)
        bot.answer_callback_query(call.id)

if __name__ == '__main__':
    init_db()
    keep_alive() 
    print("Бот успешно запущен на обновленном дизайне!")
    bot.infinity_polling()
