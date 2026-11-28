const paths = {
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z M19 11a7 7 0 0 1-14 0 M12 18v3 M8 21h8",
  archive: "M4 8h16v13H4z M3 3h18v5H3z M9 12h6",
  globe: "M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0 M2 12h20 M12 2a15 15 0 0 1 0 20 M12 2a15 15 0 0 0 0 20",
  person: "M16 8a4 4 0 1 1-8 0 4 4 0 0 1 8 0 M4 21a8 8 0 0 1 16 0",
  place: "M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0 M14 10a2 2 0 1 1-4 0 2 2 0 0 1 4 0",
  plus: "M12 5v14 M5 12h14",
  minus: "M5 12h14",
  target: "M12 2v3 M12 19v3 M2 12h3 M19 12h3 M18 12a6 6 0 1 1-12 0 6 6 0 0 1 12 0",
  edit: "m15 4 5 5 M4 15 15 4l5 5L9 20H4z",
  arrow: "M5 12h14 M13 6l6 6-6 6",
  close: "m6 6 12 12 M6 18 18 6",
  moon: "M20 15a8 8 0 0 1-11-11 9 9 0 1 0 11 11",
  info: "M12 11v6 M12 7h.01 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  route: "M6 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4 M18 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4 M8 17h7a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h7",
  calendar: "M4 6h16v15H4z M4 10h16 M8 3v4 M16 3v4",
  link: "M10 14a4 4 0 0 0 6 0l3-3a4 4 0 0 0-6-6l-1 1 M14 10a4 4 0 0 0-6 0l-3 3a4 4 0 0 0 6 6l1-1",
};

export type IconName = keyof typeof paths;
export default function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}
