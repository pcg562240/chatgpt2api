from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from services.account_service import AccountService, account_service
from services.config import DATA_DIR, config
from services.model_ids import (BUILTIN_WEB_IMAGE_MODELS, WEB_IMAGE_PREFIX, catalog_account_id,
                               custom_image_slug, valid_model_id)
from services.openai_backend_api import OpenAIBackendAPI
from utils.log import logger


@dataclass(frozen=True)
class ModelRoute:
    account_types: frozenset[str]
    allow_anonymous: bool = False
    # None preserves compatibility with callers using the old type-only route.
    account_ids: frozenset[str] | None = None


class ModelUnavailableError(RuntimeError):
    pass


class ModelCatalogService:
    """Account-scoped, last-good catalogs. Manual refresh never probes generation."""

    def __init__(self, accounts: AccountService, *,
                 backend_factory: Callable[..., Any] = OpenAIBackendAPI,
                 cache_ttl_seconds: float = 300,
                 clock: Callable[[], float] = time.monotonic,
                 cache_path: Path | None = None) -> None:
        self._accounts = accounts
        self._backend_factory = backend_factory
        self._cache_ttl_seconds = max(1.0, float(cache_ttl_seconds))
        self._clock = clock
        self._lock = RLock()
        self._expires_at = 0.0
        self._account_signature: tuple = ()
        self._anonymous_models: dict[str, dict[str, Any]] = {}
        self._catalogs: dict[str, dict[str, Any]] = {}
        self._selected_account_id = ""
        self._custom_image_models: set[str] = set()
        self._cache_path = cache_path
        if cache_path and cache_path.exists():
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                self._selected_account_id = str(payload.get("selected_account_id") or "")
                for slug in payload.get("custom_image_models", []):
                    try:
                        normalized = custom_image_slug(slug)
                        if normalized not in BUILTIN_WEB_IMAGE_MODELS:
                            self._custom_image_models.add(normalized)
                    except (ValueError, AttributeError):
                        continue
                for key, entry in payload.get("accounts", {}).items():
                    models = self._model_map({"data": entry["models"]})
                    self._catalogs[key] = {"models": models, "updated_at": str(entry["updated_at"])}
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                logger.warning({"event": "model_catalog_cache_invalid"})

    @staticmethod
    def _model_map(result: object) -> dict[str, dict[str, Any]]:
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            raise TypeError("upstream model response has no data list")
        models = {}
        for item in result["data"]:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "").strip()
            if not valid_model_id(model_id) or model_id.startswith(WEB_IMAGE_PREFIX):
                continue
            # Whitelist fields: never cache arbitrary upstream bodies or credentials.
            models[model_id] = {
                "id": model_id, "object": "model", "created": 0,
                "owned_by": "chatgpt", "permission": [], "root": model_id, "parent": None,
            }
        if not models:
            raise ValueError("upstream model catalog is empty")
        return models

    def _active_accounts(self) -> dict[str, dict]:
        return {
            catalog_account_id(a): a for a in self._accounts.list_accounts()
            if isinstance(a, dict) and a.get("status") not in {"禁用", "异常"}
            and str(a.get("access_token") or "").strip()
            and self._accounts._normalize_source_type(a.get("source_type")) != "codex"
        }

    @staticmethod
    def _signature(accounts: dict[str, dict]) -> tuple:
        return tuple(sorted((key, str(a.get("type")), hashlib.sha256(
            str(a.get("access_token")).encode()).hexdigest()) for key, a in accounts.items()))

    def _fetch_models(self, access_token: str = "") -> dict[str, dict[str, Any]]:
        backend = self._backend_factory(access_token=access_token)
        try:
            return self._model_map(backend.list_models())
        finally:
            backend.close()

    def _fetch_account(self, account: dict) -> dict[str, Any]:
        token = account["access_token"]
        token = self._accounts.refresh_access_token(token, event="list_models") or token
        models = self._fetch_models(token)
        return {"models": models, "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    def _prune(self, accounts: dict[str, dict]) -> None:
        self._catalogs = {key: value for key, value in self._catalogs.items() if key in accounts}

    def _persist(self) -> None:
        if not self._cache_path:
            return
        payload = {"version": 2, "selected_account_id": self._selected_account_id,
                   "custom_image_models": sorted(self._custom_image_models), "accounts": {
            key: {"updated_at": entry["updated_at"], "models": list(entry["models"].values())}
            for key, entry in self._catalogs.items()
        }}
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._cache_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(temp, 0o600)
        temp.replace(self._cache_path)

    @staticmethod
    def _error(exc: Exception) -> str:
        status = getattr(exc, "status_code", None)
        code = f"HTTP {status}" if isinstance(status, int) else type(exc).__name__
        logger.warning({"event": "model_catalog_refresh_failed", "error_type": code})
        return f"刷新失败（{code}），已保留最近成功目录。请检查账号登录状态或上游连接。"

    def _ensure_catalog(self) -> None:
        with self._lock:
            accounts = self._active_accounts()
            signature = self._signature(accounts)
            if signature == self._account_signature and self._clock() < self._expires_at:
                return
            self._prune(accounts)
            with ThreadPoolExecutor(max_workers=min(4, len(accounts) + 1)) as executor:
                anonymous = executor.submit(self._fetch_models)
                futures = {key: executor.submit(self._fetch_account, a) for key, a in accounts.items()}
                try:
                    self._anonymous_models = anonymous.result()
                except Exception as exc:
                    self._error(exc)
                for key, future in futures.items():
                    try:
                        self._catalogs[key] = future.result()
                    except Exception as exc:
                        self._error(exc)
            current_accounts = self._active_accounts()
            self._prune(current_accounts)
            self._account_signature = self._signature(current_accounts)
            self._expires_at = self._clock() + self._cache_ttl_seconds
            try:
                self._persist()
            except OSError:
                logger.warning({"event": "model_catalog_cache_write_failed"})

    def list_models(self) -> dict[str, Any]:
        self._ensure_catalog()
        with self._lock:
            union = dict(self._anonymous_models)
            for entry in self._catalogs.values():
                union.update(entry["models"])
            return {"object": "list", "data": [dict(union[key]) for key in sorted(union)]}

    def route_for_model(self, model: str) -> ModelRoute:
        self._ensure_catalog()
        with self._lock:
            accounts = self._active_accounts()
            ids = frozenset(key for key, entry in self._catalogs.items()
                            if key in accounts and model in entry["models"])
            return ModelRoute(
                account_types=frozenset(plan for key in ids if
                    (plan := self._accounts._normalize_account_type(accounts[key].get("type")))),
                allow_anonymous=model in self._anonymous_models,
                account_ids=ids,
            )

    def image_model_ids(self, account_id: str = "") -> list[str]:
        """Cached aliases only: refresh is explicit, not a side effect of UI reads."""
        with self._lock:
            active = self._active_accounts()
            slugs = {slug for key, entry in self._catalogs.items()
                     if key in active and (not account_id or key == account_id)
                     for slug in entry["models"]}
            if active and (not account_id or account_id in active):
                slugs.update(self._custom_image_models)
            return [WEB_IMAGE_PREFIX + slug for slug in sorted(slugs)]

    def route_for_image_model(self, model: str) -> ModelRoute:
        """Manual/builtin IDs are opt-in web routes, not text catalog claims."""
        with self._lock:
            if model in BUILTIN_WEB_IMAGE_MODELS or model in self._custom_image_models:
                accounts = self._active_accounts()
                return ModelRoute(
                    account_types=frozenset(plan for a in accounts.values() if
                        (plan := self._accounts._normalize_account_type(a.get("type")))),
                    account_ids=frozenset(accounts),
                )
        return self.route_for_model(model)

    def add_custom_image_model(self, model: str) -> str:
        slug = custom_image_slug(model)
        if slug in BUILTIN_WEB_IMAGE_MODELS:
            return slug
        with self._lock:
            if slug not in self._custom_image_models:
                if len(self._custom_image_models) >= 100:
                    raise ValueError("自定义模型最多保存 100 个，请先删除不用的模型")
                self._custom_image_models.add(slug)
                try:
                    self._persist()
                except OSError:
                    self._custom_image_models.remove(slug)
                    raise
        return WEB_IMAGE_PREFIX + slug

    def remove_custom_image_model(self, model: str) -> None:
        slug = custom_image_slug(model)
        with self._lock:
            if slug not in self._custom_image_models:
                raise ValueError("该模型不是已保存的自定义模型")
            if config.default_image_model == WEB_IMAGE_PREFIX + slug:
                raise ValueError("请先将全局默认模型切换到其他模型再删除")
            self._custom_image_models.remove(slug)
            try:
                self._persist()
            except OSError:
                self._custom_image_models.add(slug)
                raise

    def snapshot(self, account_id: str = "") -> dict[str, Any]:
        with self._lock:
            accounts = self._active_accounts()
            if account_id and account_id not in accounts:
                raise ValueError("账号不存在、已禁用或不是网页账号")
            selected = account_id or (self._selected_account_id if self._selected_account_id in accounts else next(iter(accounts), ""))
            entry = self._catalogs.get(selected, {})
            return {
                "accounts": [{"id": key, "label": f"网页账号 {i} · {a.get('type') or 'unknown'}"}
                             for i, (key, a) in enumerate(accounts.items(), 1)],
                "account_id": selected,
                "models": list(entry.get("models", {}).values()),
                "image_models": ["gpt-image-2", *BUILTIN_WEB_IMAGE_MODELS, *self.image_model_ids(selected)],
                "builtin_image_models": list(BUILTIN_WEB_IMAGE_MODELS),
                "custom_image_models": sorted(self._custom_image_models),
                "default_image_model": config.default_image_model,
                "updated_at": entry.get("updated_at"),
                "source": "account_cache" if entry else "not_refreshed",
                "generation_verified": False,
            }

    def refresh_account(self, account_id: str = "") -> dict[str, Any]:
        with self._lock:
            accounts = self._active_accounts()
            selected = account_id or (self._selected_account_id if self._selected_account_id in accounts else next(iter(accounts), ""))
            if selected not in accounts:
                raise ValueError("请选择一个正常的网页账号后刷新")
            self._prune(accounts)
            try:
                entry = self._fetch_account(accounts[selected])
            except Exception as exc:
                current = selected if selected in self._active_accounts() else ""
                return {**self.snapshot(current), "refreshed": False, "error": self._error(exc)}
            # Recheck deletion/disable while the network request was running.
            if selected not in self._active_accounts():
                raise ValueError("账号状态已改变，请重新选择账号")
            previous = self._catalogs.get(selected)
            previous_selected = self._selected_account_id
            self._selected_account_id = selected
            self._catalogs[selected] = entry
            try:
                self._persist()
            except OSError as exc:
                self._selected_account_id = previous_selected
                if previous is None:
                    self._catalogs.pop(selected, None)
                else:
                    self._catalogs[selected] = previous
                return {**self.snapshot(selected), "refreshed": False, "error": self._error(exc)}
            self._account_signature = self._signature(self._active_accounts())
            self._expires_at = self._clock() + self._cache_ttl_seconds
            return {**self.snapshot(selected), "refreshed": True, "error": ""}


model_catalog_service = ModelCatalogService(account_service, cache_path=DATA_DIR / "model_catalog.json")
