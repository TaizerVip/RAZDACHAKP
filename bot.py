import logging
import asyncio
import random
import sqlite3
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== КОНФИГУРАЦИЯ ====================
# Получаем переменные окружения
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_IDS = [int(id.strip()) for id in os.environ.get('ADMIN_IDS', '').split(',') if id.strip()]
GROUP_CHAT_ID = int(os.environ.get('GROUP_CHAT_ID'))
ADMIN_CHAT_ID = int(os.environ.get('ADMIN_CHAT_ID', GROUP_CHAT_ID))

DB_FILE = 'giveaway_bot.db'  # BotHost позволяет писать в директорию

# Проверка обязательных переменных
if not BOT_TOKEN:
    logger.error("BOT_TOKEN не установлен!")
    raise ValueError("BOT_TOKEN не установлен в переменных окружения!")
if not ADMIN_IDS:
    logger.error("ADMIN_IDS не установлен!")
    raise ValueError("ADMIN_IDS не установлен в переменных окружения!")
if not GROUP_CHAT_ID:
    logger.error("GROUP_CHAT_ID не установлен!")
    raise ValueError("GROUP_CHAT_ID не установлен в переменных окружения!")

logger.info(f"Бот запускается с настройками:")
logger.info(f"GROUP_CHAT_ID: {GROUP_CHAT_ID}")
logger.info(f"ADMIN_IDS: {ADMIN_IDS}")

# Анимации выигрыша
WIN_ANIMATIONS = [
    ["🎉", "✨", "🎊", "✨", "🎉"],
    ["🏆", "⭐", "🏆", "⭐", "🏆"],
    ["🎁", "🎀", "🎁", "🎀", "🎁"],
    ["💎", "✨", "💎", "✨", "💎"],
    ["🔥", "⚡", "🔥", "⚡", "🔥"],
    ["👑", "🌟", "👑", "🌟", "👑"],
    ["🍀", "🌈", "🍀", "🌈", "🍀"],
    ["🎰", "🎲", "🎰", "🎲", "🎰"]
]


# ==================== БАЗА ДАННЫХ ====================
def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # Создаем таблицу users
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            wins INTEGER DEFAULT 0,
            last_active TEXT
        )
    ''')

    # Создаем таблицу win_records
    c.execute('''
        CREATE TABLE IF NOT EXISTS win_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            prize TEXT,
            message_id INTEGER,
            created_at TEXT
        )
    ''')

    # Создаем таблицу admins
    c.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            added_by INTEGER,
            added_at TEXT
        )
    ''')

    # Создаем таблицу settings
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    # Проверяем и добавляем колонку message_id если она отсутствует
    try:
        c.execute("ALTER TABLE win_records ADD COLUMN message_id INTEGER")
        logger.info("✅ Добавлена колонка message_id в таблицу win_records")
    except sqlite3.OperationalError:
        pass

    # Вставляем настройки по умолчанию
    settings = [
        ('bot_enabled', '1'),
        ('win_chance', '1.0'),
        ('win_text', '🎉 ПОЗДРАВЛЯЕМ! 🎉\n\n{user} выиграл {prize}! 🎁\n\nАдминистратор свяжется с вами для получения приза!'),
        ('prize', 'Медвежонок 🧸'),
        ('animation_enabled', '1')
    ]
    
    for key, value in settings:
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

    # Добавляем главных админов
    for admin_id in ADMIN_IDS:
        c.execute("INSERT OR IGNORE INTO admins (user_id, added_by, added_at) VALUES (?, ?, ?)",
                  (admin_id, 0, datetime.now().isoformat()))

    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")


# Функции работы с БД
def get_setting(key):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None


def set_setting(key, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE settings SET value = ? WHERE key = ?", (value, key))
    conn.commit()
    conn.close()


def is_bot_enabled():
    return get_setting('bot_enabled') == '1'


def is_animation_enabled():
    return get_setting('animation_enabled') == '1'


def get_win_chance():
    return float(get_setting('win_chance'))


def get_win_text():
    return get_setting('win_text')


def get_prize():
    return get_setting('prize')


def set_win_chance(chance):
    set_setting('win_chance', str(chance))


def set_win_text(text):
    set_setting('win_text', text)


def set_prize(prize):
    set_setting('prize', prize)


def set_animation_enabled(enabled):
    set_setting('animation_enabled', '1' if enabled else '0')


def update_user_stats(user_id, username, first_name):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO users (user_id, username, first_name, last_active) 
        VALUES (?, ?, ?, ?) 
        ON CONFLICT(user_id) DO UPDATE SET 
            username = excluded.username,
            first_name = excluded.first_name,
            last_active = excluded.last_active
    ''', (user_id, username, first_name, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def add_win(user_id, username, first_name, prize, message_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET wins = wins + 1 WHERE user_id = ?", (user_id,))
    c.execute('''
        INSERT INTO win_records (user_id, username, first_name, prize, message_id, created_at) 
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, username, first_name, prize, message_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_user_wins(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT wins FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0


def get_last_wins(limit=10):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        SELECT user_id, username, first_name, prize, message_id, created_at 
        FROM win_records 
        ORDER BY created_at DESC 
        LIMIT ?
    ''', (limit,))
    wins = c.fetchall()
    conn.close()
    return wins


def is_admin(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result is not None or user_id in ADMIN_IDS


def add_admin(user_id, added_by):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO admins (user_id, added_by, added_at) VALUES (?, ?, ?)",
              (user_id, added_by, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def remove_admin(user_id):
    if user_id in ADMIN_IDS:
        return False
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return True


def get_all_admins():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id FROM admins")
    admins = [row[0] for row in c.fetchall()]
    conn.close()
    return ADMIN_IDS + admins


def get_top_winners(limit=10):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, wins FROM users ORDER BY wins DESC LIMIT ?", (limit,))
    winners = c.fetchall()
    conn.close()
    return winners


# ==================== АНИМАЦИЯ ====================
async def play_win_animation(context, chat_id, user_first_name, prize):
    if not is_animation_enabled():
        return False

    try:
        animation = random.choice(WIN_ANIMATIONS)

        msg1 = await context.bot.send_message(chat_id=chat_id, text="🎲 **БАРАБАН КРУТИТСЯ...** 🎲",
                                              parse_mode='Markdown')
        await asyncio.sleep(1.0)
        await msg1.delete()
        await asyncio.sleep(0.3)

        for i in range(3):
            anim_line = " ".join(animation)
            msg2 = await context.bot.send_message(chat_id=chat_id, text=f"✨ {anim_line} ✨")
            await asyncio.sleep(0.8)
            await msg2.delete()
            await asyncio.sleep(0.2)

        final_animation = ["🎉", "🏆", "🎊", "⭐", "💎"]
        final_line = " ".join(final_animation)
        msg3 = await context.bot.send_message(chat_id=chat_id, text=f"🌟 {final_line} 🌟")
        await asyncio.sleep(0.8)
        await msg3.delete()
        await asyncio.sleep(0.3)

        confetti = ["🎊", "🎉", "✨", "🎈", "🎁"]
        for i in range(2):
            confetti_line = " ".join(confetti)
            msg4 = await context.bot.send_message(chat_id=chat_id, text=confetti_line)
            await asyncio.sleep(0.5)
            await msg4.delete()
            await asyncio.sleep(0.2)

    except Exception as e:
        logger.error(f"Ошибка анимации: {e}")

    return True


# ==================== АДМИН-КЛАВИАТУРЫ ====================
def get_admin_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="admin_settings")],
        [InlineKeyboardButton("👑 Управление админами", callback_data="admin_manage")],
        [InlineKeyboardButton("🎁 Ручной розыгрыш", callback_data="admin_manual_giveaway")],
        [InlineKeyboardButton("🔙 Выход", callback_data="admin_exit")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_settings_keyboard():
    enabled = is_bot_enabled()
    status_text = "🟢 Включен" if enabled else "🔴 Выключен"
    animation_enabled = is_animation_enabled()
    anim_text = "🎬 Анимация: Вкл" if animation_enabled else "🎬 Анимация: Выкл"
    win_chance = get_win_chance()
    prize = get_prize()

    keyboard = [
        [InlineKeyboardButton(f"🤖 Бот: {status_text}", callback_data="admin_toggle_bot")],
        [InlineKeyboardButton(anim_text, callback_data="admin_toggle_animation")],
        [InlineKeyboardButton(f"🎲 Шанс: {win_chance}%", callback_data="admin_edit_chance")],
        [InlineKeyboardButton(f"🎁 Приз: {prize}", callback_data="admin_edit_prize")],
        [InlineKeyboardButton("📝 Текст выигрыша", callback_data="admin_edit_text")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_manage_admins_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ Добавить админа", callback_data="admin_add_admin")],
        [InlineKeyboardButton("➖ Удалить админа", callback_data="admin_remove_admin")],
        [InlineKeyboardButton("📋 Список админов", callback_data="admin_list_admins")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ==================== ОБРАБОТЧИКИ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🎁 **БОТ-БАНДИТ ЗАПУЩЕН!** 🎁\n\n"
        f"✨ Шанс победы: {get_win_chance()}%\n"
        f"🎁 Текущий приз: {get_prize()}\n"
        f"🎬 Анимация: {'Включена' if is_animation_enabled() else 'Выключена'}\n\n"
        f"📝 Команды:\n"
        f"/stats - статистика\n"
        f"/wins - мои победы\n"
        f"/lastwins - последние победы\n"
        f"/admin - админ-панель\n\n"
        f"💬 Просто пишите в чат и участвуйте в розыгрыше!\n"
        f"🏆 Удачи!",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardRemove()
    )
    update_user_stats(user.id, user.username, user.first_name)


async def check_winner(update: Update, context: ContextTypes.DEFAULT_TYPE, is_manual=False):
    user = update.effective_user
    chat = update.effective_chat

    if chat.id != GROUP_CHAT_ID:
        return

    if not is_bot_enabled() and not is_manual:
        return

    if not is_manual:
        win_chance = get_win_chance()
        rand = random.random() * 100
        if rand > win_chance:
            return

    prize = get_prize()
    win_text_template = get_win_text()

    try:
        await play_win_animation(context, chat.id, user.first_name, prize)
    except Exception as e:
        logger.error(f"Ошибка анимации: {e}")

    win_text = win_text_template.format(
        user=f"[{user.first_name}](tg://user?id={user.id})",
        prize=prize,
        username=f"@{user.username}" if user.username else "пользователь"
    )

    await asyncio.sleep(0.5)
    win_message = await context.bot.send_message(chat_id=chat.id, text=win_text, parse_mode='Markdown')

    add_win(user.id, user.username, user.first_name, prize, win_message.message_id)
    update_user_stats(user.id, user.username, user.first_name)

    chat_id_str = str(GROUP_CHAT_ID)
    if GROUP_CHAT_ID < 0:
        chat_id_str = str(GROUP_CHAT_ID)[4:]
    
    message_link = f"https://t.me/c/{chat_id_str}/{win_message.message_id}"

    admin_text = (
        f"🎁 **НОВЫЙ ПОБЕДИТЕЛЬ!** 🎁\n\n"
        f"👤 **Победитель:** {user.first_name}\n"
        f"🆔 **ID:** `{user.id}`\n"
        f"👥 **Юзернейм:** @{user.username or 'нет'}\n"
        f"🎁 **Приз:** {prize}\n"
        f"📝 **Сообщение:** [Перейти к сообщению]({message_link})\n"
        f"🕐 **Время:** {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"✅ Выдайте приз победителю!"
    )

    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=admin_text,
        parse_mode='Markdown',
        disable_web_page_preview=True
    )

    logger.info(f"Победитель! {user.id} - {prize}")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_winners = get_top_winners(10)
    text = f"📊 **СТАТИСТИКА** 📊\n\n"
    text += f"🎲 Шанс: {get_win_chance()}%\n"
    text += f"🎁 Приз: {get_prize()}\n"
    text += f"🤖 Статус: {'🟢 Вкл' if is_bot_enabled() else '🔴 Выкл'}\n"
    text += f"🎬 Анимация: {'✅ Вкл' if is_animation_enabled() else '❌ Выкл'}\n\n"
    text += f"🏆 **ТОП-10** 🏆\n\n"

    for i, (uid, username, first_name, wins) in enumerate(top_winners, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        name = first_name or f"ID:{uid}"
        text += f"{medal} **{name}** — {wins} побед\n"

    if not top_winners:
        text += "Пока нет победителей!"

    await update.message.reply_text(text, parse_mode='Markdown')


async def my_wins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    wins = get_user_wins(user.id)
    text = f"🏆 **МОИ ПОБЕДЫ** 🏆\n\n"
    text += f"👤 {user.first_name}\n"
    text += f"🎁 Побед: **{wins}**\n"
    text += f"🎲 Шанс: {get_win_chance()}%\n"
    text += f"🎁 Приз: {get_prize()}"
    await update.message.reply_text(text, parse_mode='Markdown')


async def last_wins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wins = get_last_wins(10)
    if not wins:
        await update.message.reply_text("🏆 **Пока нет побед!**\n\nБудьте первым! 🎉", parse_mode='Markdown')
        return

    text = "🏆 **ПОСЛЕДНИЕ ПОБЕДЫ** 🏆\n\n"
    for i, (uid, username, first_name, prize, message_id, created_at) in enumerate(wins, 1):
        try:
            win_time = datetime.fromisoformat(created_at)
            now = datetime.now()
            diff = now - win_time
            if diff.days > 0:
                time_ago = f"{diff.days} дн назад"
            elif diff.seconds > 3600:
                hours = diff.seconds // 3600
                time_ago = f"{hours} ч назад"
            elif diff.seconds > 60:
                minutes = diff.seconds // 60
                time_ago = f"{minutes} мин назад"
            else:
                time_ago = "только что"
        except:
            time_ago = "недавно"

        name = first_name or f"ID:{uid}"
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} **{name}** — {prize}\n"
        text += f"   └ 🕐 {time_ago}\n\n"

    text += "━━━━━━━━━━━━━━━━━━━━\n"
    text += f"🎲 **Текущий шанс:** {get_win_chance()}%\n"
    text += f"🎁 **Текущий приз:** {get_prize()}"
    await update.message.reply_text(text, parse_mode='Markdown')


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ Нет прав!")
        return
    await update.message.reply_text(
        "🔑 **АДМИН-ПАНЕЛЬ** 🔑",
        parse_mode='Markdown',
        reply_markup=get_admin_keyboard()
    )


async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user

    if not is_admin(user.id):
        await query.edit_message_text("❌ Нет прав!")
        return

    if data == "admin_stats":
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]
        c.execute("SELECT SUM(wins) FROM users")
        total_wins = c.fetchone()[0] or 0
        c.execute("SELECT COUNT(*) FROM win_records")
        total_records = c.fetchone()[0]
        conn.close()

        text = (
            f"📊 **СТАТИСТИКА** 📊\n\n"
            f"👥 Участников: {total_users}\n"
            f"🎁 Побед: {total_wins}\n"
            f"📝 Записей в истории: {total_records}\n"
            f"🎲 Шанс: {get_win_chance()}%\n"
            f"🎁 Приз: {get_prize()}\n"
            f"🤖 Статус: {'🟢 Вкл' if is_bot_enabled() else '🔴 Выкл'}\n"
            f"🎬 Анимация: {'✅ Вкл' if is_animation_enabled() else '❌ Выкл'}"
        )
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=get_admin_keyboard())

    elif data == "admin_settings":
        await query.edit_message_text("⚙️ **НАСТРОЙКИ**", parse_mode='Markdown', reply_markup=get_settings_keyboard())

    elif data == "admin_toggle_animation":
        current = is_animation_enabled()
        set_animation_enabled(not current)
        await query.answer(f"Анимация {'выключена' if current else 'включена'}")
        await query.edit_message_text("⚙️ **НАСТРОЙКИ**", parse_mode='Markdown', reply_markup=get_settings_keyboard())

    elif data == "admin_toggle_bot":
        current = is_bot_enabled()
        set_setting('bot_enabled', '0' if current else '1')
        await query.answer(f"Бот {'выключен' if current else 'включен'}")
        await query.edit_message_text("⚙️ **НАСТРОЙКИ**", parse_mode='Markdown', reply_markup=get_settings_keyboard())

    elif data == "admin_edit_chance":
        await query.edit_message_text(
            f"🎲 **ШАНС ПОБЕДЫ**\n\nТекущий: {get_win_chance()}%\n\nВведите новый (0.01-100):",
            parse_mode='Markdown'
        )
        context.user_data['edit_chance'] = True

    elif data == "admin_edit_prize":
        await query.edit_message_text(
            f"🎁 **ПРИЗ**\n\nТекущий: {get_prize()}\n\nВведите новый:",
            parse_mode='Markdown'
        )
        context.user_data['edit_prize'] = True

    elif data == "admin_edit_text":
        current = get_win_text()
        await query.edit_message_text(
            f"📝 **ТЕКСТ ВЫИГРЫША**\n\nТекущий:\n{current}\n\nВведите новый:\n(используйте {{user}}, {{prize}}, {{username}})",
            parse_mode='Markdown'
        )
        context.user_data['edit_text'] = True

    elif data == "admin_add_admin":
        await query.edit_message_text("➕ **ДОБАВИТЬ АДМИНА**\n\nВведите ID:", parse_mode='Markdown')
        context.user_data['add_admin'] = True

    elif data == "admin_remove_admin":
        await query.edit_message_text("➖ **УДАЛИТЬ АДМИНА**\n\nВведите ID:", parse_mode='Markdown')
        context.user_data['remove_admin'] = True

    elif data == "admin_list_admins":
        admins = get_all_admins()
        text = "👑 **АДМИНЫ** 👑\n\n"
        for admin_id in admins:
            text += f"• `{admin_id}`"
            if admin_id in ADMIN_IDS:
                text += " (главный)"
            text += "\n"
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=get_manage_admins_keyboard())

    elif data == "admin_manage":
        await query.edit_message_text("👑 **УПРАВЛЕНИЕ АДМИНАМИ**", parse_mode='Markdown', reply_markup=get_manage_admins_keyboard())

    elif data == "admin_manual_giveaway":
        await query.edit_message_text("🎁 **РУЧНОЙ РОЗЫГРЫШ**\n\nВведите ID победителя:", parse_mode='Markdown')
        context.user_data['manual_giveaway'] = True

    elif data == "admin_back":
        await query.edit_message_text("🔑 **АДМИН-ПАНЕЛЬ**", parse_mode='Markdown', reply_markup=get_admin_keyboard())

    elif data == "admin_exit":
        await query.edit_message_text("👋 Выход", reply_markup=None)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    text = update.message.text if update.message.text else ""

    if chat.id != GROUP_CHAT_ID:
        return

    update_user_stats(user.id, user.username, user.first_name)

    # Режимы админа
    if context.user_data.get('manual_giveaway'):
        try:
            winner_id = int(text.strip())
            winner = await context.bot.get_chat(winner_id)
            prize = get_prize()
            win_text_template = get_win_text()

            await play_win_animation(context, chat.id, winner.first_name, prize)
            await asyncio.sleep(0.5)

            win_text = win_text_template.format(
                user=f"[{winner.first_name}](tg://user?id={winner_id})",
                prize=prize,
                username=f"@{winner.username}" if winner.username else "пользователь"
            )

            win_message = await context.bot.send_message(chat_id=chat.id, text=win_text, parse_mode='Markdown')
            add_win(winner_id, winner.username, winner.first_name, prize, win_message.message_id)

            chat_id_str = str(GROUP_CHAT_ID)
            if GROUP_CHAT_ID < 0:
                chat_id_str = str(GROUP_CHAT_ID)[4:]
            
            message_link = f"https://t.me/c/{chat_id_str}/{win_message.message_id}"

            admin_text = (
                f"🎁 **РУЧНОЙ РОЗЫГРЫШ!** 🎁\n\n"
                f"👤 **Победитель:** {winner.first_name}\n"
                f"🆔 **ID:** `{winner_id}`\n"
                f"🎁 **Приз:** {prize}\n"
                f"📝 **Сообщение:** [Перейти к сообщению]({message_link})\n"
                f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            )

            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_text, parse_mode='Markdown',
                                           disable_web_page_preview=True)
            await update.message.reply_text(f"✅ Победитель: {winner.first_name}")

        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")

        context.user_data.pop('manual_giveaway', None)
        return

    if context.user_data.get('edit_chance'):
        try:
            chance = float(text.replace('%', '').strip())
            if 0.01 <= chance <= 100:
                set_win_chance(chance)
                await update.message.reply_text(f"✅ Шанс: {chance}%")
            else:
                await update.message.reply_text("❌ 0.01-100")
        except:
            await update.message.reply_text("❌ Введите число")
        context.user_data.pop('edit_chance', None)
        return

    if context.user_data.get('edit_prize'):
        set_prize(text)
        await update.message.reply_text(f"✅ Приз: {text}")
        context.user_data.pop('edit_prize', None)
        return

    if context.user_data.get('edit_text'):
        set_win_text(text)
        await update.message.reply_text(f"✅ Текст изменен")
        context.user_data.pop('edit_text', None)
        return

    if context.user_data.get('add_admin'):
        try:
            admin_id = int(text.strip())
            add_admin(admin_id, user.id)
            await update.message.reply_text(f"✅ Админ добавлен")
        except:
            await update.message.reply_text("❌ Ошибка")
        context.user_data.pop('add_admin', None)
        return

    if context.user_data.get('remove_admin'):
        try:
            admin_id = int(text.strip())
            if remove_admin(admin_id):
                await update.message.reply_text(f"✅ Админ удален")
            else:
                await update.message.reply_text("❌ Нельзя удалить главного")
        except:
            await update.message.reply_text("❌ Ошибка")
        context.user_data.pop('remove_admin', None)
        return

    # Команды
    if text == "/stats" or text == "статистика":
        await stats_command(update, context)
    elif text == "/wins" or text == "мои победы":
        await my_wins_command(update, context)
    elif text == "/lastwins" or text == "последние победы" or text == "история побед":
        await last_wins_command(update, context)
    else:
        await check_winner(update, context, is_manual=False)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleared = False
    for mode in ['manual_giveaway', 'edit_chance', 'edit_prize', 'edit_text', 'add_admin', 'remove_admin']:
        if context.user_data.get(mode):
            context.user_data.pop(mode, None)
            cleared = True

    if cleared:
        await update.message.reply_text("✅ Отменено")
    else:
        await update.message.reply_text("❌ Нет активных действий")


async def run_bot():
    logger.info("=" * 50)
    logger.info("ЗАПУСК БОТА-БАНДИТА")
    logger.info("=" * 50)
    logger.info(f"GROUP_CHAT_ID: {GROUP_CHAT_ID}")
    logger.info(f"ADMIN_IDS: {ADMIN_IDS}")
    logger.info(f"Шанс: {get_win_chance()}%")
    logger.info(f"Приз: {get_prize()}")
    logger.info(f"Анимация: {'Вкл' if is_animation_enabled() else 'Выкл'}")
    logger.info("=" * 50)

    application = Application.builder().token(BOT_TOKEN).connect_timeout(60).read_timeout(60).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("wins", my_wins_command))
    application.add_handler(CommandHandler("lastwins", last_wins_command))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)

    logger.info("✅ Бот-бандит успешно запущен!")

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("Останавливаем...")
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


def main():
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Ошибка при запуске: {e}")


if __name__ == "__main__":
    main()
