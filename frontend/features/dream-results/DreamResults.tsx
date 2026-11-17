"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useDreams } from "./store";
import { formatDate, type Dream, type Scene } from "./types";
import { listArchiveDreams, listArchiveScenes } from "./archive-api";
import StoryboardPanel from "./StoryboardPanel";
import ArchivePanel from "./ArchivePanel";
import VideoPanel from "./VideoPanel";
import Icon, { type IconName } from "./Icon";
import styles from "./dream-results.module.css";

type View = "storyboard" | "video" | "archive";
const views: { id: View; title: string; icon: IconName; description: string }[] = [
  { id: "storyboard", title: "스토리보드", icon: "storyboard", description: "꿈의 장면을 확인하고, 기억과 다른 내용을 수정해 보세요." },
  { id: "video", title: "영상 결과", icon: "video", description: "장면으로 완성된 꿈 영상을 다시 감상해 보세요." },
  { id: "archive", title: "꿈 보관함", icon: "archive", description: "차곡차곡 남긴 꿈을 다시 열어 보세요." },
];

type RequestState<T> = { data: T } | { error: string } | null;

function ResultsLayout({ view, onNavigate, dream, fromApi = false, children }: {
  view: View;
  onNavigate: (view: View) => void;
  dream?: Dream;
  fromApi?: boolean;
  children: ReactNode;
}) {
  const currentView = views.find((item) => item.id === view)!;
  const availableViews = fromApi ? views.filter((item) => item.id !== "video") : views;
  const description = fromApi && view === "storyboard"
    ? "선택한 꿈의 장면과 기억의 확신도를 확인하세요."
    : currentView.description;

  return <div className={styles.app}>
    <aside className={styles.sidebar}>
      <div className={styles.brand}><span className={styles.brandMark}>✦</span><div><strong>꿈 기록</strong><span>기억을 한 장면씩</span></div></div>
      <nav className={styles.navigation} aria-label="결과 및 보관 메뉴">
        {availableViews.map((item) => <button type="button" key={item.id} className={`${styles.navItem} ${view === item.id ? styles.activeNav : ""}`} aria-current={view === item.id ? "page" : undefined} onClick={() => onNavigate(item.id)}><Icon name={item.icon} size={21} />{item.title}</button>)}
      </nav>
      <div className={styles.sidebarDecoration} aria-hidden="true"><span>✧</span><Icon name="moon" size={62} /><span>✦</span></div>
      <div className={styles.demoInfo}>
        <span className={styles.demoBadge}>{fromApi ? "서버 조회 모드" : "예시 모드"}</span>
        {fromApi ? <p>꿈 목록과 장면을 조회해요.</p> : <p>수정한 내용은<br />이 브라우저에만 보관돼요.</p>}
      </div>
    </aside>
    <main className={styles.main}>
      <header className={styles.pageHeader}>
        <div className={styles.headingGroup}><span className={styles.headingIcon}><Icon name={currentView.icon} size={26} /></span><div><h1>{currentView.title}</h1><p>{description}</p></div></div>
        {dream && view !== "archive" && <div className={styles.dreamContext}><span>{dream.title}</span><time dateTime={dream.recordedAt}><Icon name="calendar" size={15} />{formatDate(dream.recordedAt)}</time></div>}
      </header>
      {children}
    </main>
  </div>;
}

function DemoResults() {
  const { dreams, warning } = useDreams();
  const [view, setView] = useState<View>("storyboard");
  const [dreamId, setDreamId] = useState(dreams[0]?.id ?? "");
  const dream = dreams.find((item) => item.id === dreamId) ?? dreams[0];
  return <ResultsLayout view={view} onNavigate={setView} dream={dream}>
      {warning && <p className={styles.warning} role="alert">{warning}</p>}
      {view === "archive" ? <ArchivePanel dreams={dreams} selectedId={dreamId} onSelect={setDreamId} onOpen={() => setView("storyboard")} /> : dream ? view === "storyboard" ? <StoryboardPanel key={dream.id} dream={dream} /> : <VideoPanel dream={dream} onStoryboard={() => setView("storyboard")} /> : <div className={styles.emptyState}><h2>아직 보관된 꿈이 없어요</h2><p>기록된 꿈이 생기면 이곳에서 확인할 수 있어요.</p></div>}
  </ResultsLayout>;
}

function RequestError({ title, detail, onRetry }: {
  title: string; detail: string; onRetry: () => void;
}) {
  return <div className={`${styles.board} ${styles.emptyState}`}>
    <div role="alert"><h2>{title}</h2><p>{detail}</p></div>
    <button type="button" className={styles.secondaryButton} onClick={onRetry}>다시 시도</button>
  </div>;
}

function ArchiveStoryboard({ baseUrl, dream }: { baseUrl: string; dream: Dream }) {
  const [result, setResult] = useState<RequestState<Scene[]>>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listArchiveScenes(baseUrl, dream, controller.signal).then(
      (data) => { if (!controller.signal.aborted) setResult({ data }); },
      (error: Error) => { if (!controller.signal.aborted) setResult({ error: error.message }); },
    );
    return () => controller.abort();
  }, [baseUrl, dream, attempt]);

  if (!result) return <p className={styles.board} role="status">꿈의 장면을 불러오는 중입니다.</p>;
  if ("error" in result) return <RequestError title="장면을 불러오지 못했어요" detail={result.error}
    onRetry={() => { setResult(null); setAttempt((value) => value + 1); }} />;
  return <StoryboardPanel dream={{ ...dream, scenes: result.data }} fromApi />;
}

function ApiResults({ baseUrl }: { baseUrl: string }) {
  const [result, setResult] = useState<RequestState<Dream[]>>(null);
  const [attempt, setAttempt] = useState(0);
  const [view, setView] = useState<View>("archive");
  const [dreamId, setDreamId] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    listArchiveDreams(baseUrl, controller.signal).then(
      (data) => { if (!controller.signal.aborted) setResult({ data }); },
      (error: Error) => { if (!controller.signal.aborted) setResult({ error: error.message }); },
    );
    return () => controller.abort();
  }, [baseUrl, attempt]);

  const dreams = result && "data" in result ? result.data : [];
  const dream = dreams.find((item) => item.id === dreamId) ?? dreams[0];
  return <ResultsLayout view={view} onNavigate={setView} dream={dream} fromApi>
    {!result ? <p className={styles.board} role="status">보관된 꿈을 불러오는 중입니다.</p>
      : "error" in result ? <RequestError title="꿈 목록을 불러오지 못했어요" detail={result.error}
        onRetry={() => { setResult(null); setAttempt((value) => value + 1); }} />
      : view === "storyboard" && dream ? <ArchiveStoryboard key={dream.id} baseUrl={baseUrl} dream={dream} />
      : <ArchivePanel dreams={dreams} selectedId={dream?.id ?? ""} onSelect={setDreamId}
        onOpen={() => setView("storyboard")} fromApi />}
  </ResultsLayout>;
}

export default function DreamResults() {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim().replace(/\/+$/, "");
  return baseUrl ? <ApiResults baseUrl={baseUrl} /> : <DemoResults />;
}
