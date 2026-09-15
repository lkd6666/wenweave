from typing import Any

from pydantic import BaseModel


class ComplianceCheckRequest(BaseModel):
    html: str


class ComplianceEngineRead(BaseModel):
    version: str
    commit: str
    repository: str
    available: bool
    detail: str


class ComplianceViolationItemRead(BaseModel):
    paragraphIndex: int | str | None = None
    outerHTML: str
    rules: str
    measurements: dict[str, Any]


class ComplianceViolationRead(BaseModel):
    key: str
    message: str
    items: list[ComplianceViolationItemRead]


class ComplianceReportRead(BaseModel):
    engine: ComplianceEngineRead
    isValid: bool | None
    violations: list[ComplianceViolationRead]
    warnMsgs: list[str]
    gzhStrict: dict[str, Any] | None = None
