"use client";

import { useState } from "react";
import Icon from "./Icon";
import styles from "./dream-results.module.css";
import type { JobStatus } from "./types";

export default function ArchiveMedia({ url, label, status }: { url?: string | null; label: string; status?: JobStatus }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  if (status === "queued" || status === "running" || status === "failed") {
    return <div className={styles.mediaPlaceholder}><Icon name="storyboard" size={24} /><span>{status === "failed" ? "이미지를 만들지 못함" : "이미지 생성 중"}</span></div>;
  }
  if (!url || url === failedUrl) {
    return <div className={styles.mediaPlaceholder}><Icon name="storyboard" size={24} /><span>{status === "succeeded" ? "이미지를 불러오지 못함" : "이미지 없음"}</span></div>;
  }
  // The media address comes from the backend storage API and can use a different origin.
  // eslint-disable-next-line @next/next/no-img-element
  return <img className={styles.archiveMedia} src={url} alt={label} onError={() => setFailedUrl(url)} />;
}
