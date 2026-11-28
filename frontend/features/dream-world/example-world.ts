import type { DreamSource, WorldEntity } from "./types";

// 서버 주소가 없을 때 쓰는 가상의 세계관과 꿈입니다. 등록과 수정은 이 탭 안에서만 유지됩니다.
const entity = (id: number, kind: WorldEntity["kind"], name: string, extra: Partial<WorldEntity> = {}): WorldEntity => ({
  id: String(id), kind, name, ageRange: null, hair: null, outfit: null, features: null,
  createdAt: "2026-10-01T09:00:00+09:00", ...extra,
});

export const exampleEntities: WorldEntity[] = [
  entity(1, "place", "학교", { features: "red brick building with a clock tower, cherry trees in the yard" }),
  entity(2, "place", "바다", { features: "calm blue sea seen from a wooden railing" }),
  entity(3, "place", "옛날 집", { features: "small old house with a tiled roof and a flower garden" }),
  entity(4, "person", "친구", { ageRange: "early 20s", hair: "long dark brown hair", outfit: "white blouse and backpack" }),
  entity(5, "person", "남자친구", { ageRange: "early 20s", hair: "short black hair", outfit: "dark navy jacket" }),
  entity(6, "place", "도시"),
  entity(7, "place", "호수"),
  entity(8, "place", "하늘"),
  entity(9, "person", "엄마", { ageRange: "50s", hair: "shoulder-length wavy hair" }),
];

type Scene = [summary: string, elements: [name: string, type: string, entityId?: number][]];
const dream = (id: number, date: string, title: string, scenes: Scene[]): DreamSource => ({
  id: String(id), title, recordedAt: `${date}T08:00:00+09:00`,
  scenes: scenes.map(([summary, elements], index) => ({
    order: index + 1, summary, imageUrl: null,
    elements: elements.map(([name, type, entityId]) => ({ name, type, entityId: entityId ? String(entityId) : null })),
  })),
});

export const exampleDreams: DreamSource[] = [
  dream(31, "2026-11-11", "친구들과 학교에 있다가 바다로 갔어", [
    ["친구와 학교 운동장에 서 있었다", [["학교", "place", 1], ["친구", "person", 4]]],
    ["버스를 타고 바다에 도착했다", [["바다", "place", 2], ["친구", "person", 4]]],
    ["바다 옆 옛날 집으로 들어갔다", [["옛날 집", "place", 3]]],
  ]),
  dream(28, "2026-11-05", "학교에서 남자친구를 만났어", [
    ["복도 끝에서 누가 불렀다", [["학교", "place", 1], ["남자친구", "person", 5]]],
    ["옥상에서 하늘을 봤다", [["하늘", "place", 8], ["남자친구", "person", 5]]],
  ]),
  dream(25, "2026-11-02", "학교에서 시험을 보는 꿈이었어", [
    ["교실에서 시험지를 받았다", [["학교", "place", 1], ["노트", "object"]]],
    ["답을 쓰려는데 글씨가 흐려졌다", [["학교", "place", 1], ["불안", "emotion"]]],
  ]),
  dream(22, "2026-10-28", "학교에서 버스를 타고 바다에 갔어", [
    ["학교 정문에서 버스를 기다렸다", [["학교", "place", 1], ["친구", "person", 4]]],
    ["창밖으로 도시가 지나갔다", [["도시", "place", 6]]],
    ["바다에 도착해 친구와 걸었다", [["바다", "place", 2], ["친구", "person", 4]]],
  ]),
  dream(19, "2026-10-21", "할머니랑 호숫가를 걸었어", [
    ["할머니 손을 잡고 걸었다", [["호수", "place", 7], ["할머니", "person"]]],
    ["엄마가 멀리서 불렀다", [["옛날 집", "place", 3], ["엄마", "person", 9]]],
  ]),
  dream(15, "2026-10-14", "도시 위를 날아다녔어", [
    ["높은 건물 사이를 날았다", [["도시", "place", 6]]],
    ["구름 위 하늘에 떠 있었다", [["하늘", "place", 8]]],
    ["바다 위로 내려앉았다", [["바다", "place", 2], ["남자친구", "person", 5]]],
  ]),
  dream(11, "2026-10-07", "놀이공원에서 할머니를 찾았어", [
    ["놀이공원 입구에서 길을 잃었다", [["놀이공원", "place"], ["할머니", "person"]]],
    ["호수 옆 벤치에 엄마가 있었다", [["호수", "place", 7], ["엄마", "person", 9]]],
  ]),
];
