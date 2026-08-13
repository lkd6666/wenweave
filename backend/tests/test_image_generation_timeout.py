from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from pydantic import ValidationError

from app.models.image_generation import ImageGenerationPurpose, ImageGenerationSource
from app.schemas.image_generation import ImageGenerationCreate
from app.services.image_generation import create_generation, generation_payload


class ImageGenerationTimeoutTests(unittest.TestCase):
    def _payload(self, timeout_seconds: int = 180) -> dict:
        return {
            "model_id": 1,
            "prompt": "一张测试图片",
            "quantity": 1,
            "timeout_seconds": timeout_seconds,
        }

    def test_schema_defaults_to_previous_three_minute_timeout(self) -> None:
        payload = self._payload()
        payload.pop("timeout_seconds")
        self.assertEqual(ImageGenerationCreate.model_validate(payload).timeout_seconds, 180)

    def test_schema_accepts_only_supported_timeout_range(self) -> None:
        self.assertEqual(ImageGenerationCreate.model_validate(self._payload(30)).timeout_seconds, 30)
        self.assertEqual(ImageGenerationCreate.model_validate(self._payload(1800)).timeout_seconds, 1800)
        for invalid in (29, 1801):
            with self.assertRaises(ValidationError):
                ImageGenerationCreate.model_validate(self._payload(invalid))

    def test_timeout_is_persisted_and_returned_in_payload(self) -> None:
        db = MagicMock()
        generation = create_generation(
            db,
            document_id=1,
            session_id=None,
            model_id=2,
            user_id=3,
            source=ImageGenerationSource.EDITOR,
            purpose=ImageGenerationPurpose.BODY,
            prompt="一张测试图片",
            quantity=1,
            aspect_ratio="landscape",
            quality="auto",
            timeout_seconds=360,
        )

        self.assertEqual(generation.timeout_seconds, 360)
        self.assertEqual(generation_payload(generation)["timeout_seconds"], 360)
        db.add.assert_called_once_with(generation)
        db.flush.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
