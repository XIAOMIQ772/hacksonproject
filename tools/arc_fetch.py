#!/usr/bin/env python3
"""ARC-Bench client: tasks, login, leaderboard, upload, run, and results.

Credential input (pick one):
  --cookie 'arcbench_session=...; arc_api_sticky=...'
  --cookie-file path/to/curl.txt   (a pasted curl command or raw cookie header)
  env ARCBENCH_COOKIE
  --email / --password, or ARCBENCH_EMAIL / ARCBENCH_PASSWORD
      (POST /api/auth/login, then use the Set-Cookie session)

Usage:
  python3 tools/arc_fetch.py login --email you@example.com
  python3 tools/arc_fetch.py competitions
  python3 tools/arc_fetch.py leaderboard -c arc-bench-lite [--task bookstack]
  python3 tools/arc_fetch.py upload agent.zip -c arc-bench-lite --name "my agent"
  python3 tools/arc_fetch.py run SUBMISSION_ID REQUIREMENT_ID [--wait]
  python3 tools/arc_fetch.py result RUN_ID
  python3 tools/arc_fetch.py                          # crawl all tasks
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
from urllib.parse import urlencode
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
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def load_dotenv() -> None:
    """Fill unset variables from the repo .env. Does not override the environment."""
    roots = [Path.cwd(), Path(__file__).resolve().parent.parent]
    seen: set[Path] = set()
    for root in roots:
        path = root / ".env"
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


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
    if raw:
        cookie = extract_cookie(raw)
        if "arcbench_session" not in cookie:
            print("warning: cookie string does not contain 'arcbench_session'; "
                  "auth will probably fail.", file=sys.stderr)
        return cookie
    email = args.email or os.environ.get("ARCBENCH_EMAIL")
    password = args.password or os.environ.get("ARCBENCH_PASSWORD")
    if email and password:
        user, cookie = login(email, password)
        who = user.get("email") or user.get("username") or "ok"
        print(f"logged in as {who}", file=sys.stderr)
        return cookie
    sys.exit("error: no credentials. Pass --cookie, --cookie-file, "
             "ARCBENCH_COOKIE, or --email and --password.")


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
                    urllib.request.Request(url, headers=headers), timeout=30) as resp:
                return resp.read(), resp.headers.get("content-type", "")
        except urllib.error.HTTPError as e:
            body = e.read()[:300]
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise ApiError(f"{e.code} on {url}: {body.decode('utf-8', 'replace')}", status=e.code)
        except OSError as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise ApiError(f"network error on {url}: {getattr(e, 'reason', e)}")
    raise ApiError(f"unreachable: {url}")


def get_json(url: str, cookie: str):
    body, ctype = request(url, cookie)
    if "json" not in ctype:
        raise ApiError(f"non-JSON response from {url} ({ctype})")
    return json.loads(body)


def encode_multipart(fields: dict, files: dict | None = None) -> tuple[bytes, str]:
    """files: {field: (filename, data, content_type)}."""
    boundary = f"----arcFetch{int(time.time() * 1000):x}{os.getpid()}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; "
            f'name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, (filename, data, content_type) in (files or {}).items():
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; "
            f'name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n".encode()
            + data + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _open(req: urllib.request.Request):
    try:
        return urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        raise ApiError(f"{e.code} on {req.full_url}: {detail}", status=e.code)
    except OSError as e:
        raise ApiError(f"network error on {req.full_url}: {getattr(e, 'reason', e)}")


def _json_headers(cookie: str | None, content_type: str | None = None) -> dict:
    headers = {
        "accept": "*/*",
        "origin": BASE_URL,
        "referer": f"{BASE_URL}/competitions",
        "user-agent": UA,
    }
    if content_type:
        headers["content-type"] = content_type
    if cookie:
        headers["cookie"] = cookie
    return headers


def post_multipart(url: str, fields: dict, cookie: str,
                   files: dict | None = None) -> dict:
    body, content_type = encode_multipart(fields, files)
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers=_json_headers(cookie, content_type))
    with _open(req) as resp:
        return json.loads(resp.read())


def post_json(url: str, payload: dict, cookie: str | None = None) -> tuple[dict, str]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers=_json_headers(cookie, "application/json"))
    with _open(req) as resp:
        cookies = []
        for raw in resp.headers.get_all("Set-Cookie") or []:
            pair = raw.split(";", 1)[0].strip()
            if "=" in pair:
                cookies.append(pair)
        return json.loads(resp.read()), "; ".join(cookies)


def post_empty(url: str, cookie: str) -> dict:
    """POST with an empty JSON body, matching /api/runs/{id}/start."""
    req = urllib.request.Request(
        url, data=b"", method="POST",
        headers=_json_headers(cookie, "application/json"))
    with _open(req) as resp:
        return json.loads(resp.read())


def login(email: str, password: str) -> tuple[dict, str]:
    body, cookie = post_json(f"{BASE_URL}/api/auth/login",
                             {"email": email, "password": password})
    user = body.get("user") or body
    if not cookie:
        raise ApiError("login returned no Set-Cookie session")
    return user, cookie


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
    tests_available = True
    try:
        tests = get_json(tests_url, cookie)
    except ApiError as error:
        if error.status != 404:
            raise
        # Official tasks expose requirements but keep their evaluator private.
        tests_available = False
        tests = {"files": [], "public_downloads": []}
        print("  tests unavailable (HTTP 404); saved requirements without evaluator files")
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
        "tests_available": tests_available,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }, indent=2, ensure_ascii=False))
    time.sleep(0.3)


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-\.]", "_", name.split("/")[-1]) or "file"


RUN_TERMINAL = {"PASSED", "FAILED", "ERROR", "CANCELLED", "TIMEOUT", "SUCCESS",
                "COMPLETED"}


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


def format_competition_lines(comps, detail_for) -> list[str]:
    """Print each competition, then its task ids from the detail endpoint."""
    lines = []
    for comp in comps:
        lines.append(
            f"{comp['id']:<24} {comp.get('status', '?'):<8} "
            f"tasks={comp.get('task_count', '?'):<3} {comp.get('title', '')}"
        )
        try:
            detail = detail_for(comp["id"])
        except ApiError as exc:
            lines.append(f"  tasks_unavailable {exc}")
            continue
        for task in (detail or {}).get("tasks") or []:
            lines.append(
                f"  task {task.get('id', '')} tests={task.get('total_tests', '?')} "
                f"{task.get('title', '')}"
            )
    return lines


def cmd_competitions(args, cookie):
    comps = get_json(f"{BASE_URL}/api/competitions", cookie)

    def detail_for(competition_id: str):
        return get_json(f"{BASE_URL}/api/competitions/{competition_id}", cookie)

    for line in format_competition_lines(comps, detail_for):
        print(line)


def print_submission(s: dict):
    print(f"\n{s['id']}  {s.get('display_name','')}  "
          f"model={s.get('model_name','')}  "
          f"avg_pass={s.get('average_test_pass_rate')}%  "
          f"selected={s.get('is_selected_score')}")
    for ts in s.get("task_scores") or []:
        print(f"  {(ts.get('status') or '?'):<8} {(ts.get('task_id') or ''):<36} "
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


def print_run(run: dict):
    print(f"{run.get('id')}  {run.get('status')}  "
          f"task={run.get('requirement_id')}  "
          f"score={run.get('score')}  "
          f"pass={run.get('passed_count')}/{run.get('failed_count')} failed  "
          f"rate={run.get('test_pass_rate')}  "
          f"tokens={run.get('token_count')}  "
          f"cost={run.get('token_cost_usd')}")
    if run.get("failure_reason"):
        print(f"  failure: {run['failure_reason']}")
    for step in run.get("steps") or []:
        print(f"  {step.get('status', '?'):<10} {step.get('key', ''):<16} "
              f"{step.get('title', '')}")
    tests = run.get("tests") or []
    if tests:
        print(f"  tests: {len(tests)}")


def cmd_login(args, _cookie=None):
    email = args.email or os.environ.get("ARCBENCH_EMAIL")
    password = args.password or os.environ.get("ARCBENCH_PASSWORD")
    if not email or not password:
        sys.exit("error: login needs --email and --password "
                 "(or ARCBENCH_EMAIL / ARCBENCH_PASSWORD)")
    user, cookie = login(email, password)
    who = user.get("username") or user.get("email")
    print(f"logged in as {who}", file=sys.stderr)
    if args.cookie_out:
        path = Path(args.cookie_out)
        path.write_text(cookie + "\n")
        path.chmod(0o600)
        print(f"cookie -> {path}", file=sys.stderr)
        return
    print(cookie)


def cmd_leaderboard(args, cookie):
    params = {"track": args.track, "competition_id": args.competition}
    if args.task:
        params["task_id"] = args.task
    qs = urlencode(params)
    rows = get_json(f"{BASE_URL}/api/competitions/leaderboard?{qs}", cookie)
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return
    for i, row in enumerate(rows, 1):
        task = row.get("task_title") or row.get("task_id") or ""
        print(f"{i:>3}  {row.get('username',''):<20} "
              f"{row.get('model_name',''):<24} "
              f"score={row.get('score')}  "
              f"pass={row.get('pass_rate')}  "
              f"complete={row.get('is_complete')}  {task}")
    print(f"\n{len(rows)} row(s)")


def cmd_upload(args, cookie):
    blob = Path(args.zip).read_bytes()
    official = args.credential_mode == "official_evaluation"
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
    if not official and not api_key:
        sys.exit("error: upload needs --api-key or OPENAI_API_KEY")
    model = args.model or os.environ.get("MODEL") or "deepseek-v4-flash"
    visual = (args.visual_model or (None if official else os.environ.get("VISUAL_MODEL"))
              or "deepseek-v4-flash-vision-exp")
    base_url = args.base_url or (None if official else os.environ.get("OPENAI_BASE_URL")) \
        or "https://api.arc-bench.com/v1"
    fields = {
        "competition_id": args.competition,
        "runtime": args.runtime,
        "catalog": args.catalog,
        "agent_source": "upload",
        "credential_mode": args.credential_mode,
        "display_name": args.name,
        "base_url": base_url,
        "model": model,
        "visual_model": visual,
    }
    if not official:
        fields["api_key"] = api_key
    resp = post_multipart(f"{BASE_URL}/api/submissions", fields, cookie, files={
        "file": (Path(args.zip).name, blob, "application/zip"),
    })
    sub = resp.get("submission") or resp
    print(f"submission {sub.get('id')}  {sub.get('display_name')}  "
          f"file={sub.get('original_filename')}  "
          f"competition={sub.get('competition_id')}  mode={sub.get('credential_mode', args.credential_mode)}")


def cmd_runs(args, cookie):
    params = {}
    if args.requirement:
        params["requirement_id"] = args.requirement
    if args.submission:
        params["submission_id"] = args.submission
    if args.active:
        params["active_only"] = "true"
    url = f"{BASE_URL}/api/runs?{urlencode(params)}"
    runs = get_json(url, cookie)
    if args.competition:
        runs = [run for run in runs if run.get("competition_id") == args.competition]
    if args.json:
        print(json.dumps(runs, indent=2, ensure_ascii=False))
        return
    for run in runs:
        print(f"{run.get('id')}  {run.get('status', '?'):<10} "
              f"{run.get('requirement_id', ''):<36} "
              f"pass={run.get('test_pass_rate')}  "
              f"{run.get('display_name', '')}")
    print(f"\n{len(runs)} run(s)")


def cmd_registration(args, cookie):
    data = get_json(f"{BASE_URL}/api/competitions/{args.competition}/registration", cookie)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    print(f"registered={data.get('registered')}  leader={data.get('is_team_leader')}  "
          f"budget={data.get('remaining_budget_cny')}/{data.get('initial_budget_cny')} CNY")
    print(data.get("message", ""))


def cmd_logs(args, cookie):
    params = {}
    if args.offset is not None:
        params["log_offset"] = args.offset
    if args.after_event_id:
        params["after_event_id"] = args.after_event_id
    data = get_json(f"{BASE_URL}/api/runs/{args.run_id}/logs?{urlencode(params)}", cookie)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    print(data.get("stdout") or "", end="")
    print(data.get("stderr") or "", end="")
    print(f"\nlog_offset={data.get('log_offset')} last_event_id={data.get('last_event_id')}")


def cmd_run_action(args, cookie):
    run = post_empty(f"{BASE_URL}/api/runs/{args.run_id}/{args.action}", cookie)
    print_run(run)


def cmd_run(args, cookie):
    resp = post_multipart(f"{BASE_URL}/api/runs", {
        "submission_id": args.submission_id,
        "requirement_id": args.requirement_id,
    }, cookie)
    run = resp.get("run") or resp
    if not args.no_start:
        run = post_empty(f"{BASE_URL}/api/runs/{run['id']}/start", cookie)
    print_run(run)
    if not args.wait:
        return
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        time.sleep(args.interval)
        run = get_json(f"{BASE_URL}/api/runs/{run['id']}", cookie)
        print(f"  ... status={run.get('status')}")
        if run.get("status") in RUN_TERMINAL:
            print_run(run)
            return
    print(f"timed out after {args.timeout}s; run id {run.get('id')}")


def cmd_result(args, cookie):
    run_id = args.run_id
    run = get_json(f"{BASE_URL}/api/runs/{run_id}", cookie)
    logs = get_json(f"{BASE_URL}/api/runs/{run_id}/logs", cookie)
    trace = get_json(
        f"{BASE_URL}/api/runs/{run_id}/traceability?node_id=__all__", cookie)
    preview = get_json(f"{BASE_URL}/api/runs/{run_id}/preview/status", cookie)
    commits = get_json(f"{BASE_URL}/api/runs/{run_id}/commit-history", cookie)
    files = get_json(f"{BASE_URL}/api/runs/{run_id}/workspace/files", cookie)
    task = get_json(f"{BASE_URL}/api/runs/{run_id}/editable-task", cookie)
    print_run(run)
    print(f"  traceability: interfaces={len(trace.get('interfaces') or [])} "
          f"tests={len(trace.get('tests') or [])}")
    print(f"  preview: available={preview.get('available')} "
          f"url={preview.get('preview_url')} "
          f"error={preview.get('error')}")
    print(f"  commits: {commits.get('availability')} "
          f"n={len(commits.get('commits') or [])}")
    print(f"  workspace files: {len(files.get('files') or [])}")
    md = task.get("requirements_md") or ""
    print(f"  editable task: {len(md)} chars")
    stdout = logs.get("stdout") or ""
    if stdout:
        tail = "\n".join(stdout.splitlines()[-30:])
        print("--- stdout ---")
        print(tail)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for name, payload in (
            ("run", run), ("logs", logs), ("traceability", trace),
            ("preview", preview), ("commits", commits),
            ("files", files), ("task", task),
        ):
            (out / f"{name}.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"saved -> {out}")


def cmd_notifications(args, cookie):
    data = get_json(f"{BASE_URL}/api/notifications", cookie)
    items = data.get("items") or []
    print(f"unread={data.get('unread_count')}  n={len(items)}")
    for item in items:
        print(f"{item.get('created_at', '')}  {item.get('kind', ''):<8} "
              f"{item.get('title', '')}  run={item.get('run_id')}")
        if item.get("body"):
            print(f"  {item['body'][:240]}")


def _self_check() -> None:
    body, ctype = encode_multipart(
        {"competition_id": "arc-bench-lite", "agent_source": "upload"},
        {"file": ("Archive.zip", b"PK\x03\x04", "application/zip")})
    assert b'name="competition_id"' in body
    assert b'filename="Archive.zip"' in body
    assert b"Content-Type: application/zip" in body
    assert b"PK\x03\x04" in body
    assert ctype.startswith("multipart/form-data; boundary=")
    assert "PASSED" in RUN_TERMINAL and "QUEUED" not in RUN_TERMINAL

    def unavailable(_competition_id: str):
        raise ApiError("network error on detail")

    closed = format_competition_lines(
        [{
            "id": "arc-bench-lite",
            "status": "open",
            "task_count": 2,
            "title": "ARC-Bench-Lite",
        }],
        unavailable,
    )
    assert any(line.startswith("arc-bench-lite") for line in closed)
    assert any("tasks_unavailable" in line for line in closed)

    def detail_for(competition_id: str):
        assert competition_id == "arc-bench-lite"
        return {"tasks": [{
            "id": "arc-bench-lite--bookstack",
            "total_tests": 34,
            "title": "BookStack Knowledge Base System",
        }]}

    listed = format_competition_lines(
        [{
            "id": "arc-bench-lite",
            "status": "open",
            "task_count": 2,
            "title": "ARC-Bench-Lite",
        }],
        detail_for,
    )
    assert any(
        "task arc-bench-lite--bookstack" in line and "tests=34" in line
        for line in listed
    )


def main():
    load_dotenv()
    commands = {"crawl", "competitions", "submissions", "run", "login",
                "leaderboard", "upload", "runs", "result", "notifications",
                "registration", "logs", "run-action"}
    argv = sys.argv[1:]
    if argv not in (["-h"], ["--help"]) and (not argv or argv[0] not in commands):
        argv = ["crawl"] + argv

    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--cookie", help="cookie header value")
    common.add_argument("--cookie-file",
                        help="file with cookie or pasted curl")
    common.add_argument("--email", help="login email; or ARCBENCH_EMAIL")
    common.add_argument("--password", help="login password; or ARCBENCH_PASSWORD")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("login", parents=[common],
                       help="POST /api/auth/login and print the session cookie")
    p.add_argument("--cookie-out", help="write the cookie to this file (mode 600)")

    p = sub.add_parser("leaderboard", parents=[common],
                       help="competition ranking")
    p.add_argument("-c", "--competition", default="arc-bench-web")
    p.add_argument("--task", help="task slug, e.g. bookstack")
    p.add_argument("--track", default="all")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("upload", parents=[common],
                       help="upload an agent zip as a submission")
    p.add_argument("zip")
    p.add_argument("-c", "--competition", default="arc-bench-web")
    p.add_argument("--name", required=True, help="display name")
    p.add_argument("--runtime", default="python")
    p.add_argument("--catalog", default="competition")
    p.add_argument("--model", help="default MODEL or deepseek-v4-flash")
    p.add_argument("--visual-model", help="vision model; official mode defaults to deepseek-v4-flash-vision-exp")
    p.add_argument("--base-url", help="default OPENAI_BASE_URL or the arc gateway")
    p.add_argument("--api-key", help="default OPENAI_API_KEY")
    p.add_argument("--credential-mode", choices=["self_funded", "official_evaluation"],
                   default="self_funded", help="official_evaluation uses team budget and is eligible for the leaderboard")

    p = sub.add_parser("runs", parents=[common], help="list runs")
    p.add_argument("--requirement", help="filter by requirement id")
    p.add_argument("--submission", help="filter by submission id")
    p.add_argument("--active", action="store_true", help="only queued/running runs")
    p.add_argument("-c", "--competition", help="filter by competition id")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("registration", parents=[common], help="team registration and official evaluation budget")
    p.add_argument("-c", "--competition", default="hackathon")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("logs", parents=[common], help="read run logs, optionally from a saved offset")
    p.add_argument("run_id")
    p.add_argument("--offset", type=int)
    p.add_argument("--after-event-id")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("run-action", parents=[common], help="control an existing run")
    p.add_argument("run_id")
    p.add_argument("action", choices=["start", "pause", "resume", "continue", "cancel"])

    p = sub.add_parser("result", parents=[common],
                       help="run status, logs, traceability, preview, commits")
    p.add_argument("run_id")
    p.add_argument("--out", help="write the JSON payloads into this directory")

    sub.add_parser("notifications", parents=[common],
                   help="list notifications")

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
                   help="ignored; polling reads GET /api/runs/{id}")
    p.add_argument("--wait", action="store_true",
                   help="poll the run until it finishes")
    p.add_argument("--no-start", action="store_true",
                   help="create the run but do not POST /start")
    p.add_argument("--interval", type=int, default=15)
    p.add_argument("--timeout", type=int, default=1800)

    args = ap.parse_args(argv)
    if args.cmd == "login":
        cmd_login(args)
        return
    cookie = resolve_cookie(args)
    {"crawl": cmd_crawl, "competitions": cmd_competitions,
     "submissions": cmd_submissions, "run": cmd_run,
     "leaderboard": cmd_leaderboard, "upload": cmd_upload,
     "runs": cmd_runs, "result": cmd_result,
     "notifications": cmd_notifications, "registration": cmd_registration,
     "logs": cmd_logs, "run-action": cmd_run_action}[args.cmd](args, cookie)


if __name__ == "__main__":
    try:
        if os.environ.get("ARC_FETCH_SELF_CHECK"):
            _self_check()
            print("ok")
        else:
            main()
    except ApiError as e:
        sys.exit(f"error: {e}")
