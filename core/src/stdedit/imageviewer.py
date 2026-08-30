"""
imageviewer.py — in-terminal image viewer for stdedit.

Stdlib only (zlib/struct/base64). Two display paths:

* Decode-and-render: PNG / BMP / PPM-PGM-PBM are decoded in pure Python and
  drawn inside curses as half-block (upper-half block) pixels using lazily
  allocated color pairs. Works on any 256-colour terminal.

* Passthrough: every other format (JPEG, GIF, WebP, HEIC, SVG, ...) is handed
  to the terminal's native decoder through the Kitty / iTerm2 inline-image
  protocol (the terminal renders the raw bytes itself). This is what makes
  "any format" work.

Decoders and image maths are import-free of curses so the whole module can be
unit-tested headless. curses is imported lazily inside the drawing functions.
"""

from __future__ import annotations

import base64
import os
import struct
import zlib

from typing import Optional

# ---- format detection ---------------------------------------------------

_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_JPEG_SIG = b"\xff\xd8\xff"
_GIF_SIG = b"GIF8"
_TIFF_SIG = (b"II*\x00", b"MM\x00*")
_ICO_SIG = b"\x00\x00\x01\x00"

_BRANDS = {
    b"heic": "heic",
    b"heix": "heic",
    b"heif": "heif",
    b"mif1": "heif",
    b"avif": "avif",
    b"avis": "avif",
}


def detect_format(data: bytes) -> Optional[str]:
    """Sniff an image format from raw start-of-file bytes.

    Accepts bytes; returns a canonical format name or None.
    """
    if data.startswith(_PNG_SIG):
        return "png"
    if data.startswith(_JPEG_SIG):
        return "jpeg"
    if data.startswith(_GIF_SIG):
        return "gif"
    if data.startswith(_TIFF_SIG):
        return "tiff"
    if data.startswith(_ICO_SIG):
        return "ico"
    if len(data) >= 2 and data[0] == ord("B") and data[1] == ord("M"):
        return "bmp"
    if len(data) >= 2 and data[0] == ord("P") and data[1] in b"123456":
        return "ppm"
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if len(data) >= 16 and data[4:8] == b"ftyp":
        brand = _BRANDS.get(data[8:12])
        if brand:
            return brand
        return "isobmff"
    head = data.lstrip(b" \t\r\n")
    if head.startswith((b"<?xml", b"<svg")) or b"<svg" in data[:512]:
        return "svg"
    return None


def detect_format_path(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            data = f.read(512)
    except OSError:
        return None
    return detect_format(data)


# ---- PNG decoder --------------------------------------------------------




def _png_is_palette(code: int) -> bool:
    return code == 3


def _png_channels(code: int) -> int:
    return {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[code]


def _png_parse_chunks(data: bytes):
    pos = 8
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        ctype = data[pos + 4 : pos + 8]
        raw = data[pos + 8 : pos + 8 + length]
        yield ctype, raw
        pos += 12 + length
        if ctype == b"IEND":
            return


def _png_scaled_to_rgb(val: int, maxval: int) -> tuple:
    """Expand a grayscale value to (r, g, b)."""
    if maxval == 255:
        return (val, val, val)
    v = round(val * 255 / maxval)
    return (v, v, v)


def decode_png(data: bytes) -> tuple:
    """Decode a PNG into (width, height, pixels).

    pixels is a flat list of (r, g, b) tuples, row-major, top-to-bottom.

    Supports bit depth 8, non-interlaced, colour types 0 (gray), 2 (rgb),
    3 (indexed) and 6 (rgba). Palettes may carry 1/2/4-bit indices too.
    """
    if not data.startswith(_PNG_SIG):
        raise ValueError("not a PNG")
    width = height = bit_depth = color_type = 0
    palette: dict[int, tuple] = {}
    trns: dict[int, tuple] = {}
    idat = bytearray()
    seen_ihdr = False
    for ctype, raw in _png_parse_chunks(data):
        if ctype == b"IHDR":
            (width, height, bit_depth, color_type, comp, filt, interlace) = struct.unpack(
                ">IIBBBBB", raw
            )
            if comp != 0 or filt != 0:
                raise ValueError("unsupported PNG compression/filter method")
            if interlace != 0:
                raise ValueError("interlaced PNG not supported, use a non-interlaced file")
            seen_ihdr = True
        elif ctype == b"PLTE":
            for i in range(0, len(raw) - 2, 3):
                palette[i // 3] = (raw[i], raw[i + 1], raw[i + 2])
        elif ctype == b"tRNS":
            if color_type == 3:
                for i, a in enumerate(raw):
                    trns[i] = (a,)
            elif color_type == 0:
                trns[0] = (struct.unpack(">H", raw[0:2])[0],)
            elif color_type == 2:
                for i in range(3):
                    trns[i] = (struct.unpack(">H", raw[i * 2 : i * 2 + 2])[0],)
        elif ctype == b"IDAT":
            idat.extend(raw)
    if not seen_ihdr:
        raise ValueError("PNG missing IHDR")

    if bit_depth not in (1, 2, 4, 8):
        raise ValueError(f"unsupported PNG bit depth {bit_depth}")
    if color_type not in (0, 2, 3, 6):
        raise ValueError(f"unsupported PNG colour type {color_type}")
    if bit_depth != 8 and not (_png_is_palette(color_type) or color_type in (0,)):
        raise ValueError("only 8-bit PNGs supported")

    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise ValueError(f"corrupt PNG data: {exc}") from exc

    bpp = _png_channels(color_type)
    stride = (width * bpp * bit_depth + 7) // 8
    scanline = stride + 1
    if len(raw) < scanline * height:
        raise ValueError("PNG data too short")

    def paeth(a: int, b: int, c: int) -> int:
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        if pa <= pb and pa <= pc:
            return a
        if pb <= pc:
            return b
        return c

    out = []
    prev = bytearray(stride)
    for y in range(height):
        line = bytearray(raw[y * scanline : y * scanline + scanline])
        ftype = line[0]
        line = line[1:]
        if ftype == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                up = prev[i]
                ul = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + paeth(left, up, ul)) & 0xFF

        # expand this scanline into rgb pixels
        if color_type in (0, 4):  # gray (with optional alpha)
            if bit_depth == 8:
                for x in range(width):
                    g = line[x]
                    r, g_, b = _png_scaled_to_rgb(g, 255)
                    out.append((r, g_, b))
            else:
                bits_per_px = bit_depth
                maxval = (1 << bit_depth) - 1
                for x in range(width):
                    byte_idx = (x * bits_per_px) >> 3
                    shift = 8 - bits_per_px - (x * bits_per_px) % 8
                    val = (line[byte_idx] >> shift) & maxval
                    out.append(_png_scaled_to_rgb(val, maxval))
        elif color_type == 2:  # rgb
            for x in range(width):
                i = x * 3
                r, g, b = line[i], line[i + 1], line[i + 2]
                if trns and (r, g, b) == (trns[0][0], trns[1][0], trns[2][0]):
                    out.append((0, 0, 0))  # transparent → solid black slot
                else:
                    out.append((r, g, b))
        elif color_type == 3:  # palette
            if bit_depth == 8:
                for x in range(width):
                    idx = line[x]
                    px = palette.get(idx)
                    if px is None:
                        raise ValueError(f"PNG palette missing index {idx}")
                    out.append(px)
            else:
                maxval = (1 << bit_depth) - 1
                for x in range(width):
                    byte_idx = (x * bit_depth) >> 3
                    shift = 8 - bit_depth - (x * bit_depth) % 8
                    idx = (line[byte_idx] >> shift) & maxval
                    px = palette.get(idx)
                    if px is None:
                        raise ValueError(f"PNG palette missing index {idx}")
                    out.append(px)
        else:  # color_type == 6 rgba
            for x in range(width):
                i = x * 4
                out.append((line[i], line[i + 1], line[i + 2]))
        prev = line

    return width, height, out


# ---- BMP decoder --------------------------------------------------------

def decode_bmp(data: bytes) -> tuple:
    """Decode a BI_RGB BMP (24/32-bit, optionally indexed 8-bit) into
    (width, height, pixels)."""
    if len(data) < 54 or data[0:2] != b"BM":
        raise ValueError("not a BMP")
    (pixel_offset,) = struct.unpack("<I", data[10:14])
    (dib_size,) = struct.unpack("<I", data[14:18])
    if dib_size not in (40, 12, 108, 124):
        raise ValueError(f"unsupported BMP DIB header ({dib_size})")
    if dib_size == 12:
        width, height = struct.unpack("<hh", data[18:22])
        bpp = struct.unpack("<H", data[24:26])[0]
        compression = 0
        palette_colors = 0
    else:
        width, height = struct.unpack("<ii", data[18:26])
        bpp = struct.unpack("<H", data[28:30])[0]
        compression = struct.unpack("<I", data[30:34])[0]
        palette_colors = struct.unpack("<I", data[46:50])[0] if dib_size >= 40 else 0
    if compression != 0:
        raise ValueError(f"compressed BMP not supported (compression={compression})")
    if bpp not in (8, 24, 32):
        raise ValueError(f"unsupported BMP depth ({bpp} bpp)")

    top_down = height < 0
    height = abs(height)

    palette = {}
    if bpp == 8:
        n_entries = palette_colors or 256
        for i in range(n_entries):
            off = 14 + dib_size + i * 4
            if off + 4 > len(data):
                break
            palette[i] = (data[off + 2], data[off + 1], data[off])

    row_bytes = ((bpp * width + 31) // 32) * 4
    pixels = [None] * (width * height)
    for row in range(height):
        src_row = row
        line = data[pixel_offset + src_row * row_bytes :]
        for x in range(width):
            off = x * (bpp // 8)
            if bpp == 8:
                idx = line[off]
                px = palette.get(idx, (0, 0, 0))
            else:
                px = (line[off + 2], line[off + 1], line[off])
            dst_row = row if top_down else height - 1 - row
            pixels[dst_row * width + x] = px
    return width, height, pixels


# ---- PPM / PGM / PBM decoder -------------------------------------------

def decode_ppm(data: bytes) -> tuple:
    """Decode PBM/PGM/PPM (P1..P6) into (width, height, pixels)."""
    if len(data) < 3 or data[0:1] != b"P":
        raise ValueError("not a PPM family file")
    magic = data[:2]

    def next_token(pos):
        while pos < len(data) and data[pos : pos + 1] in b" \t\r\n#":
            if data[pos : pos + 1] == b"#":
                while pos < len(data) and data[pos : pos + 1] != b"\n":
                    pos += 1
            else:
                pos += 1
        if pos >= len(data):
            raise ValueError("truncated PPM header")
        start = pos
        while pos < len(data) and data[pos : pos + 1] not in b" \t\r\n#":
            pos += 1
        return data[start:pos], pos

    wtok, pos = next_token(2)
    htok, pos = next_token(pos)
    try:
        width, height = int(wtok), int(htok)
    except ValueError as exc:
        raise ValueError(f"bad PPM dimensions: {exc}") from exc
    if width <= 0 or height <= 0:
        raise ValueError("invalid PPM dimensions")

    binary = magic in (b"P4", b"P5", b"P6")
    if not binary:
        maxval_tok, pos = next_token(pos)
        maxval = int(maxval_tok)
    else:
        if magic != b"P4":
            mtok, pos = next_token(pos)
            maxval = int(mtok)
        else:
            maxval = 1

    if magic in (b"P3", b"P6"):  # colour
        vals_per_px = 3
    elif magic in (b"P2", b"P5"):  # grayscale
        vals_per_px = 1
    else:  # P1 / P4 bitmap
        vals_per_px = 0

    n_px = width * height
    pixels = []
    if binary:
        # skip the single separating whitespace character before the raster
        while pos < len(data) and data[pos : pos + 1] in b" \t\r\n":
            pos += 1
        if magic == b"P4":
            row_bytes = (width + 7) // 8
            pxdata = data[pos:]
            for y in range(height):
                row = pxdata[y * row_bytes : (y + 1) * row_bytes]
                for x in range(width):
                    bit = (row[x >> 3] >> (7 - (x & 7))) & 1
                    v = 0 if bit else 255
                    pixels.append((v, v, v))
            return width, height, pixels
        if magic == b"P6":
            need = n_px * 3
            pxdata = data[pos : pos + need]
            for i in range(0, len(pxdata) - 2, 3):
                pixels.append((pxdata[i], pxdata[i + 1], pxdata[i + 2]))
        else:  # P5
            need = n_px
            pxdata = data[pos : pos + need]
            for v in pxdata:
                g = round(v * 255 / maxval) if maxval != 255 else v
                pixels.append((g, g, g))
    else:
        tokens = data[pos:].split()
        if magic == b"P1":  # ascii bitmap: values 0/1
            vals = [int(t) for t in tokens[:n_px]]
            for bit in vals:
                v = 0 if bit else 255
                pixels.append((v, v, v))
        else:
            count = n_px * vals_per_px
            vals = [int(t) for t in tokens[:count]]
            if vals_per_px == 1:
                for v in vals:
                    g = round(v * 255 / maxval) if maxval != 255 else v
                    pixels.append((g, g, g))
            else:
                for i in range(0, len(vals) - 2, 3):
                    pixels.append(
                        (
                            round(vals[i] * 255 / maxval),
                            round(vals[i + 1] * 255 / maxval),
                            round(vals[i + 2] * 255 / maxval),
                        )
                    )
    return width, height, pixels


# ---- dispatch -----------------------------------------------------------

DECODERS = {
    "png": decode_png,
    "bmp": decode_bmp,
    "ppm": decode_ppm,
}


def decode_image(fmt: str, data: bytes) -> tuple:
    """Return (width, height, pixels) for a decodable format."""
    dec = DECODERS.get(fmt)
    if dec is None:
        raise ValueError(f"format '{fmt}' cannot be decoded in stdlib")
    return dec(data)


# ---- rendering math (pure, headless-testable) ---------------------------

def quantize(rgb: tuple) -> int:
    """Map an (r, g, b) triple onto the xterm-256 palette index."""
    r, g, b = rgb
    # grayscale ramp (232..255)
    if abs(r - g) < 6 and abs(g - b) < 6:
        avg = (r + g + b) // 3
        if avg == 255:
            return 231
        if avg == 0:
            return 16
        # nearest gray: levels 8,18,..238 (ramp 232+n maps to 8+10n)
        n = round((avg - 8) / 10)
        n = max(0, min(23, n))
        if 0 <= n <= 23:
            return 232 + n
    # colour cube: 6 levels
    def level(c):
        if c < 48:
            return 0
        if c < 115:
            return 1
        return min(5, (c - 35) // 40)
    rl, gl, bl = level(r), level(g), level(b)
    return 16 + 36 * rl + 6 * gl + bl


def fit_scale(image_w: int, image_h: int, cell_w: int, cell_h: int) -> float:
    """Cells per source pixel at "fit" zoom for the given grid.

    A terminal cell is 1 column wide and 2 source-pixels tall.
    """
    if image_w <= 0 or image_h <= 0 or cell_w <= 0 or cell_h <= 0:
        return 1.0
    return min(cell_w / image_w, (2 * cell_h) / image_h)


def build_cells(width: int, height: int, pixels, cell_w: int, cell_h: int,
                scale: float, pan_x: int = 0, pan_y: int = 0) -> list:
    """Build (upper_rgb, lower_rgb) per cell for a half-block grid.

    scale is cells-per-source-pixel; visible region is clamped to the image.
    Returns a list of length cell_w*cell_h (None colours for out-of-image
    cells). Intellectual heavy lifting is box-average for downscaling and
    nearest sampling for upscaling.
    """
    if width <= 0 or height <= 0 or cell_w <= 0 or cell_h <= 0 or scale <= 0:
        return []
    s_per_cell_v = 1 / scale  # source pixels per row-band of one cell

    visible_w = max(0, min(width, int(cell_w / scale)))
    visible_h = max(0, min(height, int((2 * cell_h) / scale)))
    pan_x = max(0, min(pan_x, width - visible_w))
    pan_y = max(0, min(pan_y, height - visible_h))

    cells = []
    upscale = scale > 1.0
    for cy in range(cell_h):
        src_y0 = int(pan_y + cy * (visible_h / cell_h))
        for cx in range(cell_w):
            src_x0 = int(pan_x + cx * (visible_w / cell_w))
            if src_y0 >= height or src_x0 >= width:
                upper = lower = None
            elif upscale:
                upper = pixels[src_y0 * width + src_x0]
                low_y = src_y0 + 1
                lower = pixels[min(low_y, height - 1) * width + src_x0]
            else:
                # box average upper half (source rows y0..mid), lower half
                src_y1 = min(height, src_y0 + max(1, int(visible_h / (2 * cell_h))))
                src_y2 = min(height, src_y0 + max(1, int(visible_h / cell_h)))
                src_x1 = min(width, src_x0 + max(1, int(visible_w / cell_w)))
                upper = _box(pixels, width, src_x0, src_x1, src_y0, src_y1)
                lower = _box(pixels, width, src_x0, src_x1, src_y1, src_y2)
            if upper is None:
                cells.extend([None, None])
            else:
                cells.extend([upper, lower])
    return cells


def _box(pixels, width, x0, x1, y0, y1):
    x1 = max(x0 + 1, x1)
    y1 = max(y0 + 1, y1)
    r = g = b = n = 0
    for y in range(y0, y1):
        base = y * width
        for x in range(x0, x1):
            pr, pg, pb = pixels[base + x]
            r += pr
            g += pg
            b += pb
            n += 1
    return (r // n, g // n, b // n)


# ---- curses drawing -----------------------------------------------------

def make_pairs_state():
    """Colour-pair caches shared across frames (call once, pass into draw).

    Pairs are keyed by (fg, bg) xterm-256 index so the upper-half block can
    hold two colours at once (fg upper, bg lower).
    """
    return {"pairs": {}, "next": 8}


def _pair_for(fg, bg, state):
    import curses

    key = (fg, bg)
    pid = state["pairs"].get(key)
    if pid is not None:
        return pid
    limit = max(8, (getattr(curses, "COLOR_PAIRS", -1) or -1) - 2)
    if state["next"] >= limit:
        # Pair budget exhausted: collapse everything onto a shared solid pair.
        state["next"] = 8
    pid = state["next"]
    state["next"] += 1
    curses.init_pair(pid, fg, bg)
    state["pairs"][key] = pid
    return pid


def draw(stdscr, cells, cell_w, cell_h, state, x0=0, y0=0,
         background=None) -> None:
    """Paint a build_cells() grid onto the terminal with half-block chars.

    cell values are (r, g, b) triples or None (out of image). Uses:
      * half-block '▀' with fg = upper pixel, bg = lower pixel
      * lower-half block '▄' where only the lower pixel exists
      * full block '█' where upper == lower
    """
    import curses

    bg_pair = None
    if background is not None:
        bg_pair = _pair_for(quantize(background), quantize(background), state)
    cell_h = min(cell_h, max(0, stdscr.getmaxyx()[0] - y0))
    for cy in range(cell_h):
        stdscr.addstr(y0 + cy, x0, " " * cell_w,
                      bg_pair if bg_pair is not None else 0)
        for cx in range(cell_w):
            i = cy * cell_w + cx
            upper = cells[i * 2] if i * 2 < len(cells) else None
            lower = cells[i * 2 + 1] if i * 2 + 1 < len(cells) else None
            if upper is None and lower is None:
                continue
            if upper is None:
                pair = _pair_for(quantize(lower), -1, state)
                stdscr.addstr(y0 + cy, x0 + cx, "\u2584", pair)
            elif lower is None or lower == upper:
                c = quantize(upper)
                pair = _pair_for(c, c, state)
                stdscr.addstr(y0 + cy, x0 + cx, "\u2588", pair)
            else:
                pair = _pair_for(quantize(upper), quantize(lower), state)
                stdscr.addstr(y0 + cy, x0 + cx, "\u2580", pair)


# ---- passthrough (any format, terminal renders) ------------------------

_PASSTHROUGH_OK = 100 * 1024 * 1024  # refuse absurd files


def graphics_available() -> str:
    """Return 'kitty', 'iterm', or '' depending on detected terminal."""
    if os.environ.get("KITTY_WINDOW_ID"):
        return "kitty"
    prog = os.environ.get("TERM_PROGRAM", "").lower()
    if prog in ("wezterm", "mintty", "iterm.app", "konsole", "ghostty", "contour"):
        return "iterm"
    term = os.environ.get("TERM", "").lower()
    if "kitty" in term:
        return "kitty"
    if prog or "xterm" in term or "foot" in term or "wez" in term:
        return "iterm"
    return ""


def _kitty_sequence(data: bytes) -> str:
    b64 = base64.b64encode(data).decode("ascii")
    chunk = 4096
    parts = []
    n = len(b64)
    first_opts = "a=T,f=100,t=f,m=1" + ("" if False else "")
    for i in range(0, n, chunk):
        piece = b64[i : i + chunk]
        is_last = i + chunk >= n
        if i == 0:
            opts = "a=T,f=100,t=f" + (",m=1" if not is_last else "")
        elif is_last:
            opts = "m=0"
        else:
            opts = "m=1"
        parts.append(f"\x1b_G{opts};{piece}\x1b\\")
    parts.append("\x1b_Ga=p\a\x1b\\")  # display at current position
    return "".join(parts)


def _iterm_sequence(data: bytes, name: str) -> str:
    payload = base64.b64encode(data).decode("ascii")
    return f"\x1b]1337;File=name={name};size={len(data)};inline=1:{payload}\x07"


def build_passthrough_sequence(path: str, fmt: str) -> str:
    """Build the graphics-protocol escape for any image file."""
    with open(path, "rb") as f:
        data = f.read(_PASSTHROUGH_OK + 1)
    if len(data) > _PASSTHROUGH_OK:
        raise ValueError("image too large to stream to terminal")
    name = os.path.basename(path)
    mode = graphics_available()
    if mode == "kitty":
        return _kitty_sequence(data)
    if mode == "iterm":
        return _iterm_sequence(data, name)
    raise ValueError("terminal does not support inline images")


def stream_fullscreen(_stdscr, path: str, fmt: str, confirm=True) -> bool:
    """Suspend curses, stream the raw image to the terminal and wait for a
    keypress, then restore curses. Returns True on success."""
    import curses
    import sys

    try:
        seq = build_passthrough_sequence(path, fmt)
    except (OSError, ValueError) as exc:
        curses.flash()
        return False

    use_clear = "\n"
    curses.def_prog_mode()
    curses.endwin()
    try:
        sys.stdout.write(use_clear)
        sys.stdout.write(seq)
        sys.stdout.write("\n\nImage rendered by the terminal viewer. ")
        if confirm:
            sys.stdout.write("Press Enter to return to the editor.\n")
            sys.stdout.flush()
            curses.reset_shell_mode()
            sys.stdin.buffer.readline()
        else:
            sys.stdout.write("Returning to the editor.\n")
            sys.stdout.flush()
    finally:
        curses.reset_prog_mode()
    return True


def image_status_text(filename: str, width: int, height: int, fmt: str,
                      zoom_pct: int, mode: str) -> str:
    """Build the reverse-video status row for the image viewer."""
    name = os.path.basename(filename if filename else "/unknown")
    right = f"{mode}  {zoom_pct:>3}%"
    middle = f" {width}x{height}  {fmt}"
    left = f" {name} "
    return left + middle + right


# ---- tiny icon-free screen text ----------------------------------------

def viewer_hints(mode: str) -> str:
    if mode in ("jpeg", "gif", "webp", "heic", "heif", "avif", "tiff",
                "ico", "svg", "isobmff"):
        return "q: raw bytes   v: fullscreen passthrough   Ctrl-Q: quit"
    return ("q: raw bytes   +/- zoom   arrows/PageUp/PageDown pan   "
            "r: reset   Home: fit   End: 100%   v: fullscreen   Ctrl-Q: quit")