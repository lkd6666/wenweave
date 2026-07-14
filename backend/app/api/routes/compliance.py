from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.compliance import ComplianceCheckRequest, ComplianceReportRead
from app.services.wechat_compliance import run_compliance_check

router = APIRouter(prefix="/api/compliance", tags=["compliance"])


@router.post("/check", response_model=ComplianceReportRead)
def check_compliance(payload: ComplianceCheckRequest, current_user: User = Depends(get_current_user)) -> dict:
    report = run_compliance_check(payload.html)
    return report.to_dict()
