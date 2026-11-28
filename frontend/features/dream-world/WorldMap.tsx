"use client";

import { useEffect, useRef, useState } from "react";
import { placeNodes, MAX_ON_MAP } from "./layout";
import NodeMedia from "./NodeMedia";
import Icon from "./Icon";
import { formatShortDate, type DreamRoute, type EntityKind, type World } from "./types";
import styles from "./dream-world.module.css";

const ZOOMS = [0.8, 1, 1.25, 1.5];

export default function WorldMap({ world, filter, selectedId, route, onSelect, onClearRoute }: {
  world: World;
  filter: EntityKind | "all";
  selectedId: string | null;
  route: DreamRoute | null;
  onSelect: (id: string) => void;
  onClearRoute: () => void;
}) {
  const [zoom, setZoom] = useState(1);
  const [box, setBox] = useState({ width: 0, height: 0 });
  const canvas = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);

  // 선은 px 좌표로 그려야 화살표 모양이 찌그러지지 않으므로 지도 크기를 따라갑니다.
  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setBox({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // 좁은 화면에서는 지도가 화면보다 넓으므로 처음에 가운데를 보여 줍니다.
  useEffect(() => {
    const element = scroller.current;
    if (element) element.scrollLeft = (element.scrollWidth - element.clientWidth) / 2;
  }, [zoom, box.width]);

  const visible = world.nodes.filter((node) => filter === "all" || node.kind === filter);
  const placed = placeNodes(visible);
  const where = new Map(placed.map((item) => [item.id, item]));
  const px = (id: string) => {
    const item = where.get(id)!;
    return { x: (item.x / 100) * box.width, y: (item.y / 100) * box.height, r: item.size / 2 };
  };
  const edges = world.edges.filter((edge) => where.has(edge.from) && where.has(edge.to));
  const maxEdge = Math.max(1, ...edges.map((edge) => edge.dreams));
  const stops = route ? route.entityIds.filter((id) => where.has(id)) : [];
  const stepOf = new Map<string, number[]>();
  stops.forEach((id, index) => stepOf.set(id, [...(stepOf.get(id) ?? []), index + 1]));
  const focus = (id: string) => route ? stepOf.has(id) : selectedId === id;
  const step = (direction: 1 | -1) => {
    const index = ZOOMS.indexOf(zoom) + direction;
    if (index >= 0 && index < ZOOMS.length) setZoom(ZOOMS[index]);
  };

  return <div className={styles.mapFrame}>
    <div className={styles.mapScroll} ref={scroller}>
      <div className={styles.mapCanvas} ref={canvas} style={{ width: `${zoom * 100}%` }}>
        <span className={`${styles.cloud} ${styles.cloudA}`} aria-hidden="true" />
        <span className={`${styles.cloud} ${styles.cloudB}`} aria-hidden="true" />
        <span className={`${styles.cloud} ${styles.cloudC}`} aria-hidden="true" />
        {box.width > 0 && <svg className={styles.mapLines} viewBox={`0 0 ${box.width} ${box.height}`} aria-hidden="true">
          {edges.map((edge) => {
            const a = px(edge.from);
            const b = px(edge.to);
            const active = !route && (selectedId === edge.from || selectedId === edge.to);
            // 가운데를 지나지 않도록 살짝 휘게 그립니다.
            const mx = (a.x + b.x) / 2 + (b.y - a.y) * 0.12;
            const my = (a.y + b.y) / 2 - (b.x - a.x) * 0.12;
            return <path key={`${edge.from}-${edge.to}`} d={`M${a.x} ${a.y} Q${mx} ${my} ${b.x} ${b.y}`}
              className={active ? styles.lineActive : selectedId || route ? styles.lineDim : styles.line}
              style={{ strokeWidth: 1.2 + 2.6 * (edge.dreams / maxEdge) }} />;
          })}
        </svg>}
        {/* 경로 화살표는 이름표에 가리지 않도록 원 위 층에 그립니다. */}
        {box.width > 0 && stops.length > 1 && <svg className={styles.routeLayer} viewBox={`0 0 ${box.width} ${box.height}`} aria-hidden="true">
          <defs>
            <marker id="world-route-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0 0 L10 5 L0 10 z" className={styles.routeHead} />
            </marker>
          </defs>
          {stops.slice(1).map((id, index) => {
            const from = stops[index];
            if (from === id) return null;
            const a = px(from);
            const b = px(id);
            const length = Math.hypot(b.x - a.x, b.y - a.y) || 1;
            const ux = (b.x - a.x) / length;
            const uy = (b.y - a.y) / length;
            // 원 가장자리에서 시작하고 끝나도록 반지름만큼 줄입니다.
            const sx = a.x + ux * (a.r + 4);
            const sy = a.y + uy * (a.r + 4);
            const ex = b.x - ux * (b.r + 8);
            const ey = b.y - uy * (b.r + 8);
            const mx = (sx + ex) / 2 - uy * 28;
            const my = (sy + ey) / 2 + ux * 28;
            return <path key={`route-${index}`} d={`M${sx} ${sy} Q${mx} ${my} ${ex} ${ey}`} className={styles.routeLine} markerEnd="url(#world-route-arrow)" />;
          })}
        </svg>}
        {placed.map((item) => {
          const node = visible.find((entry) => entry.id === item.id)!;
          const steps = stepOf.get(node.id);
          return <button type="button" key={node.id}
            className={`${styles.node} ${focus(node.id) ? styles.nodeSelected : ""} ${route && !steps ? styles.nodeDim : ""} ${node.appearances.length === 0 ? styles.nodeQuiet : ""}`}
            style={{ left: `${item.x}%`, top: `${item.y}%`, width: item.size, height: item.size }}
            aria-pressed={selectedId === node.id} aria-label={`${node.name}, ${node.kind === "person" ? "인물" : "장소"}, ${node.appearances.length}회`}
            onClick={() => onSelect(node.id)}>
            <span className={`${styles.nodeImage} ${styles[node.kind]}`}><NodeMedia node={node} /></span>
            {steps && <span className={styles.stepBadge}>{steps.join(", ")}</span>}
            <span className={styles.nodeLabel}><strong>{node.name}</strong><small>{node.appearances.length}회</small></span>
          </button>;
        })}
        {!visible.length && <div className={styles.mapEmpty}><Icon name="globe" size={34} /><p>아직 이 종류로 등록한 항목이 없어요.</p></div>}
      </div>
    </div>
    {route ? <div className={styles.routeBanner} role="status">
      <span><Icon name="route" size={15} />{formatShortDate(route.recordedAt)} 꿈의 경로</span>
      <strong>{route.entityIds.map((id) => world.nodes.find((node) => node.id === id)?.name).filter(Boolean).join(" → ")}</strong>
      <button type="button" onClick={onClearRoute} aria-label="경로 보기 닫기"><Icon name="close" size={14} /></button>
    </div> : visible.length > MAX_ON_MAP && <p className={styles.mapNote}>자주 나온 {MAX_ON_MAP}개만 지도에 표시했어요.</p>}
    <div className={styles.legend}>
      <span><i className={styles.dotPerson} />인물</span>
      <span><i className={styles.dotPlace} />장소</span>
      {route ? <span><i className={styles.dotRoute} />꿈 속 이동 순서</span> : <span><i className={styles.dotLine} />같은 꿈에 함께 나옴</span>}
    </div>
    <div className={styles.zoomControls}>
      <button type="button" onClick={() => step(1)} disabled={zoom === ZOOMS[ZOOMS.length - 1]} aria-label="지도 크게"><Icon name="plus" size={17} /></button>
      <button type="button" onClick={() => step(-1)} disabled={zoom === ZOOMS[0]} aria-label="지도 작게"><Icon name="minus" size={17} /></button>
      <button type="button" onClick={() => setZoom(1)} aria-label="원래 크기"><Icon name="target" size={17} /></button>
    </div>
  </div>;
}
