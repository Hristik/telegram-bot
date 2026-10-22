import json
import os
import random
import threading
import logging
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from flask import Flask

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
TARGET_CHAT_ID = -1004326402343
STATUS_FILE = Path("region_status.json")
ALLOWED_USERS = [
    8265988178, 1738583657, 1627097620
]
CHANNEL_URL = "https://t.me/Radar_ekaterenburg"
CHANNEL_LINK = f'<a href="{CHANNEL_URL}">❗️Радар Екатеринбург</a>'

REGION_NAMES = [
    "Свердловская область"
]
REGION_BY_ID = {i: name for i, name in enumerate(REGION_NAMES)}
VALID_STATUSES = {"yellow", "orange", "red_bpla", "red_rocket"}


PHOTO_MAP = {
    "yellow": "yellow.jpg",
    "orange": "orange.jpg",
    "red_bpla": "red_bpla.jpg",
    "red_rocket": "red_rocket.jpg",
    "green": "bpla_green.jpg",
    "green_bpla": "bpla_green.jpg",
    "green_rocket": "rocket_green.jpg"
}
STATUS_TITLES = {
    "yellow": "🟡 Внимание по БПЛА",
    "orange": "🟠 Внимание по ракетной опасности",
    "red_bpla": "🔴 Опасность по БПЛА",
    "red_rocket": "🟥 Ракетная опасность",
}
region_status = {name: [] for name in REGION_NAMES}


def save_statuses():
    """Save status data; don't crash the bot if the file cannot be written."""
    try:
        STATUS_FILE.write_text(
            json.dumps(region_status, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        logger.exception("Не удалось сохранить статусы регионов")


def load_statuses():
    global region_status
    region_status = {name: [] for name in REGION_NAMES}
    if not STATUS_FILE.exists():
        save_statuses()
        return
    try:
        saved = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        if not isinstance(saved, dict):
            raise ValueError("Ожидался JSON-объект со статусами регионов")
        for name in REGION_NAMES:
            old_status = saved.get(name, [])
            if isinstance(old_status, str):
                old_status = {
                    "red": ["red_bpla"],
                    "brown": ["red_rocket"],
                }.get(old_status, [old_status])
            if isinstance(old_status, list):
                region_status[name] = [
                    status for status in old_status if status in VALID_STATUSES
                ]
        save_statuses()
    except (OSError, json.JSONDecodeError, ValueError):
        logger.exception("Не удалось загрузить region_status.json; используются пустые статусы")


def get_menu_status(region_name):
    statuses = region_status.get(region_name, [])
    if "red_rocket" in statuses:
        return "🟥"
    if "orange" in statuses:
        return "🟠"
    if "red_bpla" in statuses:
        return "🔴"
    if "yellow" in statuses:
        return "🟡"
    return "⚪️"


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗺 Регионы", callback_data="regions_list")],
        [InlineKeyboardButton("✅ Сгенерировать сводку", callback_data="show_summary")],
        [InlineKeyboardButton("🟥 Пуски КР от ГГ", callback_data="launches_gg")],
        [InlineKeyboardButton("🟩 Отмена угрозы КР", callback_data="cancel_launches")],
        [InlineKeyboardButton("🔴 Пуски БПЛА от ГГ", callback_data="bpla_launches")],
        [InlineKeyboardButton("🟢 Отмена пусков БПЛА", callback_data="bpla_cancel")],
    ])


def regions_list_keyboard():
    buttons = [
        [InlineKeyboardButton(f"{get_menu_status(name)} {name}", callback_data=f"r_{i}")]
        for i, name in enumerate(REGION_NAMES)
    ]
    buttons.append([InlineKeyboardButton("⬅️ В меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)


def region_control_keyboard(region_id):
    name = REGION_BY_ID[region_id]
    current = region_status.get(name, [])
    buttons = []
    labels = [
        ("yellow", "🟡 Внимание по БПЛА", "🟡 Снять внимание по БПЛА"),
        ("orange", "🟠 Внимание по ракетной опасности", "🟠 Снять внимание по ракетной опасности"),
        ("red_bpla", "🔴 Опасность по БПЛА", "🔴 Снять опасность по БПЛА"),
        ("red_rocket", "🟥 Ракетная опасность", "🟥 Снять ракетную опасность"),
    ]
    for status, add_label, remove_label in labels:
        if status in current:
            buttons.append([InlineKeyboardButton(
                remove_label, callback_data=f"s{region_id}|{status}|remove"
            )])
        else:
            buttons.append([InlineKeyboardButton(
                add_label, callback_data=f"s{region_id}|{status}|add"
            )])
    buttons.append([InlineKeyboardButton("⬅️ Регионы", callback_data="regions_list")])
    return InlineKeyboardMarkup(buttons)


async def is_allowed(update: Update) -> bool:
    user = update.effective_user
    if user and user.id in ALLOWED_USERS:
        return True
    message = "⛔️ У вас нет доступа к этому боту."
    if update.callback_query:
        await update.callback_query.answer(message, show_alert=True)
    elif update.effective_message:
        await update.effective_message.reply_text(message)
    return False


async def safe_send_post(bot, text, photo_key=None):
    path = PHOTO_MAP.get(photo_key) if photo_key else None
    try:
        if path and Path(path).is_file():
            with open(path, "rb") as photo:
                await bot.send_photo(
                    chat_id=TARGET_CHAT_ID,
                    photo=photo,
                    caption=text,
                    parse_mode="HTML",
                )
        else:
            await bot.send_message(
                chat_id=TARGET_CHAT_ID,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        return True
    except Exception:
        logger.exception("Не удалось отправить сообщение в целевой канал")
        raise



async def auto_post_status_update(bot, region_name, new_status, is_remove=False):
    current = list(region_status.get(region_name, []))

    if is_remove:
        if new_status == "all":
            if not current:
                return
            current = []
            status_line = "🟢 Все статусы сняты"
            photo_key = "green"
        else:
            current = [s for s in current if s != new_status]

            if new_status == "yellow":
                status_line = "🟢 Отбой внимания по БПЛА"
                photo_key = "green_bpla"
            elif new_status == "red_bpla":
                status_line = "🟢 Отбой опасности по БПЛА"
                photo_key = "green_bpla"
            elif new_status == "orange":
                status_line = "🟢 Отбой внимания по ракетной опасности"
                photo_key = "green_rocket"
            elif new_status == "red_rocket":
                status_line = "🟢 Отбой ракетной опасности"
                photo_key = "green_rocket"
            else:
                return
    else:
        if new_status not in VALID_STATUSES:
            raise ValueError(f"Неизвестный статус: {new_status}")

        if new_status in current:
            return

        if new_status == "red_bpla":
            current = [s for s in current if s != "yellow"]
        elif new_status == "red_rocket":
            current = [s for s in current if s != "orange"]

        current.append(new_status)
        status_line = STATUS_TITLES[new_status]
        photo_key = new_status

    region_status[region_name] = current
    save_statuses()

    text = (
        f"<b>{region_name}</b>\n"
        f"{status_line}\n\n"
        f"{CHANNEL_LINK}"
    )

    await safe_send_post(bot, text, photo_key)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update):
        return
    await update.effective_message.reply_text(
        "Управление обстановкой:", reply_markup=main_menu_keyboard()
    )


async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update):
        return
    await update.effective_message.reply_text(
        f"🆔 ID этого чата/канала: {update.effective_chat.id}"
    )


async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update):
        return
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Управление обстановкой:", reply_markup=main_menu_keyboard())


async def show_regions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update):
        return
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Выберите регион:", reply_markup=regions_list_keyboard())


async def region_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update):
        return
    query = update.callback_query
    await query.answer()
    try:
        region_id = int(query.data.split("_", 1)[1])
        name = REGION_BY_ID[region_id]
    except (ValueError, KeyError, IndexError):
        await query.edit_message_text("Не удалось определить регион.", reply_markup=regions_list_keyboard())
        return
    await query.edit_message_text(
        f"{name}\nУстановите статус:",
        reply_markup=region_control_keyboard(region_id),
    )


async def set_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update):
        return
    query = update.callback_query
    await query.answer()
    try:
        command, status, action = query.data.split("|")
        region_id = int(command[1:])
        region_name = REGION_BY_ID[region_id]
        if action not in ("add", "remove"):
            raise ValueError("Неизвестное действие")
        if status != "all" and status not in VALID_STATUSES:
            raise ValueError("Неизвестный статус")
        await auto_post_status_update(
            context.bot, region_name, status, is_remove=(action == "remove")
        )
        await query.edit_message_text(
            f"✅ Статус региона «{region_name}» обновлён.",
            reply_markup=regions_list_keyboard(),
        )
    except Exception as exc:
        logger.exception("Ошибка при изменении статуса")
        try:
            await query.edit_message_text(
                f"❌ Не удалось обновить статус: {exc}",
                reply_markup=regions_list_keyboard(),
            )
        except Exception:
            pass


async def show_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update):
        return
    query = update.callback_query
    await query.answer()
    active_regions = {name: statuses for name, statuses in region_status.items() if statuses}
    if not active_regions:
        summary_text = (
            "✅ По обстановке спокойно. Продолжаем следить.\n\n"
            "Фиксаций не наблюдаем. При появлении подтверждённой информации сообщим."
        )
    else:
        groups = {status: [] for status in VALID_STATUSES}
        for region, statuses in active_regions.items():
            for status in statuses:
                if status in groups:
                    groups[status].append(region)
        parts = [
            f"{STATUS_TITLES[status]}:\n<b>{', '.join(regions)}</b>"
            for status, regions in groups.items() if regions
        ]
        summary_text = "Сводка угроз на данный момент\n\n" + "\n\n".join(parts)
    summary_text += f"\n\n{CHANNEL_LINK}"
    try:
        await safe_send_post(context.bot, summary_text)
        await query.edit_message_text("✅ Сводка отправлена.", reply_markup=main_menu_keyboard())
    except Exception as exc:
        await query.edit_message_text(
            f"❌ Ошибка отправки сводки: {exc}", reply_markup=main_menu_keyboard()
        )


async def post_random_message(update, context, phrases, success_text):
    if not await is_allowed(update):
        return
    query = update.callback_query
    await query.answer()
    text = f"{random.choice(phrases)}\n\n{CHANNEL_LINK}"
    try:
        await safe_send_post(context.bot, text)
        await query.edit_message_text(success_text, reply_markup=main_menu_keyboard())
    except Exception as exc:
        logger.exception("Не удалось отправить пост")
        await query.edit_message_text(
            f"❌ Не удалось отправить сообщение: {exc}",
            reply_markup=main_menu_keyboard(),
        )


async def launches_gg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await post_random_message(
        update, context,
        [
            "⚠️ Активность пусковых установок в приграничье, возможны пуски в тыл. Следим за информацией.",
            "⚠️ Поступила информация об активности в приграничье. Ожидаем подтверждения.",
        ],
        "✅ Сообщение о ракетной угрозе отправлено.",
    )


async def cancel_launches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await post_random_message(
        update, context,
        [
            "🟢 Угроза пусков крылатых ракет отменена.",
            "🟢 Информация о ракетной угрозе не подтвердилась. Угроза отменена.",
        ],
        "✅ Сообщение об отмене ракетной угрозы отправлено.",
    )


async def bpla_launches_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await post_random_message(
        update, context,
        [
            "⚠️ Сообщается об активности БПЛА в приграничье. Следим за подтверждённой информацией.",
            "⚠️ Возможна активность БПЛА в приграничье. Ожидаем уточнений.",
        ],
        "✅ Сообщение об активности БПЛА отправлено.",
    )


async def bpla_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await post_random_message(
        update, context,
        [
            "🟢 Угроза пусков БПЛА отменена.",
            "🟢 Информация о пусках БПЛА не подтвердилась.",
        ],
        "✅ Сообщение об отмене угрозы БПЛА отправлено.",
    )


app_web = Flask(__name__)


@app_web.route("/")
def home():
    return "bot is alive", 200


def run_web():
    app_web.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), use_reloader=False)


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "Не задан BOT_TOKEN. Добавьте токен бота в переменные окружения."
        )
    load_statuses()
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("chatid", chat_id))
    application.add_handler(CallbackQueryHandler(main_menu, pattern=r"^main_menu$"))
    application.add_handler(CallbackQueryHandler(show_regions, pattern=r"^regions_list$"))
    application.add_handler(CallbackQueryHandler(region_control, pattern=r"^r_\d+$"))
    application.add_handler(CallbackQueryHandler(set_status, pattern=r"^s\d+\|"))
    application.add_handler(CallbackQueryHandler(show_summary, pattern=r"^show_summary$"))
    application.add_handler(CallbackQueryHandler(launches_gg, pattern=r"^launches_gg$"))
    application.add_handler(CallbackQueryHandler(cancel_launches, pattern=r"^cancel_launches$"))
    application.add_handler(CallbackQueryHandler(bpla_launches_handler, pattern=r"^bpla_launches$"))
    application.add_handler(CallbackQueryHandler(bpla_cancel_handler, pattern=r"^bpla_cancel$"))

    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()
    logger.info("Бот запускается")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
