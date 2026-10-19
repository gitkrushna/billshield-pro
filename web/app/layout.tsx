import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BillShield Pro — M1 foundation",
  description: "Development foundation. Classification is not available at M1.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
