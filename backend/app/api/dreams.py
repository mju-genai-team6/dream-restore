"""꿈 기록 생성·조회·원문 확정·음성 업로드 (S1) / 꿈 일기 목록 (S3). 사용: B1, B2"""
from fastapi import APIRouter

router = APIRouter(prefix="/dreams", tags=["dreams"])
