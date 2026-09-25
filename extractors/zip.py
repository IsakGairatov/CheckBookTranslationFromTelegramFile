import re
import struct
import zlib

from .config import (
    MIN_WORDS,
    MAX_WORDS,
    ZIP_TAIL_SIZE,
    MAX_ZIP_TAIL_SIZE,
    ZIP_ENTRY_CHUNK_SIZE,
    MAX_ZIP_ENTRY_CHUNK_SIZE,
    MAX_ZIP_TEXT_DOWNLOAD,
)



from downloader import download_part

from .fb2 import (
    decode_fb2,
    extract_fb2_paragraphs,
)

from .common import (
    trim_to_sentences,
)

# ============================================================
# ZIP CENTRAL DIRECTORY
# ============================================================

def find_eocd(
    data
):
    return data.rfind(
        b"PK\x05\x06"
    )


def dos_datetime_to_string(
    dos_date,
    dos_time
):
    try:

        year = 1980 + (
            (dos_date >> 9) & 0x7F
        )

        month = (
            dos_date >> 5
        ) & 0x0F

        day = dos_date & 0x1F

        hour = (
            dos_time >> 11
        ) & 0x1F

        minute = (
            dos_time >> 5
        ) & 0x3F

        second = (
            dos_time & 0x1F
        ) * 2

        return (
            f"{year:04d}-"
            f"{month:02d}-"
            f"{day:02d} "
            f"{hour:02d}:"
            f"{minute:02d}:"
            f"{second:02d}"
        )

    except ValueError:

        return None


def parse_zip_entries(
    tail,
    tail_offset
):
    """
    Разбирает ZIP Central Directory.
    """

    eocd_pos = find_eocd(
        tail
    )

    if eocd_pos == -1:
        return None

    if eocd_pos + 22 > len(tail):
        return None

    central_directory_size = struct.unpack_from(
        "<I",
        tail,
        eocd_pos + 12
    )[0]

    central_directory_offset = struct.unpack_from(
        "<I",
        tail,
        eocd_pos + 16
    )[0]

    local_offset = (
        central_directory_offset
        - tail_offset
    )

    if local_offset < 0:
        return None

    if (
        local_offset + central_directory_size
        > len(tail)
    ):
        return None

    directory = tail[
        local_offset:
        local_offset + central_directory_size
    ]

    entries = []

    pos = 0

    while pos + 46 <= len(directory):

        if directory[
            pos:pos + 4
        ] != b"PK\x01\x02":
            break

        compression = struct.unpack_from(
            "<H",
            directory,
            pos + 10
        )[0]

        modification_time = struct.unpack_from(
            "<H",
            directory,
            pos + 12
        )[0]

        modification_date = struct.unpack_from(
            "<H",
            directory,
            pos + 14
        )[0]

        compressed_size = struct.unpack_from(
            "<I",
            directory,
            pos + 20
        )[0]

        uncompressed_size = struct.unpack_from(
            "<I",
            directory,
            pos + 24
        )[0]

        filename_length = struct.unpack_from(
            "<H",
            directory,
            pos + 28
        )[0]

        extra_length = struct.unpack_from(
            "<H",
            directory,
            pos + 30
        )[0]

        comment_length = struct.unpack_from(
            "<H",
            directory,
            pos + 32
        )[0]

        local_header_offset = struct.unpack_from(
            "<I",
            directory,
            pos + 42
        )[0]

        filename_start = pos + 46

        filename_end = (
            filename_start
            + filename_length
        )

        filename_bytes = directory[
            filename_start:
            filename_end
        ]

        try:

            filename = filename_bytes.decode(
                "utf-8"
            )

        except UnicodeDecodeError:

            filename = filename_bytes.decode(
                "cp437",
                errors="replace"
            )

        generated_at = dos_datetime_to_string(
            modification_date,
            modification_time
        )

        entries.append({
            "filename": filename,
            "compression": compression,
            "compressed_size": compressed_size,
            "uncompressed_size": uncompressed_size,
            "local_header_offset": local_header_offset,
            "generated_at": generated_at
        })

        pos = (
            filename_end
            + extra_length
            + comment_length
        )

    return entries


async def get_zip_entries(
    client,
    message
):
    """
    Читает только конец ZIP.
    """

    file_size = message.document.size

    amount = min(
        ZIP_TAIL_SIZE,
        file_size
    )

    while True:

        offset = max(
            0,
            file_size - amount
        )

        tail = await download_part(
            client,
            message,
            offset,
            amount
        )

        entries = parse_zip_entries(
            tail,
            offset
        )

        if entries is not None:
            return entries

        if amount >= file_size:
            return None

        if amount >= MAX_ZIP_TAIL_SIZE:
            return None

        amount = min(
            amount * 2,
            MAX_ZIP_TAIL_SIZE,
            file_size
        )

    return None


# ============================================================
# ZIP ENTRY
# ============================================================

async def download_zip_entry_start(
    client,
    message,
    entry
):
    """
    Скачивает начало FB2 внутри ZIP.

    Для DEFLATE:
        - начинаем с начала FB2
        - скачиваем блоками по 32 KB
        - максимум 60 KB сжатых данных
        - возвращаем распакованный результат

    Для STORED:
        - просто скачиваем первые 60 KB.
    """

    local_header_offset = entry["local_header_offset"]

    # --------------------------------------------------------
    # Читаем Local File Header
    # --------------------------------------------------------

    header = await download_part(
        client,
        message,
        local_header_offset,
        30
    )

    if len(header) < 30:
        return None

    if header[:4] != b"PK\x03\x04":
        return None

    filename_length = struct.unpack_from(
        "<H",
        header,
        26
    )[0]

    extra_length = struct.unpack_from(
        "<H",
        header,
        28
    )[0]

    data_offset = (
        local_header_offset
        + 30
        + filename_length
        + extra_length
    )

    compressed_size = entry["compressed_size"]

    # --------------------------------------------------------
    # Максимум 60 KB сжатого FB2
    # --------------------------------------------------------

    max_download = min(
        MAX_ZIP_TEXT_DOWNLOAD,
        compressed_size
    )

    # --------------------------------------------------------
    # STORED
    # --------------------------------------------------------

    if entry["compression"] == 0:

        return await download_part(
            client,
            message,
            data_offset,
            max_download
        )

    # --------------------------------------------------------
    # DEFLATE
    # --------------------------------------------------------

    if entry["compression"] != 8:

        print(
            f"[ZIP] Неподдерживаемое сжатие: "
            f"{entry['compression']}"
        )

        return None

    decompressor = zlib.decompressobj(
        -15
    )

    downloaded = 0

    result = bytearray()

    while downloaded < max_download:

        remaining = max_download - downloaded

        # Telegram не принимает наш последний
        # произвольный кусок 28 KB.
        # Поэтому скачиваем целый блок 32 KB.
        amount = ZIP_ENTRY_CHUNK_SIZE

        if remaining < ZIP_ENTRY_CHUNK_SIZE:
            amount = ZIP_ENTRY_CHUNK_SIZE

        compressed_chunk = await download_part(
            client,
            message,
            data_offset + downloaded,
            amount
        )

        if not compressed_chunk:
            break

        downloaded += len(
            compressed_chunk
        )

        try:

            decompressed = (
                decompressor.decompress(
                    compressed_chunk
                )
            )

        except zlib.error as e:

            print(
                f"[ZIP] Ошибка DEFLATE: {e}"
            )

            return None

        result.extend(
            decompressed
        )

        if len(compressed_chunk) < amount:
            break

    print(
        f"[ZIP] Скачано сжатых данных: "
        f"{downloaded:,} байт "
        f"из максимум {max_download:,}"
    )

    print(
        f"[ZIP] Распаковано: "
        f"{len(result):,} байт"
    )

    return bytes(result)

# ============================================================
# ZIP ENTRY — EPUB
# ============================================================

async def download_zip_entry(
    client,
    message,
    entry,
    max_compressed_size=MAX_ZIP_ENTRY_CHUNK_SIZE
):
    """
    Скачивает начало одного файла внутри ZIP.

    Используется для EPUB/XHTML.

    DEFLATE:
        начинаем с начала сжатого потока
        и последовательно распаковываем.

    STORED:
        просто скачиваем начало файла.

    Весь ZIP/EPUB не скачивается.
    """

    local_header_offset = entry[
        "local_header_offset"
    ]

    # --------------------------------------------------------
    # Local File Header
    # --------------------------------------------------------

    header = await download_part(
        client,
        message,
        local_header_offset,
        30
    )

    if len(header) < 30:
        return None

    if header[:4] != b"PK\x03\x04":
        return None

    filename_length = struct.unpack_from(
        "<H",
        header,
        26
    )[0]

    extra_length = struct.unpack_from(
        "<H",
        header,
        28
    )[0]

    data_offset = (
        local_header_offset
        + 30
        + filename_length
        + extra_length
    )

    compressed_size = entry[
        "compressed_size"
    ]

    # Не скачиваем больше,
    # чем реально есть в entry.
    max_download = min(
        max_compressed_size,
        compressed_size
    )

    if max_download <= 0:
        return None

    # --------------------------------------------------------
    # STORED
    # --------------------------------------------------------

    if entry["compression"] == 0:

        return await download_part(
            client,
            message,
            data_offset,
            max_download
        )

    # --------------------------------------------------------
    # DEFLATE
    # --------------------------------------------------------

    if entry["compression"] != 8:

        print(
            f"[EPUB] Неподдерживаемое "
            f"сжатие: {entry['compression']}"
        )

        return None

    decompressor = zlib.decompressobj(
        -15
    )

    downloaded = 0
    result = bytearray()

    while downloaded < max_download:

        remaining = (
            max_download
            - downloaded
        )

        # ----------------------------------------------------
        # Telegram нормально работает с блоками 32 KB.
        #
        # Даже если remaining меньше 32 KB,
        # запрашиваем полный блок.
        # download_part() сам обрежет результат
        # до нужного размера.
        # ----------------------------------------------------

        amount = ZIP_ENTRY_CHUNK_SIZE

        compressed_chunk = await download_part(
            client,
            message,
            data_offset + downloaded,
            amount
        )

        if not compressed_chunk:
            break

        downloaded += len(
            compressed_chunk
        )

        try:

            decompressed = (
                decompressor.decompress(
                    compressed_chunk
                )
            )

        except zlib.error as e:

            print(
                f"[EPUB] Ошибка DEFLATE: {e}"
            )

            return None

        result.extend(
            decompressed
        )

        # Если получили меньше запрошенного,
        # значит файл закончился.
        if len(compressed_chunk) < amount:
            break

        # Если ZIP entry полностью скачан.
        if downloaded >= max_download:
            break

    print(
        f"[EPUB] Скачано сжатых данных: "
        f"{downloaded:,} байт "
        f"из максимум {max_download:,}"
    )

    print(
        f"[EPUB] Распаковано: "
        f"{len(result):,} байт"
    )

    return bytes(result)


# ============================================================
# ZIP → FB2
# ============================================================

async def get_zip_middle_text(
    client,
    message
):
    """
    ZIP → FB2.

    Берём начало FB2, но не метаданные.

    Максимум:
        60 KB сжатых данных.

    Из полученного текста пытаемся получить
    1000–1500 слов.
    """

    entries = await get_zip_entries(
        client,
        message
    )

    if not entries:
        return None

    # --------------------------------------------------------
    # Ищем FB2
    # --------------------------------------------------------

    fb2_entries = [
        entry
        for entry in entries
        if entry["filename"].lower().endswith(".fb2")
    ]

    if not fb2_entries:

        print(
            "[ZIP] FB2 внутри ZIP не найден."
        )

        return None

    # Если несколько FB2 —
    # берём самый большой.
    entry = max(
        fb2_entries,
        key=lambda x: x["uncompressed_size"]
    )

    print(
        f"[ZIP] FB2: {entry['filename']}"
    )

    print(
        f"[ZIP] Размер FB2: "
        f"{entry['uncompressed_size']:,} байт"
    )

    # --------------------------------------------------------
    # Скачиваем только начало FB2
    # --------------------------------------------------------

    data = await download_zip_entry_start(
        client,
        message,
        entry
    )

    if not data:
        return None

    # --------------------------------------------------------
    # Декодируем
    # --------------------------------------------------------

    text = decode_fb2(
        data
    )

    # --------------------------------------------------------
    # Извлекаем только <p>
    # --------------------------------------------------------

    body_match = re.search(
        r"<body\b[^>]*>",
        text,
        re.IGNORECASE
    )

    if not body_match:
        print(
            "[ZIP] <body> ещё не попал "
            "в первые 60 KB."
        )

        return None

    body_text = text[
                body_match.end():
                ]

    paragraphs = extract_fb2_paragraphs(
        body_text
    )

    if not paragraphs:
        print(
            "[ZIP] В <body> не найдены <p>."
        )

        return None

    full_text = "\n\n".join(
        paragraphs
    )

    # --------------------------------------------------------
    # Слова
    # --------------------------------------------------------

    words = re.findall(
        r"\S+",
        full_text
    )

    print(
        f"[ZIP] Получено слов: "
        f"{len(words)}"
    )

    # --------------------------------------------------------
    # Если меньше 1000 —
    # значит 60 KB оказалось недостаточно
    # --------------------------------------------------------

    if len(words) < MIN_WORDS:

        print(
            "[ZIP] В первых 60 KB "
            "недостаточно текста."
        )

        return None

    # --------------------------------------------------------
    # Берём первые 1000–1500 слов
    #
    # Здесь НЕ нужно брать середину полученного
    # куска — нам нужен именно текст начала книги.
    # --------------------------------------------------------

    amount = min(
        MAX_WORDS,
        len(words)
    )

    result = " ".join(
        words[:amount]
    )

    result = trim_to_sentences(
        result
    )

    if not result:
        return None

    print(
        f"[ZIP] Итоговых слов: "
        f"{len(result.split())}"
    )

    return result