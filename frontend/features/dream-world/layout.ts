import type { WorldNode } from "./types";

export type Placed = { id: string; x: number; y: number; size: number };

// 지도에 한 번에 그리는 최대 항목 수. 나머지는 아래 목록과 오른쪽 상세에서 볼 수 있습니다.
export const MAX_ON_MAP = 15;
// 이름표가 원 아래에 붙으므로 가운데를 조금 위로 올립니다.
const CENTER_Y = 46;

/**
 * 가장 많이 나온 항목을 가운데에 두고, 나머지를 등장 횟수 순서로 안쪽 고리부터 채웁니다.
 * x, y는 지도 너비와 높이에 대한 백분율이고 size는 px입니다. 같은 입력이면 항상 같은 자리에 놓입니다.
 */
export function placeNodes(nodes: WorldNode[]): Placed[] {
  const shown = nodes.slice(0, MAX_ON_MAP);
  const max = Math.max(1, ...shown.map((node) => node.appearances.length));
  const size = (node: WorldNode, center = false) =>
    Math.round((center ? 96 : 66) + (center ? 16 : 30) * (node.appearances.length / max));
  if (!shown.length) return [];
  const [first, ...rest] = shown;
  const placed: Placed[] = [{ id: first.id, x: 50, y: CENTER_Y, size: size(first, true) }];
  // 안쪽 고리는 60도 간격, 바깥 고리는 그 사이(30도 어긋난 자리)에 놓습니다.
  // 지도가 가로로 넓어서, 바깥 고리는 안쪽과 가장 덜 겹치는 왼쪽과 오른쪽 끝부터 채웁니다.
  const inner = rest.slice(0, 6);
  const outer = rest.slice(6);
  // 항목이 적을 때는 가로로 넓게 벌려 놓습니다 (2개는 좌우, 3개는 삼각형, 4개는 네 귀퉁이).
  const start = { 1: 0, 2: 0, 3: -150, 4: -135 }[inner.length] ?? -90;
  const innerAngles = inner.map((_, index) => start + (360 / inner.length) * index);
  const gaps = [180, 0, -120, 60, -60, 120];
  const outerAngles = outer.length <= gaps.length
    ? outer.map((_, index) => gaps[index])
    : outer.map((_, index) => -60 + (360 / outer.length) * index);
  const put = (items: WorldNode[], angles: number[], rx: number, ry: number) => items.forEach((node, index) => {
    const angle = (angles[index] * Math.PI) / 180;
    placed.push({
      id: node.id,
      x: Math.round((50 + rx * Math.cos(angle)) * 10) / 10,
      y: Math.round((CENTER_Y + ry * Math.sin(angle)) * 10) / 10,
      size: size(node),
    });
  });
  put(inner, innerAngles, 25, 27);
  put(outer, outerAngles, 41, 36);
  return placed;
}
