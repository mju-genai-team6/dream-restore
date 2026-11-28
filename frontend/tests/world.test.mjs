import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import Module, { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const require = createRequire(import.meta.url);

// result-flow.test.mjs와 같은 방식으로 순수 함수만 불러와 확인합니다.
function load(name) {
  const filename = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../features/dream-world", `${name}.ts`);
  const compiled = ts.transpileModule(readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const mod = new Module(filename);
  mod.filename = filename;
  mod.paths = require.resolve.paths("typescript");
  mod._compile(compiled, filename);
  return mod.exports;
}
const api = load("world-api");
const { placeNodes } = load("layout");
const signal = () => new AbortController().signal;
const response = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const entity = (id, kind, name) => ({ id: String(id), kind, name, ageRange: null, hair: null, outfit: null, features: null, createdAt: "2026-11-01" });
const dream = (id, date, scenes) => ({
  id: String(id), title: `꿈 ${id}`, recordedAt: date,
  scenes: scenes.map((elements, index) => ({ order: index + 1, summary: "", imageUrl: index === 0 ? `/img/${id}.png` : null,
    elements: elements.map(([name, type, entityId = null]) => ({ name, type, entityId })) })),
});

test("연결된 요소와 이름이 같은 요소를 함께 세고, 같은 꿈에 나온 항목을 잇는다", () => {
  const world = api.buildWorld(
    [entity(1, "place", "학교"), entity(2, "person", "친구"), entity(3, "place", "바다")],
    [
      dream(10, "2026-11-10", [[["학교", "place", "1"], ["친구", "person", "2"]], [["바다", "place", "3"]]]),
      dream(11, "2026-11-12", [[["  학교 ", "place"], ["할머니", "person"]]]),
      dream(12, "2026-11-01", [[["학교", "person"], ["우산", "object"]]]),
    ],
  );
  const school = world.nodes.find((node) => node.id === "1");
  assert.equal(world.nodes[0].id, "1"); // 가장 많이 나온 항목이 앞에 온다
  assert.deepEqual(school.appearances.map((item) => [item.dreamId, item.matchedBy]), [["11", "name"], ["10", "link"]]);
  assert.equal(school.imageUrl, "/img/11.png"); // 가장 최근 꿈의 장면 이미지
  assert.deepEqual(school.appearances[1].path, ["학교", "바다"]);
  assert.deepEqual(world.edges.map((edge) => `${edge.from}-${edge.to}:${edge.dreams}`).sort(), ["1-2:1", "1-3:1", "2-3:1"]);
  // 종류가 다른 같은 이름(인물 '학교')과 물건 요소는 연결하지 않고, 등록 안 된 인물·장소만 후보가 된다
  assert.deepEqual(world.candidates.map((item) => `${item.kind}:${item.name}:${item.dreamIds.length}`), ["person:학교:1", "person:할머니:1"]);
  assert.equal(world.dreamCount, 3);
});

test("다른 항목에 이미 연결된 요소는 이름이 같아도 옮기지 않는다", () => {
  const world = api.buildWorld(
    [entity(1, "person", "할머니"), entity(2, "person", "외할머니")],
    [dream(20, "2026-11-01", [[["할머니", "person", "2"]]])],
  );
  assert.equal(world.nodes.find((node) => node.id === "1").appearances.length, 0);
  assert.equal(world.nodes.find((node) => node.id === "2").appearances[0].matchedBy, "link");
  assert.equal(world.candidates.length, 0);
});

test("등록은 빈 칸을 빼고, 수정은 빈 칸을 빈 문자열로 보내 지운다", () => {
  const draft = { kind: "person", name: " 민수 ", ageRange: "", hair: "short hair ", outfit: "", features: "" };
  assert.deepEqual(api.entityPayload(draft, "create"), { name: "민수", kind: "person", hair: "short hair" });
  assert.deepEqual(api.entityPayload(draft, "update"), { name: "민수", age_range: "", hair: "short hair", outfit: "", features: "" });
});

test("같은 종류 안에서만 공백과 대소문자를 무시하고 중복을 찾는다", () => {
  const entities = [entity(1, "place", "Cafe"), entity(2, "person", "민수")];
  assert.equal(api.findDuplicate(entities, { kind: "place", name: " cafe " })?.id, "1");
  assert.equal(api.findDuplicate(entities, { kind: "place", name: "민수" }), undefined);
  assert.equal(api.findDuplicate(entities, { kind: "place", name: "cafe" }, "1"), undefined);
});

test("장면이 있는 꿈만 장면 목록을 부르고, 서버 이미지 주소만 쓴다", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    calls.push(String(url).replace("http://localhost:8000", ""));
    if (String(url).includes("/dreams?")) return response({ items: [
      { dream_id: 5, created_at: "2026-11-02", summary: "바다 꿈", status: "rendered" },
      { dream_id: 6, created_at: "2026-11-03", summary: null, status: "interviewing" },
    ], next_cursor: null });
    return response({ scenes: [{ order: 1, summary_ko: "바다", image_url: "/storage/a.png?v=1",
      elements: [{ name: "바다", type: "place", entity_id: 3 }] },
    { order: 2, summary_ko: "밖", image_url: "https://evil.example/a.png", elements: [] }] });
  });
  const dreams = await api.loadDreamSources("http://localhost:8000", signal());
  assert.deepEqual(calls, ["/dreams?limit=50", "/dreams/5/scenes"]);
  assert.equal(dreams[0].scenes[0].imageUrl, "http://localhost:8000/storage/a.png?v=1");
  assert.equal(dreams[0].scenes[0].elements[0].entityId, "3");
  assert.equal(dreams[0].scenes[1].imageUrl, null);
});

test("서버 오류 메시지를 그대로 보여 주고, 등록은 POST로 보낸다", async (t) => {
  const sent = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    sent.push([init?.method, JSON.parse(init?.body ?? "null")]);
    return response({ error: { code: "validation_failed", message: "같은 이름의 장소가 이미 있습니다." } }, 400);
  });
  await assert.rejects(
    api.createEntity("http://localhost:8000", { kind: "place", name: "학교", ageRange: "", hair: "", outfit: "", features: "" }, signal()),
    { message: "같은 이름의 장소가 이미 있습니다.", status: 400 },
  );
  assert.deepEqual(sent, [["POST", { name: "학교", kind: "place" }]]);
});

test("지도 배치는 가운데에 가장 많이 나온 항목을 두고 겹치지 않게 놓는다", () => {
  const nodes = Array.from({ length: 9 }, (_, i) => ({ ...entity(i + 1, "place", `곳${i}`), appearances: Array(9 - i).fill({}), imageUrl: null }));
  const placed = placeNodes(nodes);
  assert.deepEqual([placed[0].x, placed[0].y], [50, 46]);
  assert.equal(placed.length, 9);
  const keys = new Set(placed.map((item) => `${item.x},${item.y}`));
  assert.equal(keys.size, 9);
  assert.ok(placed.every((item) => item.x > 0 && item.x < 100 && item.y > 0 && item.y < 100));
});

test("꿈 경로는 장면마다 장소를 먼저 넣고, 연속으로 같은 항목은 한 번만 넣는다", () => {
  const world = api.buildWorld(
    [entity(1, "place", "학교"), entity(2, "person", "친구"), entity(3, "place", "바다")],
    [dream(30, "2026-11-10", [
      [["친구", "person", "2"], ["학교", "place", "1"]],
      [["학교", "place", "1"]],
      [["친구", "person", "2"]],
      [["바다", "place", "3"], ["친구", "person", "2"]],
      [["우산", "object"]],
    ])],
  );
  assert.deepEqual(world.routes["30"].entityIds, ["1", "2", "3"]);
  assert.equal(world.routes["30"].recordedAt, "2026-11-10");
});

test("기간을 고르면 그 안에 기록한 꿈만 남긴다", () => {
  const now = new Date("2026-11-28T00:00:00+09:00").getTime();
  const dreams = [dream(1, "2026-11-20T00:00:00+09:00", []), dream(2, "2026-09-20T00:00:00+09:00", []), dream(3, "잘못된 날짜", [])];
  assert.deepEqual(api.dreamsInPeriod(dreams, "30", now).map((item) => item.id), ["1"]);
  assert.deepEqual(api.dreamsInPeriod(dreams, "90", now).map((item) => item.id), ["1", "2"]);
  assert.equal(api.dreamsInPeriod(dreams, "all", now).length, 3);
});

test("항목이 적으면 가운데 양옆으로 벌려 놓는다", () => {
  const nodes = Array.from({ length: 3 }, (_, i) => ({ ...entity(i + 1, "place", `곳${i}`), appearances: [], imageUrl: null }));
  const [, left, right] = placeNodes(nodes);
  assert.equal(left.y, right.y);
  assert.ok(Math.abs(left.x - right.x) > 40);
});

test("꿈이 여러 페이지면 다음 페이지를 이어서 부르고, 같은 페이지가 반복되면 멈춘다", async (t) => {
  const item = (id) => ({ dream_id: id, created_at: "2026-11-02", summary: `꿈 ${id}`, status: "images_ready" });
  const pages = { "": { items: [item(9), item(8)], next_cursor: "c1" }, c1: { items: [item(7)], next_cursor: null } };
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    const path = String(url).replace("http://localhost:8000", "");
    calls.push(path);
    if (path.startsWith("/dreams?")) return response(pages[new URL(String(url)).searchParams.get("cursor") ?? ""]);
    return response({ scenes: [] });
  });
  const dreams = await api.loadDreamSources("http://localhost:8000", signal());
  assert.deepEqual(dreams.map((dream) => dream.id), ["9", "8", "7"]);
  assert.deepEqual(calls.slice(0, 2), ["/dreams?limit=50", "/dreams?limit=50&cursor=c1"]);

  pages.c1 = { items: [], next_cursor: "c1" };
  await assert.rejects(api.loadDreamSources("http://localhost:8000", signal()), /반복/);
});
