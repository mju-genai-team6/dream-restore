"use client";

import { useEffect, useEffectEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, currentStep, getDream, stepPath, type Step } from "./api";
import type { DreamRecord } from "./types";

type Result<T> = { key: string; data?: T; error?: string };

export function errorMessage(err: unknown) {
  return err instanceof ApiError ? err.message : "요청에 실패했어요. 잠시 후 다시 시도해 주세요.";
}

// 화면이 열릴 때 데이터를 불러오고 로딩, 실패, 다시 시도를 한곳에서 처리합니다. key 가 바뀌면 다시 불러옵니다.
export function useRequest<T>(key: string, load: () => Promise<T>) {
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<Result<T> | null>(null);
  const requestKey = `${key}#${attempt}`;
  const runLoad = useEffectEvent(load);

  useEffect(() => {
    let cancelled = false;
    runLoad().then(
      (data) => !cancelled && setResult({ key: requestKey, data }),
      (err) => !cancelled && setResult({ key: requestKey, error: errorMessage(err) }),
    );
    return () => {
      cancelled = true;
    };
  }, [requestKey]);

  const done = result?.key === requestKey;
  return {
    loading: !done,
    data: done ? result.data : undefined,
    error: done ? result.error : undefined,
    retry: () => setAttempt((n) => n + 1),
    setData: (data: T) => setResult({ key: requestKey, data }),
  };
}

// 단계 화면용입니다. 꿈 기록 상태가 steps 에 해당할 때만 load 를 실행하고,
// 아니면 지금 해야 할 단계의 화면으로 보냅니다. (새로고침, 뒤로 가기, 주소 직접 입력)
export function useStep<T>(dreamId: string, steps: Step[], load: (dream: DreamRecord) => Promise<T>) {
  const router = useRouter();
  const request = useRequest<{ data: T } | { moveTo: string }>(dreamId, async () => {
    const dream = await getDream(dreamId);
    return steps.includes(currentStep(dream)) ? { data: await load(dream) } : { moveTo: stepPath(dream) };
  });
  const moveTo = request.data && "moveTo" in request.data ? request.data.moveTo : null;

  useEffect(() => {
    if (moveTo) router.replace(moveTo);
  }, [moveTo, router]);

  return {
    loading: request.loading || moveTo !== null,
    data: request.data && "data" in request.data ? request.data.data : undefined,
    error: request.error,
    retry: request.retry,
    setData: (data: T) => request.setData({ data }),
  };
}
