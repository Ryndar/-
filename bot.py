import telebot
from telebot import types
import requests
import random
import threading
import sqlite3

TOKEN = '8435975783:AAHcrtHRtu3aWbQ2ZgFY3m748AFIbSDXMQ4'
KP_API_KEY = 'bd3ae916-cf12-4969-8c6e-47cf08e65734'

bot = telebot.TeleBot(TOKEN)

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('movies.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS movies (
            chat_id INTEGER,
            title TEXT,
            genres TEXT,
            status TEXT, 
            rating TEXT,
            UNIQUE(chat_id, title)
        )
    ''')
    conn.commit()
    conn.close()

# --- ФУНКЦИИ ДЛЯ РАБОТЫ С БАЗОЙ ---
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
    genres_str = ','.join(genres)
    c.execute('INSERT OR REPLACE INTO movies (chat_id, title, genres, status, rating) VALUES (?, ?, ?, "want", "")', (chat_id, title, genres_str))
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

# --- ВРЕМЕННАЯ ПАМЯТЬ ---
movies_cache = {} 
tinder_sessions = {}

def get_tinder_session(chat_id):
    if chat_id not in tinder_sessions:
        tinder_sessions[chat_id] = {}
    return tinder_sessions[chat_id]

# --- УМНОЕ АВТОУДАЛЕНИЕ ---
def delete_after(chat_id, message_id, delay=10):
    def delete_task():
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass 
    timer = threading.Timer(delay, delete_task)
    timer.start()

# --- ПОИСК НА КИНОПОИСКЕ ---
def search_movie_kp(query=None, random_popular=False):
    headers = {"X-API-KEY": KP_API_KEY, "Content-Type": "application/json"}
    
    if query:
        url = f"https://kinopoiskapiunofficial.tech/api/v2.1/films/search-by-keyword?keyword={query}&page=1"
    else:
        page = random.randint(1, 10)
        url = f"https://kinopoiskapiunofficial.tech/api/v2.2/films/collections?type=TOP_POPULAR_ALL&page={page}"

    try:
        response = requests.get(url, headers=headers, timeout=5).json()
        results = response.get("films", []) or response.get("items", [])
        
        if results:
            movie = random.choice(results) if random_popular else results[0]
            movie_id = str(movie.get("filmId", movie.get("kinopoiskId", random.randint(100000, 999999))))
            genres = [g.get("genre", "другое") for g in movie.get("genres", [])]
            rating = movie.get("rating", movie.get("ratingKinopoisk", "Нет оценки"))
            if rating == 'null' or not rating: rating = "Нет оценки"
            year = movie.get("year", "Неизвестно")
            overview = movie.get("description", "Описание доступно на сайте Кинопоиска.")
            if not overview or overview == 'null': overview = "Описание доступно на сайте Кинопоиска."

            movie_data = {
                "id": movie_id,
                "title": movie.get("nameRu", movie.get("nameOriginal", "Без названия")),
                "year": year,
                "rating": rating,
                "overview": overview,
                "poster": movie.get("posterUrl", None),
                "genres": genres
            }
            
            movies_cache[movie_id] = movie_data
            return movie_data
    except Exception as e:
        print("Ошибка API Кинопоиска:", e)
    return None

# --- ГЛАВНОЕ МЕНЮ ---
def get_main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("🔍 Найти фильм"),
        types.KeyboardButton("📋 Мои списки"),
        types.KeyboardButton("🎲 Рулетка"),
        types.KeyboardButton("🔥 Тиндер"),
        types.KeyboardButton("📊 Статистика")
    )
    return markup

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    text = (
        "🍿 *Добро пожаловать в Кино-Дневник!*\n\n"
        "Я помогу вам не забыть, что вы хотели посмотреть, "
        "и сохраню ваши впечатления.\n\n"
        "👇 _Используйте кнопки меню ниже для управления._"
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=get_main_menu())

# --- УМНАЯ РУЛЕТКА ---
def send_roulette(chat_id, message_id=None):
    want_list = list(get_want_list(chat_id).keys())
    
    if not want_list:
        text = "Ваш список 'Хочу посмотреть' пока пуст! Сначала добавьте фильмы."
        if message_id:
            bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
        else:
            msg = bot.send_message(chat_id, text)
            delete_after(chat_id, msg.message_id, 5)
        return

    choice = random.choice(want_list)
    text = f"🎲 *Кино-рулетка сделала выбор!*\n\nПредлагаю посмотреть:\n🎬 *{choice}*"
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    # Используем укороченное название для кнопки, чтобы не превысить лимит
    markup.add(
        types.InlineKeyboardButton("✅ Посмотрели (Оценить)", callback_data=f"r_watch|{choice[:30]}"),
        types.InlineKeyboardButton("🔄 Выбрать другой фильм", callback_data="r_reroll")
    )
    
    if message_id:
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="Markdown", reply_markup=markup)
    else:
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)

# --- ОБРАБОТЧИК МЕНЮ ---
@bot.message_handler(content_types=['text'])
def handle_menu_text(message):
    text = message.text
    chat_id = message.chat.id
    
    if text == "🔍 Найти фильм":
        msg = bot.send_message(chat_id, "Введите название фильма:")
        bot.register_next_step_handler(msg, process_find_from_menu)
        delete_after(chat_id, msg.message_id, 15)
        
    elif text == "📋 Мои списки":
        show_lists_menu(chat_id)
        
    elif text == "🎲 Рулетка":
        send_roulette(chat_id)
        
    elif text == "🔥 Тиндер":
        play_tinder(message)
        
    elif text == "📊 Статистика":
        show_statistics(chat_id)
        
    else:
        if not message.text.startswith('/'):
            process_find_from_menu(message)

# --- ЛИЧНАЯ СТАТИСТИКА ---
def show_statistics(chat_id):
    want_count = len(get_want_list(chat_id))
    watched_data = get_watched_list(chat_id)
    watched_count = len(watched_data)
    
    avg_rating = 0
    if watched_count > 0:
        total_score = 0
        valid_scores = 0
        for r in watched_data.values():
            try:
                total_score += float(r.replace(',', '.'))
                valid_scores += 1
            except:
                pass
        if valid_scores > 0:
            avg_rating = round(total_score / valid_scores, 1)

    text = (
        "📊 *ВАША КИНО-СТАТИСТИКА*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📍 В планах на просмотр: *{want_count}*\n"
        f"✅ Просмотрено фильмов: *{watched_count}*\n"
        f"⭐️ Ваш средний балл: *{avg_rating} из 10*\n"
    )
    bot.send_message(chat_id, text, parse_mode="Markdown")

# --- ПОИСК И КАРТОЧКА ФИЛЬМА ---
def process_find_from_menu(message):
    query = message.text.strip()
    movie = search_movie_kp(query=query)
    
    if not movie:
        msg = bot.reply_to(message, "Ничего не нашел 😔\n💡 *Совет:* Напишите 1-2 главных слова из названия.")
        delete_after(message.chat.id, msg.message_id, 12)
        return

    chat_id = message.chat.id
    title = movie['title']
    movie_id = movie['id']

    text = (
        f"🎬 *{title}* ({movie['year']})\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎭 *Жанры:* {', '.join(movie['genres']).capitalize()}\n"
        f"⭐️ *Рейтинг КП:* {movie['rating']}\n\n"
        f"_{movie['overview'][:250]}..._"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    if is_in_lists(chat_id, title):
        btn_del = types.InlineKeyboardButton("❌ Убрать из списков", callback_data=f"del|{movie_id}")
        markup.add(btn_del)
    else:
        btn_want = types.InlineKeyboardButton("📍 В 'Хочу'", callback_data=f"want|{movie_id}")
        btn_watched = types.InlineKeyboardButton("✅ Просмотрено", callback_data=f"watched|{movie_id}")
        markup.add(btn_want, btn_watched)

    if movie['poster']:
        bot.send_photo(chat_id, movie['poster'], caption=text, parse_mode="Markdown", reply_markup=markup)
    else:
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)

# --- ИНТЕРАКТИВНОЕ МЕНЮ СПИСКОВ ---
def show_lists_menu(chat_id, message_id=None):
    text = "📋 *Управление списками*\nВыберите категорию для просмотра:"
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📍 Список «Хочу посмотреть»", callback_data="menu_want"),
        types.InlineKeyboardButton("✅ Список «Просмотрено»", callback_data="menu_watched"),
        types.InlineKeyboardButton("🎭 Фильтр по жанрам", callback_data="menu_genres")
    )
    
    if message_id:
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="Markdown", reply_markup=markup)
    else:
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)

# --- ТИНДЕР ---
def play_tinder(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "🎲 Подбираю случайный популярный фильм...")
    movie = search_movie_kp(random_popular=True)
    
    if not movie:
        msg = bot.send_message(chat_id, "Не удалось найти фильм.")
        delete_after(chat_id, msg.message_id, 5)
        return

    text = f"🔥 *КИНО-ТИНДЕР* 🔥\n━━━━━━━━━━━━━━━━━━\n🎬 *{movie['title']}* ({movie['year']})\n🎭 Жанры: {', '.join(movie['genres'])}\n⭐️ КП: {movie['rating']}"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("👍 Буду", callback_data="tyes"),
        types.InlineKeyboardButton("👎 Не буду", callback_data="tno")
    )

    if movie['poster']:
        msg = bot.send_photo(chat_id, movie['poster'], caption=text, parse_mode="Markdown", reply_markup=markup)
    else:
        msg = bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)

    tinder = get_tinder_session(chat_id)
    tinder[msg.message_id] = {'title': movie['title'], 'genres': movie['genres'], 'yes': set(), 'no': set()}

# --- ОБРАБОТКА ВСЕХ INLINE КНОПОК ---
@bot.callback_query_handler(func=lambda call: True)
def handle_buttons(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    msg_id = call.message.message_id
    
    parts = call.data.split('|')
    cmd = parts[0]

    # --- Обработка рулетки ---
    if cmd == "r_reroll":
        # Пользователь нажал "Другой фильм", меняем текущее сообщение на новое
        send_roulette(chat_id, message_id=msg_id)

    elif cmd == "r_watch":
        title_short = parts[1]
        want_data = get_want_list(chat_id)
        
        # Восстанавливаем полное название из укороченного
        full_title = None
        for title in want_data.keys():
            if title.startswith(title_short):
                full_title = title
                break
                
        if full_title:
            bot.answer_callback_query(call.id)
            msg = bot.send_message(chat_id, f"Какую оценку (от 1 до 10) поставите фильму *{full_title}*?", parse_mode="Markdown")
            bot.register_next_step_handler(msg, process_rating, full_title)
            # Удаляем сообщение с рулеткой, чтобы чат оставался чистым
            bot.delete_message(chat_id, msg_id)
        else:
            bot.answer_callback_query(call.id, "Ошибка! Фильм не найден в вашем списке.", show_alert=True)

    # --- Навигация по спискам ---
    elif cmd == "menu_want":
        want_data = get_want_list(chat_id)
        text = "📍 *Хочу посмотреть:*\n━━━━━━━━━━━━━━━━━━\n"
        if want_data:
            for i, title in enumerate(want_data.keys(), 1):
                text += f"{i}. {title}\n"
        else:
            text += "_Список пуст_"
            
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu"))
        bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text, parse_mode="Markdown", reply_markup=markup)

    elif cmd == "menu_watched":
        watched_data = get_watched_list(chat_id)
        text = "✅ *Просмотрено:*\n━━━━━━━━━━━━━━━━━━\n"
        if watched_data:
            for i, (title, rating) in enumerate(watched_data.items(), 1):
                text += f"{i}. {title} (⭐️ {rating})\n"
        else:
            text += "_Список пуст_"
            
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu"))
        bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text, parse_mode="Markdown", reply_markup=markup)

    elif cmd == "menu_genres":
        want_data = get_want_list(chat_id)
        all_genres = set()
        for genres in want_data.values():
            all_genres.update(genres)
            
        markup = types.InlineKeyboardMarkup(row_width=2)
        if not all_genres:
            bot.answer_callback_query(call.id, "Сначала добавьте фильмы в список!", show_alert=True)
            return
            
        buttons = []
        for g in sorted(all_genres):
            buttons.append(types.InlineKeyboardButton(g.capitalize(), callback_data=f"show_g|{g[:15]}"))
        markup.add(*buttons)
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu"))
        
        bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text="🎭 *Выберите жанр:*", parse_mode="Markdown", reply_markup=markup)

    elif cmd == "show_g":
        genre_filter = parts[1]
        want_data = get_want_list(chat_id)
        text = f"🎭 *Жанр: {genre_filter.capitalize()}*\n━━━━━━━━━━━━━━━━━━\n"
        found = False
        for title, genres in want_data.items():
            if any(genre_filter in g.lower() for g in genres):
                text += f"— {title}\n"
                found = True
        if not found: text += "_Ничего не найдено_"
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 К жанрам", callback_data="menu_genres"))
        bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text, parse_mode="Markdown", reply_markup=markup)

    elif cmd == "back_to_menu":
        show_lists_menu(chat_id, message_id=msg_id)

    # --- Добавление / Удаление фильмов ---
    elif cmd in ["want", "watched", "del"]:
        movie_id = parts[1]
        movie = movies_cache.get(movie_id)
        
        if not movie:
            bot.answer_callback_query(call.id, "Кнопка устарела, найдите фильм заново!", show_alert=True)
            return
            
        title = movie['title']
        genres = movie['genres']

        if cmd == "want":
            if not is_in_lists(chat_id, title):
                add_want(chat_id, title, genres)
                bot.answer_callback_query(call.id, f"«{title}» добавлен в планы!")
                msg = bot.send_message(chat_id, f"📍 Фильм *{title}* добавлен в список отложенного.", parse_mode="Markdown")
                delete_after(chat_id, msg.message_id, 5)
            else:
                bot.answer_callback_query(call.id, "Уже есть в списке!", show_alert=True)

        elif cmd == "watched":
            bot.answer_callback_query(call.id)
            msg = bot.send_message(chat_id, f"Какую оценку (от 1 до 10) поставите фильму *{title}*?", parse_mode="Markdown")
            bot.register_next_step_handler(msg, process_rating, title)

        elif cmd == "del":
            remove_movie(chat_id, title)
            bot.answer_callback_query(call.id, "Фильм удален из списков!")
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None) 

    # --- Тиндер ---
    elif cmd in ["tyes", "tno"]:
        tinder = get_tinder_session(chat_id)
        if msg_id not in tinder:
            bot.answer_callback_query(call.id, "Голосование устарело!", show_alert=True)
            return
            
        t_session = tinder[msg_id]
        title = t_session['title']
        
        if cmd == "tyes":
            t_session['yes'].add(user_id)
            t_session['no'].discard(user_id)
            bot.answer_callback_query(call.id, "Вы нажали 👍")
        else:
            t_session['no'].add(user_id)
            t_session['yes'].discard(user_id)
            bot.answer_callback_query(call.id, "Вы нажали 👎")
            
        if len(t_session['yes']) >= 2:
            bot.send_message(chat_id, f"🎉 *МЭТЧ!* 🎉\nОба участника хотят посмотреть 🎬 *{title}*!\n\n_Фильм автоматически добавлен в планы._", parse_mode="Markdown")
            if not is_in_lists(chat_id, title):
                add_want(chat_id, title, t_session['genres'])
            del tinder[msg_id]
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)

def process_rating(message, title):
    rating = message.text.strip()
    
    add_watched(message.chat.id, title, rating)
        
    msg = bot.send_message(message.chat.id, f"✅ Оценка *{rating}* для фильма *{title}* сохранена!", parse_mode="Markdown")
    delete_after(message.chat.id, msg.message_id, 7)
    
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except:
        pass

if __name__ == '__main__':
    init_db()
    print("Бот готов! Рулетка прокачана кнопками.")
    bot.infinity_polling()