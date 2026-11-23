"""장면 모듈: 인터뷰가 끝난 꿈을 3~5개 장면으로 나누고 장면별 이미지 프롬프트를 만듭니다."""
from app.core.enums import ElementType
from app.llm.client import Complete, call_json, load_prompt
from app.llm.interview import NO_MEMORY
from app.llm.schemas import (
    ExtractedElement,
    InterviewAnswer,
    SceneCharacter,
    SceneSplitResult,
)


def split_scenes(
    text: str,
    answers: list[InterviewAnswer],
    elements: list[ExtractedElement],
    complete: Complete | None = None,
) -> SceneSplitResult:
    """꿈 원문, 인터뷰 답변, 인터뷰 후 요소 목록으로 장면을 나눕니다 (LLM 1회 호출).

    elements: reextract 결과의 요소 (dream_elements의 최신 목록).
    결과의 scenes를 model_dump()하면 repositories.scenes.create_scenes에 그대로 넣을 수 있습니다.
    """
    text = text.strip()
    if not text:
        raise ValueError("꿈 내용이 비어 있습니다.")
    if not elements:
        raise ValueError("요소 목록이 비어 있습니다. 인터뷰 후 재추출을 먼저 해야 합니다.")

    lines = [f"## 꿈 내용\n{text}", "", "## 되묻기 질문과 답변"]
    for i, a in enumerate(answers, start=1):
        answer = (a.answer or "").strip() or NO_MEMORY
        lines.append(f"{i}. 질문: {a.question}\n   답변: {answer}")
    lines += ["", "## 요소 목록"]
    for e in elements:
        lines.append(f"- type: {e.type.value} | name: {e.name} | description: {e.description}")

    names = {e.name for e in elements}
    person_names = {e.name for e in elements if e.type == ElementType.PERSON}
    # 그림으로 그릴 수 있는 요소(인물·장소·물건). 감정만으로는 장면을 그릴 수 없다
    visible_names = {e.name for e in elements if e.type != ElementType.EMOTION}

    def check(result: SceneSplitResult) -> None:
        """스키마로는 볼 수 없는 내용 검사. 문제가 있으면 call_json이 다시 요청합니다."""
        for scene in result.scenes:
            # 요소 목록에 없는 이름(예: 목록에 없는 "나무")은 어느 요소와도 연결할 수 없으므로 버린다 (중복도 제거)
            scene.element_names = [n for n in dict.fromkeys(scene.element_names) if n in names]
            if not scene.element_names:
                raise ValueError(
                    f"장면 {scene.order}의 element_names가 비어 있습니다. 요소 목록의 name을 글자 그대로 써 주세요: "
                    f"{sorted(names)}"
                )
            # 요소 목록에 인물·장소·물건이 하나도 없으면 이 규칙은 지킬 수 없으므로 검사하지 않는다
            if visible_names and not visible_names.intersection(scene.element_names):
                raise ValueError(
                    f"장면 {scene.order}에는 인물, 장소, 물건 요소가 하나 이상 있어야 합니다 (감정만 있음). "
                    f"이 장면에 나오는 것을 다음 중에서 골라 element_names에 넣어 주세요: {sorted(visible_names)}"
                )
        # 동물·물건을 인물로 착각해 넣는 경우가 잦다. 남는 항목은 다시 요청하지 않고 버린다 (같은 인물이 둘이면 첫 번째만)
        kept: dict[str, SceneCharacter] = {}
        for c in result.characters:
            if c.name in person_names and c.name not in kept:
                kept[c.name] = c
        result.characters = list(kept.values())
        got = [c.name for c in result.characters]
        if set(got) != person_names:
            raise ValueError(
                f"characters에 type이 person인 요소가 빠짐없이 있어야 합니다. "
                f"필요: {sorted(person_names)}, 받은 것: {got}"
            )

    return call_json(load_prompt("split_scenes"), "\n".join(lines), SceneSplitResult, complete, check)
