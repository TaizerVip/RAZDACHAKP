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

DB_FILE = 'giveaway_bot.db'

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
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        logger.info("Создание/проверка таблиц...")
        
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
        logger.info("✅ Таблица users готова")
        
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
        logger.info("✅ Таблица win_records готова")
        
        # Создаем таблицу admins
        c.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_by INTEGER,
                added_at TEXT
            )
        ''')
        logger.info("✅ Таблица admins готова")
        
        # Создаем таблицу settings
        c.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        logger.info("✅ Таблица settings готова")
        
        # Проверяем и добавляем колонку message_id если она отсутствует
        try:
            c.execute("ALTER TABLE win_records ADD COLUMN message_id INTEGER")
            logger.info("✅ Добавлена колонка message_id в таблицу win_records")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                logger.info("Колонка message_id уже существует")
            else:
                logger.info(f"Колонка message_id уже есть или ошибка: {e}")
        
        # Вставляем настройки по умолчанию, если их нет
        default_settings = [
            ('bot_enabled', '1'),
            ('win_chance', '1.0'),
            ('win_text', '🎉 ПОЗДРАВЛЯЕМ! 🎉\n\n{user} выиграл {prize}! 🎁\n\nАдминистратор свяжется с вами для получения приза!'),
            ('prize', 'Медвежонок 🧸'),
            ('animation_enabled', '1')
        ]
        
        for key, value in default_settings:
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
            logger.info(f"✅ Настройка {key} = {value}")
        
        # Добавляем главных админов
        for admin_id in ADMIN_IDS:
            c.execute("INSERT OR IGNORE INTO admins (user_id, added_by, added_at) VALUES (?, ?, ?)",
                      (admin_id, 0, datetime.now().isoformat()))
            logger.info(f"✅ Добавлен админ: {admin_id}")
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных успешно инициализирована!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка при инициализации БД: {e}")
        raise


# Принудительно инициализируем БД при старте
logger.info("Инициализация базы данных...")
init_db()


# ==================== ФУНКЦИИ РАБОТЫ С БД ====================
def get_setting(key):
    """Получить настройку из БД"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key = ?", (key,))
        result = c.fetchone()
        conn.close()
        if result:
            return result[0]
        else:
            logger.warning(f"Настройка {key} не найдена")
            return None
    except Exception as e:
        logger.error(f"Ошибка при получении настройки {key}: {e}")
        return None


def set_setting(key, value):
    """Установить настройку"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE settings SET value = ? WHERE key = ?", (value, key))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Ошибка при установке настройки {key}: {e}")
        return False


def is_bot_enabled():
    """Проверить включен ли бот"""
    value = get_setting('bot_enabled')
    return value == '1' if value else True


def is_animation_enabled():
    """Проверить включена ли анимация"""
    value = get_setting('animation_enabled')
    return value == '1' if value else True


def get_win_chance():
    """Получить шанс победы"""
    value = get_setting('win_chance')
    try:
        return float(value) if value else 1.0
    except:
        return 1.0


def get_win_text():
    """Получить текст победы"""
    value = get_setting('win_text')
    if value:
        return value
    return '🎉 ПОЗДРАВЛЯЕМ! 🎉\n\n{user} выиграл {prize}! 🎁\n\nАдминистратор свяжется с вами для получения приза!'


def get_prize():
    """Получить текущий приз"""
    value = get_setting('prize')
    return value if value else 'Медвежонок 🧸'


def set_win_chance(chance):
    """Установить шанс победы"""
    set_setting('win_chance', str(chance))


def set_win_text(text):
    """Установить текст победы"""
    set_setting('win_text', text)


def set_prize(prize):
    """Установить приз"""
    set_setting('prize', prize)


def set_animation_enabled(enabled):
    """Включить/выключить анимацию"""
    set_setting('animation_enabled', '1' if enabled else '0')


def update_user_stats(user_id, username, first_name):
    """Обновить статистику пользователя"""
    try:
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
        return True
    except Exception as e:
        logger.error(f"Ошибка при обновлении статистики пользователя {user_id}: {e}")
        return False


def add_win(user_id, username, first_name, prize, message_id):
    """Добавить запись о победе"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE users SET wins = wins + 1 WHERE user_id = ?", (user_id,))
        c.execute('''
            INSERT INTO win_records (user_id, username, first_name, prize, message_id, created_at) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, prize, message_id, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Ошибка при добавлении победы: {e}")
        return False


def get_user_wins(user_id):
    """Получить количество побед пользователя"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT wins FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        conn.close()
        return result[0] if result else 0
    except Exception as e:
        logger.error(f"Ошибка при получении побед пользователя: {e}")
        return 0


def get_last_wins(limit=10):
    """Получить последние победы"""
    try:
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
    except Exception as e:
        logger.error(f"Ошибка при получении последних побед: {e}")
        return []


def is_admin(user_id):
    """Проверить является ли пользователь админом"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        conn.close()
        return result is not None or user_id in ADMIN_IDS
    except Exception as e:
        logger.error(f"Ошибка при проверке админа: {e}")
        return user_id in ADMIN_IDS


def add_admin(user_id, added_by):
    """Добавить админа"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO admins (user_id, added_by, added_at) VALUES (?, ?, ?)",
                  (user_id, added_by, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Ошибка при добавлении админа: {e}")
        return False


def remove_admin(user_id):
    """Удалить админа"""
    if user_id in ADMIN_IDS:
        return False
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Ошибка при удалении админа: {e}")
        return False


def get_all_admins():
    """Получить всех админов"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT user_id FROM admins")
        admins = [row[0] for row in c.fetchall()]
        conn.close()
        return ADMIN_IDS + admins
    except Exception as e:
        logger.error(f"Ошибка при получении списка админов: {e}")
        return ADMIN_IDS


def get_top_winners(limit=10):
    """Получить топ победителей"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT user_id, username, first_name, wins FROM users ORDER BY wins DESC LIMIT ?", (limit,))
        winners = c.fetchall()
        conn.close()
        return winners
    except Exception as e:
        logger.error(f"Ошибка при получении топа победителей: {e}")
        return []


# ==================== ОСТАЛЬНОЙ КОД (обработчики и т.д.) ====================
# Здесь вставьте все обработчики из предыдущей версии
# (функции play_win_animation, start, check_winner, stats_command, 
#  my_wins_command, last_wins_command, admin_command, 
#  admin_callback_handler, message_handler, cancel, run_bot, main)

# ... (весь остальной код обработчиков)


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
