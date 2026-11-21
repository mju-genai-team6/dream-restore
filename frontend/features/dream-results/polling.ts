// 한 요청이 끝난 뒤에만 다음 요청을 예약합니다. 화면 이탈과 최대 대기 시간은 진행 중 요청도 취소합니다.
export function pollResult<T>({ load, pending, onData, onError, onTimeout, intervalMs = 4_000, timeoutMs = 180_000 }: {
  load: (signal: AbortSignal) => Promise<T>;
  pending: (data: T) => boolean;
  onData: (data: T) => void;
  onError: (error: unknown) => void;
  onTimeout: () => void;
  intervalMs?: number;
  timeoutMs?: number;
}) {
  const controller = new AbortController();
  let next: ReturnType<typeof setTimeout> | undefined;
  const deadline = setTimeout(() => { controller.abort(); clearTimeout(next); onTimeout(); }, timeoutMs);

  async function read() {
    try {
      const data = await load(controller.signal);
      if (controller.signal.aborted) return;
      onData(data);
      if (pending(data)) next = setTimeout(read, intervalMs);
      else clearTimeout(deadline);
    } catch (error) {
      if (controller.signal.aborted) return;
      clearTimeout(deadline);
      onError(error);
    }
  }
  void read();
  return () => { controller.abort(); clearTimeout(next); clearTimeout(deadline); };
}
