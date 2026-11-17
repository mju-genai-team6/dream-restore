// 예시 모드(mock-server.ts)에서 쓰는 데이터입니다. 질문과 요소는 docs/schemas/examples 의 예시 JSON 을 옮겼습니다.

// 음성을 올리면 STT 결과로 돌려주는 글
export const mockTranscript =
  "학교 복도를 걷고 있었는데 형광등이 계속 깜빡였어. 갑자기 할머니가 나타나서 우산을 줬어. " +
  "창밖을 봤더니 학교 밖이 전부 바다였고 파도가 엄청 높아서 무서웠어.";

// interview.json 의 questions
export const mockQuestions: { order: number; target_element: string | null; question: string }[] = [
  { order: 1, target_element: "학교 복도", question: "복도에서 기억나는 것을 자유롭게 말해 주세요." },
  { order: 2, target_element: "할머니", question: "할머니는 어떤 모습이었나요?" },
  { order: 3, target_element: "할머니", question: "할머니가 무언가 말을 했나요? 기억나는 대로 말해 주세요." },
  { order: 4, target_element: "우산", question: "우산은 어떻게 생겼나요?" },
  { order: 5, target_element: "바다", question: "바다를 봤을 때 주변은 어땠나요?" },
  { order: 6, target_element: null, question: "꿈이 어떻게 끝났는지 기억나나요?" },
];

// elements.json (인터뷰 답변을 반영한 요소)
export const mockElements: { type: "person" | "place" | "object" | "emotion"; name: string; description: string }[] = [
  { type: "place", name: "학교 복도", description: "어둡고 긴 복도, 형광등이 깜빡임" },
  { type: "person", name: "할머니", description: "흰 머리에 분홍색 카디건을 입음" },
  { type: "object", name: "우산", description: "노란색 장우산" },
  { type: "place", name: "바다", description: "창밖으로 보인 회색 바다, 파도가 높음" },
  { type: "emotion", name: "두려움", description: "바다를 보고 무서웠음" },
  { type: "emotion", name: "안도감", description: "우산을 받고 마음이 놓임" },
];
