"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import StepLayout, { ErrorBox, Loading } from "./StepLayout";
import { answerQuestion, getInterview } from "./api";
import type { InterviewItem } from "./types";
import { errorMessage, useStep } from "./useRequest";
import styles from "./dream-record.module.css";

export default function InterviewStep({ dreamId }: { dreamId: string }) {
  const router = useRouter();
  // 질문을 다 답한 뒤에도 대화를 다시 볼 수 있게 확신도 단계의 꿈도 받아 줍니다.
  const interview = useStep(dreamId, ["interview", "confidence"], () => getInterview(dreamId));

  return (
    <StepLayout step={3} title="조금 더 떠올려 볼까요?" description="기억나는 만큼만 답해 주세요. 떠오르지 않으면 건너뛰어도 괜찮아요.">
      {interview.loading && <Loading message="질문을 준비하고 있어요. 처음에는 30초 정도 걸릴 수 있어요." />}
      {interview.error && (
        <ErrorBox message={interview.error}>
          <button type="button" className={styles.linkButton} onClick={interview.retry}>
            다시 시도
          </button>
          <button type="button" className={styles.linkButton} onClick={() => router.push("/record")}>
            새로 기록하기
          </button>
        </ErrorBox>
      )}
      {interview.data && <Chat dreamId={dreamId} items={interview.data} onChange={interview.setData} />}
    </StepLayout>
  );
}

// 서버의 질문 목록에는 답변 내용이 없어서, 내가 쓴 답은 이 탭(sessionStorage)에만 두고 말풍선에 보여 줍니다.
const answersKey = (dreamId: string) => `dream-restore:b1-answers:${dreamId}`;

function loadAnswers(dreamId: string): Record<number, string> {
  try {
    return JSON.parse(window.sessionStorage.getItem(answersKey(dreamId)) ?? "{}");
  } catch {
    return {};
  }
}

function rememberAnswer(dreamId: string, questionId: number, answer: string) {
  try {
    window.sessionStorage.setItem(answersKey(dreamId), JSON.stringify({ ...loadAnswers(dreamId), [questionId]: answer }));
  } catch {
    // 저장소를 못 쓰는 브라우저에서는 새로고침 뒤 '답변함'으로만 보입니다.
  }
}

type ChatProps = {
  dreamId: string;
  items: InterviewItem[];
  onChange: (items: InterviewItem[]) => void;
};

function Chat({ dreamId, items, onChange }: ChatProps) {
  const router = useRouter();
  const [draft, setDraft] = useState("");
  const [answers, setAnswers] = useState<Record<number, string>>(() => loadAnswers(dreamId));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chatRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const answered = items.filter((item) => item.answered);
  const current = items.find((item) => !item.answered);

  // 새 질문이 나오면 대화 영역만 맨 아래로 내립니다.
  useEffect(() => {
    const chat = chatRef.current;
    if (chat) chat.scrollTop = chat.scrollHeight;
  }, [answered.length]);

  // text 가 null 이면 '잘 기억 안 남'
  async function send(text: string | null) {
    if (!current || busy) return;
    const answer = text?.trim() || null;
    setBusy(true);
    setError(null);
    try {
      await answerQuestion(dreamId, current.questionId, answer);
      if (answer) {
        rememberAnswer(dreamId, current.questionId, answer);
        setAnswers((prev) => ({ ...prev, [current.questionId]: answer }));
      }
      onChange(items.map((item) => (item.questionId === current.questionId ? { ...item, answered: true, skipped: !answer } : item)));
      setDraft("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      // 답을 써서 보냈으면 커서를 입력창으로 되돌려 다음 질문에 바로 답할 수 있게 합니다.
      // 건너뛸 때는 휴대폰 키보드가 올라오지 않게 그대로 둡니다.
      if (answer) inputRef.current?.focus();
    }
  }

  return (
    <section className={styles.card}>
      <div className={styles.progress}>
        <span>
          {answered.length} / {items.length}
        </span>
        <div className={styles.progressBar} aria-hidden="true">
          <div style={{ width: `${(answered.length / items.length) * 100}%` }} />
        </div>
      </div>

      <div className={styles.chat} ref={chatRef} aria-live="polite">
        {answered.map((item) => (
          <div key={item.questionId} className={styles.chatPair}>
            <p className={styles.bubbleQuestion}>{item.question}</p>
            {item.skipped ? (
              <p className={styles.bubbleSkipped}>잘 기억 안 남</p>
            ) : (
              <p className={styles.bubbleAnswer}>{answers[item.questionId] ?? "답변함"}</p>
            )}
          </div>
        ))}
        {current && <p className={styles.bubbleQuestion}>{current.question}</p>}
      </div>

      {error && <ErrorBox message={error} />}

      {current ? (
        <div className={styles.answerBox}>
          <label className={styles.srOnly} htmlFor="answer">
            답변
          </label>
          <textarea
            id="answer"
            ref={inputRef}
            className={styles.textarea}
            rows={3}
            maxLength={1000}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="떠오르는 대로 적어 주세요"
            readOnly={busy}
          />
          <div className={styles.actions}>
            <button type="button" className={styles.secondaryButton} onClick={() => send(null)} disabled={busy}>
              잘 기억 안 남
            </button>
            <button type="button" className={styles.primaryButton} onClick={() => send(draft)} disabled={!draft.trim() || busy}>
              {busy ? "저장하는 중" : "보내기"}
            </button>
          </div>
        </div>
      ) : (
        <div className={styles.actions}>
          <p className={styles.helper}>질문은 여기까지예요. 이제 기억이 얼마나 또렷한지 알려 주세요.</p>
          <button type="button" className={styles.primaryButton} onClick={() => router.push(`/record/${dreamId}/confidence`)}>
            다음
          </button>
        </div>
      )}
    </section>
  );
}
