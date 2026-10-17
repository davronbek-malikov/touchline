"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/", label: "Search" },
  { href: "/shortlist", label: "Shortlists" },
  { href: "/compare", label: "Compare" },
  { href: "/notes", label: "Notes" },
  { href: "/about", label: "About the data" },
];

export default function Rail() {
  const path = usePathname();
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <aside className="rail">
      <Link href="/" className="wordmark">Touchline</Link>
      <p className="tagline">Scouting copilot</p>
      <nav className="nav" aria-label="Main">
        {NAV.map((n) => (
          <Link key={n.href} href={n.href} aria-current={active(n.href) ? "page" : undefined}>
            {n.label}
          </Link>
        ))}
      </nav>
      <p className="rail-foot">
        Market data as of 6 July 2026. Event data from StatsBomb open data.
      </p>
    </aside>
  );
}
