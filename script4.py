import shutil

from pyrogram import Client, filters
from pyrogram.types import InputMediaDocument
from decouple import config
import asyncio
import os
import re
from io import BytesIO
import glob
from pathlib import Path
from collections import defaultdict
import time
from colorama import Fore, Style
import platform
from datetime import datetime
from selenium import webdriver
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.chrome.options import Options
import sqlite3

stop_event = asyncio.Event()
bot_name = "Antiplagiat_Check_AI_bot"


class FileSender:
    """Класс для безопасной отправки файлов с обработкой ошибок"""
    
    @staticmethod
    async def send_file_with_retry(client, chat_id, file_path, max_retries=5, initial_delay=5):
        """
        Отправка файла с повторными попытками при ошибках таймаута
        """
        delay = initial_delay
        
        for attempt in range(max_retries):
            try:
                # Проверяем размер файла перед отправкой
                file_size = os.path.getsize(file_path)
                if file_size == 0:
                    print(f"Ошибка: Файл {file_path} имеет нулевой размер")
                    return False
                    
                print(f"Попытка {attempt + 1} отправки файла: {file_path}")
                
                # Отправка файла с увеличенным таймаутом
                await client.send_document(
                    chat_id=chat_id,
                    document=file_path,
                    timeout=300  # Увеличенный таймаут 5 минут
                )
                
                print(f"Файл успешно отправлен: {file_path}")
                return True
                
            except TimeoutError as e:
                print(f"Таймаут при отправке файла (попытка {attempt + 1}): {e}")
                
                if attempt < max_retries - 1:
                    print(f"Повторная попытка через {delay} секунд...")
                    await asyncio.sleep(delay)
                    delay *= 2  # Экспоненциальная задержка
                else:
                    print(f"Превышено максимальное количество попыток для файла: {file_path}")
                    return False
                    
            except FloodWait as e:
                wait_time = e.value
                print(f"FloodWait: необходимо подождать {wait_time} секунд")
                await asyncio.sleep(wait_time)
                continue
                
            except Exception as e:
                print(f"Неожиданная ошибка при отправке файла {file_path}: {e}")
                return False
        
        return False

    @staticmethod
    async def send_files_safely(client, chat_id, file_paths, max_concurrent=2):
        """
        Безопасная отправка нескольких файлов с ограничением одновременных запросов
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def send_with_semaphore(file_path):
            async with semaphore:
                return await FileSender.send_file_with_retry(client, chat_id, file_path)
        
        # Создаем задачи для отправки файлов
        tasks = [send_with_semaphore(file_path) for file_path in file_paths]
        
        # Выполняем с ограничением одновременных запросов
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Анализируем результаты
        successful = 0
        for file_path, result in zip(file_paths, results):
            if result is True:
                successful += 1
            else:
                print(f"Не удалось отправить файл: {file_path}")
        
        print(f"Успешно отправлено: {successful}/{len(file_paths)} файлов")
        return successful

    @staticmethod
    def validate_file(file_path):
        """
        Проверяет файл перед отправкой
        """
        if not os.path.exists(file_path):
            print(f"Файл не существует: {file_path}")
            return False
        
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            print(f"Файл имеет нулевой размер: {file_path}")
            return False
        
        if file_size > 2000 * 1024 * 1024:  # 2GB - лимит Telegram
            print(f"Файл слишком большой: {file_path} ({file_size} bytes)")
            return False
        
        return True

    @staticmethod
    async def send_single_file_safely(client, chat_id, file_path):
        """
        Безопасная отправка одного файла
        """
        if not FileSender.validate_file(file_path):
            return False
        
        return await FileSender.send_file_with_retry(client, chat_id, file_path)

class App:
    def __init__(self):
        self.clients = {}  # Будем хранить клиентов здесь
        self.clear_console()

    async def initialize(self):
        """Инициализация всех клиентов один раз при старте"""
        if not os.path.exists('.env'):
            self.check_env_file()
            return

        for i in range(2):
            client_name = f"client{i + 1}"
            try:
                print(Fore.YELLOW + f"Инициализация {client_name}..." + Style.RESET_ALL)

                self.clients[client_name] = Client(
                    name=config(f'LOGIN{i + 1}'),
                    api_id=config(f'API_ID{i + 1}'),
                    api_hash=config(f'API_HASH{i + 1}'),
                    phone_number=config(f'PHONE{i + 1}'))

                await self.clients[client_name].start()
                print(Fore.GREEN + f"{client_name} успешно инициализирован!" + Style.RESET_ALL)

            except Exception as e:
                print(Fore.RED + f"Ошибка инициализации {client_name}:" + Style.RESET_ALL)
                print(e)
                await self.shutdown()
                return False

        return True

    async def shutdown(self):
        """Корректное завершение работы всех клиентов"""
        for name, client in self.clients.items():
            try:
                if isinstance(client, Client) and client.is_initialized:
                    await client.stop()
                    print(f"Клиент {name} отключен")
                else:
                    print(f"Клиент {name} не был инициализирован")
            except Exception as e:
                print(f"Ошибка при отключении клиента {name}: {e}")

    def clear_console(self):
        """Очистка консоли"""
        os.system('cls' if platform.system() == 'Windows' else 'clear')

    def check_env_file(self):
        """Создание .env файла"""
        print(Fore.RED + "Не внесены данные об аккаунтах Telegram")
        env_text = ""
        for i in range(2):
            print(Style.RESET_ALL + "---------------------------------")
            env_text += f"API_ID{i + 1}=" + input(f"ID {i + 1} аккаунта: ") + "\n"
            env_text += f"API_HASH{i + 1}=" + input(f"HASH {i + 1} аккаунта: ") + "\n"
            env_text += f"LOGIN{i + 1}=" + input(f"username {i + 1} аккаунта без '@': ") + "\n"
            env_text += f"PHONE{i + 1}=" + input(f"номер телефона {i + 1} аккаунта: ") + "\n"

        with open(".env", "w") as f:
            f.write(env_text)

        print(Fore.GREEN + "Данные успешно добавлены!" + Style.RESET_ALL)

    async def main_menu(self):
        """Главное меню"""
        while True:
            print("\nВыберите задачу:")
            print("1. Отправка файлов и боту и редактору (не работает)")
            print("2. Отправка файлов только боту (не работает)")
            print("3. Отправка файлов только редактору от разных пользователей")
            print("4. Выйти")

            choice = input("Ваш выбор: ")
            self.clear_console()

            if choice == "1":
                #await self.mode_1()
                self.clear_console()
                print(Fore.YELLOW + "К сожалению, этот режим в данный момент не работает" + Style.RESET_ALL)
            elif choice == "2":
                #await self.mode_2()
                self.clear_console()
                print(Fore.YELLOW + "К сожалению, этот режим в данный момент не работает" + Style.RESET_ALL)
            elif choice == "3":
                await self.mode_3()
            elif choice == "4":
                print("Завершение работы...")
                await self.shutdown()
                await asyncio.sleep(1)
                # Получаем текущий event loop и останавливаем его
                loop = asyncio.get_running_loop()
                loop.stop()
                break
            else:
                print(Fore.RED + "Некорректный выбор!" + Style.RESET_ALL)

    async def mode_1(self):
        """Режим 1 - мониторинг сообщений"""
        self.editor = input("Введите username редактора без '@': ")
        self.author = input("Введите username автора без '@': ")
        self.clear_console()

        print(f"\n{Fore.CYAN}=== Начинаем мониторинг ===")
        print(f"Отправитель: @{self.author}")
        print(f"Редактор: @{self.editor}{Style.RESET_ALL}")
        print(f"Для остановки введите 'stop'{Style.RESET_ALL}")

        client = self.clients['client1']

        @client.on_message(filters.document & filters.private)
        async def handle_document(client, message):
            if message.text and message.text.lower() == 'stop':
                stop_event.set()
                return

            if message.from_user.username != self.author:
                return

            check_words = ['.pdf', '.rtf', '.doc', '.docx']
            documents = []

            # Обработка одного файла
            if hasattr(message, 'document'):
                if any(word in message.document.file_name.lower() for word in check_words):
                    documents.append(message.document)

            # Обработка нескольких файлов (если сообщение содержит media_group)
            if hasattr(message, 'media_group_id'):
                try:
                    # Получаем всю группу медиа
                    media_group = await client.get_media_group(message.chat.id, message.id)
                    for msg in media_group:
                        if hasattr(msg, 'document') and any(
                                word in msg.document.file_name.lower() for word in check_words):
                            documents.append(msg.document)
                except Exception as e:
                    print(Fore.RED + f"Ошибка получения media group: {e}" + Style.RESET_ALL)

            if not documents:
                return

            print(Fore.GREEN + f"Получено {len(documents)} файлов" + Style.RESET_ALL)

            # Разбиваем файлы на группы по 5 штук
            for i in range(0, len(documents), 5):
                batch = documents[i:i + 5]
                await self.process_batch(batch, message)

                # Задержка между партиями
                if i + 5 < len(documents):
                    await asyncio.sleep(2)

        print(Fore.GREEN + f"Бот запущен как @{(await client.get_me()).username}")
        print(Fore.CYAN + "Ожидаю новые файлы от клиента..." + Style.RESET_ALL)

        async def console_input():
            while True:
                cmd = await asyncio.get_event_loop().run_in_executor(None, input)
                if cmd.lower() == 'stop':
                    stop_event.set()
                    break

        console_task = asyncio.create_task(console_input())

        while not stop_event.is_set():
            await asyncio.sleep(1)

        console_task.cancel()
        stop_event.clear()
        self.clear_console()
        print(Fore.YELLOW + "Мониторинг остановлен, возвращаемся в меню" + Style.RESET_ALL)

    async def process_batch(self, batch, original_message):
        """Обработка партии файлов с защитой от блокировки"""
        client = self.clients['client1']

        try:
            # Создаем уникальную папку для этой партии
            batch_dir = os.path.join("downloads", f"batch_{int(time.time())}")
            os.makedirs(batch_dir, exist_ok=True)

            # Обрабатываем файлы последовательно с задержками
            for i, doc in enumerate(batch):
                try:
                    filename = f"doc_{i}_{doc.file_name}"
                    file_path = os.path.join(batch_dir, filename)

                    # Шаг 1: Скачивание с уникальным временным именем
                    temp_path = file_path + ".temp"
                    print(Fore.YELLOW + f"Скачивание {filename}..." + Style.RESET_ALL)

                    await client.download_media(
                        doc,
                        file_name=temp_path,
                        progress=self.download_progress,
                        progress_args=(filename,)
                    )

                    # Шаг 2: Переименование после завершения скачивания
                    await asyncio.sleep(0.5)  # Задержка для гарантии завершения
                    os.rename(temp_path, file_path)

                    # Шаг 3: Обработка файла
                    print(Fore.CYAN + f"Обработка {filename}..." + Style.RESET_ALL)
                    await self.process_and_send_file(client, file_path, filename, original_message.caption)

                    # Шаг 4: Очистка
                    await asyncio.sleep(0.5)
                    self.safe_remove(file_path)

                except Exception as e:
                    print(Fore.RED + f"Ошибка обработки файла {filename}: {e}" + Style.RESET_ALL)
                    continue

        except Exception as e:
            print(Fore.RED + f"Критическая ошибка партии: {e}" + Style.RESET_ALL)
        finally:
            # Попытка очистки папки через 5 секунд
            asyncio.create_task(self.delayed_cleanup(batch_dir, delay=5))

    async def process_and_send_file(self, client, file_path, filename, caption):
        """Безопасная обработка и отправка файла"""
        try:
            # Создаем копию для отправки
            send_path = file_path + ".send"
            shutil.copyfile(file_path, send_path)

            # Отправляем файл
            await client.send_document(bot_name, send_path)
            await self.process_single_file(send_path, filename, caption)

        finally:
            self.safe_remove(send_path)

    def safe_remove(self, path):
        """Безопасное удаление файла с несколькими попытками"""
        for _ in range(3):
            try:
                if os.path.exists(path):
                    os.remove(path)
                    break
            except:
                time.sleep(0.5)

    async def delayed_cleanup(self, dir_path, delay):
        """Отложенная очистка папки"""
        await asyncio.sleep(delay)
        try:
            shutil.rmtree(dir_path, ignore_errors=True)
        except:
            pass

    async def process_single_file(self, file_path, filename, caption):
        """Обработка одного файла"""
        words_for_bot = ["АД", "ад", "а.д.", "АНТИ", "анти", "рерайт"]

        try:
            if any(word in filename for word in words_for_bot) and "payment" not in filename:
                print(Fore.CYAN + "Файл для обработки ботом" + Style.RESET_ALL)
                await self.work_with_bot(file_path, filename, self.author, caption)
            else:
                print(Fore.CYAN + "Файл для обработки редактором" + Style.RESET_ALL)
                await self.send_to_editor(file_path, self.editor)

        except Exception as e:
            print(Fore.RED + f"Ошибка обработки файла: {e}" + Style.RESET_ALL)
            await self.notify_error(self.author, filename)

    async def mode_2(self):
        self.editor = input("Введите username редактора без '@': ")
        self.author = input("Введите username автора без '@': ")
        self.clear_console()

        print(f"\n{Fore.CYAN}=== Начинаем мониторинг ===")
        print(f"Отправитель: @{self.author}")
        print(f"Редактор: @{self.editor}{Style.RESET_ALL}")
        print(f"Для остановки введите 'stop'{Style.RESET_ALL}")

        # Получаем клиента для мониторинга
        client = self.clients['client1']

        @client.on_message(filters.document & filters.private)
        async def handle_document(client, message):
            # Проверяем команду stop
            if message.text and message.text.lower() == 'stop':
                stop_event.set()
                return

            check_words = ['.pdf', '.rtf', '.doc', '.docx']
            if message.from_user.username != self.author:
                return
            flag = False
            if any(word in message.document.file_name for word in check_words):
                flag = True
            if flag == False:
                return

            print(Fore.GREEN + f"Получен файл: {message.document.file_name}" + Style.RESET_ALL)

            # Скачивание файла
            os.makedirs("downloads", exist_ok=True)
            path = await message.download(f"downloads/{message.document.file_name}")
            print(Fore.BLUE + f"Файл сохранен: {path}" + Style.RESET_ALL)

            await self.work_with_bot(path, message.document.file_name, self.author, message.caption)

        print(Fore.GREEN + f"Бот запущен как @{(await client.get_me()).username}")
        print(Fore.CYAN + "Ожидаю новых файлов от клиента..." + Style.RESET_ALL)

        # Добавляем обработку команды stop из консоли
        async def console_input():
            while True:
                cmd = await asyncio.get_event_loop().run_in_executor(None, input)
                if cmd.lower() == 'stop':
                    stop_event.set()
                    break

        console_task = asyncio.create_task(console_input())

        # Ожидаем команды остановки
        while not stop_event.is_set():
            await asyncio.sleep(1)

        console_task.cancel()
        stop_event.clear()
        self.clear_console()
        print(Fore.YELLOW + "Мониторинг остановлен, возвращаемся в меню" + Style.RESET_ALL)

    async def process_file(self, file_path, filename, caption, editor, author):
        """Обработка полученного файла"""
        words_for_bot = ["АД", "ад", "а.д.", "АНТИ", "анти", "рерайт"]
        check_words = ['.pdf','.rtf','.doc','.docx']

        try:
            if any(word in filename for word in words_for_bot) and "payment" not in filename:
                print(Fore.CYAN + "Файл для обработки ботом" + Style.RESET_ALL)

                await self.work_with_bot(file_path, filename, author, caption)
            else:
                print(Fore.CYAN + "Файл для обработки редактором" + Style.RESET_ALL)
                await self.send_to_editor(file_path, editor)

        except Exception as e:
            print(Fore.RED + f"Ошибка обработки файла: {e}" + Style.RESET_ALL)
            await self.notify_error(author, filename)

    async def work_with_bot(self, file_path, filename, recipient, link_status):
        """Работа с ботом антиплагиата"""
        try:
            print(link_status)
        except:
            pass
        client = self.clients['client1']

        try:
            print(Fore.MAGENTA + f"Отправка файла {filename} боту @{bot_name}..." + Style.RESET_ALL)
            await client.send_document(bot_name, file_path)

            # Ожидание ответа от бота с обработкой кнопки
            response = await self.wait_for_bot_response()
            if not response:
                raise Exception("Бот не ответил")

            print(Fore.GREEN + "Получен ответ от бота!" + Style.RESET_ALL)

            # Если есть кнопка "Посмотреть отчет" - нажимаем ее
            if response.reply_markup:
                for row in response.reply_markup.inline_keyboard:
                    for button in row:
                        if "посмотреть отчет" in button.text.lower():
                            print(Fore.YELLOW + "Нажимаем кнопку 'Посмотреть отчет'..." + Style.RESET_ALL)

                            print(Fore.YELLOW + f"Cсылка получена успешно: {button.url}" + Style.RESET_ALL)
                            if link_status is not None and "ссылкой" in link_status:
                                client = self.clients['client1']
                                await client.send_message(recipient, button.url)
                            else:
                                webs = web()
                                if link_status is not None and "рерайт" in filename:
                                    await webs.download_raport(button.url, filename, button.url, self.clients['client1'])
                                else:
                                    await webs.download_raport(button.url, filename, None, self.clients['client1'])

                            # Даем время на обработку
                            await asyncio.sleep(3)
                            break
            else:
                await self.notify_error(recipient, filename)

        except Exception as e:
            print(Fore.RED + f"Ошибка работы с ботом: {e}" + Style.RESET_ALL)
            await self.notify_error(recipient, filename)

    async def send_to_editor(self, file_path, editor):
        author = self.author
        client_editor = self.clients['client2']
        client_author = self.clients['client1']

        try:
            # 1. Отправляем файл редактору и запоминаем время отправки
            sent_message = await client_editor.send_document(
                editor,
                file_path,
                caption="📎 Файл для проверки"
            )
            request_time = sent_message.date  # Запоминаем время отправки
            print(Fore.GREEN + f"Файл отправлен редактору @{editor} в {request_time}" + Style.RESET_ALL)

            # 2. Ожидаем новый файл от редактора (только те, что пришли ПОСЛЕ request_time)
            edited_file_path = await self.wait_for_editor_response(
                client_editor,
                editor,
                min_date=request_time
            )
            if not edited_file_path:
                raise Exception("Редактор не отправил исправленный файл")

            # 3. Пересылаем файл автору
            await client_author.send_document(author, edited_file_path)
            print(Fore.GREEN + f"Файл переслан автору @{author}" + Style.RESET_ALL)

        except Exception as e:
            print(Fore.RED + f"Ошибка: {e}" + Style.RESET_ALL)

    async def mode_3(self):
        editor = input("Введите username редактора: ").replace("@", "")
        authors = input("Введите username автора (-ов) через запятую: ").replace("@", "").split(",")

        print(f"\n{Fore.CYAN}=== Начинаем мониторинг ===")
        print(f"Отправитель (-и): @{authors}")
        print(f"Редактор: @{editor}{Style.RESET_ALL}")
        print(f"Для остановки введите 'stop'{Style.RESET_ALL}")

        client = self.clients['client1']
        client2 = self.clients['client2']
        processed_media_groups = defaultdict(bool)


        @client.on_message(filters.media_group | filters.document)
        async def handle_document(client, message):
            filenames = []
            if message.text and message.text.lower() == 'stop':
                processed_media_groups.clear()
                stop_event.set()
                return

            if message.from_user.username not in authors:
                return


            else:
                check_words = ['.pdf', '.rtf', '.doc', '.docx']

                # Обработка медиагруппы
                if message.media_group_id:
                    if processed_media_groups[message.media_group_id]:
                        return
                    processed_media_groups[message.media_group_id] = True

                    print(Fore.CYAN + f"Начата обработка авторской медиагруппы {message.media_group_id}" + Style.RESET_ALL)

                    try:
                        album = await client.get_media_group(message.chat.id, message.id)
                        media_group = []

                        for msg in album:
                            if msg.document and any(ext in msg.document.file_name.lower() for ext in check_words):
                                if "payment" in msg.document.file_name.lower() or "receipt" in msg.document.file_name.lower() or "document" in msg.document.file_name.lower() and "выполнен" not in msg.document.file_name.lower() or "документ" in msg.document.file_name.lower() or "пэймент" in msg.document.file_name.lower():
                                    pass
                                else:
                                    # Скачиваем файл в оперативную память
                                    file_data = await msg.download(in_memory=True)
                                    a = msg.document.file_name.rsplit(".", 1)
                                    filenames.append(a[0])

                                    # Создаем BytesIO объект из скачанных данных
                                    file_buffer = BytesIO(
                                        file_data.getvalue() if hasattr(file_data, 'getvalue') else file_data)
                                    file_buffer.name = msg.document.file_name

                                    media = InputMediaDocument(
                                        media=file_buffer
                                    )
                                    media_group.append(media)

                        if media_group:
                            await self.clients['client2'].send_media_group(
                                chat_id=editor,
                                media=media_group
                            )
                            print(Fore.GREEN + f"Успешно отправлено {len(media_group)} файлов" + Style.RESET_ALL)
                            dbn = "files.db"
                            conn = sqlite3.connect(dbn)
                            cursor = conn.cursor()
                            for filename in filenames:
                                cleared = re.sub(r'[^a-zA-Zа-яА-ЯёЁ0-9]', '', filename, flags=re.IGNORECASE)
                                cursor.execute("""INSERT INTO files (username, filename) 
                                                                          VALUES (?, ?)""",
                                               (message.from_user.username, cleared.lower()))

                            conn.commit()
                            conn.close()

                    except Exception as e:
                        print(Fore.RED + f"Ошибка обработки медиагруппы: {e}" + Style.RESET_ALL)
                    finally:
                        # Закрываем все буферы
                        for media in media_group:
                            if hasattr(media.media, 'close'):
                                media.media.close()

                # Обработка одиночного документа
                elif message.document and any(ext in message.document.file_name.lower() for ext in check_words):
                    try:
                        if "payment" in message.document.file_name.lower() or "receipt" in message.document.file_name.lower() or "document" in message.document.file_name.lower() and "выполнен" not in message.document.file_name.lower() or "документ" in message.document.file_name.lower() or "пэймент" in message.document.file_name.lower():
                            return
                        print(Fore.GREEN + f"Начата обработка авторского файла: {message.document.file_name}" + Style.RESET_ALL)

                        # Скачиваем файл в оперативную память

                        file_data = await message.download(in_memory=True)

                        # Создаем BytesIO объект
                        file_buffer = BytesIO(file_data.getvalue() if hasattr(file_data, 'getvalue') else file_data)
                        file_buffer.name = message.document.file_name

                        # Отправляем файл редактору
                        await self.clients['client2'].send_document(
                            chat_id=editor,
                            document=file_buffer
                        )
                        print(Fore.GREEN + "Файл успешно отправлен редактору" + Style.RESET_ALL)
                        dbn = "files.db"
                        conn = sqlite3.connect(dbn)
                        cursor = conn.cursor()
                        cleared = re.sub(r'[^a-zA-Zа-яА-ЯёЁ0-9]', '', message.document.file_name.rsplit(".", 1)[0], flags=re.IGNORECASE)
                        cursor.execute("""INSERT INTO files (username, filename) 
                                                                    VALUES (?, ?)""",
                                       (message.from_user.username, cleared.lower()))

                        conn.commit()
                        conn.close()

                    except Exception as e:
                        print(Fore.RED + f"Ошибка обработки файла: {e}" + Style.RESET_ALL)
                    finally:
                        if 'file_buffer' in locals():
                            file_buffer.close()

        @client2.on_message(filters.media_group | filters.document)
        async def handle_editor(client2, message):
            filenames = []
            if message.from_user.username != editor:
                return
            if "payment" in message.document.file_name.lower() or "receipt" in message.document.file_name.lower() or "document" in message.document.file_name.lower() and "выполнен" not in message.document.file_name.lower() or "документ" in message.document.file_name.lower() or "пэймент" in message.document.file_name.lower():
                return

            check_words = ['.pdf', '.rtf', '.doc', '.docx', '.txt']

            # Обработка медиагруппы от редактора
            if message.media_group_id:
                if processed_media_groups.get(message.media_group_id):
                    return

                processed_media_groups[message.media_group_id] = True
                print(Fore.CYAN + f"Обработка ответа от редактора {message.media_group_id}" + Style.RESET_ALL)

                try:
                    await asyncio.sleep(1)  # Даем время на сборку группы
                    album = await client2.get_media_group(message.chat.id, message.id)

                    # Группируем файлы по авторам
                    author_files = defaultdict(list)

                    with sqlite3.connect("files.db") as conn:
                        cursor = conn.cursor()

                        for msg in album:
                            if msg.document and any(ext in msg.document.file_name.lower() for ext in check_words):
                                base_name = os.path.splitext(msg.document.file_name)[0]
                                cleared = re.sub(r'[^a-zA-Zа-яА-ЯёЁ0-9]', '', base_name,
                                                 flags=re.IGNORECASE)

                                # Получаем автора файла из БД
                                cursor.execute("SELECT username FROM files WHERE filename = ?", (cleared.lower(),))
                                result = cursor.fetchone()

                                if result:
                                    author = result[0]
                                    file_data = await msg.download(in_memory=True)
                                    file_buffer = BytesIO(file_data.getvalue())
                                    file_buffer.name = msg.document.file_name

                                    author_files[author].append((file_buffer, base_name))

                    # Отправляем файлы каждому автору
                    for author, files in author_files.items():
                        media_group = [InputMediaDocument(media=fb) for fb, _ in files]

                        try:
                            await client.send_media_group(
                                chat_id=author,
                                media=media_group
                            )
                            print(
                                Fore.GREEN + f"Отправлено {len(media_group)} файлов автору {author}" + Style.RESET_ALL)

                            # Удаляем отправленные файлы из БД
                            with sqlite3.connect("files.db") as conn:
                                cursor = conn.cursor()
                                for _, base_name in files:
                                    cursor.execute("DELETE FROM files WHERE username = ? AND filename = ?",
                                                   (author, cleared.lower()))
                                conn.commit()
                                cursor.execute("""SELECT COUNT(*) FROM files""")
                                if cursor.fetchone()[0] == 0:
                                    print(Fore.CYAN + "Ожидаю новых файлов от клиента..." + Style.RESET_ALL)

                        except Exception as e:
                            print(Fore.RED + f"Ошибка отправки автору {author}: {e}" + Style.RESET_ALL)
                        finally:
                            for fb, _ in files:
                                fb.close()

                except Exception as e:
                    print(Fore.RED + f"Ошибка обработки медиагруппы: {e}" + Style.RESET_ALL)

            elif message.document and any(ext in message.document.file_name.lower() for ext in check_words):
                try:
                    print(Fore.GREEN + f"Обработка ответа от редактора: {message.document.file_name}" + Style.RESET_ALL)
                    base_name = os.path.splitext(message.document.file_name)[0]
                    cleared = re.sub(r'[^a-zA-Zа-яА-ЯёЁ0-9]', '', base_name,
                                     flags=re.IGNORECASE)
                    print(cleared.lower())

                    # Используем одно соединение для всех операций с БД
                    with sqlite3.connect("files.db") as conn:
                        cursor = conn.cursor()

                        # 1. Находим автора файла
                        cursor.execute("SELECT username FROM files WHERE filename = ?", (cleared.lower(),))
                        result = cursor.fetchone()

                        if result:
                            author = result[0]
                            file_data = await message.download(in_memory=True)
                            file_buffer = BytesIO(file_data.getvalue())
                            file_buffer.name = message.document.file_name

                            # 2. Отправляем файл автору
                            await client.send_document(
                                chat_id=author,
                                document=file_buffer,
                            )
                            print(Fore.GREEN + f"Файл отправлен автору {author}" + Style.RESET_ALL)

                            # 3. Удаляем запись из БД
                            cursor.execute("DELETE FROM files WHERE username = ? AND filename = ?",
                                           (author, cleared.lower()))
                            conn.commit()

                            # 4. Проверяем, пуста ли таблица
                            cursor.execute("SELECT COUNT(*) FROM files")
                            if cursor.fetchone()[0] == 0:
                                print(
                                    Fore.CYAN + "Таблица files пуста. Ожидаю новых файлов от клиента..." + Style.RESET_ALL)

                except Exception as e:
                    print(Fore.RED + f"Ошибка обработки файла: {e}" + Style.RESET_ALL)
                finally:
                    if 'file_buffer' in locals():
                        file_buffer.close()

        @client2.on_message(filters.photo | filters.text)
        async def handle_editor_errors(client2, message):
            # Проверяем отправителя
            if message.from_user.username != editor:
                return

            # Получаем текст сообщения: из подписи к фото или из текстового сообщения
            error_text = message.caption if message.photo else message.text

            # Проверяем наличие ключевой фразы
            if not error_text or "не проверяется" not in error_text:
                return

            try:
                print(Fore.CYAN + "Получено сообщение об ошибке" + Style.RESET_ALL)
                with sqlite3.connect("files.db") as conn:
                    cursor = conn.cursor()
                    # Получаем все записи из БД
                    cursor.execute("SELECT filename, username FROM files")
                    records = cursor.fetchall()  # Получаем список кортежей (filename, username)
                    cleared = re.sub(r'[^a-zA-Zа-яА-ЯёЁ0-9]', '', error_text,
                                     flags=re.IGNORECASE)
                    error_text = cleared.lower()

                    # Ищем совпадения в тексте ошибки
                    for filename, username in records:
                        if filename in error_text:
                            try:
                                # Отправляем сообщение автору
                                await client.send_message(
                                    chat_id=username,
                                    text=message.caption if message.photo else message.text
                                )
                                print(Fore.RED +
                                      f"Сообщение об ошибке отправлено автору {username}" +
                                      Style.RESET_ALL)
                                cursor.execute("DELETE FROM files WHERE username = ? AND filename = ?",
                                               (username, filename))
                                conn.commit()

                                # Проверяем, пуста ли таблица
                                cursor.execute("SELECT COUNT(*) FROM files")
                                if cursor.fetchone()[0] == 0:
                                    print(
                                        Fore.CYAN + "Ожидаю новых файлов от клиента..." + Style.RESET_ALL)
                            except Exception as e:
                                print(Fore.RED +
                                      f"Ошибка отправки сообщения {username}: {e}" +
                                      Style.RESET_ALL)

            except Exception as e:
                print(Fore.RED + f"Ошибка работы с БД: {e}" + Style.RESET_ALL)

        print(Fore.GREEN + f"Бот запущен как @{(await client.get_me()).username}")
        print(Fore.CYAN + "Ожидаю новых файлов от клиента..." + Style.RESET_ALL)

        async def console_input():
            while True:
                cmd = await asyncio.get_event_loop().run_in_executor(None, input)
                if cmd.lower() == 'stop':
                    active = False
                    conn = sqlite3.connect("files.db")
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM files")
                    conn.commit()
                    conn.close()
                    stop_event.set()
                    break

        console_task = asyncio.create_task(console_input())

        while not stop_event.is_set():
            await asyncio.sleep(1)

        console_task.cancel()
        stop_event.clear()
        self.clear_console()
        print(Fore.YELLOW + "Мониторинг остановлен, возвращаемся в меню" + Style.RESET_ALL)

    async def wait_for_editor_response(self, client, editor_username, min_date, timeout=36000):
        """
        Ждёт файл от редактора, который был отправлен ПОСЛЕ min_date.
        """
        print(Fore.YELLOW + f"Ожидаем новый файл от @{editor_username}..." + Style.RESET_ALL)

        start_time = time.time()
        while time.time() - start_time < timeout:
            async for message in client.get_chat_history(editor_username, limit=20):  # Проверяем последние 20 сообщений
                # Пропускаем сообщения, отправленные ДО нашего запроса
                if message.date <= min_date:
                    continue

                # Если это документ и он от редактора (не от бота)
                if message.document and message.from_user.username == editor_username:
                    file_name = f"{message.document.file_name}"
                    edited_file_path = await message.download(f"downloads/{file_name}")
                    print(Fore.BLUE + f"Получен новый файл от редактора: {edited_file_path}" + Style.RESET_ALL)
                    return edited_file_path

            await asyncio.sleep(5)  # Проверяем каждые 5 секунд

        return None

    async def notify_error(self, recipient, filename):
        """Уведомление об ошибке"""
        client = self.clients['client1']
        print(Fore.RED + f"Ошибка при обработке файла: «{filename}»!" + Style.RESET_ALL)
        await client.send_message(recipient, f"Документ «{filename}» не грузится")

    async def wait_for_bot_response(self, timeout=300):
        """Ожидание ответа от бота с улучшенной логикой"""
        client = self.clients['client1']
        start = datetime.now()
        last_message_id = 0  # Для отслеживания новых сообщений

        print(Fore.YELLOW + f"Ожидаем ответа от бота (таймаут {timeout} сек)..." + Style.RESET_ALL)

        while (datetime.now() - start).seconds < timeout:
            try:
                # Получаем историю чата
                async for message in client.get_chat_history(bot_name, limit=10):
                    # Пропускаем старые сообщения
                    if message.id <= last_message_id:
                        continue

                    # Фиксируем ID последнего сообщения
                    last_message_id = message.id

                    # Проверяем, что сообщение от нужного бота
                    if not (message.from_user and message.from_user.username == bot_name):
                        continue

                    # Логируем полученное сообщение (если есть текст)
                    if hasattr(message, 'text') and message.text:
                        print(Fore.CYAN + f"Получено сообщение от бота: {message.text}" + Style.RESET_ALL)

                        # Пропускаем сообщение о проверке файла
                        if "Проверяем файл" in message.text:
                            continue

                        return message

                    # Если есть reply_markup (кнопки), тоже возвращаем сообщение
                    if hasattr(message, 'reply_markup') and message.reply_markup:
                        return message

                await asyncio.sleep(5)  # Интервал проверки

            except Exception as e:
                print(Fore.RED + f"Ошибка при проверке сообщений: {e}" + Style.RESET_ALL)
                await asyncio.sleep(5)

        print(Fore.RED + "Таймаут ожидания ответа от бота!" + Style.RESET_ALL)
        return None

    async def get_pdf_report(self, timeout=15):
        """Получение PDF отчета с улучшенной логикой"""
        client = self.clients['client1']
        start = datetime.now()
        last_message_id = 0

        print(Fore.YELLOW + f"Ожидаем PDF отчет (таймаут {timeout} сек)..." + Style.RESET_ALL)

        while (datetime.now() - start).seconds < timeout:
            try:
                async for message in client.get_chat_history(bot_name, limit=10):
                    if message.id <= last_message_id:
                        continue

                    last_message_id = message.id

                    if (message.document and
                            message.document.mime_type == "application/pdf"):
                        print(Fore.GREEN + "Найден PDF отчет!" + Style.RESET_ALL)
                        path = await message.download(
                            file_name=f"downloads/report_temp_{message.id}.pdf"
                        )
                        return path

                await asyncio.sleep(5)

            except Exception as e:
                print(Fore.RED + f"Ошибка при проверке PDF: {e}" + Style.RESET_ALL)
                await asyncio.sleep(5)

        print(Fore.RED + "Таймаут ожидания PDF отчета!" + Style.RESET_ALL)
        return None

class web:
    async def download_raport(self, url, oldname, re, client):
        chrome_options = webdriver.ChromeOptions()

        # Добавляем все необходимые опции
        download_dir = os.path.abspath("downloads")

        # Настройки для автоматического скачивания
        prefs = {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
            "profile.default_content_settings.popups": 0
        }

        chrome_options.add_experimental_option("prefs", prefs)
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument('--headless')  # Добавьте для безголового режима
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')

        # Инициализация драйвера

        try:
            print(Fore.CYAN + f"Получена первоначальная ссылка: {url}" + Style.RESET_ALL)
            b = url.split('/apiCorp')
            c = b[1].split("?")
            e = c[1].split('userId=5')
            d = b[0] + '/apicorp/export' + c[0] + "?short=False&v=1&userId=5&c=0" + e[-1]
            download_url = d
            print(Fore.CYAN + f"Преобразована ссылка для скачивания: {download_url}" + Style.RESET_ALL)
            driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()),
                                      options=chrome_options)
            driver.get(download_url)

            try:
                # Универсальное ожидание загрузки страницы
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.export-reports"))
                )

                # Более надёжный селектор для кнопки создания отчёта
                make_btn = WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((By.XPATH,
                                                "//html/body/div[1]/main/div/div[1]/div[1]/div[2]/div[2]/table/tbody/tr/td[3]/div/button"))
                )
                make_btn.click()
                print(Fore.GREEN + "Кнопка экспорта успешно нажата" + Style.RESET_ALL)

                # Ожидание появления кнопки скачивания
                driver.get(download_url)

                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.export-reports"))
                )

                make_btn = WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((By.XPATH,
                                                "//html/body/div[1]/main/div/div[1]/div[1]/div[2]/div[2]/table/tbody/tr/td[3]/div/button"))
                )
                make_btn.click()
                print(Fore.GREEN + "Кнопка скачивания успешно нажата" + Style.RESET_ALL)

            except TimeoutException:
                print(Fore.RED + "Таймаут ожидания элемента. Возможные причины:" + Style.RESET_ALL)
                print("- Изменилась структура страницы")
                print("- Элемент находится внутри iframe")
                print("- Требуется прокрутка страницы")
                # Можно добавить скриншот для диагностики
            except Exception as e:
                print(Fore.RED + f"Неожиданная ошибка: {str(e)}" + Style.RESET_ALL)

            # Ожидание скачивания файла
            await asyncio.sleep(10)  # Увеличьте время при медленном интернете
            print(Fore.CYAN + f"Файл успешно установлен" + Style.RESET_ALL)

        except Exception as e:
            print(Fore.RED + f"Ошибка при работе с Selenium: {e}" + Style.RESET_ALL)
        finally:
            driver.quit()

        download_dir = "downloads"
        os.makedirs(download_dir, exist_ok=True)

        # Проверяем наличие нового файла
        for filename in os.listdir(download_dir):
            print(os.listdir(download_dir))
            if filename.endswith(".pdf"):
                print(Fore.GREEN + f"Найден PDF файл: {filename}" + Style.RESET_ALL)
                os.rename(os.path.join(download_dir, filename), os.path.join(download_dir, oldname))
                a = App()
                if re is None:
                    client.send_document(
                        chat_id=a.editor,
                        document=os.path.join(download_dir, oldname),
                        parse_mode="markdown"
                    )
                else:
                    client.send_document(
                        chat_id=a.editor,
                        document=os.path.join(download_dir, oldname),
                        caption=re,
                        parse_mode="markdown"
                    )


        print(Fore.RED + "PDF файл не найден в папке downloads!" + Style.RESET_ALL)
        return None

async def main():
    app = App()
    if await app.initialize():
        await app.main_menu()


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()