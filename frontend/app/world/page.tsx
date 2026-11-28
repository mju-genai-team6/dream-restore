import type { Metadata } from "next";
import DreamWorld from "@/features/dream-world/DreamWorld";

export const metadata: Metadata = {
  title: "꿈 기록 | 세계관",
  description: "여러 꿈에 반복해 나온 인물과 장소를 이어 보고 세계관에 등록하는 공간",
};

export default function WorldPage() {
  return <DreamWorld />;
}
