"""后台接口 /api/v1/admin/*，只有管理员能调。"""
from fastapi import APIRouter, Depends

from ...auth.deps import get_current_admin
from . import stats

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
)

router.include_router(stats.router)
