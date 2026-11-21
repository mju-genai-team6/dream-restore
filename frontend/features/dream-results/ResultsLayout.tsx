"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { formatDate, type Dream } from "./types";
import Icon, { type IconName } from "./Icon";
import styles from "./dream-results.module.css";

export type View = "storyboard" | "video" | "archive";
const views: { id: View; title: string; icon: IconName; description: string }[] = [
  { id: "storyboard", title: "스토리보드", icon: "storyboard", description: "꿈의 장면을 확인하고, 기억과 다른 내용을 수정해 보세요." },
  { id: "video", title: "영상 결과", icon: "video", description: "장면으로 완성된 꿈 영상을 다시 감상해 보세요." },
  { id: "archive", title: "꿈 보관함", icon: "archive", description: "차곡차곡 남긴 꿈을 다시 열어 보세요." },
];

export default function ResultsLayout({ view, onNavigate, dream, fromApi = false, children }: {
  view: View;
  onNavigate: (view: View) => void;
  dream?: Dream;
  fromApi?: boolean;
  children: ReactNode;
}) {
  const currentView = views.find((item) => item.id === view)!;
  const availableViews = views;
  const description = fromApi && view === "storyboard"
    ? "선택한 꿈의 장면과 기억의 확신도를 확인하세요."
    : currentView.description;

  return <div className={styles.app}>
    <aside className={styles.sidebar}>
      <div className={styles.brand}><span className={styles.brandMark}>✦</span><div><strong>꿈 기록</strong><span>기억을 한 장면씩</span></div></div>
      <nav className={styles.navigation} aria-label="결과 및 보관 메뉴">
        <Link href="/record" className={styles.navItem}><Icon name="mic" size={21} />꿈 기록하기</Link>
        {availableViews.map((item) => <button type="button" key={item.id} className={`${styles.navItem} ${view === item.id ? styles.activeNav : ""}`} aria-current={view === item.id ? "page" : undefined} onClick={() => onNavigate(item.id)}><Icon name={item.icon} size={21} />{item.title}</button>)}
      </nav>
      <div className={styles.sidebarDecoration} aria-hidden="true"><span>✧</span><Icon name="moon" size={62} /><span>✦</span></div>
      <div className={styles.demoInfo}>
        <span className={styles.demoBadge}>{fromApi ? "서버 조회 모드" : "예시 모드"}</span>
        {fromApi ? <p>기록한 꿈의 장면과 영상을 확인해요.</p> : <p>수정한 내용은<br />이 브라우저에만 보관돼요.</p>}
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

