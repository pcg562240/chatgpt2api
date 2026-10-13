from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.system as system_api
from services.account_service import AccountService
from services.model_ids import BUILTIN_WEB_IMAGE_MODELS, catalog_account_id
from services.model_service import ModelCatalogService, ModelUnavailableError
from services.openai_backend_api import OpenAIBackendAPI
from services.protocol import conversation, openai_v1_models
from services.storage.json_storage import JSONStorageBackend
from test.test_model_catalog_service import FakeBackend, model_list
from utils.helper import is_codex_image_model, is_image_chat_request, split_image_model


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.accounts = AccountService(JSONStorageBackend(Path(self.tmp.name) / 'accounts.json'))
        self.accounts.add_account_items([
            {'access_token': 'first-token-secret', 'email': 'first@example.test', 'type': 'Pro', 'quota': 10},
            {'access_token': 'second-token-secret', 'email': 'second@example.test', 'type': 'Pro', 'quota': 10},
            {'access_token': 'codex-secret', 'source_type': 'codex', 'type': 'Pro'},
        ])
        self.accounts.refresh_access_token = lambda token, **_: token
        self.first = catalog_account_id(self.accounts.get_account('first-token-secret'))
        self.second = catalog_account_id(self.accounts.get_account('second-token-secret'))
        self.calls, self.closed = [], []
        self.outcomes = {'': model_list('anonymous'), 'first-token-secret': model_list('future-8'),
                         'second-token-secret': model_list('other-9')}
        self.path = Path(self.tmp.name) / 'catalog.json'
        self.catalog = self.make_catalog()
        self.route_patch = mock.patch('services.model_service.model_catalog_service', self.catalog)
        self.route_patch.start()
        self.addCleanup(self.route_patch.stop)

    def make_catalog(self):
        return ModelCatalogService(self.accounts, cache_path=self.path,
            backend_factory=lambda access_token='': FakeBackend(access_token, self.outcomes, self.calls, self.closed))

    def test_refresh_only_selected_account_and_no_generation(self):
        result = self.catalog.refresh_account(self.second)
        self.assertEqual(self.calls, ['second-token-secret'])
        self.assertEqual(self.closed, self.calls)
        self.assertTrue(result['refreshed'])
        self.assertEqual(result['account_id'], self.second)
        self.assertEqual(result['image_models'], ['gpt-image-2', *BUILTIN_WEB_IMAGE_MODELS, 'web-image/other-9'])
        self.assertFalse(result['generation_verified'])
        self.assertEqual(len(result['accounts']), 2)  # codex not sent to web catalog

    def test_same_plan_accounts_are_not_interchangeable(self):
        self.catalog.refresh_account(self.first)
        self.catalog.refresh_account(self.second)
        self.assertEqual(self.accounts.get_text_access_token(model='future-8'), 'first-token-secret')
        route = self.catalog.route_for_model('future-8')
        self.assertEqual(route.account_ids, frozenset({self.first}))
        with mock.patch.object(self.accounts, 'fetch_remote_info', side_effect=lambda token, *_: self.accounts.get_account(token)):
            token = self.accounts.get_available_access_token(model='other-9')
        self.assertEqual(token, 'second-token-secret')
        self.accounts.release_image_slot(token)
        with self.assertRaises(ModelUnavailableError):
            self.accounts.get_available_access_token(model='not-in-catalog')

    def test_refresh_updates_existing_cache_and_removes_retired_model(self):
        self.catalog.refresh_account(self.first)
        self.outcomes['first-token-secret'] = model_list('new-model-2030')
        self.catalog.refresh_account(self.first)
        self.assertIn('web-image/new-model-2030', self.catalog.image_model_ids())
        self.assertNotIn('web-image/future-8', self.catalog.image_model_ids())
        self.assertFalse(self.catalog.route_for_model('future-8').account_ids)

    def test_empty_or_failed_refresh_retains_timestamp_and_account_selection(self):
        initial = self.catalog.refresh_account(self.second)
        for failure in [RuntimeError('Bearer secret-token upstream error'), model_list()]:
            self.outcomes['second-token-secret'] = failure
            result = self.catalog.refresh_account(self.second)
            self.assertFalse(result['refreshed'])
            self.assertEqual(result['account_id'], self.second)
            self.assertEqual(result['models'], initial['models'])
            self.assertEqual(result['updated_at'], initial['updated_at'])
            self.assertNotIn('secret-token', result['error'])

    def test_persistence_restart_and_no_account_secrets(self):
        self.catalog.refresh_account(self.first)
        text = self.path.read_text()
        for sensitive in ['first-token-secret', 'second-token-secret', '@example.test', 'access_token', 'refresh_token']:
            self.assertNotIn(sensitive, text)
            self.assertNotIn(sensitive, json.dumps(self.catalog.snapshot()))
        restored = self.make_catalog()
        self.assertEqual(restored.snapshot(self.first)['models'], self.catalog.snapshot(self.first)['models'])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_deleted_or_disabled_accounts_stop_advertising_cached_models(self):
        self.catalog.refresh_account(self.first)
        self.accounts.update_account('first-token-secret', {'status': '禁用'})
        self.assertNotIn('web-image/future-8', self.catalog.image_model_ids())
        with self.assertRaises(ValueError):
            self.catalog.refresh_account(self.first)
        self.assertNotIn('future-8', {m['id'] for m in self.catalog.list_models()['data']})

    def test_token_rotation_with_known_identity_keeps_account_id(self):
        original = self.accounts.get_account('first-token-secret')
        self.assertEqual(catalog_account_id(original), catalog_account_id({**original, 'access_token': 'rotated'}))

    def test_last_refreshed_account_selection_survives_restart(self):
        self.catalog.refresh_account(self.second)
        self.assertEqual(self.catalog.snapshot()['account_id'], self.second)
        self.assertEqual(self.make_catalog().snapshot()['account_id'], self.second)

    def test_replacing_same_count_account_invalidates_catalog(self):
        self.catalog.list_models()
        self.accounts.delete_accounts(['second-token-secret'])
        self.accounts.add_account_items([{'access_token': 'replacement', 'email': 'new@example.test', 'type': 'Pro'}])
        self.outcomes['replacement'] = model_list('replacement-model')
        ids = {item['id'] for item in self.catalog.list_models()['data']}
        self.assertIn('replacement-model', ids)
        self.assertNotIn('other-9', ids)

    def test_failed_persist_restores_last_good_memory(self):
        before = self.catalog.refresh_account(self.first)
        self.outcomes['first-token-secret'] = model_list('next-9')
        with mock.patch.object(self.catalog, '_persist', side_effect=OSError('disk full')):
            result = self.catalog.refresh_account(self.first)
        self.assertFalse(result['refreshed'])
        self.assertEqual(result['models'], before['models'])

    def test_model_ids_cannot_inject_image_aliases(self):
        self.outcomes['first-token-secret'] = model_list('new-9', 'web-image/nested', 'bad\nmodel')
        result = self.catalog.refresh_account(self.first)
        self.assertEqual([m['id'] for m in result['models']], ['new-9'])

    def test_v1_models_exposes_dynamic_alias_after_refresh(self):
        self.catalog.refresh_account(self.first)
        with mock.patch.object(openai_v1_models, 'model_catalog_service', self.catalog), \
             mock.patch.object(openai_v1_models, 'account_service', self.accounts):
            ids = {m['id'] for m in openai_v1_models.list_models()['data']}
        self.assertIn('future-8', ids)
        self.assertIn('web-image/future-8', ids)


class AliasRoutingTests(unittest.TestCase):
    def test_chat_and_image_routes_are_separate(self):
        self.assertFalse(is_image_chat_request({'model': 'future-8'}))
        self.assertTrue(is_image_chat_request({'model': 'web-image/future-8'}))
        self.assertEqual(split_image_model('web-image/Future-8-max'), (None, 'Future-8-max'))
        self.assertEqual(split_image_model('web-image/bad\nslug'), (None, None))
        self.assertFalse(is_codex_image_model('web-image/codex-gpt-image-2'))

    def test_upstream_model_passthrough_no_rewrite_or_suffix_stripping(self):
        backend = object.__new__(OpenAIBackendAPI)
        self.assertEqual(backend._image_model_settings('web-image/Future-8-max'), ('Future-8-max', ''))
        self.assertEqual(backend._image_model_settings('web-image/gpt-image-2'), ('gpt-image-2', ''))

    def test_image_pool_passes_discovered_model_to_account_selector(self):
        request = conversation.ConversationRequest(model='web-image/future-8', prompt='test')
        with mock.patch.object(conversation.account_service, 'get_available_access_token',
                               side_effect=RuntimeError('stop before quota use')) as select:
            with self.assertRaises(conversation.ImageGenerationError):
                conversation._generate_single_image(request, 1, 1)
        self.assertEqual(select.call_args.kwargs['model'], 'future-8')

    def test_unavailable_model_is_explicit_client_error_not_auto_fallback(self):
        request = conversation.ConversationRequest(model='web-image/retired-model', prompt='test')
        with mock.patch.object(conversation.account_service, 'get_available_access_token',
                               side_effect=ModelUnavailableError('retired model')):
            with self.assertRaises(conversation.ImageGenerationError) as caught:
                conversation._generate_single_image(request, 1, 1)
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(caught.exception.code, 'model_not_found')


class DiscoveryApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(system_api.create_router('test'))
        self.client = TestClient(app)
        self.headers = {'Authorization': 'Bearer chatgpt2api'}

    def test_requires_authentication(self):
        self.assertEqual(self.client.get('/api/model-catalog').status_code, 401)
        self.assertEqual(self.client.post('/api/model-catalog/refresh', json={}).status_code, 401)
        self.assertEqual(self.client.post('/api/model-catalog/default', json={'model': 'gpt-image-2'}).status_code, 401)

    def test_refresh_requires_admin(self):
        with mock.patch('api.support.require_identity', return_value={'role': 'user'}):
            self.assertEqual(self.client.post('/api/model-catalog/refresh', json={}).status_code, 403)

    def test_unknown_account_returns_400(self):
        with mock.patch.object(system_api.model_catalog_service, 'refresh_account', side_effect=ValueError('bad account')):
            response = self.client.post('/api/model-catalog/refresh', json={'account_id': 'missing'}, headers=self.headers)
        self.assertEqual(response.status_code, 400)

    def test_default_rejects_unadvertised_alias(self):
        with mock.patch.object(system_api.model_catalog_service, 'image_model_ids', return_value=[]):
            response = self.client.post('/api/model-catalog/default', json={'model': 'web-image/unknown'}, headers=self.headers)
        self.assertEqual(response.status_code, 400)

    def test_save_default_only_updates_selected_field(self):
        with mock.patch.object(system_api.model_catalog_service, 'image_model_ids', return_value=['web-image/new-9']), \
             mock.patch.object(system_api.config, 'update') as update:
            response = self.client.post('/api/model-catalog/default', json={'model': 'web-image/new-9'}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        update.assert_called_once_with({'default_image_model': 'web-image/new-9'})

    def test_api_request_defaults_are_resolved_at_request_time(self):
        from api.ai import ImageGenerationRequest
        from api.image_tasks import ImageGenerationTaskRequest
        from api.image_inputs import _payload_from_fields
        with mock.patch.dict(system_api.config.data, {'default_image_model': 'web-image/new-9'}):
            self.assertEqual(ImageGenerationRequest(prompt='test').model, 'web-image/new-9')
            self.assertEqual(ImageGenerationTaskRequest(prompt='test', client_task_id='test').model, 'web-image/new-9')
            self.assertEqual(_payload_from_fields({'prompt': 'test'})['model'], 'web-image/new-9')
