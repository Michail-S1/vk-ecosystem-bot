import sqlite3
from vkbottle import BaseStateGroup, Keyboard, KeyboardButtonColor, Text
from vkbottle.bot import Bot, Message
import os
import pandas as pd
from vkbottle import DocMessagesUploader
from vkbottle.tools import DocMessagesUploader

# ТОКЕН: Не забудь вставить свой ключ из ВК
TOKEN = "token_here"
# Замени цифры на свой реальный ID ВКонтакте
ADMIN_IDS = [614064375]

bot = Bot(token=TOKEN)

# =====================================================================
# 1. СОЗДАНИЕ КЛАВИАТУР (КНОПОК)
# =====================================================================

# Главное меню
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

# Выбор типа задания
type_keyboard = (
    Keyboard(one_time=False)
    .add(Text("Индивидуальное"), color=KeyboardButtonColor.PRIMARY)
    .add(Text("Групповое"), color=KeyboardButtonColor.PRIMARY)
    .row()
    .add(Text("Назад"), color=KeyboardButtonColor.NEGATIVE)
).get_json()

# Список заданий (пока тестовый вариант)
tasks_keyboard = (
    Keyboard(one_time=False)
    .add(Text("Задание 1"), color=KeyboardButtonColor.SECONDARY)
    .add(Text("Задание 2"), color=KeyboardButtonColor.SECONDARY)
    .row()
    .add(Text("Назад"), color=KeyboardButtonColor.NEGATIVE)
).get_json()

# Кнопка назад для этапа отправки ссылки
back_only_keyboard = (
    Keyboard(one_time=False)
    .add(Text("Назад"), color=KeyboardButtonColor.NEGATIVE)
).get_json()


# =====================================================================
# 2. ОПИСАНИЕ ЭТАПОВ (СОСТОЯНИЙ)
# =====================================================================
class RegistrationState(BaseStateGroup):
    WAITING_FOR_TEAM = 0
    WAITING_FOR_MINI_TEAM = 1
    WAITING_FOR_FIO = 2


class TaskState(BaseStateGroup):
    CHOOSING_TYPE = 10  # Юзер выбирает Индивидуальное/Групповое
    CHOOSING_TASK = 11  # Юзер выбирает конкретное Задание 1 / Задание 2
    WAITING_FOR_LINK = 12  # Юзер должен прислать ссылку на проверку

class RatingState(BaseStateGroup):
    CHOOSING_TYPE = 20 # Юзер выбирает Индивидуальный или Групповой рейтинг

class AdminState(BaseStateGroup):
    WAITING_RATING_TYPE = 30
    WAITING_SCORE_TYPE = 31   # Админ выбирает, кому начисляет (индив/групп)
    WAITING_SCORE_DATA = 32   # Админ вводит саму строку с баллами
# =====================================================================
# 3. ПОДКЛЮЧЕНИЕ К БАЗЕ ДАННЫХ
# =====================================================================
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
# 4. ОБРАБОТКА КНОПКИ «НАЗАД» (УМНАЯ НАВИГАЦИЯ)
# =====================================================================
@bot.on.private_message(text="Назад")
async def go_back(message: Message):
    vk_id = message.peer_id
    state_payload = await bot.state_dispenser.get(vk_id)

    # Если никаких состояний нет, просто выкидываем в главное меню
    if not state_payload:
        await message.answer("Привет! Что ты хочешь?", keyboard=main_keyboard)
        return

    current_state = state_payload.state

    # Если назад нажали на выборе ТИПА задания -> возвращаем в Главное меню
    if current_state == TaskState.CHOOSING_TYPE:
        await bot.state_dispenser.delete(vk_id)
        await message.answer("Привет! Что ты хочешь?", keyboard=main_keyboard)

    # Если назад нажали на выборе конкретного ЗАДАНИЯ -> возвращаем к выбору ТИПА
    elif current_state == TaskState.CHOOSING_TASK:
        await bot.state_dispenser.set(vk_id, TaskState.CHOOSING_TYPE)
        await message.answer("Какой тип задания ты хочешь?", keyboard=type_keyboard)

    # Если назад нажали на этапе СДАЧИ ССЫЛКИ -> возвращаем к списку заданий
    elif current_state == TaskState.WAITING_FOR_LINK:
        old_type = state_payload.payload.get("task_type")
        await bot.state_dispenser.set(vk_id, TaskState.CHOOSING_TASK, task_type=old_type)
        await message.answer(f"Выбери {old_type} задание:", keyboard=tasks_keyboard)

    # Если назад нажали в меню Рейтинга -> возвращаем в Главное меню
    elif current_state == RatingState.CHOOSING_TYPE:
        await bot.state_dispenser.delete(vk_id)
        await message.answer("Привет! Что ты хочешь?", keyboard=main_keyboard)

    # Если назад нажали при вводе данных для баллов -> возвращаем к выбору типа начисления
    elif current_state == AdminState.WAITING_SCORE_DATA:
        await bot.state_dispenser.set(vk_id, AdminState.WAITING_SCORE_TYPE)
        await message.answer("Кому зачислить баллы?", keyboard=type_keyboard)

    # If назад нажали при выборе типа начисления -> возвращаем в меню админа
    elif current_state == AdminState.WAITING_SCORE_TYPE:
        await bot.state_dispenser.delete(vk_id)
        await message.answer("🛠 Панель Администратора", keyboard=admin_keyboard)

# =====================================================================
# 5. ЛОГИКА ВЕТКИ «ЗАДАНИЯ»
# =====================================================================

# Нажатие на главную кнопку "Задание"
@bot.on.private_message(text="Задание")
async def task_menu(message: Message):
    vk_id = message.peer_id
    await bot.state_dispenser.set(vk_id, TaskState.CHOOSING_TYPE)
    await message.answer("Какой тип задания ты хочешь?", keyboard=type_keyboard)


# Выбор "Индивидуальное" или "Групповое"
@bot.on.private_message(state=TaskState.CHOOSING_TYPE, text=["Индивидуальное", "Групповое"])
async def choose_task_type(message: Message):
    vk_id = message.peer_id
    selected_type = message.text.lower()  # Сохраняем выбор юзера

    # Переводим на шаг выбора заданий и запоминаем тип (индивид/групп)
    await bot.state_dispenser.set(vk_id, TaskState.CHOOSING_TASK, task_type=selected_type)
    await message.answer(f"Выбери {selected_type} задание:", keyboard=tasks_keyboard)


# Выбор конкретного задания (Задание 1 или Задание 2)
@bot.on.private_message(state=TaskState.CHOOSING_TASK, text=["Задание 1", "Задание 2"])
async def view_task_details(message: Message):
    vk_id = message.peer_id
    task_name = message.text

    state_payload = await bot.state_dispenser.get(vk_id)
    selected_type = state_payload.payload.get("task_type")

    # Переводим в режим ожидания ссылки
    await bot.state_dispenser.set(
        vk_id,
        TaskState.WAITING_FOR_LINK,
        task_type=selected_type,
        task_name=task_name
    )

    # Тут бот присылает условия (пока заглушка)
    await message.answer(
        f"Название: {task_name} ({selected_type})\n"
        f"Описание: Выполните условия и прикрепите ссылку в ответ на это сообщение.\n\n"
        f"Жду ссылку:",
        keyboard=back_only_keyboard
    )


# Ловим ссылку (любой текст, если мы в состоянии WAITING_FOR_LINK и это не кнопка Назад)
@bot.on.private_message(state=TaskState.WAITING_FOR_LINK)
async def receive_link(message: Message):
    vk_id = message.peer_id
    user_link = message.text

    # Проверяем, что это ссылка, а не случайный текст
    if not user_link.startswith("http"):
        await message.answer("Пожалуйста, пришлите корректную ссылку (начинающуюся с http:// или https://)")
        return

    state_payload = await bot.state_dispenser.get(vk_id)
    task_name = state_payload.payload.get("task_name")

    # ТУТ БУДЕТ ЗАПИСЬ В БАЗУ ДАННЫХ (на следующем этапе свяжем с ID заданий)

    # Успешно сохранили, сбрасываем состояние и возвращаем в главное меню
    await bot.state_dispenser.delete(vk_id)
    await message.answer(f"Ссылка на {task_name} успешно сохранена в базу данных для админа!", keyboard=main_keyboard)


# =====================================================================
# 6. КНОПКИ ЗАГЛУШКИ ДЛЯ БАЛАНСА И РЕЙТИНГА
# =====================================================================
@bot.on.private_message(text="Баланс")
async def balance_menu(message: Message):
    vk_id = message.peer_id

    # 1. Узнаем, в какой команде состоит юзер
    user = query_db("SELECT team, mini_team FROM Users WHERE vk_id = ?", (vk_id,), one=True)
    if not user:
        return
    team, mini_team = user[0], user[1]

    # 2. Достаем баллы из базы (индивидуальные и групповые)
    ind_scores = query_db("SELECT task_id, amount FROM Scores WHERE target_id = ? AND type = 'индивидуальное'",
                          (str(vk_id),))
    grp_scores = query_db("SELECT task_id, amount FROM Scores WHERE target_id = ? AND type = 'групповое'", (mini_team,))

    # 3. Формируем красивый текст ответа
    text = f"📊 Твой баланс и история начислений!\n\n"
    text += f"Команда: {team}\nМини-команда: {mini_team}\n\n"

    ind_total = 0
    if ind_scores:
        text += "👤 Индивидуальные начисления:\n"
        for task_id, amount in ind_scores:
            text += f"• Задание {task_id}: +{amount} баллов\n"
            ind_total += amount
        text += f"Итого индивидуальных: {ind_total}\n\n"

    grp_total = 0
    if grp_scores:
        text += "👥 Начисления команды:\n"
        for task_id, amount in grp_scores:
            text += f"• Задание {task_id}: +{amount} баллов\n"
            grp_total += amount
        text += f"Итого командных: {grp_total}\n\n"

    text += f"🏆 Общее количество твоих баллов: {ind_total + grp_total}"

    await message.answer(text)


# Нажатие на кнопку Рейтинг
@bot.on.private_message(text="Рейтинг")
async def rating_menu(message: Message):
    vk_id = message.peer_id
    await bot.state_dispenser.set(vk_id, RatingState.CHOOSING_TYPE)

    # Мы переиспользуем клавиатуру type_keyboard, так как там тоже кнопки "Индивидуальное" и "Групповое"
    await message.answer("Какой рейтинг ты хочешь посмотреть?", keyboard=type_keyboard)


# Вывод самого рейтинга
@bot.on.private_message(state=RatingState.CHOOSING_TYPE, text=["Индивидуальное", "Групповое"])
async def show_rating(message: Message):
    vk_id = message.peer_id
    rating_type = message.text.lower()

    if rating_type == "индивидуальное":
        # Считаем сумму баллов для каждого юзера с помощью SQL
        query = """
        SELECT target_id, SUM(amount) as total
        FROM Scores
        WHERE type = 'индивидуальное'
        GROUP BY target_id
        ORDER BY total DESC
        """
        results = query_db(query)

        text = "🏆 Индивидуальный рейтинг:\n\n"
        place = 1
        user_place = "Нет в рейтинге"
        user_score = 0

        if results:
            for row in results:
                target_id, total = row[0], row[1]
                # Выводим Топ-5, чтобы не спамить огромным сообщением
                if place <= 5:
                    text += f"{place} место: ID {target_id} — {total} баллов\n"

                # Ищем самого юзера в этом списке
                if str(vk_id) == str(target_id):
                    user_place = place
                    user_score = total
                place += 1
        else:
            text += "Рейтинг пока пуст.\n"

        text += f"\nТвое место: {user_place}\nТвои баллы: {user_score}"
        await message.answer(text, keyboard=type_keyboard)

    elif rating_type == "групповое":
        query = """
        SELECT target_id, SUM(amount) as total
        FROM Scores
        WHERE type = 'групповое'
        GROUP BY target_id
        ORDER BY total DESC
        """
        results = query_db(query)

        text = "🏆 Групповой рейтинг:\n\n"
        place = 1

        if results:
            for row in results:
                target_id, total = row[0], row[1]
                text += f"{place} место: Команда {target_id} — {total} баллов\n"
                place += 1
        else:
            text += "Рейтинг пока пуст.\n"

        await message.answer(text, keyboard=type_keyboard)


# =====================================================================
# 8. АДМИН ПАНЕЛЬ
# =====================================================================

# Вход в админку по секретной команде
# Было: @bot.on.private_message(text="/админ")
# Стало:
@bot.on.private_message(text="/админ")
async def enter_admin(message: Message):
    if message.peer_id in ADMIN_IDS:
        # Принудительно очищаем любые застрявшие состояния пользователя
        await bot.state_dispenser.delete(message.peer_id)
        await message.answer("🛠 Добро пожаловать в панель Администратора!", keyboard=admin_keyboard)
    else:
        await message.answer("У вас нет прав доступа к этой команде.")

# Выход из админки обратно к заданиям
@bot.on.private_message(text="Меню пользователя")
async def exit_admin(message: Message):
    await bot.state_dispenser.delete(message.peer_id)
    await message.answer("Возвращаюсь в режим пользователя.", keyboard=main_keyboard)


# --- ВЫГРУЗКА РЕЙТИНГА ---

@bot.on.private_message(text="Выгрузка рейтинг")
async def admin_export_rating(message: Message):
    if message.peer_id not in ADMIN_IDS: return

    await bot.state_dispenser.set(message.peer_id, AdminState.WAITING_RATING_TYPE)
    await message.answer("Какой тип рейтинга выгрузить?", keyboard=type_keyboard)  # Используем старую клаву с типами


@bot.on.private_message(state=AdminState.WAITING_RATING_TYPE, text=["Индивидуальное", "Групповое"])
async def process_rating_export(message: Message):
    if message.peer_id not in ADMIN_IDS: return

    rating_type = message.text.lower()
    await message.answer("Собираю данные, формирую Excel...")

    try:
        # Запрашиваем данные из БД (убрали одинарные кавычки в AS для стабильности SQL)
        if rating_type == "индивидуальное":
            query = """
            SELECT Users.vk_id as ID_ВК, Users.full_name as ФИО, SUM(Scores.amount) as Сумма_баллов
            FROM Users
            LEFT JOIN Scores ON Users.vk_id = Scores.target_id AND Scores.type = 'индивидуальное'
            GROUP BY Users.vk_id
            ORDER BY Сумма_баллов DESC
            """
        else:
            query = """
            SELECT Users.mini_team as Мини_команда, Users.team as Команда, SUM(Scores.amount) as Сумма_баллов
            FROM Users
            LEFT JOIN Scores ON Users.mini_team = Scores.target_id AND Scores.type = 'групповое'
            GROUP BY Users.mini_team
            ORDER BY Сумма_баллов DESC
            """

        conn = sqlite3.connect("bot_data.db")
        df = pd.read_sql_query(query, conn)
        conn.close()

        # Меняем пустоту на нули
        df['Сумма_баллов'] = df['Сумма_баллов'].fillna(0)

        # Добавляем колонку "Место"
        df.insert(0, 'Место', range(1, 1 + len(df)))

        filename = f"rating_{rating_type}.xlsx"
        df.to_excel(filename, index=False)

        # Загружаем файл в ВК
        uploader = DocMessagesUploader(bot.api)
        doc = await uploader.upload(file_source=filename, peer_id=message.peer_id, title=f"Рейтинг_{rating_type}.xlsx")

        await message.answer(f"✅ Файл выгрузки готов:", attachment=doc, keyboard=admin_keyboard)
        await bot.state_dispenser.delete(message.peer_id)
        os.remove(filename)

    except Exception as e:
        # Если произойдет сбой, бот пришлет ошибку прямо в чат!
        await message.answer(f"❌ Произошла ошибка при создании файла: {e}", keyboard=admin_keyboard)
        await bot.state_dispenser.delete(message.peer_id)
    # Запрашиваем данные из БД (соединяем таблицу пользователей и баллов)
    if rating_type == "индивидуальное":
        query = """
        SELECT Users.vk_id as 'ID ВК', Users.full_name as 'ФИО', SUM(Scores.amount) as 'Сумма баллов'
        FROM Users
        LEFT JOIN Scores ON Users.vk_id = Scores.target_id AND Scores.type = 'индивидуальное'
        GROUP BY Users.vk_id
        ORDER BY 'Сумма баллов' DESC
        """
    else:
        query = """
        SELECT Users.mini_team as 'Мини-команда', Users.team as 'Команда', SUM(Scores.amount) as 'Сумма баллов'
        FROM Users
        LEFT JOIN Scores ON Users.mini_team = Scores.target_id AND Scores.type = 'групповое'
        GROUP BY Users.mini_team
        ORDER BY 'Сумма баллов' DESC
        """

    # Подключаемся через pandas для магии с Excel
    conn = sqlite3.connect("bot_data.db")
    df = pd.read_sql_query(query, conn)
    conn.close()

    # Если баллов пока ни у кого нет, pandas вместо чисел ставит NaN (пустоту). Меняем их на нули:
    df['Сумма баллов'] = df['Сумма баллов'].fillna(0)

    # Добавляем колонку "Место в рейтинге"
    df.insert(0, 'Место', range(1, 1 + len(df)))

    # Сохраняем во временный файл
    filename = f"rating_{rating_type}.xlsx"
    df.to_excel(filename, index=False)

    # Отправляем файл в ВК
    uploader = DocMessagesUploader(bot.api)
    doc = await uploader.upload(file_source=filename, peer_id=message.peer_id, title=f"Рейтинг_{rating_type}.xlsx")

    await message.answer(f"✅ Файл выгрузки готов:", attachment=doc, keyboard=admin_keyboard)

    # Сбрасываем состояние и удаляем временный файл с компьютера
    await bot.state_dispenser.delete(message.peer_id)
    os.remove(filename)


# --- ЗАЧИСЛЕНИЕ БАЛЛОВ ---

# 1. Нажатие на кнопку "Зачислить баллы"
@bot.on.private_message(text="Зачислить баллы")
async def admin_score_menu(message: Message):
    if message.peer_id not in ADMIN_IDS: return

    await bot.state_dispenser.set(message.peer_id, AdminState.WAITING_SCORE_TYPE)
    await message.answer("Кому зачислить баллы?", keyboard=type_keyboard)


# 2. Выбор типа начисления
@bot.on.private_message(state=AdminState.WAITING_SCORE_TYPE, text=["Индивидуальное", "Групповое"])
async def admin_choose_score_type(message: Message):
    if message.peer_id not in ADMIN_IDS: return

    score_type = message.text.lower()
    await bot.state_dispenser.set(message.peer_id, AdminState.WAITING_SCORE_DATA, score_type=score_type)

    if score_type == "индивидуальное":
        primer = "12345678 | 1 | 10  (где 12345678 — ID ВК пользователя)"
    else:
        primer = "1.1 | 2 | 15  (где 1.1 — номер мини-команды)"

    await message.answer(
        f"Введите данные для начисления в формате:\n"
        f"`Цель | Номер_Задания | Баллы`\n\n"
        f"Пример: {primer}",
        keyboard=back_only_keyboard
    )


# 3. Обработка введенных данных и запись в БД
@bot.on.private_message(state=AdminState.WAITING_SCORE_DATA)
async def admin_process_scoring(message: Message):
    if message.peer_id not in ADMIN_IDS: return

    raw_data = message.text
    state_payload = await bot.state_dispenser.get(message.peer_id)
    score_type = state_payload.payload.get("score_type")

    # Проверяем формат строки (должно быть два разделителя '|')
    if "|" not in raw_data or raw_data.count("|") != 2:
        await message.answer(
            "❌ Неверный формат! Используйте черточку | как разделитель.\nПример: `ID | Задание | Баллы`")
        return

    try:
        # Разбиваем строку и убираем лишние пробелы
        parts = [p.strip() for p in raw_data.split("|")]
        target_id = parts[0]
        task_id = int(parts[1])
        amount = int(parts[2])

        # Записываем в базу данных
        query_db(
            "INSERT INTO Scores (target_id, task_id, type, amount) VALUES (?, ?, ?, ?)",
            (target_id, task_id, score_type, amount),
            commit=True
        )

        await message.answer(
            f"✅ Успешно начислено!\n"
            f"Тип: {score_type.capitalize()}\n"
            f"Кому/Куда: {target_id}\n"
            f"Задание №: {task_id}\n"
            f"Баллы: +{amount}",
            keyboard=admin_keyboard
        )
        # Сбрасываем состояние админа и возвращаем в меню управления
        await bot.state_dispenser.delete(message.peer_id)

    except ValueError:
        await message.answer("❌ Ошибка! Номер задания и баллы должны быть целыми числами.")
    except Exception as e:
        await message.answer(f"❌ Ошибка при записи в базу данных: {e}")
# =====================================================================
# 9. РЕГИСТРАЦИЯ И ПРИВЕТСТВИЕ (В САМОМ НИЗУ)
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