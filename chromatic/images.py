"""Decode bounded, raster-only uploads and normalize image orientation."""

import io
import warnings

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError


def decode_image(data: bytes, max_pixels: int) -> np.ndarray:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"PNG", "JPEG"}:
                    raise ValueError("Only PNG and JPEG images are supported")
                if image.width * image.height > max_pixels:
                    raise ValueError(
                        f"Image exceeds {max_pixels:,} pixels; resize before uploading"
                    )
                if getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Animated images are not supported")
                # Composite transparent inputs on white instead of hidden RGB values.
                oriented = ImageOps.exif_transpose(image).convert("RGBA")
                background = Image.new("RGBA", oriented.size, "white")
                return np.array(Image.alpha_composite(background, oriented).convert("RGB"))
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ) as exc:
        raise ValueError("Invalid or unsafe image") from exc


def encode_png(image: np.ndarray) -> bytes:
    stream = io.BytesIO()
    Image.fromarray(image).save(stream, format="PNG")
    return stream.getvalue()
