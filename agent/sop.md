# Working procedure: test-driven development

## For every requirement group
1. Contract. From the card, list for each atomic requirement: the page or dialog it lives on, every quoted string with its role (button, link, heading, tab, menuitem, textbox, combobox, option, checkbox, dialog, alert, status, gridcell), the validation rules with their exact messages, and what must still hold after a reload. Keep this list short; it is your checklist.
2. Red. Write one end-to-end test per scenario in `backend/test-e2e/<group>.spec.ts`, asserting the checklist items, the failure paths and the state after `page.reload()`. Run `check` with the group pattern and confirm the new tests fail because the feature is missing, not because of a mistake in the test.
3. Green. Implement the smallest change that makes the tests pass, a scenario or a small batch at a time: backend tables, validation, permission checks and atomic writes; frontend elements with the exact names and roles. Re-run `check` with the pattern after each batch. Read the failure lines (pending locator and source line) and fix the app, not the test, unless the test contradicts the requirement.
4. Refactor. With the tests green, remove duplication and move repeated UI into the shared components listed in PLAN.md. Re-run `check` with the pattern.
5. Review and regress. Walk the checklist against the code once: every quoted string present with its role, no second element with the same name and role in that view, errors next to their controls, data persisted on the server. Delete any temporary debugging tests you created. Run `check` without a pattern so earlier groups stay green, then call `done`.

## Economy
- Tool calls in one reply that only read (files, images, read-only shell commands such as grep, ls, cat, git diff) run concurrently: request all the independent reads you need in a single reply instead of one per step. The task already contains a code map and the files your work owns; do not re-read them.
- Make related changes to several files with one `apply` call instead of one write or edit per step.
- Reasoning starts low. Use `set_reasoning` to raise it for a design decision or a failure you do not understand, and lower it again for routine edits.
- Every message you send is re-read on each later step. Keep replies short: no restating the requirements, no long plans beyond the checklist.
- Do not re-read files you wrote in this session or files already shown in the task. Read other files once, with offset/limit when large, and search with `grep -n` instead of reading whole directories.
- Change existing files with `edit` on a small unique snippet. Use `write` only for new files or full rewrites of small files.
- Keep bash output small (`| head`, `| tail`, `grep`). Do not install packages unless the requirement cannot be met with the existing dependencies.
- Batch related changes before running `check`; do not start servers or browsers yourself.
- Stop once the checklist is covered; do not polish styling or add features the requirements do not ask for.
