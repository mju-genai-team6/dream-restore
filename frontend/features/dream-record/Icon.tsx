// B2(features/dream-results/Icon.tsx)와 같은 방식의 선 아이콘입니다.
// moon, archive, check, info, edit 는 B2와 같은 모양입니다.
const paths = {
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z M19 11a7 7 0 0 1-14 0 M12 18v3 M8 21h8",
  stop: "M7 7h10v10H7z",
  text: "M4 6h16 M4 12h16 M4 18h10",
  chat: "M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z M9 11h.01 M12 11h.01 M15 11h.01",
  sliders: "M4 7h10 M18 7h2 M4 17h4 M12 17h8 M16 5v4 M10 15v4",
  edit: "m15 4 5 5 M4 15 15 4l5 5L9 20H4z",
  moon: "M20 15a8 8 0 0 1-11-11 9 9 0 1 0 11 11",
  archive: "M4 8h16v13H4z M3 3h18v5H3z M9 12h6",
  check: "m5 12 4 4L19 6",
  info: "M12 11v6 M12 7h.01 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
};

export type IconName = keyof typeof paths;

export default function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={paths[name]} />
    </svg>
  );
}
