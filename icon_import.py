"""Extract standalone icons from screenshots and store reusable thumbnails."""
import base64
import hashlib
import io
from statistics import median


KEY_PREFIX = "imported_icon:"
BATCH_LIMIT = 240


def library(db):
    return {key[len(KEY_PREFIX):]: image for key, image in db.execute(
        "SELECT key,value FROM settings WHERE key GLOB ? ORDER BY rowid", (KEY_PREFIX + "*",))}


def save(db, images):
    from image_import import icon_thumbnail

    if not isinstance(images, list) or not 1 <= len(images) <= BATCH_LIMIT:
        raise ValueError(f"请选择 1–{BATCH_LIMIT} 个图标")
    added = 0
    for image in images:
        thumbnail = icon_thumbnail(image)
        key = KEY_PREFIX + "imported-" + hashlib.sha256(thumbnail.encode("ascii")).hexdigest()
        added += db.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (key, thumbnail)).rowcount
    return added


def content_bands(lines):
    """Join small gaps within a mark and retain the whitespace between cells."""
    runs = []
    for index, active in enumerate(lines):
        if not active:
            continue
        if runs and runs[-1][1] == index:
            runs[-1][1] += 1
        else:
            runs.append([index, index + 1])
    if not runs:
        return []
    join_gap = max(3, round(max(end - start for start, end in runs) * .45))
    bands = [runs[0]]
    for start, end in runs[1:]:
        if start - bands[-1][1] <= join_gap:
            bands[-1][1] = end
        else:
            bands.append([start, end])
    return bands


def foreground(image):
    from PIL import Image, ImageChops

    alpha = image.getchannel("A")
    if alpha.histogram()[0] >= image.width * image.height * .10:
        return alpha.point(lambda value: 255 if value >= 32 else 0), None
    rgb = image.convert("RGB")
    width, height = image.size
    samples = [rgb.getpixel(pt) for pt in (
        (0, 0), (width // 2, 0), (width - 1, 0), (0, height // 2), (width - 1, height // 2),
        (0, height - 1), (width // 2, height - 1), (width - 1, height - 1))]
    background = tuple(round(median(channel)) for channel in zip(*samples))
    red, green, blue = ImageChops.difference(rgb, Image.new("RGB", image.size, background)).split()
    contrast = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    cutoff = max(18, min(85, round(contrast.getextrema()[1] * .55)))
    return contrast.point(lambda value: 255 if value >= cutoff else 0), background


def thumbnail(image, mask, bounds, background):
    from PIL import Image, ImageFilter

    crop = image.crop(bounds)
    if background is not None:
        pixels = []
        edge = mask.crop(bounds).filter(ImageFilter.MaxFilter(5))
        source_pixels = getattr(crop, "get_flattened_data", crop.getdata)()
        edge_pixels = getattr(edge, "get_flattened_data", edge.getdata)()
        for (red, green, blue, original_alpha), keep in zip(source_pixels, edge_pixels):
            rgb = red, green, blue
            contrast = max(abs(pixel - bg) for pixel, bg in zip(rgb, background))
            alpha = min(1, contrast / 160) if keep and contrast >= 12 else 0
            color = tuple(max(0, min(255, round(bg + (pixel - bg) / alpha)))
                          for pixel, bg in zip(rgb, background)) if alpha else (0, 0, 0)
            pixels.append((*color, round(alpha * original_alpha)))
        crop.putdata(pixels)
    crop.thumbnail((56, 56), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (64, 64))
    canvas.paste(crop, ((64 - crop.width) // 2, (64 - crop.height) // 2))
    result = io.BytesIO()
    canvas.quantize(colors=128).save(result, format="PNG", optimize=True)
    return base64.b64encode(result.getvalue()).decode("ascii")


def split(source):
    from PIL import Image, ImageOps

    if not isinstance(source, str) or len(source) > 14_000_000:
        raise ValueError("请选择 10 MB 以内的图标图片")
    try:
        raw = base64.b64decode(source, validate=True)
        if len(raw) > 10 * 1024 * 1024:
            raise ValueError("图片过大")
        with Image.open(io.BytesIO(raw)) as original:
            if original.format not in ("PNG", "JPEG", "WEBP") or original.width * original.height > 20_000_000:
                raise ValueError("图片格式或尺寸无效")
            image = ImageOps.exif_transpose(original).convert("RGBA")
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise ValueError("请选择像素不超过 2000 万的 PNG、JPG 或 WebP 图片") from error
    image.thumbnail((2600, 2600), Image.Resampling.LANCZOS)
    mask, background = foreground(image)
    _, rows = mask.getprojection()
    bounds = []
    for top, bottom in content_bands(rows):
        columns, _ = mask.crop((0, top, mask.width, bottom)).getprojection()
        for left, right in content_bands(columns):
            if right - left >= 3 and bottom - top >= 3:
                bounds.append((max(0, left - 2), max(0, top - 2), min(image.width, right + 2),
                               min(image.height, bottom + 2)))
    if not bounds:
        raise ValueError("没有识别到图标，请选择图标清晰、彼此留有空隙的图片")
    if len(bounds) > BATCH_LIMIT:
        raise ValueError(f"识别到超过 {BATCH_LIMIT} 个图标，请分批上传")
    return {"icons": [thumbnail(image, mask, box, background) for box in bounds]}
