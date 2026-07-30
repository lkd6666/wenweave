from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import app.models  # noqa: F401 - register all tables used by the schema migration.
from sqlalchemy import create_engine, inspect, text

from app import bootstrap
from app.db.base import Base
from app.models.storage_config import StorageConfig
from app.services import oss_client


class ObjectStorageAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.secret = patch.object(oss_client, "_secret", return_value="test-secret")
        self.secret.start()

    def tearDown(self) -> None:
        self.secret.stop()

    @staticmethod
    def _config(provider: str) -> StorageConfig:
        return StorageConfig(
            provider=provider,
            endpoint="storage.example.com",
            bucket="test-bucket",
            access_key_id="test-key",
            access_key_secret_encrypted="encrypted",
            region_or_zone="test-region",
            upload_endpoint="upload.example.com",
            custom_domain="cdn.example.com",
        )

    def _assert_common_result_contract(self, config: StorageConfig, client: MagicMock) -> None:
        with patch.object(oss_client, "sign_read_url", return_value="https://read.example.com/key.txt"):
            oss_client.put_object_bytes(config, "key.txt", b"payload", "text/plain")
            self.assertEqual(oss_client.get_object_bytes(config, "key.txt"), b"payload")
            self.assertEqual(
                oss_client.inspect_object(config, "key.txt"),
                {"size": 7, "content_type": "text/plain", "etag": "etag"},
            )
            listed = oss_client.list_objects(config)
            self.assertEqual(listed["objects"][0]["key"], "key.txt")
            self.assertEqual(listed["prefixes"][0]["key"], "folder")
            oss_client.delete_object(config, "key.txt")

    def test_aliyun_adapter_contract(self) -> None:
        bucket = MagicMock()
        bucket.get_object.return_value = SimpleNamespace(read=lambda: b"payload")
        bucket.head_object.return_value = SimpleNamespace(
            content_length=7,
            etag="etag",
            headers={"Content-Type": "text/plain"},
        )
        bucket.list_objects.return_value = SimpleNamespace(
            object_list=[SimpleNamespace(key="key.txt", size=7, last_modified=datetime.now(timezone.utc), etag="etag")],
            prefix_list=["folder/"],
            is_truncated=False,
        )
        bucket.sign_url.return_value = "https://upload.example.com/key.txt"
        config = self._config(oss_client.ALIYUN_OSS)
        with patch.object(oss_client, "_build_alibaba_bucket", return_value=bucket):
            target = oss_client.sign_direct_upload(config, "key.txt", "text/plain")
            self.assertEqual(target["upload_method"], "PUT")
            self.assertEqual(target["upload_headers"]["Content-Type"], "text/plain")
            self.assertEqual(oss_client.sign_read_url(config, "key.txt"), "https://upload.example.com/key.txt")
            self._assert_common_result_contract(config, bucket)
        bucket.put_object.assert_called_once()
        bucket.delete_object.assert_called_once_with("key.txt")

    def test_tencent_adapter_contract(self) -> None:
        client = MagicMock()
        client.get_presigned_url.return_value = "https://upload.example.com/key.txt"
        client.get_object.return_value = {"Body": SimpleNamespace(read=lambda: b"payload")}
        client.head_object.return_value = {"Content-Length": "7", "Content-Type": "text/plain", "ETag": "etag"}
        client.list_objects.return_value = {
            "Contents": [{"Key": "key.txt", "Size": 7, "LastModified": "2026-01-01T00:00:00Z", "ETag": "etag"}],
            "CommonPrefixes": [{"Prefix": "folder/"}],
            "IsTruncated": "false",
        }
        config = self._config(oss_client.TENCENT_COS)
        with patch.object(oss_client, "_build_cos_client", return_value=client):
            target = oss_client.sign_direct_upload(config, "key.txt", "text/plain")
            self.assertEqual(target["upload_method"], "PUT")
            self.assertEqual(oss_client.sign_read_url(config, "key.txt"), "https://upload.example.com/key.txt")
            self._assert_common_result_contract(config, client)
        client.put_object.assert_called_once()
        client.delete_object.assert_called_once_with(Bucket="test-bucket", Key="key.txt")

    def test_huawei_adapter_contract(self) -> None:
        client = MagicMock()
        client.createSignedUrl.return_value = SimpleNamespace(
            signedUrl="https://upload.example.com/key.txt", actualSignedRequestHeaders={"Content-Type": "text/plain"}
        )
        client.getObject.return_value = SimpleNamespace(body=SimpleNamespace(buffer=b"payload"))
        client.getObjectMetadata.return_value = SimpleNamespace(
            body=SimpleNamespace(contentLength=7, contentType="text/plain", etag="etag")
        )
        client.listObjects.return_value = SimpleNamespace(
            body=SimpleNamespace(
                contents=[SimpleNamespace(key="key.txt", size=7, lastModified="2026-01-01T00:00:00Z", etag="etag")],
                commonPrefixes=["folder/"],
                isTruncated=False,
            )
        )
        client.putObject.return_value = SimpleNamespace(status=200)
        client.deleteObject.return_value = SimpleNamespace(status=204)
        config = self._config(oss_client.HUAWEI_OBS)
        with patch.object(oss_client, "_build_obs_client", return_value=client):
            target = oss_client.sign_direct_upload(config, "key.txt", "text/plain")
            self.assertEqual(target["upload_method"], "PUT")
            self.assertEqual(target["upload_headers"]["Content-Type"], "text/plain")
            self.assertEqual(oss_client.sign_read_url(config, "key.txt"), "https://upload.example.com/key.txt")
            self._assert_common_result_contract(config, client)
        client.putObject.assert_called_once()
        client.deleteObject.assert_called_once_with("test-bucket", "key.txt")

    def test_volcengine_adapter_contract(self) -> None:
        client = MagicMock()
        client.pre_signed_url.return_value = SimpleNamespace(
            signed_url="https://upload.example.com/key.txt", signed_header={"Content-Type": "text/plain", "host": "ignored"}
        )
        client.get_object.return_value = SimpleNamespace(read=lambda: b"payload")
        client.head_object.return_value = SimpleNamespace(content_length=7, content_type="text/plain", etag="etag")
        client.list_objects_type2.return_value = SimpleNamespace(
            contents=[SimpleNamespace(key="key.txt", size=7, last_modified="2026-01-01T00:00:00Z", etag="etag")],
            common_prefixes=[SimpleNamespace(prefix="folder/")],
            is_truncated=False,
        )
        config = self._config(oss_client.VOLCENGINE_TOS)
        with patch.object(oss_client, "_build_tos_client", return_value=client):
            target = oss_client.sign_direct_upload(config, "key.txt", "text/plain")
            self.assertEqual(target["upload_method"], "PUT")
            self.assertNotIn("host", {name.lower() for name in target["upload_headers"]})
            self.assertEqual(oss_client.sign_read_url(config, "key.txt"), "https://upload.example.com/key.txt")
            self._assert_common_result_contract(config, client)
        client.put_object.assert_called_once()
        client.delete_object.assert_called_once_with("test-bucket", "key.txt")

    def test_qiniu_adapter_contract_and_post_target(self) -> None:
        auth = MagicMock()
        auth.upload_token.return_value = "upload-token"
        auth.private_download_url.return_value = "https://read.example.com/key.txt?token=private"
        manager = MagicMock()
        manager.stat.return_value = ({"fsize": 7, "mimeType": "text/plain", "hash": "etag"}, SimpleNamespace(status_code=200))
        manager.list.return_value = (
            {"items": [{"key": "key.txt", "fsize": 7, "putTime": 1_700_000_000_000_000_0, "hash": "etag"}], "commonPrefixes": ["folder/"]},
            True,
            SimpleNamespace(status_code=200),
        )
        manager.delete.return_value = ({}, SimpleNamespace(status_code=200))
        response = SimpleNamespace(raise_for_status=MagicMock(), content=b"payload")
        config = self._config(oss_client.QINIU_KODO)
        with (
            patch.object(oss_client, "_build_qiniu_auth", return_value=auth),
            patch.object(oss_client, "_qiniu_manager", return_value=manager),
            patch.object(oss_client.qiniu, "put_data", return_value=({}, SimpleNamespace(status_code=200))),
            patch.object(oss_client.httpx, "get", return_value=response),
        ):
            target = oss_client.sign_direct_upload(config, "key.txt", "text/plain")
            self.assertEqual(target["upload_method"], "POST")
            self.assertEqual(target["upload_fields"], {"token": "upload-token", "key": "key.txt", "mimeType": "text/plain"})
            self.assertEqual(oss_client.sign_read_url(config, "key.txt"), "https://read.example.com/key.txt?token=private")
            self._assert_common_result_contract(config, manager)
        manager.delete.assert_called_once_with("test-bucket", "key.txt")

    def test_sdk_errors_are_sanitized(self) -> None:
        bucket = MagicMock()
        bucket.put_object.side_effect = RuntimeError("secret endpoint detail")
        with patch.object(oss_client, "_build_alibaba_bucket", return_value=bucket):
            with self.assertRaisesRegex(oss_client.ObjectStorageError, "阿里云 OSS上传失败") as caught:
                oss_client.put_object_bytes(self._config(oss_client.ALIYUN_OSS), "key.txt", b"payload")
        self.assertNotIn("secret endpoint detail", str(caught.exception))

    def test_connection_checks_written_content_and_cleans_up(self) -> None:
        config = self._config(oss_client.ALIYUN_OSS)
        with (
            patch.object(oss_client, "_put_bytes") as put_bytes,
            patch.object(oss_client, "get_object_bytes", return_value=b"yibanpaiban connectivity test") as get_bytes,
            patch.object(oss_client, "delete_object") as delete_object,
        ):
            success, message = oss_client.test_connection(config)
        self.assertTrue(success)
        self.assertIn("读写权限正常", message)
        put_bytes.assert_called_once()
        get_bytes.assert_called_once()
        delete_object.assert_called_once()

    def test_legacy_storage_config_migrates_to_aliyun_without_touching_the_secret(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE storage_configs"))
            connection.execute(
                text(
                    "CREATE TABLE storage_configs ("
                    "id INTEGER PRIMARY KEY, "
                    "endpoint VARCHAR(256) NOT NULL DEFAULT '', "
                    "bucket VARCHAR(256) NOT NULL DEFAULT '', "
                    "access_key_id VARCHAR(256) NOT NULL DEFAULT '', "
                    "access_key_secret_encrypted TEXT NOT NULL DEFAULT '', "
                    "custom_domain VARCHAR(256) NOT NULL DEFAULT ''"
                    ")"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO storage_configs "
                    "(id, endpoint, bucket, access_key_id, access_key_secret_encrypted, custom_domain) "
                    "VALUES (1, 'oss-cn-test.aliyuncs.com', 'test-bucket', 'test-key', 'encrypted-secret', '')"
                )
            )
        with patch.object(bootstrap, "engine", engine):
            bootstrap.migrate_schema()
        columns = {column["name"] for column in inspect(engine).get_columns("storage_configs")}
        self.assertTrue({"provider", "region_or_zone", "upload_endpoint"}.issubset(columns))
        with engine.connect() as connection:
            migrated = connection.execute(
                text("SELECT provider, access_key_secret_encrypted FROM storage_configs WHERE id = 1")
            ).one()
        self.assertEqual(migrated.provider, oss_client.ALIYUN_OSS)
        self.assertEqual(migrated.access_key_secret_encrypted, "encrypted-secret")


if __name__ == "__main__":
    unittest.main()
