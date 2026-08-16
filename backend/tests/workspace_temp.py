from __future__ import annotations

import shutil
import uuid
from pathlib import Path


class WorkspaceTempDirectory:
    """Temporary directory helper that stays inside the writable workspace."""

    def __init__(self, prefix: str = "tmp") -> None:
        root = Path(__file__).resolve().parents[1] / "data" / "test-temp"
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / f"{prefix}-{uuid.uuid4().hex}"
        self.name = str(self.path)
        self.path.mkdir(parents=True, exist_ok=False)

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)

    def __enter__(self) -> str:
        return self.name

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.cleanup()
