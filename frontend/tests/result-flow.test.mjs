import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import Module, { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const require = createRequire(import.meta.url);

// 기존 TypeScript 컴파일러로 순수 API·폴링 코드를 실행합니다. 테스트용 의존성은 추가하지 않습니다.
function load(name) {
  const filename = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../features/dream-results", `${name}.ts`);
  const compiled = ts.transpileModule(readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const mod = new Module(filename);
  mod.filename = filename;
  mod.paths = require.resolve.paths("typescript");
  mod._compile(compiled, filename);
  return mod.exports;
}
const api = load("archive-api");
const { pollResult } = load("polling");
const { videoMatchesScenes } = load("types");
const signal = () => new AbortController().signal;
const response = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const flush = () => new Promise((resolve) => setImmediate(resolve));

test("장면은 서버 상태·실제 요소 ID·확신도·작업과 캐시 버전을 보존한다", async (t) => {
  t.mock.method(globalThis, "fetch", async () => response({ scenes: [
    { scene_id: 20, order: 2, summary_ko: "바다", image_url: "/storage/two.png?v=7", version_no: 3,
      status: "failed", active_job: null, confidence_level: "low", elements: [{ element_id: 91, type: "place", name: "바다", confidence: "low" }] },
    { scene_id: 10, order: 1, summary_ko: "학교", image_url: null, version_no: 1,
      status: "running", active_job: { job_id: 88, status: "running" }, confidence_level: null, elements: [] },
  ] }));
  const scenes = await api.listArchiveScenes("http://localhost:8000", { id: "8", recordedAt: "2026-11-21" }, signal());
  assert.deepEqual(scenes.map((scene) => scene.id), ["10", "20"]);
  assert.equal(scenes[0].activeJob.job_id, 88);
  assert.equal(scenes[1].imageStatus, "failed"); // 주소가 있어도 성공으로 추정하지 않는다.
  assert.equal(scenes[1].confidenceLevel, "low");
  assert.equal(scenes[1].versions[0].elements[0].id, "91");
  assert.equal(scenes[1].imageUrl, "http://localhost:8000/storage/two.png?v=7");
});

test("보관함은 다음 페이지와 영상 유무를 읽고 잘못된 반복 커서는 중단한다", async (t) => {
  const urls = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    urls.push(url);
    return response({ items: [{ dream_id: urls.length, created_at: "2026-11-21", summary: "꿈", thumbnail_url: "https://elsewhere.invalid/storage/a.png", status: "rendered", has_video: true }], next_cursor: "1" });
  });
  await assert.rejects(api.listArchiveDreams("http://localhost:8000", signal()), /같은 목록 페이지/);
  assert.deepEqual(urls, ["http://localhost:8000/dreams", "http://localhost:8000/dreams?cursor=1"]);
});

test("URL의 꿈·작업이 다른 꿈이면 결과를 섞지 않고 오류로 처리한다", async (t) => {
  t.mock.method(globalThis, "fetch", async () => response({ job_id: 42, dream_id: 9 }));
  await assert.rejects(api.getArchiveJob("http://localhost:8000", "42", "8", signal()), /이 꿈에 해당하는/);
  await assert.rejects(api.getArchiveDream("http://localhost:8000", "8", signal()), /일치하지/);
});

test("완성 영상 404는 대기 상태이며 다른 서버 오류는 그대로 표시한다", async (t) => {
  const mock = t.mock.method(globalThis, "fetch", async () => response({ error: { message: "아직 완성된 영상이 없습니다." } }, 404));
  assert.equal(await api.getArchiveVideo("http://localhost:8000", "8", signal()), null);
  mock.mock.mockImplementation(async () => response({ error: { code: "INVALID_STATE", message: "이미지가 준비되지 않았습니다." } }, 409));
  await assert.rejects(api.requestArchiveVideo("http://localhost:8000", "8", signal()), (err) => err.status === 409 && err.code === "INVALID_STATE" && /이미지/.test(err.message));
});

test("영상 버전과 is_latest를 모두 확인하고 외부 영상 URL은 거부한다", async (t) => {
  const mock = t.mock.method(globalThis, "fetch", async () => response({ video_url: "/storage/video.mp4", is_latest: false, scene_versions: [{ scene_id: 1, version_no: 2 }] }));
  const video = await api.getArchiveVideo("http://localhost:8000", "8", signal());
  const dream = { video, scenes: [{ id: "1", versions: [{ version: 2 }] }] };
  assert.equal(videoMatchesScenes(dream), false);
  assert.equal(videoMatchesScenes({ ...dream, video: { ...video, isLatest: true } }), true);
  assert.equal(videoMatchesScenes({ ...dream, scenes: [] }), false);
  mock.mock.mockImplementation(async () => response({ video_url: "https://elsewhere.invalid/storage/a.mp4" }));
  await assert.rejects(api.getArchiveVideo("http://localhost:8000", "8", signal()), /영상 주소/);
});

test("이미지 재시도·장면 재시도·영상 생성은 올바른 꿈에 POST한다", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, init) => { calls.push([url, init.method, JSON.parse(init.body)]); return response({ job_id: 42 }, 202); });
  await api.retryArchiveImages("http://localhost:8000", "8", signal());
  await api.requestArchiveScenes("http://localhost:8000", "8", signal());
  await api.requestArchiveVideo("http://localhost:8000", "8", signal());
  assert.deepEqual(calls, [
    ["http://localhost:8000/dreams/8/images/retry", "POST", {}],
    ["http://localhost:8000/dreams/8/jobs", "POST", { type: "generate_scenes" }],
    ["http://localhost:8000/dreams/8/renders", "POST", {}],
  ]);
});

test("진행 중 요청은 겹치지 않고 모든 장면 완료 후 자동 조회를 멈춘다", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let resolve;
  let calls = 0;
  const values = [];
  const stop = pollResult({ load: () => { calls++; return new Promise((done) => { resolve = done; }); },
    pending: (scenes) => scenes.some((s) => s === "queued" || s === "running"),
    onData: (value) => values.push(value), onError: assert.fail, onTimeout: assert.fail,
    intervalMs: 4_000, timeoutMs: 180_000 });
  t.mock.timers.tick(20_000);
  assert.equal(calls, 1);
  resolve(["running", "succeeded"]); await flush();
  t.mock.timers.tick(4_000);
  assert.equal(calls, 2);
  resolve(["succeeded", "failed"]); await flush();
  t.mock.timers.tick(200_000);
  assert.equal(calls, 2);
  assert.equal(values.length, 2);
  stop();
});

test("화면 이탈은 진행 중 요청과 이후 갱신을 취소한다", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let requestSignal;
  let resolve;
  const stop = pollResult({ load: (signal) => { requestSignal = signal; return new Promise((done) => { resolve = done; }); },
    pending: () => true, onData: assert.fail, onError: assert.fail, onTimeout: assert.fail });
  stop();
  assert.equal(requestSignal.aborted, true);
  resolve("late response"); await flush();
  t.mock.timers.tick(200_000);
});

test("3분 제한은 응답이 멈춘 요청도 중단하며 실패로 위장하지 않는다", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let requestSignal;
  let timeout = 0;
  let resolve;
  const stop = pollResult({ load: (signal) => { requestSignal = signal; return new Promise((done) => { resolve = done; }); },
    pending: () => true, onData: assert.fail, onError: assert.fail, onTimeout: () => timeout++ });
  t.mock.timers.tick(179_999);
  assert.equal(timeout, 0);
  t.mock.timers.tick(1);
  assert.equal(timeout, 1);
  assert.equal(requestSignal.aborted, true);
  resolve("late response"); await flush();
  stop();
});

test("조회 오류가 나면 요청을 반복하지 않고 다시 시도를 기다린다", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let calls = 0;
  const errors = [];
  const stop = pollResult({ load: async () => { calls++; throw new Error("offline"); }, pending: () => true,
    onData: assert.fail, onError: (err) => errors.push(err.message), onTimeout: assert.fail });
  await flush();
  t.mock.timers.tick(200_000);
  assert.equal(calls, 1);
  assert.deepEqual(errors, ["offline"]);
  stop();
});
