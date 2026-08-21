#!/usr/bin/env python3
"""Generate icon.png and logo.png for the HA Docs add-on.

The Supervisor reads these two images from the add-on folder in the cloned
repository, not from the built image, so regenerating them needs no version bump
and no image rebuild - only a push and an add-on store reload.

Written without Pillow on purpose. This box has no Pillow installed, and the
add-on already vendors or hand-rolls rather than taking dependencies (see the
Mermaid notes in ha_docs/Dockerfile). Everything below is stdlib: a scanline
polygon filler at 4x supersample for the antialiasing, and a minimal PNG encoder
built on zlib.

Run from the repository root:

    python scripts/gen_icon.py
"""

import math
import struct
import zlib

# Home Assistant blue, so the store tile and the mdi:book-open-variant-outline
# panel icon in config.yaml read as the same product.
BLUE = (3, 169, 244)
WHITE = (255, 255, 255)

# Every shape is described in a 128x128 design space and scaled to whatever the
# output size is, so icon.png and logo.png can share one set of coordinates.
DESIGN = 128.0

# Samples per axis. 4 means 16 samples per output pixel, which is enough to keep
# the rounded corners and the tilted page edges clean at 128px.
SS = 4


class Raster:
    """RGBA canvas with even-odd polygon fill and box downsampling."""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.buf = bytearray(width * height * 4)

    def fill(self, contours, color):
        """Fill one path opaquely.

        Multiple contours use the even-odd rule, which is what makes a counter -
        the hole in a D or an o - come out as a hole, rather than needing a
        second colour painted back over it afterwards.
        """
        edges = []
        min_y = float(self.height)
        max_y = 0.0
        for contour in contours:
            count = len(contour)
            for i in range(count):
                x0, y0 = contour[i]
                x1, y1 = contour[(i + 1) % count]
                if y0 == y1:
                    continue  # horizontal edges contribute no crossings
                edges.append((x0, y0, x1, y1))
                min_y = min(min_y, y0, y1)
                max_y = max(max_y, y0, y1)
        if not edges:
            return

        red, green, blue = color
        top = max(0, int(min_y))
        bottom = min(self.height - 1, int(max_y) + 1)

        for y in range(top, bottom + 1):
            sample_y = y + 0.5
            crossings = []
            for x0, y0, x1, y1 in edges:
                # Half-open test, so a vertex shared by two edges is counted
                # once and the fill cannot leak along that scanline.
                if (y0 <= sample_y < y1) or (y1 <= sample_y < y0):
                    crossings.append(x0 + (sample_y - y0) * (x1 - x0) / (y1 - y0))
            if not crossings:
                continue
            crossings.sort()
            for i in range(0, len(crossings) - 1, 2):
                start = max(0, int(crossings[i] + 0.5))
                end = min(self.width, int(crossings[i + 1] + 0.5))
                for x in range(start, end):
                    at = (y * self.width + x) * 4
                    self.buf[at] = red
                    self.buf[at + 1] = green
                    self.buf[at + 2] = blue
                    self.buf[at + 3] = 255

    def downsample(self, factor):
        out = Raster(self.width // factor, self.height // factor)
        area = factor * factor
        for y in range(out.height):
            for x in range(out.width):
                sum_r = sum_g = sum_b = sum_a = 0
                for dy in range(factor):
                    row = (y * factor + dy) * self.width
                    for dx in range(factor):
                        at = (row + x * factor + dx) * 4
                        # Weight colour by coverage, so a transparent edge sample
                        # cannot drag the average toward black.
                        a = self.buf[at + 3]
                        sum_r += self.buf[at] * a
                        sum_g += self.buf[at + 1] * a
                        sum_b += self.buf[at + 2] * a
                        sum_a += a
                at = (y * out.width + x) * 4
                if sum_a:
                    out.buf[at] = sum_r // sum_a
                    out.buf[at + 1] = sum_g // sum_a
                    out.buf[at + 2] = sum_b // sum_a
                    out.buf[at + 3] = sum_a // area
        return out

    def write_png(self, path):
        raw = bytearray()
        stride = self.width * 4
        for y in range(self.height):
            raw.append(0)  # filter type 0 (None); these images are tiny
            raw += self.buf[y * stride:(y + 1) * stride]

        def chunk(tag, data):
            body = tag + data
            return (
                struct.pack(">I", len(data))
                + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
            )

        png = b"\x89PNG\r\n\x1a\n"
        png += chunk(
            b"IHDR", struct.pack(">IIBBBBB", self.width, self.height, 8, 6, 0, 0, 0)
        )
        png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        png += chunk(b"IEND", b"")
        with open(path, "wb") as handle:
            handle.write(png)


# ---------------------------------------------------------------------------
# Shapes, all in 128-unit design space
# ---------------------------------------------------------------------------


def rounded_rect(x0, y0, x1, y1, radius, steps=16):
    points = []
    corners = [
        (x1 - radius, y1 - radius, 0.0),
        (x0 + radius, y1 - radius, 90.0),
        (x0 + radius, y0 + radius, 180.0),
        (x1 - radius, y0 + radius, 270.0),
    ]
    for cx, cy, start in corners:
        for i in range(steps + 1):
            angle = math.radians(start + 90.0 * i / steps)
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points


# The open book. Each page is a quadrilateral that lifts toward its outer edge,
# which is what reads as "open" rather than as a flat rectangle.
SPINE_X = 64.0
GAP = 2.4            # half the blue channel left down the middle
PAGE_TOP = 46.0      # top of the page at the spine
PAGE_BOTTOM = 91.0   # bottom of the page at the spine
RISE = 9.0           # how much the outer edge lifts
OUTER = 47.0         # page width


def page(side):
    """side is -1 for the left page, +1 for the right."""
    inner_x = SPINE_X + side * GAP
    outer_x = inner_x + side * OUTER
    return [
        (inner_x, PAGE_TOP),
        (outer_x, PAGE_TOP - RISE),
        (outer_x, PAGE_BOTTOM - RISE),
        (inner_x, PAGE_BOTTOM),
    ]


def rule_line(side, fraction, thickness=3.4, inset=0.17):
    """A line of 'text' on a page, following that page's tilt."""
    inner_x = SPINE_X + side * GAP
    ends = []
    for u in (inset, 1.0 - inset):
        x = inner_x + side * OUTER * u
        y = (PAGE_TOP - RISE * u) + fraction * (PAGE_BOTTOM - PAGE_TOP)
        ends.append((x, y))
    (x0, y0), (x1, y1) = ends
    half = thickness / 2.0
    return [(x0, y0 - half), (x1, y1 - half), (x1, y1 + half), (x0, y0 + half)]


def draw_mark(raster, scale, offset_x=0.0, offset_y=0.0, tile=True):
    def place(points):
        return [(x * scale + offset_x, y * scale + offset_y) for x, y in points]

    if tile:
        raster.fill([place(rounded_rect(0, 0, DESIGN, DESIGN, 27))], BLUE)

    for side in (-1, 1):
        raster.fill([place(page(side))], WHITE)
        for fraction in (0.30, 0.50, 0.70):
            raster.fill([place(rule_line(side, fraction))], BLUE)


# ---------------------------------------------------------------------------
# A six-glyph vector font
#
# logo.png wants the words "HA DOCS" beside the mark, and there is no font
# renderer here for the same reason there is no Pillow. Only these six letters
# are ever needed, so they are described directly as filled outlines in an em
# space with the cap height at 100 units and the baseline at y=100.
#
# Each glyph is a list of shapes, and each shape is a list of contours filled in
# one pass. Contours within a shape use the even-odd rule, which is what hollows
# out the O and the D. Shapes that overlap - the three strokes of an A - have to
# stay separate, because even-odd would cancel them where they cross.
# ---------------------------------------------------------------------------

STROKE = 17.0


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def arc_ribbon(cx, cy, rx_out, ry_out, rx_in, ry_in, start_deg, end_deg, steps=40):
    """One contour: out along the outer arc, back along the inner one.

    Angles are in screen orientation (y grows downward), so 0 is right, 90 is
    down, 180 is left. Sweeping from start to end may go either way; the sign of
    the difference decides.
    """
    outer = []
    inner = []
    for i in range(steps + 1):
        t = start_deg + (end_deg - start_deg) * i / steps
        a = math.radians(t)
        outer.append((cx + rx_out * math.cos(a), cy + ry_out * math.sin(a)))
        inner.append((cx + rx_in * math.cos(a), cy + ry_in * math.sin(a)))
    inner.reverse()
    return outer + inner


def _glyph_H():
    return [[_rect(0, 0, STROKE, 100)],
            [_rect(55, 0, 55 + STROKE, 100)],
            [_rect(STROKE, 41.5, 55, 58.5)]]


def _glyph_A():
    return [[[(0, 100), (28, 0), (28 + STROKE, 0), (STROKE, 100)]],
            [[(43 - STROKE, 0), (43, 0), (71, 100), (71 - STROKE, 100)]],
            [_rect(16, 60, 55, 75)]]


def _glyph_D():
    return [[_rect(0, 0, STROKE, 100)],
            [arc_ribbon(STROKE, 50, 57, 50, 57 - STROKE, 50 - STROKE, -90, 90)]]


def _glyph_O():
    return [[ellipse(38, 50, 38, 50), ellipse(38, 50, 38 - STROKE, 50 - STROKE)]]


def _glyph_C():
    return [[arc_ribbon(38, 50, 38, 50, 38 - STROKE, 50 - STROKE, 58, 302)]]


def _glyph_S():
    # Traced the way the stroke is written: start upper-right, sweep left over
    # the top and down the left side to the waist, then out right, down the right
    # side and back left along the bottom. Two 225-degree arcs on circles that
    # overlap at the waist, which is what joins them.
    top = arc_ribbon(34, 27, 34, 27, 34 - STROKE, 27 - STROKE, 315, 90)
    bottom = arc_ribbon(34, 73, 34, 27, 34 - STROKE, 27 - STROKE, 270, 495)
    return [[top], [bottom]]


GLYPHS = {
    "H": (72.0, _glyph_H),
    "A": (71.0, _glyph_A),
    "D": (74.0, _glyph_D),
    "O": (76.0, _glyph_O),
    "C": (76.0, _glyph_C),
    "S": (68.0, _glyph_S),
    " ": (34.0, lambda: []),
}

TRACKING = 12.0


def text_width(text):
    total = 0.0
    for ch in text:
        total += GLYPHS[ch][0] + TRACKING
    return total - TRACKING if text else 0.0


def draw_text(raster, text, x, baseline, size, color):
    """Draw `text` with its cap height equal to `size`, in device pixels."""
    unit = size / 100.0
    pen = x
    for ch in text:
        advance, builder = GLYPHS[ch]
        for shape in builder():
            placed = [
                [(pen + px * unit, baseline - (100 - py) * unit) for px, py in contour]
                for contour in shape
            ]
            raster.fill(placed, color)
        pen += (advance + TRACKING) * unit


def ellipse(cx, cy, rx, ry, steps=56):
    return [
        (cx + rx * math.cos(2 * math.pi * i / steps),
         cy + ry * math.sin(2 * math.pi * i / steps))
        for i in range(steps)
    ]


def mark_bounds():
    """Bounding box of the book itself, which is not the bounding box of the
    tile it sits on. Sizing the mark by the tile makes it come out far too small
    next to the wordmark."""
    xs = []
    ys = []
    for side in (-1, 1):
        for x, y in page(side):
            xs.append(x)
            ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


def build_logo(path, width=250, height=100):
    """The mark and the wordmark on one blue field.

    Filled rather than transparent on purpose: the add-on page renders this over
    a background that follows the Home Assistant theme, and a white mark on
    transparent would disappear in light mode.
    """
    raster = Raster(width * SS, height * SS)
    raster.fill([rounded_rect(0, 0, width * SS, height * SS, 18 * SS)], BLUE)

    x0, y0, x1, y1 = mark_bounds()
    mark_width = 74.0
    scale = mark_width * SS / (x1 - x0)
    mark_height = (y1 - y0) * scale

    cap = 26.0
    gap = 16.0
    words = "HA DOCS"
    text_px = text_width(words) * cap / 100.0

    # Centre the mark and the wordmark as one group.
    left = (width * SS - (mark_width * SS + gap * SS + text_px * SS)) / 2.0

    draw_mark(raster, scale,
              offset_x=left - x0 * scale,
              offset_y=(height * SS - mark_height) / 2.0 - y0 * scale,
              tile=False)

    draw_text(raster, words,
              left + (mark_width + gap) * SS,
              (height / 2.0 + cap / 2.0) * SS,
              cap * SS, WHITE)

    raster.downsample(SS).write_png(path)
    print("wrote {} ({}x{})".format(path, width, height))


def build_icon(path, size=128):
    raster = Raster(size * SS, size * SS)
    draw_mark(raster, size * SS / DESIGN)
    raster.downsample(SS).write_png(path)
    print("wrote {} ({}x{})".format(path, size, size))


if __name__ == "__main__":
    build_icon("ha_docs/icon.png", 128)
    build_logo("ha_docs/logo.png", 250, 100)
