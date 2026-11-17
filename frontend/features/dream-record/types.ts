// 기록 흐름 화면에서 쓰는 데이터 형식입니다.
// 값 이름은 backend/app/core/enums.py, 필드는 backend/app/schemas 를 따릅니다.

export type DreamStatus = "recorded" | "interviewing" | "scenes_ready" | "images_ready" | "rendered";
export type InputType = "voice" | "text";
export type ElementType = "person" | "place" | "object" | "emotion";
export type Confidence = "high" | "medium" | "low";

export type DreamRecord = {
  id: number;
  inputType: InputType;
  status: DreamStatus;
  // STT 결과 또는 텍스트 입력 원문
  rawText: string | null;
  // 음성 입력은 내용 확인 단계에서 확정하기 전까지 null
  confirmedText: string | null;
  interview: { answered: number; total: number };
  // 진행 중인 장면 생성 또는 영상 작업. 없거나 끝났으면 null
  activeJob: { id: number; type: string; status: string } | null;
};

export type InterviewItem = {
  questionId: number;
  order: number;
  targetElement: string | null;
  question: string;
  // 답했거나 건너뛴 질문이면 true
  answered: boolean;
  skipped: boolean;
};

export type DreamElement = {
  id: number;
  type: ElementType;
  name: string;
  description: string;
  confidence: Confidence | null;
};

export const elementTypeLabels: Record<ElementType, string> = {
  person: "인물",
  place: "장소",
  object: "물건",
  emotion: "감정",
};

// label 은 B2의 confidenceLabels(features/dream-results/types.ts)와 같은 문구입니다.
export const confidenceOptions: { value: Confidence; label: string; hint: string }[] = [
  { value: "high", label: "확실", hint: "또렷하게 기억나요" },
  { value: "medium", label: "보통", hint: "대략 기억나요" },
  { value: "low", label: "흐릿", hint: "잘 기억나지 않아요" },
];
