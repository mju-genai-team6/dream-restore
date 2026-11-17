"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import StepLayout, { ErrorBox, Loading } from "./StepLayout";
import Icon from "./Icon";
import { ApiError, currentStep, getDream, getElements, requestScenes, resultsPath, saveConfidence, stepPath } from "./api";
import { confidenceOptions, elementTypeLabels, type Confidence, type DreamElement } from "./types";
import { errorMessage, useStep } from "./useRequest";
import styles from "./dream-record.module.css";

export default function ConfidenceStep({ dreamId }: { dreamId: string }) {
  const router = useRouter();
  const elements = useStep(dreamId, ["confidence"], () => getElements(dreamId));

  return (
    <StepLayout step={4} title="얼마나 또렷하게 기억나나요?" description="꿈에 나온 것마다 기억나는 정도를 골라 주세요.">
      <div className={styles.notice}>
        <Icon name="info" size={15} />
        <div>
          <p>확신도는 기억이 분명한 정도이며, AI의 정확도를 뜻하지 않아요. 흐릿한 기억이 많은 장면은 영상에서도 흐리게 표현돼요.</p>
          <ul className={styles.legend}>
            {confidenceOptions.map((option) => (
              <li key={option.value}>
                <span className={`${styles.legendBadge} ${styles[option.value]}`}>{option.label}</span>
                {option.hint}
              </li>
            ))}
          </ul>
        </div>
      </div>
      {elements.loading && <Loading message="꿈에 나온 것들을 정리하고 있어요. 처음에는 30초 정도 걸릴 수 있어요." />}
      {elements.error && (
        <ErrorBox message={elements.error}>
          <button type="button" className={styles.linkButton} onClick={elements.retry}>
            다시 시도
          </button>
        </ErrorBox>
      )}
      {elements.data &&
        (elements.data.length > 0 ? (
          <ConfidenceForm dreamId={dreamId} elements={elements.data} />
        ) : (
          <div className={`${styles.card} ${styles.status}`}>
            <p>꿈에서 정리된 내용이 없어요. 꿈 이야기를 조금 더 자세히 남겨 주세요.</p>
            <button type="button" className={styles.secondaryButton} onClick={() => router.push("/record")}>
              새로 기록하기
            </button>
          </div>
        ))}
    </StepLayout>
  );
}

function ConfidenceForm({ dreamId, elements }: { dreamId: string; elements: DreamElement[] }) {
  const router = useRouter();
  const [values, setValues] = useState<Record<number, Confidence>>(() =>
    Object.fromEntries(elements.filter((el) => el.confidence).map((el) => [el.id, el.confidence as Confidence])),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // setBusy 가 화면에 반영되기 전에 한 번 더 눌려도 요청이 나가지 않게 ref 로도 막습니다.
  const sendingRef = useRef(false);

  const doneCount = elements.filter((el) => values[el.id]).length;
  const allChosen = doneCount === elements.length;

  function choose(elementId: number, value: Confidence) {
    setValues((prev) => ({ ...prev, [elementId]: value }));
    // 고를 때마다 저장해 두면 새로고침해도 남습니다. 실패해도 '장면 만들기'에서 전체를 다시 저장합니다.
    saveConfidence(dreamId, { [elementId]: value }).catch(() => {});
  }

  async function submit() {
    if (!allChosen || sendingRef.current) return;
    sendingRef.current = true;
    setBusy(true);
    setError(null);
    try {
      await saveConfidence(dreamId, values);
      const jobId = await requestScenes(dreamId);
      router.push(resultsPath(dreamId, jobId));
    } catch (err) {
      // 다른 탭에서 이미 요청했다면 409 가 옵니다. 꿈 상태를 다시 보고 맞는 화면으로 보냅니다.
      if (err instanceof ApiError && err.code === "INVALID_STATE") {
        const dream = await getDream(dreamId).catch(() => null);
        if (dream && currentStep(dream) !== "confidence") {
          router.replace(stepPath(dream));
          return;
        }
      }
      setError(errorMessage(err));
      setBusy(false);
      sendingRef.current = false;
    }
  }

  return (
    <>
      <ul className={styles.elementList}>
        {elements.map((el) => (
          <li key={el.id} className={styles.elementCard}>
            <div className={styles.elementHead}>
              <span className={styles.typeBadge}>{elementTypeLabels[el.type]}</span>
              <h2>{el.name}</h2>
            </div>
            {el.description && <p className={styles.elementDescription}>{el.description}</p>}
            <div className={styles.choices} role="group" aria-label={`${el.name} 확신도`}>
              {confidenceOptions.map((option) => {
                const selected = values[el.id] === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    aria-pressed={selected}
                    className={`${styles.choice} ${selected ? styles[option.value] : ""}`}
                    onClick={() => choose(el.id, option.value)}
                    disabled={busy}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
          </li>
        ))}
      </ul>
      {error && <ErrorBox message={error} />}
      <div className={styles.stickyBar}>
        <span className={styles.helper}>
          {doneCount} / {elements.length} 선택
        </span>
        <button type="button" className={styles.primaryButton} onClick={submit} disabled={!allChosen || busy}>
          {busy ? "요청하는 중" : "장면 만들기"}
        </button>
      </div>
    </>
  );
}
