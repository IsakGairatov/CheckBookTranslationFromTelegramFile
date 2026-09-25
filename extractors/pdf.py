import re
import zlib

from .config import (
    PDF_MIDDLE_CHUNK_SIZE,
    PDF_START_CHUNK_SIZE,
    MIN_WORDS,
    MAX_WORDS,
)

from downloader import download_part

from .common import (
    trim_to_sentences,
)

# ============================================================
# PDF
# ============================================================


def decode_pdf_literal_string(data):
    """
    Декодирует PDF literal string:

        (Hello world)

    Поддерживает:
    - \\n
    - \\r
    - \\t
    - \\b
    - \\f
    - \\(
    - \\)
    - \\\\
    - octal escapes
    - escaped newline
    """

    if not data:
        return b""

    result = bytearray()
    i = 0
    length = len(data)

    while i < length:

        byte = data[i]

        if byte != 0x5C:

            result.append(byte)
            i += 1
            continue

        i += 1

        if i >= length:
            break

        byte = data[i]

        escapes = {
            ord("n"): b"\n",
            ord("r"): b"\r",
            ord("t"): b"\t",
            ord("b"): b"\b",
            ord("f"): b"\f",
            ord("("): b"(",
            ord(")"): b")",
            ord("\\"): b"\\",
        }

        if byte in escapes:

            result.extend(
                escapes[byte]
            )

            i += 1
            continue

        # Escaped newline
        if byte == 0x0A:

            i += 1
            continue

        if byte == 0x0D:

            i += 1

            if (
                i < length
                and data[i] == 0x0A
            ):
                i += 1

            continue

        # Octal escape
        if 48 <= byte <= 55:

            octal = byte - 48
            count = 1

            i += 1

            while (
                i < length
                and count < 3
                and 48 <= data[i] <= 55
            ):

                octal = (
                    octal * 8
                    + data[i] - 48
                )

                count += 1
                i += 1

            result.append(
                octal & 0xFF
            )

            continue

        # Неизвестный escape
        result.append(byte)

        i += 1

    return bytes(result)


def decode_pdf_hex_string(data):
    """
    Декодирует PDF hex string:

        <48656C6C6F>
    """

    if not data:
        return b""

    data = re.sub(
        rb"\s+",
        b"",
        data
    )

    if not data:
        return b""

    if len(data) % 2:

        data += b"0"

    try:

        return bytes.fromhex(
            data.decode("ascii")
        )

    except (
        ValueError,
        UnicodeDecodeError
    ):

        return b""


def decode_pdf_text_bytes(data):
    """
    Пытается декодировать PDF text string.

    Поддерживает:
    - UTF-16 BE
    - UTF-16 LE
    - UTF-8
    - CP1252
    - Latin-1
    """

    if not data:
        return ""

    # UTF-16 BE
    if data.startswith(
        b"\xfe\xff"
    ):

        try:

            return data.decode(
                "utf-16-be",
                errors="ignore"
            )

        except UnicodeDecodeError:

            pass

    # UTF-16 LE
    if data.startswith(
        b"\xff\xfe"
    ):

        try:

            return data.decode(
                "utf-16-le",
                errors="ignore"
            )

        except UnicodeDecodeError:

            pass

    # UTF-8
    try:

        text = data.decode(
            "utf-8",
            errors="strict"
        )

        if text:
            return text

    except UnicodeDecodeError:

        pass

    # CP1252
    try:

        text = data.decode(
            "cp1252",
            errors="ignore"
        )

        if text:
            return text

    except UnicodeDecodeError:

        pass

    # Latin-1
    try:

        return data.decode(
            "latin-1",
            errors="ignore"
        )

    except UnicodeDecodeError:

        return ""


def clean_pdf_text(text):
    """
    Чистит извлечённый PDF-текст.
    """

    if not text:
        return ""

    # Убираем управляющие символы
    text = re.sub(
        r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]",
        " ",
        text
    )

    # NBSP
    text = text.replace(
        "\u00a0",
        " "
    )

    # Несколько пробелов / переносов
    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def pdf_text_quality(text):
    """
    Проверяет, похож ли текст
    на настоящий человеческий текст.

    Защищает от бинарного мусора.
    """

    if not text:
        return 0.0

    visible = 0
    letters = 0
    spaces = 0
    controls = 0

    for char in text:

        code = ord(char)

        if char.isspace():

            spaces += 1
            visible += 1
            continue

        if code < 32:

            controls += 1
            continue

        visible += 1

        if char.isalpha():

            letters += 1

    if visible == 0:
        return 0.0

    control_ratio = (
        controls / max(
            1,
            len(text)
        )
    )

    if control_ratio > 0.05:
        return 0.0

    letter_ratio = (
        letters / max(
            1,
            visible
        )
    )

    space_ratio = (
        spaces / max(
            1,
            len(text)
        )
    )

    score = (
        letter_ratio * 0.75
        + min(
            space_ratio * 2.0,
            0.20
        )
    )

    return min(
        1.0,
        score
    )


def extract_pdf_literal_strings(data):
    """
    Извлекает literal strings из PDF.

    Поддерживает вложенные скобки:

        (Hello (world))
    """

    results = []

    if not data:
        return results

    i = 0
    length = len(data)

    while i < length:

        if data[i] != ord("("):

            i += 1
            continue

        start = i

        depth = 1
        escaped = False

        i += 1

        while i < length:

            byte = data[i]

            if escaped:

                escaped = False
                i += 1
                continue

            if byte == 0x5C:

                escaped = True
                i += 1
                continue

            if byte == ord("("):

                depth += 1

            elif byte == ord(")"):

                depth -= 1

                if depth == 0:

                    results.append(
                        data[
                            start + 1:i
                        ]
                    )

                    i += 1
                    break

            i += 1

        else:

            break

    return results

def parse_pdf_cmap(data):
    """
    Разбирает PDF ToUnicode CMap.

    Поддерживает:
    - beginbfchar
    - beginbfrange
    """

    if not data:
        return {}

    # Если CMap сжат — пробуем распаковать.
    if b"beginbfchar" not in data and b"beginbfrange" not in data:

        try:
            data = zlib.decompress(data)

        except zlib.error:

            try:
                data = zlib.decompress(
                    data,
                    -15
                )

            except zlib.error:
                return {}

    cmap = {}

    # --------------------------------------------------------
    # beginbfchar
    #
    # <0115> <0422>
    # <0116> <0435>
    # --------------------------------------------------------

    for block in re.findall(
        rb"beginbfchar(.*?)endbfchar",
        data,
        re.S
    ):

        for match in re.finditer(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>",
            block
        ):

            src = int(
                match.group(1),
                16
            )

            dst_bytes = bytes.fromhex(
                match.group(2).decode("ascii")
            )

            try:

                dst = dst_bytes.decode(
                    "utf-16-be"
                )

            except UnicodeDecodeError:

                dst = dst_bytes.decode(
                    "latin-1",
                    errors="ignore"
                )

            cmap[src] = dst

    # --------------------------------------------------------
    # beginbfrange
    #
    # <0001> <0005> <0041>
    #
    # или:
    #
    # <0001> <0005>
    # [
    #   <0041>
    #   <0042>
    #   <0043>
    #   ...
    # ]
    # --------------------------------------------------------

    for block in re.findall(
        rb"beginbfrange(.*?)endbfrange",
        data,
        re.S
    ):

        # ----------------------------------------------------
        # Диапазон с последовательными Unicode-кодами
        # ----------------------------------------------------

        for match in re.finditer(
            rb"<([0-9A-Fa-f]+)>\s+"
            rb"<([0-9A-Fa-f]+)>\s+"
            rb"<([0-9A-Fa-f]+)>",
            block
        ):

            start = int(
                match.group(1),
                16
            )

            end = int(
                match.group(2),
                16
            )

            dst = int(
                match.group(3),
                16
            )

            for src in range(
                start,
                end + 1
            ):

                try:

                    cmap[src] = chr(
                        dst + (src - start)
                    )

                except ValueError:

                    pass

        # ----------------------------------------------------
        # Диапазон со списком
        # ----------------------------------------------------

        for match in re.finditer(
            rb"<([0-9A-Fa-f]+)>\s+"
            rb"<([0-9A-Fa-f]+)>\s+"
            rb"\[(.*?)\]",
            block,
            re.S
        ):

            start = int(
                match.group(1),
                16
            )

            end = int(
                match.group(2),
                16
            )

            values = re.findall(
                rb"<([0-9A-Fa-f]+)>",
                match.group(3)
            )

            for index, value in enumerate(values):

                src = start + index

                if src > end:
                    break

                raw = bytes.fromhex(
                    value.decode("ascii")
                )

                try:

                    cmap[src] = raw.decode(
                        "utf-16-be"
                    )

                except UnicodeDecodeError:

                    cmap[src] = raw.decode(
                        "latin-1",
                        errors="ignore"
                    )

    print(
        f"[PDF] ToUnicode CMap: "
        f"{len(cmap)} символов"
    )

    return cmap


def decode_pdf_cid_string(
    data,
    cmap
):
    """
    Декодирует CID/glyph string PDF
    через ToUnicode CMap.

    Например:

        <0115><0138><0139>

    превращается в Unicode-текст.
    """

    if not data or not cmap:
        return ""

    result = []

    # CID в нашем PDF двухбайтовый:
    #
    # 0115
    # 0138
    # 0139
    #
    # Поэтому читаем по 2 байта.

    if len(data) % 2:
        data = data[:-1]

    for i in range(
        0,
        len(data),
        2
    ):

        cid = int.from_bytes(
            data[i:i + 2],
            "big"
        )

        char = cmap.get(
            cid
        )

        if char is not None:
            result.append(char)

        else:
            # Неизвестный CID.
            # Не вставляем мусор.
            result.append("")

    return "".join(result)


def extract_pdf_hex_strings_with_cmap(
    data,
    cmap
):
    """
    Извлекает hex strings из TJ/Tj
    и декодирует их через ToUnicode.
    """

    if not data or not cmap:
        return []

    results = []

    for match in re.finditer(
        rb"<([0-9A-Fa-f\s]+)>",
        data
    ):

        raw = decode_pdf_hex_string(
            match.group(1)
        )

        if not raw:
            continue

        text = decode_pdf_cid_string(
            raw,
            cmap
        )

        if text:
            results.append(text)

    return results

async def find_pdf_tounicode(
    client,
    message,
    middle_offset,
    middle_size,
):
    """
    Ищет ToUnicode для шрифта F9.

    Сначала проверяем начало и конец PDF,
    где обычно находятся каталоги, страницы,
    xref и связанные структуры.

    Полный PDF не скачиваем.
    """

    file_size = message.document.size

    if not file_size:
        return {}

    # ========================================================
    # Области, которые проверяем
    # ========================================================

    windows = []

    # Начало PDF.
    windows.append(
        (
            0,
            min(
                1024 * 1024,
                file_size
            )
        )
    )

    # Конец PDF.
    tail_size = min(
        512 * 1024,
        file_size
    )

    windows.append(
        (
            max(
                0,
                file_size - tail_size
            ),
            tail_size
        )
    )

    # Область вокруг content stream.
    middle_window_size = 512 * 1024

    middle_offset_start = max(
        0,
        middle_offset
        - middle_window_size // 2
    )

    windows.append(
        (
            middle_offset_start,
            min(
                middle_window_size,
                file_size - middle_offset_start
            )
        )
    )

    checked = set()

    for offset, size in windows:

        key = (
            offset,
            size
        )

        if key in checked:
            continue

        checked.add(key)

        print(
            "[PDF] Ищу /F9 в области: "
            f"offset={offset:,}, "
            f"size={size:,}"
        )

        data = await download_part(
            client,
            message,
            offset,
            size
        )

        if not data:
            continue

        # ====================================================
        # Ищем именно ссылку на F9:
        #
        # /F9 123 0 R
        #
        # ====================================================

        matches = list(
            re.finditer(
                rb"/F9\s+(\d+)\s+0\s+R",
                data
            )
        )

        print(
            "[PDF] Ссылок /F9 найдено:",
            len(matches)
        )

        for match in matches[:3]:
            print(
                "[PDF DEBUG] F9 object:",
                int(match.group(1))
            )

        if not matches:
            continue

        for match in matches:

            font_object_number = int(
                match.group(1)
            )

            print(
                "[PDF] F9 object:",
                font_object_number
            )

            # =================================================
            # Ищем объект шрифта
            # =================================================

            object_pattern = (
                rb"\b"
                + str(
                    font_object_number
                ).encode()
                + rb"\s+0\s+obj\b"
            )

            object_match = re.search(
                object_pattern,
                data
            )

            if not object_match:

                print(
                    "[PDF] F9 object "
                    "не найден в этой области."
                )

                continue

            object_start = (
                object_match.start()
            )

            object_end = data.find(
                b"endobj",
                object_start
            )

            if object_end == -1:

                continue

            font_object = data[
                object_start:
                object_end
            ]

            print(
                "[PDF DEBUG] F9 OBJECT:"
            )

            print(
                font_object[:3000].decode(
                    "latin-1",
                    errors="replace"
                )
            )

            # =================================================
            # Ищем ToUnicode
            # =================================================

            tounicode_match = re.search(
                rb"/ToUnicode\s+(\d+)\s+0\s+R",
                font_object
            )

            if not tounicode_match:

                print(
                    "[PDF] У F9 нет /ToUnicode."
                )

                continue

            tounicode_object_number = int(
                tounicode_match.group(1)
            )

            print(
                "[PDF] ToUnicode object:",
                tounicode_object_number
            )

            # =================================================
            # Ищем объект ToUnicode
            # =================================================

            cmap_pattern = (
                rb"\b"
                + str(
                    tounicode_object_number
                ).encode()
                + rb"\s+0\s+obj\b"
            )

            cmap_match = re.search(
                cmap_pattern,
                data
            )

            if not cmap_match:

                print(
                    "[PDF] ToUnicode object "
                    "не найден в этой области."
                )

                continue

            cmap_start = (
                cmap_match.start()
            )

            cmap_end = data.find(
                b"endobj",
                cmap_start
            )

            if cmap_end == -1:

                continue

            cmap_object = data[
                cmap_start:
                cmap_end
            ]

            print(
                "[PDF DEBUG] TOUNICODE OBJECT:"
            )

            print(
                cmap_object[:3000].decode(
                    "latin-1",
                    errors="replace"
                )
            )

            # =================================================
            # stream
            # =================================================

            stream_pos = cmap_object.find(
                b"stream"
            )

            if stream_pos == -1:

                continue

            stream_start = (
                stream_pos
                + len(b"stream")
            )

            # Перевод строки после stream.

            if (
                stream_start + 1
                < len(cmap_object)
                and cmap_object[
                    stream_start:
                    stream_start + 2
                ] == b"\r\n"
            ):

                stream_start += 2

            elif (
                stream_start < len(cmap_object)
                and cmap_object[
                    stream_start:
                    stream_start + 1
                ] in (b"\n", b"\r")
            ):

                stream_start += 1

            stream_end = cmap_object.find(
                b"endstream",
                stream_start
            )

            if stream_end == -1:

                continue

            compressed = cmap_object[
                stream_start:
                stream_end
            ].rstrip(
                b"\r\n"
            )

            if not compressed:

                continue

            # =================================================
            # Распаковка
            # =================================================

            try:

                cmap_data = zlib.decompress(
                    compressed
                )

            except zlib.error:

                try:

                    cmap_data = zlib.decompress(
                        compressed,
                        -15
                    )

                except zlib.error as e:

                    print(
                        "[PDF] Ошибка распаковки "
                        "ToUnicode:",
                        e
                    )

                    continue

            # =================================================
            # CMap
            # =================================================

            cmap = parse_pdf_cmap(
                cmap_data
            )

            if cmap:

                print(
                    "[PDF] CMap успешно найден: "
                    f"{len(cmap)} отображений"
                )

                return cmap

    print(
        "[PDF] ToUnicode для F9 "
        "не найден в проверенных областях."
    )

    return {}

def extract_pdf_text_raw(
    data,
    allow_streams=True,
    max_streams=16
):
    """
    Извлекает текст из PDF-фрагмента.

    Важно:
    функция рассчитана на частично скачанный PDF.
    Никаких тяжёлых regex по бинарным данным.
    """

    pdf_cmap = getattr(extract_pdf_text_raw, "_cmap", None)

    if not data:
        return None

    print(
        f"[PDF DEBUG] extract_pdf_text_raw: "
        f"{len(data):,} байт"
    )

    f9_pos = data.find(b"/F9")

    if f9_pos != -1:
        print()
        print("=" * 60)
        print("[PDF DEBUG] F9 CONTEXT")
        print("=" * 60)

        print(
            data[
                max(0, f9_pos - 200):
                f9_pos + 500
            ].decode(
                "latin-1",
                errors="replace"
            )
        )

        print("=" * 60)

    chunks = []

    # ========================================================
    # Добавление текста
    # ========================================================

    def add_text(value):

        if value is None:
            return

        if isinstance(value, bytes):

            value = decode_pdf_text_bytes(
                value
            )

        if not isinstance(
            value,
            str
        ):

            value = str(value)

        value = clean_pdf_text(
            value
        )

        if value:
            chunks.append(value)

    # ========================================================
    # 1. Ищем Tj
    # ========================================================

    print("[PDF DEBUG] Ищу Tj...")

    # --------------------------------------------------------
    # Literal strings:
    #
    # (text) Tj
    #
    # Разбираем вручную, чтобы незакрытая скобка
    # в обрезанном PDF никогда не повесила regex.
    # --------------------------------------------------------

    i = 0
    data_len = len(data)

    while i < data_len:

        pos = data.find(
            b"Tj",
            i
        )

        if pos == -1:
            break

        # ----------------------------------------------------
        # Проверяем границу оператора:
        #
        # Tj
        # Tj\s
        # Tj]
        # и т.п.
        # ----------------------------------------------------

        after = pos + 2

        if (
            after < data_len
            and (
                65 <= data[after] <= 90
                or 97 <= data[after] <= 122
                or 48 <= data[after] <= 57
                or data[after] == 95
            )
        ):

            i = after
            continue

        # ----------------------------------------------------
        # Ищем непосредственно перед Tj.
        # ----------------------------------------------------

        before = pos - 1

        while (
            before >= 0
            and data[before] in b" \t\r\n"
        ):
            before -= 1

        # ----------------------------------------------------
        # Hex string:
        #
        # <48656C6C6F> Tj
        # ----------------------------------------------------

        if (
            before >= 0
            and data[before] == ord(">")
        ):

            start = data.rfind(
                b"<",
                0,
                before
            )

            if start != -1:

                raw = data[
                    start + 1:
                    before
                ]

                # Проверяем, что это действительно
                # hex string.
                if re.fullmatch(
                    rb"[0-9A-Fa-f\s]+",
                    raw
                ):

                    decoded = (
                        decode_pdf_hex_string(
                            raw
                        )
                    )

                    add_text(
                        decoded
                    )

        # ----------------------------------------------------
        # Literal string:
        #
        # (Hello) Tj
        #
        # Ищем ближайшую "(" назад.
        # ----------------------------------------------------

        elif (
            before >= 0
            and data[before] == ord(")")
        ):

            start = before
            depth = 1
            escaped = False

            j = before - 1

            while j >= 0:

                byte = data[j]

                if escaped:

                    escaped = False
                    j -= 1
                    continue

                if byte == 0x5C:

                    escaped = True
                    j -= 1
                    continue

                if byte == ord(")"):

                    depth += 1

                elif byte == ord("("):

                    depth -= 1

                    if depth == 0:

                        start = j

                        raw = data[
                            start + 1:
                            before
                        ]

                        decoded = (
                            decode_pdf_literal_string(
                                raw
                            )
                        )

                        add_text(
                            decoded
                        )

                        break

                j -= 1

        i = after

    # ========================================================
    # Проверяем обычный текст
    # ========================================================

    current_text = clean_pdf_text(
        " ".join(chunks)
    )

    current_words = re.findall(
        r"\S+",
        current_text
    )

    print(
        f"[PDF DEBUG] После Tj: "
        f"{len(current_words)} слов"
    )

    if len(current_words) >= MIN_WORDS:
        quality = pdf_text_quality(current_text)

        print(
            f"[PDF DEBUG] Качество текста: "
            f"{quality:.3f}"
        )

        if quality >= 0.65:
            return current_text

        print(
            "[PDF DEBUG] Текст похож на "
            "неправильно декодированный PDF. "
            "Продолжаю поиск."
        )

    # ========================================================
    # 2. TJ
    # ========================================================

    print("[PDF DEBUG] Ищу TJ...")

    # --------------------------------------------------------
    # Здесь тоже НЕ используем:
    #
    # [^\]]*
    #
    # на всём бинарном PDF.
    #
    # Ищем оператор TJ и разбираем небольшой участок
    # непосредственно перед ним.
    # --------------------------------------------------------

    search_pos = 0

    while search_pos < data_len:

        pos = data.find(
            b"TJ",
            search_pos
        )

        if pos == -1:
            break

        before = pos - 1

        while (
            before >= 0
            and data[before] in b" \t\r\n"
        ):
            before -= 1

        # Ожидаем ] перед TJ
        if (
            before >= 0
            and data[before] == ord("]")
        ):

            # Ограничиваем поиск назад.
            # Нам не нужен весь PDF.
            start_search = max(
                0,
                before - 65536
            )

            start = data.rfind(
                b"[",
                start_search,
                before
            )

            if start != -1:

                array_data = data[
                    start + 1:
                    before
                ]

                # Literal strings
                for raw in extract_pdf_literal_strings(
                    array_data
                ):

                    decoded = (
                        decode_pdf_literal_string(
                            raw
                        )
                    )

                    add_text(
                        decoded
                    )

                # Hex strings
                for match in re.finditer(
                        rb"<([0-9A-Fa-f\s]{2,65536})>",
                        array_data
                ):

                    raw = decode_pdf_hex_string(
                        match.group(1)
                    )

                    if pdf_cmap:
                        decoded = decode_pdf_cid_string(
                            raw,
                            pdf_cmap
                        )

                        if decoded:
                            add_text(decoded)
                            continue

                    # Если CMap нет — используем
                    # старый способ декодирования.
                    add_text(raw)

        search_pos = pos + 2

    # ========================================================
    # Проверяем TJ
    # ========================================================

    current_text = clean_pdf_text(
        " ".join(chunks)
    )

    current_words = re.findall(
        r"\S+",
        current_text
    )

    print(
        f"[PDF DEBUG] После TJ: "
        f"{len(current_words)} слов"
    )

    if len(current_words) >= MIN_WORDS:

        quality = pdf_text_quality(
            current_text
        )

        print(
            f"[PDF DEBUG] Качество текста после TJ: "
            f"{quality:.3f}"
        )

        if quality >= 0.65:
            return current_text

        print(
            "[PDF DEBUG] Текст после TJ похож "
            "на неправильно декодированный PDF. "
            "Продолжаю поиск."
        )

    # ========================================================
    # 3. FlateDecode
    # ========================================================

    if not allow_streams:
        return current_text or None

    print(
        "[PDF DEBUG] Ищу FlateDecode..."
    )

    flate_positions = []

    search_pos = 0

    while True:

        pos = data.find(
            b"/FlateDecode",
            search_pos
        )

        if pos == -1:
            break

        flate_positions.append(
            pos
        )

        search_pos = pos + 1

    print(
        f"[PDF] FlateDecode найдено: "
        f"{len(flate_positions)}"
    )

    stream_count = 0

    # ========================================================
    # Обрабатываем streams
    # ========================================================

    for flate_pos in flate_positions:

        if stream_count >= max_streams:
            break

        print()
        print("[PDF DEBUG] FlateDecode position:", flate_pos)

        obj_pos = data.rfind(
            b" obj",
            0,
            flate_pos
        )

        if obj_pos != -1:
            print(
                "[PDF DEBUG] Возможный PDF object:"
            )
            print(
                data[
                max(0, obj_pos - 100):
                flate_pos + 100
                ].decode(
                    "latin-1",
                    errors="replace"
                )
            )
        else:
            print(
                "[PDF DEBUG] Заголовок object "
                "в этом фрагменте не найден."
            )

        # ----------------------------------------------------
        # Ищем stream после /FlateDecode
        # ----------------------------------------------------

        stream_pos = data.find(
            b"stream",
            flate_pos
        )

        if stream_pos == -1:
            continue

        # Защита от поиска слишком далеко.
        if (
            stream_pos - flate_pos
            > 4096
        ):
            continue

        stream_start = (
            stream_pos
            + len(b"stream")
        )

        # ----------------------------------------------------
        # Перевод строки после stream
        # ----------------------------------------------------

        if (
            stream_start + 1 < data_len
            and data[
                stream_start:
                stream_start + 2
            ] == b"\r\n"
        ):

            stream_start += 2

        elif (
            stream_start < data_len
            and data[
                stream_start:
                stream_start + 1
            ] in (b"\n", b"\r")
        ):

            stream_start += 1

        # ----------------------------------------------------
        # Ищем endstream
        # ----------------------------------------------------

        stream_end = data.find(
            b"endstream",
            stream_start
        )

        if stream_end == -1:

            print(
                "[PDF] FlateDecode stream "
                "обрезан в середине фрагмента."
            )

            continue

        compressed = data[
            stream_start:
            stream_end
        ]

        compressed = compressed.rstrip(
            b"\r\n"
        )

        if not compressed:
            continue

        # ----------------------------------------------------
        # Распаковка
        # ----------------------------------------------------

        try:

            decompressed = zlib.decompress(
                compressed
            )

            print()
            print("=" * 60)
            print("[PDF DEBUG] НАЧАЛО РАСПАКОВАННОГО STREAM")
            print("=" * 60)

            print(
                decompressed[:3000].decode(
                    "latin-1",
                    errors="replace"
                )
            )

            print("=" * 60)
            print("[PDF DEBUG] КОНЕЦ ФРАГМЕНТА")
            print("=" * 60)
            print()

        except zlib.error:

            try:

                decompressed = zlib.decompress(
                    compressed,
                    -15
                )

                print()
                print("=" * 60)
                print("[PDF DEBUG] НАЧАЛО РАСПАКОВАННОГО STREAM")
                print("=" * 60)

                print(
                    decompressed[:3000].decode(
                        "latin-1",
                        errors="replace"
                    )
                )

                print("=" * 60)
                print("[PDF DEBUG] КОНЕЦ ФРАГМЕНТА")
                print("=" * 60)
                print()

            except zlib.error as e:

                print(
                    "[PDF] Ошибка распаковки:",
                    e
                )

                continue

        stream_count += 1

        print(
            "[PDF] FlateDecode: "
            f"{len(compressed):,} → "
            f"{len(decompressed):,} байт"
        )

        # ----------------------------------------------------
        # Разбираем распакованный content stream.
        # ----------------------------------------------------

        nested_text = extract_pdf_text_raw(
            decompressed,
            allow_streams=False
        )

        if nested_text:

            add_text(
                nested_text
            )

        current_text = clean_pdf_text(
            " ".join(chunks)
        )

        current_words = re.findall(
            r"\S+",
            current_text
        )

        if len(current_words) >= MIN_WORDS:
            break

    # ========================================================
    # Результат
    # ========================================================

    text = clean_pdf_text(
        " ".join(chunks)
    )

    if not text:
        return None

    return text


def make_pdf_result(text):
    """
    Получает из PDF-текста
    1000–1500 слов.
    """

    if not text:
        return None

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

    result = " ".join(
        words[:amount]
    )

    result = trim_to_sentences(
        result
    )

    if not result:
        return None

    final_words = re.findall(
        r"\S+",
        result
    )

    # Если обрезание по предложениям
    # выбросило слишком много текста,
    # возвращаем исходные 1000–1500 слов.
    if len(final_words) < MIN_WORDS:

        result = " ".join(
            words[:amount]
        )

    final_words = re.findall(
        r"\S+",
        result
    )

    if len(final_words) < MIN_WORDS:

        return None

    return result


async def get_pdf_middle_text(
    client,
    message
):
    """
    Извлекает фрагмент PDF
    с минимальным скачиванием.

    Алгоритм:

    1. Проверяем середину PDF.
    2. Если текста недостаточно —
       проверяем начало.
    3. Полный PDF никогда не скачиваем.

    Для PDF со сканом или неподдерживаемым
    Font Encoding возвращается None.
    """

    file_size = message.document.size

    if not file_size:
        return None

    extract_pdf_text_raw._cmap = None

    # ========================================================
    # 1. СЕРЕДИНА PDF
    # ========================================================

    middle_amount = min(
        PDF_MIDDLE_CHUNK_SIZE,
        file_size
    )

    middle_offset = max(
        0,
        file_size // 2
        - middle_amount // 2
    )

    print(
        "[PDF] Проверяю середину..."
    )

    print(
        f"[PDF] offset={middle_offset:,} "
        f"size={middle_amount:,}"
    )

    middle_data = await download_part(
        client,
        message,
        middle_offset,
        middle_amount
    )

    # ========================================================
    # Ищем ToUnicode для F9
    # ========================================================

    pdf_cmap = await find_pdf_tounicode(
        client,
        message,
        middle_offset,
        middle_amount
    )

    if pdf_cmap:

        print(
            f"[PDF] CMap найден: "
            f"{len(pdf_cmap)} отображений"
        )

    else:

        print(
            "[PDF] CMap для F9 не найден."
        )

    # Передаём CMap в parser.
    extract_pdf_text_raw._cmap = pdf_cmap

    middle_text = extract_pdf_text_raw(
        middle_data
    )

    if middle_text:

        middle_words = re.findall(
            r"\S+",
            middle_text
        )

        quality = pdf_text_quality(
            middle_text
        )

        print(
            "[PDF] В середине найдено "
            f"{len(middle_words)} слов"
        )

        print(
            f"[PDF] Качество текста: "
            f"{quality:.3f}"
        )

        if quality >= 0.65:

            result = make_pdf_result(
                middle_text
            )

            if result:
                print(
                    "[PDF] Текст получен "
                    "из середины."
                )

                return result

        else:

            print(
                "[PDF] Текст из середины "
                "отброшен из-за низкого качества."
            )

    # ========================================================
    # 2. НАЧАЛО PDF
    # ========================================================

    start_amount = min(
        PDF_START_CHUNK_SIZE,
        file_size
    )

    print(
        "[PDF] В середине недостаточно "
        "текста. Проверяю начало..."
    )

    print(
        f"[PDF] offset=0 "
        f"size={start_amount:,}"
    )

    start_data = await download_part(
        client,
        message,
        0,
        start_amount
    )

    start_text = extract_pdf_text_raw(
        start_data
    )

    if start_text:

        start_words = re.findall(
            r"\S+",
            start_text
        )

        print(
            "[PDF] В начале найдено "
            f"{len(start_words)} слов"
        )

        result = make_pdf_result(
            start_text
        )

        if result:

            print(
                "[PDF] Текст получен "
                "из начала."
            )

            return result

    # ========================================================
    # 3. ОТКАЗ
    # ========================================================

    print(
        "[PDF] Не удалось извлечь "
        "1000–1500 слов частично."
    )

    print(
        "[PDF] Возможно, это скан, "
        "изображения или PDF "
        "с неподдерживаемым "
        "Font Encoding."
    )

    return None