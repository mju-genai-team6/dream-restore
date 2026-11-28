"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import NodeMedia from "./NodeMedia";
import Icon from "./Icon";
import { findDuplicate } from "./world-api";
import { formatShortDate, kindLabels, kindSubject, LIMITS, type EntityDraft, type World, type WorldEntity, type WorldNode } from "./types";
import styles from "./dream-world.module.css";

const appearanceRows = [
  { key: "ageRange", label: "나이대" },
  { key: "hair", label: "머리" },
  { key: "outfit", label: "옷차림" },
  { key: "features", label: "특징" },
] as const;

export function EntityDetail({ node, world, routeId, onEdit, onSelect, onRoute }: {
  node: WorldNode; world: World; routeId: string | null;
  onEdit: () => void; onSelect: (id: string) => void; onRoute: (dreamId: string | null) => void;
}) {
  const rows = appearanceRows.filter((row) => node.kind === "person" || row.key === "features");
  const neighbors = world.edges
    .filter((edge) => edge.from === node.id || edge.to === node.id)
    .map((edge) => ({ node: world.nodes.find((item) => item.id === (edge.from === node.id ? edge.to : edge.from))!, dreams: edge.dreams }))
    .filter((item) => item.node)
    .sort((a, b) => b.dreams - a.dreams);
  const pending = node.appearances.filter((item) => item.matchedBy === "name").length;

  return <>
    <div className={styles.entityHead}>
      <span className={`${styles.entityImage} ${styles[node.kind]}`}><NodeMedia node={node} /></span>
      <div>
        <h2>{node.name} <span className={styles.kindBadge}>{kindLabels[node.kind]}</span></h2>
        <p>{node.appearances.length ? `꿈 ${node.appearances.length}개에 나왔어요` : "아직 나온 꿈이 없어요"}</p>
      </div>
      <button type="button" className={styles.iconButton} onClick={onEdit} aria-label={`${node.name} 외형 수정`}><Icon name="edit" size={16} /></button>
    </div>

    <section className={styles.panelBox}>
      <h3>{node.kind === "person" ? "등록한 외형" : "등록한 모습"}</h3>
      <dl className={styles.appearance}>
        {rows.map((row) => <div key={row.key}><dt>{row.label}</dt><dd>{node[row.key] || <span className={styles.muted}>비어 있음</span>}</dd></div>)}
      </dl>
      <p className={styles.panelNote}>이 내용은 이 {kindSubject[node.kind]} 나오는 장면 이미지를 만들 때 함께 들어가, 다른 날의 꿈에서도 같은 모습으로 그려져요.</p>
    </section>

    {neighbors.length > 0 && <section className={styles.panelSection}>
      <h3><Icon name="link" size={15} />함께 나온 항목</h3>
      <div className={styles.chips}>{neighbors.map((item) =>
        <button type="button" key={item.node.id} className={styles.chip} onClick={() => onSelect(item.node.id)}>
          {item.node.name}<small>{item.dreams}번</small>
        </button>)}</div>
    </section>}

    <section className={styles.panelSection}>
      <h3>이 {kindSubject[node.kind]} 나온 꿈</h3>
      {node.appearances.length ? <ul className={styles.dreamList}>{node.appearances.map((item) =>
        <li key={item.dreamId} className={routeId === item.dreamId ? styles.dreamOn : undefined}>
          <Link href={`/?dreamId=${encodeURIComponent(item.dreamId)}`} className={styles.dreamItem} aria-label={`${formatShortDate(item.recordedAt)} 꿈 스토리보드 열기`}>
            <span className={styles.dreamThumb}><NodeMedia node={{ name: item.path[0] ?? node.name, imageUrl: item.imageUrl }} /></span>
            <span className={styles.dreamText}>
              <time dateTime={item.recordedAt}>{formatShortDate(item.recordedAt)}</time>
              {item.path.length > 0 && <strong>{item.path.join(" → ")}</strong>}
              <span>&ldquo;{item.title}&rdquo;</span>
            </span>
            <Icon name="arrow" size={16} />
          </Link>
          {world.routes[item.dreamId] && <button type="button" className={styles.routeButton} aria-pressed={routeId === item.dreamId}
            onClick={() => onRoute(routeId === item.dreamId ? null : item.dreamId)}>
            <Icon name="route" size={13} />{routeId === item.dreamId ? "경로 끄기" : "지도에서 경로 보기"}
          </button>}
        </li>)}</ul>
        : <p className={styles.panelEmptyText}>이 이름이 나오는 꿈을 기록하면 여기에 모여요.</p>}
      {pending > 0 && <p className={styles.panelNote}>이 중 {pending}개는 이름이 같아서 찾은 꿈이에요. 그 꿈의 장면을 다시 만들면 등록한 외형이 이미지에 반영돼요.</p>}
    </section>
  </>;
}

export function EntityForm({ mode, initial, entities, editingId, busy, error, onSubmit, onCancel }: {
  mode: "create" | "update";
  initial: EntityDraft;
  entities: WorldEntity[];
  editingId?: string;
  busy: boolean;
  error: string;
  onSubmit: (draft: EntityDraft) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState(initial);
  const [touched, setTouched] = useState(false);
  const set = (key: keyof EntityDraft, value: string) => setDraft((current) => ({ ...current, [key]: value }));
  const duplicate = findDuplicate(entities, draft, editingId);
  const nameProblem = !draft.name.trim() ? "이름을 적어 주세요."
    : draft.name.trim().length > LIMITS.name ? `이름은 ${LIMITS.name}자까지 쓸 수 있어요.`
    : duplicate ? `같은 이름의 ${kindSubject[draft.kind]} 이미 있어요.` : "";
  const tooLong = (["ageRange", "hair", "outfit"] as const).some((key) => draft[key].trim().length > LIMITS[key]);

  function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (nameProblem || tooLong || busy) return;
    onSubmit(draft);
  }

  const field = (key: "ageRange" | "hair" | "outfit", label: string, placeholder: string) =>
    <label className={styles.field}>{label}
      <input value={draft[key]} maxLength={LIMITS[key]} placeholder={placeholder} onChange={(event) => set(key, event.target.value)} />
    </label>;

  return <form className={styles.form} onSubmit={submit} noValidate>
    <div className={styles.formHead}>
      <h2>{mode === "create" ? "세계관에 추가하기" : `${initial.name} 수정`}</h2>
      <button type="button" className={styles.iconButton} onClick={onCancel} aria-label="닫기"><Icon name="close" size={16} /></button>
    </div>
    <p className={styles.helper}>{mode === "create"
      ? "여러 꿈에 반복해서 나오는 인물이나 장소를 등록하면, 같은 이름이 나온 꿈끼리 이어져요."
      : "바꾼 외형은 이후에 만드는 장면 이미지부터 반영돼요."}</p>

    {mode === "create" && <fieldset className={styles.kindPicker}>
      <legend>종류</legend>
      {(["person", "place"] as const).map((kind) => <label key={kind} className={draft.kind === kind ? styles.kindOn : ""}>
        <input type="radio" name="kind" value={kind} checked={draft.kind === kind} onChange={() => set("kind", kind)} />
        <Icon name={kind} size={16} />{kindLabels[kind]}
      </label>)}
    </fieldset>}

    <label className={styles.field}>이름
      <input value={draft.name} maxLength={LIMITS.name} placeholder={draft.kind === "person" ? "예: 할머니, 민수" : "예: 학교, 바다"}
        aria-invalid={touched && Boolean(nameProblem)} onChange={(event) => set("name", event.target.value)} onBlur={() => setTouched(true)} />
      <span className={styles.fieldHint}>꿈에서 부르는 이름 그대로 적으면 지난 꿈에서도 찾아 연결해요.</span>
      {mode === "update" && draft.name.trim() && draft.name.trim() !== initial.name.trim() &&
        <span className={styles.fieldWarn}>이름을 바꾸면 &lsquo;{initial.name}&rsquo;(으)로 나온 꿈 중 아직 연결 전인 꿈은 이 항목에서 빠져요.</span>}
      {touched && nameProblem && !(duplicate && error) && <span className={styles.fieldError} role="alert">{nameProblem}</span>}
    </label>

    {draft.kind === "person" && <>
      {field("ageRange", "나이대", "예: early 20s, elderly")}
      {field("hair", "머리", "예: short black hair")}
      {field("outfit", "옷차림", "예: navy jacket, white sneakers")}
    </>}
    <label className={styles.field}>{draft.kind === "person" ? "그 밖의 특징" : "장소의 모습"}
      <textarea value={draft.features} rows={3} placeholder={draft.kind === "person" ? "예: round glasses, always smiling" : "예: red brick building with a clock tower"}
        onChange={(event) => set("features", event.target.value)} />
    </label>
    <p className={styles.panelNote}>외형은 이미지 생성 문장에 그대로 들어가서, 영어로 적으면 더 정확하게 그려져요.</p>

    {error && <p className={styles.formError} role="alert">{error}</p>}
    <div className={styles.formActions}>
      <button type="button" className={styles.secondaryButton} onClick={onCancel}>취소</button>
      <button type="submit" className={styles.primaryButton} disabled={busy}>{busy ? "저장 중" : mode === "create" ? "등록하기" : "저장하기"}</button>
    </div>
  </form>;
}
