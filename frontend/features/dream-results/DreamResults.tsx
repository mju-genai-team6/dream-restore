"use client";

import { useState } from "react";
import { useDreams } from "./store";
import StoryboardPanel from "./StoryboardPanel";
import ArchivePanel from "./ArchivePanel";
import VideoPanel from "./VideoPanel";
import ResultsLayout, { type View } from "./ResultsLayout";
import ApiResults from "./ApiResults";
import styles from "./dream-results.module.css";

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

export default function DreamResults(props: { dreamId?: string; jobId?: string; view?: string }) {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim().replace(/\/+$/, "");
  return baseUrl ? <ApiResults key={JSON.stringify(props)} baseUrl={baseUrl} {...props} /> : <DemoResults />;
}
