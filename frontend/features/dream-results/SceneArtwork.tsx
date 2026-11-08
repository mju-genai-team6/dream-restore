"use client";

import { useId } from "react";
import type { ArtworkKind } from "./types";
import styles from "./dream-results.module.css";

// 외부 이미지나 생성 결과물 대신 사용하는 화면 예시용 벡터 일러스트입니다.
export default function SceneArtwork({ kind, label }: { kind: ArtworkKind; label: string }) {
  const id = useId().replaceAll(":", "");
  const evening = kind === "sea" || kind === "village" || kind === "person";
  return (
    <svg className={styles.artwork} viewBox="0 0 720 430" role="img" aria-label={`${label} 예시 이미지`} preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id={`${id}-sky`} x2="0" y2="1">
          <stop stopColor={evening ? "#a7abd4" : "#b8d6e5"} />
          <stop offset=".62" stopColor={evening ? "#f2c9cf" : "#f1e5e3"} />
          <stop offset="1" stopColor="#f7e7ca" />
        </linearGradient>
        <linearGradient id={`${id}-water`} x2="0" y2="1"><stop stopColor="#91b6ca" /><stop offset="1" stopColor="#647c9f" /></linearGradient>
        <linearGradient id={`${id}-path`} x2="0" y2="1"><stop stopColor="#e2cfba" /><stop offset="1" stopColor="#f6e9d3" /></linearGradient>
        <filter id={`${id}-soft`}><feGaussianBlur stdDeviation="5" /></filter>
      </defs>
      <rect width="720" height="430" fill={`url(#${id}-sky)`} />
      <g fill="#fff5ed" opacity=".52">
        <ellipse cx="130" cy="98" rx="120" ry="15" /><ellipse cx="210" cy="86" rx="68" ry="13" />
        <ellipse cx="600" cy="157" rx="160" ry="18" /><ellipse cx="475" cy="68" rx="70" ry="12" />
      </g>
      <circle cx="552" cy="102" r="32" fill="#fff1cd" opacity=".9" />
      <path d="M0 254 97 177 200 245 323 164 449 253 580 196 720 263V430H0Z" fill="#a9aac5" opacity=".62" />
      <path d="M0 292 156 230 280 288 452 219 576 274 720 235V430H0Z" fill="#8f9fb0" opacity=".65" />

      {kind === "sea" || kind === "person" ? <>
        <path d="M0 266Q280 251 720 273V430H0Z" fill={`url(#${id}-water)`} />
        <g stroke="#d8e6e7" opacity=".65" strokeWidth="2"><path d="M30 291h135m45 15h210m90-12h160M0 333h170m34 18h165m102-11h220M70 380h130m90 16h110m130-13h175" /></g>
        <path d="M526 273h48l55 157H448Z" fill="#f3d7cf" opacity=".4" />
        <path d="M0 401 720 328V430H0Z" fill="#c9b4a4" />
        <g stroke="#eee1d1" strokeWidth="10"><path d="M0 340 720 283M50 338v85m145-100v88m157-105v90m159-105v91m166-103v90" /></g>
      </> : <>
        <path d="M0 301Q180 256 358 299T720 289V430H0Z" fill="#9dad9a" />
        <path d="M340 298Q360 341 260 430H530Q424 345 366 298Z" fill={`url(#${id}-path)`} />
      </>}

      {kind === "school" && <>
        <path d="M107 195h402v140H107Z" fill="#e9d7c0" />
        <path d="M83 194 310 120 535 194Z" fill="#8e8cae" />
        <path d="M277 145h63v190h-63Z" fill="#f5e8d4" />
        <path d="M277 145 308 111 340 145Z" fill="#85829f" />
        <circle cx="309" cy="174" r="16" fill="#faf7ed" stroke="#aba2a2" strokeWidth="3" />
        <path d="M309 163v12l9 5" fill="none" stroke="#958a99" strokeWidth="2" />
        {[0, 1, 2, 3, 4, 5].map((n) => <g key={n} fill="#8299ad"><rect x={135 + n * 60} y="217" width="25" height="32" rx="2" /><rect x={135 + n * 60} y="272" width="25" height="30" rx="2" /></g>)}
        <path d="M294 290q14-22 29 0v45h-29Z" fill="#8a7f8c" />
      </>}

      {kind === "house" && <>
        <path d="M199 205h293v140H199Z" fill="#f0ddbf" />
        <path d="M174 208 338 105 519 208Z" fill="#b2929b" />
        <path d="M373 101h24v59h-24Z" fill="#c3a9a3" />
        <path d="M319 257q22-34 44 0v88h-44Z" fill="#9a8a8e" />
        <g fill="#edc993" stroke="#b4a394" strokeWidth="5"><rect x="230" y="239" width="44" height="48" rx="3" /><rect x="410" y="239" width="44" height="48" rx="3" /></g>
        <path d="M251 238v49m-21-24h44m158-25v49m-22-24h44" stroke="#b4a394" strokeWidth="3" />
        <path d="M300 345h82l31 20H278Z" fill="#d3bfa9" />
      </>}

      {kind === "village" && <>
        {[{ x: 35, y: 235, w: 152 }, { x: 222, y: 195, w: 182 }, { x: 447, y: 227, w: 173 }].map(({ x, y, w }) => <g key={x}>
          <rect x={x} y={y} width={w} height="125" fill="#c8b9c2" />
          <path d={`M${x - 16} ${y} ${x + w / 2} ${y - 72} ${x + w + 16} ${y}Z`} fill="#89849f" />
          <rect x={x + 26} y={y + 30} width="29" height="37" fill="#f3d7a4" rx="3" />
          <rect x={x + w - 54} y={y + 30} width="29" height="37" fill="#f3d7a4" rx="3" />
          <rect x={x + w / 2 - 16} y={y + 76} width="33" height="49" fill="#8c819a" rx="4" />
        </g>)}
      </>}

      {kind !== "village" && <g>
        <path d="M80 183q-16 85 0 247m-9-169-33-40m39 22 37-48" fill="none" stroke="#8f8d96" strokeWidth="12" />
        <g fill={kind === "sea" || kind === "person" ? "#c2b3d1" : "#e6c1ce"} opacity=".9"><circle cx="59" cy="168" r="59" /><circle cx="111" cy="181" r="54" /><circle cx="31" cy="213" r="49" /></g>
        <path d="M661 232v198m0-143-33-24m34 1 29-35" fill="none" stroke="#8c9592" strokeWidth="10" />
        <g fill="#a4b7a2"><circle cx="642" cy="224" r="43" /><circle cx="682" cy="216" r="41" /><circle cx="672" cy="257" r="47" /></g>
      </g>}

      {kind === "sea" && <g transform="translate(404 233)">
        <path d="M-24 75q5-48 24-49 21 0 27 49l13 87h-74Z" fill="#cdc6d9" />
        <ellipse cy="14" rx="21" ry="27" fill="#675d79" />
        <path d="M-20 10q-10 45-2 75 29-7 44-2 4-47-2-73Z" fill="#675d79" />
      </g>}
      {kind === "person" && <g filter={`url(#${id}-soft)`} opacity=".65">
        <ellipse cx="380" cy="256" rx="25" ry="34" fill="#897b94" /><path d="M336 405q2-124 43-125 46 0 50 125Z" fill="#a196af" />
      </g>}
      <g opacity=".9">{[15, 42, 84, 117, 583, 609, 647, 684].map((x, index) => <g key={x}>
        <path d={`M${x} 430v-${20 + index % 3 * 12}`} stroke="#819482" strokeWidth="3" />
        <circle cx={x} cy={410 - index % 3 * 12} r="7" fill={index % 2 ? "#e2b6c9" : "#efe1bf"} />
      </g>)}</g>
    </svg>
  );
}
