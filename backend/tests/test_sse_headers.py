import unittest

from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

from app.api.sse import SSE_RESPONSE_HEADERS


async def _empty_event_stream():
    if False:
        yield None


class SseResponseHeadersTests(unittest.TestCase):
    def test_headers_prohibit_storage_and_response_transforms(self) -> None:
        cache_control = SSE_RESPONSE_HEADERS["Cache-Control"]

        self.assertIn("no-store", cache_control)
        self.assertIn("no-transform", cache_control)
        self.assertEqual(SSE_RESPONSE_HEADERS["Surrogate-Control"], "no-store")
        self.assertEqual(SSE_RESPONSE_HEADERS["X-Accel-Buffering"], "no")

    def test_sse_response_types_preserve_cache_controls(self) -> None:
        for response in (
            EventSourceResponse(_empty_event_stream(), headers=SSE_RESPONSE_HEADERS),
            StreamingResponse(_empty_event_stream(), media_type="text/event-stream", headers=SSE_RESPONSE_HEADERS),
        ):
            self.assertEqual(response.headers["cache-control"], SSE_RESPONSE_HEADERS["Cache-Control"])
            self.assertEqual(response.headers["surrogate-control"], "no-store")
            self.assertEqual(response.headers["x-accel-buffering"], "no")
