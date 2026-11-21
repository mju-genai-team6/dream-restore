"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  getArchiveDream, getArchiveJob, getArchiveVideo, listArchiveDreams, listArchiveScenes,
  requestArchiveScenes, requestArchiveVideo, retryArchiveImages,
} from "./archive-api";
import { pollResult } from "./polling";
import type { Dream, ResultJob } from "./types";
import ResultsLayout, { type View } from "./ResultsLayout";
import ArchivePanel from "./ArchivePanel";
import StoryboardPanel from "./StoryboardPanel";
import VideoPanel from "./VideoPanel";
import styles from "./dream-results.module.css";

type Snapshot = { dream: Dream; job: ResultJob | null };
const active = (job?: { status: string } | null) => job?.status === "queued" || job?.status === "running";
const validId = (id: string) => /^[1-9]\d*$/.test(id) && Number.isSafeInteger(Number(id));
const message = (error: unknown) => error instanceof Error ? error.message : "다시 불러오지 못했어요.";
const stageLabels: Record<string, string> = {
  splitting: "꿈을 장면으로 나누고 있어요", prompting: "장면의 내용을 정리하고 있어요",
  requesting: "장면 이미지를 만들고 있어요", saving: "이미지를 저장하고 있어요",
  validating_input: "영상에 넣을 장면을 확인하고 있어요", postprocessing: "기억의 확신도를 영상에 반영하고 있어요",
  composing: "꿈의 장면을 영상으로 이어 붙이고 있어요", verifying: "완성된 영상을 확인하고 있어요",
};

function resultPath(id: string, view: View, jobId?: string) {
  const query = new URLSearchParams({ dreamId: id });
  if (view === "video") query.set("view", "video");
  if (jobId) query.set("jobId", jobId);
  return `/?${query}`;
}

function RequestError({ detail, onRetry }: { detail: string; onRetry: () => void }) {
  return <div className={`${styles.board} ${styles.emptyState}`}>
    <div role="alert"><h2>기록을 불러오지 못했어요</h2><p>{detail}</p></div>
    <button type="button" className={styles.secondaryButton} onClick={onRetry}>새로고침</button>
  </div>;
}

function ApiArchive({ baseUrl }: { baseUrl: string }) {
  const router = useRouter();
  const [dreams, setDreams] = useState<Dream[] | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    listArchiveDreams(baseUrl, controller.signal).then(
      (data) => { if (!controller.signal.aborted) setDreams(data); },
      (error) => { if (!controller.signal.aborted) setError(message(error)); },
    );
    return () => controller.abort();
  }, [baseUrl, attempt]);
  const selected = dreams?.find((dream) => dream.id === selectedId) ?? dreams?.[0];
  function navigate(view: View) {
    if (view !== "archive" && selected) router.push(resultPath(selected.id, view));
  }
  return <ResultsLayout view="archive" onNavigate={navigate} fromApi>
    {error ? <RequestError detail={error} onRetry={() => { setError(""); setDreams(null); setAttempt((n) => n + 1); }} />
      : !dreams ? <p className={styles.board} role="status">보관된 꿈을 불러오는 중입니다.</p>
      : <ArchivePanel dreams={dreams} selectedId={selected?.id ?? ""} onSelect={setSelectedId}
        onOpen={() => navigate("storyboard")} fromApi />}
  </ResultsLayout>;
}

function ApiDream({ baseUrl, id, jobId, view }: { baseUrl: string; id: string; jobId?: string; view: View }) {
  const router = useRouter();
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [timedOut, setTimedOut] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const submitting = useRef<AbortController | null>(null);

  useEffect(() => () => submitting.current?.abort(), []);
  useEffect(() => pollResult({
    async load(signal): Promise<Snapshot> {
      const dream = await getArchiveDream(baseUrl, id, signal);
      const scenes = await listArchiveScenes(baseUrl, dream, signal);
      const requestedJob = jobId ? await getArchiveJob(baseUrl, jobId, id, signal) : null;
      const video = dream.hasVideo ? await getArchiveVideo(baseUrl, id, signal) : null;
      return { dream: { ...dream, scenes, video }, job: dream.activeJob ?? requestedJob };
    },
    pending({ dream, job }) {
      return active(job) || dream.scenes.some((scene) => active({ status: scene.imageStatus })) ||
        // 마지막 이미지 저장과 꿈 상태 조회가 엇갈렸으면 한 번 더 확인합니다.
        (dream.status === "scenes_ready" && dream.scenes.length > 0 && dream.scenes.every((scene) => scene.imageStatus === "succeeded"));
    },
    onData: setSnapshot,
    onError: (error) => setError(message(error)),
    onTimeout: () => setTimedOut(true),
  }), [baseUrl, id, jobId, attempt]);

  function refresh() { setError(""); setTimedOut(false); setAttempt((n) => n + 1); }
  function navigate(next: View) { router.push(next === "archive" ? "/" : resultPath(id, next, jobId)); }

  async function request(kind: "images" | "scenes" | "video") {
    if (submitting.current) return;
    const controller = new AbortController();
    submitting.current = controller;
    setBusy(true);
    setError("");
    try {
      let nextJob: string | undefined;
      if (kind === "images") await retryArchiveImages(baseUrl, id, controller.signal);
      else if (kind === "scenes") nextJob = String((await requestArchiveScenes(baseUrl, id, controller.signal)).job_id);
      else nextJob = String((await requestArchiveVideo(baseUrl, id, controller.signal)).job_id);
      if (controller.signal.aborted) return;
      if (kind === "images") {
        // 이전 실패 작업 번호를 빼고 현재 꿈과 이미지 상태를 다시 확인합니다.
        router.replace(resultPath(id, view));
        refresh();
      } else router.replace(resultPath(id, kind === "video" ? "video" : "storyboard", nextJob));
    } catch (error) {
      if (!controller.signal.aborted) setError(message(error));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
      if (submitting.current === controller) submitting.current = null;
    }
  }

  const dream = snapshot?.dream;
  const job = snapshot?.job;
  const pendingImages = dream?.scenes.filter((scene) => active({ status: scene.imageStatus })).length ?? 0;
  const failedImages = dream?.scenes.filter((scene) => scene.imageStatus === "failed").length ?? 0;
  const working = active(job) || pendingImages > 0;
  const canRender = dream && ["images_ready", "rendered"].includes(dream.status) && dream.scenes.length > 0 &&
    dream.scenes.every((scene) => scene.imageStatus === "succeeded") && !working;
  const renderFailed = job?.type === "render_video" && job.status === "failed";

  return <ResultsLayout view={view} onNavigate={navigate} dream={dream} fromApi>
    {error && (dream ? <div className={styles.warning} role="alert">{error} <button type="button" className={styles.secondaryButton} onClick={refresh}>새로고침</button></div>
      : <RequestError detail={error} onRetry={refresh} />)}
    {timedOut && <div className={styles.warning} role="status">자동 확인을 멈췄어요. 생성이 계속되고 있을 수 있으니 새로고침해 주세요. <button type="button" className={styles.secondaryButton} onClick={refresh}>새로고침</button></div>}
    {!snapshot && !error && !timedOut && <p className={styles.board} role="status">꿈의 결과를 불러오는 중입니다.</p>}
    {dream && <>
      {!timedOut && !error && working && <p className={styles.progressNotice} role="status">
        {active(job) ? (job?.stage && stageLabels[job.stage]) || "생성을 기다리고 있어요" : "장면 이미지를 만들고 있어요"}
        {dream.scenes.length > 0 && ` · 이미지 ${dream.scenes.filter((scene) => scene.imageStatus === "succeeded").length}/${dream.scenes.length}개 완료`}
      </p>}
      {job?.status === "failed" && <div className={styles.warning} role="alert">
        {renderFailed ? "영상을 만들지 못했어요. 장면은 그대로 보관되어 있어요."
          : job.error?.message || "생성 작업을 완료하지 못했어요. 다시 시도해 주세요."}
        {renderFailed && canRender && <p>잠시 후 아래 ‘영상 다시 시도’를 눌러 주세요. 문제가 계속되면 나중에 다시 이용해 주세요.</p>}
        {job.type === "generate_scenes" && dream.status === "interviewing" &&
          <button type="button" className={styles.secondaryButton} disabled={busy} onClick={() => request("scenes")}>장면 생성 다시 시도</button>}
      </div>}
      {failedImages > 0 && <div className={styles.warning} role="alert">이미지를 만들지 못한 장면이 {failedImages}개 있어요.
        {dream.status === "scenes_ready" && !working && <button type="button" className={styles.secondaryButton} disabled={busy} onClick={() => request("images")}>{busy ? "요청 중" : "실패한 이미지 다시 만들기"}</button>}
      </div>}
      {!dream.scenes.length && !working && job?.status !== "failed" && <p className={styles.warning}>
        아직 준비된 장면이 없어요. <Link href={`/record/${id}/confidence`}>꿈 기록 단계 확인하기</Link>
      </p>}
      <div className={styles.resultActions}>
        <button type="button" className={styles.secondaryButton} onClick={refresh} disabled={busy}>새로고침</button>
        <button type="button" className={styles.primaryButton} disabled={busy || !canRender} onClick={() => request("video")}>{busy ? "요청 중" : renderFailed ? "영상 다시 시도" : dream.video ? "영상 다시 만들기" : "영상 만들기"}</button>
      </div>
      {view === "video" ? <VideoPanel dream={dream} onStoryboard={() => navigate("storyboard")} fromApi />
        : <StoryboardPanel dream={dream} fromApi />}
    </>}
  </ResultsLayout>;
}

export default function ApiResults({ baseUrl, dreamId, jobId, view }: {
  baseUrl: string; dreamId?: string; jobId?: string; view?: string;
}) {
  const router = useRouter();
  if ((dreamId !== undefined && !validId(dreamId)) || (jobId !== undefined && (!dreamId || !validId(jobId)))) {
    return <ResultsLayout view="storyboard" onNavigate={() => router.push("/")} fromApi>
      <div className={`${styles.board} ${styles.emptyState}`} role="alert"><h2>꿈 기록 주소를 확인해 주세요</h2><Link href="/">보관함으로 돌아가기</Link></div>
    </ResultsLayout>;
  }
  return dreamId ? <ApiDream baseUrl={baseUrl} id={dreamId} jobId={jobId} view={view === "video" ? "video" : "storyboard"} />
    : <ApiArchive baseUrl={baseUrl} />;
}
