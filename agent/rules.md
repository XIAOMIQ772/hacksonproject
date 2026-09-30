# Engineering rules for the generated web app

Treat the requirements as a contract verified by end-to-end browser tests that find controls by ARIA role and accessible name, operate them with clicks, typing, keys, clipboard, drag and file upload, and reload the page to check persistence. The requirement text wins over these rules whenever they conflict.

## Reading requirements
1. Each atomic requirement's description is the acceptance rule. Scenario steps may be templated placeholders; use them only for seed values and flow.
2. Every double-quoted UI string is an exact accessible name or message: same case, spacing and punctuation. Substitute placeholders like `<cell coordinate>` with real values and keep the rest verbatim.
3. When the description and a scenario disagree, satisfy both (e.g. show the confirmation dialog when one says "must" and the other says "if").
4. Implement only what the requirements describe; the app is verified by end-to-end tests that locate elements by role, name, label and link target, and every addition is a chance for a locator to match twice. Add no feature, page, control, text, link, animation or decorative styling the requirements do not ask for. Unless a requirement says otherwise, each key element (a link to a page, a button for an action, a form field, a heading, a status or error message) appears exactly once in its view: no second link to the same destination, no repeated button for the same action, no translated or abbreviated duplicate of a required label. A flow whose requirement names no input (for example a creation page described only by its submit button) must succeed without any user input: add no required field the requirement does not list, and use a sensible default value instead.

## Semantics
5. Use the role the requirement names (link, button, heading, tab, menuitem, searchbox, checkbox...). Otherwise: navigation is an `<a href>`, an action is a `<button>`.
6. Every interactive element has an accessible name: visible text, a `<label for>` for inputs, or `aria-label` for icon-only controls.
7. Within one view, names are unique per role. Repeated rows or cells get names that include their identifier (e.g. `Open dropdown for B2`).
8. An element's accessible name is exactly its required label: counts, badges and icons next to a label are outside the link/button or marked `aria-hidden="true"`.
9. A label text must resolve to exactly one element. A popup (listbox, menu) must not reuse its trigger's `aria-labelledby` or `aria-label`.
10. Pages and dialogs have a heading with the required title. Reflect state in ARIA: `aria-selected`, `aria-expanded`, `aria-current`, `disabled`.

## Components
11. Simple controls are native elements: button, a, input (text/checkbox/radio/file), textarea.
12. Composite controls are implemented in the page DOM following WAI-ARIA Authoring Practices, as small shared components reused everywhere:
    - Combobox (any "combo box", "dropdown", "select" choice): a `role="combobox"` trigger labelled by its `<label>`, with `aria-expanded` and `aria-controls`; clicking it shows a visible `role="listbox"` (no label of its own) whose items are clickable `role="option"` elements named exactly as the option text; clicking an option selects it and closes the list; the trigger shows the selected text.
    - Menu: trigger button with `aria-haspopup="menu"` and `aria-expanded`; a `role="menu"` with `role="menuitem"` buttons.
    - Dialog: `role="dialog"` with `aria-labelledby` pointing at its heading; focus moves inside when opened.
    - Tabs: `role="tablist"` containing `role="tab"` elements, active one `aria-selected="true"`.
    - Editable grid: `role="grid"`, rows `role="row"`, cells `role="gridcell"` named by `aria-label` when the requirement defines cell names.
13. Never use native `<select>`, native date/color pickers, or `alert`/`confirm`/`prompt`, unless the requirement explicitly demands that element; then add the comment `required by REQ-x` on that line.
14. When a feature has several entry points (context menu, tab menu, toolbar), every entry point works, and anything reachable by right-click is also reachable through a visible named button.

## Interaction
15. Everything is operable by clicking visible elements; nothing appears only on hover.
16. Text entry: Enter commits, Escape cancels and restores, blur commits.
17. Handle real `copy`/`cut`/`paste` events with the system clipboard as plain text (tab-separated columns, newline-separated rows). Cut then paste moves: the source is cleared after a successful paste.
18. File upload uses a labelled `<input type="file">`; downloads use a Blob and an `<a download="name.ext">`.
19. No transitions, animations, skeletons or deferred rendering. With React Router 7 set `unstable_useTransitions={false}` on the router so a navigation replaces the page immediately.

## Data
20. All data lives in the backend database. UI state the requirements ask to keep (active tab, selection, filters, sort) is saved on the server too.
21. Persist every change immediately when the action completes; no debounce, no save-on-unload. Send writes with `fetch(..., { keepalive: true })`; the server applies writes in arrival order, so a reload right after an action shows the new state.
22. Every object has a stable URL; opening it directly in a new browser session shows its latest state; reload restores the last saved state.
23. Names and values are arbitrary strings of any length; never infer behaviour from their shape. The database accumulates records from many sessions: new or changed objects are immediately visible in their lists (no hiding by pagination or caps). Landing and list pages show every object the signed-in user can access (owned, shared directly, via a team or an organization), each linked by its name, so any accessible object is reachable from the home page by clicking.
24. Undo/redo history is kept per object.
25. Seed data described by the requirements (accounts, sample records) is created automatically at backend startup on an empty database, idempotently, and the server accepts requests only after schema and seeding have finished (chain them onto `app.ready`). Seed exactly the records the requirements name, with the stated attributes; do not invent extra sample records whose names could collide with objects users create. When scenario preconditions describe the same record differently, seed the version most requirements share and make every feature work equally on objects created through the UI.

## Validation and errors
26. Validate on the server; batch operations are all-or-nothing.
27. On failure nothing changes: no partial writes, original values and names stay displayed, the input keeps the user's text.
28. Show the exact required message once, next to its control, in an element with `role="alert"`; mark the input `aria-invalid="true"` and point `aria-describedby` at the message.
29. Server errors return JSON; the UI shows the message and never stays in a loading state.

## Delivery
30. Keep the template layout: `frontend/` (Vite + React) and `backend/` (Express + SQLite). The backend listens on `PORT`, serves `/api/*` and the built frontend. Use only dependencies already in the templates unless a small pure-JavaScript package is essential.
31. A fresh checkout must work with: `cd frontend && npm install && npm run build && cd ../backend && npm install && npm start`.
