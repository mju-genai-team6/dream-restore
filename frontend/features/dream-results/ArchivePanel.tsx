"use client";

import { useState } from "react";
import { formatDate, latestVersion, videoMatchesScenes, type Dream } from "./types";
import Icon from "./Icon";
import SceneArtwork from "./SceneArtwork";
import styles from "./dream-results.module.css";

export default function ArchivePanel({ dreams, selectedId, onSelect, onOpen }: {
  dreams: Dream[]; selectedId: string; onSelect: (id: string) => void; onOpen: () => void;
}) {
  const [query, setQuery] = useState("");
  const filtered = dreams.filter((dream) => dream.title.includes(query.trim()));
  const selected = dreams.find((dream) => dream.id === selectedId);
  const first = selected?.scenes[0];
  return <div className={styles.workspace}>
    <section className={styles.board} aria-label="보관된 꿈 목록">
      <div className={styles.boardHeading}><div><h2>보관된 꿈 <span>{dreams.length}</span></h2><p>기록을 선택하면 내용을 다시 볼 수 있어요.</p></div></div>
      <label className={styles.search}><Icon name="search" size={18} /><span className={styles.srOnly}>꿈 제목 검색</span><input type="search" placeholder="꿈 제목으로 검색" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      <div className={styles.archiveList}>{filtered.map((dream) => {
        const scene = dream.scenes[0];
        return <button type="button" key={dream.id} className={`${styles.archiveCard} ${selectedId === dream.id ? styles.selectedArchive : ""}`} aria-pressed={selectedId === dream.id} onClick={() => onSelect(dream.id)} aria-label={`${dream.title} 선택`}>
          <div className={styles.archiveImage}>{scene ? <SceneArtwork kind={scene.artwork} label={dream.title} /> : <Icon name="storyboard" size={30} />}</div>
          <div className={styles.archiveInfo}><time dateTime={dream.recordedAt}>{formatDate(dream.recordedAt)}</time><h3>{dream.title}</h3><p>{dream.originalText}</p><span>{dream.scenes.length}개 장면 <span aria-hidden="true">·</span> {videoMatchesScenes(dream) ? "영상 있음" : dream.video ? "수정 전 영상 있음" : "장면 기록"}</span></div><Icon name="arrow" size={18} />
        </button>;
      })}</div>
      {!filtered.length && <div className={styles.emptyState}><Icon name="search" size={30} /><h3>{query ? "검색한 제목의 꿈이 없어요" : "아직 보관된 꿈이 없어요"}</h3><p>{query ? "다른 제목으로 다시 찾아보세요." : "저장된 꿈은 이곳에서 다시 볼 수 있어요."}</p>{query && <button type="button" className={styles.secondaryButton} onClick={() => setQuery("")}>전체 꿈 보기</button>}</div>}
    </section>
    <aside className={styles.detailPanel} aria-label="보관된 꿈 상세">
      {selected ? <>
        <div className={styles.panelHeading}><h2>꿈 기록</h2><Icon name="archive" size={19} /></div>
        {first && <div className={styles.detailImage}><SceneArtwork kind={first.artwork} label={selected.title} /></div>}
        <time className={styles.detailDate} dateTime={selected.recordedAt}>{formatDate(selected.recordedAt)}</time>
        <h3 className={styles.archiveDetailTitle}>{selected.title}</h3>
        <section className={styles.originalRecord}><h4>처음 남긴 꿈 이야기</h4><p>{selected.originalText}</p></section>
        <dl className={styles.facts}><div><dt>장면</dt><dd>{selected.scenes.length}개</dd></div><div><dt>수정한 장면</dt><dd>{selected.scenes.filter((scene) => latestVersion(scene).version > 1).length}개</dd></div><div><dt>영상</dt><dd>{videoMatchesScenes(selected) ? "재생 가능" : selected.video ? "수정 전 영상" : "아직 없음"}</dd></div></dl>
        <button type="button" className={styles.primaryButton} onClick={onOpen}>장면 열기<Icon name="arrow" size={16} /></button>
      </> : <div className={styles.panelEmpty}><Icon name="archive" size={30} /><p>확인할 꿈을 선택해 주세요.</p></div>}
    </aside>
  </div>;
}
