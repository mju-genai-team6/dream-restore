"""장면 목록 (S3), 장면 수정 POST /scenes/{id}/revisions (S4 선택). 사용: B2"""
from fastapi import APIRouter

router = APIRouter(prefix="", tags=["scenes"])
