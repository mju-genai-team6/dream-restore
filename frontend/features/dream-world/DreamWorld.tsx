"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import WorldMap from "./WorldMap";
import NodeMedia from "./NodeMedia";
import { EntityDetail, EntityForm } from "./EntityPanel";
import Icon from "./Icon";
import { exampleDreams, exampleEntities } from "./example-world";
import { buildWorld, createEntity, dreamsInPeriod, WorldApiError, draftOf, emptyDraft, listEntities, loadDreamSources, updateEntity } from "./world-api";
import { kindLabels, kindSubject, periodLabels, type Period, type DreamSource, type EntityDraft, type EntityKind, type WorldEntity, type WorldNode } from "./types";
import styles from "./dream-world.module.css";

type Panel = { mode: "view" } | { mode: "create"; initial: EntityDraft } | { mode: "edit"; id: string };
const message = (error: unknown) => error instanceof Error ? error.message : "다시 시도해 주세요.";
const filters: { id: EntityKind | "all"; label: string }[] = [
  { id: "all", label: "전체" }, { id: "person", label: "인물" }, { id: "place", label: "장소" },
];

function draftToEntity(id: string, draft: EntityDraft, createdAt: string): WorldEntity {
  const text = (value: string) => value.trim() || null;
  return {
    id, kind: draft.kind, name: draft.name.trim(), createdAt,
    ageRange: text(draft.ageRange), hair: text(draft.hair), outfit: text(draft.outfit), features: text(draft.features),
  };
}

function Frequent({ title, kind, nodes, onSelect, onMore }: {
  title: string; kind: EntityKind; nodes: WorldNode[]; onSelect: (id: string) => void; onMore: () => void;
}) {
  const top = nodes.filter((node) => node.kind === kind && node.appearances.length > 0).slice(0, 4);
  return <section className={styles.card}>
    <div className={styles.cardHead}><h2>{title}</h2><button type="button" className={styles.textButton} onClick={onMore}>{kindLabels[kind]}만 보기<Icon name="arrow" size={13} /></button></div>
    {top.length ? <ul className={styles.frequent}>{top.map((node) => <li key={node.id}>
      <button type="button" onClick={() => onSelect(node.id)}>
        <span className={`${styles.frequentImage} ${styles[node.kind]}`}><NodeMedia node={node} /></span>
        <strong>{node.name}</strong><small>{node.appearances.length}회</small>
      </button>
    </li>)}</ul> : <p className={styles.panelEmptyText}>아직 꿈에 나온 {kindSubject[kind]} 없어요.</p>}
  </section>;
}

export default function DreamWorld() {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim().replace(/\/+$/, "") || "";
  const fromApi = Boolean(baseUrl);
  const [entities, setEntities] = useState<WorldEntity[] | null>(fromApi ? null : exampleEntities);
  const [dreams, setDreams] = useState<DreamSource[] | null>(fromApi ? null : exampleDreams);
  const [loadError, setLoadError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [filter, setFilter] = useState<EntityKind | "all">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [panel, setPanel] = useState<Panel>({ mode: "view" });
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");
  const [notice, setNotice] = useState("");
  const [period, setPeriod] = useState<Period>("all");
  const [routeId, setRouteId] = useState<string | null>(null);
  const saving = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!fromApi) return;
    const controller = new AbortController();
    Promise.all([listEntities(baseUrl, controller.signal), loadDreamSources(baseUrl, controller.signal)]).then(
      ([nextEntities, nextDreams]) => {
        if (controller.signal.aborted) return;
        setEntities(nextEntities);
        setDreams(nextDreams);
      },
      (error) => { if (!controller.signal.aborted) setLoadError(message(error)); },
    );
    return () => controller.abort();
  }, [fromApi, baseUrl, attempt]);
  useEffect(() => () => saving.current?.abort(), []);

  // /world?entity=3 처럼 들어오면 그 항목을 골라 둡니다. 결과 화면 등에서 바로 연결할 때 씁니다.
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("entity");
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 주소는 첫 렌더 뒤에만 읽을 수 있습니다.
    if (id) setSelectedId(id);
  }, []);
  useEffect(() => {
    if (!selectedId) return;
    const url = new URL(window.location.href);
    url.searchParams.set("entity", selectedId);
    window.history.replaceState(window.history.state, "", url);
  }, [selectedId]);

  const world = useMemo(() => entities && dreams ? buildWorld(entities, dreamsInPeriod(dreams, period)) : null, [entities, dreams, period]);
  const route = routeId ? world?.routes[routeId] ?? null : null;
  const selected = world?.nodes.find((node) => node.id === (selectedId ?? world.nodes[0]?.id)) ?? null;

  function select(id: string) { setSelectedId(id); setPanel({ mode: "view" }); setFormError(""); setNotice(""); }
  function showRoute(dreamId: string | null) { setRouteId(dreamId); if (dreamId) setFilter("all"); }
  function openCreate(kind: EntityKind = filter === "place" ? "place" : "person", name = "") {
    setPanel({ mode: "create", initial: emptyDraft(kind, name) }); setFormError(""); setNotice("");
  }

  async function save(draft: EntityDraft) {
    if (saving.current || !entities) return;
    const controller = new AbortController();
    saving.current = controller;
    setBusy(true);
    setFormError("");
    try {
      let saved: WorldEntity;
      if (panel.mode === "edit") {
        const previous = entities.find((item) => item.id === panel.id)!;
        saved = fromApi ? await updateEntity(baseUrl, panel.id, draft, controller.signal) : draftToEntity(panel.id, draft, previous.createdAt);
        if (controller.signal.aborted) return;
        setEntities(entities.map((item) => item.id === saved.id ? saved : item));
        setNotice("외형을 저장했어요.");
      } else {
        const nextId = String(Math.max(0, ...entities.map((item) => Number(item.id))) + 1);
        saved = fromApi ? await createEntity(baseUrl, draft, controller.signal) : draftToEntity(nextId, draft, new Date().toISOString());
        if (controller.signal.aborted) return;
        setEntities([...entities, saved]);
        setNotice(`'${saved.name}' 항목을 세계관에 추가했어요.`);
      }
      setSelectedId(saved.id);
      setPanel({ mode: "view" });
    } catch (error) {
      if (controller.signal.aborted) return;
      setFormError(message(error));
      // 다른 사람이 같은 이름을 먼저 등록했을 수 있으니 목록을 다시 받아 둡니다.
      if (fromApi && error instanceof WorldApiError && error.status === 400) {
        listEntities(baseUrl, controller.signal).then((fresh) => setEntities(fresh), () => undefined);
      }
    } finally {
      if (saving.current === controller) saving.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  const editing = panel.mode === "edit" ? entities?.find((item) => item.id === panel.id) : undefined;

  return <div className={styles.app}>
    <aside className={styles.sidebar}>
      <div className={styles.brand}><span className={styles.brandMark}>✦</span><div><strong>꿈 기록</strong><span>기억을 한 장면씩</span></div></div>
      <nav className={styles.navigation} aria-label="메뉴">
        <Link href="/record" className={styles.navItem}><Icon name="mic" size={21} />꿈 기록하기</Link>
        <Link href="/" className={styles.navItem}><Icon name="archive" size={21} />결과와 보관</Link>
        <Link href="/world" className={`${styles.navItem} ${styles.activeNav}`} aria-current="page"><Icon name="globe" size={21} />꿈 세계관</Link>
      </nav>
      <div className={styles.sidebarDecoration} aria-hidden="true"><span>✧</span><Icon name="moon" size={62} /><span>✦</span></div>
      <div className={styles.demoInfo}>
        <span className={styles.demoBadge}>{fromApi ? "서버 조회 모드" : "예시 모드"}</span>
        <p>{fromApi ? <>장면이 만들어진 꿈으로<br />세계관을 이어 보여 줘요.</> : <>등록한 항목은<br />새로고침하면 사라져요.</>}</p>
      </div>
    </aside>

    <main className={styles.main}>
      <header className={styles.pageHeader}>
        <div className={styles.headingGroup}>
          <span className={styles.headingIcon}><Icon name="globe" size={26} /></span>
          <div><h1>꿈 세계관</h1><p>여러 꿈에 반복해 나온 인물과 장소가 어떻게 이어지는지 확인해 보세요.</p></div>
        </div>
        {world && <div className={styles.headerSide}>
          <label className={styles.periodPicker}><Icon name="calendar" size={15} />
            <span className={styles.srOnly}>기간</span>
            <select value={period} onChange={(event) => { setPeriod(event.target.value as Period); setRouteId(null); }}>
              {(Object.keys(periodLabels) as Period[]).map((key) => <option key={key} value={key}>{periodLabels[key]}</option>)}
            </select>
          </label>
          <span className={styles.summaryPill}>꿈 {world.dreamCount}개, 항목 {world.nodes.length}개</span>
          <button type="button" className={styles.primaryButton} onClick={() => openCreate()}><Icon name="plus" size={16} />항목 추가</button>
        </div>}
      </header>

      {loadError ? <div className={`${styles.card} ${styles.stateBox}`} role="alert">
        <h2>세계관을 불러오지 못했어요</h2><p>{loadError}</p>
        <button type="button" className={styles.secondaryButton} onClick={() => { setLoadError(""); setEntities(null); setDreams(null); setAttempt((n) => n + 1); }}>다시 불러오기</button>
      </div> : !world ? <p className={`${styles.card} ${styles.stateBox}`} role="status">꿈과 세계관 항목을 불러오는 중이에요.</p>
      : <div className={styles.workspace}>
        <div className={styles.centerColumn}>
          <section className={styles.card} aria-label="세계관 지도">
            <div className={styles.cardHead}>
              <div><h2>세계관 지도</h2><p>원이 클수록 자주 나왔고, 선이 굵을수록 같은 꿈에 함께 자주 나왔어요.</p></div>
              <div className={styles.tabs} role="group" aria-label="종류 고르기">{filters.map((item) =>
                <button type="button" key={item.id} aria-pressed={filter === item.id} className={filter === item.id ? styles.tabOn : ""} onClick={() => { setFilter(item.id); setRouteId(null); }}>{item.label}</button>)}</div>
            </div>
            {world.nodes.length ? <WorldMap world={world} filter={filter} selectedId={selected?.id ?? null} route={route} onSelect={select} onClearRoute={() => setRouteId(null)} />
              : <div className={styles.stateBox}><Icon name="globe" size={34} /><h2>아직 등록한 인물과 장소가 없어요</h2><p>꿈에 자주 나오는 인물이나 장소를 추가하면 여기서 서로 이어져요.</p>
                <button type="button" className={styles.primaryButton} onClick={() => openCreate()}>첫 항목 추가하기</button></div>}
          </section>

          <div className={styles.cardRow}>
            <Frequent title="자주 나온 인물" kind="person" nodes={world.nodes} onSelect={select} onMore={() => setFilter("person")} />
            <Frequent title="자주 나온 장소" kind="place" nodes={world.nodes} onSelect={select} onMore={() => setFilter("place")} />
          </div>

          {world.candidates.length > 0 && <section className={styles.card}>
            <div className={styles.cardHead}><div><h2>세계관에 추가할 수 있는 이름</h2><p>꿈에 나왔지만 아직 등록하지 않은 인물과 장소예요. 눌러서 바로 추가할 수 있어요.</p></div></div>
            <div className={styles.chips}>{world.candidates.slice(0, 12).map((item) =>
              <button type="button" key={`${item.kind}:${item.name}`} className={styles.candidate} onClick={() => openCreate(item.kind, item.name)}>
                <Icon name={item.kind} size={14} />{item.name}<small>꿈 {item.dreamIds.length}개</small><Icon name="plus" size={13} />
              </button>)}</div>
          </section>}
        </div>

        <aside className={`${styles.card} ${styles.detailPanel}`} aria-label="세계관 항목 상세">
          {notice && <p className={styles.notice} role="status">{notice}</p>}
          {panel.mode === "create" ? <EntityForm key={`create-${panel.initial.kind}-${panel.initial.name}`} mode="create" initial={panel.initial} entities={entities!} busy={busy} error={formError} onSubmit={save} onCancel={() => setPanel({ mode: "view" })} />
            : panel.mode === "edit" && editing ? <EntityForm key={`edit-${editing.id}`} mode="update" initial={draftOf(editing)} entities={entities!} editingId={editing.id} busy={busy} error={formError} onSubmit={save} onCancel={() => setPanel({ mode: "view" })} />
            : selected ? <EntityDetail node={selected} world={world} routeId={route?.dreamId ?? null} onRoute={showRoute} onSelect={select} onEdit={() => { setPanel({ mode: "edit", id: selected.id }); setFormError(""); setNotice(""); }} />
            : <div className={styles.stateBox}><Icon name="globe" size={30} /><p>지도에서 인물이나 장소를 골라 주세요.</p></div>}
        </aside>
      </div>}
    </main>
  </div>;
}
