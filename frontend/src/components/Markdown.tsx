import type { ReactNode } from "react";

// Minimal, safe Markdown renderer for AI output: headings, bullet/numbered lists,
// pipe tables, **bold**, and paragraphs. Builds React elements (never raw HTML),
// so model output can't inject markup.

function inline(text: string, key: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) =>
    p.startsWith("**") && p.endsWith("**") && p.length > 4
      ? <strong key={`${key}-${i}`}>{p.slice(2, -2)}</strong>
      : <span key={`${key}-${i}`}>{p}</span>);
}

const cells = (row: string) =>
  row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
const isDivider = (row: string) => /^\s*\|?\s*:?-{2,}/.test(row);

export default function Markdown({ text }: { text: string }) {
  const lines = (text || "").replace(/\r/g, "").split("\n");
  const out: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const k = `l${i}`;
    if (!line.trim()) { i++; continue; }

    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      const level = h[1].length;
      const style = { margin: level <= 2 ? "16px 0 6px" : "12px 0 4px", fontSize: level <= 2 ? 17 : 15 };
      out.push(level <= 2 ? <h3 key={k} style={style}>{inline(h[2], k)}</h3>
                          : <h4 key={k} style={style}>{inline(h[2], k)}</h4>);
      i++; continue;
    }

    if (line.trim().startsWith("|")) {
      const rows: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(lines[i++]);
      const body = rows.filter((r) => !isDivider(r));
      const [head, ...rest] = body;
      out.push(
        <div key={k} style={{ overflowX: "auto", margin: "6px 0" }}>
          <table>
            {head && <thead><tr>{cells(head).map((c, j) => <th key={j}>{inline(c, `${k}h${j}`)}</th>)}</tr></thead>}
            <tbody>
              {rest.map((r, ri) => (
                <tr key={ri}>{cells(r).map((c, j) => <td key={j}>{inline(c, `${k}r${ri}c${j}`)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>);
      continue;
    }

    const bullet = /^\s*([-*•]|\d+[.)])\s+/;
    if (bullet.test(line)) {
      const ordered = /^\s*\d+[.)]/.test(line);
      const items: string[] = [];
      while (i < lines.length && bullet.test(lines[i])) items.push(lines[i++].replace(bullet, ""));
      const list = items.map((it, j) => <li key={j}>{inline(it, `${k}i${j}`)}</li>);
      out.push(ordered ? <ol key={k} style={{ paddingLeft: 22, margin: "4px 0" }}>{list}</ol>
                       : <ul key={k} style={{ paddingLeft: 22, margin: "4px 0" }}>{list}</ul>);
      continue;
    }

    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|\s*\||\s*([-*•]|\d+[.)])\s)/.test(lines[i])) {
      para.push(lines[i++]);
    }
    if (!para.length) { para.push(line); i++; }
    out.push(<p key={k} style={{ margin: "4px 0", lineHeight: 1.6 }}>{inline(para.join(" "), k)}</p>);
  }
  return <div className="markdown">{out}</div>;
}
