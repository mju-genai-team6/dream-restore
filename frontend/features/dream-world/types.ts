export type EntityKind = "person" | "place";

// 서버 world_entities 한 줄을 화면에서 쓰는 형태로 바꾼 값입니다.
export type WorldEntity = {
  id: string;
  kind: EntityKind;
  name: string;
  ageRange: string | null;
  hair: string | null;
  outfit: string | null;
  features: string | null;
  createdAt: string;
};

// 장면이 있는 꿈 한 건. 지도는 이 목록과 세계관 항목만으로 만듭니다.
export type SceneSource = {
  order: number;
  summary: string;
  imageUrl: string | null;
  elements: { name: string; type: string; entityId: string | null }[];
};

export type DreamSource = {
  id: string;
  title: string;
  recordedAt: string;
  scenes: SceneSource[];
};

export type Appearance = {
  dreamId: string;
  title: string;
  recordedAt: string;
  imageUrl: string | null;
  path: string[];
  // link: 서버가 연결한 요소, name: 아직 연결 전이지만 서버 규칙과 같은 이름으로 찾은 요소
  matchedBy: "link" | "name";
};

export type WorldNode = WorldEntity & {
  appearances: Appearance[];
  imageUrl: string | null;
};

export type WorldEdge = { from: string; to: string; dreams: number };

export type Candidate = { kind: EntityKind; name: string; dreamIds: string[] };

// 꿈 하나의 장면 순서대로 지나간 세계관 항목 (지도 위 경로 표시에 씀)
export type DreamRoute = { dreamId: string; title: string; recordedAt: string; entityIds: string[] };

export type World = {
  nodes: WorldNode[];
  edges: WorldEdge[];
  candidates: Candidate[];
  routes: Record<string, DreamRoute>;
  dreamCount: number;
};

export type Period = "all" | "30" | "90";
export const periodLabels: Record<Period, string> = { all: "전체 기간", "30": "최근 30일", "90": "최근 90일" };

export type EntityDraft = {
  kind: EntityKind;
  name: string;
  ageRange: string;
  hair: string;
  outfit: string;
  features: string;
};

export const kindLabels: Record<EntityKind, string> = { person: "인물", place: "장소" };
// 조사까지 붙인 표기 (인물이, 장소가)
export const kindSubject: Record<EntityKind, string> = { person: "인물이", place: "장소가" };

export const LIMITS = { name: 50, ageRange: 50, hair: 200, outfit: 200 } as const;

export function formatShortDate(value: string) {
  const parts = new Intl.DateTimeFormat("ko-KR", {
    year: "numeric", month: "2-digit", day: "2-digit", timeZone: "Asia/Seoul",
  }).formatToParts(new Date(value));
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}.${get("month")}.${get("day")}`;
}
