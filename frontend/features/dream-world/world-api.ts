import type {
  Appearance, Candidate, DreamRoute, DreamSource, Period, EntityDraft, EntityKind, World, WorldEdge, WorldEntity, WorldNode,
} from "./types";

// 서버 응답 형식 (backend/app/schemas/world.py, dreams.py, scenes.py)
type EntityResponse = {
  id: number; kind: EntityKind; name: string;
  age_range: string | null; hair: string | null; outfit: string | null; features: string | null;
  created_at: string;
};
type DreamListResponse = {
  items: { dream_id: number; created_at: string; summary: string | null; status: string }[];
  next_cursor: string | null;
};
type SceneListResponse = {
  scenes: {
    order: number; summary_ko: string; image_url: string | null;
    elements: { name: string; type: string; entity_id?: number | null }[];
  }[];
};

// 장면이 만들어진 뒤의 상태만 장면 목록을 부릅니다. 그 전 상태는 요소가 장면에 묶이지 않았습니다.
const HAS_SCENES = new Set(["scenes_ready", "images_ready", "rendered"]);
const KINDS = new Set<string>(["person", "place"]);

export class WorldApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

async function request<T>(baseUrl: string, path: string, signal: AbortSignal, init?: { method: string; body: unknown }): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      signal: AbortSignal.any([signal, AbortSignal.timeout(20_000)]),
      cache: "no-store",
      ...(init ? { method: init.method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(init.body) } : {}),
    });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new WorldApiError("서버 응답을 받지 못했어요. 잠시 후 다시 시도해 주세요.", 0);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const message = body?.error?.message;
    throw new WorldApiError(typeof message === "string" && message ? message : `서버 응답 오류 (${response.status})`, response.status);
  }
  return response.json();
}

// B2 archive-api.ts와 같은 규칙: 같은 서버의 /storage/ 주소만 이미지로 씁니다.
export function mediaUrl(baseUrl: string, path: string | null) {
  if (!path) return null;
  try {
    const url = new URL(path, `${baseUrl}/`);
    return url.origin === new URL(baseUrl).origin && url.pathname.startsWith("/storage/") ? url.href : null;
  } catch {
    return null;
  }
}

function toEntity(item: EntityResponse): WorldEntity {
  return {
    id: String(item.id), kind: item.kind, name: item.name,
    ageRange: item.age_range, hair: item.hair, outfit: item.outfit, features: item.features,
    createdAt: item.created_at,
  };
}

export async function listEntities(baseUrl: string, signal: AbortSignal) {
  const { entities } = await request<{ entities: EntityResponse[] }>(baseUrl, "/world/entities", signal);
  return entities.map(toEntity);
}

async function listDreamsWithScenes(baseUrl: string, signal: AbortSignal) {
  const dreams: DreamListResponse["items"] = [];
  const seen = new Set<string>();
  let cursor: string | null = null;
  do {
    const query: string = cursor ? `?limit=50&cursor=${encodeURIComponent(cursor)}` : "?limit=50";
    const page: DreamListResponse = await request(baseUrl, `/dreams${query}`, signal);
    dreams.push(...page.items);
    cursor = page.next_cursor;
    if (cursor) {
      if (seen.has(cursor)) throw new Error("서버가 같은 목록 페이지를 반복해서 보냈어요.");
      seen.add(cursor);
    }
  } while (cursor);
  return dreams.filter((dream) => HAS_SCENES.has(dream.status));
}

// 꿈마다 장면 목록을 부르므로 한 번에 4개까지만 동시에 요청합니다.
export async function loadDreamSources(baseUrl: string, signal: AbortSignal): Promise<DreamSource[]> {
  const dreams = await listDreamsWithScenes(baseUrl, signal);
  const result: DreamSource[] = new Array(dreams.length);
  let next = 0;
  async function worker() {
    while (next < dreams.length) {
      const index = next++;
      const dream = dreams[index];
      const id = String(dream.dream_id);
      const { scenes } = await request<SceneListResponse>(baseUrl, `/dreams/${id}/scenes`, signal);
      result[index] = {
        id,
        title: dream.summary?.trim() || `꿈 기록 ${id}`,
        recordedAt: dream.created_at,
        scenes: scenes.map((scene) => ({
          order: scene.order,
          summary: scene.summary_ko,
          imageUrl: mediaUrl(baseUrl, scene.image_url),
          elements: scene.elements.map((element) => ({
            name: element.name,
            type: element.type,
            entityId: element.entity_id == null ? null : String(element.entity_id),
          })),
        })),
      };
    }
  }
  await Promise.all(Array.from({ length: Math.min(4, dreams.length) }, worker));
  return result;
}

// 빈 칸은 보내지 않습니다(등록). 수정할 때는 빈 문자열을 보내 그 칸을 비웁니다(서버 규칙).
export function entityPayload(draft: EntityDraft, mode: "create" | "update") {
  const body: Record<string, string> = { name: draft.name.trim() };
  if (mode === "create") body.kind = draft.kind;
  const optional = { age_range: draft.ageRange, hair: draft.hair, outfit: draft.outfit, features: draft.features };
  for (const [key, value] of Object.entries(optional)) {
    const text = value.trim();
    if (text || mode === "update") body[key] = text;
  }
  return body;
}

export async function createEntity(baseUrl: string, draft: EntityDraft, signal: AbortSignal) {
  return toEntity(await request<EntityResponse>(baseUrl, "/world/entities", signal, { method: "POST", body: entityPayload(draft, "create") }));
}

export async function updateEntity(baseUrl: string, id: string, draft: EntityDraft, signal: AbortSignal) {
  return toEntity(await request<EntityResponse>(baseUrl, `/world/entities/${encodeURIComponent(id)}`, signal, { method: "PATCH", body: entityPayload(draft, "update") }));
}

// 서버 normalize_name과 같은 비교: 앞뒤 공백을 빼고 대소문자를 구분하지 않습니다.
export function normalizeName(name: string) {
  return name.trim().toLowerCase();
}

export function findDuplicate(entities: WorldEntity[], draft: EntityDraft, excludeId?: string) {
  const key = normalizeName(draft.name);
  return entities.find((entity) => entity.id !== excludeId && entity.kind === draft.kind && normalizeName(entity.name) === key);
}

function scenePath(dream: DreamSource) {
  const path: string[] = [];
  for (const scene of [...dream.scenes].sort((a, b) => a.order - b.order)) {
    const label = scene.elements.find((element) => element.type === "place")?.name ?? scene.elements[0]?.name;
    if (label && path[path.length - 1] !== label) path.push(label);
  }
  return path;
}

/**
 * 세계관 항목과 장면이 있는 꿈으로 지도 데이터를 만듭니다.
 * - 요소의 entity_id가 있으면 그 항목으로 셉니다.
 * - entity_id가 없으면 서버 연결 규칙(같은 종류, 같은 이름)으로 찾아 '이름으로 찾음'으로 표시합니다.
 *   서버는 장면을 만들 때만 연결하므로, 나중에 등록한 항목도 지난 꿈에서 바로 보이게 하려는 것입니다.
 * - 같은 꿈에 함께 나온 두 항목은 연결선으로 잇습니다.
 * - 어느 항목에도 해당하지 않는 인물과 장소 요소는 '추가할 수 있는 이름'으로 모읍니다.
 */
export function buildWorld(entities: WorldEntity[], dreams: DreamSource[]): World {
  const byId = new Map(entities.map((entity) => [entity.id, entity]));
  const byName = new Map<string, string>();
  for (const entity of [...entities].sort((a, b) => Number(a.id) - Number(b.id))) {
    const key = `${entity.kind}:${normalizeName(entity.name)}`;
    if (!byName.has(key)) byName.set(key, entity.id);
  }

  const appearances = new Map<string, Appearance[]>();
  const edgeCount = new Map<string, number>();
  const candidates = new Map<string, Candidate>();
  const routes: Record<string, DreamRoute> = {};

  for (const dream of dreams) {
    const hits = new Map<string, { matchedBy: "link" | "name"; imageUrl: string | null }>();
    const route: string[] = [];
    for (const scene of [...dream.scenes].sort((a, b) => a.order - b.order)) {
      const inScene: { id: string; kind: string }[] = [];
      for (const element of scene.elements) {
        if (!KINDS.has(element.type)) continue;
        const key = `${element.type}:${normalizeName(element.name)}`;
        const linked = element.entityId && byId.has(element.entityId) ? element.entityId : null;
        const id = linked ?? (element.entityId ? null : byName.get(key) ?? null);
        if (!id) {
          if (element.entityId || !normalizeName(element.name)) continue;
          const candidate = candidates.get(key) ?? { kind: element.type as EntityKind, name: element.name.trim(), dreamIds: [] };
          if (!candidate.dreamIds.includes(dream.id)) candidate.dreamIds.push(dream.id);
          candidates.set(key, candidate);
          continue;
        }
        inScene.push({ id, kind: element.type });
        const previous = hits.get(id);
        hits.set(id, {
          matchedBy: previous?.matchedBy === "link" || linked ? "link" : "name",
          imageUrl: previous?.imageUrl ?? scene.imageUrl,
        });
      }
      // 장면마다 장소를 먼저, 없으면 인물을 경로에 넣고 바로 앞과 같으면 건너뜁니다.
      const stop = inScene.find((item) => item.kind === "place") ?? inScene[0];
      if (stop && route[route.length - 1] !== stop.id) route.push(stop.id);
    }
    if (route.length) routes[dream.id] = { dreamId: dream.id, title: dream.title, recordedAt: dream.recordedAt, entityIds: route };
    const path = scenePath(dream);
    for (const [id, hit] of hits) {
      const list = appearances.get(id) ?? [];
      list.push({ dreamId: dream.id, title: dream.title, recordedAt: dream.recordedAt, imageUrl: hit.imageUrl, path, matchedBy: hit.matchedBy });
      appearances.set(id, list);
    }
    const ids = [...hits.keys()].sort();
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const key = `${ids[i]}|${ids[j]}`;
        edgeCount.set(key, (edgeCount.get(key) ?? 0) + 1);
      }
    }
  }

  const nodes: WorldNode[] = entities.map((entity) => {
    const list = (appearances.get(entity.id) ?? []).sort((a, b) => b.recordedAt.localeCompare(a.recordedAt));
    return { ...entity, appearances: list, imageUrl: list.find((item) => item.imageUrl)?.imageUrl ?? null };
  }).sort((a, b) => b.appearances.length - a.appearances.length || Number(a.id) - Number(b.id));

  const edges: WorldEdge[] = [...edgeCount].map(([key, count]) => {
    const [from, to] = key.split("|");
    return { from, to, dreams: count };
  });

  return {
    nodes,
    edges,
    candidates: [...candidates.values()].sort((a, b) => b.dreamIds.length - a.dreamIds.length || a.name.localeCompare(b.name, "ko")),
    routes,
    dreamCount: dreams.length,
  };
}

// 기록한 날짜가 기준 시각에서 days일 안에 있는 꿈만 남깁니다.
export function dreamsInPeriod(dreams: DreamSource[], period: Period, now = Date.now()) {
  if (period === "all") return dreams;
  const from = now - Number(period) * 24 * 60 * 60 * 1000;
  return dreams.filter((dream) => {
    const time = new Date(dream.recordedAt).getTime();
    return Number.isFinite(time) && time >= from;
  });
}

export function emptyDraft(kind: EntityKind = "person", name = ""): EntityDraft {
  return { kind, name, ageRange: "", hair: "", outfit: "", features: "" };
}

export function draftOf(entity: WorldEntity): EntityDraft {
  return {
    kind: entity.kind, name: entity.name,
    ageRange: entity.ageRange ?? "", hair: entity.hair ?? "", outfit: entity.outfit ?? "", features: entity.features ?? "",
  };
}
