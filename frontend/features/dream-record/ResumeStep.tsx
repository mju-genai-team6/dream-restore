"use client";

import { useRouter } from "next/navigation";
import StepLayout, { ErrorBox, Loading } from "./StepLayout";
import { useStep } from "./useRequest";
import styles from "./dream-record.module.css";

// /record/[dreamId] 로 들어오면 꿈 기록 상태를 보고 하던 단계로 보냅니다.
export default function ResumeStep({ dreamId }: { dreamId: string }) {
  const router = useRouter();
  const dream = useStep(dreamId, [], async () => null);

  return (
    <StepLayout title="이어서 기록하기">
      {dream.loading && <Loading message="어디까지 했는지 확인하는 중" />}
      {dream.error && (
        <ErrorBox message={dream.error}>
          <button type="button" className={styles.linkButton} onClick={dream.retry}>
            다시 시도
          </button>
          <button type="button" className={styles.linkButton} onClick={() => router.push("/record")}>
            새로 기록하기
          </button>
        </ErrorBox>
      )}
    </StepLayout>
  );
}
