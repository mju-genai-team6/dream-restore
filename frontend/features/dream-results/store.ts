"use client";

import { useSyncExternalStore } from "react";
import { exampleDreams } from "./example-dreams";
import { latestVersion, type Confidence, type Dream, type SceneDraft } from "./types";

const STORAGE_KEY = "dream-restore:b2-results:v1";
const CHANGE_EVENT = "dream-restore:b2-results-changed";
type Snapshot = { dreams: Dream[]; warning: string | null };
const initialSnapshot: Snapshot = { dreams: exampleDreams, warning: null };
let cached = initialSnapshot;
let loaded = false;

// 현재 예시 데이터의 수정본만 저장합니다. 실제 꿈의 DB 저장은 C의 API와 연결합니다.
function validStoredDreams(value: unknown): value is Dream[] {
  if (!Array.isArray(value) || value.length !== exampleDreams.length) return false;
  return value.every((dream, index) => {
    const original = exampleDreams[index];
    if (!dream || dream.id !== original.id || !Array.isArray(dream.scenes) || dream.scenes.length !== original.scenes.length) return false;
    return dream.scenes.every((scene: Dream["scenes"][number], sceneIndex: number) => {
      const seed = original.scenes[sceneIndex];
      if (scene.id !== seed.id || scene.artwork !== seed.artwork || scene.imageStatus !== seed.imageStatus || !Array.isArray(scene.versions) || !scene.versions.length) return false;
      return scene.versions.every((version, versionIndex) =>
        version.version === versionIndex + 1 &&
        typeof version.title === "string" && version.title.trim().length > 0 && version.title.length <= 60 &&
        typeof version.place === "string" && version.place.trim().length > 0 && version.place.length <= 80 &&
        typeof version.description === "string" && version.description.trim().length > 0 && version.description.length <= 1200 &&
        typeof version.createdAt === "string" && Number.isFinite(Date.parse(version.createdAt)) &&
        Array.isArray(version.elements) && version.elements.length === latestVersion(seed).elements.length &&
        version.elements.every((element, elementIndex) => element.id === latestVersion(seed).elements[elementIndex].id &&
          element.name === latestVersion(seed).elements[elementIndex].name &&
          (["high", "medium", "low"] as Confidence[]).includes(element.confidence)),
      );
    });
  });
}

function readSnapshot(): Snapshot {
  if (typeof window === "undefined") return initialSnapshot;
  if (!loaded) {
    loaded = true;
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed.schemaVersion !== 1 || !validStoredDreams(parsed.dreams)) throw new Error("INVALID_STORAGE");
        // 고정된 예시 정보는 파일에서 읽고, 사용자 수정 버전만 복원합니다.
        cached = { dreams: exampleDreams.map((dream, index) => ({ ...dream, scenes: parsed.dreams[index].scenes })), warning: null };
      }
    } catch {
      cached = { ...initialSnapshot, warning: "저장된 예시를 읽지 못해 기본 예시를 열었습니다. 새 수정본은 이 브라우저에 다시 저장됩니다." };
    }
  }
  return cached;
}

function subscribe(notify: () => void) {
  const onChange = () => notify();
  const onStorage = (event: StorageEvent) => {
    if (event.key !== STORAGE_KEY && event.key !== null) return;
    loaded = false;
    cached = initialSnapshot;
    notify();
  };
  window.addEventListener(CHANGE_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

export function useDreams() {
  return useSyncExternalStore(subscribe, readSnapshot, () => initialSnapshot);
}

export function saveScene(dreamId: string, sceneId: string, baseVersion: number, draft: SceneDraft) {
  const snapshot = readSnapshot();
  const dream = snapshot.dreams.find((item) => item.id === dreamId);
  const scene = dream?.scenes.find((item) => item.id === sceneId);
  if (!scene || latestVersion(scene).version !== baseVersion) {
    return { ok: false as const, message: "장면의 최신 버전이 바뀌었습니다. 수정창을 닫고 다시 열어 주세요." };
  }
  const dreams = snapshot.dreams.map((item) => item.id !== dreamId ? item : {
    ...item,
    scenes: item.scenes.map((target) => target.id !== sceneId ? target : {
      ...target, versions: [...target.versions, {
        ...draft, title: draft.title.trim(), place: draft.place.trim(), description: draft.description.trim(),
        version: baseVersion + 1, createdAt: new Date().toISOString(),
      }],
    }),
  });
  let persisted = true;
  try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ schemaVersion: 1, dreams })); }
  catch { persisted = false; }
  cached = { dreams, warning: persisted ? null : "브라우저 저장 공간을 사용할 수 없습니다. 이번 수정은 현재 화면에서만 유지됩니다." };
  window.dispatchEvent(new Event(CHANGE_EVENT));
  return { ok: true as const, persisted };
}
