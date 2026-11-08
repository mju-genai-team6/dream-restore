"""진행 상태 SSE GET /dreams/{id}/events (S2). 사용: B2"""
from fastapi import APIRouter

router = APIRouter(prefix="/dreams", tags=["events"])
