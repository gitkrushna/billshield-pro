import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BillShield Pro — GST bill checks",
  description: "Check product classification and GST bill details against cited evidence.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
