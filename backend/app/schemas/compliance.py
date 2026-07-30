from typing import Any

from pydantic import BaseModel


class ComplianceCheckRequest(BaseModel):
    html: str


class ComplianceDiagnosticRead(BaseModel):
    code: str
    severity: str
    path: str
    line: int
    column: int
    snippet: str
    message: str
    consequence: str
    suggestion: str


class ComplianceReportRead(BaseModel):
    removedClasses: list[str]
    keptClasses: list[str]
    removedIdAttributes: list[str]
    riskStyleHints: list[str]
    bannedTags: list[str]
    consecutiveBrRuns: list[int]
    svgIdAttributes: list[str]
    imageIssues: list[str]
    removedSvgBrs: int
    hasSvg: bool
    oversizedSvgBlocks: list[int]
    maxNestingDepth: int
    willFlattenNesting: bool
    emptyNodeSuspects: list[str]
    diagnostics: list[ComplianceDiagnosticRead]
    hasError: bool
    hasWarning: bool
    gzhStrict: dict[str, Any] | None = None
