"""Generate the BACnet MQTT Gateway store icon and logo without dependencies."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


BLUE = (3, 169, 244, 255)
NAVY = (15, 48, 72, 255)
WHITE = (255, 255, 255, 255)


def png(path: Path, width: int, height: int, pixels: bytearray) -> None:
    raw = bytearray()
    for row in range(height):
        raw.append(0)
        raw.extend(pixels[row * width * 4 : (row + 1) * width * 4])

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    data = b"\x89PNG\r\n\x1a\n"
    data += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    data += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    data += chunk(b"IEND", b"")
    path.write_bytes(data)


def canvas(width: int, height: int, color: tuple[int, int, int, int]) -> bytearray:
    return bytearray(color * (width * height))


def rect(buf: bytearray, width: int, x0: int, y0: int, x1: int, y1: int, color) -> None:
    for y in range(max(0, y0), min(y1, len(buf) // (width * 4))):
        for x in range(max(0, x0), min(x1, width)):
            at = (y * width + x) * 4
            buf[at : at + 4] = bytes(color)


def circle(buf: bytearray, width: int, cx: int, cy: int, radius: int, color) -> None:
    for y in range(cy - radius, cy + radius + 1):
        for x in range(cx - radius, cx + radius + 1):
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius**2:
                if 0 <= x < width and 0 <= y < len(buf) // (width * 4):
                    at = (y * width + x) * 4
                    buf[at : at + 4] = bytes(color)


def draw_mark(buf: bytearray, width: int, height: int, scale: float = 1.0, ox: int = 0, oy: int = 0) -> None:
    def p(value: float) -> int:
        return round(value * scale)

    # BACnet/IP network motif: a gateway in the center, with three connected nodes.
    cx, cy = ox + p(64), oy + p(64)
    for nx, ny in ((28, 32), (100, 32), (64, 101)):
        nx, ny = ox + p(nx), oy + p(ny)
        steps = max(abs(nx - cx), abs(ny - cy))
        for step in range(steps + 1):
            x = cx + (nx - cx) * step // max(1, steps)
            y = cy + (ny - cy) * step // max(1, steps)
            rect(buf, width, x - p(2), y - p(2), x + p(3), y + p(3), WHITE)
        circle(buf, width, nx, ny, p(11), WHITE)
    rect(buf, width, cx - p(18), cy - p(18), cx + p(19), cy + p(19), WHITE)
    rect(buf, width, cx - p(10), cy - p(10), cx + p(11), cy + p(11), BLUE)


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "bacnet_mqtt_gateway"
    icon = canvas(128, 128, BLUE)
    draw_mark(icon, 128, 128)
    png(root / "icon.png", 128, 128, icon)

    logo = canvas(250, 100, NAVY)
    draw_mark(logo, 250, 100, scale=0.62, ox=12, oy=10)
    # The wordmark is intentionally rendered as simple block glyphs so the asset
    # remains deterministic and does not depend on a host-installed font.
    for x, w in ((103, 8), (117, 8), (131, 8), (145, 8), (159, 8), (173, 8)):
        rect(logo, 250, x, 35, x + w, 66, WHITE)
    rect(logo, 250, 103, 35, 187, 42, WHITE)
    rect(logo, 250, 103, 59, 187, 66, WHITE)
    png(root / "logo.png", 250, 100, logo)


if __name__ == "__main__":
    main()
