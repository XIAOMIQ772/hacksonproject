// Minimal content-addressed version model: each commit stores a full tree snapshot.
const { sha } = require('./store');

function makeCommit(s, { parents = [], message, authorId, tree, time }) {
  const t = time || new Date().toISOString();
  const id = sha(JSON.stringify({ parents, message, authorId, tree, t, n: s.seq++ }));
  s.commits[id] = { sha: id, parents, message, authorId, time: t, tree };
  return id;
}

function ancestors(s, start) {
  const seen = new Set();
  const stack = [start];
  while (stack.length) {
    const c = stack.pop();
    if (!c || seen.has(c) || !s.commits[c]) continue;
    seen.add(c);
    stack.push(...s.commits[c].parents);
  }
  return seen;
}

function log(s, head, path) {
  const list = [...ancestors(s, head)].map((id) => s.commits[id]);
  list.sort((a, b) => (a.time < b.time ? 1 : a.time > b.time ? -1 : 0));
  if (!path) return list;
  return list.filter((c) => {
    const parent = c.parents[0] ? s.commits[c.parents[0]].tree : {};
    return c.tree[path] !== parent[path];
  });
}

function mergeBase(s, a, b) {
  const aa = ancestors(s, a);
  const queue = [b];
  const seen = new Set();
  while (queue.length) {
    const c = queue.shift();
    if (!c || seen.has(c)) continue;
    seen.add(c);
    if (aa.has(c)) return c;
    queue.push(...(s.commits[c]?.parents || []));
  }
  return null;
}

function lineDiff(oldText, newText) {
  const split = (t) => (t === undefined || t === '' ? [] : t.replace(/\n$/, '').split('\n'));
  const a = split(oldText);
  const b = split(newText);
  const n = a.length;
  const m = b.length;
  const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = [];
  let i = 0;
  let j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && a[i] === b[j]) { out.push({ type: 'ctx', oldNo: i + 1, newNo: j + 1, text: a[i] }); i++; j++; }
    else if (i < n && (j >= m || dp[i + 1][j] >= dp[i][j + 1])) { out.push({ type: 'del', oldNo: i + 1, text: a[i] }); i++; }
    else { out.push({ type: 'add', newNo: j + 1, text: b[j] }); j++; }
  }
  return out;
}

function diffTrees(oldTree = {}, newTree = {}) {
  const paths = [...new Set([...Object.keys(oldTree), ...Object.keys(newTree)])].sort();
  const files = [];
  for (const p of paths) {
    if (oldTree[p] === newTree[p]) continue;
    const lines = lineDiff(oldTree[p], newTree[p]);
    files.push({
      path: p,
      status: oldTree[p] === undefined ? 'added' : newTree[p] === undefined ? 'deleted' : 'modified',
      additions: lines.filter((l) => l.type === 'add').length,
      deletions: lines.filter((l) => l.type === 'del').length,
      lines,
    });
  }
  return {
    files,
    additions: files.reduce((t, f) => t + f.additions, 0),
    deletions: files.reduce((t, f) => t + f.deletions, 0),
  };
}

// File-level three-way merge; a path changed differently on both sides is a conflict.
function mergeTrees(base = {}, ours = {}, theirs = {}) {
  const tree = { ...ours };
  const conflicts = [];
  for (const p of new Set([...Object.keys(base), ...Object.keys(theirs)])) {
    if (theirs[p] === base[p]) continue;
    if (ours[p] === base[p] || ours[p] === theirs[p]) {
      if (theirs[p] === undefined) delete tree[p];
      else tree[p] = theirs[p];
    } else conflicts.push(p);
  }
  return { tree, conflicts };
}

function listDir(tree, dir) {
  const prefix = dir ? `${dir}/` : '';
  const entries = new Map();
  for (const p of Object.keys(tree)) {
    if (!p.startsWith(prefix)) continue;
    const rest = p.slice(prefix.length);
    const [name, ...more] = rest.split('/');
    const type = more.length ? 'dir' : 'file';
    if (!entries.has(name) || type === 'dir') entries.set(name, { name, type, path: prefix + name });
  }
  return [...entries.values()].sort((x, y) => (x.type === y.type ? x.name.localeCompare(y.name) : x.type === 'dir' ? -1 : 1));
}

function isDir(tree, dir) {
  return Object.keys(tree).some((p) => p.startsWith(`${dir}/`));
}

module.exports = { makeCommit, ancestors, log, mergeBase, lineDiff, diffTrees, mergeTrees, listDir, isDir };
