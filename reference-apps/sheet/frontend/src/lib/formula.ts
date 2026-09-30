// Formula tokenizer, parser, evaluator and reference rewriting.

export const MAX_ROWS = 100000;
export const MAX_COLS = 18278; // ZZZ

export type Err = { err: string };
export type Scalar = number | string | boolean | null | Err;
export type Value = Scalar | { range: Scalar[] };

export const isErr = (v: unknown): v is Err => typeof v === 'object' && v !== null && 'err' in v;

export function colName(c: number): string {
  let s = '';
  let n = c + 1;
  while (n > 0) {
    const m = (n - 1) % 26;
    s = String.fromCharCode(65 + m) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}

export function colIndex(letters: string): number {
  let n = 0;
  for (const ch of letters.toUpperCase()) n = n * 26 + (ch.charCodeAt(0) - 64);
  return n - 1;
}

export const cellName = (r: number, c: number) => `${colName(c)}${r + 1}`;

export type Ref = { col: number; row: number; absC: boolean; absR: boolean };

type Tok =
  | { t: 'num'; v: number; s: number; e: number }
  | { t: 'str'; v: string; s: number; e: number }
  | { t: 'bool'; v: boolean; s: number; e: number }
  | { t: 'ref'; v: Ref; s: number; e: number }
  | { t: 'func'; v: string; s: number; e: number }
  | { t: 'name'; v: string; s: number; e: number }
  | { t: 'err'; v: string; s: number; e: number }
  | { t: 'op'; v: string; s: number; e: number }
  | { t: '(' | ')' | ',' | ':'; v: string; s: number; e: number };

const REF_RE = /^(\$?)([A-Za-z]{1,3})(\$?)(\d+)$/;

export function tokenize(src: string): Tok[] | null {
  const toks: Tok[] = [];
  let i = 0;
  while (i < src.length) {
    const ch = src[i];
    if (/\s/.test(ch)) { i++; continue; }
    const rest = src.slice(i);
    let m: RegExpMatchArray | null;
    if ((m = rest.match(/^(\d+\.?\d*|\.\d+)(e[+-]?\d+)?/i))) {
      toks.push({ t: 'num', v: Number(m[0]), s: i, e: i + m[0].length });
      i += m[0].length;
      continue;
    }
    if (ch === '"') {
      let j = i + 1;
      let v = '';
      while (j < src.length) {
        if (src[j] === '"') {
          if (src[j + 1] === '"') { v += '"'; j += 2; continue; }
          break;
        }
        v += src[j++];
      }
      if (j >= src.length) return null;
      toks.push({ t: 'str', v, s: i, e: j + 1 });
      i = j + 1;
      continue;
    }
    if ((m = rest.match(/^#[A-Za-z0-9/]+[!?]/))) {
      toks.push({ t: 'err', v: m[0].toUpperCase(), s: i, e: i + m[0].length });
      i += m[0].length;
      continue;
    }
    if ((m = rest.match(/^\$?[A-Za-z_][A-Za-z0-9_.]*\$?\d*/))) {
      const word = m[0];
      const after = src.slice(i + word.length).trimStart();
      const rm = word.match(REF_RE);
      if (rm && after[0] !== '(') {
        toks.push({
          t: 'ref',
          v: { absC: rm[1] === '$', col: colIndex(rm[2]), absR: rm[3] === '$', row: Number(rm[4]) - 1 },
          s: i,
          e: i + word.length,
        });
      } else if (after[0] === '(' && !word.includes('$')) {
        toks.push({ t: 'func', v: word.toUpperCase(), s: i, e: i + word.length });
      } else if (/^(TRUE|FALSE)$/i.test(word)) {
        toks.push({ t: 'bool', v: word.toUpperCase() === 'TRUE', s: i, e: i + word.length });
      } else {
        toks.push({ t: 'name', v: word, s: i, e: i + word.length });
      }
      i += word.length;
      continue;
    }
    const two = src.slice(i, i + 2);
    if (two === '<=' || two === '>=' || two === '<>') {
      toks.push({ t: 'op', v: two, s: i, e: i + 2 });
      i += 2;
      continue;
    }
    if ('+-*/^&=<>%'.includes(ch)) {
      toks.push({ t: 'op', v: ch, s: i, e: i + 1 });
      i++;
      continue;
    }
    if ('(),:'.includes(ch)) {
      toks.push({ t: ch as '(' | ')' | ',' | ':', v: ch, s: i, e: i + 1 });
      i++;
      continue;
    }
    return null;
  }
  return toks;
}

// ---------- AST ----------
type Node =
  | { k: 'lit'; v: Scalar }
  | { k: 'ref'; ref: Ref }
  | { k: 'range'; a: Ref; b: Ref }
  | { k: 'fn'; name: string; args: Node[] }
  | { k: 'un'; op: string; x: Node }
  | { k: 'bin'; op: string; a: Node; b: Node }
  | { k: 'pct'; x: Node };

class ParseError extends Error {}

function parse(toks: Tok[]): Node {
  let p = 0;
  const peek = () => toks[p];
  const next = () => toks[p++];
  const expect = (t: string) => {
    const tok = next();
    if (!tok || tok.t !== t) throw new ParseError('expected ' + t);
    return tok;
  };
  const isOp = (...ops: string[]) => peek()?.t === 'op' && ops.includes(peek()!.v as string);

  function comparison(): Node {
    let a = concat();
    while (isOp('=', '<>', '<', '>', '<=', '>=')) {
      const op = next().v as string;
      a = { k: 'bin', op, a, b: concat() };
    }
    return a;
  }
  function concat(): Node {
    let a = additive();
    while (isOp('&')) { next(); a = { k: 'bin', op: '&', a, b: additive() }; }
    return a;
  }
  function additive(): Node {
    let a = multiplicative();
    while (isOp('+', '-')) {
      const op = next().v as string;
      a = { k: 'bin', op, a, b: multiplicative() };
    }
    return a;
  }
  function multiplicative(): Node {
    let a = power();
    while (isOp('*', '/')) {
      const op = next().v as string;
      a = { k: 'bin', op, a, b: power() };
    }
    return a;
  }
  function power(): Node {
    let a = unary();
    while (isOp('^')) { next(); a = { k: 'bin', op: '^', a, b: unary() }; }
    return a;
  }
  function unary(): Node {
    if (isOp('+', '-')) {
      const op = next().v as string;
      return { k: 'un', op, x: unary() };
    }
    let x = primary();
    while (isOp('%')) { next(); x = { k: 'pct', x }; }
    return x;
  }
  function primary(): Node {
    const tok = next();
    if (!tok) throw new ParseError('unexpected end');
    switch (tok.t) {
      case 'num': return { k: 'lit', v: tok.v };
      case 'str': return { k: 'lit', v: tok.v };
      case 'bool': return { k: 'lit', v: tok.v };
      case 'err': return { k: 'lit', v: { err: tok.v } };
      case 'name': return { k: 'lit', v: { err: '#NAME?' } };
      case 'ref': {
        if (peek()?.t === ':') {
          next();
          const b = next();
          if (!b || b.t !== 'ref') throw new ParseError('bad range');
          return { k: 'range', a: tok.v, b: b.v };
        }
        return { k: 'ref', ref: tok.v };
      }
      case 'func': {
        expect('(');
        const args: Node[] = [];
        if (peek()?.t !== ')') {
          args.push(comparison());
          while (peek()?.t === ',') { next(); args.push(comparison()); }
        }
        expect(')');
        return { k: 'fn', name: tok.v, args };
      }
      case '(': {
        const x = comparison();
        expect(')');
        return x;
      }
      default:
        throw new ParseError('unexpected token');
    }
  }
  const node = comparison();
  if (p !== toks.length) throw new ParseError('trailing tokens');
  return node;
}

const astCache = new Map<string, Node | null>();
function getAst(raw: string): Node | null {
  if (astCache.has(raw)) return astCache.get(raw)!;
  let node: Node | null = null;
  const toks = tokenize(raw.slice(1));
  if (toks && toks.length) {
    try { node = parse(toks); } catch { node = null; }
  }
  if (astCache.size > 5000) astCache.clear();
  astCache.set(raw, node);
  return node;
}

// ---------- evaluation ----------
export const NUM_RE = /^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i;

export function literalValue(raw: string): Scalar {
  if (raw === '' || raw == null) return null;
  if (raw.startsWith("'")) return raw.slice(1); // forced text (e.g. CSV "=..." imported literally)
  const t = raw.trim();
  if (NUM_RE.test(t)) return Number(t);
  return raw;
}

export const isFormula = (raw: string | undefined) => !!raw && raw.startsWith('=') && raw.length > 1;

const validRef = (r: Ref) => r.row >= 0 && r.col >= 0 && r.row < MAX_ROWS && r.col < MAX_COLS;

export function makeEvaluator(cells: Record<string, string>) {
  const memo = new Map<string, Scalar>();
  const stack = new Set<string>();

  function cellValue(r: number, c: number): Scalar {
    const key = `${r},${c}`;
    if (memo.has(key)) return memo.get(key)!;
    const raw = cells[key];
    if (!isFormula(raw)) {
      const v = raw === '=' ? { err: '#ERROR!' } : literalValue(raw ?? '');
      memo.set(key, v);
      return v;
    }
    if (stack.has(key)) return { err: '#REF!' };
    stack.add(key);
    const ast = getAst(raw!);
    let v: Scalar;
    if (!ast) v = { err: '#ERROR!' };
    else {
      const res = ev(ast);
      if (typeof res === 'object' && res !== null && 'range' in res) {
        v = res.range.length === 1 ? res.range[0] : { err: '#VALUE!' };
      } else v = res;
      if (v === null) v = 0;
    }
    stack.delete(key);
    memo.set(key, v);
    return v;
  }

  function toNum(v: Scalar): number | Err {
    if (isErr(v)) return v;
    if (v === null) return 0;
    if (typeof v === 'number') return v;
    if (typeof v === 'boolean') return v ? 1 : 0;
    const t = v.trim();
    if (NUM_RE.test(t)) return Number(t);
    return { err: '#VALUE!' };
  }

  function scalar(n: Node): Scalar {
    const v = ev(n);
    if (typeof v === 'object' && v !== null && 'range' in v) {
      return v.range.length === 1 ? v.range[0] : { err: '#VALUE!' };
    }
    return v;
  }

  function ev(n: Node): Value {
    switch (n.k) {
      case 'lit': return n.v;
      case 'ref': return validRef(n.ref) ? cellValue(n.ref.row, n.ref.col) : { err: '#REF!' };
      case 'range': {
        if (!validRef(n.a) || !validRef(n.b)) return { err: '#REF!' };
        const r1 = Math.min(n.a.row, n.b.row), r2 = Math.max(n.a.row, n.b.row);
        const c1 = Math.min(n.a.col, n.b.col), c2 = Math.max(n.a.col, n.b.col);
        const out: Scalar[] = [];
        for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) out.push(cellValue(r, c));
        return { range: out };
      }
      case 'un': {
        const x = toNum(scalar(n.x));
        if (isErr(x)) return x;
        return n.op === '-' ? -x : x;
      }
      case 'pct': {
        const x = toNum(scalar(n.x));
        return isErr(x) ? x : x / 100;
      }
      case 'bin': {
        const a = scalar(n.a);
        const b = scalar(n.b);
        if (isErr(a)) return a;
        if (isErr(b)) return b;
        if (n.op === '&') return fmtScalar(a) + fmtScalar(b);
        if (['=', '<>', '<', '>', '<=', '>='].includes(n.op)) {
          const na = typeof a === 'number' ? a : a === null ? 0 : a;
          const nb = typeof b === 'number' ? b : b === null ? 0 : b;
          let cmp: number;
          if (typeof na === 'number' && typeof nb === 'number') cmp = na - nb;
          else cmp = String(na).toLowerCase().localeCompare(String(nb).toLowerCase());
          switch (n.op) {
            case '=': return cmp === 0;
            case '<>': return cmp !== 0;
            case '<': return cmp < 0;
            case '>': return cmp > 0;
            case '<=': return cmp <= 0;
            default: return cmp >= 0;
          }
        }
        const x = toNum(a);
        const y = toNum(b);
        if (isErr(x)) return x;
        if (isErr(y)) return y;
        switch (n.op) {
          case '+': return x + y;
          case '-': return x - y;
          case '*': return x * y;
          case '/': return y === 0 ? { err: '#DIV/0!' } : x / y;
          case '^': return Math.pow(x, y);
        }
        return { err: '#ERROR!' };
      }
      case 'fn': return callFn(n.name, n.args);
    }
  }

  function collectNums(args: Node[]): number[] | Err {
    const nums: number[] = [];
    for (const a of args) {
      const v = ev(a);
      if (typeof v === 'object' && v !== null && 'range' in v) {
        for (const x of v.range) {
          if (isErr(x)) return x;
          if (typeof x === 'number') nums.push(x);
        }
      } else {
        if (isErr(v)) return v;
        if (v === null) continue;
        const x = toNum(v);
        if (isErr(x)) {
          if (a.k === 'ref') continue; // text in a referenced cell is ignored
          return x;
        }
        nums.push(x);
      }
    }
    return nums;
  }

  function callFn(name: string, args: Node[]): Value {
    switch (name) {
      case 'SUM': {
        const ns = collectNums(args);
        return isErr(ns) ? ns : ns.reduce((s, x) => s + x, 0);
      }
      case 'AVERAGE': {
        const ns = collectNums(args);
        if (isErr(ns)) return ns;
        return ns.length ? ns.reduce((s, x) => s + x, 0) / ns.length : { err: '#DIV/0!' };
      }
      case 'COUNT': {
        let count = 0;
        for (const a of args) {
          const v = ev(a);
          if (typeof v === 'object' && v !== null && 'range' in v) count += v.range.filter((x) => typeof x === 'number').length;
          else if (typeof v === 'number') count++;
          else if (typeof v === 'string' && a.k === 'lit' && NUM_RE.test(v.trim())) count++;
        }
        return count;
      }
      case 'MIN':
      case 'MAX': {
        const ns = collectNums(args);
        if (isErr(ns)) return ns;
        if (!ns.length) return 0;
        return name === 'MIN' ? Math.min(...ns) : Math.max(...ns);
      }
      default:
        return { err: '#NAME?' };
    }
  }

  return cellValue;
}

export function fmtNumber(n: number): string {
  if (!Number.isFinite(n)) return '#NUM!';
  if (Number.isInteger(n)) return String(n);
  return String(parseFloat(n.toPrecision(12)));
}

export function fmtScalar(v: Scalar): string {
  if (v === null) return '';
  if (isErr(v)) return v.err;
  if (typeof v === 'number') return fmtNumber(v);
  if (typeof v === 'boolean') return v ? 'TRUE' : 'FALSE';
  return v;
}

// Display text for a cell: literals show exactly what was typed, formulas show results.
export function displayValue(raw: string | undefined, value: Scalar): string {
  if (raw === undefined || raw === '') return '';
  if (!isFormula(raw)) return raw === '=' ? '#ERROR!' : raw.startsWith("'") ? raw.slice(1) : raw;
  return fmtScalar(value);
}

// ---------- reference rewriting ----------
export function refText(r: Ref): string {
  return `${r.absC ? '$' : ''}${colName(r.col)}${r.absR ? '$' : ''}${r.row + 1}`;
}

type RangeMap = (a: Ref, b: Ref) => [Ref, Ref] | null;

/**
 * Rewrites references in a formula. `single` maps a lone reference (null => #REF!),
 * `range` maps both ends of an A1:B2 range (null => #REF!). Returns null if any
 * reference became invalid and `wholeOnInvalid` is set.
 */
export function rewriteFormula(
  raw: string,
  single: (r: Ref) => Ref | null,
  range: RangeMap,
  wholeOnInvalid = false,
): string {
  if (!isFormula(raw)) return raw;
  const body = raw.slice(1);
  const toks = tokenize(body);
  if (!toks) return raw;
  let out = '';
  let pos = 0;
  let invalid = false;
  for (let i = 0; i < toks.length; i++) {
    const t = toks[i];
    if (t.t !== 'ref') continue;
    const colon = toks[i + 1];
    const t2 = toks[i + 2];
    if (colon?.t === ':' && t2?.t === 'ref') {
      const mapped = range(t.v, t2.v);
      out += body.slice(pos, t.s);
      if (mapped) {
        const same = mapped[0] === t.v && mapped[1] === t2.v;
        out += same ? body.slice(t.s, t2.e) : `${refText(mapped[0])}:${refText(mapped[1])}`;
      } else {
        out += '#REF!';
        invalid = true;
      }
      pos = t2.e;
      i += 2;
    } else {
      const mapped = single(t.v);
      out += body.slice(pos, t.s);
      if (mapped) out += mapped === t.v ? body.slice(t.s, t.e) : refText(mapped);
      else {
        out += '#REF!';
        invalid = true;
      }
      pos = t.e;
    }
  }
  out += body.slice(pos);
  if (invalid && wholeOnInvalid) return '=#REF!';
  return '=' + out;
}

/** Copy semantics: relative parts move by (dr, dc); out-of-bounds => "=#REF!". */
export function offsetFormula(raw: string, dr: number, dc: number): string {
  if (!dr && !dc) return raw;
  const move = (r: Ref): Ref | null => {
    const n = { ...r, row: r.absR ? r.row : r.row + dr, col: r.absC ? r.col : r.col + dc };
    return validRef(n) ? n : null;
  };
  return rewriteFormula(
    raw,
    move,
    (a, b) => {
      const x = move(a);
      const y = move(b);
      return x && y ? [x, y] : null;
    },
    true,
  );
}

/** Structural change along an axis: insert (count>0) or delete one line at `at`. */
export function shiftFormula(raw: string, axis: 'row' | 'col', at: number, insert: boolean): string {
  const get = (r: Ref) => (axis === 'row' ? r.row : r.col);
  const set = (r: Ref, v: number): Ref => (axis === 'row' ? { ...r, row: v } : { ...r, col: v });
  return rewriteFormula(
    raw,
    (r) => {
      const i = get(r);
      if (insert) return i >= at ? set(r, i + 1) : r;
      if (i === at) return null;
      return i > at ? set(r, i - 1) : r;
    },
    (a, b) => {
      const lo = Math.min(get(a), get(b));
      const hi = Math.max(get(a), get(b));
      const [ra, rb] = get(a) <= get(b) ? [a, b] : [b, a];
      if (insert) {
        const nlo = lo >= at ? lo + 1 : lo;
        const nhi = hi >= at ? hi + 1 : hi;
        if (nlo === lo && nhi === hi) return [a, b];
        return [set(ra, nlo), set(rb, nhi)];
      }
      if (lo === at && hi === at) return null;
      const nlo = lo > at ? lo - 1 : lo;
      const nhi = hi >= at ? hi - 1 : hi;
      if (nlo === lo && nhi === hi) return [a, b];
      return [set(ra, nlo), set(rb, nhi)];
    },
  );
}

/** Cut/move: references inside the source rectangle follow the moved cells. */
export function moveRefsFormula(
  raw: string,
  rect: { r1: number; c1: number; r2: number; c2: number },
  dr: number,
  dc: number,
): string {
  const inside = (r: Ref) => r.row >= rect.r1 && r.row <= rect.r2 && r.col >= rect.c1 && r.col <= rect.c2;
  const mv = (r: Ref): Ref => ({ ...r, row: r.row + dr, col: r.col + dc });
  return rewriteFormula(
    raw,
    (r) => (inside(r) ? mv(r) : r),
    (a, b) => (inside(a) && inside(b) ? [mv(a), mv(b)] : [a, b]),
  );
}
