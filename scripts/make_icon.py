"""A paper square with one short rule. Enough for a home-screen icon."""

import struct
import zlib
from pathlib import Path

PAPER = (243, 240, 232, 255)
INK = (28, 27, 25, 255)


def write_png(path: Path, size: int) -> None:
    row = bytearray()
    rows = []
    bar_top = int(size * 0.62)
    bar_height = max(2, size // 64)
    bar_left = int(size * 0.28)
    bar_right = int(size * 0.72)
    for y in range(size):
        row = bytearray(b"\x00")
        for x in range(size):
            ink = bar_top <= y < bar_top + bar_height and bar_left <= x < bar_right
            row.extend(INK if ink else PAPER)
        rows.append(bytes(row))
    raw = b"".join(rows)
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.write_bytes(png)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1] / "static"
    root.mkdir(parents=True, exist_ok=True)
    write_png(root / "icon-180.png", 180)
    write_png(root / "icon-512.png", 512)
