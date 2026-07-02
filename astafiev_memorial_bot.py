#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram-бот для Мемориального комплекса В.П. Астафьева в Овсянке
С поддержкой health check для Render.com
Полная админ-панель: удаление мероприятий, добавление фото, управление админами
"""

import asyncio
import os
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from supabase import create_client
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# ========== HEALTH CHECK HTTP СЕРВЕР ==========
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Bot is alive! Astafiev Memorial Complex Bot Running')
    
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()
    
    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    print(f"✅ Health check server running on port {port}")
    server.serve_forever()
# ==========================================

# ========== ИНИЦИАЛИЗАЦИЯ ==========
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ========== ПРОВЕРКА АДМИНА ==========
def is_admin(user_id: int) -> bool:
    try:
        result = supabase.table("admins").select("user_id").eq("user_id", user_id).execute()
        return len(result.data) > 0
    except Exception:
        return False

# ========== ФУНКЦИЯ АВТОУДАЛЕНИЯ СТАРЫХ МЕРОПРИЯТИЙ ==========
async def auto_delete_old_events():
    """Запускается раз в сутки и удаляет мероприятия, которые прошли более 2 дней назад"""
    while True:
        try:
            # Дата, которая была 2 дня назад
            two_days_ago = (datetime.now() - timedelta(days=2)).date()
            
            # Обновляем статус старых мероприятий на is_active = False
            result = supabase.table("events").update({"is_active": False}).lt("event_date", two_days_ago).execute()
            
            if result.data:
                print(f"🗑️ Автоудаление: отключено {len(result.data)} старых мероприятий")
        except Exception as e:
            print(f"❌ Ошибка автоудаления: {e}")
        
        # Ждём 24 часа до следующей проверки
        await asyncio.sleep(86400)

# ========== ГЛАВНОЕ МЕНЮ ==========
def get_main_keyboard(user_id: int):
    keyboard = [
        [KeyboardButton(text="🏛️ О комплексе")],
        [KeyboardButton(text="🎟️ Объекты"), KeyboardButton(text="📅 Афиша")],
        [KeyboardButton(text="🚆 Как добраться"), KeyboardButton(text="📞 Контакты")]
    ]
    if is_admin(user_id):
        keyboard.append([KeyboardButton(text="🔧 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "🏛️ *Добро пожаловать в бот Мемориального комплекса В.П. Астафьева!*\n\n"
        "Я помогу вам узнать всё о музеях в Овсянке:\n"
        "• Национальный центр\n"
        "• Дом-музей писателя\n"
        "• Музей повести «Последний поклон»\n"
        "• Выставочный зал\n\n"
        "Выберите нужный пункт в меню 👇",
        reply_markup=get_main_keyboard(message.from_user.id),
        parse_mode="Markdown"
    )

@dp.message(F.text == "🏛️ О комплексе")
async def about_complex(message: types.Message):
    text = (
        "🏛️ *Мемориальный комплекс В.П. Астафьева в Овсянке*\n\n"
        "Открыт 1 мая 2004 года.\n\n"
        "📍 *В состав комплекса входят:*\n"
        "• Национальный центр (ул. Щетинкина, 30)\n"
        "• Дом-музей Астафьева (ул. Щетинкина, 26)\n"
        "• Музей «Последний поклон» (ул. Щетинкина, 35)\n"
        "• Выставочный зал (ул. Щетинкина, 24)\n\n"
        "🕐 *Режим работы:*\n"
        "Вторник – Воскресенье: 10:00 – 18:00\n"
        "Четверг: 10:00 – 21:00\n"
        "Понедельник — выходной\n\n"
        "📞 *Справки:* +7 (391) 234-74-00"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "🎟️ Объекты")
async def show_objects(message: types.Message):
    try:
        result = supabase.table("objects").select("*").eq("is_active", True).order("order_index").execute()
        objects = result.data
        
        if not objects:
            await message.answer("Информация об объектах временно недоступна.")
            return
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=obj["name_ru"], callback_data=f"obj_{obj['id']}")]
            for obj in objects
        ])
        
        await message.answer("🏛️ *Выберите объект:*", reply_markup=keyboard, parse_mode="Markdown")
    except Exception as e:
        await message.answer("❌ Ошибка загрузки данных. Попробуйте позже.")

@dp.callback_query(F.data.startswith("obj_"))
async def show_object_detail(callback: types.CallbackQuery):
    try:
        obj_id = int(callback.data.split("_")[1])
        result = supabase.table("objects").select("*").eq("id", obj_id).execute()
        
        if not result.data:
            await callback.answer("Объект не найден")
            return
        
        obj = result.data[0]
        
        text = (
            f"🏛️ *{obj['name_ru']}*\n\n"
            f"📍 *Адрес:* {obj['address']}\n"
            f"🕐 *Часы работы:* {obj['working_hours']}\n\n"
            f"💰 *Цены:*\n"
            f"• Взрослые — {obj['price_adult']}₽\n"
            f"• Льготный (дети/студенты/пенсионеры) — {obj['price_discount']}₽\n"
            f"• Многодетные/ветераны/инвалиды III группы — {obj['price_special']}₽\n\n"
            f"{obj['description']}\n\n"
            f"Действует Пушкинская карта."
        )
        
        if obj.get('photo_url'):
            await callback.message.answer_photo(photo=obj['photo_url'], caption=text, parse_mode="Markdown")
        else:
            await callback.message.answer(text, parse_mode="Markdown")
        
        await callback.answer()
    except Exception as e:
        await callback.message.answer("❌ Ошибка загрузки информации об объекте.")
        await callback.answer()

@dp.message(F.text == "📅 Афиша")
async def show_events(message: types.Message):
    try:
        result = supabase.table("events").select("*").eq("is_active", True).order("event_date").execute()
        events = result.data
        
        if not events:
            await message.answer("На данный момент запланированных мероприятий нет. Следите за обновлениями!")
            return
        
        text = "📅 *Афиша мероприятий:*\n\n"
        for event in events:
            date_str = event['event_date']
            time_str = f" {event['start_time']}" if event.get('start_time') else ""
            text += f"• *{date_str}*{time_str} — {event['title']}\n"
            if event.get('description'):
                text += f"  _{event['description']}_\n"
            if event.get('price'):
                text += f"  Стоимость: {event['price']}\n"
            text += "\n"
        
        await message.answer(text, parse_mode="Markdown")
    except Exception as e:
        await message.answer("❌ Ошибка загрузки афиши.")

@dp.message(F.text == "🚆 Как добраться")
async def how_to_get(message: types.Message):
    text = (
        "🚆 *Как добраться до Овсянки из Красноярска*\n\n"
        "🚂 *Электричка:*\n"
        "От ж/д вокзала Красноярска до станции Овсянка\n"
        "Время в пути: ~1 час\n\n"
        "🚌 *Автобус:*\n"
        "№146 от автовокзала, №106 от Предмостной площади\n\n"
        "🚗 *Автомобиль:*\n"
        "Трасса Р-257 «Енисей» в сторону Дивногорска, ~40 км"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "📞 Контакты")
async def contacts(message: types.Message):
    text = (
        "📞 *Контакты Мемориального комплекса*\n\n"
        "🏛️ *Администрация:* +7 (391) 234-74-00\n"
        "📧 Email: astafiev@kkkm.ru\n\n"
        "🌐 *Сайт:* astafiev.kkkm.ru\n"
        "📱 *ВКонтакте:* Мемориальный комплекс В.П. Астафьева в Овсянке\n\n"
        "📍 *Физический адрес:*\n"
        "Красноярский край, с. Овсянка, ул. Щетинкина, 30"
    )
    await message.answer(text, parse_mode="Markdown")

# ========== АДМИН-ПАНЕЛЬ (РАСШИРЕННАЯ) ==========
class AddEventState(StatesGroup):
    title = State()
    description = State()
    date = State()
    time = State()
    price = State()

class AddPhotoState(StatesGroup):
    select_object = State()
    upload_photo = State()

class AddAdminState(StatesGroup):
    user_id = State()
    username = State()

@dp.message(F.text == "🔧 Админ-панель")
async def admin_panel(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к админ-панели.")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Добавить мероприятие", callback_data="admin_add_event")],
        [InlineKeyboardButton(text="🗑️ Удалить мероприятие", callback_data="admin_delete_event")],
        [InlineKeyboardButton(text="🖼️ Добавить фото для объекта", callback_data="admin_add_photo")],
        [InlineKeyboardButton(text="👥 Добавить администратора", callback_data="admin_add_admin")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")]
    ])
    
    await message.answer(
        "🔧 *Админ-панель*\n\n"
        "Выберите действие:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# ========== 1. ДОБАВЛЕНИЕ МЕРОПРИЯТИЯ ==========
@dp.callback_query(F.data == "admin_add_event")
async def add_event_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    
    await state.set_state(AddEventState.title)
    await callback.message.answer("📝 Введите *название мероприятия*:")
    await callback.answer()

@dp.message(AddEventState.title)
async def add_event_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddEventState.description)
    await message.answer("📄 Введите *описание* (или '-' чтобы пропустить):", parse_mode="Markdown")

@dp.message(AddEventState.description)
async def add_event_description(message: types.Message, state: FSMContext):
    desc = message.text if message.text != "-" else ""
    await state.update_data(description=desc)
    await state.set_state(AddEventState.date)
    await message.answer("📅 Введите *дату* в формате ГГГГ-ММ-ДД\nНапример: 2026-06-20")

@dp.message(AddEventState.date)
async def add_event_date(message: types.Message, state: FSMContext):
    await state.update_data(date=message.text)
    await state.set_state(AddEventState.time)
    await message.answer("⏰ Введите *время* (например, 14:00) или '-' чтобы пропустить:")

@dp.message(AddEventState.time)
async def add_event_time(message: types.Message, state: FSMContext):
    time_val = message.text if message.text != "-" else None
    await state.update_data(time=time_val)
    await state.set_state(AddEventState.price)
    await message.answer("💰 Введите *стоимость* (например, 'Бесплатно' или '250 руб.'):")

@dp.message(AddEventState.price)
async def add_event_price(message: types.Message, state: FSMContext):
    data = await state.get_data()
    
    try:
        supabase.table("events").insert({
            "title": data['title'],
            "description": data['description'],
            "event_date": data['date'],
            "start_time": data['time'],
            "price": message.text,
            "is_active": True
        }).execute()
        
        await message.answer(f"✅ Мероприятие *«{data['title']}»* успешно добавлено!\n\nОно появится в разделе «Афиша».", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ Ошибка при добавлении мероприятия: {str(e)}")
    
    await state.clear()

# ========== 2. УДАЛЕНИЕ МЕРОПРИЯТИЯ ==========
@dp.callback_query(F.data == "admin_delete_event")
async def delete_event_list(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    
    try:
        result = supabase.table("events").select("*").eq("is_active", True).order("event_date").execute()
        events = result.data
        
        if not events:
            await callback.message.answer("📭 Нет активных мероприятий для удаления.")
            await callback.answer()
            return
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{e['event_date']} — {e['title']}", callback_data=f"del_{e['id']}")]
            for e in events
        ])
        
        await callback.message.answer(
            "🗑️ *Выберите мероприятие для удаления:*",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await callback.answer()
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {str(e)}")
        await callback.answer()

@dp.callback_query(F.data.startswith("del_"))
async def confirm_delete_event(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    
    event_id = int(callback.data.split("_")[1])
    
    # Получаем название мероприятия для подтверждения
    result = supabase.table("events").select("title").eq("id", event_id).execute()
    if result.data:
        event_title = result.data[0]['title']
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_del_{event_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_delete")]
        ])
        
        await callback.message.answer(
            f"⚠️ Вы уверены, что хотите удалить мероприятие *«{event_title}»*?\n\nЭто действие необратимо.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_del_"))
async def execute_delete_event(callback: types.CallbackQuery):
    event_id = int(callback.data.split("_")[2])
    
    try:
        # Получаем название перед удалением
        result = supabase.table("events").select("title").eq("id", event_id).execute()
        event_title = result.data[0]['title'] if result.data else "мероприятие"
        
        # Удаляем (или помечаем is_active = False)
        supabase.table("events").update({"is_active": False}).eq("id", event_id).execute()
        
        await callback.message.answer(f"✅ Мероприятие *«{event_title}»* удалено из афиши.", parse_mode="Markdown")
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка при удалении: {str(e)}")
    
    await callback.answer()

@dp.callback_query(F.data == "cancel_delete")
async def cancel_delete(callback: types.CallbackQuery):
    await callback.message.answer("❌ Удаление отменено.")
    await callback.answer()

# ========== 3. ДОБАВЛЕНИЕ ФОТО ДЛЯ ОБЪЕКТА ==========
@dp.callback_query(F.data == "admin_add_photo")
async def add_photo_select_object(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    
    try:
        result = supabase.table("objects").select("id, name_ru").eq("is_active", True).execute()
        objects = result.data
        
        if not objects:
            await callback.message.answer("❌ Нет доступных объектов.")
            await callback.answer()
            return
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=obj['name_ru'], callback_data=f"photoobj_{obj['id']}")]
            for obj in objects
        ])
        
        await state.set_state(AddPhotoState.select_object)
        await callback.message.answer(
            "🖼️ *Выберите объект, для которого хотите добавить фото:*",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await callback.answer()
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {str(e)}")
        await callback.answer()

@dp.callback_query(F.data.startswith("photoobj_"), AddPhotoState.select_object)
async def add_photo_upload(callback: types.CallbackQuery, state: FSMContext):
    object_id = int(callback.data.split("_")[1])
    await state.update_data(object_id=object_id)
    await state.set_state(AddPhotoState.upload_photo)
    
    await callback.message.answer(
        "📸 Отправьте *фотографию* для этого объекта.\n\n"
        "Просто отправьте изображение — оно автоматически загрузится.",
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message(AddPhotoState.upload_photo, F.photo)
async def add_photo_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    object_id = data['object_id']
    
    try:
        # Получаем файл
        photo = message.photo[-1]  # Самое большое разрешение
        file = await bot.get_file(photo.file_id)
        file_bytes = await bot.download_file(file.file_path)
        
        # Сохраняем в Supabase Storage
        file_name = f"object_{object_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        
        # Загружаем в бакет museum_photos
        supabase.storage.from_("museum_photos").upload(
            file_name,
            file_bytes.getvalue(),
            {"content-type": "image/jpeg"}
        )
        
        # Получаем публичную ссылку
        public_url = supabase.storage.from_("museum_photos").get_public_url(file_name)
        
        # Обновляем запись в таблице objects
        supabase.table("objects").update({"photo_url": public_url}).eq("id", object_id).execute()
        
        await message.answer(
            f"✅ Фото успешно загружено!\n\n"
            f"Теперь при просмотре объекта будет отображаться это изображение."
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при загрузке фото: {str(e)}")
    
    await state.clear()

@dp.message(AddPhotoState.upload_photo)
async def add_photo_invalid(message: types.Message):
    await message.answer("❌ Пожалуйста, отправьте *фотографию* (не текст или другой файл).", parse_mode="Markdown")

# ========== ДОБАВЛЕНИЕ АДМИНИСТРАТОРА (с проверкой существования пользователя) ==========
class AddAdminState(StatesGroup):
    user_id = State()

@dp.callback_query(F.data == "admin_add_admin")
async def add_admin_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    
    await state.set_state(AddAdminState.user_id)
    await callback.message.answer(
        "👥 *Добавление нового администратора*\n\n"
        "Введите *Telegram ID* пользователя.\n\n"
        "Как узнать ID:\n"
        "1. Попросите пользователя написать @userinfobot\n"
        "2. Он пришлёт сообщение с его ID (число)\n\n"
        "Введите ID:",
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message(AddAdminState.user_id)
async def add_admin_check_user(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Неверный формат. Введите число (Telegram ID).\n\nПопробуйте ещё раз:")
        return
    
    try:
        # ПЫТАЕМСЯ ПОЛУЧИТЬ ИНФОРМАЦИЮ О ПОЛЬЗОВАТЕЛЕ ЧЕРЕЗ TELEGRAM API
        # Это проверит, существует ли пользователь с таким ID
        user_info = await bot.get_chat(user_id)
        
        # Если дошли сюда — пользователь существует
        username = user_info.username if user_info.username else None
        first_name = user_info.first_name
        
        # Проверяем, не админ ли уже
        existing = supabase.table("admins").select("user_id").eq("user_id", user_id).execute()
        if existing.data:
            await message.answer(
                f"❌ Пользователь *{first_name}* (ID: `{user_id}`) уже является администратором.",
                parse_mode="Markdown"
            )
            await state.clear()
            return
        
        # Добавляем администратора
        supabase.table("admins").insert({
            "user_id": user_id,
            "username": username,
            "role": "editor"
        }).execute()
        
        await message.answer(
            f"✅ *Новый администратор добавлен!*\n\n"
            f"• Имя: {first_name}\n"
            f"• Username: {'@' + username if username else 'не указан'}\n"
            f"• ID: `{user_id}`\n\n"
            f"Теперь этот пользователь будет видеть кнопку «Админ-панель».",
            parse_mode="Markdown"
        )
        
        # Опционально: отправить уведомление новому администратору
        try:
            await bot.send_message(
                user_id,
                f"🎉 *Вы стали администратором бота Мемориального комплекса Астафьева!*\n\n"
                f"Теперь вам доступна админ-панель. Напишите /start, чтобы увидеть кнопку «🔧 Админ-панель».",
                parse_mode="Markdown"
            )
        except Exception:
            pass  # Не отправилось — ничего страшного
        
    except Exception as e:
        error_text = str(e)
        if "USER_ID_INVALID" in error_text or "user not found" in error_text.lower():
            await message.answer(
                f"❌ Пользователь с ID `{user_id}` не найден в Telegram.\n\n"
                f"Проверьте правильность ID и попробуйте снова.\n\n"
                f"Как узнать ID: @userinfobot",
                parse_mode="Markdown"
            )
        else:
            await message.answer(f"❌ Ошибка: {error_text}")
    
    await state.clear()

# ========== 5. СТАТИСТИКА ==========
@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён")
        return
    
    try:
        objects_count = supabase.table("objects").select("id", count="exact").execute()
        events_count = supabase.table("events").select("id", count="exact").execute()
        admins_count = supabase.table("admins").select("user_id", count="exact").execute()
        
        await callback.message.answer(
            f"📊 *Статистика бота*\n\n"
            f"🏛️ Объектов в базе: {objects_count.count}\n"
            f"📅 Мероприятий: {events_count.count}\n"
            f"👥 Администраторов: {admins_count.count}\n\n"
            f"⚡ Работает на Supabase + aiogram\n"
            f"🗑️ Старые мероприятия удаляются автоматически через 2 дня",
            parse_mode="Markdown"
        )
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {str(e)}")
    
    await callback.answer()

# ========== ЗАПУСК ==========
async def main():
    print("🚀 Запуск бота...")

    await bot.delete_webhook()
    print("✅ Webhook удалён")
    # Проверяем подключение к Supabase
    try:
        supabase.table("admins").select("user_id").limit(1).execute()
        print("✅ Подключение к Supabase успешно")
    except Exception as e:
        print(f"❌ Ошибка подключения к Supabase: {e}")
        return
    
    # Проверяем наличие токена бота
    if not BOT_TOKEN or BOT_TOKEN == "ВАШ_ТОКЕН_ОТ_BOTFATHER":
        print("❌ Не указан BOT_TOKEN в переменных окружения!")
        return
    
    print("✅ Токен бота загружен")
    
    # Запускаем health check сервер в отдельном потоке
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    print("✅ Health check сервер запущен на порту 8080")
    
    # Запускаем фоновую задачу автоудаления старых мероприятий
    asyncio.create_task(auto_delete_old_events())
    print("✅ Запущена задача автоудаления старых мероприятий (каждые 24 часа)")
    
    print("🤖 Бот для Мемориального комплекса Астафьева успешно запущен!")
    print("📱 Откройте Telegram и найдите бота")
    print("\n🔧 Доступные функции админ-панели:")
    print("   • 📝 Добавить мероприятие")
    print("   • 🗑️ Удалить мероприятие")
    print("   • 🖼️ Добавить фото для объекта")
    print("   • 👥 Добавить администратора")
    print("   • 📊 Статистика")
    print("   • ⏰ Автоудаление старых событий (каждую ночь)")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
