from datetime import datetime

from pydantic import BaseModel, Field


class StorageConfigRead(BaseModel):
    configured: bool
    endpoint: str
    bucket: str
    access_key_id: str
    access_key_secret_masked: str
    custom_domain: str


class StorageConfigUpdate(BaseModel):
    endpoint: str = Field(min_length=1, max_length=256)
    bucket: str = Field(min_length=1, max_length=256)
    access_key_id: str = Field(min_length=1, max_length=256)
    access_key_secret: str | None = None  # 留空表示不修改现有密钥
    custom_domain: str = ""


class StorageTestResult(BaseModel):
    success: bool
    message: str


class StorageDirectUploadCheck(BaseModel):
    object_key: str
    upload_url: str
    content_type: str
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
