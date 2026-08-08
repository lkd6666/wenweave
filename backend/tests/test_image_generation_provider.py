from __future__ import annotations

import asyncio
import json
import unittest

import httpx

import app.services.external_fetch as external_fetch
import app.services.image_generation as image_generation


class _ImageModel:
    model_name = "wan2.7-image"


class _Generation:
    prompt = "一只在书桌旁的猫"
    quantity = 1
    aspect_ratio = "portrait"
    quality = "auto"


class DashScopeImageAdapterTests(unittest.TestCase):
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
