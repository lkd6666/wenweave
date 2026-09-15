import io
import unittest

from PIL import Image

from app.services.document_image_transform import (
    CROP_RECT_SCALE,
    CropRect,
    DocumentImageTransformError,
    read_document_image_dimensions,
    transform_document_image,
)


def _png_with_distinct_pixels() -> bytes:
    """A 2x3 raster whose location is easy to assert after rotation."""
    image = Image.new("RGB", (2, 3))
    image.putdata([
        (255, 0, 0), (0, 255, 0),
        (0, 0, 255), (255, 255, 0),
        (255, 0, 255), (0, 255, 255),
    ])
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _opened(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as source:
        return source.convert("RGB")


class DocumentImageTransformTests(unittest.TestCase):
    def test_clockwise_rotation_bakes_expected_pixels_and_dimensions(self) -> None:
        transformed = transform_document_image(_png_with_distinct_pixels(), rotation_degrees=90)

        self.assertEqual((transformed.width, transformed.height), (3, 2))
        self.assertEqual(transformed.content_type, "image/png")
        # 90° clockwise: left column bottom-to-top becomes the top row.
        self.assertEqual(list(_opened(transformed.data).getdata()), [
            (255, 0, 255), (0, 0, 255), (255, 0, 0),
            (0, 255, 255), (255, 255, 0), (0, 255, 0),
        ])

    def test_180_and_270_degree_rotations_bake_expected_pixels(self) -> None:
        rotated_180 = transform_document_image(_png_with_distinct_pixels(), rotation_degrees=180)
        self.assertEqual((rotated_180.width, rotated_180.height), (2, 3))
        self.assertEqual(list(_opened(rotated_180.data).getdata()), [
            (0, 255, 255), (255, 0, 255),
            (255, 255, 0), (0, 0, 255),
            (0, 255, 0), (255, 0, 0),
        ])

        rotated_270 = transform_document_image(_png_with_distinct_pixels(), rotation_degrees=270)
        self.assertEqual((rotated_270.width, rotated_270.height), (3, 2))
        self.assertEqual(list(_opened(rotated_270.data).getdata()), [
            (0, 255, 0), (255, 255, 0), (0, 255, 255),
            (255, 0, 0), (0, 0, 255), (255, 0, 255),
        ])

    def test_crop_coordinates_describe_the_rotated_image(self) -> None:
        transformed = transform_document_image(
            _png_with_distinct_pixels(),
            rotation_degrees=90,
            crop=CropRect(0, 0, CROP_RECT_SCALE // 2, CROP_RECT_SCALE),
        )

        # The 3x2 rotated image rounds its first 50% to the first two columns.
        self.assertEqual((transformed.width, transformed.height), (2, 2))
        self.assertEqual(list(_opened(transformed.data).getdata()), [
            (255, 0, 255), (0, 0, 255),
            (0, 255, 255), (255, 255, 0),
        ])

    def test_bmp_is_written_as_jpeg_and_gif_is_rejected(self) -> None:
        source = Image.new("RGB", (2, 1), "red")
        bmp = io.BytesIO()
        source.save(bmp, format="BMP")
        transformed = transform_document_image(bmp.getvalue(), rotation_degrees=180)
        self.assertEqual(transformed.content_type, "image/jpeg")

        gif = io.BytesIO()
        source.save(gif, format="GIF")
        with self.assertRaisesRegex(DocumentImageTransformError, "GIF"):
            transform_document_image(gif.getvalue(), rotation_degrees=90)

    def test_invalid_geometry_and_noop_are_rejected(self) -> None:
        source = _png_with_distinct_pixels()
        with self.assertRaisesRegex(DocumentImageTransformError, "裁剪范围超出"):
            transform_document_image(source, crop=CropRect(50_001, 0, 50_000, 100_000))
        with self.assertRaisesRegex(DocumentImageTransformError, "请提供"):
            transform_document_image(source)
        with self.assertRaisesRegex(DocumentImageTransformError, "仅支持"):
            transform_document_image(source, rotation_degrees=45)

    def test_dimension_reader_returns_real_png_dimensions(self) -> None:
        self.assertEqual(read_document_image_dimensions(_png_with_distinct_pixels()), ("image/png", 2, 3))
