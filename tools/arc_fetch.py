#!/usr/bin/env python3
"""Crawl ARC-Bench competition tasks into structured local data.

Reads your session cookie (never written to disk), enumerates every task in a
competition, and for each task saves:

  tasks/<NNN>-<slug>/
    requirement.txt     raw requirement API response (JSON)
    requirements.md     requirements_markdown extracted
    requirements.yaml   requirements_yaml extracted
    prerequisites.md    prerequisites_markdown (only if non-empty)
    tests.txt           raw tests API response (JSON)
    tests/              every test file unpacked (spec files, helpers.ts, ...)
    assets/             binary files referenced as assets/... in the spec
    reference/          images referenced as ./reference/... in the spec
    public_downloads/   files listed in tests payload public_downloads (if any)
    meta.json           fetch metadata

Credential input (pick one):
  --cookie 'arcbench_session=...; arc_api_sticky=...'
  --cookie-file path/to/curl.txt   (a pasted curl command or raw cookie header)
  env ARCBENCH_COOKIE

Usage:
  python3 tools/arc_fetch.py                          # crawl all tasks
  python3 tools/arc_fetch.py --task arc-bench-web--12306
  python3 tools/arc_fetch.py --no-binaries            # json+text only

  python3 tools/arc_fetch.py competitions             # list competitions
  python3 tools/arc_fetch.py submissions [-c COMP]    # list submissions + scores
  python3 tools/arc_fetch.py run SUBMISSION_ID REQUIREMENT_ID [--wait]
                                                      # trigger a test run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://arc-bench.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
CATALOG = "competition"

# references in spec markdown / test sources, e.g. ./reference/homepage.png,
# assets/logo.png, assets/icons/foo.svg
REF_RE = re.compile(
    r"(?:\.\/)?(reference|assets)\/([A-Za-z0-9_\-\.\/]+\.[A-Za-z0-9]{2,5})")


class ApiError(Exception):
    pass


def extract_cookie(text: str) -> str:
    """Accept a raw cookie string, a `cookie:` header line, or a pasted curl."""
    text = text.strip()
    m = re.search(r"(?:^|\s)-b\s+'([^']+)'", text) or \
        re.search(r'(?:^|\s)-b\s+"([^"]+)"', text) or \
        re.search(r"(?i)cookie:\s*([^\n']+)", text)
    if m:
        return m.group(1).strip()
    return text


def resolve_cookie(args) -> str:
    raw = args.cookie or os.environ.get("ARCBENCH_COOKIE")
    if args.cookie_file:
        raw = Path(args.cookie_file).read_text()
    if not raw:
        sys.exit("error: no credentials. Pass --cookie, --cookie-file, "
                 "or set ARCBENCH_COOKIE.")
    cookie = extract_cookie(raw)
    if "arcbench_session" not in cookie:
        print("warning: cookie string does not contain 'arcbench_session'; "
              "auth will probably fail.", file=sys.stderr)
    return cookie


def join_base(base_url: str, name: str) -> str:
    """Insert a filename before the query string of a *_base_url."""
    base_url = base_url.replace("http://", "https://", 1)
    if "?" in base_url:
        path, qs = base_url.split("?", 1)
        return f"{path}/{name}?{qs}"
    return f"{base_url}/{name}"


def request(url: str, cookie: str, retries: int = 3) -> tuple[bytes, str]:
    url = url.replace("http://", "https://", 1)
    headers = {
        "accept": "*/*",
        "content-type": "application/json",
        "cookie": cookie,
        "referer": f"{BASE_URL}/competitions",
        "user-agent": UA,
    }
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=headers)) as resp:
                return resp.read(), resp.headers.get("content-type", "")
        except urllib.error.HTTPError as e:
            body = e.read()[:300]
            if e.code in (401, 403):
                raise ApiError(
                    f"{e.code} on {url} — session cookie is missing/expired. "
                    f"Copy a fresh one from DevTools (Application > Cookies).")
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise ApiError(f"{e.code} on {url}: {body[:200]!r}")
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise ApiError(f"network error on {url}: {e.reason}")
    raise ApiError(f"unreachable: {url}")


def get_json(url: str, cookie: str):
    body, ctype = request(url, cookie)
    if "json" not in ctype:
        raise ApiError(f"non-JSON response from {url} ({ctype})")
    return json.loads(body)


def post_multipart(url: str, fields: dict, cookie: str) -> dict:
    boundary = f"----arcFetch{int(time.time() * 1000):x}"
    parts = []
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; "
            f'name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "accept": "*/*",
        "content-type": f"multipart/form-data; boundary={boundary}",
        "cookie": cookie,
        "origin": BASE_URL,
        "referer": f"{BASE_URL}/competitions",
        "user-agent": UA,
    })
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read()[:300]
        if e.code in (401, 403):
            raise ApiError(f"{e.code} on {url} — session cookie expired.")
        raise ApiError(f"{e.code} on {url}: {detail!r}")


def safe_path(root: Path, rel: str) -> Path:
    p = (root / rel).resolve()
    if root.resolve() not in p.parents and p != root.resolve():
        raise ApiError(f"unsafe path in payload: {rel!r}")
    return p


def write(root: Path, rel: str, data, binary=False):
    p = safe_path(root, rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    if binary:
        p.write_bytes(data)
    else:
        p.write_text(data, encoding="utf-8")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "task"


def task_dir_name(task: dict, out_root: Path) -> str:
    num = re.sub(r"\D", "", task.get("display_id", "")) or "000"
    suffix = task["id"].split("--")[-1]
    existing = sorted(out_root.glob(f"{num}-*/"))
    if existing:
        return existing[0].name
    return f"{num}-{slugify(suffix)}"


def collect_binaries(*texts: str) -> dict[str, set[str]]:
    """Return {'reference': {names}, 'assets': {names}} found in texts."""
    found: dict[str, set[str]] = {"reference": set(), "assets": set()}
    for text in texts:
        for kind, name in REF_RE.findall(text or ""):
            if ".." not in name and not name.startswith("/"):
                found[kind].add(name)
    return found


def fetch_task(task: dict, comp_id: str, cookie: str,
               out_root: Path, with_binaries: bool):
    tid = task["id"]
    d = out_root / task_dir_name(task, out_root)
    d.mkdir(parents=True, exist_ok=True)
    print(f"[{task.get('display_id', '?')}] {tid} -> {d}")

    req_url = f"{BASE_URL}/api/requirements/{tid}?catalog={CATALOG}"
    req = get_json(req_url, cookie)
    write(d, "requirement.txt", json.dumps(req, indent=4, ensure_ascii=False))
    write(d, "requirements.md", req.get("requirements_markdown") or "")
    if req.get("requirements_yaml"):
        write(d, "requirements.yaml", req["requirements_yaml"])
    if req.get("prerequisites_markdown"):
        write(d, "prerequisites.md", req["prerequisites_markdown"])

    tests_url = f"{BASE_URL}/api/requirements/{tid}/tests?catalog={CATALOG}"
    tests = get_json(tests_url, cookie)
    write(d, "tests.txt", json.dumps(tests, indent=4, ensure_ascii=False))

    test_texts = []
    for f in tests.get("files") or []:
        write(d, f"tests/{f['path']}", f["content"])
        test_texts.append(f["content"])

    if with_binaries:
        bins = collect_binaries(
            req.get("requirements_markdown"),
            req.get("prerequisites_markdown"),
            *test_texts,
        )
        bases = {
            "reference": req.get("references_base_url"),
            "assets": req.get("assets_base_url"),
        }
        for kind, names in bins.items():
            base = bases.get(kind)
            if not base:
                continue
            for name in sorted(names):
                dest = safe_path(d, f"{kind}/{name}")
                if dest.exists():
                    continue
                url = join_base(base, name)
                try:
                    data, _ = request(url, cookie)
                except ApiError as e:
                    print(f"  ! {kind}/{name}: {e}")
                    continue
                write(d, f"{kind}/{name}", data, binary=True)
                print(f"  {kind}/{name} ({len(data)} B)")
                time.sleep(0.15)

    for item in tests.get("public_downloads") or []:
        url = item if isinstance(item, str) else item.get("url", "")
        name = item if isinstance(item, str) else item.get("path", "download")
        if not url:
            continue
        if url.startswith("/"):
            url = BASE_URL + url
        try:
            data, _ = request(url, cookie)
            write(d, f"public_downloads/{safe_name(name)}", data, binary=True)
        except ApiError as e:
            print(f"  ! public_download {name}: {e}")

    write(d, "meta.json", json.dumps({
        "id": tid,
        "display_id": task.get("display_id"),
        "competition": comp_id,
        "title": task.get("title"),
        "test_runner": task.get("test_runner"),
        "total_tests": task.get("total_tests"),
        "test_files": len(tests.get("files") or []),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }, indent=2, ensure_ascii=False))
    time.sleep(0.3)


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-\.]", "_", name.split("/")[-1]) or "file"


RUN_TERMINAL = {"PASSED", "FAILED", "ERROR", "CANCELLED", "TIMEOUT", "SUCCESS"}


def cmd_crawl(args, cookie):
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    comp = get_json(f"{BASE_URL}/api/competitions/{args.competition}", cookie)
    tasks = comp.get("tasks") or []
    if args.task:
        tasks = [t for t in tasks if t["id"] == args.task] or \
                [{"id": args.task, "display_id": "TASK-???"}]
    print(f"competition {comp['id']}: {len(tasks)} task(s)")

    manifest = {"competition": comp, "fetched_at":
                time.strftime("%Y-%m-%dT%H:%M:%S%z"), "dirs": {}}
    for t in tasks:
        fetch_task(t, args.competition, cookie, out_root,
                   with_binaries=not args.no_binaries)
        manifest["dirs"][t["id"]] = task_dir_name(t, out_root)
    write(out_root, "manifest.json", json.dumps(manifest, indent=2,
                                               ensure_ascii=False))
    print(f"done -> {out_root}/manifest.json")


def cmd_competitions(args, cookie):
    comps = get_json(f"{BASE_URL}/api/competitions", cookie)
    for c in comps:
        print(f"{c['id']:<24} {c.get('status','?'):<8} "
              f"tasks={c.get('task_count','?'):<3} {c.get('title','')}")


def print_submission(s: dict):
    print(f"\n{s['id']}  {s.get('display_name','')}  "
          f"model={s.get('model_name','')}  "
          f"avg_pass={s.get('average_test_pass_rate')}%  "
          f"selected={s.get('is_selected_score')}")
    for ts in s.get("task_scores") or []:
        print(f"  {ts.get('status','?'):<8} {ts.get('task_id'):<36} "
              f"pass={ts.get('test_pass_rate')}% "
              f"feat={ts.get('feature_implementation_rate')}% "
              f"run={ts.get('run_id')}")


def cmd_submissions(args, cookie):
    subs = get_json(
        f"{BASE_URL}/api/competitions/{args.competition}/submissions", cookie)
    if args.out:
        Path(args.out).write_text(json.dumps(subs, indent=2,
                                             ensure_ascii=False))
        print(f"saved -> {args.out}")
    if args.json:
        print(json.dumps(subs, indent=2, ensure_ascii=False))
    else:
        for s in subs:
            print_submission(s)
        print(f"\n{len(subs)} submission(s)")


def find_score(subs, submission_id: str, run_id: str):
    for s in subs:
        if s.get("id") != submission_id:
            continue
        for ts in s.get("task_scores") or []:
            if ts.get("run_id") == run_id:
                return s, ts
    return None, None


def cmd_run(args, cookie):
    resp = post_multipart(f"{BASE_URL}/api/runs", {
        "submission_id": args.submission_id,
        "requirement_id": args.requirement_id,
    }, cookie)
    run = resp.get("run") or resp
    print(f"run {run.get('id')}  task={run.get('requirement_id')}  "
          f"status={run.get('status')}")
    if not args.wait:
        return
    deadline = time.time() + args.timeout
    comp_id = run.get("competition_id") or args.competition
    while time.time() < deadline:
        time.sleep(args.interval)
        subs = get_json(
            f"{BASE_URL}/api/competitions/{comp_id}/submissions", cookie)
        s, ts = find_score(subs, run["submission_id"], run["id"])
        status = (ts or {}).get("status")
        print(f"  ... status={status or 'PENDING'}")
        if status in RUN_TERMINAL:
            if s:
                print_submission(s)
            return
    print(f"timed out after {args.timeout}s; run id {run.get('id')}")


def main():
    commands = {"crawl", "competitions", "submissions", "run"}
    argv = sys.argv[1:]
    if not argv or argv[0] not in commands:
        argv = ["crawl"] + argv

    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--cookie", help="cookie header value")
    common.add_argument("--cookie-file",
                        help="file with cookie or pasted curl")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("crawl", parents=[common],
                       help="download all task data (default)")
    p.add_argument("-c", "--competition", default="arc-bench-web")
    p.add_argument("--task", help="fetch a single task id")
    p.add_argument("--out", default="tasks")
    p.add_argument("--no-binaries", action="store_true",
                   help="skip assets/ and reference/ downloads")

    sub.add_parser("competitions", parents=[common],
                   help="list competitions")

    p = sub.add_parser("submissions", parents=[common],
                       help="list submissions and task scores")
    p.add_argument("-c", "--competition", default="arc-bench-web")
    p.add_argument("--json", action="store_true", help="dump raw JSON")
    p.add_argument("--out", help="also save raw JSON to a file")

    p = sub.add_parser("run", parents=[common],
                       help="trigger a test run for a submission+task")
    p.add_argument("submission_id")
    p.add_argument("requirement_id")
    p.add_argument("-c", "--competition", default="arc-bench-web",
                   help="used for --wait polling if run omits it")
    p.add_argument("--wait", action="store_true",
                   help="poll submissions until the run finishes")
    p.add_argument("--interval", type=int, default=15)
    p.add_argument("--timeout", type=int, default=1800)

    args = ap.parse_args(argv)
    cookie = resolve_cookie(args)
    {"crawl": cmd_crawl, "competitions": cmd_competitions,
     "submissions": cmd_submissions, "run": cmd_run}[args.cmd](args, cookie)


if __name__ == "__main__":
    try:
        main()
    except ApiError as e:
        sys.exit(f"error: {e}")
