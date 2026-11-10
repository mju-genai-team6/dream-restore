"use client";

import { useRef, useState, type FormEvent } from "react";
import { confidenceLabels, latestVersion, type Dream, type Scene, type SceneDraft } from "./types";
import { saveScene } from "./store";
import SceneArtwork from "./SceneArtwork";
import Icon from "./Icon";
import styles from "./dream-results.module.css";

function SceneEditor({ dreamId, scene, onClose, onSaved }: {
  dreamId: string; scene: Scene; onClose: () => void; onSaved: (message: string) => void;
}) {
  const [base] = useState(() => latestVersion(scene));
  const [draft, setDraft] = useState<SceneDraft>({ title: base.title, place: base.place, description: base.description, elements: base.elements.map((item) => ({ ...item })) });
  const [error, setError] = useState("");
  const submitting = useRef(false);
  const changed = JSON.stringify(draft) !== JSON.stringify({ title: base.title, place: base.place, description: base.description, elements: base.elements });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || !changed) return;
    if (![draft.title, draft.place, draft.description].every((value) => value.trim())) { setError("제목, 장소, 설명을 모두 입력해 주세요."); return; }
    submitting.current = true;
    const result = saveScene(dreamId, scene.id, base.version, draft);
    if (!result.ok) { submitting.current = false; setError(result.message); return; }
    onSaved(result.persisted ? `수정본 v${base.version + 1}를 이 브라우저에 저장했습니다.` : "수정한 내용이 현재 화면에 적용되었습니다. 브라우저 저장은 실패했습니다.");
    onClose();
  }
  return <form className={styles.editForm} onSubmit={submit}>
    <div className={styles.panelHeading}><h2>장면 내용 수정</h2><button type="button" className={styles.iconButton} onClick={onClose} aria-label="수정 취소"><Icon name="close" size={18} /></button></div>
    <p className={styles.helper}>기억과 다른 내용을 직접 고쳐 주세요.</p>
    <label className={styles.field}>장면 제목<input autoFocus value={draft.title} maxLength={60} required onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></label>
    <label className={styles.field}>장소<input value={draft.place} maxLength={80} required onChange={(e) => setDraft({ ...draft, place: e.target.value })} /></label>
    <label className={styles.field}>장면 설명<textarea value={draft.description} maxLength={1200} rows={5} required onChange={(e) => setDraft({ ...draft, description: e.target.value })} /><span className={styles.characterCount}>{draft.description.length} / 1200</span></label>
    <fieldset className={styles.confidenceFields}><legend>요소별 기억의 확신도</legend>{draft.elements.map((element, index) =>
      <label key={element.id}><span>{element.name}</span><select value={element.confidence} onChange={(event) => setDraft({ ...draft, elements: draft.elements.map((item, i) => i === index ? { ...item, confidence: event.target.value as typeof item.confidence } : item) })}>{Object.entries(confidenceLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>,
    )}</fieldset>
    <p className={styles.editNote}>예시 모드에서는 글과 확신도만 변경됩니다. 이미지 재생성은 서버 연결 후 제공됩니다.</p>
    {error && <p className={styles.error} role="alert">{error}</p>}
    <div className={styles.formActions}><button type="button" className={styles.secondaryButton} onClick={onClose}>취소</button><button type="submit" className={styles.primaryButton} disabled={!changed}>수정본 저장</button></div>
  </form>;
}

export default function StoryboardPanel({ dream }: { dream: Dream }) {
  const [selectedId, setSelectedId] = useState(dream.scenes[0]?.id);
  const [editing, setEditing] = useState(false);
  const [viewedVersion, setViewedVersion] = useState<number | null>(null);
  const [notice, setNotice] = useState("");
  const selected = dream.scenes.find((scene) => scene.id === selectedId) ?? dream.scenes[0];
  const current = selected && latestVersion(selected);
  const version = selected?.versions.find((item) => item.version === viewedVersion) ?? current;
  function selectScene(id: string) { setSelectedId(id); setViewedVersion(null); setNotice(""); setEditing(false); }
  return <div className={styles.workspace}>
    <section className={styles.centerColumn} aria-label="스토리보드 장면 목록">
      <div className={styles.board}>
        <div className={styles.boardHeading}><div><h2>꿈의 장면들 <span>{dream.scenes.length}</span></h2><p>장면을 선택해 내용을 확인해 보세요.</p></div><span className={styles.smallBadge}>예시 이미지</span></div>
        {dream.scenes.length ? <div className={styles.sceneGrid}>{dream.scenes.map((scene, index) => {
          const latest = latestVersion(scene);
          return <button type="button" key={scene.id} className={`${styles.sceneCard} ${selected?.id === scene.id ? styles.selectedCard : ""}`} aria-pressed={selected?.id === scene.id} aria-label={`장면 ${index + 1} ${latest.title} 선택`} onClick={() => selectScene(scene.id)}>
            <div className={styles.sceneImage}><SceneArtwork kind={scene.artwork} label={latest.title} /><span className={styles.versionBadge}>v{latest.version}</span>{selected?.id === scene.id && <span className={styles.selectionCheck}><Icon name="check" size={14} /></span>}</div>
            <div className={styles.sceneCardBody}><span className={styles.sceneNumber}>{index + 1}</span><div><h3>{latest.title}</h3><p>{latest.description}</p></div></div>
          </button>;
        })}</div> : <div className={styles.emptyState}><Icon name="storyboard" size={34} /><h3>아직 준비된 장면이 없어요</h3><p>장면이 준비되면 이곳에서 확인할 수 있어요.</p></div>}
      </div>
      {selected && version && <section className={styles.selectedSummary} aria-label="선택한 장면 미리보기">
        <div className={styles.summaryImage}><SceneArtwork kind={selected.artwork} label={version.title} /></div>
        <div className={styles.summaryText}><span className={styles.eyebrow}>선택한 장면</span><h2>{version.title}</h2><p>{version.description}</p><span className={styles.location}><Icon name="pin" size={15} />{version.place}</span></div>
      </section>}
      <p className={styles.bottomNote}><Icon name="info" size={14} />이미지는 화면 확인용 예시이며, 장면을 수정해도 자동으로 바뀌지 않습니다.</p>
    </section>
    <aside className={styles.detailPanel} aria-label="선택한 장면 상세">
      {selected && version && current ? editing ? <SceneEditor key={selected.id} dreamId={dream.id} scene={selected} onClose={() => setEditing(false)} onSaved={(message) => { setNotice(message); setViewedVersion(null); }} /> : <>
        <div className={styles.panelHeading}><h2>장면 자세히 보기</h2><span className={styles.smallBadge}>v{version.version}</span></div>
        <p className={styles.helper}>꿈의 내용과 기억의 확신도를 확인하세요.</p>
        <div className={styles.detailImage}><SceneArtwork kind={selected.artwork} label={version.title} /></div>
        <div className={styles.detailTitle}><h3>{version.title}</h3><span className={styles.location}><Icon name="pin" size={14} />{version.place}</span></div>
        <p className={styles.sceneDescription}>{version.description}</p>
        <section className={styles.confidenceSection}><h3>요소별 기억의 확신도</h3><ul>{version.elements.map((element) => <li key={element.id}><span>{element.name}</span><span className={`${styles.confidenceBadge} ${styles[element.confidence]}`}>{confidenceLabels[element.confidence]}</span></li>)}</ul><p>기억이 분명한 정도이며, AI의 정확도를 뜻하지 않아요.</p></section>
        {selected.versions.length > 1 && <label className={styles.versionSelect}><span><Icon name="clock" size={15} />수정 이력</span><select aria-label="장면 버전" value={version.version} onChange={(event) => setViewedVersion(Number(event.target.value))}>{selected.versions.map((item) => <option key={item.version} value={item.version}>버전 {item.version}{item.version === current.version ? " · 최신" : " · 이전 내용"}</option>)}</select></label>}
        {version.version !== current.version && <p className={styles.editNote}>이전 버전의 내용입니다. 수정은 최신 버전을 기준으로 시작합니다.</p>}
        {notice && <p className={styles.success} role="status">{notice}</p>}
        <button type="button" className={styles.primaryButton} onClick={() => { setViewedVersion(null); setEditing(true); setNotice(""); }}><Icon name="edit" size={16} />장면 내용 수정</button>
      </> : <div className={styles.panelEmpty}><Icon name="storyboard" size={28} /><p>확인할 장면을 선택해 주세요.</p></div>}
    </aside>
  </div>;
}
