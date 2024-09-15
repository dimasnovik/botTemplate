import os
from datetime import datetime

import pytz
import requests
from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, FSInputFile

import config
import database
import kb
import utils
from admins import log_conversion, log_wrong_extension, admin_chat, log_merge
from database import *
from model import DocumentData, ConversionData
from pdfengine import merge_pdf

bot = Bot(token=config.BOT_TOKEN)
router = Router()


class Form(StatesGroup):
    merging = State()
    common = State()
    complaining = State()
    heif_waiting = State()


@router.message(Command("start"))
async def start_handler(message: Message, state: FSMContext):
    hour = datetime.now(pytz.timezone('Europe/Moscow')).hour
    if hour < 6:
        greeting = 'Доброй ночи!'
    elif 6 <= hour < 12:
        greeting = 'Доброе утро!'
    elif 12 <= hour <= 17:
        greeting = 'Добрый день!'
    else:
        greeting = 'Добрый вечер!'

    await message.answer(greeting + '\nЯ могу буквально что угодно превратить в <b>pdf</b>.\n'
                                    'Также я умею склеивать <b>несколько файлов</b> в один цельный <b>pdf</b>.\n'
                                    'И кстати, у моих создателей нет доступа к вашим файлам, '
                                    'а после конвертации все файлы стираются с сервера🧐\n'
                                    'Внизу есть меню для более удобной работы.\n'
                                    'Или просто отправьте мне файл!😎', parse_mode='HTML',
                         reply_markup=kb.main_kb(message.from_user.id))
    await state.set_state(Form.common)


@router.message(F.text == "📜 Главное меню", Form.complaining)
async def main_menu_after_complain(msg: Message, state: FSMContext):
    await msg.answer("Спасибо за обратную связь, обращение принято!\n"
                     "🫡 Я готов работать дальше!",
                     reply_markup=kb.main_kb(msg.from_user.id))
    await state.set_state(Form.common)


@router.message(F.text == "📜 Главное меню")
async def main_menu_handler(msg: Message, state: FSMContext):
    await msg.answer("🫡 Я готов работать дальше!",
                     reply_markup=kb.main_kb(msg.from_user.id))
    await state.set_state(Form.common)


@router.message(F.text == "О нас")
async def about_handler(msg: Message):
    await msg.answer(
        "Бот трепетно разработан в <b>1113tech</b>.\n Если вы уже задумывались о Боте или автоматизации"
        " для себя или для своего бизнеса, напишите нам @ttoomm\n"
        "Сделаем все красиво 🥦", parse_mode='HTML', reply_markup=kb.main_menu_button(msg.from_user.id))


@router.message(F.text == "Конвертировать файл")
async def convert_button_handler(msg: Message, state: FSMContext):
    await msg.answer("Просто пошлите мне файл, который нужно сконвертировать!",
                     reply_markup=kb.choose_mode(msg.from_user.id))
    await state.set_state(Form.common)


@router.message(F.text == "🍏 .HEIC ➡️.JPEG")
async def convert_heif_handler(msg: Message, state: FSMContext):
    await msg.answer("Просто пошлите мне файл с расширением .HEIC/.HEIF",
                     reply_markup=kb.choose_mode(msg.from_user.id))
    await state.set_state(Form.heif_waiting)


@router.message(F.document, Form.heif_waiting)
async def heif_converter(msg: Message, state: FSMContext):
    user_id = msg.from_user.id
    document = DocumentData()
    await document.from_message(msg)
    file_name = document.get_full_name()
    extension = document.extension
    if extension in ('.HEIC', '.heic', '.HEIF', '.heif'):
        await msg.answer(f"Скачиваю ваш {extension} файл...")
        os.makedirs(f'upload{user_id}', exist_ok=True)
        os.makedirs(f'converted{user_id}', exist_ok=True)
        await bot.download(document.file_id, f'upload{user_id}/{file_name}')

        await msg.answer("Конвертирую в .JPEG...")
        conversion = utils.heic2jpg(document, user_id)

        await send_document(msg, conversion)

        utils.remove_files(f'upload{user_id}/')
        utils.remove_files(f'converted{user_id}/')
        os.removedirs(f'upload{user_id}')
        os.removedirs(f'converted{user_id}')
        await log_conversion(msg, conversion)

    else:
        await msg.answer(f"Отправьте .HEIC/.HEIF, вы отправили {document.extension}\n"
                         f"Или вернитесь в главное меню")
        await log_wrong_extension(msg, document.extension)


@router.message(F.text == "Сообщить об ошибке")
async def complain_handler(msg: Message, state: FSMContext):
    await state.set_state(Form.complaining)
    await msg.answer("Подробно опишите проблему, при необходимости прикрепите файлы/скрины ✍🏼\n"
                     "Чтобы закончить  - просто вернитесь в главное меню",
                     reply_markup=kb.main_menu_button(msg.from_user.id))


@router.message(Form.complaining)
async def complain_message_handler(msg: Message):
    await bot.forward_message(admin_chat, msg.from_user.id, msg.message_id)


@router.message(F.text == "Статистика" or F.text == "stats")
async def stats_handler(msg: Message, state: FSMContext):
    db = Session()
    total_c = db.query(ConversionRecord).count()
    successful_c = db.query(ConversionRecord).filter(ConversionRecord.is_successful).count()
    failed_c = total_c - successful_c

    total_m = db.query(MergeRecord).count()
    successful_m = db.query(MergeRecord).filter(MergeRecord.is_successful).count()
    failed_m = total_m - successful_m

    users_res_c = '\n<b>Стастистика конверсий по пользователям:</b>\n'
    for res in database.get_users_conversions(db):
        user = await bot.get_chat(res[0])
        users_res_c += f'@{user.username} сделал {res[1]} конверсий\n'

    users_res_m = '\n<b>Стастистика объединений по пользователям:</b>\n'
    for res in database.get_users_merges(db):
        user = await bot.get_chat(res[0])
        users_res_m += f'@{user.username} сделал {res[1]} объединений\n'

    await msg.answer(f"<b>Всего конверсий: {total_c}</b>\n"
                     f"Успешных: {successful_c}\n"
                     f"Неуспешных: {failed_c}\n"
                     f"{users_res_c}"
                     f"\n<b>Всего объединений: {total_m}</b>\n"
                     f"Успешных: {successful_m}\n"
                     f"Неуспешных: {failed_m}\n"
                     f"{users_res_m}", parse_mode='HTML',
                     reply_markup=kb.main_menu_button(msg.from_user.id))


@router.message(F.document | F.photo, Form.common)
async def document_converter(msg: Message, state: FSMContext):
    user_id = msg.from_user.id
    document = DocumentData()
    await document.from_message(msg)
    file_name = document.get_full_name()
    if utils.is_valid_extension(document.extension):
        await msg.answer("Скачиваю файл...")
        os.makedirs(f'upload{user_id}', exist_ok=True)
        os.makedirs(f'converted{user_id}', exist_ok=True)
        await bot.download(document.file_id, f'upload{user_id}/{file_name}')

        await msg.answer("Конвертирую...")
        conversion = utils.convert_document(document, user_id)

        await send_document(msg, conversion)

        utils.remove_file(f'upload{user_id}/{file_name}')
        utils.remove_file(f'converted{user_id}/{document.raw_name + ".pdf"}')
        os.removedirs(f'upload{user_id}')
        os.removedirs(f'converted{user_id}')

        await log_conversion(msg, conversion)

    else:
        await msg.answer(f"Расширение '{document.extension}' пока не поддерживается!")
        await log_wrong_extension(msg, document.extension)


async def send_document(msg: Message, conversion: ConversionData):
    code = conversion.code
    path = conversion.doc.path
    user_id = msg.from_user.id
    if code == 200:
        file = FSInputFile(path)
        file.filename = conversion.doc.get_full_name()
        await msg.answer_document(file, caption="Ваш файл в PDF",
                                  reply_markup=kb.main_menu_button(user_id))
    else:
        await error_handler(msg, code)


@router.message(F.text == 'Объединить несколько файлов в один pdf')
async def merge_button_handler(msg: Message, state: FSMContext):
    await state.set_state(Form.merging)
    await msg.answer("Посылайте файлы, которые нужно объединить в PDF-документ\n"
                     "Когда закончите, нажмите кнопку ниже или напишите <b>'Объединить файлы!'</b>",
                     parse_mode='HTML',
                     reply_markup=kb.main_menu_button(msg.from_user.id))


@router.message(F.document | F.photo, Form.merging)
async def merging_docs_handler(msg: Message, state: FSMContext):
    user_id = msg.from_user.id
    document = DocumentData()
    await document.from_message(msg)
    file_name = document.get_full_name()
    extension = document.extension
    if utils.is_valid_extension(extension):
        db = Session()
        create_document(db, msg.document.file_id, extension, user_id, False)
    else:
        await msg.answer(f"Расширение '{extension}' пока не поддерживается!\n"
                         f"Файл '{file_name}' не будет включен в объединение..")
        await log_wrong_extension(msg, extension)
    await msg.answer("Жду следующий файл для объединения\n"
                     "Чтобы объединить отправленные файлы,"
                     " нажмите кнопку ниже или напечатайте <b>'Объединить файлы!'</b>",
                     parse_mode='HTML', reply_markup=kb.convert_all_button(user_id))


@router.message(F.text == "Объединить файлы!")
async def merge(msg):
    await msg.answer("Идет скачивание файлов...")
    user_id = msg.from_user.id
    i = 0
    files = []
    document_data = []
    directory = f"upload{user_id}"
    os.makedirs(directory, exist_ok=True)
    db = Session()
    documents = get_files_of_user(db, user_id)
    for file in documents:
        await bot.download(file.file_id, f"{directory}/file{str(i)}{file.extension}")
        await msg.answer(f"{i + 1}/{len(documents)} файл загружен ✅ ")
        files.append(('files', open(f'{directory}/file{str(i)}{file.extension}', 'rb')))
        doc = DocumentData(f'file{str(i)}', file.file_id, file.extension, file.extension)
        document_data.append(doc)
        i += 1
    if files:
        if all(ext == '.pdf' or ext == '.PDF' for ext in map(lambda document: document.extension, documents)):
            await msg.answer("Все ваши файлы формата PDF! Процесс объединения пойдет быстрее! ⚡️⚡️⚡️")
            merge_result = merge_pdf(files, msg)
            code = merge_result.code
            conversion = ConversionData(code, merge_result.doc)
            await send_document(msg, conversion)
            log_merge(msg, conversion)
        else:
            try:
                await msg.answer("Файлы скачаны ✅ . Идет объединение файлов. Процесс может занять некоторое время...")
                os.makedirs(f'converted{user_id}', exist_ok=True)
                paths = []
                for doc in document_data:
                    utils.convert_document(doc, f'{user_id}')
                    paths.append(('files', open(f'converted{user_id}/{doc.get_full_name()}', 'rb')))
                merge_result = merge_pdf(paths, msg)
                code = merge_result.code
                conversion = ConversionData(code, merge_result.doc)
                await send_document(msg, conversion)
                log_merge(msg, conversion)
            except requests.exceptions.ConnectionError:
                await msg.answer("Сервис конвертации временно недоступен", reply_markup=kb.main_menu_button(user_id))
                db = Session()
                create_merge_record(db, user_id, False, False)

        utils.remove_files(f'upload{user_id}')
        utils.remove_files(f'converted{user_id}')
        utils.remove_file(f'converted/file{user_id}.pdf')
        delete_files_of_user(db, user_id)
    else:
        await msg.answer("Вы пока не добавили ни одного файла для объединения",
                         reply_markup=kb.main_menu_button(user_id))


async def error_handler(msg: Message, code: int):
    user_id = msg.from_user.id
    if code == 400:
        await msg.answer("Что-то не так с исходным файлом", reply_markup=kb.main_menu_button(user_id))

    elif code == 503:
        await msg.answer("Сервис конвертации временно недоступен",
                         reply_markup=kb.main_menu_button(user_id))
    else:
        await msg.answer("Что-то пошло не так, обратитесь к разработчику \n @dvnovik",
                         reply_markup=kb.main_menu_button(user_id))
