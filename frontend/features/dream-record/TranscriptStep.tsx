"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import StepLayout, { ErrorBox, Loading } from "./StepLayout";
import { confirmTranscript } from "./api";
import { errorMessage, useStep } from "./useRequest";
import styles from "./dream-record.module.css";

const TEXT_MAX = 5000;

export default function TranscriptStep({ dreamId }: { dreamId: string }) {
  const dream = useStep(dreamId, ["transcript"], async (record) => record);

  return (
    <StepLayout step={2} title="이렇게 들었어요" description="잘못 옮겨진 부분이 있으면 고쳐 주세요. 빠진 내용을 더 적어도 좋아요.">
      {dream.loading && <Loading message="꿈 기록을 불러오는 중" />}
      {dream.error && (
        <ErrorBox message={dream.error}>
          <button type="button" className={styles.linkButton} onClick={dream.retry}>
            다시 시도
          </button>
        </ErrorBox>
      )}
      {dream.data && <TranscriptForm dreamId={dreamId} initialText={dream.data.rawText ?? ""} />}
    </StepLayout>
  );
}

function TranscriptForm({ dreamId, initialText }: { dreamId: string; initialText: string }) {
  const router = useRouter();
  const [text, setText] = useState(initialText);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!text.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await confirmTranscript(dreamId, text);
      router.push(`/record/${dreamId}/interview`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <section className={styles.card}>
      <label className={styles.label} htmlFor="transcript">
        꿈 내용
      </label>
      <textarea
        id="transcript"
        className={styles.textarea}
        rows={10}
        maxLength={TEXT_MAX}
        value={text}
        onChange={(event) => setText(event.target.value)}
        disabled={busy}
      />
      <span className={styles.characterCount}>
        {text.length} / {TEXT_MAX}
      </span>
      {error && <ErrorBox message={error} />}
      <div className={styles.actions}>
        {/* 같은 꿈 기록에 새 녹음을 올리도록 id 를 넘깁니다. */}
        <button type="button" className={styles.secondaryButton} onClick={() => router.push(`/record?dreamId=${dreamId}`)} disabled={busy}>
          다시 녹음
        </button>
        <button type="button" className={styles.primaryButton} onClick={submit} disabled={!text.trim() || busy}>
          {busy ? "저장하는 중" : "다음"}
        </button>
      </div>
    </section>
  );
}
