from __future__ import annotations

import base64
import json
from io import BytesIO
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from api import ai
from api.errors import install_exception_handlers
from services.image_output import normalize_image_output, parse_output_size
from services.protocol import conversation


def png(size=(1254, 1254), mode="RGB", color="orange"):
    output = BytesIO()
    Image.new(mode, size, color).save(output, format="PNG")
    return output.getvalue()


def image_size(payload):
    with Image.open(BytesIO(payload)) as image:
        image.load()
        return image.size


class ImageOutputContractTests(unittest.TestCase):
    def test_parse_explicit_sizes_and_native(self):
        for value, expected in [("512x512", (512, 512)), ("768x768", (768, 768)),
                                ("3840x2160", (3840, 2160)), (" 512X768 ", (512, 768)),
                                (None, None), ("auto", None), ("", None)]:
            with self.subTest(value=value):
                self.assertEqual(parse_output_size(value), expected)

    def test_reject_invalid_or_unbounded_sizes(self):
        for value in ("0x512", "-1x512", "512", "512x", "512x512extra", "4097x512",
                      "10000x10000", 512, True, {"width": 512}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_output_size(value)

    def test_requested_512_and_768_pixels_are_exact(self):
        for edge in (512, 768):
            with self.subTest(edge=edge):
                payload, metadata = normalize_image_output(png(), f"{edge}x{edge}")
                self.assertEqual(image_size(payload), (edge, edge))
                self.assertEqual(metadata["original_size"], "1254x1254")
                self.assertTrue(metadata["resized"])
                self.assertEqual(metadata["size_processing"], "server_resize_pad")

    def test_auto_and_omitted_size_preserve_original_bytes(self):
        original = png()
        for size in (None, "auto", ""):
            self.assertEqual(normalize_image_output(original, size), (original, {}))

    def test_already_matching_size_is_not_reencoded(self):
        original = png((512, 512))
        payload, metadata = normalize_image_output(original, "512x512")
        self.assertEqual(payload, original)
        self.assertFalse(metadata["resized"])
        self.assertEqual(metadata["size_processing"], "upstream")

    def test_rectangular_target_is_exact(self):
        payload, _ = normalize_image_output(png(), "512x768")
        self.assertEqual(image_size(payload), (512, 768))

    def test_padding_preserves_composition_without_stretching_or_cropping(self):
        payload, _ = normalize_image_output(png((200, 100), color="blue"), "100x100")
        with Image.open(BytesIO(payload)) as image:
            self.assertEqual(image.getpixel((50, 0)), (255, 255, 255))
            self.assertEqual(image.getpixel((50, 50)), (0, 0, 255))
            self.assertEqual(image.size, (100, 100))

    def test_transparency_survives_resize_and_padding(self):
        payload, _ = normalize_image_output(png((200, 100), "RGBA", (255, 0, 0, 128)), "100x100")
        with Image.open(BytesIO(payload)) as image:
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.getpixel((50, 0))[3], 0)
            self.assertEqual(image.getpixel((50, 50))[3], 128)

    def test_exif_orientation_does_not_break_pixel_size_contract(self):
        image = Image.new("RGB", (200, 100), "blue")
        exif = image.getexif()
        exif[274] = 6
        buf = BytesIO()
        image.save(buf, format="JPEG", exif=exif)
        payload, _ = normalize_image_output(buf.getvalue(), "100x200")
        self.assertEqual(image_size(payload), (100, 200))

    def test_base64_and_url_store_identical_normalized_bytes(self):
        with mock.patch.object(conversation, "save_image_bytes", return_value="http://local/image.png") as save:
            result = conversation.format_image_result(
                [{"b64_json": base64.b64encode(png()).decode()}], "cat", "b64_json",
                size="512x512", max_images=1)
        item = result["data"][0]
        output = base64.b64decode(item["b64_json"])
        self.assertEqual(image_size(output), (512, 512))
        self.assertEqual(save.call_args.args[0], output)
        self.assertEqual(item["original_size"], "1254x1254")

    def test_url_only_response_saves_correct_pixels(self):
        with mock.patch.object(conversation, "save_image_bytes", return_value="http://local/image.png") as save:
            result = conversation.format_image_result(
                [{"b64_json": base64.b64encode(png()).decode()}], "cat", "url",
                size="768x768", max_images=1)
        self.assertNotIn("b64_json", result["data"][0])
        self.assertEqual(image_size(save.call_args.args[0]), (768, 768))

    def test_extra_upstream_images_are_not_decoded_or_saved(self):
        items = [{"b64_json": base64.b64encode(png()).decode()}, {"b64_json": "invalid-unused-extra"}]
        with mock.patch.object(conversation, "save_image_bytes", return_value="http://local/image.png") as save:
            result = conversation.format_image_result(items, "cat", "b64_json", size="512x512", max_images=1)
        self.assertEqual(len(result["data"]), 1)
        save.assert_called_once()

    def test_invalid_upstream_image_is_not_returned_as_success(self):
        with mock.patch.object(conversation, "save_image_bytes") as save:
            with self.assertRaises(conversation.ImageGenerationError) as error:
                conversation.format_image_result(
                    [{"b64_json": base64.b64encode(b"not an image").decode()}],
                    "cat", "b64_json", size="512x512", max_images=1)
        self.assertEqual(error.exception.code, "invalid_image")
        save.assert_not_called()

    def test_codex_duplicate_results_produce_one_correctly_sized_image(self):
        data = base64.b64encode(png()).decode()
        backend = mock.Mock()
        backend.iter_codex_image_response_events.return_value = [
            {"type": "image_generation_call", "result": data},
            {"type": "image_generation_call", "result": data}]
        request = conversation.ConversationRequest(model="codex-gpt-image-2", prompt="cat", size="768x768")
        with mock.patch.object(conversation, "save_image_bytes", return_value="http://local/image.png"):
            outputs = list(conversation.stream_codex_image_outputs(backend, request))
        self.assertEqual(len(outputs[0].data), 1)
        self.assertEqual(image_size(base64.b64decode(outputs[0].data[0]["b64_json"])), (768, 768))

    def test_web_worker_downloads_and_returns_one_image(self):
        backend = mock.Mock()
        backend.resolve_conversation_image_urls.return_value = ["https://local/first", "https://local/second"]
        backend.download_image_bytes.return_value = [png()]
        events = [{"type": "conversation.done", "conversation_id": "c", "file_ids": ["first", "second"]}]
        request = conversation.ConversationRequest(model="gpt-image-2", prompt="cat", size="512x512")
        with (mock.patch.object(conversation, "conversation_events", return_value=iter(events)),
              mock.patch.object(conversation, "save_image_bytes", return_value="http://local/image.png")):
            outputs = list(conversation.stream_image_outputs(backend, request))
        backend.download_image_bytes.assert_called_once_with(["https://local/first"])
        results = [output for output in outputs if output.kind == "result"]
        self.assertEqual(len(results[0].data), 1)
        self.assertEqual(image_size(base64.b64decode(results[0].data[0]["b64_json"])), (512, 512))

    def test_n_workers_return_n_images_in_serial_and_parallel_modes(self):
        def worker(request, index, total):
            data = conversation.format_image_result(
                [{"b64_json": base64.b64encode(png()).decode()}] * 2,
                request.prompt, "b64_json", size=request.size, max_images=1)["data"]
            return [conversation.ImageOutput(kind="result", model=request.model, index=index, total=total, data=data)]
        for parallel in (False, True):
            with self.subTest(parallel=parallel):
                request = conversation.ConversationRequest(model="gpt-image-2", prompt="cat", n=3, size="512x512")
                with (mock.patch.dict(conversation.config.data, {"image_parallel_generation": parallel}),
                      mock.patch.object(conversation, "_generate_single_image", side_effect=worker),
                      mock.patch.object(conversation, "save_image_bytes", return_value="http://local/image.png")):
                    result = conversation.collect_image_outputs(conversation.stream_image_outputs_with_pool(request))
                self.assertEqual(len(result["data"]), 3)
                self.assertTrue(all(image_size(base64.b64decode(item["b64_json"])) == (512, 512) for item in result["data"]))

    def test_invalid_size_http_400_before_account_acquisition_for_stream_and_json(self):
        app = FastAPI()
        install_exception_handlers(app)
        app.include_router(ai.create_router())
        client = TestClient(app)
        for stream in (False, True):
            with self.subTest(stream=stream):
                with (mock.patch.object(ai, "require_identity", return_value={"id": "test", "role": "admin"}),
                      mock.patch.object(conversation.account_service, "get_available_access_token") as acquire):
                    response = client.post("/v1/images/generations", json={
                        "prompt": "cat", "size": "9999x9999", "stream": stream})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "invalid_size")
                self.assertEqual(response.json()["error"]["param"], "size")
                acquire.assert_not_called()

    def test_successful_json_and_streaming_api_enforce_pixels_and_count(self):
        def worker(request, index, total):
            data = conversation.format_image_result(
                [{"b64_json": base64.b64encode(png()).decode()}] * 2,
                request.prompt, request.response_format, size=request.size, max_images=1)["data"]
            return [conversation.ImageOutput(kind="result", model=request.model, index=index, total=total, data=data)]
        app = FastAPI()
        install_exception_handlers(app)
        app.include_router(ai.create_router())
        client = TestClient(app)
        for stream in (False, True):
            with self.subTest(stream=stream):
                with (mock.patch.object(ai, "require_identity", return_value={"id": "test", "role": "admin"}),
                      mock.patch.object(conversation, "_generate_single_image", side_effect=worker),
                      mock.patch.object(conversation, "save_image_bytes", return_value="http://local/image.png")):
                    response = client.post("/v1/images/generations", json={
                        "prompt": "cat", "size": "512x512", "n": 1, "stream": stream})
                self.assertEqual(response.status_code, 200)
                if stream:
                    chunks = [json.loads(line[5:].strip()) for line in response.text.splitlines()
                              if line.startswith("data:") and line[5:].strip() != "[DONE]"]
                    items = [item for chunk in chunks for item in chunk.get("data", [])]
                else:
                    items = response.json()["data"]
                self.assertEqual(len(items), 1)
                self.assertEqual(image_size(base64.b64decode(items[0]["b64_json"])), (512, 512))
                self.assertEqual(items[0]["size_processing"], "server_resize_pad")


if __name__ == "__main__":
    unittest.main()
