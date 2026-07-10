from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Tuple


WIDTH = 256
HEIGHT = 256


def lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def set_pixel(buf: bytearray, x: int, y: int, color: Tuple[int, int, int, int]) -> None:
    if x < 0 or y < 0 or x >= WIDTH or y >= HEIGHT:
        return
    idx = (y * WIDTH + x) * 4
    buf[idx : idx + 4] = bytes(color)


def fill_rect(buf: bytearray, x0: int, y0: int, x1: int, y1: int, color: Tuple[int, int, int, int]) -> None:
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(WIDTH, x1)
    y1 = min(HEIGHT, y1)
    for y in range(y0, y1):
        row = (y * WIDTH + x0) * 4
        for _ in range(x0, x1):
            buf[row : row + 4] = bytes(color)
            row += 4


def point_in_triangle(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
    cx: float,
    cy: float,
) -> bool:
    def sign(x1: float, y1: float, x2: float, y2: float, x3: float, y3: float) -> float:
        return (x1 - x3) * (y2 - y3) - (x2 - x3) * (y1 - y3)

    b1 = sign(px, py, ax, ay, bx, by) < 0.0
    b2 = sign(px, py, bx, by, cx, cy) < 0.0
    b3 = sign(px, py, cx, cy, ax, ay) < 0.0
    return (b1 == b2) and (b2 == b3)


def fill_triangle(
    buf: bytearray,
    ax: int,
    ay: int,
    bx: int,
    by: int,
    cx: int,
    cy: int,
    color: Tuple[int, int, int, int],
) -> None:
    min_x = max(min(ax, bx, cx), 0)
    max_x = min(max(ax, bx, cx), WIDTH - 1)
    min_y = max(min(ay, by, cy), 0)
    max_y = min(max(ay, by, cy), HEIGHT - 1)
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            if point_in_triangle(x + 0.5, y + 0.5, ax, ay, bx, by, cx, cy):
                set_pixel(buf, x, y, color)


def build_png(buf: bytearray, width: int, height: int) -> bytes:
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        start = y * stride
        raw.extend(buf[start : start + stride])

    compressor = zlib.compressobj(level=9)
    compressed = compressor.compress(bytes(raw)) + compressor.flush()

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        length = struct.pack(">I", len(data))
        crc = struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
        return length + chunk_type + data + crc

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", header),
            chunk(b"IDAT", compressed),
            chunk(b"IEND", b""),
        ]
    )


def build_icon(png_data: bytes) -> bytes:
    header = struct.pack("<HHH", 0, 1, 1)
    width = 0  # 0 means 256
    height = 0
    entry = struct.pack(
        "<BBBBHHII",
        width,
        height,
        0,
        0,
        1,
        32,
        len(png_data),
        6 + 16,
    )
    return header + entry + png_data


def main() -> None:
    buf = bytearray(WIDTH * HEIGHT * 4)

    bg_top = (26, 30, 38, 255)
    bg_bottom = (44, 52, 64, 255)
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        row_color = (
            lerp(bg_top[0], bg_bottom[0], t),
            lerp(bg_top[1], bg_bottom[1], t),
            lerp(bg_top[2], bg_bottom[2], t),
            255,
        )
        for x in range(WIDTH):
            set_pixel(buf, x, y, row_color)

    shadow = (18, 22, 28, 255)
    card = (72, 84, 102, 255)
    card_highlight = (98, 114, 138, 255)
    fill_rect(buf, 40, 34, 40 + 92, 34 + 120, shadow)
    fill_rect(buf, 36, 30, 36 + 92, 30 + 120, card)
    fill_rect(buf, 44, 40, 44 + 64, 40 + 10, card_highlight)
    fill_rect(buf, 36 + 92 - 18, 30, 36 + 92, 30 + 24, bg_top)

    folder_shadow = (198, 129, 18, 255)
    folder = (243, 176, 40, 255)
    folder_tab = (250, 202, 96, 255)
    folder_highlight = (255, 214, 120, 255)
    fill_rect(buf, 96, 146, 96 + 132, 146 + 70, folder_shadow)
    fill_rect(buf, 92, 140, 92 + 132, 140 + 70, folder)
    fill_rect(buf, 110, 122, 110 + 58, 122 + 18, folder_tab)
    fill_rect(buf, 92, 140, 92 + 132, 140 + 10, folder_highlight)

    arrow = (90, 214, 222, 255)
    fill_rect(buf, 142, 86, 142 + 16, 86 + 36, arrow)
    fill_triangle(buf, 126, 122, 174, 122, 150, 150, arrow)

    png_data = build_png(buf, WIDTH, HEIGHT)
    base_dir = Path(__file__).resolve().parents[1]
    png_path = base_dir / "app_icon.png"
    ico_path = base_dir / "app_icon.ico"
    png_path.write_bytes(png_data)
    ico_path.write_bytes(build_icon(png_data))


if __name__ == "__main__":
    main()
