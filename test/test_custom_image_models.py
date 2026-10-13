from __future__ import annotations

import json
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.system as system_api
from services.model_ids import BUILTIN_WEB_IMAGE_MODELS, custom_image_slug
from services.model_service import ModelUnavailableError
from services.openai_backend_api import OpenAIBackendAPI
from services.protocol import conversation, openai_v1_models
from test import test_account_model_discovery as discovery
from utils.helper import UpstreamHTTPError, is_codex_image_model, is_image_chat_request, split_image_model


class CustomImageModelsTests(unittest.TestCase):
    setUp = discovery.DiscoveryTests.setUp
    make_catalog = discovery.DiscoveryTests.make_catalog

    def test_builtins_work_without_catalog_fetch_and_only_route_web(self):
        for model in BUILTIN_WEB_IMAGE_MODELS:
            self.assertIn(model, self.catalog.snapshot()['image_models'])
            self.assertEqual(self.catalog.route_for_image_model(model).account_ids, {self.first, self.second})
            self.assertEqual(self.catalog.add_custom_image_model(model), model)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.catalog.snapshot()['custom_image_models'], [])

    def test_manual_registration_keeps_exact_id_and_is_idempotent(self):
        alias = self.catalog.add_custom_image_model(' Future-Image-9-max ')
        self.assertEqual(alias, 'web-image/Future-Image-9-max')
        self.assertEqual(self.catalog.add_custom_image_model(alias), alias)
        self.assertEqual(self.catalog.snapshot()['custom_image_models'], ['Future-Image-9-max'])
        self.assertIn(alias, self.catalog.image_model_ids())
        self.assertEqual(self.calls, [])  # No generation or discovery on registration.

    def test_manual_route_does_not_claim_text_catalog_membership(self):
        self.catalog.add_custom_image_model('future-image')
        self.assertEqual(self.catalog.route_for_image_model('future-image').account_ids, {self.first, self.second})
        self.assertFalse(self.catalog.route_for_model('future-image').account_ids)
        self.assertNotIn('future-image', {m['id'] for m in self.catalog.snapshot()['models']})

    def test_manual_registration_survives_refresh_and_restart(self):
        alias = self.catalog.add_custom_image_model('Future-Image-max')
        self.catalog.refresh_account(self.first)
        restored = self.make_catalog()
        self.assertIn(alias, restored.image_model_ids())
        self.assertEqual(restored.snapshot()['custom_image_models'], ['Future-Image-max'])
        text = self.path.read_text()
        self.assertNotIn('secret', text)
        self.assertNotIn('@example.test', text)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_custom_model_selection_uses_quota_and_web_slot_selector(self):
        self.catalog.add_custom_image_model('Future-Image-max')
        with mock.patch.object(self.accounts, 'fetch_remote_info', side_effect=lambda token, *_: self.accounts.get_account(token)):
            token = self.accounts.get_available_access_token(model='Future-Image-max')
        self.assertIn(token, {'first-token-secret', 'second-token-secret'})
        self.accounts.release_image_slot(token)

    def test_disabled_accounts_are_not_custom_or_builtin_candidates(self):
        self.catalog.add_custom_image_model('manual-image')
        for token in ('first-token-secret', 'second-token-secret'):
            self.accounts.update_account(token, {'status': '禁用'})
        self.assertEqual(self.catalog.image_model_ids(), [])
        for model in ('manual-image', *BUILTIN_WEB_IMAGE_MODELS):
            self.assertFalse(self.catalog.route_for_image_model(model).account_ids)
            with self.assertRaises(ModelUnavailableError):
                self.accounts.get_available_access_token(model=model)

    def test_custom_removal_persists_and_removes_opt_in_routing(self):
        self.catalog.add_custom_image_model('manual-image')
        self.catalog.remove_custom_image_model('web-image/manual-image')
        self.assertEqual(self.make_catalog().snapshot()['custom_image_models'], [])
        self.assertFalse(self.catalog.route_for_image_model('manual-image').account_ids)

    def test_default_custom_model_must_be_changed_before_deleting(self):
        alias = self.catalog.add_custom_image_model('manual-image')
        with mock.patch.dict(system_api.config.data, {'default_image_model': alias}):
            with self.assertRaises(ValueError):
                self.catalog.remove_custom_image_model(alias)
        self.assertIn(alias, self.catalog.image_model_ids())

    def test_persist_failure_rolls_back_add_and_remove(self):
        with mock.patch.object(self.catalog, '_persist', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.catalog.add_custom_image_model('manual-image')
        self.assertEqual(self.catalog.snapshot()['custom_image_models'], [])
        self.catalog.add_custom_image_model('manual-image')
        with mock.patch.object(self.catalog, '_persist', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.catalog.remove_custom_image_model('manual-image')
        self.assertEqual(self.catalog.snapshot()['custom_image_models'], ['manual-image'])

    def test_invalid_ids_are_rejected_and_nothing_saved(self):
        for value in ('', 'auto', 'bad model', 'bad\nmodel', '模型', 'a' * 129, 'web-image/',
                      'web-image/web-image/nested', 'https://example.test/model'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.catalog.add_custom_image_model(value)
        self.assertEqual(self.catalog.snapshot()['custom_image_models'], [])

    def test_manual_model_limit_and_duplicate_at_limit(self):
        self.catalog._custom_image_models = {f'model-{i}' for i in range(100)}
        self.assertEqual(self.catalog.add_custom_image_model('model-0'), 'web-image/model-0')
        with self.assertRaises(ValueError):
            self.catalog.add_custom_image_model('model-overflow')

    def test_v1_list_exposes_builtins_and_manual_aliases_not_raw_manual_ids(self):
        self.catalog.add_custom_image_model('manual-image')
        with mock.patch.object(openai_v1_models, 'model_catalog_service', self.catalog), \
             mock.patch.object(openai_v1_models, 'account_service', self.accounts):
            ids = {m['id'] for m in openai_v1_models.list_models()['data']}
        self.assertTrue(set(BUILTIN_WEB_IMAGE_MODELS) <= ids)
        self.assertIn('web-image/manual-image', ids)
        self.assertNotIn('manual-image', ids)

    def test_admin_endpoints_add_default_and_remove(self):
        app = FastAPI()
        app.include_router(system_api.create_router('test'))
        client = TestClient(app)
        headers = {'Authorization': 'Bearer chatgpt2api'}
        with mock.patch.object(system_api, 'model_catalog_service', self.catalog):
            response = client.post('/api/model-catalog/custom', json={'model': 'manual-image'}, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['registered_model'], 'web-image/manual-image')
            with mock.patch.object(system_api.config, 'update') as update:
                response = client.post('/api/model-catalog/default', json={'model': 'web-image/manual-image'}, headers=headers)
                self.assertEqual(response.status_code, 200)
                update.assert_called_once_with({'default_image_model': 'web-image/manual-image'})
            response = client.request('DELETE', '/api/model-catalog/custom', json={'model': 'manual-image'}, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['custom_image_models'], [])
            self.assertEqual(client.post('/api/model-catalog/custom', json={'model': 'bad name'}, headers=headers).status_code, 400)

    def test_custom_endpoints_require_admin(self):
        app = FastAPI()
        app.include_router(system_api.create_router('test'))
        client = TestClient(app)
        for method in ('POST', 'DELETE'):
            self.assertEqual(client.request(method, '/api/model-catalog/custom', json={'model': 'test'}).status_code, 401)
            with mock.patch('api.support.require_identity', return_value={'role': 'user'}):
                self.assertEqual(client.request(method, '/api/model-catalog/custom', json={'model': 'test'}).status_code, 403)


class ImagePassthroughTests(unittest.TestCase):
    def test_upstream_unknown_model_is_reported_without_retry_or_fallback(self):
        error = UpstreamHTTPError('/backend-api/f/conversation', 404,
                                  {'error': {'code': 'model_not_found', 'message': 'private details'}})
        with mock.patch.object(conversation.account_service, 'get_available_access_token', return_value='test-token') as select, \
             mock.patch.object(conversation.account_service, 'get_account', return_value={}), \
             mock.patch.object(conversation.account_service, 'mark_image_result'), \
             mock.patch.object(conversation, 'OpenAIBackendAPI'), \
             mock.patch.object(conversation, 'stream_image_outputs', side_effect=error):
            with self.assertRaises(conversation.ImageGenerationError) as caught:
                conversation._generate_single_image(conversation.ConversationRequest(model='web-image/manual-image', prompt='test'), 1, 1)
        self.assertEqual(select.call_count, 1)
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(caught.exception.code, 'model_not_found')
        self.assertNotIn('private details', str(caught.exception))

    def test_builtins_and_custom_ids_are_exact_upstream_models(self):
        backend = object.__new__(OpenAIBackendAPI)
        for model in BUILTIN_WEB_IMAGE_MODELS:
            self.assertTrue(is_image_chat_request({'model': model}))
            self.assertEqual(split_image_model(model), (None, model))
            self.assertEqual(backend._image_model_settings(model), (model, ''))
        self.assertEqual(backend._image_model_settings('web-image/My-Future-image-max'), ('My-Future-image-max', ''))
        self.assertFalse(is_codex_image_model('web-image/codex-next-image'))

    def test_builtins_pass_exact_model_to_web_account_selector(self):
        for model in BUILTIN_WEB_IMAGE_MODELS:
            with mock.patch.object(conversation.account_service, 'get_available_access_token', side_effect=RuntimeError('stop')) as select:
                with self.assertRaises(conversation.ImageGenerationError):
                    conversation._generate_single_image(conversation.ConversationRequest(model=model, prompt='test'), 1, 1)
            self.assertEqual(select.call_args.kwargs['model'], model)

    def test_unknown_raw_image_model_is_explicit_400_without_quota(self):
        with mock.patch.object(conversation.account_service, 'get_available_access_token') as select:
            with self.assertRaises(conversation.ImageGenerationError) as caught:
                list(conversation.stream_image_outputs_with_pool(conversation.ConversationRequest(model='unknown-model', prompt='test')))
        select.assert_not_called()
        self.assertEqual(caught.exception.status_code, 400)
