"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import StepLayout, { ErrorBox } from "./StepLayout";
import Icon from "./Icon";
import { ApiError, createDream, uploadAudio } from "./api";
import { errorMessage } from "./useRequest";
import styles from "./dream-record.module.css";

// Whisper 파일 제한(25MB)을 넘지 않도록 5분에서 자동으로 멈춥니다.
const MAX_SECONDS = 5 * 60;
const TEXT_MAX = 5000;

type Mode = "voice" | "text";
type Recording = { blob: Blob; url: string };

// Chrome 은 webm, iOS Safari 는 mp4 로 녹음됩니다. 서버는 둘 다 받습니다.
function pickMimeType() {
  return ["audio/webm", "audio/mp4"].find((type) => MediaRecorder.isTypeSupported(type)) ?? "";
}

function formatTime(seconds: number) {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

// 내용 확인 화면에서 '다시 녹음'으로 돌아오면 주소에 ?dreamId= 가 붙어 있습니다.
function dreamIdFromAddress() {
  const value = Number(new URLSearchParams(window.location.search).get("dreamId"));
  return Number.isInteger(value) && value > 0 ? value : null;
}

export default function RecordStep() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("voice");
  const [isRecording, setIsRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [recording, setRecording] = useState<Recording | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const urlRef = useRef<string | null>(null);
  // STT 가 실패해서 다시 보낼 때 꿈 기록을 또 만들지 않도록 id 를 기억합니다.
  const dreamIdRef = useRef<number | null>(null);

  function stopTimer() {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
  }

  function releaseMic() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }

  function clearRecording() {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = null;
    setRecording(null);
  }

  useEffect(() => {
    return () => {
      stopTimer();
      if (recorderRef.current) recorderRef.current.onstop = null;
      releaseMic();
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    };
  }, []);

  function switchToText(message: string) {
    setNotice(message);
    setMode("text");
  }

  async function startRecording() {
    setError(null);
    setNotice(null);
    // http 주소(localhost 제외)에서는 mediaDevices 자체가 없습니다.
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      switchToText("이 브라우저에서는 녹음을 할 수 없어요. 글로 적어 주세요.");
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      switchToText("마이크를 사용할 수 없어요. 브라우저 설정에서 마이크를 허용하거나 글로 적어 주세요.");
      return;
    }

    streamRef.current = stream;
    const mimeType = pickMimeType();
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks: Blob[] = [];
    const startedAt = Date.now();
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    recorder.onstop = () => {
      releaseMic();
      const blob = new Blob(chunks, { type: recorder.mimeType || mimeType || "audio/webm" });
      if (blob.size === 0 || Date.now() - startedAt < 1000) {
        setSeconds(0);
        setNotice("녹음이 너무 짧아요. 버튼을 누르고 꿈 이야기를 들려주세요.");
        return;
      }
      urlRef.current = URL.createObjectURL(blob);
      setRecording({ blob, url: urlRef.current });
    };
    recorderRef.current = recorder;
    clearRecording();
    recorder.start();
    setSeconds(0);
    setIsRecording(true);
    // 화면이 꺼지거나 탭이 뒤로 가면 타이머가 밀리므로 시작 시각과의 차이로 계산합니다.
    timerRef.current = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startedAt) / 1000);
      setSeconds(Math.min(elapsed, MAX_SECONDS));
      if (elapsed >= MAX_SECONDS) stopRecording();
    }, 500);
  }

  function stopRecording() {
    stopTimer();
    setIsRecording(false);
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
  }

  function retake() {
    clearRecording();
    setSeconds(0);
    setError(null);
  }

  async function submitVoice() {
    if (!recording || busy) return;
    setBusy(true);
    setError(null);
    try {
      let dreamId = dreamIdRef.current ?? dreamIdFromAddress();
      if (dreamId !== null) {
        dreamIdRef.current = dreamId;
        try {
          await uploadAudio(dreamId, recording.blob);
        } catch (err) {
          // 다시 녹음하려던 기록이 없거나 이미 다음 단계로 넘어갔으면 새 기록으로 올립니다.
          const stale = err instanceof ApiError && (err.code === "NOT_FOUND" || err.code === "INVALID_STATE");
          if (!stale) throw err;
          dreamId = null;
        }
      }
      if (dreamId === null) {
        dreamId = await createDream("voice");
        dreamIdRef.current = dreamId;
        await uploadAudio(dreamId, recording.blob);
      }
      router.push(`/record/${dreamId}/transcript`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  async function submitText() {
    if (!text.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const dreamId = await createDream("text", text);
      // 텍스트 입력은 원문이 바로 확정되므로 내용 확인 단계 없이 되묻기로 갑니다.
      router.push(`/record/${dreamId}/interview`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  function switchMode(next: Mode) {
    if (isRecording || busy) return;
    setError(null);
    setNotice(null);
    setMode(next);
  }

  let helper = "버튼을 눌러 녹음을 시작하세요.";
  if (isRecording) helper = "녹음하고 있어요. 다 말했으면 버튼을 한 번 더 눌러 주세요.";
  else if (recording) helper = "들어 보고 괜찮으면 다음으로 넘어가 주세요.";

  return (
    <StepLayout step={1} title="어떤 꿈을 꿨나요?" description="생각나는 대로 말하거나 적어 주세요. 순서가 뒤죽박죽이어도 괜찮아요.">
      <div className={styles.tabs} role="tablist" aria-label="입력 방식">
        <button type="button" role="tab" aria-selected={mode === "voice"} className={mode === "voice" ? styles.tabActive : styles.tab} onClick={() => switchMode("voice")}>
          <Icon name="mic" size={16} />말로 하기
        </button>
        <button type="button" role="tab" aria-selected={mode === "text"} className={mode === "text" ? styles.tabActive : styles.tab} onClick={() => switchMode("text")}>
          <Icon name="text" size={16} />글로 쓰기
        </button>
      </div>

      {notice && (
        <p className={styles.notice} role="status">
          <Icon name="info" size={15} />
          {notice}
        </p>
      )}

      {mode === "voice" ? (
        <section className={styles.card}>
          <div className={styles.recorder}>
            <button
              type="button"
              className={`${styles.micButton} ${isRecording ? styles.micRecording : ""}`}
              onClick={isRecording ? stopRecording : startRecording}
              disabled={busy || (recording !== null && !isRecording)}
              aria-label={isRecording ? "녹음 정지" : "녹음 시작"}
            >
              <Icon name={isRecording ? "stop" : "mic"} size={isRecording ? 30 : 36} />
            </button>
            <p className={styles.timer} aria-live="off">
              {formatTime(seconds)} <span>/ {formatTime(MAX_SECONDS)}</span>
            </p>
            {busy ? (
              <p className={styles.converting} role="status">
                <span className={styles.spinner} aria-hidden="true" />
                말한 내용을 글로 옮기고 있어요. 1분 정도 걸릴 수 있어요.
              </p>
            ) : (
              <p className={styles.helper}>{helper}</p>
            )}
            {recording && !isRecording && <audio className={styles.audio} controls src={recording.url} />}
          </div>
          {error && (
            <ErrorBox message={error}>
              <button type="button" className={styles.linkButton} onClick={() => switchMode("text")}>
                글로 쓰기로 바꾸기
              </button>
            </ErrorBox>
          )}
          {recording && (
            <div className={styles.actions}>
              <button type="button" className={styles.secondaryButton} onClick={retake} disabled={busy}>
                다시 녹음
              </button>
              <button type="button" className={styles.primaryButton} onClick={submitVoice} disabled={busy}>
                {busy ? "옮기는 중" : error ? "다시 시도" : "다음"}
              </button>
            </div>
          )}
        </section>
      ) : (
        <section className={styles.card}>
          <label className={styles.label} htmlFor="dream-text">
            꿈 내용
          </label>
          <textarea
            id="dream-text"
            className={styles.textarea}
            rows={9}
            maxLength={TEXT_MAX}
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="예) 학교 복도를 걷고 있었는데 갑자기 창밖이 바다로 변했어"
            disabled={busy}
          />
          <span className={styles.characterCount}>
            {text.length} / {TEXT_MAX}
          </span>
          {error && <ErrorBox message={error} />}
          <div className={styles.actions}>
            <button type="button" className={styles.primaryButton} onClick={submitText} disabled={!text.trim() || busy}>
              {busy ? "저장하는 중" : "다음"}
            </button>
          </div>
        </section>
      )}
    </StepLayout>
  );
}
