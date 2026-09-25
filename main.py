import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events

from extractors.fb2 import get_fb2_middle_text
from extractors.zip import get_zip_middle_text
from extractors.epub import get_epub_middle_text
from extractors.pdf import get_pdf_middle_text


# ============================================================
# ОПРЕДЕЛЕНИЕ ФОРМАТА
# ============================================================

async def get_middle_text(
    client,
    message
):
    """
    Главная функция.

    Поддерживает:
        FB2
        EPUB
        ZIP
        PDF
    """

    if not message.document:
        return None

    filename = (
        message.file.name
        or ""
    )

    extension = Path(
        filename
    ).suffix.lower()

    print(
        f"[FORMAT] {extension or 'unknown'}"
    )

    if extension == ".fb2":

        return await get_fb2_middle_text(
            client,
            message
        )

    if extension == ".epub":

        return await get_epub_middle_text(
            client,
            message
        )

    if extension == ".zip":

        return await get_zip_middle_text(
            client,
            message
        )

    if extension == ".pdf":

        return await get_pdf_middle_text(
            client,
            message
        )

    return None


# ============================================================
# TELEGRAM BOT
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv(
    "bot_token"
)

API_ID = os.getenv(
    "api_id"
)

API_HASH = os.getenv(
    "api_hash"
)

SESSION = "middle_text_bot"


client = TelegramClient(
    SESSION,
    API_ID,
    API_HASH
)


# ============================================================
# ОБРАБОТКА ФАЙЛА
# ============================================================

@client.on(events.NewMessage)
async def handle_file(
    event
):
    message = event.message

    if not message.document:
        return

    filename = (
        message.file.name
        or ""
    )

    extension = Path(
        filename
    ).suffix.lower()

    supported = {
        ".fb2",
        ".epub",
        ".zip",
        ".pdf"
    }

    if extension not in supported:
        return

    print()
    print("=" * 80)
    print(
        f"Получен файл: {filename}"
    )

    if message.document.size:

        print(
            "Размер: "
            f"{message.document.size / 1024 / 1024:.2f} MB"
        )

    print(
        "Формат:",
        extension
    )

    print(
        "Ищу текст примерно в середине..."
    )

    try:

        text = await get_middle_text(
            client,
            message
        )

        if not text:

            print()
            print(
                "Не удалось получить "
                "1000–1500 слов."
            )

            return

        print()
        print("=" * 80)
        print("РЕЗУЛЬТАТ:")
        print("=" * 80)

        print(text)

        print("=" * 80)

        print(
            "Количество слов:",
            len(text.split())
        )

        print("=" * 80)

    except Exception as e:

        print(
            f"Ошибка: {type(e).__name__}: {e}"
        )


# ============================================================
# ЗАПУСК
# ============================================================

async def main():

    await client.start(
        bot_token=BOT_TOKEN
    )

    print(
        "Бот запущен."
    )

    print(
        "Отправь ему FB2, EPUB, ZIP или PDF."
    )

    await client.run_until_disconnected()


if __name__ == "__main__":

    import asyncio

    asyncio.run(
        main()
    )