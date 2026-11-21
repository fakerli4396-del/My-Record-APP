"""Local bill images, stored transactionally with the ledger."""
import base64
import io


MAX_FILES = 3
MAX_BYTES = 3 * 1024 * 1024
MAX_PIXELS = 24_000_000


def ensure(db):
    db.execute("""CREATE TABLE IF NOT EXISTS bill_attachments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_id INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        image BLOB NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS bill_attachments_bill ON bill_attachments(bill_id)")


def metadata(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='bill_attachments'").fetchone():
        return []
    return [dict(row) for row in db.execute("SELECT id,bill_id,name FROM bill_attachments ORDER BY id")]


def prepare(item):
    from PIL import Image, ImageOps

    if not isinstance(item, dict) or not isinstance(item.get("name"), str):
        raise ValueError("附件格式无效")
    source = item.get("content")
    if not isinstance(source, str) or not 0 < len(source) <= MAX_BYTES * 4 // 3:
        raise ValueError("每张附件图片不能超过 3 MB")
    name = item["name"].replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(char for char in name if char.isprintable()).strip()[:160] or "图片附件"
    try:
        raw = base64.b64decode(source, validate=True)
        if not raw or len(raw) > MAX_BYTES:
            raise ValueError()
        with Image.open(io.BytesIO(raw)) as original:
            if original.format not in ("JPEG", "PNG", "WEBP") or original.width * original.height > MAX_PIXELS:
                raise ValueError()
            image = ImageOps.exif_transpose(original).convert("RGBA")
            image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
        result = Image.new("RGB", image.size, "white")
        result.paste(image, mask=image.getchannel("A"))
        output = io.BytesIO()
        result.save(output, format="JPEG", quality=90, optimize=True)
        return name, output.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise ValueError("附件须为有效的 JPG、PNG 或 WebP 图片，且不超过 2400 万像素") from error


def update(db, bill_id, data):
    incoming = data.get("attachments", [])
    removed = data.get("remove_attachments", [])
    if not isinstance(incoming, list) or len(incoming) > MAX_FILES or not isinstance(removed, list) or len(removed) > MAX_FILES:
        raise ValueError("每笔账单最多保留 3 张图片")
    if any(type(key) is not int for key in removed):
        raise ValueError("附件编号无效")
    existing = {row[0] for row in db.execute("SELECT id FROM bill_attachments WHERE bill_id=?", (bill_id,))}
    removed = set(removed)
    if not removed <= existing:
        raise ValueError("附件已变更，请刷新后重试")
    if len(existing - removed) + len(incoming) > MAX_FILES:
        raise ValueError("每笔账单最多保留 3 张图片")
    images = [prepare(item) for item in incoming]
    db.executemany("DELETE FROM bill_attachments WHERE id=?", [(key,) for key in removed])
    db.executemany("INSERT INTO bill_attachments(bill_id,name,image) VALUES (?,?,?)",
                   [(bill_id, name, image) for name, image in images])


def read(db, bill_id, key):
    if type(bill_id) is not int or type(key) is not int:
        raise ValueError("附件编号无效")
    row = db.execute("SELECT image FROM bill_attachments WHERE id=? AND bill_id=?", (key, bill_id)).fetchone()
    if row is None:
        raise ValueError("账单附件不存在")
    return {"content":base64.b64encode(row["image"]).decode("ascii")}
