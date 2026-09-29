# Engineering rules for the generated web app

The app is accepted by browser automation that locates controls by ARIA role and accessible name and drives them with clicks, typing, key presses, clipboard paste, drag and file upload, then reloads the page to verify persistence. The requirement text wins over these rules whenever they conflict.

## Reading requirements
1. Each atomic requirement's description is the acceptance rule. Scenario steps may be templated placeholders; use them only for seed values and flow.
2. Every double-quoted UI string is an exact accessible name or message: same case, spacing and punctuation. Substitute placeholders like `<cell coordinate>` with real values and keep the rest verbatim.
3. When the description and a scenario disagree, satisfy both (e.g. show the confirmation dialog when one says "must" and the other says "if").
4. Implement only what the requirements describe. No extra pages, controls, animations or decorative styling.

## Semantics
5. Use the role the requirement names (link, button, heading, tab, menuitem, searchbox, checkbox...). Otherwise: navigation is an `<a href>`, an action is a `<button>`.
6. Every interactive element has an accessible name: visible text, a `<label for>` for inputs, or `aria-label` for icon-only controls.
7. Within one view, names are unique per role. Repeated rows or cells get names that include their identifier (e.g. `Open dropdown for B2`).
8. A label text must resolve to exactly one element. A popup (listbox, menu) must not reuse its trigger's `aria-labelledby` or `aria-label`.
9. Pages and dialogs have a heading with the required title. Reflect state in ARIA: `aria-selected`, `aria-expanded`, `aria-current`, `disabled`.

## Components
10. Simple controls are native elements: button, a, input (text/checkbox/radio/file), textarea.
11. Composite controls are implemented in the page DOM following WAI-ARIA Authoring Practices, as small shared components reused everywhere:
    - Combobox (any "combo box", "dropdown", "select" choice): a `role="combobox"` trigger labelled by its `<label>`, with `aria-expanded` and `aria-controls`; clicking it shows a visible `role="listbox"` (no label of its own) whose items are clickable `role="option"` elements named exactly as the option text; clicking an option selects it and closes the list; the trigger shows the selected text.
    - Menu: trigger button with `aria-haspopup="menu"` and `aria-expanded`; a `role="menu"` with `role="menuitem"` buttons.
    - Dialog: `role="dialog"` with `aria-labelledby` pointing at its heading; focus moves inside when opened.
    - Tabs: `role="tablist"` containing `role="tab"` elements, active one `aria-selected="true"`.
    - Editable grid: `role="grid"`, rows `role="row"`, cells `role="gridcell"` named by `aria-label` when the requirement defines cell names.
12. Never use native `<select>`, native date/color pickers, or `alert`/`confirm`/`prompt`, unless the requirement explicitly demands that element; then add the comment `required by REQ-x` on that line.
13. When a feature has several entry points (context menu, tab menu, toolbar), every entry point works, and anything reachable by right-click is also reachable through a visible named button.

## Interaction
14. Everything is operable by clicking visible elements; nothing appears only on hover.
15. Text entry: Enter commits, Escape cancels and restores, blur commits.
16. Handle real `copy`/`cut`/`paste` events with the system clipboard as plain text (tab-separated columns, newline-separated rows). Cut then paste moves: the source is cleared after a successful paste.
17. File upload uses a labelled `<input type="file">`; downloads use a Blob and an `<a download="name.ext">`.
18. No transitions, animations, skeletons or deferred rendering. With React Router 7 set `unstable_useTransitions={false}` on the router so a navigation replaces the page immediately.

## Data
19. All data lives in the backend database. UI state the requirements ask to keep (active tab, selection, filters, sort) is saved on the server too.
20. Persist every change immediately when the action completes; no debounce, no save-on-unload. Send writes with `fetch(..., { keepalive: true })`; the server applies writes in arrival order, so a reload right after an action shows the new state.
21. Every object has a stable URL; opening it directly in a new browser session shows its latest state; reload restores the last saved state.
22. Names and values are arbitrary strings of any length; never infer behaviour from their shape. The database accumulates records from many sessions: new or changed objects are immediately visible in their lists (no hiding by pagination or caps).
23. Undo/redo history is kept per object.
24. Seed data described by the requirements (accounts, sample records) is created automatically at backend startup on an empty database, idempotently.

## Validation and errors
25. Validate on the server; batch operations are all-or-nothing.
26. On failure nothing changes: no partial writes, original values and names stay displayed, the input keeps the user's text.
27. Show the exact required message once, next to its control, in an element with `role="alert"`; mark the input `aria-invalid="true"` and point `aria-describedby` at the message.
28. Server errors return JSON; the UI shows the message and never stays in a loading state.

## Delivery
29. Keep the template layout: `frontend/` (Vite + React) and `backend/` (Express + SQLite). The backend listens on `PORT`, serves `/api/*` and the built frontend. Use only dependencies already in the templates unless a small pure-JavaScript package is essential.
30. A fresh checkout must work with: `cd frontend && npm install && npm run build && cd ../backend && npm install && npm start`.
