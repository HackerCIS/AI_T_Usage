"""Headroom's icon: four usage bars under one ceiling, the gap above them is what is left.

Writes the home-screen PNGs in static/ and mac/AppIcon.icns. Standard library only.
"""

import math
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TOP = (43, 41, 37)
BOTTOM = (22, 21, 19)
PAPER = (243, 240, 232)
CEILING = (242, 181, 68)

# In tile units, 0..1. Bars sit on one floor; the ceiling line is the plan's limit.
LEFT, RIGHT = 0.20, 0.80
FLOOR, TRACK_TOP = 0.78, 0.31
CEIL_Y, CEIL_H = 0.235, 0.024
BAR_W = 0.105
USED = (0.62, 0.86, 0.45, 0.72)


def rrect_sdf(px, py, x0, y0, x1, y1, r):
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    qx = abs(px - cx) - ((x1 - x0) / 2 - r)
    qy = abs(py - cy) - ((y1 - y0) / 2 - r)
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    return outside + min(max(qx, qy), 0.0) - r


class Canvas:
    def __init__(self, size):
        self.size = size
        self.px = [[0.0, 0.0, 0.0, 0.0] for _ in range(size * size)]

    def fill(self, box, radius, color, alpha=1.0):
        """Anti-aliased rounded rect. box and radius are in pixels; color may be a function of y."""
        x0, y0, x1, y1 = box
        lo_x, hi_x = max(0, int(x0) - 1), min(self.size, int(math.ceil(x1)) + 1)
        lo_y, hi_y = max(0, int(y0) - 1), min(self.size, int(math.ceil(y1)) + 1)
        for y in range(lo_y, hi_y):
            rgb = color(y) if callable(color) else color
            for x in range(lo_x, hi_x):
                d = rrect_sdf(x + 0.5, y + 0.5, x0, y0, x1, y1, radius)
                a = min(1.0, max(0.0, 0.5 - d)) * alpha
                if a <= 0:
                    continue
                p = self.px[y * self.size + x]
                out = a + p[3] * (1 - a)
                for i in range(3):
                    p[i] = (rgb[i] * a + p[i] * p[3] * (1 - a)) / out
                p[3] = out

    def png(self) -> bytes:
        rows = []
        for y in range(self.size):
            row = bytearray(b"\x00")
            for p in self.px[y * self.size:(y + 1) * self.size]:
                row.extend(round(v) for v in p[:3])
                row.append(round(p[3] * 255))
            rows.append(bytes(row))

        def chunk(tag: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

        ihdr = struct.pack(">IIBBBBB", self.size, self.size, 8, 6, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def render(size: int, full_bleed: bool) -> bytes:
    # macOS icons leave a margin and round their own corners; iOS masks a full square itself.
    inset = 0.0 if full_bleed else size * 100 / 1024
    tile = size - 2 * inset
    corner = 0.0 if full_bleed else tile * 0.225
    c = Canvas(size)

    def at(u0, v0, u1, v1):
        return (inset + u0 * tile, inset + v0 * tile, inset + u1 * tile, inset + v1 * tile)

    def gradient(y):
        t = min(1.0, max(0.0, (y - inset) / tile))
        return tuple(a + (b - a) * t for a, b in zip(TOP, BOTTOM))

    c.fill(at(0, 0, 1, 1), corner, gradient)
    gap = (RIGHT - LEFT - 4 * BAR_W) / 3
    round_px = BAR_W * tile * 0.32
    for i, used in enumerate(USED):
        u0 = LEFT + i * (BAR_W + gap)
        c.fill(at(u0, TRACK_TOP, u0 + BAR_W, FLOOR), round_px, PAPER, 0.10)
        top = FLOOR - used * (FLOOR - TRACK_TOP)
        c.fill(at(u0, top, u0 + BAR_W, FLOOR), round_px, PAPER)
    c.fill(at(LEFT, CEIL_Y, RIGHT, CEIL_Y + CEIL_H), CEIL_H * tile / 2, CEILING)
    return c.png()


def write_icns(path: Path) -> None:
    names = {16: ["16x16"], 32: ["16x16@2x", "32x32"], 64: ["32x32@2x"], 128: ["128x128"],
             256: ["128x128@2x", "256x256"], 512: ["256x256@2x", "512x512"], 1024: ["512x512@2x"]}
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()
        for size, labels in names.items():
            data = render(size, full_bleed=False)
            for label in labels:
                (iconset / f"icon_{label}.png").write_bytes(data)
        if shutil.which("iconutil") is None:
            raise SystemExit("iconutil not found; AppIcon.icns needs macOS")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(path)], check=True)


if __name__ == "__main__":
    static = ROOT / "static"
    static.mkdir(parents=True, exist_ok=True)
    (static / "icon-180.png").write_bytes(render(180, full_bleed=True))
    (static / "icon-512.png").write_bytes(render(512, full_bleed=True))
    write_icns(ROOT / "mac" / "AppIcon.icns")
