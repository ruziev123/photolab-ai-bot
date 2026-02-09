import asyncio
import os
import base64
import hashlib
import sqlite3

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, LabeledPrice
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = OpenAI(api_key=OPENAI_API_KEY)


# =================================================
# SQLITE БАЗА
# =================================================
conn = sqlite3.connect("database.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0
)
""")
conn.commit()


def get_balance(uid):
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
    row = cursor.fetchone()
    return row[0] if row else 0


def add_credits(uid, amount):
    cursor.execute("""
        INSERT INTO users(user_id, balance)
        VALUES(?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET balance = balance + ?
    """, (uid, amount, amount))
    conn.commit()


def use_credit(uid):
    bal = get_balance(uid)
    if bal <= 0:
        return False

    cursor.execute(
        "UPDATE users SET balance = balance - 1 WHERE user_id=?",
        (uid,)
    )
    conn.commit()
    return True


# =================================================
# КЭШ
# =================================================
CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)


# =================================================
# 🎛 UI
# =================================================
def main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🖼 Создать"), KeyboardButton(text="📸 Фото-стиль")],
            [KeyboardButton(text="💎 Магазин"), KeyboardButton(text="👤 Баланс")]
        ],
        resize_keyboard=True
    )


def shop_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🟢 Starter • 5 фото • 75⭐")],
            [KeyboardButton(text="🔵 Popular 🔥 • 10 фото • 140⭐")],
            [KeyboardButton(text="🟣 Pro • 20 фото • 260⭐")],
            [KeyboardButton(text="⬅️ Назад")]
        ],
        resize_keyboard=True
    )


# =================================================
# START
# =================================================
@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer(
        f"🎨 Добро пожаловать в лабораторию\n\n"
        f"Баланс: {get_balance(message.from_user.id)} генераций\n\n"
        f"👇 Выбери действие",
        reply_markup=main_kb()
    )


# =================================================
# UI КНОПКИ
# =================================================
@dp.message(lambda m: m.text == "👤 Баланс")
async def balance_btn(m):
    await m.answer(
        f"👤 Твой баланс: {get_balance(m.from_user.id)} генераций ⭐",
        reply_markup=main_kb()
    )


@dp.message(lambda m: m.text == "💎 Магазин")
async def shop_btn(m):
    await m.answer(
        "💎 *МАГАЗИН ГЕНЕРАЦИЙ*\n\n"
        "🟢 Starter — попробовать\n"
        "🔵 Popular 🔥 — выгодно\n"
        "🟣 Pro — максимум\n",
        reply_markup=shop_kb(),
        parse_mode="Markdown"
    )


@dp.message(lambda m: m.text == "⬅️ Назад")
async def back_btn(m):
    await m.answer("Главное меню", reply_markup=main_kb())


@dp.message(lambda m: m.text == "🖼 Создать")
async def create_btn(m):
    await m.answer("✍️ Напиши описание картинки")


@dp.message(lambda m: m.text == "📸 Фото-стиль")
async def edit_btn(m):
    await m.answer("📸 Отправь фото + подпись со стилем")


# =================================================
# ⭐ STARS
# =================================================
async def send_invoice(message, stars, title, payload):
    prices = [LabeledPrice(label=title, amount=stars)]

    await bot.send_invoice(
        chat_id=message.chat.id,
        title=title,
        description="AI генерации",
        payload=payload,
        currency="XTR",
        prices=prices
    )


@dp.message(lambda m: "Starter" in m.text)
async def buy5(m): await send_invoice(m, 75, "5 генераций", "p5")


@dp.message(lambda m: "Popular" in m.text)
async def buy10(m): await send_invoice(m, 140, "10 генераций", "p10")


@dp.message(lambda m: "Pro" in m.text)
async def buy20(m): await send_invoice(m, 260, "20 генераций", "p20")


@dp.pre_checkout_query()
async def checkout(q):
    await bot.answer_pre_checkout_query(q.id, ok=True)


@dp.message(lambda m: m.successful_payment)
async def paid(m):
    p = m.successful_payment.invoice_payload

    if p == "p5":
        add_credits(m.from_user.id, 5)
    elif p == "p10":
        add_credits(m.from_user.id, 10)
    elif p == "p20":
        add_credits(m.from_user.id, 20)

    await m.answer(
        f"✅ Оплата прошла\nБаланс: {get_balance(m.from_user.id)}",
        reply_markup=main_kb()
    )


# =================================================
# TEXT → IMAGE
# =================================================
@dp.message(lambda msg: msg.text and "⭐" not in msg.text and "•" not in msg.text)
async def text_to_image(message: types.Message):

    if not use_credit(message.from_user.id):
        await message.answer("❌ Нет генераций. Открой Магазин 💎", reply_markup=main_kb())
        return

    prompt = message.text[:300]

    name = hashlib.md5(prompt.encode()).hexdigest() + ".png"
    path = os.path.join(CACHE_DIR, name)

    if os.path.exists(path):
        await message.answer_photo(types.FSInputFile(path))
        return

    msg = await message.answer("⚡ Генерю...")

    try:
        result = client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size="512x512"
        )

        img = base64.b64decode(result.data[0].b64_json)

        with open(path, "wb") as f:
            f.write(img)

        await message.answer_photo(types.FSInputFile(path))

    except:
        await message.answer("Ошибка генерации")

    await msg.delete()


# =================================================
# PHOTO → STYLE
# =================================================
@dp.message(lambda msg: msg.photo)
async def image_edit(message: types.Message):

    if not use_credit(message.from_user.id):
        await message.answer("❌ Нет генераций. Открой Магазин 💎", reply_markup=main_kb())
        return

    prompt = (message.caption or "make it cool")[:200]

    msg = await message.answer("⚡ Обрабатываю...")

    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        await bot.download_file(file.file_path, "temp.png")

        result = client.images.edit(
            model="gpt-image-1",
            image=open("temp.png", "rb"),
            prompt=prompt,
            size="512x512"
        )

        img = base64.b64decode(result.data[0].b64_json)

        path = os.path.join(CACHE_DIR, "edit_" + hashlib.md5(prompt.encode()).hexdigest() + ".png")

        with open(path, "wb") as f:
            f.write(img)

        await message.answer_photo(types.FSInputFile(path))

    except:
        await message.answer("Ошибка обработки")

    await msg.delete()


# =================================================
# RUN
# =================================================
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
