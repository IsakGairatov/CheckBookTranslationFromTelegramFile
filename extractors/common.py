import re
from html import unescape

from .config import (
    MIN_WORDS,
    MAX_WORDS,
    MAX_ZIP_ENTRY_CHUNK_SIZE,
)


# ============================================================
# ОБЩИЕ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def clean_text(text):
    """
    Убирает XML/HTML-теги, entities
    и лишние пробелы.
    """

    if not text:
        return None

    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    text = unescape(text)

    text = " ".join(
        text.split()
    )

    return text.strip() or None


def detect_encoding(data):
    """
    Определяет XML-кодировку.
    """

    match = re.search(
        rb'<\?xml[^>]+encoding=["\']([^"\']+)["\']',
        data[:4096],
        re.IGNORECASE
    )

    if match:

        try:
            return match.group(1).decode(
                "ascii"
            )
        except UnicodeDecodeError:
            pass

    return "utf-8"


def extract_tag_value(
    text,
    tag
):
    """
    Ищет:

        <title>...</title>
        <dc:title>...</dc:title>
    """

    match = re.search(
        rf"<(?:[\w.-]+:)?{re.escape(tag)}\b[^>]*>"
        rf"(.*?)"
        rf"</(?:[\w.-]+:)?{re.escape(tag)}\s*>",
        text,
        re.IGNORECASE | re.DOTALL
    )

    if not match:
        return None

    return clean_text(
        match.group(1)
    )


# ============================================================
# ПРЕДЛОЖЕНИЯ
# ============================================================

def trim_to_sentences(text):
    """
    Оставляет только цельные предложения.

    Первое и последнее неполное предложение
    удаляются.
    """

    if not text:
        return None

    # --------------------------------------------------------
    # Начало
    # --------------------------------------------------------

    start_match = re.search(
        r'[.!?]["»”\']?\s+',
        text
    )

    if start_match:

        text = text[
            start_match.end():
        ]

    # --------------------------------------------------------
    # Конец
    # --------------------------------------------------------

    matches = list(
        re.finditer(
            r'[.!?]["»”\']?(?=\s|$)',
            text
        )
    )

    if matches:

        text = text[
            :matches[-1].end()
        ]

    text = text.strip()

    if not text:
        return None

    return text


def make_result(
    text
):
    """
    Берёт 1000–1500 слов и
    оставляет только цельные предложения.
    """

    words = re.findall(
        r"\S+",
        text
    )

    if len(words) < MIN_WORDS:
        return None

    amount = min(
        MAX_WORDS,
        len(words)
    )

    start = max(
        0,
        (len(words) - amount) // 2
    )

    result = " ".join(
        words[
            start:
            start + amount
        ]
    )

    result = trim_to_sentences(
        result
    )

    if not result:
        return None

    if len(result.split()) < MIN_WORDS:
        return None

    return result