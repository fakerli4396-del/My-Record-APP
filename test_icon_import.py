import base64
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path

import app
import exchange
import icon_import
import ledger
from PIL import Image, ImageDraw


def encoded(image):
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return base64.b64encode(stream.getvalue()).decode("ascii")


class IconImportTests(unittest.TestCase):
    def test_grid_excludes_faint_frames_and_keeps_disconnected_strokes(self):
        sheet = Image.new("RGB", (2048, 1123), (252, 252, 252))
        draw = ImageDraw.Draw(sheet)
        for row in range(5):
            for column in range(9):
                left, top = 25 + column * 225, 20 + row * 225
                draw.rounded_rectangle((left, top, left + 205, top + 205), radius=20,
                                       outline=(220, 228, 237), width=2)
                draw.rounded_rectangle((left + 63, top + 63, left + 136, top + 123),
                                       radius=8, outline="black", width=6)
                draw.ellipse((left + 92, top + 132, left + 102, top + 142), fill="black")
        draw.rectangle((631, 52, 666, 188), outline=(176, 182, 189), width=2)
        icons = icon_import.split(encoded(sheet))["icons"]
        self.assertEqual(len(icons), 45)
        for content in icons:
            icon = Image.open(io.BytesIO(base64.b64decode(content))).convert("RGBA")
            self.assertEqual(icon.size, (64, 64))
            self.assertEqual(icon.getpixel((0, 0))[3], 0)
            _, rows = icon.getchannel("A").getprojection()
            self.assertIn(0, rows[7:57])

    def test_transparent_single_icon_can_be_reused_and_exported(self):
        image = Image.new("RGBA", (80, 80))
        ImageDraw.Draw(image).ellipse((20, 20, 60, 60), fill=(220, 180, 40, 255))
        icons = icon_import.split(encoded(image))["icons"]
        self.assertEqual(len(icons), 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.db"
            app.initialize(path)
            with app.connect(path) as db:
                self.assertEqual(icon_import.save(db, icons * 2), 1)
                self.assertEqual(icon_import.save(db, icons), 0)
                key = next(iter(icon_import.library(db)))
                ledger.mutate(db, {"action": "category", "kind": "expense", "name": "测试类目", "icon": key})
                book = ledger.mutate(db, {"action": "book", "name": "测试账本", "icon": key})
                ledger.mutate(db, {"action": "asset_image_import", "owner": "family", "items": [{
                    "name": "测试资产", "purchase_price": 100, "purchase_day": date.today().isoformat(),
                    "asset_icon": key, "has_loan": False, "value": 100}]})
                state = ledger.snapshot(db)
                self.assertIn(key, state["imported_icons"])
                self.assertEqual(state["categories"][-1]["icon"], key)
                self.assertEqual(state["book_icons"][str(book)], key)
                self.assertEqual(state["positions"][0]["asset_icon"], key)
            result = exchange.export(path, dict(format="xlsx", book="", owner="all", path=directory))
            restored = Path(directory) / "restored.db"
            exchange.workbook_db(Path(result["path"]), restored)
            with app.connect(restored) as db:
                self.assertEqual(ledger.snapshot(db)["imported_icons"], state["imported_icons"])
