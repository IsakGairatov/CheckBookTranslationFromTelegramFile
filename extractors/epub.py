import re
from html import unescape

from .config import (
    MIN_WORDS,
    MAX_WORDS,
    MAX_ZIP_ENTRY_CHUNK_SIZE,
)

from .common import (
    detect_encoding,
    trim_to_sentences,
)

from .zip import (
    get_zip_entries,
    download_zip_entry,
)

# ============================================================
# EPUB
# ============================================================

def decode_xml(
    data
):
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


def extract_epub_opf_info(
    data
):
    """
    Извлекает manifest + spine EPUB.
    """

    text = decode_xml(
        data
    )

    manifest = {}

    for match in re.finditer(
        r"<item\b([^>]*)>",
        text,
        re.IGNORECASE
    ):

        attrs = match.group(1)

        id_match = re.search(
            r'\bid\s*=\s*["\']([^"\']+)["\']',
            attrs,
            re.IGNORECASE
        )

        href_match = re.search(
            r'\bhref\s*=\s*["\']([^"\']+)["\']',
            attrs,
            re.IGNORECASE
        )

        media_match = re.search(
            r'\bmedia-type\s*=\s*["\']([^"\']+)["\']',
            attrs,
            re.IGNORECASE
        )

        if not id_match or not href_match:
            continue

        manifest[
            id_match.group(1)
        ] = {
            "href": href_match.group(1),
            "media_type": (
                media_match.group(1)
                if media_match
                else ""
            )
        }

    spine_ids = []

    for match in re.finditer(
        r"<itemref\b([^>]*)>",
        text,
        re.IGNORECASE
    ):

        attrs = match.group(1)

        idref_match = re.search(
            r'\bidref\s*=\s*["\']([^"\']+)["\']',
            attrs,
            re.IGNORECASE
        )

        if idref_match:

            spine_ids.append(
                idref_match.group(1)
            )

    return manifest, spine_ids


def extract_html_text(data):
    """
    Извлекает обычный текст из XHTML/HTML EPUB.
    Не зависит от наличия <p>.
    """

    text = decode_xml(data)

    # --------------------------------------------------------
    # Удаляем script/style
    # --------------------------------------------------------

    text = re.sub(
        r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>",
        " ",
        text,
        flags=re.IGNORECASE | re.DOTALL
    )

    # --------------------------------------------------------
    # Переносы для блочных элементов
    # --------------------------------------------------------

    text = re.sub(
        r"</(?:p|div|section|article|blockquote|h[1-6]|li|br)\s*>",
        "\n",
        text,
        flags=re.IGNORECASE
    )

    # --------------------------------------------------------
    # Удаляем остальные XML/HTML-теги
    # --------------------------------------------------------

    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    # --------------------------------------------------------
    # HTML entities
    # --------------------------------------------------------

    text = unescape(
        text
    )

    # --------------------------------------------------------
    # Нормализуем строки
    # --------------------------------------------------------

    lines = []

    for line in text.splitlines():

        line = " ".join(
            line.split()
        )

        if line:
            lines.append(
                line
            )

    if not lines:
        return None

    return "\n\n".join(
        lines
    )


async def get_epub_middle_text(
    client,
    message
):
    """
    EPUB является ZIP.

    Не читаем OPF и не используем spine.

    Находим XHTML/HTML-файлы внутри EPUB,
    выбираем файл примерно из середины,
    скачиваем только его.

    Если в главе:
        меньше 1000 слов -> возвращаем всю главу.

    Если 1000+ слов:
        берём до 1500 слов.
    """

    entries = await get_zip_entries(
        client,
        message
    )

    if not entries:
        return None

    # --------------------------------------------------------
    # Ищем только текстовые файлы EPUB
    # --------------------------------------------------------

    text_entries = []

    for entry in entries:

        filename = entry["filename"].lower()

        if filename.endswith(
            (".xhtml", ".html", ".htm")
        ):
            text_entries.append(
                entry
            )

    if not text_entries:
        print(
            "[EPUB] XHTML/HTML файлы не найдены."
        )

        return None

    print(
        f"[EPUB] Найдено XHTML/HTML файлов: "
        f"{len(text_entries)}"
    )

    # --------------------------------------------------------
    # Выбираем файл примерно из середины
    # --------------------------------------------------------

    middle_index = (
        len(text_entries) // 2
    )

    # Сначала середина,
    # затем соседние файлы.
    indexes = [
        middle_index
    ]

    for distance in range(
        1,
        len(text_entries)
    ):

        left = (
            middle_index - distance
        )

        right = (
            middle_index + distance
        )

        if left >= 0:
            indexes.append(left)

        if right < len(text_entries):
            indexes.append(right)

        # Не нужно просматривать весь EPUB.
        if len(indexes) >= 5:
            break

    # --------------------------------------------------------
    # Пробуем центральные главы
    # --------------------------------------------------------

    for index in indexes:

        entry = text_entries[index]

        print(
            f"[EPUB] Читаю: "
            f"{entry['filename']} "
            f"compressed={entry['compressed_size']} "
            f"uncompressed={entry['uncompressed_size']}"
        )

        # ----------------------------------------------------
        # Если файл огромный,
        # не скачиваем больше 512 KB.
        # ----------------------------------------------------

        data = await download_zip_entry(
            client,
            message,
            entry,
            max_compressed_size=MAX_ZIP_ENTRY_CHUNK_SIZE
        )

        if not data:
            print(
                "[EPUB] Не удалось скачать содержимое."
            )

            continue

        text = extract_html_text(
            data
        )

        if not text:
            print(
                "[EPUB] Текст не найден."
            )

            continue

        words = re.findall(
            r"\S+",
            text
        )

        word_count = len(words)

        print(
            f"[EPUB] Получено текста: "
            f"{word_count} слов"
        )

        # ----------------------------------------------------
        # Меньше 1000 слов —
        # просто возвращаем всю главу.
        # ----------------------------------------------------

        if word_count < MIN_WORDS:

            print(
                "[EPUB] В главе меньше 1000 слов."
            )

            print(
                "[EPUB] Возвращаю всю главу."
            )

            return text

        # ----------------------------------------------------
        # 1000+ слов —
        # берём максимум 1500.
        # ----------------------------------------------------

        amount = min(
            MAX_WORDS,
            word_count
        )

        start = max(
            0,
            (word_count - amount) // 2
        )

        result = " ".join(
            words[
                start:
                start + amount
            ]
        )

        # ----------------------------------------------------
        # Убираем обрезанные предложения.
        # ----------------------------------------------------

        result = trim_to_sentences(
            result
        )

        if not result:
            continue

        print(
            f"[EPUB] Итоговых слов: "
            f"{len(result.split())}"
        )

        return result

    return None