import Link from "next/link";
import type { ReactNode } from "react";
import Icon, { type IconName } from "./Icon";
import { USE_MOCK } from "./api";
import styles from "./dream-record.module.css";

// 화면 틀은 B2 결과 화면(features/dream-results/DreamResults.tsx)과 같게 맞췄습니다.
// 왼쪽 메뉴, 제목, 가운데 내용, 오른쪽 안내 순서이고 좁은 화면에서는 메뉴가 위로 올라갑니다.

const steps: { label: string; icon: IconName; tip: string }[] = [
  { label: "꿈 입력", icon: "mic", tip: "잠에서 깬 직후에 가장 많이 기억나요. 떠오르는 것부터 남겨 주세요." },
  { label: "내용 확인", icon: "edit", tip: "말한 내용이 글로 잘 옮겨졌는지 봐 주세요. 여기서 고친 글이 꿈의 원문이 돼요." },
  { label: "되묻기", icon: "chat", tip: "정해진 답은 없어요. 기억나지 않는 것도 그대로 기록돼요." },
  { label: "확신도", icon: "sliders", tip: "여기서 고른 값은 결과 화면의 스토리보드에도 그대로 표시돼요." },
];

type Props = {
  // 1~4. 이어하기처럼 단계가 정해지지 않은 화면은 비워 둡니다.
  step?: number;
  title: string;
  description?: string;
  children: ReactNode;
};

export default function StepLayout({ step, title, description, children }: Props) {
  const current = step ? steps[step - 1] : null;

  const stepItems = steps.map((item, index) => {
    const number = index + 1;
    const state = !step || number > step ? "" : number < step ? styles.stepDone : styles.stepCurrent;
    return (
      <li key={item.label} className={`${styles.stepItem} ${state}`} aria-current={number === step ? "step" : undefined}>
        <span className={styles.stepNumber}>{step && number < step ? <Icon name="check" size={13} /> : number}</span>
        <span className={styles.stepLabel}>{item.label}</span>
      </li>
    );
  });

  return (
    <div className={styles.app}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <span className={styles.brandMark}>✦</span>
          <div>
            <strong>꿈 기록</strong>
            <span>기억을 한 장면씩</span>
          </div>
        </div>
        <nav className={styles.navigation} aria-label="메뉴">
          <Link href="/record" className={`${styles.navItem} ${styles.activeNav}`} aria-current="page">
            <Icon name="mic" size={21} />꿈 기록하기
          </Link>
          <Link href="/" className={styles.navItem}>
            <Icon name="archive" size={21} />결과와 보관
          </Link>
        </nav>
        <div className={styles.sidebarDecoration} aria-hidden="true">
          <span>✧</span>
          <Icon name="moon" size={62} />
          <span>✦</span>
        </div>
        {USE_MOCK && (
          <div className={styles.demoInfo}>
            <span className={styles.demoBadge}>예시 모드</span>
            <p>
              서버 없이 예시 데이터로
              <br />
              동작하고 있어요.
            </p>
          </div>
        )}
      </aside>

      <main className={styles.main}>
        <header className={styles.pageHeader}>
          <div className={styles.headingGroup}>
            <span className={styles.headingIcon}>
              <Icon name={current?.icon ?? "moon"} size={26} />
            </span>
            <div>
              <h1>{title}</h1>
              {description && <p>{description}</p>}
            </div>
          </div>
          {step && (
            <span className={styles.stepCount}>
              {step} / {steps.length} 단계
            </span>
          )}
        </header>

        {step && (
          <ol className={styles.stepper} aria-label="기록 단계">
            {stepItems}
          </ol>
        )}

        <div className={styles.workspace}>
          <div className={styles.centerColumn}>{children}</div>
          <aside className={styles.detailPanel}>
            <h2 className={styles.panelTitle}>기록 단계</h2>
            <ol className={styles.stepRail}>{stepItems}</ol>
            {current && (
              <p className={styles.panelTip}>
                <Icon name="info" size={15} />
                {current.tip}
              </p>
            )}
          </aside>
        </div>
      </main>
    </div>
  );
}

export function Loading({ message }: { message: string }) {
  return (
    <div className={`${styles.card} ${styles.status}`} role="status">
      <span className={styles.spinner} aria-hidden="true" />
      <p>{message}</p>
    </div>
  );
}

export function ErrorBox({ message, children }: { message: string; children?: ReactNode }) {
  return (
    <div className={styles.errorBox} role="alert">
      <p>{message}</p>
      {children && <div className={styles.errorActions}>{children}</div>}
    </div>
  );
}
