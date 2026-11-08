export type Confidence = "high" | "medium" | "low";
export type DreamStatus = "recorded" | "interviewing" | "scenes_ready" | "images_ready" | "rendered";
export type JobStatus = "queued" | "running" | "succeeded" | "failed";
export type ArtworkKind = "school" | "sea" | "village" | "house" | "person";

export type DreamElement = {
  id: string;
  name: string;
  confidence: Confidence;
};

export type SceneVersion = {
  version: number;
  title: string;
  place: string;
  description: string;
  elements: DreamElement[];
  createdAt: string;
};

export type Scene = {
  id: string;
  artwork: ArtworkKind;
  imageStatus: JobStatus;
  versions: SceneVersion[];
};

export type DreamVideo = {
  url: string;
  // 장면 수정 후 이전 영상과 현재 스토리보드를 구분하는 기준입니다.
  sceneVersions: Record<string, number>;
};

export type Dream = {
  id: string;
  title: string;
  recordedAt: string;
  originalText: string;
  status: DreamStatus;
  scenes: Scene[];
  video: DreamVideo | null;
};

export type SceneDraft = Omit<SceneVersion, "version" | "createdAt">;

export const confidenceLabels: Record<Confidence, string> = {
  high: "확실",
  medium: "보통",
  low: "흐릿",
};

export function latestVersion(scene: Scene): SceneVersion {
  return scene.versions[scene.versions.length - 1];
}

export function formatDate(value: string) {
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric", month: "long", day: "numeric", timeZone: "Asia/Seoul",
  }).format(new Date(value));
}

export function videoMatchesScenes(dream: Dream) {
  return Boolean(dream.video && dream.scenes.every(
    (scene) => dream.video!.sceneVersions[scene.id] === latestVersion(scene).version,
  ));
}
