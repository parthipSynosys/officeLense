"""Image decoding, validation, resizing and saving (Pillow + pillow-heif).

Validation checks the REAL file content (magic bytes + Pillow's decoder),
never just the extension. Supported: JPEG, PNG, WebP, HEIC/HEIF.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import BinaryIO

import numpy as np
import pillow_heif
from PIL import Image, ImageOps, UnidentifiedImageError

pillow_heif.register_heif_opener()

# Guard against decompression bombs (Pillow raises above 2x this value).
Image.MAX_IMAGE_PIXELS = 120_000_000

# Pillow format names we accept. MPO = multi-picture JPEG produced by many phones.
ALLOWED_FORMATS = {"JPEG", "MPO", "PNG", "WEBP", "HEIF"}

FORMAT_EXTENSIONS = {"JPEG": ".jpg", "MPO": ".jpg", "PNG": ".png", "WEBP": ".webp", "HEIF": ".heic"}

# ISO-BMFF brands used by HEIC/HEIF files.
_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}

ImageSource = bytes | Path | str | BinaryIO


class InvalidImageError(ValueError):
    """Raised when content is not a decodable image of an allowed type."""


def sniff_image_type(head: bytes) -> str | None:
    """Identify an image type from its first bytes. Returns a Pillow format name or None."""
    if head.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if len(head) >= 12 and head[0:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "WEBP"
    if len(head) >= 12 and head[4:8] == b"ftyp" and head[8:12] in _HEIF_BRANDS:
        return "HEIF"
    return None


def _read_head(source: ImageSource, n: int = 32) -> bytes:
    if isinstance(source, bytes):
        return source[:n]
    if isinstance(source, (str, Path)):
        with open(source, "rb") as fh:
            return fh.read(n)
    pos = source.tell()
    head = source.read(n)
    source.seek(pos)
    return head


def _open(source: ImageSource) -> Image.Image:
    if isinstance(source, bytes):
        return Image.open(io.BytesIO(source))
    return Image.open(source)


def validate_image_file(source: ImageSource) -> str:
    """Cheap validation without a full decode. Returns the Pillow format name."""
    if sniff_image_type(_read_head(source)) is None:
        raise InvalidImageError("Unsupported or unrecognised image type")
    try:
        with _open(source) as img:
            fmt = img.format
            if fmt not in ALLOWED_FORMATS:
                raise InvalidImageError(f"Unsupported image format: {fmt}")
            img.verify()
    except InvalidImageError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise InvalidImageError(f"Corrupt or unreadable image: {exc}") from exc
    return fmt


def load_image(source: ImageSource) -> Image.Image:
    """Fully decode an image, apply EXIF orientation and convert to RGB."""
    if sniff_image_type(_read_head(source)) is None:
        raise InvalidImageError("Unsupported or unrecognised image type")
    try:
        img = _open(source)
        if img.format not in ALLOWED_FORMATS:
            raise InvalidImageError(f"Unsupported image format: {img.format}")
        img.load()
        img = ImageOps.exif_transpose(img) or img
        if img.mode != "RGB":
            if img.mode in ("RGBA", "LA", "P"):
                # Flatten transparency onto white instead of black.
                rgba = img.convert("RGBA")
                bg = Image.new("RGB", rgba.size, (255, 255, 255))
                bg.paste(rgba, mask=rgba.split()[-1])
                img = bg
            else:
                img = img.convert("RGB")
        return img
    except InvalidImageError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise InvalidImageError(f"Corrupt or unreadable image: {exc}") from exc


def resize_max(img: Image.Image, max_side: int) -> Image.Image:
    """Return a copy whose longest side is at most `max_side` (never upscales)."""
    out = img.copy()
    out.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return out


def save_jpeg(img: Image.Image, path: Path, quality: int) -> None:
    """Atomically save as JPEG. EXIF (incl. GPS) is intentionally NOT copied."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    img.save(tmp, "JPEG", quality=quality, optimize=True, progressive=True)
    os.replace(tmp, path)


def pil_to_bgr(img: Image.Image) -> np.ndarray:
    """RGB PIL image -> contiguous BGR uint8 array for OpenCV."""
    arr = np.asarray(img.convert("RGB") if img.mode != "RGB" else img, dtype=np.uint8)
    return np.ascontiguousarray(arr[:, :, ::-1])
