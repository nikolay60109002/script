import asyncio
import time
from pyrogram import Client
from pyrogram.errors import FloodWait, TimeoutError

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

async def send_files_safely(client, chat_id, file_paths, max_concurrent=2):
    """
    Безопасная отправка нескольких файлов с ограничением одновременных запросов
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def send_with_semaphore(file_path):
        async with semaphore:
            return await send_file_with_retry(client, chat_id, file_path)
    
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

# Пример использования
async def main():
    # Ваши данные API
    api_id = 'your_api_id'
    api_hash = 'your_api_hash'
    
    async with Client("my_account", api_id, api_hash) as client:
        chat_id = "your_chat_id"  # ID чата или канала
        
        file_paths = [
            "file1.docx",
            "file2.pdf", 
            "file3.jpg"
            # ваш список файлов
        ]
        
        # Фильтруем файлы с нулевым размером
        valid_files = []
        for file_path in file_paths:
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                valid_files.append(file_path)
            else:
                print(f"Пропускаем файл с нулевым размером или несуществующий: {file_path}")
        
        if valid_files:
            await send_files_safely(client, chat_id, valid_files)
        else:
            print("Нет валидных файлов для отправки")

# Дополнительная функция для проверки файла перед отправкой
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

# Если нужно запустить для одного файла
async def send_single_file_safely(client, chat_id, file_path):
    """
    Безопасная отправка одного файла
    """
    if not validate_file(file_path):
        return False
    
    return await send_file_with_retry(client, chat_id, file_path)

# Запуск
if __name__ == "__main__":
    import os
    
    # Для Windows и macOS
    if os.name == 'nt':  # Windows
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    asyncio.run(main())