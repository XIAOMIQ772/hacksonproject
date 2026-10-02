# Working procedure

## For every feature area of the plan
1. Contract. Get the text of all the area's requirements with one `requirement` call. List for each atomic requirement the page or dialog it lives on, every quoted string with its role (button, link, heading, tab, menuitem, textbox, combobox, option, checkbox, dialog, alert, status, gridcell), the validation rules with their exact messages, and what must still hold after a reload. Keep this list short; it is your checklist.
2. Build in small verified slices. Write the area's end-to-end tests in `backend/test-e2e/<area>.spec.ts` (one per scenario, asserting the checklist items, the failure paths and the state after `page.reload()`), or complete the ones a subagent drafted, together with the first slice of the implementation, then run `check` with the area pattern. Keep slices small: after the few files of one slice, run `check` before writing more; never write several large modules before the first check. Fix from the failure lines (pending locator and source line).
3. Finish the area. When its tests pass, run `check` without a pattern so earlier areas stay green, start the area's review by a subagent (see Subagents) and move on to the next area; its findings arrive as a message.

## Economy
- Keep source files small (about 400 lines at most): split pages into components and routes into modules, so a file is cheap to read and an error is easy to locate.
- Keep replies short: no restating the requirements, no long plans beyond the checklist.
- Keep bash output small (`| head`, `| tail`, `grep`).
- Stop once the checklist is covered.
