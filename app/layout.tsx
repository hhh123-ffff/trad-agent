import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "观澜",
  description: "A 股盘后复盘与公开信息候选观察工作台",
  manifest: "/manifest.json"
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#f7f3ec"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
