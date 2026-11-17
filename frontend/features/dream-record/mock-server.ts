// 백엔드를 띄우지 않고 화면을 확인할 때 쓰는 가짜 서버입니다.
// api.ts 가 fetch 대신 이 함수를 부르고, 주소와 응답 JSON, 오류 형식은 backend/app/api 와 같게 맞췄습니다.
// 진행 상황은 sessionStorage 에 두어서 새로고침해도 이어집니다.
// 주소 끝에 ?fail=stt, ?fail=llm, ?fail=save 를 붙이면 그 요청이 실패합니다.

import { mockElements, mockQuestions, mockTranscript } from "./mock-data";

type Json = Record<string, unknown>;
export type MockResponse = { status: number; body: Json };

type MockQuestion = { question_id: number; order: number; target_element: string | null; question: string; answered: boolean; skipped: boolean };
type MockElement = { element_id: number; type: string; name: string; description: string; confidence: string | null };
type MockDream = {
  dream_id: number;
  status: string;
  input_type: "voice" | "text";
  raw_text: string | null;
  confirmed_text: string | null;
  questions: MockQuestion[] | null;
  elements: MockElement[] | null;
  job_id: number | null;
};

const STORAGE_KEY = "dream-restore:b1-record-mock:v2";
let memory: Record<string, MockDream> = {};

function loadAll(): Record<string, MockDream> {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    // 저장소를 못 쓰면 메모리만 사용합니다.
  }
  return memory;
}

function save(dream: MockDream) {
  memory = { ...loadAll(), [dream.dream_id]: dream };
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(memory));
  } catch {
    // 메모리에는 저장되어 있습니다.
  }
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const fail = (kind: string) => new URLSearchParams(window.location.search).get("fail") === kind;
const error = (status: number, code: string, message: string, detail: Json = {}): MockResponse => ({
  status,
  body: { error: { code, message, detail } },
});

function progress(dream: MockDream) {
  const total = dream.questions?.length ?? 0;
  const answered = dream.questions?.filter((q) => q.answered).length ?? 0;
  return { answered, total };
}

function dreamBody(dream: MockDream): Json {
  return {
    dream_id: dream.dream_id,
    status: dream.status,
    input_type: dream.input_type,
    raw_text: dream.raw_text,
    confirmed_text: dream.confirmed_text,
    interview_progress: progress(dream),
    active_job: dream.job_id ? { job_id: dream.job_id, type: "generate_scenes", status: "queued", stage: null } : null,
    latest_render: null,
    created_at: new Date().toISOString(),
  };
}

export async function mockServer(method: string, path: string, body?: unknown): Promise<MockResponse> {
  // POST /dreams
  if (method === "POST" && path === "/dreams") {
    await wait(400);
    const input = body as { input_type: "voice" | "text"; text?: string };
    const id = Math.max(0, ...Object.keys(loadAll()).map(Number)) + 1;
    const text = input.input_type === "text" ? (input.text ?? "") : null;
    const dream: MockDream = {
      dream_id: id,
      status: "recorded",
      input_type: input.input_type,
      raw_text: text,
      confirmed_text: text, // 텍스트 입력은 생성할 때 바로 확정합니다.
      questions: null,
      elements: null,
      job_id: null,
    };
    save(dream);
    return { status: 201, body: { dream_id: id, status: dream.status } };
  }

  const match = path.match(/^\/dreams\/(\d+)(\/[a-z/]+)?$/);
  const dream = match ? loadAll()[match[1]] : undefined;
  if (!match || !dream) return error(404, "NOT_FOUND", "꿈 기록을 찾을 수 없습니다.");
  const sub = match[2] ?? "";
  const notNow = () => error(409, "INVALID_STATE", "현재 단계에서는 할 수 없는 요청입니다.", { status: dream.status });

  // GET /dreams/{id}
  if (method === "GET" && sub === "") {
    await wait(300);
    return { status: 200, body: dreamBody(dream) };
  }

  // PATCH /dreams/{id}: 원문 확정
  if (method === "PATCH" && sub === "") {
    await wait(400);
    if (dream.status !== "recorded") return notNow();
    dream.confirmed_text = (body as { confirmed_text: string }).confirmed_text;
    save(dream);
    return { status: 200, body: { dream_id: dream.dream_id, status: dream.status } };
  }

  // POST /dreams/{id}/audio: 음성 업로드 + STT
  if (method === "POST" && sub === "/audio") {
    await wait(1500);
    if (dream.input_type !== "voice" || dream.status !== "recorded") return notNow();
    if (fail("stt")) return error(502, "STT_FAILED", "음성을 텍스트로 변환하지 못했습니다. 다시 녹음하거나 텍스트로 입력해 주세요.");
    dream.raw_text = mockTranscript;
    dream.confirmed_text = null; // 다시 올리면 확정 원문을 비웁니다.
    save(dream);
    return { status: 201, body: { audio_id: Date.now(), transcript: mockTranscript } };
  }

  // GET /dreams/{id}/interview: 첫 조회 때 질문 생성, 상태 interviewing
  if (method === "GET" && sub === "/interview") {
    if (!dream.questions) {
      if (!dream.confirmed_text) return error(409, "INVALID_STATE", "원문을 먼저 확정해 주세요.");
      await wait(1500);
      if (fail("llm")) return error(502, "LLM_FAILED", "질문을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.");
      dream.questions = mockQuestions.map((q, i) => ({ ...q, question_id: i + 1, answered: false, skipped: false }));
      dream.status = "interviewing";
      save(dream);
    } else {
      await wait(300);
    }
    return { status: 200, body: { questions: dream.questions, ...progress(dream) } };
  }

  // POST /dreams/{id}/interview: 답변 또는 건너뛰기
  if (method === "POST" && sub === "/interview") {
    await wait(500);
    if (fail("save")) return error(502, "LLM_FAILED", "답변을 저장하지 못했습니다. 다시 시도해 주세요.");
    if (!dream.questions || dream.elements) return notNow();
    const input = body as { question_id: number; answer?: string; skipped?: boolean };
    const question = dream.questions.find((q) => q.question_id === input.question_id);
    if (!question) return error(404, "NOT_FOUND", "질문을 찾을 수 없습니다.");
    question.answered = true;
    question.skipped = Boolean(input.skipped);
    save(dream);
    const { answered, total } = progress(dream);
    return { status: 200, body: { remaining: total - answered, completed: answered === total } };
  }

  // GET /dreams/{id}/elements: 인터뷰가 끝난 뒤 첫 조회 때 재추출
  if (method === "GET" && sub === "/elements") {
    const { answered, total } = progress(dream);
    if (!total || answered < total) return error(409, "INVALID_STATE", "인터뷰를 먼저 끝내 주세요.");
    if (!dream.elements) {
      await wait(1500);
      dream.elements = mockElements.map((el, i) => ({ ...el, element_id: i + 1, confidence: null }));
      save(dream);
    } else {
      await wait(300);
    }
    return { status: 200, body: { elements: dream.elements } };
  }

  // PUT /dreams/{id}/elements/confidence
  if (method === "PUT" && sub === "/elements/confidence") {
    await wait(500);
    if (fail("save")) return error(502, "LLM_FAILED", "확신도를 저장하지 못했습니다. 다시 시도해 주세요.");
    if (!dream.elements || dream.job_id) return notNow();
    const items = (body as { items: { element_id: number; confidence: string }[] }).items;
    for (const item of items) {
      const el = dream.elements.find((e) => e.element_id === item.element_id);
      if (!el) return error(400, "VALIDATION_ERROR", "요소 목록에 없는 값입니다.", { element_ids: [item.element_id] });
      el.confidence = item.confidence;
    }
    save(dream);
    return { status: 200, body: { elements: dream.elements } };
  }

  // POST /dreams/{id}/jobs: 장면 생성 요청 (진행 중이면 기존 job_id)
  if (method === "POST" && sub === "/jobs") {
    await wait(800);
    if (dream.status !== "interviewing" || dream.elements?.some((e) => !e.confidence)) return notNow();
    dream.job_id ??= (Date.now() % 100000) + 1;
    save(dream);
    return { status: 202, body: { job_id: dream.job_id, type: "generate_scenes", status: "queued" } };
  }

  return error(404, "NOT_FOUND", "없는 주소입니다.");
}
