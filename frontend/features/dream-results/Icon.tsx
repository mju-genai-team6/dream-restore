import type { CSSProperties } from "react";

const paths = {
  storyboard: "M3 4h18v16H3z M3 14l5-5 5 5 3-3 5 5 M8 7h.01",
  video: "M4 4h16v16H4z M10 8l6 4-6 4z",
  archive: "M4 8h16v13H4z M3 3h18v5H3z M9 12h6",
  edit: "m15 4 5 5 M4 15 15 4l5 5L9 20H4z",
  pin: "M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0 M14 10a2 2 0 1 1-4 0 2 2 0 0 1 4 0",
  search: "M20 20l-5-5 M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0",
  arrow: "M5 12h14 M13 6l6 6-6 6",
  clock: "M12 7v5l3 2 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  check: "m5 12 4 4L19 6",
  close: "m6 6 12 12 M6 18 18 6",
  moon: "M20 15a8 8 0 0 1-11-11 9 9 0 1 0 11 11",
  calendar: "M4 5h16v16H4z M4 10h16 M8 3v4 M16 3v4",
  info: "M12 11v6 M12 7h.01 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
};

export type IconName = keyof typeof paths;
export default function Icon({ name, size = 20, style }: { name: IconName; size?: number; style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={style}><path d={paths[name]} /></svg>;
}
