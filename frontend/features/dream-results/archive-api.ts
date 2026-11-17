import type { Confidence, Dream, DreamStatus, Scene } from "./types";

type DreamListResponse = {
  items: {
    dream_id: number;
    created_at: string;
    thumbnail_url: string | null;
    summary: string | null;
    status: DreamStatus;
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
    elements: { name: string; type: string; confidence: Confidence | null }[];
  }[];
};

async function readJson<T>(baseUrl: string, path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, { signal, cache: "no-store" });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const message = body?.error?.message;
    throw new Error(typeof message === "string" && message ? message : `서버 응답 오류 (${response.status})`);
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
    imageStatus: scene.image_url ? "succeeded" : "queued",
    versions: [{
      version: scene.version_no,
      title: `장면 ${scene.order}`,
      place: scene.elements.find((element) => element.type === "place")?.name ?? "",
      description: scene.summary_ko,
      createdAt: dream.recordedAt,
      elements: scene.elements.map((element, index) => ({
        id: String(index),
        name: element.name,
        confidence: element.confidence,
      })),
    }],
  }));
}
