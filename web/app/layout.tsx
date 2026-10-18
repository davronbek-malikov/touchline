import type { Metadata } from "next";
import { Barlow, Barlow_Condensed } from "next/font/google";
import { Suspense } from "react";

import { ChatsProvider } from "@/components/ChatsProvider";
import Rail from "@/components/Rail";

import "./globals.css";
import "./screens.css";
import "./chat.css";

const barlow = Barlow({ subsets: ["latin", "latin-ext"], weight: ["400", "500", "600", "700"], variable: "--font-barlow" });
const condensed = Barlow_Condensed({ subsets: ["latin", "latin-ext"], weight: ["600", "700"], variable: "--font-barlow-condensed" });

export const metadata: Metadata = {
  title: "Touchline",
  description: "A scouting assistant: describe the player you need and get an evidence-backed shortlist with cited reports.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${barlow.variable} ${condensed.variable}`}>
      <body>
        <ChatsProvider>
          <div className="shell">
            <Suspense><Rail /></Suspense>
            <main className="main">{children}</main>
          </div>
        </ChatsProvider>
      </body>
    </html>
  );
}
