## Если нужно просто добавить в существующий код, используйте эту обертку
from pyrogram.errors import TimeoutError, FloodWait
import asyncio

async def safe_send_document(client, chat_id, document, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await client.send_document(chat_id, document, timeout=300)
        except TimeoutError:
            if attempt < max_retries - 1:
                await asyncio.sleep(5 * (attempt + 1))
            else:
                raise
        except FloodWait as e:
            await asyncio.sleep(e.value)