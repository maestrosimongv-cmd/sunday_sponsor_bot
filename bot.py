import asyncio
import asyncpg
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove

# ========== КОНФИГУРАЦИЯ (жёстко задано для теста) ==========
API_TOKEN = '8659440760:AAGxcuLvyP8oeU5Mmt8g_6kxIwaULdUtZHM'
DATABASE_URL = 'postgresql://neondb_owner:npg_bGuoEjZJt61D@ep-delicate-mountain-alf99j5d.c-3.eu-central-1.aws.neon.tech/neondb?sslmode=require'
ADMIN_IDS = [235845445]
MAX_PER_SLOT = 16

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

class SponsorReg(StatesGroup):
    choosing_time = State()
    entering_nickname = State()
    entering_party_count = State()

async def get_db_connection():
    return await asyncpg.connect(DATABASE_URL)

async def get_available_slots():
    conn = await get_db_connection()
    try:
        rows = await conn.fetch(
            "SELECT slot_id, hour_time, current_count, max_capacity FROM time_slots "
            "WHERE current_count < max_capacity ORDER BY hour_time"
        )
        return rows
    finally:
        await conn.close()

async def get_time_keyboard():
    slots = await get_available_slots()
    if not slots:
        return None
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for slot in slots:
        hour = slot['hour_time'].strftime('%H:%M')
        button_text = f"🕒 *{hour} МСК* ({slot['current_count']}/{slot['max_capacity']})"
        kb.inline_keyboard.append([InlineKeyboardButton(text=button_text, callback_data=f"time_{slot['slot_id']}")])
    return kb

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    kb = await get_time_keyboard()
    if kb is None:
        await message.answer("😞 *Все временные слоты уже заполнены. Попробуйте позже.*", parse_mode="Markdown")
        return
    await message.answer(
        "🎉 *Добро пожаловать в сбор спонсоров!*\n\n*Выберите удобное время (МСК):*",
        reply_markup=kb, parse_mode="Markdown"
    )
    await state.set_state(SponsorReg.choosing_time)

@dp.message(Command("start_collection"))
async def start_collection(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ *Нет прав.*", parse_mode="Markdown")
        return
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 *Начать сбор*", callback_data="start_join")]
    ])
    await message.answer(
        "🎉 *НАБОР СПОНСОРОВ ОТКРЫТ!*\n"
        f"*Максимум участников на один час:* {MAX_PER_SLOT}\n"
        "*Нажмите кнопку, чтобы зарегистрироваться:*",
        reply_markup=inline_kb, parse_mode="Markdown"
    )
    await bot.send_message(ADMIN_IDS[0], "✅ *Кнопка сбора отправлена в чат.*", parse_mode="Markdown")

@dp.callback_query(lambda c: c.data == "start_join")
async def start_join_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    kb = await get_time_keyboard()
    if kb is None:
        await callback.message.answer("😞 *Все временные слоты уже заполнены. Попробуйте позже.*", parse_mode="Markdown")
        return
    await callback.message.answer(
        "🎉 *Добро пожаловать в сбор спонсоров!*\n\n*Выберите удобное время (МСК):*",
        reply_markup=kb, parse_mode="Markdown"
    )
    await state.set_state(SponsorReg.choosing_time)

@dp.callback_query(SponsorReg.choosing_time, lambda c: c.data.startswith("time_"))
async def time_chosen(callback: types.CallbackQuery, state: FSMContext):
    slot_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    await state.update_data(slot_id=slot_id)

    conn = await get_db_connection()
    try:
        check_query = """
            SELECT EXISTS(
                SELECT 1 FROM sponsors s
                JOIN time_slots ts ON s.slot_id = ts.slot_id
                WHERE s.user_id = $1 AND ts.slot_id = $2 AND s.registered_at > NOW() - INTERVAL '48 hours'
            )
        """
        already = await conn.fetchval(check_query, user_id, slot_id)
        if already:
            await callback.answer("❌ Вы уже регистрировались на это время в течение последних 48 часов.", show_alert=True)
            await callback.message.answer("*Пожалуйста, выберите другое время.*", parse_mode="Markdown")
            await state.clear()
            new_kb = await get_time_keyboard()
            if new_kb:
                await callback.message.edit_reply_markup(reply_markup=new_kb)
            return

        slot = await conn.fetchrow("SELECT current_count, max_capacity, hour_time FROM time_slots WHERE slot_id = $1", slot_id)
        if slot and slot['current_count'] >= slot['max_capacity']:
            await callback.answer("⛔ Это время уже заполнено, выберите другое.", show_alert=True)
            await state.clear()
            new_kb = await get_time_keyboard()
            if new_kb:
                await callback.message.edit_reply_markup(reply_markup=new_kb)
            return
        await state.update_data(hour_time=slot['hour_time'])
    finally:
        await conn.close()

    await callback.answer()
    await callback.message.edit_text("*Введите ваш ник и тег (например, Simson idumx):*", parse_mode="Markdown")
    await state.set_state(SponsorReg.entering_nickname)

@dp.message(SponsorReg.entering_nickname)
async def nickname_entered(message: types.Message, state: FSMContext):
    nickname = message.text.strip()
    if len(nickname) < 3:
        await message.answer("*Слишком коротко. Введите ник и тег (например, Simson idumx):*", parse_mode="Markdown")
        return
    await state.update_data(nickname=nickname)
    await message.answer("*Сколько пати вы даете? (введите число):*", parse_mode="Markdown")
    await state.set_state(SponsorReg.entering_party_count)

@dp.message(SponsorReg.entering_party_count)
async def party_count_entered(message: types.Message, state: FSMContext):
    try:
        party_count = int(message.text.strip())
        if party_count <= 0:
            raise ValueError
    except ValueError:
        await message.answer("*Пожалуйста, введите целое положительное число (например, 5).*", parse_mode="Markdown")
        return

    data = await state.get_data()
    slot_id = data['slot_id']
    nickname = data['nickname']
    user_id = message.from_user.id
    username = message.from_user.username or "без юзернейма"
    full_name = message.from_user.full_name

    conn = await get_db_connection()
    try:
        slot = await conn.fetchrow("SELECT slot_id, current_count, max_capacity, hour_time FROM time_slots WHERE slot_id = $1 FOR UPDATE", slot_id)
        if slot['current_count'] >= slot['max_capacity']:
            await message.answer("❌ *Это время уже заполнено. Начните заново, нажав кнопку 'Начать сбор'.*", parse_mode="Markdown")
            await state.clear()
            return

        check_query = """
            SELECT EXISTS(
                SELECT 1 FROM sponsors s
                WHERE s.user_id = $1 AND s.slot_id = $2 AND s.registered_at > NOW() - INTERVAL '48 hours'
            )
        """
        already = await conn.fetchval(check_query, user_id, slot_id)
        if already:
            await message.answer("❌ *Вы уже регистрировались на это время в течение последних 48 часов.*", parse_mode="Markdown")
            await state.clear()
            return

        await conn.execute(
            "INSERT INTO sponsors (slot_id, user_id, username, full_name, nickname_tag, party_count) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            slot_id, user_id, username, full_name, nickname, party_count
        )
        new_count = slot['current_count'] + 1
        await conn.execute("UPDATE time_slots SET current_count = $1 WHERE slot_id = $2", new_count, slot_id)

        hour_str = slot['hour_time'].strftime('%H:%M')
        await message.answer(
            f"🎉 *Поздравляю! Вы зарегистрированы на сбор в {hour_str} МСК.*\n"
            f"*Ваш ник:* {nickname}\n"
            f"*Количество пати:* {party_count}\n"
            f"*Спасибо за участие!*",
            parse_mode="Markdown"
        )

        # Автоудаление диалога через 48 часов
        asyncio.create_task(delete_dialog_later(message.chat.id, 48 * 3600))

        if new_count == MAX_PER_SLOT:
            await send_slot_report(slot_id, conn)
    finally:
        await conn.close()

    await state.clear()
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Начать сбор", callback_data="start_join")]
    ])
    await message.answer(
        "*Хотите записаться на другое время? Нажмите кнопку ниже:*",
        reply_markup=inline_kb, parse_mode="Markdown"
    )

async def send_slot_report(slot_id: int, conn):
    slot = await conn.fetchrow("SELECT hour_time, current_count FROM time_slots WHERE slot_id = $1", slot_id)
    if not slot:
        return
    hour_str = slot['hour_time'].strftime('%H:%M')
    sponsors = await conn.fetch(
        "SELECT nickname_tag, party_count, full_name, username FROM sponsors WHERE slot_id = $1 ORDER BY registered_at",
        slot_id
    )
    report = f"🕒 *Время {hour_str} МСК* ({len(sponsors)}/{MAX_PER_SLOT} спонсоров):\n\n"
    for idx, s in enumerate(sponsors, 1):
        report += f"{idx}. {s['nickname_tag']} — *{s['party_count']} пати*"
        if s['username']:
            report += f" (@{s['username']})"
        report += "\n"
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, report, parse_mode="Markdown")
        except:
            pass

async def delete_dialog_later(chat_id: int, delay_seconds: int):
    await asyncio.sleep(delay_seconds)
    try:
        await bot.send_message(chat_id, "👋 *Ваша регистрация устарела. Для новой регистрации нажмите кнопку в чате.*", parse_mode="Markdown")
        await bot.send_message(chat_id, "Для начала нового сбора нажмите кнопку в том чате, где администратор опубликовал объявление.", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        print(f"Ошибка при удалении диалога: {e}")

async def reminder_worker():
    while True:
        now = datetime.utcnow() + timedelta(hours=3)
        target_hour = now.hour + 1
        conn = await get_db_connection()
        try:
            slots = await conn.fetch("SELECT slot_id, hour_time FROM time_slots WHERE EXTRACT(HOUR FROM hour_time) = $1", target_hour)
            for slot in slots:
                slot_id = slot['slot_id']
                sponsors = await conn.fetch(
                    "SELECT user_id, nickname_tag, party_count, hour_time FROM sponsors s JOIN time_slots ts ON s.slot_id = ts.slot_id WHERE s.slot_id = $1",
                    slot_id
                )
                for sp in sponsors:
                    user_id = sp['user_id']
                    hour_str = sp['hour_time'].strftime('%H:%M')
                    party_count = sp['party_count']
                    nickname = sp['nickname_tag']
                    try:
                        await bot.send_message(
                            user_id,
                            f"⏰ *Напоминание!* Через 1 час, в {hour_str} МСК, у вас запланировано участие в пати.\n"
                            f"*Ник:* {nickname}\n"
                            f"*Пати:* {party_count}\n"
                            f"*Пожалуйста, подготовьтесь вовремя.*",
                            parse_mode="Markdown"
                        )
                    except:
                        pass
        except Exception as e:
            print(f"Ошибка в напоминании: {e}")
        finally:
            await conn.close()
        await asyncio.sleep(3600)

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("*Нет прав.*", parse_mode="Markdown")
        return
    conn = await get_db_connection()
    try:
        slots = await conn.fetch("SELECT hour_time, current_count, max_capacity FROM time_slots ORDER BY hour_time")
        text = "*📊 Статус слотов:*\n\n"
        for s in slots:
            status = "✅ *открыт*" if s['current_count'] < s['max_capacity'] else "❌ *закрыт*"
            text += f"{s['hour_time'].strftime('%H:%M')} МСК: {s['current_count']}/{s['max_capacity']} {status}\n"
        await message.answer(text, parse_mode="Markdown")
    finally:
        await conn.close()

async def reset_slots_48h():
    while True:
        await asyncio.sleep(48 * 3600)
        conn = await get_db_connection()
        try:
            await conn.execute("DELETE FROM sponsors")
            await conn.execute("UPDATE time_slots SET current_count = 0")
            for admin_id in ADMIN_IDS:
                await bot.send_message(admin_id, "🔄 *Автоматический сброс слотов выполнен (каждые 48 часов).*", parse_mode="Markdown")
        except Exception as e:
            print(f"Ошибка сброса: {e}")
        finally:
            await conn.close()

@dp.message(Command("reset_slots"))
async def cmd_reset(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("*Нет прав.*", parse_mode="Markdown")
        return
    conn = await get_db_connection()
    try:
        await conn.execute("DELETE FROM sponsors")
        await conn.execute("UPDATE time_slots SET current_count = 0")
        await message.answer("✅ *Все слоты сброшены. Набор начинается заново.*", parse_mode="Markdown")
    finally:
        await conn.close()

async def main():
    print("Бот запущен (лимит 16, автосброс 48ч, напоминания за час, удаление диалогов 48ч)...")
    await bot.delete_webhook(drop_pending_updates=True)
    asyncio.create_task(reset_slots_48h())
    asyncio.create_task(reminder_worker())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
