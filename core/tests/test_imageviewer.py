"""Headless tests for the image viewer (no curses required)."""

import os
import struct
import tempfile
import unittest
import zlib

from stdedit import imageviewer

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _png_chunk(ctype, data):
    c = struct.pack(">I", len(data)) + ctype + data
    return c + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)


def make_png(w, h, pixels):
    """Build an 8-bit RGB non-interlaced PNG from row-major (r, g, b) pxs."""
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    scan = bytearray()
    for y in range(h):
        scan.append(0)  # filter: none
        for x in range(w):
            scan.extend(pixels[y * w + x])
    idat = zlib.compress(bytes(scan))
    return (PNG_SIG + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat)
            + _png_chunk(b"IEND", b""))


def make_bmp(w, h, pixels):
    """Build a BI_RGB 24-bit BMP from TOP-DOWN row-major (r, g, b) pixels.

    BMP files store rows bottom-up, so the input rows are reversed on write.
    """
    row_bytes = ((24 * w + 31) // 32) * 4
    pix_off = 54
    total = pix_off + row_bytes * h
    hdr = struct.pack("<2sIHHI", b"BM", total, 0, 0, pix_off)
    dib = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, 0, 0, 0, 0, 0)
    body = bytearray()
    for row in reversed(pixels):
        for r, g, b in row:
            body.extend((b, g, r))
        body.extend(b"\x00" * (row_bytes - w * 3))
    return hdr + dib + bytes(body)


class TestDetectFormat(unittest.TestCase):
    def test_magic_bytes(self):
        cases = [
            (PNG_SIG, "png"),
            (b"\xff\xd8\xff", "jpeg"),
            (b"GIF89a", "gif"),
            (b"BM\x00\x00", "bmp"),
            (b"P6\n1", "ppm"),
            (b"P3\n1", "ppm"),
            (b"P4", "ppm"),
            (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "webp"),
            (b"II*\x00", "tiff"),
            (b"MM\x00*", "tiff"),
            (b"\x00\x00\x01\x00", "ico"),
            (b"        <svg", "svg"),
            (b"<?xml version=\"1.0\"?><svg", "svg"),
        ]
        for data, expected in cases:
            self.assertEqual(imageviewer.detect_format(data), expected,
                             repr(data))
        self.assertIsNone(imageviewer.detect_format(b"just text"))
        self.assertIsNone(imageviewer.detect_format(b""))

    def test_detect_format_path(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(PNG_SIG)
            path = f.name
        try:
            self.assertEqual(imageviewer.detect_format_path(path), "png")
        finally:
            os.unlink(path)


class TestDecoders(unittest.TestCase):
    def test_decode_png_rgb(self):
        png = make_png(2, 2, [(255, 0, 0), (0, 255, 0),
                              (0, 0, 255), (255, 255, 255)])
        w, h, px = imageviewer.decode_png(png)
        self.assertEqual((w, h), (2, 2))
        self.assertEqual(px, [(255, 0, 0), (0, 255, 0),
                              (0, 0, 255), (255, 255, 255)])

    def test_decode_png_rejects_bad_signature(self):
        with self.assertRaises(ValueError):
            imageviewer.decode_png(b"not a png")

    def test_decode_png_palette(self):
        # 2x2 indexed, 8-bit: pixels 0,1,0,1
        palette = bytes((v for entry in ((255, 0, 0), (0, 0, 255))
                         for v in entry))
        ihdr = struct.pack(">IIBBBBB", 2, 2, 8, 3, 0, 0, 0)
        scan = b"\x00\x00\x01" b"\x00\x00\x01"  # two rows: filter,0,1
        png = (PNG_SIG + _png_chunk(b"IHDR", ihdr)
               + _png_chunk(b"PLTE", palette)
               + _png_chunk(b"IDAT", zlib.compress(scan))
               + _png_chunk(b"IEND", b""))
        w, h, px = imageviewer.decode_png(png)
        self.assertEqual((w, h), (2, 2))
        self.assertEqual(px, [(255, 0, 0), (0, 0, 255),
                              (255, 0, 0), (0, 0, 255)])

    def test_decode_bmp_rgb(self):
        bmp = make_bmp(2, 2, [[(255, 0, 0), (0, 255, 0)],
                              [(0, 0, 255), (0, 0, 0)]])
        w, h, px = imageviewer.decode_bmp(bmp)
        self.assertEqual((w, h), (2, 2))
        self.assertEqual(px, [(255, 0, 0), (0, 255, 0),
                              (0, 0, 255), (0, 0, 0)])

    def test_decode_ppm_ascii(self):
        data = b"P3\n2 2\n255\n255 0 0 0 255 0\n0 0 255 255 255 255\n"
        w, h, px = imageviewer.decode_ppm(data)
        self.assertEqual((w, h), (2, 2))
        self.assertEqual(px, [(255, 0, 0), (0, 255, 0),
                              (0, 0, 255), (255, 255, 255)])

    def test_decode_ppm_binary_gray(self):
        data = b"P5\n2 2\n255\n\x00\x7f\xff\x80"
        w, h, px = imageviewer.decode_ppm(data)
        self.assertEqual(px, [(0, 0, 0), (127, 127, 127),
                              (255, 255, 255), (128, 128, 128)])

    def test_decode_image_dispatch(self):
        w, h, px = imageviewer.decode_image("png", make_png(1, 1, [(1, 2, 3)]))
        self.assertEqual((w, h, px), (1, 1, [(1, 2, 3)]))
        with self.assertRaises(ValueError):
            imageviewer.decode_image("jpeg", b"\xff\xd8\xff")


class TestRenderMath(unittest.TestCase):
    def test_fit_scale(self):
        # 100x50 image in a 40-wide x 10-tall grid (cells are 2px tall)
        self.assertAlmostEqual(imageviewer.fit_scale(100, 50, 40, 10), 0.4)
        self.assertAlmostEqual(imageviewer.fit_scale(100, 50, 40, 50), 0.4)
        self.assertEqual(imageviewer.fit_scale(0, 0, 40, 10), 1.0)
        self.assertEqual(imageviewer.fit_scale(20, 20, 0, 0), 1.0)

    def test_build_cells_grid_size(self):
        px = [(200, 0, 0), (0, 200, 0), (0, 0, 200), (200, 200, 200)]
        cells = imageviewer.build_cells(2, 2, px, 4, 1, 1.0)
        # 4 cells * (upper, lower)
        self.assertEqual(len(cells), 8)
        self.assertEqual(cells[0], (200, 0, 0))
        self.assertEqual(cells[1], (0, 0, 200))

    def test_build_cells_downscale_box_average(self):
        px = [(255, 0, 0)] * 4  # uniform red 2x2 downscaled to 1 cell
        cells = imageviewer.build_cells(2, 2, px, 1, 1, 1.0)
        self.assertEqual(cells[0], (255, 0, 0))
        self.assertEqual(cells[1], (255, 0, 0))

    def test_build_cells_upscale_nearest(self):
        px = [(10, 20, 30)]
        cells = imageviewer.build_cells(1, 1, px, 4, 1, 2.0)
        self.assertEqual(cells[0], (10, 20, 30))
        self.assertEqual(cells[1], (10, 20, 30))

    def test_build_cells_pan_clamped(self):
        px = [(1, 0, 0), (2, 0, 0), (3, 0, 0), (4, 0, 0)]
        cells = imageviewer.build_cells(2, 2, px, 2, 1, 1.0, pan_x=50, pan_y=50)
        # extreme pan clamps to the image edge; no crash, correct length
        self.assertEqual(len(cells), 4)

    def test_quantize_bounds(self):
        for rgb in [(0, 0, 0), (255, 255, 255), (255, 0, 0),
                    (0, 255, 0), (0, 0, 255), (128, 128, 128)]:
            self.assertGreaterEqual(imageviewer.quantize(rgb), 0)
            self.assertLessEqual(imageviewer.quantize(rgb), 255)


class TestPassthrough(unittest.TestCase):
    def test_build_kitty_sequence_shape(self):
        seq = imageviewer._kitty_sequence(b"abc")
        self.assertIn("\x1b_G", seq)
        self.assertIn("a=T", seq)
        self.assertIn("a=p", seq)
        # base64 of "abc"
        self.assertIn("YWJj", seq)

    def test_build_iterm_sequence_shape(self):
        seq = imageviewer._iterm_sequence(b"xy", "pic.png")
        self.assertIn("\x1b]1337;File=name=pic.png;size=2;inline=1:", seq)
        self.assertIn("eHk=", seq)
        self.assertIn("\x07", seq)

    def test_build_passthrough_sequence_roundtrip(self):
        path = tempfile.mktemp()
        with open(path, "wb") as f:
            f.write(b"\xff\xd8\xfffake-jpeg")
        try:
            seq = imageviewer.build_passthrough_sequence(path, "jpeg")
            self.assertIn("\x1b_G", seq)
        finally:
            os.unlink(path)

    def test_graphics_available_env(self):
        # ensure the function inspects env without crashing
        old = os.environ.copy()
        try:
            os.environ.pop("KITTY_WINDOW_ID", None)
            os.environ.pop("TERM_PROGRAM", None)
            os.environ["TERM"] = "xterm-kitty"
            self.assertEqual(imageviewer.graphics_available(), "kitty")
            os.environ["KITTY_WINDOW_ID"] = "1"
            self.assertEqual(imageviewer.graphics_available(), "kitty")
            os.environ.pop("KITTY_WINDOW_ID")
            os.environ["TERM_PROGRAM"] = "WezTerm"
            self.assertEqual(imageviewer.graphics_available(), "iterm")
        finally:
            os.environ.clear()
            os.environ.update(old)


class TestBufferImageMode(unittest.TestCase):
    def test_buffer_load_detects_image(self):
        from stdedit.buffer import Buffer
        path = tempfile.mktemp(suffix=".png")
        with open(path, "wb") as f:
            f.write(make_png(1, 1, [(255, 0, 0)]))
        try:
            b = Buffer()
            b.load(path)
            self.assertEqual(b.image_format, "png")
            self.assertEqual(b.image_path, path)
            self.assertFalse(b.modified)
            self.assertEqual(len(b.lines), 1)
        finally:
            os.unlink(path)

    def test_buffer_load_resets_image_state_for_text(self):
        from stdedit.buffer import Buffer
        path = tempfile.mktemp(suffix=".txt")
        with open(path, "wb") as f:
            f.write(b"hello\nworld\n")
        try:
            b = Buffer()
            b.load(path)
            self.assertIsNone(b.image_format)
            self.assertIsNone(b.image_path)
        finally:
            os.unlink(path)


class TestStatusAndHints(unittest.TestCase):
    def test_image_status_text_contains_all_fields(self):
        text = imageviewer.image_status_text(
            "/tmp/photos/sunset.png", 800, 600, "png", 100, "fit")
        self.assertIn("sunset.png", text)
        self.assertIn("800x600", text)
        self.assertIn("png", text)
        self.assertIn("100%", text)
        self.assertIn("fit", text)

    def test_status_text_escapes_unknown_filename(self):
        text = imageviewer.image_status_text("", 1, 1, "ppm", 50, "zoom")
        self.assertIn("unknown", text)

    def test_viewer_hints_decodable_format(self):
        hints = imageviewer.viewer_hints("png")
        self.assertIn("Home: fit", hints)
        self.assertIn("+/- zoom", hints)
        self.assertIn("Ctrl-Q: quit", hints)

    def test_viewer_hints_passthrough_format(self):
        for fmt in ("jpeg", "gif", "webp", "heic", "avif", "svg"):
            hints = imageviewer.viewer_hints(fmt)
            self.assertIn("fullscreen passthrough", hints, fmt)
            self.assertNotIn("Home: fit", hints)


class TestMalformedImages(unittest.TestCase):
    def test_ppm_malformed_headers_raise_valueerror(self):
        for blob in (b"", b"P6\n", b"P6\n0 0\n", b"P7 1 1", b"P2"):
            with self.assertRaises(ValueError, msg=repr(blob)):
                imageviewer.decode_ppm(blob)

    def test_ppm_truncated_raster_is_graceful(self):
        # Header is valid, raster is short — must not raise or hang.
        width, height, pixels = imageviewer.decode_ppm(b"P6\n2 2\n255\n")
        self.assertEqual((width, height), (2, 2))
        self.assertIsInstance(pixels, list)
        self.assertLessEqual(len(pixels), 4)

    def test_ppm_ascii_garbage_dimensions(self):
        with self.assertRaises(ValueError):
            imageviewer.decode_ppm(b"P3\nabc def\n")


if __name__ == "__main__":
    unittest.main()