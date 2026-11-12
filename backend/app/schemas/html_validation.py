from typing import Literal

from pydantic import BaseModel, Field


class HtmlValidationIssueRead(BaseModel):
    code: str
    message: str
    line: int | None = None
    column: int | None = None
    tag: str = ""
    severity: Literal["error", "warning"] = "error"


class HtmlValidationReportRead(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    issues: list[HtmlValidationIssueRead] = Field(default_factory=list)
