import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "꿈 기록 | 결과와 보관",
  description: "꿈의 장면과 기억의 확신도를 확인하고 기록을 다시 보는 공간",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
