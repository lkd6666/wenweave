from pydantic import BaseModel


class ComplianceCheckRequest(BaseModel):
    html: str


class ComplianceReportRead(BaseModel):
    removedClasses: list[str]
    keptClasses: list[str]
    removedIdAttributes: list[str]
    riskStyleHints: list[str]
    removedSvgBrs: int
    hasSvg: bool
    oversizedSvgBlocks: list[int]
    maxNestingDepth: int
    willFlattenNesting: bool
    emptyNodeSuspects: list[str]
    hasError: bool
    hasWarning: bool
