import type { Confidence, Dream, DreamStatus, DreamVideo, JobStatus, ResultJob, Scene } from "./types";

type DreamListResponse = {
  items: {
    dream_id: number;
    created_at: string;
    thumbnail_url: string | null;
    summary: string | null;
    status: DreamStatus;
    input_type: "voice" | "text";
    has_video: boolean;
  }[];
  next_cursor: string | null;
};

type SceneListResponse = {
  scenes: {
    scene_id: number;
    order: number;
    summary_ko: string;
    image_url: string | null;
    version_no: number;
    status: JobStatus;
    active_job: ResultJob | null;
    confidence_level: Confidence | null;
    elements: { element_id: number; name: string; type: string; confidence: Confidence | null }[];
  }[];
};

export class ArchiveApiError extends Error {
  constructor(message: string, public status: number, public code?: string) { super(message); }
}

async function readJson<T>(baseUrl: string, path: string, signal: AbortSignal, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      signal: AbortSignal.any([signal, AbortSignal.timeout(20_000)]),
      cache: "no-store",
      ...(body === undefined ? {} : {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      }),
    });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new ArchiveApiError("서버 응답을 받지 못했어요. 잠시 후 다시 시도해 주세요.", 0);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const message = body?.error?.message;
    throw new ArchiveApiError(typeof message === "string" && message ? message : `서버 응답 오류 (${response.status})`, response.status, body?.error?.code);
  }
  return response.json();
}

function mediaUrl(baseUrl: string, path: string | null) {
  if (!path) return null;
  try {
    const url = new URL(path, `${baseUrl}/`);
    return url.origin === new URL(baseUrl).origin && url.pathname.startsWith("/storage/")
      ? url.href
      : null;
  } catch {
    return null;
  }
}

export async function listArchiveDreams(baseUrl: string, signal: AbortSignal): Promise<Dream[]> {
  const dreams = new Map<string, Dream>();
  const seenCursors = new Set<string>();
  let cursor: string | null = null;
  do {
    const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
    const page: DreamListResponse = await readJson(baseUrl, `/dreams${query}`, signal);
    for (const item of page.items) {
      const id = String(item.dream_id);
      dreams.set(id, {
        id,
        title: item.summary?.trim() || `꿈 기록 ${id}`,
        thumbnailUrl: mediaUrl(baseUrl, item.thumbnail_url),
        recordedAt: item.created_at,
        originalText: "",
        status: item.status,
        hasVideo: item.has_video,
        scenes: [],
        video: null,
      });
    }
    cursor = page.next_cursor;
    if (cursor) {
      if (seenCursors.has(cursor)) throw new Error("서버가 같은 목록 페이지를 반복해서 보냈어요.");
      seenCursors.add(cursor);
    }
  } while (cursor);
  return [...dreams.values()];
}

export async function listArchiveScenes(baseUrl: string, dream: Dream, signal: AbortSignal): Promise<Scene[]> {
  const { scenes } = await readJson<SceneListResponse>(baseUrl, `/dreams/${encodeURIComponent(dream.id)}/scenes`, signal);
  return [...scenes].sort((a, b) => a.order - b.order).map((scene) => ({
    id: String(scene.scene_id),
    artwork: "school",
    imageUrl: mediaUrl(baseUrl, scene.image_url),
    imageStatus: scene.status,
    activeJob: scene.active_job,
    confidenceLevel: scene.confidence_level,
    versions: [{
      version: scene.version_no,
      title: `장면 ${scene.order}`,
      place: scene.elements.find((element) => element.type === "place")?.name ?? "",
      description: scene.summary_ko,
      createdAt: dream.recordedAt,
      elements: scene.elements.map((element) => ({
        id: String(element.element_id),
        name: element.name,
        confidence: element.confidence,
      })),
    }],
  }));
}

export async function getArchiveDream(baseUrl: string, id: string, signal: AbortSignal): Promise<Dream> {
  const item = await readJson<{
    dream_id: number; created_at: string; status: DreamStatus;
    raw_text: string | null; confirmed_text: string | null;
    active_job: ResultJob | null; latest_render: { render_id: number } | null;
  }>(baseUrl, `/dreams/${encodeURIComponent(id)}`, signal);
  if (String(item.dream_id) !== id) throw new Error("요청한 꿈과 서버의 기록이 일치하지 않습니다.");
  const text = item.confirmed_text || item.raw_text || "";
  return {
    id, title: text.trim().slice(0, 60) || `꿈 기록 ${id}`, recordedAt: item.created_at,
    originalText: text, status: item.status, activeJob: item.active_job,
    hasVideo: item.latest_render !== null, scenes: [], video: null,
  };
}

export async function getArchiveJob(baseUrl: string, id: string, dreamId: string, signal: AbortSignal) {
  const job = await readJson<ResultJob>(baseUrl, `/jobs/${encodeURIComponent(id)}`, signal);
  if (String(job.job_id) !== id || String(job.dream_id) !== dreamId) {
    throw new Error("이 꿈에 해당하는 생성 작업이 아닙니다. 보관함에서 꿈을 다시 열어 주세요.");
  }
  return job;
}

export async function getArchiveVideo(baseUrl: string, id: string, signal: AbortSignal): Promise<DreamVideo | null> {
  try {
    const item = await readJson<{
      video_url: string; is_latest: boolean;
      scene_versions: { scene_id: number; version_no: number }[];
    }>(baseUrl, `/dreams/${encodeURIComponent(id)}/renders/latest`, signal);
    const url = mediaUrl(baseUrl, item.video_url);
    if (!url) throw new Error("영상 주소를 확인하지 못했어요.");
    return { url, isLatest: item.is_latest, sceneVersions: Object.fromEntries(
      item.scene_versions.map((scene) => [String(scene.scene_id), scene.version_no]),
    ) };
  } catch (error) {
    if (error instanceof ArchiveApiError && error.status === 404) return null;
    throw error;
  }
}

export function retryArchiveImages(baseUrl: string, id: string, signal: AbortSignal) {
  return readJson<ResultJob[]>(baseUrl, `/dreams/${encodeURIComponent(id)}/images/retry`, signal, {});
}

export function requestArchiveScenes(baseUrl: string, id: string, signal: AbortSignal) {
  return readJson<ResultJob>(baseUrl, `/dreams/${encodeURIComponent(id)}/jobs`, signal, { type: "generate_scenes" });
}

export function requestArchiveVideo(baseUrl: string, id: string, signal: AbortSignal) {
  return readJson<{ render_id: number; job_id: number }>(baseUrl, `/dreams/${encodeURIComponent(id)}/renders`, signal, {});
}
