"""Bounded container validation without decoding, probing, or transcoding media."""

from collections.abc import AsyncIterator


async def mp4_stream(chunks: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    header = bytearray()
    checked = False
    async for chunk in chunks:
        if not checked:
            needed = max(0, 12 - len(header))
            header.extend(chunk[:needed])
            rest = chunk[needed:]
            if len(header) < 12:
                continue
            if header[4:8] != b"ftyp":
                raise ValueError("Provider output is not an MP4 container")
            checked = True
            yield bytes(header)
            if rest:
                yield rest
        else:
            yield chunk
    if not checked:
        raise ValueError("Provider output is incomplete")
