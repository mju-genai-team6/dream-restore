"use client";

import { useState } from "react";
import { useDreams } from "./store";
import { formatDate } from "./types";
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

export default function DreamResults() {
  const { dreams, warning } = useDreams();
  const [view, setView] = useState<View>("storyboard");
  const [dreamId, setDreamId] = useState(dreams[0]?.id ?? "");
  const dream = dreams.find((item) => item.id === dreamId) ?? dreams[0];
  const currentView = views.find((item) => item.id === view)!;
  return <div className={styles.app}>
    <aside className={styles.sidebar}>
      <div className={styles.brand}><span className={styles.brandMark}>✦</span><div><strong>꿈 기록</strong><span>기억을 한 장면씩</span></div></div>
      <nav className={styles.navigation} aria-label="결과 및 보관 메뉴">{views.map((item) => <button type="button" key={item.id} className={`${styles.navItem} ${view === item.id ? styles.activeNav : ""}`} aria-current={view === item.id ? "page" : undefined} onClick={() => setView(item.id)}><Icon name={item.icon} size={21} />{item.title}</button>)}</nav>
      <div className={styles.sidebarDecoration} aria-hidden="true"><span>✧</span><Icon name="moon" size={62} /><span>✦</span></div>
      <div className={styles.demoInfo}><span className={styles.demoBadge}>예시 모드</span><p>수정한 내용은<br />이 브라우저에만 보관돼요.</p></div>
    </aside>
    <main className={styles.main}>
      <header className={styles.pageHeader}><div className={styles.headingGroup}><span className={styles.headingIcon}><Icon name={currentView.icon} size={26} /></span><div><h1>{currentView.title}</h1><p>{currentView.description}</p></div></div>{dream && view !== "archive" && <div className={styles.dreamContext}><span>{dream.title}</span><time dateTime={dream.recordedAt}><Icon name="calendar" size={15} />{formatDate(dream.recordedAt)}</time></div>}</header>
      {warning && <p className={styles.warning} role="alert">{warning}</p>}
      {view === "archive" ? <ArchivePanel dreams={dreams} selectedId={dreamId} onSelect={setDreamId} onOpen={() => setView("storyboard")} /> : dream ? view === "storyboard" ? <StoryboardPanel key={dream.id} dream={dream} /> : <VideoPanel dream={dream} onStoryboard={() => setView("storyboard")} /> : <div className={styles.emptyState}><h2>아직 보관된 꿈이 없어요</h2><p>기록된 꿈이 생기면 이곳에서 확인할 수 있어요.</p></div>}
    </main>
  </div>;
}
