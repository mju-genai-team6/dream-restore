"use client";

import { useState } from "react";
import { formatDate, videoMatchesScenes, type Dream } from "./types";
import Icon from "./Icon";
import styles from "./dream-results.module.css";

function VideoPlayer({ url, title }: { url: string; title: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <div className={styles.emptyState} role="alert"><Icon name="info" size={30} /><h3>영상을 불러오지 못했어요</h3><p>영상 파일이나 연결 상태를 확인한 뒤 다시 시도해 주세요.</p><button type="button" className={styles.secondaryButton} onClick={() => setFailed(false)}>다시 불러오기</button></div>;
  return <video className={styles.videoPlayer} controls preload="metadata" src={url} aria-label={`${title} 영상`} onError={() => setFailed(true)}>현재 브라우저에서 영상을 재생할 수 없습니다.</video>;
}

export default function VideoPanel({ dream, onStoryboard }: { dream: Dream; onStoryboard: () => void }) {
  const currentVideo = videoMatchesScenes(dream);
  return <div className={styles.workspace}>
    <section className={styles.board} aria-label="꿈 영상 결과">
      <div className={styles.boardHeading}><div><h2>꿈 영상</h2><p>{dream.title}</p></div><span className={styles.smallBadge}>{currentVideo ? "재생 가능" : dream.video ? "수정 전 영상" : "영상 대기"}</span></div>
      {dream.video ? <>
        {!currentVideo && <p className={styles.warning} role="status">장면을 수정하기 전의 영상입니다. 현재 스토리보드와 내용이 다를 수 있어요.</p>}
        <VideoPlayer key={dream.video.url} url={dream.video.url} title={dream.title} />
      </> : <div className={styles.videoEmpty}><span className={styles.playSymbol}><Icon name="video" size={36} /></span><h3>아직 완성된 영상이 없어요</h3><p>장면을 확인한 뒤 완성된 꿈 영상을<br />이곳에서 다시 볼 수 있어요.</p><button type="button" className={styles.secondaryButton} onClick={onStoryboard}>스토리보드 확인<Icon name="arrow" size={16} /></button></div>}
      <p className={styles.videoNote}><Icon name="info" size={16} />예시 모드에서는 영상이 생성되지 않습니다. 영상 생성 결과를 연결하면 재생할 수 있습니다.</p>
    </section>
    <aside className={styles.detailPanel} aria-label="영상의 꿈 정보">
      <div className={styles.panelHeading}><h2>이 꿈의 기록</h2><Icon name="video" size={19} /></div>
      <p className={styles.videoDreamTitle}>{dream.title}</p><p className={styles.helper}>{formatDate(dream.recordedAt)}</p>
      <dl className={styles.facts}><div><dt>장면 수</dt><dd>{dream.scenes.length}개</dd></div><div><dt>영상 상태</dt><dd>{currentVideo ? "최신 장면 반영" : dream.video ? "수정 전 결과" : "생성 결과 없음"}</dd></div></dl>
      <section className={styles.originalRecord}><h3>장면 순서</h3><ol className={styles.videoSceneList}>{dream.scenes.map((scene, index) => <li key={scene.id}><span>{index + 1}</span>{scene.versions[scene.versions.length - 1].title}</li>)}</ol></section>
      <button type="button" className={styles.secondaryButton} onClick={onStoryboard}>장면으로 돌아가기</button>
    </aside>
  </div>;
}
