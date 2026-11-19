import type { ReactNode } from "react";

// A deliberately small Markdown renderer for the project's own legal drafts: headings, paragraphs, lists, tables, blockquotes, **bold**, `code`
// and [links](https://…). It builds React nodes (never an HTML string), so nothing in a document can inject markup, and it takes no dependency.

function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(re)) {
    if (m.index! > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) out.push(<strong key={`${key}-${i++}`}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`")) out.push(<code key={`${key}-${i++}`} className="font-mono-nums rounded bg-surface-2 px-1 text-[0.9em]">{tok.slice(1, -1)}</code>);
    else {
      const [, label, href] = /\[([^\]]+)\]\(([^)]+)\)/.exec(tok)!;
      const safe = /^(https?:\/\/|\/)/.test(href);
      out.push(safe ? <a key={`${key}-${i++}`} href={href} className="font-medium text-accent hover:underline">{label}</a> : label);
    }
    last = m.index! + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function renderMarkdown(src: string): ReactNode[] {
  const lines = src.split("\n");
  const out: ReactNode[] = [];
  let i = 0;
  let k = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const key = `b${k++}`;
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    if (h) {
      const cls = h[1].length === 1 ? "text-xl font-semibold mt-2" : "text-base font-semibold mt-4";
      out.push(<h2 key={key} className={`${cls} text-text-primary`}>{inline(h[2], key)}</h2>);
      i++;
    } else if (line.startsWith(">")) {
      const buf: string[] = [];
      while (i < lines.length && lines[i].startsWith(">")) buf.push(lines[i++].replace(/^>\s?/, ""));
      out.push(<blockquote key={key} data-testid="legal-banner" className="rounded-md border border-band-red/40 bg-band-red/10 p-3 text-sm text-text-primary">{inline(buf.join(" "), key)}</blockquote>);
    } else if (/^\s*[*-]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items: string[] = [];
      while (i < lines.length && (/^\s*[*-]\s+/.test(lines[i]) || /^\s*\d+\.\s+/.test(lines[i]) || (lines[i].startsWith("  ") && lines[i].trim()))) {
        if (/^\s*([*-]|\d+\.)\s+/.test(lines[i])) items.push(lines[i].replace(/^\s*([*-]|\d+\.)\s+/, ""));
        else items[items.length - 1] += " " + lines[i].trim();
        i++;
      }
      const Tag = ordered ? "ol" : "ul";
      out.push(<Tag key={key} className={`${ordered ? "list-decimal" : "list-disc"} ml-5 flex flex-col gap-1 text-sm text-text-secondary`}>{items.map((t, j) => <li key={j}>{inline(t, `${key}-${j}`)}</li>)}</Tag>);
    } else if (line.startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].startsWith("|")) {
        if (!/^\|[\s:|-]+\|$/.test(lines[i])) rows.push(lines[i].split("|").slice(1, -1).map((c) => c.trim()));
        i++;
      }
      out.push(
        <div key={key} className="overflow-x-auto">
          <table className="w-full min-w-[32rem] border-collapse text-left text-xs text-text-secondary">
            <thead><tr>{rows[0].map((c, j) => <th key={j} className="border-b border-border p-2 font-medium text-text-primary">{inline(c, `${key}h${j}`)}</th>)}</tr></thead>
            <tbody>{rows.slice(1).map((r, ri) => <tr key={ri}>{r.map((c, j) => <td key={j} className="border-b border-border/60 p-2 align-top">{inline(c, `${key}-${ri}-${j}`)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
    } else {
      const buf: string[] = [];
      while (i < lines.length && lines[i].trim() && !/^(#{1,3}\s|>|\||\s*[*-]\s|\s*\d+\.\s)/.test(lines[i])) buf.push(lines[i++]);
      out.push(<p key={key} className="text-sm text-text-secondary">{inline(buf.join(" "), key)}</p>);
    }
  }
  return out;
}
