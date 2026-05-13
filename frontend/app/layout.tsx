import type { Metadata } from "next";
import { IBM_Plex_Sans, Syne } from "next/font/google";

import "./globals.css";

const fontDisplay = Syne({
  subsets: ["latin"],
  variable: "--font-display",
});

const fontBody = IBM_Plex_Sans({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500", "600"],
  variable: "--font-body",
});

export const metadata: Metadata = {
  title: "Smart Cut Reel",
  description:
    "Turn 16:9 footage into smooth 9:16 vertical video — optional long-silence trimming (with audio prep before VAD) and optional filler-word cuts.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${fontDisplay.variable} ${fontBody.variable} min-h-screen bg-zinc-950 font-sans text-zinc-100 antialiased`}
      >
        <div className="relative min-h-screen">
          <div
            aria-hidden
            className="pointer-events-none fixed inset-0 bg-[radial-gradient(ellipse_80%_50%_at_50%_-20%,rgba(16,185,129,0.12),transparent)]"
          />
          <div className="relative mx-auto max-w-5xl px-5 py-12 sm:px-6 sm:py-16">
            {children}
          </div>
        </div>
      </body>
    </html>
  );
}
