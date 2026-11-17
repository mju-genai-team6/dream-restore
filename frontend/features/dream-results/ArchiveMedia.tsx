"use client";

import { useState } from "react";
import Icon from "./Icon";
import styles from "./dream-results.module.css";

export default function ArchiveMedia({ url, label }: { url?: string | null; label: string }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  if (!url || url === failedUrl) {
    return <div className={styles.mediaPlaceholder}><Icon name="storyboard" size={24} /><span>이미지 없음</span></div>;
  }
  // The media address comes from the backend storage API and can use a different origin.
  // eslint-disable-next-line @next/next/no-img-element
  return <img className={styles.archiveMedia} src={url} alt={label} onError={() => setFailedUrl(url)} />;
}
