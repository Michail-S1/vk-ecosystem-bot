import sqlite3
import os
import pandas as pd
from vkbottle import BaseStateGroup, Keyboard, KeyboardButtonColor, Text, BaseMiddleware
from vkbottle.bot import Bot, Message
from vkbottle.tools import DocMessagesUploader

# ТОКЕН: Твой ключ из ВК
TOKEN = "tokennn"

# Твой реальный ID ВКонтакте
ADMIN_IDS = [614064375]

bot = Bot(token=TOKEN)


# =====================================================================
# 0. ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ (Автоматическое создание таблиц)
# =====================================================================
def init_db():
    conn = sqlite3.connect("bot_data.db")
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS Users (vk_id INTEGER PRIMARY KEY, full_name TEXT, team TEXT, mini_team TEXT, role TEXT DEFAULT 'user');
        CREATE TABLE IF NOT EXISTS Tasks (task_id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, name TEXT, description TEXT);
        CREATE TABLE IF NOT EXISTS Submissions (submission_id INTEGER PRIMARY KEY AUTOINCREMENT, vk_id INTEGER, task_id INTEGER, link TEXT);
        CREATE TABLE IF NOT EXISTS Scores (score_id INTEGER PRIMARY KEY AUTOINCREMENT, target_id TEXT, type TEXT, amount INTEGER, task_id INTEGER);
    """)
    conn.commit()
    conn.close()


init_db()


def query_db(query, args=(), one=False, commit=False):
    conn = sqlite3.connect("bot_data.db")
    cursor = conn.cursor()
    cursor.execute(query, args)
    if commit:
        conn.commit()
        conn.close()
        return
    rv = cursor.fetchall()
    conn.close()
    return (rv[0] if rv else None) if one else rv


# =====================================================================
# 1. MIDDLEWARE (Глобальный перехватчик кнопок)
# =====================================================================
class GlobalMenuMiddleware(BaseMiddleware[Message]):
    async def pre(self):
        # Если юзер жмет главные кнопки - принудительно сбрасываем его состояние
        main_commands = ["/админ", "Задание", "Баланс", "Рейтинг", "Меню пользователя"]
        if self.event.text in main_commands:
            state = await bot.state_dispenser.get(self.event.peer_id)
            if state:
                await bot.state_dispenser.delete(self.event.peer_id)


bot.labeler.message_view.register_middleware(GlobalMenuMiddleware)

# =====================================================================
# 2. СОЗДАНИЕ КЛАВИАТУР (КНОПОК)
# =====================================================================
admin_keyboard = (
    Keyboard(one_time=False)
    .add(Text("Выгрузка рейтинг"), color=KeyboardButtonColor.PRIMARY)
    .row()
    .add(Text("Выгрузка по заданиям"), color=KeyboardButtonColor.PRIMARY)
    .row()
    .add(Text("Зачислить баллы"), color=KeyboardButtonColor.POSITIVE)
    .row()
    .add(Text("Меню пользователя"), color=KeyboardButtonColor.NEGATIVE)
).get_json()

main_keyboard = (
    Keyboard(one_time=False)
    .add(Text("Задание"), color=KeyboardButtonColor.PRIMARY)
    .row()
    .add(Text("Баланс"), color=KeyboardButtonColor.SECONDARY)
    .add(Text("Рейтинг"), color=KeyboardButtonColor.SECONDARY)
).get_json()

type_keyboard = (
    Keyboard(one_time=False)
    .add(Text("Индивидуальное"), color=KeyboardButtonColor.PRIMARY)
    .add(Text("Групповое"), color=KeyboardButtonColor.PRIMARY)
    .row()
    .add(Text("Назад"), color=KeyboardButtonColor.NEGATIVE)
).get_json()

tasks_keyboard = (
    Keyboard(one_time=False)
    .add(Text("Задание 1"), color=KeyboardButtonColor.SECONDARY)
    .add(Text("Задание 2"), color=KeyboardButtonColor.SECONDARY)
    .row()
    .add(Text("Назад"), color=KeyboardButtonColor.NEGATIVE)
).get_json()

back_only_keyboard = (
    Keyboard(one_time=False)
    .add(Text("Назад"), color=KeyboardButtonColor.NEGATIVE)
).get_json()


# =====================================================================
# 3. ОПИСАНИЕ ЭТАПОВ (СОСТОЯНИЙ)
# =====================================================================
class RegistrationState(BaseStateGroup):
    WAITING_FOR_TEAM = 0
    WAITING_FOR_MINI_TEAM = 1
    WAITING_FOR_FIO = 2


class TaskState(BaseStateGroup):
    CHOOSING_TYPE = 10
    CHOOSING_TASK = 11
    WAITING_FOR_LINK = 12


class RatingState(BaseStateGroup):
    CHOOSING_TYPE = 20


class AdminState(BaseStateGroup):
    WAITING_RATING_TYPE = 30
    WAITING_SCORE_TYPE = 31
    WAITING_SCORE_DATA = 32
    WAITING_TASK_EXPORT_TYPE = 33
    WAITING_TASK_EXPORT_NUM = 34


# =====================================================================
# 4. ОБРАБОТКА КНОПКИ «НАЗАД»
# =====================================================================
@bot.on.private_message(text="Назад")
async def go_back(message: Message):
    vk_id = message.peer_id
    state_payload = await bot.state_dispenser.get(vk_id)

    if not state_payload:
        await message.answer("Главное меню:", keyboard=main_keyboard)
        return

    current_state = state_payload.state

    if current_state in [TaskState.CHOOSING_TYPE, RatingState.CHOOSING_TYPE]:
        await bot.state_dispenser.delete(vk_id)
        await message.answer("Главное меню:", keyboard=main_keyboard)
    elif current_state == TaskState.CHOOSING_TASK:
        await bot.state_dispenser.set(vk_id, TaskState.CHOOSING_TYPE)
        await message.answer("Какой тип задания ты хочешь?", keyboard=type_keyboard)
    elif current_state == TaskState.WAITING_FOR_LINK:
        old_type = state_payload.payload.get("task_type")
        await bot.state_dispenser.set(vk_id, TaskState.CHOOSING_TASK, task_type=old_type)
        await message.answer(f"Выбери {old_type} задание:", keyboard=tasks_keyboard)
    elif current_state == AdminState.WAITING_SCORE_DATA:
        await bot.state_dispenser.set(vk_id, AdminState.WAITING_SCORE_TYPE)
        await message.answer("Кому зачислить баллы?", keyboard=type_keyboard)
    elif current_state in [AdminState.WAITING_SCORE_TYPE, AdminState.WAITING_RATING_TYPE,
                           AdminState.WAITING_TASK_EXPORT_TYPE]:
        await bot.state_dispenser.delete(vk_id)
        await message.answer("🛠 Панель Администратора", keyboard=admin_keyboard)
    elif current_state == AdminState.WAITING_TASK_EXPORT_NUM:
        await bot.state_dispenser.set(vk_id, AdminState.WAITING_TASK_EXPORT_TYPE)
        await message.answer("Какой тип заданий выгрузить?", keyboard=type_keyboard)


# =====================================================================
# 5. ЛОГИКА ВЕТКИ «ЗАДАНИЯ»
# =====================================================================
@bot.on.private_message(text="Задание")
async def task_menu(message: Message):
    await bot.state_dispenser.set(message.peer_id, TaskState.CHOOSING_TYPE)
    await message.answer("Какой тип задания ты хочешь?", keyboard=type_keyboard)


@bot.on.private_message(state=TaskState.CHOOSING_TYPE, text=["Индивидуальное", "Групповое"])
async def choose_task_type(message: Message):
    selected_type = message.text.lower()
    await bot.state_dispenser.set(message.peer_id, TaskState.CHOOSING_TASK, task_type=selected_type)
    await message.answer(f"Выбери {selected_type} задание:", keyboard=tasks_keyboard)


@bot.on.private_message(state=TaskState.CHOOSING_TASK, text=["Задание 1", "Задание 2"])
async def view_task_details(message: Message):
    task_name = message.text
    state_payload = await bot.state_dispenser.get(message.peer_id)
    selected_type = state_payload.payload.get("task_type")

    await bot.state_dispenser.set(
        message.peer_id, TaskState.WAITING_FOR_LINK, task_type=selected_type, task_name=task_name
    )
    await message.answer(
        f"Название: {task_name} ({selected_type})\n"
        f"Описание: Выполните условия и прикрепите ссылку в ответ на это сообщение.\n\nЖду ссылку:",
        keyboard=back_only_keyboard
    )


@bot.on.private_message(state=TaskState.WAITING_FOR_LINK)
async def receive_link(message: Message):
    vk_id = message.peer_id
    user_link = message.text

    if not user_link.startswith("http"):
        await message.answer("Пожалуйста, пришлите корректную ссылку (начинающуюся с http:// или https://)")
        return

    state_payload = await bot.state_dispenser.get(vk_id)
    task_name = state_payload.payload.get("task_name")

    # Парсим номер задания из текста (например, из "Задание 1" достаем 1)
    task_id = int(task_name.replace("Задание ", "").strip())

    # Записываем ссылку в БД
    query_db("INSERT INTO Submissions (vk_id, task_id, link) VALUES (?, ?, ?)", (vk_id, task_id, user_link),
             commit=True)

    await bot.state_dispenser.delete(vk_id)
    await message.answer(f"Ссылка на {task_name} успешно сохранена в базу данных для админа!", keyboard=main_keyboard)


# =====================================================================
# 6. БАЛАНС И РЕЙТИНГ
# =====================================================================
@bot.on.private_message(text="Баланс")
async def balance_menu(message: Message):
    vk_id = message.peer_id
    user = query_db("SELECT team, mini_team FROM Users WHERE vk_id = ?", (vk_id,), one=True)
    if not user: return

    team, mini_team = user[0], user[1]
    ind_scores = query_db("SELECT task_id, amount FROM Scores WHERE target_id = ? AND type = 'индивидуальное'",
                          (str(vk_id),))
    grp_scores = query_db("SELECT task_id, amount FROM Scores WHERE target_id = ? AND type = 'групповое'", (mini_team,))

    text = f"📊 Твой баланс и история начислений!\n\nКоманда: {team}\nМини-команда: {mini_team}\n\n"
    ind_total, grp_total = 0, 0

    if ind_scores:
        text += "👤 Индивидуальные начисления:\n"
        for task_id, amount in ind_scores:
            text += f"• Задание {task_id}: +{amount} баллов\n"
            ind_total += amount
        text += f"Итого индивидуальных: {ind_total}\n\n"

    if grp_scores:
        text += "👥 Начисления команды:\n"
        for task_id, amount in grp_scores:
            text += f"• Задание {task_id}: +{amount} баллов\n"
            grp_total += amount
        text += f"Итого командных: {grp_total}\n\n"

    text += f"🏆 Общее количество твоих баллов: {ind_total + grp_total}"
    await message.answer(text, keyboard=main_keyboard)


@bot.on.private_message(text="Рейтинг")
async def rating_menu(message: Message):
    await bot.state_dispenser.set(message.peer_id, RatingState.CHOOSING_TYPE)
    await message.answer("Какой рейтинг ты хочешь посмотреть?", keyboard=type_keyboard)


@bot.on.private_message(state=RatingState.CHOOSING_TYPE, text=["Индивидуальное", "Групповое"])
async def show_rating(message: Message):
    vk_id = message.peer_id
    rating_type = message.text.lower()

    if rating_type == "индивидуальное":
        query = "SELECT target_id, SUM(amount) as total FROM Scores WHERE type = 'индивидуальное' GROUP BY target_id ORDER BY total DESC"
        results = query_db(query)
        text = "🏆 Индивидуальный рейтинг:\n\n"
        place = 1
        user_place, user_score = "Нет в рейтинге", 0

        if results:
            for row in results:
                target_id, total = row[0], row[1]
                if place <= 5: text += f"{place} место: ID {target_id} — {total} баллов\n"
                if str(vk_id) == str(target_id):
                    user_place, user_score = place, total
                place += 1
        else:
            text += "Рейтинг пока пуст.\n"

        text += f"\nТвое место: {user_place}\nТвои баллы: {user_score}"
        await message.answer(text, keyboard=type_keyboard)

    elif rating_type == "групповое":
        query = "SELECT target_id, SUM(amount) as total FROM Scores WHERE type = 'групповое' GROUP BY target_id ORDER BY total DESC"
        results = query_db(query)
        text = "🏆 Групповой рейтинг:\n\n"
        place = 1

        if results:
            for row in results:
                text += f"{place} место: Команда {row[0]} — {row[1]} баллов\n"
                place += 1
        else:
            text += "Рейтинг пока пуст.\n"
        await message.answer(text, keyboard=type_keyboard)


# =====================================================================
# 7. АДМИН ПАНЕЛЬ
# =====================================================================
@bot.on.private_message(text="/админ")
async def enter_admin(message: Message):
    if message.peer_id in ADMIN_IDS:
        await message.answer("🛠 Добро пожаловать в панель Администратора!", keyboard=admin_keyboard)
    else:
        await message.answer("У вас нет прав доступа к этой команде.")


@bot.on.private_message(text="Меню пользователя")
async def exit_admin(message: Message):
    await message.answer("Возвращаюсь в режим пользователя.", keyboard=main_keyboard)


# --- 1. ВЫГРУЗКА РЕЙТИНГА ---
@bot.on.private_message(text="Выгрузка рейтинг")
async def admin_export_rating(message: Message):
    if message.peer_id not in ADMIN_IDS: return
    await bot.state_dispenser.set(message.peer_id, AdminState.WAITING_RATING_TYPE)
    await message.answer("Какой тип рейтинга выгрузить?", keyboard=type_keyboard)


@bot.on.private_message(state=AdminState.WAITING_RATING_TYPE, text=["Индивидуальное", "Групповое"])
async def process_rating_export(message: Message):
    if message.peer_id not in ADMIN_IDS: return
    rating_type = message.text.lower()
    await message.answer("Собираю данные, формирую Excel...")

    try:
        if rating_type == "индивидуальное":
            query = "SELECT Users.vk_id as ID_ВК, Users.full_name as ФИО, SUM(Scores.amount) as Сумма_баллов FROM Users LEFT JOIN Scores ON Users.vk_id = Scores.target_id AND Scores.type = 'индивидуальное' GROUP BY Users.vk_id ORDER BY Сумма_баллов DESC"
        else:
            query = "SELECT Users.mini_team as Мини_команда, Users.team as Команда, SUM(Scores.amount) as Сумма_баллов FROM Users LEFT JOIN Scores ON Users.mini_team = Scores.target_id AND Scores.type = 'групповое' GROUP BY Users.mini_team ORDER BY Сумма_баллов DESC"

        conn = sqlite3.connect("bot_data.db")
        df = pd.read_sql_query(query, conn)
        conn.close()

        if df.empty:
            await message.answer("Нет данных для выгрузки.", keyboard=admin_keyboard)
            await bot.state_dispenser.delete(message.peer_id)
            return

        df['Сумма_баллов'] = df['Сумма_баллов'].fillna(0)
        df.insert(0, 'Место', range(1, 1 + len(df)))

        filename = f"rating_{rating_type}.xlsx"
        df.to_excel(filename, index=False)
        uploader = DocMessagesUploader(bot.api)
        doc = await uploader.upload(file_source=filename, peer_id=message.peer_id, title=f"Рейтинг_{rating_type}.xlsx")

        await message.answer(f"✅ Файл выгрузки готов:", attachment=doc, keyboard=admin_keyboard)
        await bot.state_dispenser.delete(message.peer_id)
        os.remove(filename)
    except Exception as e:
        await message.answer(f"❌ Ошибка при создании файла: {e}", keyboard=admin_keyboard)
        await bot.state_dispenser.delete(message.peer_id)


# --- 2. ВЫГРУЗКА ПО ЗАДАНИЯМ (Ссылки юзеров) ---
@bot.on.private_message(text="Выгрузка по заданиям")
async def admin_export_tasks(message: Message):
    if message.peer_id not in ADMIN_IDS: return
    await bot.state_dispenser.set(message.peer_id, AdminState.WAITING_TASK_EXPORT_TYPE)
    await message.answer("Какой тип заданий выгрузить?", keyboard=type_keyboard)


@bot.on.private_message(state=AdminState.WAITING_TASK_EXPORT_TYPE, text=["Индивидуальное", "Групповое"])
async def admin_export_tasks_type(message: Message):
    if message.peer_id not in ADMIN_IDS: return
    await bot.state_dispenser.set(message.peer_id, AdminState.WAITING_TASK_EXPORT_NUM)
    await message.answer("Выберите задание для выгрузки:", keyboard=tasks_keyboard)


@bot.on.private_message(state=AdminState.WAITING_TASK_EXPORT_NUM)
async def process_task_export(message: Message):
    if message.peer_id not in ADMIN_IDS: return

    task_id = int(message.text.replace("Задание ", "").strip())
    await message.answer("Формирую выгрузку ссылок...")

    try:
        query = """
        SELECT Users.vk_id as 'ID ВК', Users.full_name as 'ФИО', Users.team as 'Команда', Users.mini_team as 'Мини-команда', Submissions.link as 'Ссылка'
        FROM Submissions
        JOIN Users ON Submissions.vk_id = Users.vk_id
        WHERE Submissions.task_id = ?
        """
        conn = sqlite3.connect("bot_data.db")
        df = pd.read_sql_query(query, conn, params=(task_id,))
        conn.close()

        if df.empty:
            await message.answer(f"По заданию {task_id} пока нет отправленных ссылок.", keyboard=admin_keyboard)
            await bot.state_dispenser.delete(message.peer_id)
            return

        filename = f"task_{task_id}_links.xlsx"
        df.to_excel(filename, index=False)
        uploader = DocMessagesUploader(bot.api)
        doc = await uploader.upload(file_source=filename, peer_id=message.peer_id,
                                    title=f"Ссылки_Задание_{task_id}.xlsx")

        await message.answer(f"✅ Файл со ссылками готов:", attachment=doc, keyboard=admin_keyboard)
        await bot.state_dispenser.delete(message.peer_id)
        os.remove(filename)
    except Exception as e:
        await message.answer(f"❌ Ошибка выгрузки: {e}", keyboard=admin_keyboard)
        await bot.state_dispenser.delete(message.peer_id)


# --- 3. ЗАЧИСЛЕНИЕ БАЛЛОВ ---
@bot.on.private_message(text="Зачислить баллы")
async def admin_score_menu(message: Message):
    if message.peer_id not in ADMIN_IDS: return
    await bot.state_dispenser.set(message.peer_id, AdminState.WAITING_SCORE_TYPE)
    await message.answer("Кому зачислить баллы?", keyboard=type_keyboard)


@bot.on.private_message(state=AdminState.WAITING_SCORE_TYPE, text=["Индивидуальное", "Групповое"])
async def admin_choose_score_type(message: Message):
    if message.peer_id not in ADMIN_IDS: return
    score_type = message.text.lower()
    await bot.state_dispenser.set(message.peer_id, AdminState.WAITING_SCORE_DATA, score_type=score_type)

    primer = "12345678 | 1 | 10  (ID | Задание | Баллы)" if score_type == "индивидуальное" else "1.1 | 2 | 15  (Мини-команда | Задание | Баллы)"
    await message.answer(f"Введите данные для начисления:\n\nПример: {primer}", keyboard=back_only_keyboard)


@bot.on.private_message(state=AdminState.WAITING_SCORE_DATA)
async def admin_process_scoring(message: Message):
    if message.peer_id not in ADMIN_IDS: return
    raw_data = message.text
    state_payload = await bot.state_dispenser.get(message.peer_id)
    score_type = state_payload.payload.get("score_type")

    if "|" not in raw_data or raw_data.count("|") != 2:
        await message.answer("❌ Неверный формат!\nПример: `ID | Задание | Баллы`")
        return

    try:
        parts = [p.strip() for p in raw_data.split("|")]
        target_id, task_id, amount = parts[0], int(parts[1]), int(parts[2])

        query_db("INSERT INTO Scores (target_id, task_id, type, amount) VALUES (?, ?, ?, ?)",
                 (target_id, task_id, score_type, amount), commit=True)
        await message.answer(
            f"✅ Успешно начислено!\nТип: {score_type.capitalize()}\nКому: {target_id}\nЗадание: {task_id}\nБаллы: +{amount}",
            keyboard=admin_keyboard)
        await bot.state_dispenser.delete(message.peer_id)
    except ValueError:
        await message.answer("❌ Номер задания и баллы должны быть числами.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


# =====================================================================
# 8. РЕГИСТРАЦИЯ И ПРИВЕТСТВИЕ (В САМОМ НИЗУ)
# =====================================================================
@bot.on.private_message(state=RegistrationState.WAITING_FOR_TEAM)
async def get_team(message: Message):
    await bot.state_dispenser.set(message.peer_id, RegistrationState.WAITING_FOR_MINI_TEAM, team=message.text)
    await message.answer("Отлично, напиши свою мини-команду (напр., 1.1)")


@bot.on.private_message(state=RegistrationState.WAITING_FOR_MINI_TEAM)
async def get_mini_team(message: Message):
    state_payload = await bot.state_dispenser.get(message.peer_id)
    await bot.state_dispenser.set(message.peer_id, RegistrationState.WAITING_FOR_FIO,
                                  team=state_payload.payload["team"], mini_team=message.text)
    await message.answer("Супер! А теперь напиши свое ФИО")


@bot.on.private_message(state=RegistrationState.WAITING_FOR_FIO)
async def get_fio(message: Message):
    state_payload = await bot.state_dispenser.get(message.peer_id)
    query_db("INSERT INTO Users (vk_id, full_name, team, mini_team) VALUES (?, ?, ?, ?)",
             (message.peer_id, message.text, state_payload.payload["team"], state_payload.payload["mini_team"]),
             commit=True)
    await bot.state_dispenser.delete(message.peer_id)
    await message.answer("Регистрация успешна!", keyboard=main_keyboard)


@bot.on.private_message()
async def greeting(message: Message):
    user = query_db("SELECT * FROM Users WHERE vk_id = ?", (message.peer_id,), one=True)
    if user:
        await message.answer("Привет! Что ты хочешь?", keyboard=main_keyboard)
    else:
        await bot.state_dispenser.set(message.peer_id, RegistrationState.WAITING_FOR_TEAM)
        await message.answer("Привет! Напиши свою команду (напр., 1)")


bot.run_forever()