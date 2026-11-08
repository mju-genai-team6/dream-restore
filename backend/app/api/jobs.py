"""장면 생성 요청 POST /dreams/{id}/jobs, 작업 조회 GET /jobs/{id} (S2). 사용: B1, B2"""
from fastapi import APIRouter

router = APIRouter(prefix="", tags=["jobs"])
