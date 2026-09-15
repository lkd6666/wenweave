from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

import app.services.external_fetch as external_fetch
import app.services.image_generation as image_generation
from app.models.image_generation import ImageGenerationOperation


class _ImageModel:
    model_name = "wan2.7-image"


class _Generation:
    prompt = "一只在书桌旁的猫"
    quantity = 1
    aspect_ratio = "portrait"
    quality = "auto"
    timeout_seconds = 180


class DashScopeImageAdapterTests(unittest.TestCase):
    def test_provider_http_timeout_uses_generation_setting(self) -> None:
        provider = SimpleNamespace(
            image_protocol="openai_images",
            image_base_url="https://api.example.test/v1",
            api_key_encrypted="encrypted",
        )
        model = SimpleNamespace(provider=provider)
        generation = SimpleNamespace(timeout_seconds=420)
        client = MagicMock()
        client_context = MagicMock()
        client_context.__aenter__ = AsyncMock(return_value=client)
        client_context.__aexit__ = AsyncMock(return_value=None)
        expected = image_generation.ProviderGenerationResult(images=(), usage={})

        async def run() -> None:
            with (
                patch.object(image_generation, "decrypt_secret", return_value="key"),
                patch.object(image_generation.httpx, "AsyncClient", return_value=client_context) as constructor,
                patch.object(image_generation, "_openai_images", new=AsyncMock(return_value=expected)),
            ):
                result = await image_generation._call_provider_once(model, generation)
                self.assertIs(result, expected)
                timeout = constructor.call_args.kwargs["timeout"]
                self.assertEqual(timeout.read, 420.0)
                self.assertEqual(timeout.connect, 20.0)

        asyncio.run(run())

    def test_overall_provider_deadline_becomes_clear_generation_error(self) -> None:
        async def slow_provider(*_args, **_kwargs) -> image_generation.ProviderGenerationResult:
            await asyncio.sleep(1)
            return image_generation.ProviderGenerationResult(images=(), usage={})

        async def run() -> None:
            generation = SimpleNamespace(timeout_seconds=30)
            with (
                patch.object(image_generation, "_generation_timeout_seconds", return_value=0.01),
                patch.object(image_generation, "_call_provider", new=slow_provider),
            ):
                with self.assertRaisesRegex(image_generation.ImageGenerationError, "超过指定的 0.01 秒"):
                    await image_generation._call_provider_with_timeout(object(), generation)  # type: ignore[arg-type]

        asyncio.run(run())

    def test_openai_images_endpoint_accepts_root_version_resource_and_exact_endpoint(self) -> None:
        expected_generation = "https://api.example.test/v1/images/generations"
        expected_edit = "https://api.example.test/v1/images/edits"
        for configured_url in (
            "https://api.example.test/v1",
            "https://api.example.test/v1/images",
            "https://api.example.test/v1/images/generations",
            "https://api.example.test/v1/images/edits",
        ):
            self.assertEqual(image_generation._openai_images_endpoint(configured_url, "generate"), expected_generation)
            self.assertEqual(image_generation._openai_images_endpoint(configured_url, "edit"), expected_edit)

    def test_openai_edit_uses_multipart_reference_image(self) -> None:
        request_holder: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            request_holder.append(request)
            return httpx.Response(200, json={"data": [{"b64_json": "aGVsbG8="}]})

        async def run() -> image_generation.ProviderGenerationResult:
            generation = SimpleNamespace(
                prompt="改为水彩风格",
                quantity=1,
                aspect_ratio="square",
                quality="auto",
                operation=ImageGenerationOperation.EDIT,
            )
            model = SimpleNamespace(model_name="gpt-image-1")
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await image_generation._openai_images(client, "https://api.example.test/v1", "key", model, generation, source_data=b"source")

        result = asyncio.run(run())
        self.assertEqual(len(result.images), 1)
        self.assertEqual(str(request_holder[0].url), "https://api.example.test/v1/images/edits")
        self.assertIn("multipart/form-data", request_holder[0].headers["content-type"])
        self.assertIn(b"\xe6\x94\xb9\xe4\xb8\xba\xe6\xb0\xb4\xe5\xbd\xa9\xe9\xa3\x8e\xe6\xa0\xbc", request_holder[0].content)

    def test_current_application_check_uses_live_body_and_cover_references(self) -> None:
        url = "https://cdn.example.test/image.png?signature=a&expires=1"
        self.assertTrue(
            image_generation.asset_is_currently_applied(
                url,
                '<p><img src="https://cdn.example.test/image.png?signature=a&amp;expires=1"></p>',
            )
        )
        self.assertTrue(image_generation.asset_is_currently_applied(url, cover_url=url))
        self.assertFalse(image_generation.asset_is_currently_applied(url, f'<p data-previous-src="{url}">已替换</p>'))
        self.assertFalse(image_generation.asset_is_currently_applied(url, "<p>图片已被替换</p>"))

    def test_provider_retries_when_endpoint_returns_fewer_images_than_requested(self) -> None:
        generation = _Generation()
        generation.quantity = 3
        responses = [
            image_generation.ProviderGenerationResult(
                images=(image_generation.ProviderImage(data=b"one"),), usage={"images": 1}
            ),
            image_generation.ProviderGenerationResult(
                images=(image_generation.ProviderImage(data=b"two"),), usage={"images": 1}
            ),
            image_generation.ProviderGenerationResult(
                images=(image_generation.ProviderImage(data=b"three"),), usage={"images": 1}
            ),
        ]

        async def run() -> image_generation.ProviderGenerationResult:
            with patch.object(image_generation, "_call_provider_once", new=AsyncMock(side_effect=responses)) as call:
                result = await image_generation._call_provider(object(), generation)  # type: ignore[arg-type]
                self.assertEqual(call.await_count, 3)
                return result

        result = asyncio.run(run())
        self.assertEqual(len(result.images), 3)
        self.assertEqual(result.usage["images"], 3)

    def test_provider_drops_repeated_image_urls_from_batch(self) -> None:
        generation = _Generation()
        generation.quantity = 3
        repeated = image_generation.ProviderGenerationResult(
            images=(
                image_generation.ProviderImage(url="https://cdn.example/same.png?signature=one"),
                image_generation.ProviderImage(url="https://cdn.example/same.png?signature=two"),
            ),
            usage={"images": 2},
        )

        async def run() -> image_generation.ProviderGenerationResult:
            with patch.object(image_generation, "_call_provider_once", new=AsyncMock(return_value=repeated)):
                return await image_generation._call_provider(object(), generation)  # type: ignore[arg-type]

        result = asyncio.run(run())
        self.assertEqual([item.url for item in result.images], ["https://cdn.example/same.png?signature=one"])

    def test_parses_native_dashscope_message_image(self) -> None:
        payload = {
            "output": {
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "image", "image": "https://example.test/generated.png"}
                            ]
                        }
                    }
                ]
            }
        }
        images = image_generation._images_from_payload(payload)
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].url, "https://example.test/generated.png")

    def test_trusts_only_dashscope_result_hosts_for_desktop_proxy(self) -> None:
        hosts = (
            "dashscope-result-bj.oss-cn-beijing.aliyuncs.com",
            "dashscope-7c2c.oss-accelerate.aliyuncs.com",
        )
        for host in hosts:
            trusted_hosts = image_generation._trusted_provider_image_hosts(f"https://{host}/image.png")
            self.assertEqual(trusted_hosts, frozenset({host}))
            self.assertTrue(external_fetch._is_allowed_address(host, "198.18.0.185", trusted_hosts))

        trusted_hosts = image_generation._trusted_provider_image_hosts(f"https://{hosts[0]}/image.png")
        self.assertFalse(
            external_fetch._is_allowed_address("untrusted.example.test", "198.18.0.185", trusted_hosts)
        )
        self.assertFalse(
            external_fetch._is_allowed_address("bucket.oss-cn-beijing.aliyuncs.com", "198.18.0.185", trusted_hosts)
        )

    def test_token_plan_uses_native_wan27_route_and_messages(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.method == "POST":
                return httpx.Response(200, json={"output": {"task_id": "task-1", "task_status": "PENDING"}})
            return httpx.Response(
                200,
                json={
                    "output": {
                        "task_id": "task-1",
                        "task_status": "FAILED",
                        "message": "test failure",
                    }
                },
            )

        async def run() -> None:
            original_interval = image_generation.POLL_INTERVAL_SECONDS
            image_generation.POLL_INTERVAL_SECONDS = 0
            try:
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    with self.assertRaises(image_generation.ImageGenerationError):
                        await image_generation._dashscope_images(
                            client,
                            "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
                            "test-key",
                            _ImageModel(),
                            _Generation(),
                        )
            finally:
                image_generation.POLL_INTERVAL_SECONDS = original_interval

        asyncio.run(run())
        self.assertGreaterEqual(len(requests), 2)
        self.assertEqual(
            str(requests[0].url),
            "https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/image-generation/generation",
        )
        body = json.loads(requests[0].content)
        self.assertEqual(body["model"], "wan2.7-image")
        self.assertEqual(body["input"]["messages"][0]["content"][0]["text"], _Generation.prompt)
        self.assertEqual(body["parameters"]["size"], "720*1280")
        self.assertEqual(requests[0].headers.get("X-DashScope-Async"), "enable")
        self.assertEqual(
            str(requests[1].url),
            "https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1/tasks/task-1",
        )


if __name__ == "__main__":
    unittest.main()
