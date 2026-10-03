# Engineering rules for the generated web app

Treat the requirements as a contract verified by end-to-end browser tests. The requirement text wins over these rules whenever they conflict.

## How the app is evaluated
- The evaluator installs and builds the delivered `frontend/` and `backend/` and starts the backend, which serves the API and the built frontend on one port. Nothing runs that the delivery does not include.
- The app is checked end to end through the browser UI only, as the requirement scenarios describe. Each scenario starts in a fresh, unauthenticated browser session at the home page, finds elements by ARIA role, accessible name, label or visible text, operates them with clicks, typing, keys, clipboard and file upload, and reloads or reopens pages to check that results persisted.
- Playwright locators are strict: a locator that matches two elements fails the test, and one that matches nothing fails after a timeout.
- All sessions share one running server and database: records created earlier remain, and new objects often carry a unique suffix in their names.

## Reading requirements
1. Each atomic requirement's description is the acceptance rule. Scenario steps are generated from templates and can be garbled or hold placeholders; use them only for seed values and flow. Walk each scenario step by step in the state the previous step leaves (signed in or not, current page, open dialog): every control a step uses must be visible in that state. When it is not, change the app so the step works, never the test. A step that opens a page or record without saying how to reach it ("opens the Issues page", "opens the `X` entry") starts from the page the scenario is on, usually the home page: that page links it directly by that exact name, for visitors as for signed-in users (link the named pages, and list the seeded records that scenarios open this way by their exact titles). For example, if a scenario, after an action on the signed-in account (a credential change or reset, also a rejected one), returns to the home page and signs in again, that action ends the current session while the page keeps showing its result message.
2. Every double-quoted UI string is an exact accessible name or message: same case, spacing and punctuation. Substitute placeholders like `<cell coordinate>` with real values and keep the rest verbatim.
3. When the description and a scenario disagree, satisfy both (e.g. show the confirmation dialog when one says "must" and the other says "if"). A message with placeholders (`between <min> and <max>`) is the general rule; a literal message stated for one named scenario applies only under that scenario's conditions: it replaces the template only when every condition the requirement attaches to it holds (range size, entry path, after reload, after a move), and equal parameter values alone are not the scenario.
4. Implement only what the requirements describe; elements are found by role, name, label and link target, and every addition is a chance for a name to become ambiguous. Add no feature, page, control, text, link, animation or decorative styling the requirements do not ask for. Unless a requirement says otherwise, each key element (a link to a page, a button for an action, a form field, a heading, a status or error message) appears exactly once in its view: no second link to the same destination, no repeated button for the same action, no translated or abbreviated duplicate of a required label. A flow whose requirement names no input (for example a creation page described only by its submit button) must succeed without any user input: add no required field the requirement does not list, and use a sensible default value instead.

## Semantics
5. Use the role the requirement names (link, button, heading, tab, menuitem, searchbox, checkbox...). Otherwise: navigation is a plain `<a href>` element (a full page load, so a click returns once the next page has loaded), never react-router's `<Link>`, `<NavLink>`, `<Navigate>` or `navigate()`, which route on the client and show the next page before its data; after a successful form submit, move with `window.location.assign(url)`. An action is a `<button>`.
6. Every interactive element has an accessible name: visible text, a `<label for>` for inputs, or `aria-label` for icon-only controls.
7. Within one view, names are unique per role. Repeated rows or cells get names that include their identifier (e.g. `Open dropdown for B2`).
8. An element's accessible name is exactly its required label: counts, badges and icons next to a label are outside the link/button or marked `aria-hidden="true"`.
9. A label text must resolve to exactly one element. A popup (listbox, menu) must not reuse its trigger's `aria-labelledby` or `aria-label`.
10. Pages and dialogs have a heading with the required title. Reflect state in ARIA: `aria-selected`, `aria-expanded`, `aria-current`, `disabled`.

## Components
11. Simple controls are native elements: button, a, input (text/checkbox/radio/file), textarea.
12. Composite controls are implemented in the page DOM following WAI-ARIA Authoring Practices, as small shared components reused everywhere:
    - Combobox (a "combo box" or "dropdown" choice): an `<input type="button" role="combobox" value="<selected text>">` trigger labelled by its `<label>` (it passes both `toHaveValue` and `toHaveText`; a `<button>` fails `toHaveValue`, a text input fails `toHaveText`), with `aria-expanded` and `aria-controls`; clicking it shows a visible `role="listbox"` (no label of its own) whose items are clickable `role="option"` elements named exactly as the option text; clicking an option selects it and closes the list.
    - Menu: trigger button with `aria-haspopup="menu"` and `aria-expanded`; a `role="menu"` with `role="menuitem"` buttons.
    - Dialog: `role="dialog"` with `aria-labelledby` pointing at its heading; focus moves inside when opened.
    - Tabs: `role="tablist"` containing `role="tab"` elements, active one `aria-selected="true"`.
    - Editable grid: `role="grid"`, rows `role="row"`, cells `role="gridcell"` named by `aria-label` when the requirement defines cell names.
13. The requirement wording decides the kind of a choice: a "native select" is a `<select>`; a combobox whose options are described as clicked or as having the option role is the ARIA combobox above, even when it edits a stored value. When the requirement says neither, a combobox editing a stored value in a settings field or a table row is a `<select>` (tests operate it with `selectOption` and read it with `toHaveValue`), and one in a creation form or picker is the ARIA combobox. A `<select>`'s options carry their text in the `label` attribute with `value` equal to it (`<option value="Write" label="Write">`, no text content), so option names never repeat as page text. Use other native inputs (date, color) only where the requirement asks for them. A row that shows a value repeated in other rows (a role, a status) shows it as `<td><span class="sr-only">Role: </span>Write</td>`: the row's text contains the value, but no element's full text is the bare value, which tests look up once on the whole page; after an add or change, a `role="status"` line shows the new value once in its own element (`<strong>Write</strong>`). Never use `alert`, `confirm` or `prompt` (the test browser dismisses them, so `confirm()` returns false); show messages and confirmations in the page.
14. When a feature has several entry points (context menu, tab menu, toolbar), every entry point works.

## Interaction
15. Everything is operable by clicking visible elements; nothing appears only on hover.
16. Text entry: Enter commits, Escape cancels and restores, blur commits. A field showing a stored value that may contain line breaks (a formula bar, a note) is a `<textarea rows=1>`.
17. Handle real `copy`/`cut`/`paste` events with the system clipboard as plain text (tab-separated columns, newline-separated rows). Cut then paste moves: the source is cleared after a successful paste.
18. File upload uses a labelled `<input type="file">`; downloads use a Blob and an `<a download="name.ext">`.
19. No transitions, animations, skeletons or deferred rendering; keep the router setting in `frontend/src/main.tsx` that commits navigations immediately, and its error reporter, which makes `check` list errors thrown in the page.

## Data
20. All data lives in the backend database. UI state the requirements ask to keep (active tab, selection, filters, sort) is saved on the server too.
21. Persist every change immediately when the action completes; no debounce, no save-on-unload. Send writes with `fetch(..., { keepalive: true })` so a reload does not cancel them, and keep the template's API queue in `backend/src/app.js`, which handles requests in arrival order; a reload right after an action then shows the new state.
22. Every object has a stable URL; opening it directly in a new browser session shows its latest state; reload restores the last saved state.
23. Names and values are arbitrary strings of any length; never infer behaviour from their shape. The database accumulates records from many sessions: new or changed objects are immediately visible in their lists (no hiding by pagination or caps). Landing and list pages show every object the viewer can access (a visitor: every public one; a signed-in user: owned, shared directly, via a team or an organization), each linked by its name, so any accessible object is reachable from the home page by clicking.
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
