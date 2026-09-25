import re

from .config import FB2_CHUNK_SIZE, MAX_FB2_CHUNK_SIZE
from downloader import download_part
from .common import detect_encoding, clean_text, make_result


# ============================================================
# FB2
# ============================================================

def decode_fb2(data):
    """
    Декодирует FB2.
    """

    encoding = detect_encoding(
        data
    )

    try:

        return data.decode(
            encoding,
            errors="ignore"
        )

    except LookupError:

        return data.decode(
            "utf-8",
            errors="ignore"
        )


def extract_fb2_paragraphs(
    text
):
    """
    Извлекает содержимое <p>...</p>.
    """

    pattern = re.compile(
        r"<(?:[\w.-]+:)?p\b[^>]*>"
        r"(.*?)"
        r"</(?:[\w.-]+:)?p\s*>",
        re.IGNORECASE | re.DOTALL
    )

    paragraphs = []

    for match in pattern.finditer(text):

        paragraph = clean_text(
            match.group(1)
        )

        if paragraph:
            paragraphs.append(
                paragraph
            )

    return paragraphs


async def get_fb2_middle_text(
    client,
    message
):
    """
    Берёт текст примерно из середины FB2.

    Сначала:
        32 KB

    Потом:
        64 KB
        128 KB
        256 KB
        512 KB

    Весь файл не скачивается.
    """

    file_size = message.document.size

    if not file_size:
        return None

    amount = min(
        FB2_CHUNK_SIZE,
        file_size
    )

    while True:

        offset = max(
            0,
            file_size // 2 - amount // 2
        )

        data = await download_part(
            client,
            message,
            offset,
            amount
        )

        text = decode_fb2(
            data
        )

        paragraphs = extract_fb2_paragraphs(
            text
        )

        if paragraphs:

            text = "\n\n".join(
                paragraphs
            )

            result = make_result(
                text
            )

            if result:
                return result

        if amount >= file_size:
            break

        if amount >= MAX_FB2_CHUNK_SIZE:
            break

        amount = min(
            amount * 2,
            MAX_FB2_CHUNK_SIZE,
            file_size
        )

    return None