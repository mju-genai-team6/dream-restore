"""영상 생성 요청·최신 영상 조회 (S3). 사용: B2, 연결: E1"""
from fastapi import APIRouter

router = APIRouter(prefix="/dreams", tags=["renders"])
