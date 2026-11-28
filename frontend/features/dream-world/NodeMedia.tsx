"use client";

import { useState } from "react";
import type { WorldNode } from "./types";
import styles from "./dream-world.module.css";

// 그 항목이 나온 장면 이미지 중 가장 최근 것을 보여 주고, 없으면 첫 글자로 대신합니다.
export default function NodeMedia({ node }: { node: Pick<WorldNode, "name" | "imageUrl"> }) {
  const [failed, setFailed] = useState<string | null>(null);
  if (!node.imageUrl || node.imageUrl === failed) {
    return <span className={styles.initial} aria-hidden="true">{node.name.trim().slice(0, 1)}</span>;
  }
  // 이미지 주소는 백엔드 storage에서 오므로 다른 origin일 수 있습니다.
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={node.imageUrl} alt="" onError={() => setFailed(node.imageUrl)} />;
}
