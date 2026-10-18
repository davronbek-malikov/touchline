"use client";

import Link from "next/link";
import { Fragment, useId, useState } from "react";

import { Citation, Report } from "@/lib/api";

function CitedSpan({ text, citations, refNo }: { text: string; citations: Citation[]; refNo: (c: Citation) => number }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className="cited" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button type="button" className="cited-text" aria-describedby={open ? id : undefined}
              onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onClick={() => setOpen((o) => !o)}>
        {text}
      </button>
      <sup>{[...new Set(citations.map(refNo))].map((n) => `[${n}]`).join("")}</sup>
      {open && (
        <span role="tooltip" id={id} className="cite-card">
          {citations.map((c, i) => (
            <span key={i} className="cite-card-item">
              <span className="cite-card-quote">“{c.cited_text}”</span>
              <span className="cite-card-source">{c.title}</span>
            </span>
          ))}
        </span>
      )}
    </span>
  );
}

/** The report as plain text with [n] markers and a source list, for copying. */
export function reportPlainText(report: Report): string {
  const refs = new Map<string, number>();
  let body = "";
  for (const b of report.blocks) {
    body += b.text;
    const nums = [...new Set(b.citations.map((c) => {
      const key = c.source_id || c.title;
      if (!refs.has(key)) refs.set(key, refs.size + 1);
      return refs.get(key)!;
    }))];
    if (nums.length) body += nums.map((n) => `[${n}]`).join("");
  }
  const sources = [...refs.entries()].map(([key, n]) => {
    const c = report.blocks.flatMap((b) => b.citations).find((x) => (x.source_id || x.title) === key)!;
    return `[${n}] ${c.title}${c.url ? ` ${c.url}` : ""}`;
  });
  return `Scouting report: ${report.name}\n\n${body.trim()}${sources.length ? `\n\nSources:\n${sources.join("\n")}` : ""}`;
}

/** Renders report blocks with lightweight markdown (bold, headings) and citation hover cards. */
export default function ReportView({ report }: { report: Report }) {
  if (report.error) {
    return <div className="error">The report on {report.name ?? `player ${report.player_id}`} couldn&apos;t be written: {report.error}</div>;
  }
  const refs = new Map<string, { n: number; c: Citation }>();
  const refNo = (c: Citation) => {
    const key = c.source_id || c.title;
    if (!refs.has(key)) refs.set(key, { n: refs.size + 1, c });
    return refs.get(key)!.n;
  };
  // Assign numbers in reading order before rendering.
  report.blocks.forEach((b) => b.citations.forEach(refNo));

  return (
    <article className="report">
      <header className="report-head">
        <h2>{report.name}</h2>
        <Link href={`/players/${report.player_id}`} className="hint">Open profile</Link>
      </header>
      <div className="report-body">
        {report.blocks.map((b, i) =>
          b.citations.length ? (
            <CitedSpan key={i} text={b.text} citations={b.citations} refNo={refNo} />
          ) : (
            <Fragment key={i}>{renderInline(b.text)}</Fragment>
          ),
        )}
      </div>
      {refs.size > 0 && (
        <footer className="report-sources">
          <h3>Sources</h3>
          <ol>
            {[...refs.values()].map(({ n, c }) => (
              <li key={n} value={n}>
                {c.url ? <a href={c.url} target="_blank" rel="noreferrer">{c.title}</a> : c.title}
                {c.source === "wikipedia" && <span className="hint"> (CC BY-SA 4.0)</span>}
              </li>
            ))}
          </ol>
        </footer>
      )}
    </article>
  );
}

/** Minimal inline markdown for uncited report text: "## Heading" lines and **bold**.
 *  Line breaks come from white-space: pre-line on .report-body. */
function renderInline(text: string) {
  const lines = text.split("\n");
  const out: React.ReactNode[] = [];
  lines.forEach((line, i) => {
    const heading = line.match(/^#{1,3}\s+(.*)$/);
    if (heading) {
      out.push(<strong key={i} className="report-h">{heading[1].replace(/\*\*/g, "")}</strong>);
      return;
    }
    const prevHeading = i > 0 && /^#{1,3}\s/.test(lines[i - 1]);
    if (prevHeading && line.trim() === "") return; // the heading block already breaks the line
    const parts = line.replace(/^[-*]\s/, "• ").split(/(\*\*[^*]+\*\*)/).map((seg, j) =>
      seg.startsWith("**") && seg.endsWith("**")
        ? <strong key={j}>{seg.slice(2, -2)}</strong>
        : <Fragment key={j}>{seg}</Fragment>);
    out.push(<Fragment key={i}>{parts}{i < lines.length - 1 && !/^#{1,3}\s/.test(lines[i + 1]) ? "\n" : ""}</Fragment>);
  });
  return out;
}
