import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "꿈 기록 | 기록하기",
  description: "꿈을 말하거나 적고, 되묻기와 확신도 입력으로 기억을 정리하는 공간",
};

export default function RecordLayout({ children }: LayoutProps<"/record">) {
  return children;
}
