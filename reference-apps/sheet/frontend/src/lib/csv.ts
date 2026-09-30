/** RFC 4180 parser. Returns null for an unterminated quoted field. */
export function parseCsv(text: string): string[][] | null {
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let i = 0;
  let quoted = false;
  let fieldStarted = false;
  while (i < text.length) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') { field += '"'; i += 2; continue; }
        quoted = false;
        i++;
        continue;
      }
      field += ch;
      i++;
      continue;
    }
    if (ch === '"' && !fieldStarted) { quoted = true; fieldStarted = true; i++; continue; }
    if (ch === ',') { row.push(field); field = ''; fieldStarted = false; i++; continue; }
    if (ch === '\r' || ch === '\n') {
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
      fieldStarted = false;
      i += ch === '\r' && text[i + 1] === '\n' ? 2 : 1;
      continue;
    }
    field += ch;
    fieldStarted = true;
    i++;
  }
  if (quoted) return null;
  if (fieldStarted || field !== '' || row.length) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

export function csvEscape(v: string): string {
  return /[",\r\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

export function toCsv(rows: string[][]): string {
  return rows.map((r) => r.map(csvEscape).join(',')).join('\n');
}

/** Tab/newline separated clipboard text into a rectangle (empty fields preserved). */
export function parseTsv(text: string): string[][] {
  let t = text.replace(/\r\n?/g, '\n');
  if (t.endsWith('\n')) t = t.slice(0, -1);
  return t.split('\n').map((line) => line.split('\t'));
}
