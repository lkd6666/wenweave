from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


StorageProvider = Literal["aliyun_oss", "tencent_cos", "huawei_obs", "volcengine_tos", "qiniu_kodo"]


class StorageConfigRead(BaseModel):
    configured: bool
    provider: StorageProvider
    endpoint: str
    bucket: str
    access_key_id: str
    access_key_secret_masked: str
    region_or_zone: str
    upload_endpoint: str
    custom_domain: str


class StorageConfigUpdate(BaseModel):
    provider: StorageProvider = "aliyun_oss"
    endpoint: str = Field(min_length=1, max_length=256)
    bucket: str = Field(min_length=1, max_length=256)
    access_key_id: str = Field(min_length=1, max_length=256)
    access_key_secret: str | None = None  # 留空表示不修改现有密钥
    region_or_zone: str = Field(default="", max_length=128)
    upload_endpoint: str = Field(default="", max_length=256)
    custom_domain: str = ""


class StorageTestResult(BaseModel):
    success: bool
    message: str


class StorageDirectUploadCheck(BaseModel):
    object_key: str
    upload_url: str
    content_type: str
    upload_method: Literal["PUT", "POST"] = "PUT"
    upload_headers: dict[str, str] = Field(default_factory=dict)
    upload_fields: dict[str, str] = Field(default_factory=dict)
    file_field_name: str = "file"
    expected_size: int
    expires_in_seconds: int


class StorageDirectUploadCheckVerify(BaseModel):
    object_key: str


class StorageImageRepairResult(BaseModel):
    repaired_count: int
    message: str


class StorageObjectRead(BaseModel):
    key: str
    name: str
    size: int
    last_modified: datetime | None = None
    etag: str = ""
    thumbnail_url: str | None = None


class StoragePrefixRead(BaseModel):
    key: str
    name: str


class StorageObjectListResult(BaseModel):
    objects: list[StorageObjectRead] = Field(default_factory=list)
    prefixes: list[StoragePrefixRead] = Field(default_factory=list)
    next_marker: str | None = None


class StorageObjectUrlResult(BaseModel):
    url: str
    expires_in_seconds: int
