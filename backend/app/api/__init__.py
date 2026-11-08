from fastapi import APIRouter

from app.api import dreams, elements, events, interview, jobs, renders, scenes

router = APIRouter()
for module in (dreams, interview, elements, jobs, events, scenes, renders):
    router.include_router(module.router)

# 선택 기능 (S4): world, evaluations, revisions
