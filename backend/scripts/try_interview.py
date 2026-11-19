"""인터뷰 모듈을 실제 OpenAI API로 돌려 보는 체험 스크립트 (D).

요소 추출 → 되묻기 질문에 직접 답하기 → 재추출 순서로 진행하고,
인터뷰 전후의 요소 수와 글자 수를 비교해 보여 줍니다.

실행: backend 폴더에서
    python scripts/try_interview.py
    python scripts/try_interview.py "어제 꾼 꿈 내용을 여기에 적기"

.env 에 OPENAI_API_KEY 가 있어야 합니다. 실행할 때마다 API 요금이 조금 나갑니다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.llm.client import LlmError
from app.llm.interview import extract_and_ask, reextract
from app.llm.schemas import ExtractedElement, InterviewAnswer

SAMPLE = "학교 복도를 걷고 있었는데 어둡고 길었어. 갑자기 할머니가 나타나서 우산을 줬어. 창밖을 보니까 바다였고 좀 무서웠어."


def show(title: str, elements: list[ExtractedElement]) -> None:
    print(f"\n[{title}] 요소 {len(elements)}개, 설명 글자 수 {chars(elements)}자")
    for e in elements:
        print(f"  - {e.type.value:8} {e.name}: {e.description or '(설명 없음)'}")


def chars(elements: list[ExtractedElement]) -> int:
    return sum(len(e.description) for e in elements)


def main() -> None:
    text = " ".join(sys.argv[1:]).strip() or SAMPLE
    print(f"모델: {settings.llm_model}")
    print(f"꿈 내용: {text}")

    print("\n요소를 추출하고 질문을 만드는 중...")
    first = extract_and_ask(text)
    show("인터뷰 전", first.elements)

    print("\n질문에 답해 주세요. 기억나지 않으면 그냥 Enter를 누르세요.")
    answers = []
    for q in first.questions:
        answer = input(f"\n{q.order}. {q.question}\n   답: ")
        answers.append(InterviewAnswer(question=q.question, answer=answer))

    print("\n답변을 반영해 다시 추출하는 중...")
    second = reextract(text, answers)
    show("인터뷰 후", second.elements)

    print("\n[인터뷰 효과]")
    print(f"  요소 수: {len(first.elements)} → {len(second.elements)}")
    print(f"  설명 글자 수: {chars(first.elements)} → {chars(second.elements)}")


if __name__ == "__main__":
    try:
        main()
    except LlmError as e:
        sys.exit(f"\n실패: {e}")
