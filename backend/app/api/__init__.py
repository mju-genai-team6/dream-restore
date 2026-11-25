from fastapi import APIRouter

from app.api import dreams, elements, interview, jobs, renders, scenes, world

router = APIRouter()
for module in (dreams, interview, elements, jobs, scenes, renders, world):
    router.include_router(module.router)

# 선택 기능 (S4): evaluations, revisions
