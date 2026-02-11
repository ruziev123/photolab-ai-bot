import asyncio
import os
import base64
import sqlite3

from aiogram import Bot, Dispatcher, types, F
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
# DATABASE
# =================================================

conn = sqlite3.connect("database.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    trial_used INTEGER DEFAULT 0
)
""")
conn.commit()


# -------------------------
# helpers
# -------------------------

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

    cursor.execute("UPDATE users SET balance = balance - 1 WHERE user_id=?", (uid,))
    conn.commit()
    return True


def give_trial(uid):
    cursor.execute("SELECT trial_used FROM users WHERE user_id=?", (uid,))
    row = cursor.fetchone()

    if not row:
        cursor.execute(
            "INSERT INTO users(user_id, balance, trial_used) VALUES(?, 1, 1)",
            (uid,)
        )
        conn.commit()
        return True

    if row[0] == 0:
        cursor.execute(
            "UPDATE users SET balance = balance + 1, trial_used = 1 WHERE user_id=?",
            (uid,)
        )
        conn.commit()
        return True

    return False


# =================================================
# UI
# =================================================

def main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🖼 Создать"), KeyboardButton(text="📸 Фото с описанием")],
            [KeyboardButton(text="💎 Магазин"), KeyboardButton(text="👤 Баланс")]
        ],
        resize_keyboard=True
    )


def shop_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⚪ Trial • 2 фото • 1⭐")],
            [KeyboardButton(text="🟢 Starter • 5 фото • 75⭐")],
            [KeyboardButton(text="🔵 Popular • 10 фото • 140⭐")],
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
    uid = message.from_user.id

    trial = give_trial(uid)
    bal = get_balance(uid)

    text = f"🎨 PhotoLab AI\n\nБаланс: {bal} генераций"

    if trial:
        text += "\n🎁 Ты получил 1 бесплатную генерацию!"

    await message.answer(text, reply_markup=main_kb())


# =================================================
# BUTTONS
# =================================================

@dp.message(F.text == "👤 Баланс")
async def balance_btn(m):
    await m.answer(f"Баланс: {get_balance(m.from_user.id)} ⭐", reply_markup=main_kb())


@dp.message(F.text == "💎 Магазин")
async def shop_btn(m):
    await m.answer("Выбери пакет:", reply_markup=shop_kb())


@dp.message(F.text == "⬅️ Назад")
async def back_btn(m):
    await m.answer("Главное меню", reply_markup=main_kb())


@dp.message(F.text == "🖼 Создать")
async def create_btn(m):
    await m.answer("Напиши описание картинки ✍️")


@dp.message(F.text == "📸 Фото с описанием")
async def edit_btn(m):
    await m.answer("Отправь фото + подпись")


# =================================================
# ⭐ PAYMENTS
# =================================================

async def send_invoice(message, stars, title):
    prices = [LabeledPrice(label=title, amount=stars)]

    await bot.send_invoice(
        chat_id=message.chat.id,
        title=title,
        description="AI генерации",
        payload="stars",
        currency="XTR",
        prices=prices
    )


@dp.message(F.text.contains("Trial"))
async def buy2(m): await send_invoice(m, 1, "2 генерации")


@dp.message(F.text.contains("Starter"))
async def buy5(m): await send_invoice(m, 75, "5 генераций")


@dp.message(F.text.contains("Popular"))
async def buy10(m): await send_invoice(m, 140, "10 генераций")


@dp.message(F.text.contains("Pro"))
async def buy20(m): await send_invoice(m, 260, "20 генераций")


@dp.pre_checkout_query()
async def checkout(q):
    await bot.answer_pre_checkout_query(q.id, ok=True)


# 🔥 НАДЁЖНАЯ ЛОГИКА ПО amount ⭐
@dp.message(lambda m: m.successful_payment)
async def paid(m):
    stars = m.successful_payment.total_amount

    if stars == 1:
        add_credits(m.from_user.id, 2)
    elif stars == 75:
        add_credits(m.from_user.id, 5)
    elif stars == 140:
        add_credits(m.from_user.id, 10)
    elif stars == 260:
        add_credits(m.from_user.id, 20)

    await m.answer(
        f"Оплачено ✅\nБаланс: {get_balance(m.from_user.id)}",
        reply_markup=main_kb()
    )


# =================================================
# TEXT → IMAGE
# =================================================

@dp.message(lambda msg: msg.text and "⭐" not in msg.text)
async def text_to_image(message: types.Message):

    if not use_credit(message.from_user.id):
        await message.answer("Нет генераций ❌ Открой Магазин", reply_markup=main_kb())
        return

    prompt = message.text[:300]

    msg = await message.answer("Генерю...")

    result = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="512x512"
    )

    img = base64.b64decode(result.data[0].b64_json)

    with open("temp.png", "wb") as f:
        f.write(img)

    await message.answer_photo(types.FSInputFile("temp.png"))
    await msg.delete()


# =================================================

async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
