from fastapi import APIRouter

from app.bootstrap import get_service
from app.models.dashboard import DashboardSummary

router = APIRouter()


@router.get("/dashboard/summary", response_model=DashboardSummary)
async def dashboard_summary():
    svc = get_service("dashboard")
    return svc.build_summary()
