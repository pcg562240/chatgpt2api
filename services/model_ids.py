"""Version-independent image aliases; never reinterpret normal chat IDs as images."""
from __future__ import annotations

import hashlib
import re

WEB_IMAGE_PREFIX = "web-image/"
BUILTIN_WEB_IMAGE_MODELS = ("gpt-image-2.5-flare", "gpt-image-2.5-sunburst")
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")


def valid_model_id(value: object) -> bool:
    return isinstance(value, str) and bool(_MODEL_ID.fullmatch(value))


def web_image_slug(value: object) -> str | None:
    value = str(value or "").strip()
    if value.startswith(WEB_IMAGE_PREFIX):
        slug = value[len(WEB_IMAGE_PREFIX):]
        return slug if valid_model_id(slug) and not slug.startswith(WEB_IMAGE_PREFIX) else None
    return None


def custom_image_slug(value: str) -> str:
    """Normalize a manual ID without changing its case or model suffixes."""
    value = value.strip()
    slug = web_image_slug(value) if value.startswith(WEB_IMAGE_PREFIX) else value
    if not slug or not valid_model_id(slug) or slug == "auto" or "://" in slug:
        raise ValueError("请输入准确的模型 ID（1–128 个英文字符、数字或 . _ : / -），不支持 auto、网址或显示名称")
    return slug


def catalog_account_id(account: dict) -> str:
    # JWT rotation must not invalidate a known user's catalog. No token is persisted.
    identity = str(account.get("user_id") or account.get("email") or account.get("access_token") or "")
    scope = str(account.get("account_id") or "")
    source = str(account.get("source_type") or "web")
    return hashlib.sha256(f"{source}\0{scope}\0{identity}".encode()).hexdigest()[:24]
