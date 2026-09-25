---
name: arcbench-tdd
description: Test-driven development for one ARC-Bench requirement. Use when a worker agent receives a single requirement and must write its Playwright test before changing product code, then make that test pass and report the result through the ARC-Bench runtime signals.
---

# ARC Bench TDD

Apply this skill to exactly one requirement assigned by the lead agent. Do not spawn subagents, do not open `requirements.yaml`, and do not implement other requirements.

The app is React + Express. Product code is `frontend/src` and `backend/src`. Keep behavior that already works. Open pages with a relative path such as `page.goto('/')`. The test runner sets the base URL. Do not hardcode a port.

From the project root, the only test command is:

```bash
bash backend/scripts/run-spec.sh REQ-ID
```

That script installs dependencies when they are missing, rebuilds the frontend when source is newer than `frontend/dist`, seeds the database, starts the server, runs this spec, and stops the server. Do not run `npm install`, `npm run build`, `npm run start`, or `npx playwright` yourself. Do not switch browsers.

Progress is reported with the runtime signal script. From the project root:

```bash
python .codex/skills/arcbench-runtime-signals/scripts/arc_signal.py implement-started --node-id REQ-ID --project-dir .
python .codex/skills/arcbench-runtime-signals/scripts/arc_signal.py test-passed --node-id REQ-ID --project-dir .
python .codex/skills/arcbench-runtime-signals/scripts/arc_signal.py test-failed --node-id REQ-ID --message "short reason" --project-dir .
python .codex/skills/arcbench-runtime-signals/scripts/arc_signal.py implement-done --node-id REQ-ID --project-dir .
```

## Red

1. Run `implement-started` for this requirement id.
2. Add one short Playwright file, `backend/test-e2e/<REQ-ID>.spec.js`. Do not add helpers or extra cases.
3. Do not search for or open an official test suite. The test you write is the development contract.
4. Assert every quoted or backticked string in the requirement description and in every scenario step. Also assert the visible labels from the reference image that the lead passed for this requirement. Those strings are the text the page must show. When the sentence names a role, put the string on that role's accessible name: a heading for a heading, a form for a form. A control the user activates must be a button when the requirement says button. A link is not a substitute for a named button. Also perform the scenario action, such as clicking the named control.
5. Keep the file to a single test: open the page, do the action, then `expect` the required text. Do not edit product code in this step. Do not start the server in this step.

## Green

1. Change only the product code this requirement needs. Patch existing files. Do not replace a page that already implements an earlier requirement.
2. Read only the files you will edit. Do not print the whole tree, other spec files, `run-spec.sh`, `package.json`, `backend/src/app.js`, `backend/src/index.js`, or git history.
3. Run `bash backend/scripts/run-spec.sh REQ-ID` once.
4. If the script prints `playwright exit 0`, run `test-passed` and then `implement-done` immediately. Do not run the script again.
5. If it fails, fix the product code and run the same command again. Do this at most twice. Do not weaken the assertions. Then run `test-passed` or `test-failed`, and `implement-done`.
6. Do not leave a server running. The script stops it.
7. Your last message to the lead is four lines: the requirement id, the `playwright exit` number, the files you changed, and passed or failed. Do not paste code or logs.
