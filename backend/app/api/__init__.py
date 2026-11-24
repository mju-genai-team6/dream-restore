from fastapi import APIRouter

from app.api import dreams, elements, interview, jobs, renders, scenes

router = APIRouter()
for module in (dreams, interview, elements, jobs, scenes, renders):
    router.include_router(module.router)

# 선택 기능 (S4): world, evaluations, revisions
