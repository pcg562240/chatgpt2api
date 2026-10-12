from __future__ import annotations

from io import BytesIO
import re
from typing import Any

from PIL import Image, ImageOps

MAX_OUTPUT_EDGE = 4096


def parse_output_size(value: object) -> tuple[int, int] | None:
    """Accept explicit pixel sizes or preserve native output for omitted/auto sizes."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("size must be auto or WIDTHxHEIGHT")
    text = value.strip().lower()
    if text in {"", "auto"}:
        return None
    match = re.fullmatch(r"([1-9]\d{0,3})x([1-9]\d{0,3})", text)
    if match is None:
        raise ValueError("size must be auto or WIDTHxHEIGHT")
    width, height = map(int, match.groups())
    if max(width, height) > MAX_OUTPUT_EDGE:
        raise ValueError(f"size dimensions must not exceed {MAX_OUTPUT_EDGE} pixels")
    return width, height


def normalize_image_output(payload: bytes, size: object) -> tuple[bytes, dict[str, Any]]:
    """Enforce output pixels; this is local resampling, NOT native upstream generation.

    Preserve the complete composition with centered padding if aspect ratios differ.
    Base64 responses and stored URLs must both use the returned bytes.
    """
    target = parse_output_size(size)
    if target is None:
        return payload, {}
    with Image.open(BytesIO(payload)) as source:
        source.load()
        original = source.size
        orientation = source.getexif().get(274, 1)
        changed = original != target or orientation in range(2, 9)
        metadata = {
            "requested_size": f"{target[0]}x{target[1]}",
            "original_size": f"{original[0]}x{original[1]}",
            "size": f"{target[0]}x{target[1]}",
            "resized": original != target,
            "size_processing": "server_resize_pad" if changed else "upstream",
        }
        if not changed:
            return payload, metadata
        image = ImageOps.exif_transpose(source)
        has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
        image = image.convert("RGBA" if has_alpha else "RGB")
        background = (0, 0, 0, 0) if has_alpha else (255, 255, 255)
        output = ImageOps.pad(image, target, method=Image.Resampling.LANCZOS, color=background)
        buffer = BytesIO()
        output.save(buffer, format="PNG")
        return buffer.getvalue(), metadata
