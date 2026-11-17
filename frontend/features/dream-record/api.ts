// 기록 흐름 화면이 서버에 보내는 요청을 모아 둔 파일입니다. 화면 코드는 여기 있는 함수만 부릅니다.
// frontend/.env.local 에 NEXT_PUBLIC_API_BASE_URL 이 있으면 실제 서버로, 없으면 mock-server.ts 로 보냅니다.
// 서버 응답(snake_case)은 여기서 types.ts 형식(camelCase)으로 바꿉니다.

import { mockServer } from "./mock-server";
import type { Confidence, DreamElement, DreamRecord, ElementType, InputType, InterviewItem } from "./types";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");
export const USE_MOCK = !API_BASE;

// 백엔드 AUDIO_MAX_MB 와 같은 값
export const AUDIO_MAX_BYTES = 25 * 1024 * 1024;

// STT, 질문 생성, 재추출은 요청 안에서 AI 응답을 기다리기 때문에 오래 걸릴 수 있습니다.
const TIMEOUT_MS = 120_000;

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status = 0,
    public detail: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

type Body = { json?: unknown; form?: FormData };
type ErrorBody = { error?: { code?: string; message?: string; detail?: Record<string, unknown> } };

async function request<T>(method: string, path: string, body: Body = {}): Promise<T> {
  if (USE_MOCK) {
    const res = await mockServer(method, path, body.json);
    if (res.status >= 400) throw toApiError(res.status, res.body);
    return res.body as T;
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(API_BASE + path, {
      method,
      headers: body.json !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body.form ?? (body.json !== undefined ? JSON.stringify(body.json) : undefined),
      signal: controller.signal,
    });
  } catch {
    if (controller.signal.aborted) {
      throw new ApiError("UPSTREAM_TIMEOUT", "응답이 너무 오래 걸려요. 잠시 후 다시 시도해 주세요.");
    }
    throw new ApiError("NETWORK", "서버에 연결하지 못했어요. 인터넷 연결을 확인하고 다시 시도해 주세요.");
  } finally {
    clearTimeout(timer);
  }

  const data = await res.json().catch(() => null);
  if (!res.ok || data === null) throw toApiError(res.status, data);
  return data as T;
}

// 서버 오류는 { error: { code, message, detail } } 형식이고 message 는 화면에 그대로 보여 줍니다. (docs/rules/error-format.md)
function toApiError(status: number, data: unknown): ApiError {
  const err = (data as ErrorBody | null)?.error;
  if (err?.code && err.message) return new ApiError(err.code, err.message, status, err.detail ?? {});
  return new ApiError(`HTTP_${status}`, "요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.", status);
}

// 서버 응답 형식 (backend/app/schemas)

type DreamRes = {
  dream_id: number;
  status: DreamRecord["status"];
  input_type: InputType;
  raw_text: string | null;
  confirmed_text: string | null;
  interview_progress: { answered: number; total: number };
  active_job: { job_id: number; type: string; status: string } | null;
};
type QuestionRes = {
  question_id: number;
  order: number;
  target_element: string | null;
  question: string;
  answered: boolean;
  skipped: boolean;
};
type ElementRes = {
  element_id: number;
  type: ElementType;
  name: string;
  description: string;
  confidence: Confidence | null;
};

function toDream(d: DreamRes): DreamRecord {
  return {
    id: d.dream_id,
    inputType: d.input_type,
    status: d.status,
    rawText: d.raw_text,
    confirmedText: d.confirmed_text,
    interview: d.interview_progress,
    activeJob: d.active_job ? { id: d.active_job.job_id, type: d.active_job.type, status: d.active_job.status } : null,
  };
}

function toQuestion(q: QuestionRes): InterviewItem {
  return {
    questionId: q.question_id,
    order: q.order,
    targetElement: q.target_element,
    question: q.question,
    answered: q.answered,
    skipped: q.skipped,
  };
}

function toElement(e: ElementRes): DreamElement {
  return { id: e.element_id, type: e.type, name: e.name, description: e.description ?? "", confidence: e.confidence };
}

// POST /dreams. 텍스트 입력은 원문을 같이 보내고, 서버가 바로 확정 원문으로 저장합니다.
export async function createDream(inputType: InputType, text?: string): Promise<number> {
  const res = await request<{ dream_id: number }>("POST", "/dreams", {
    json: inputType === "text" ? { input_type: "text", text: text?.trim() } : { input_type: "voice" },
  });
  return res.dream_id;
}

// GET /dreams/{id}
export async function getDream(dreamId: string | number): Promise<DreamRecord> {
  return toDream(await request<DreamRes>("GET", `/dreams/${dreamId}`));
}

// POST /dreams/{id}/audio. 음성을 올리면 STT 결과가 꿈 기록의 raw_text 로 저장됩니다.
// 같은 꿈에 다시 올리면 새 녹음으로 바뀝니다.
export async function uploadAudio(dreamId: number, audio: Blob): Promise<void> {
  if (audio.size > AUDIO_MAX_BYTES) {
    throw new ApiError("AUDIO_TOO_LARGE", "음성 파일이 25MB를 넘었어요. 조금 짧게 녹음해 주세요.");
  }
  // 파일 형식은 서버가 내용을 보고 판별하므로 이름은 참고용입니다.
  const ext = audio.type.includes("mp4") ? "mp4" : "webm";
  const form = new FormData();
  form.append("file", audio, `recording.${ext}`);
  await request("POST", `/dreams/${dreamId}/audio`, { form });
}

// PATCH /dreams/{id}. 음성 입력에서 고친 원문을 확정할 때 씁니다.
export async function confirmTranscript(dreamId: string | number, text: string): Promise<void> {
  await request("PATCH", `/dreams/${dreamId}`, { json: { confirmed_text: text.trim() } });
}

// GET /dreams/{id}/interview. 처음 부를 때 질문 5~7개가 만들어지고 상태가 interviewing 으로 바뀝니다.
export async function getInterview(dreamId: string | number): Promise<InterviewItem[]> {
  const res = await request<{ questions: QuestionRes[] }>("GET", `/dreams/${dreamId}/interview`);
  return res.questions.map(toQuestion).sort((a, b) => a.order - b.order);
}

// POST /dreams/{id}/interview. answer 가 null 이면 '잘 기억 안 남'(skipped)으로 보냅니다.
export async function answerQuestion(dreamId: string | number, questionId: number, answer: string | null): Promise<void> {
  const text = answer?.trim();
  await request("POST", `/dreams/${dreamId}/interview`, {
    json: text ? { question_id: questionId, answer: text } : { question_id: questionId, skipped: true },
  });
}

// GET /dreams/{id}/elements. 인터뷰가 끝난 뒤 처음 부를 때 답변을 반영해 다시 추출합니다.
export async function getElements(dreamId: string | number): Promise<DreamElement[]> {
  const res = await request<{ elements: ElementRes[] }>("GET", `/dreams/${dreamId}/elements`);
  return res.elements.map(toElement);
}

// PUT /dreams/{id}/elements/confidence. 일부 요소만 보내도 됩니다.
export async function saveConfidence(dreamId: string | number, values: Record<number, Confidence>): Promise<void> {
  const items = Object.entries(values).map(([id, confidence]) => ({ element_id: Number(id), confidence }));
  await request("PUT", `/dreams/${dreamId}/elements/confidence`, { json: { items } });
}

// POST /dreams/{id}/jobs. 장면 분할 뒤 이미지 생성까지 서버가 이어서 진행합니다.
// 이미 진행 중이면 서버가 기존 작업을 돌려주므로 여러 번 불러도 작업은 하나입니다.
export async function requestScenes(dreamId: string | number): Promise<number> {
  const res = await request<{ job_id: number }>("POST", `/dreams/${dreamId}/jobs`, { json: { type: "generate_scenes" } });
  return res.job_id;
}

// 장면 생성 요청 뒤에 넘어갈 B2 화면 주소입니다. B2와 라우팅을 정하면 여기만 바꿉니다.
// jobId 는 B2 가 진행 상태(GET /jobs/{jobId})를 볼 때 쓰는 값이고, 진행 중인 작업이 없으면 뺍니다.
export function resultsPath(dreamId: string | number, jobId?: number | null) {
  return jobId ? `/?dreamId=${dreamId}&jobId=${jobId}` : `/?dreamId=${dreamId}`;
}

export type Step = "record" | "transcript" | "interview" | "confidence" | "results";

// 꿈 기록 상태로 지금 해야 할 단계를 정합니다.
export function currentStep(dream: DreamRecord): Step {
  if (dream.activeJob?.type === "generate_scenes") return "results";
  if (dream.status === "recorded") {
    if (dream.confirmedText) return "interview";
    return dream.rawText ? "transcript" : "record";
  }
  if (dream.status === "interviewing") {
    const { answered, total } = dream.interview;
    return total > 0 && answered === total ? "confidence" : "interview";
  }
  return "results";
}

export function stepPath(dream: DreamRecord): string {
  const step = currentStep(dream);
  if (step === "results") return resultsPath(dream.id, dream.activeJob?.id);
  // 녹음을 올리지 못한 꿈은 같은 기록에 다시 녹음합니다.
  if (step === "record") return `/record?dreamId=${dream.id}`;
  return `/record/${dream.id}/${step}`;
}
