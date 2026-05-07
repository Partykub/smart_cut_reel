import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Smart Cut Reel · Debug",
  description: "Phase 1 debug frontend for the smart cut reel pipeline.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-zinc-950 text-zinc-100 antialiased">
        <div className="mx-auto max-w-5xl px-6 py-10">{children}</div>
      </body>
    </html>
  );
}
