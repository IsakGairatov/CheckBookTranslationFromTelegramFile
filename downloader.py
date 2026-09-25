async def download_part(
    client,
    message,
    offset,
    limit
):
    """
    Скачивает только указанный участок Telegram-файла.
    Весь файл НЕ скачивается.
    """

    if limit <= 0:
        return b""

    chunk_size = 32 * 1024

    data = bytearray()
    downloaded = 0

    stream = client.iter_download(
        message.document,
        offset=offset,
        chunk_size=chunk_size,
        request_size=chunk_size
    )

    async for chunk in stream:

        remaining = limit - downloaded

        if remaining <= 0:
            break

        chunk = chunk[:remaining]

        data.extend(chunk)

        downloaded += len(chunk)

        if downloaded >= limit:
            break

    print(
        f"[DOWNLOAD] offset={offset} "
        f"requested={limit} "
        f"actual={len(data)}"
    )

    return bytes(data)