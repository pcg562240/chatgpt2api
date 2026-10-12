"""Version-independent image aliases; never reinterpret normal chat IDs as images."""
from __future__ import annotations

import hashlib
import re

WEB_IMAGE_PREFIX = "web-image/"
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")


def valid_model_id(value: object) -> bool:
    return isinstance(value, str) and bool(_MODEL_ID.fullmatch(value))


def web_image_slug(value: object) -> str | None:
    value = str(value or "").strip()
    if value.startswith(WEB_IMAGE_PREFIX):
        slug = value[len(WEB_IMAGE_PREFIX):]
        return slug if valid_model_id(slug) and not slug.startswith(WEB_IMAGE_PREFIX) else None
    return None


def catalog_account_id(account: dict) -> str:
    # JWT rotation must not invalidate a known user's catalog. No token is persisted.
    identity = str(account.get("user_id") or account.get("email") or account.get("access_token") or "")
    scope = str(account.get("account_id") or "")
    source = str(account.get("source_type") or "web")
    return hashlib.sha256(f"{source}\0{scope}\0{identity}".encode()).hexdigest()[:24]
