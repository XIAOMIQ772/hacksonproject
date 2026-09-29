# Keep

Note management system for creating, organizing, searching, and configuring personal notes.

## REQ-1 Google Keep Home Page

Main workspace of the application. It shows the notes area, pinned notes section, header actions, search entry, settings entry, sidebar navigation, and quick label access. Reference image: ![image](./reference/home_page.png)

**Type:** FOLDER
**Dependencies:** None

### REQ-1.1 Enter Website

Open the application and display the home page. The page exposes a visible region named `Notes workspace`, a button named `Take a note`, and a textbox named `Search`.

**Type:** ATOMIC
**Dependencies:** None

**Scenarios:**

- Enter Website
  - **GIVEN:** User has a browser or app with network access.
  - **WHEN:** Open the application entry URL.
  - **THEN:** The home page is displayed with the `Notes workspace` region, the `Take a note` button, and the `Search` textbox visible.

## REQ-2 Notes Management

Core note management capability for listing, creating, updating, deleting, archiving, coloring, labeling, and pinning notes. Reference image: ![image](./reference/home_page.png)

**Type:** FOLDER
**Dependencies:** REQ-1

### REQ-2.1 Note Listing

Display the notes list on the home page with pinned notes shown separately from unpinned notes. The pinned section is a named region or heading `Pinned`, and the regular section is a named region or heading `Others`. Each note is exposed as a unique article named by its title. Seed data: pinned note "Sprint goals" and regular note "Groceries".

**Type:** ATOMIC
**Dependencies:** REQ-1.1

**Scenarios:**

- Note Listing
  - **GIVEN:** User has opened the application and the system is accessible.
  - **WHEN:** View the home page.
  - **THEN:** The page displays visible `Pinned` and `Others` sections, with `Sprint goals` in the pinned section and `Groceries` in the regular section.

### REQ-2.2 Create Note

Create a note from the `Take a note` button. Activating it opens exactly one dialog named `Note editor` containing uniquely labelled textboxes `Title` and `Note content`, plus a button named `Close`. Closing the dialog autosaves the note. Take a note form from homepage image: ![image](./reference/create_note_home_page.png) Note form image: ![image](./reference/create_note_form.png)

**Type:** ATOMIC
**Dependencies:** REQ-2.1

**Scenarios:**

- Create Note
  - **GIVEN:** User is on the home page.
  - **WHEN:** Activate the unique button `Take a note`, fill the `Title` textbox with `Weekend plan`, fill the `Note content` textbox with `Visit the farmers market and prep lunches.`, and activate the `Close` button in the `Note editor` dialog.
  - **THEN:** The `Note editor` dialog closes, the note is autosaved, and exactly one note article named `Weekend plan` appears in the notes list.

### REQ-2.3 Delete Note

Delete notes from the note actions menu and manage the deleted-note recovery flow.

**Type:** FOLDER
**Dependencies:** REQ-2.2

#### REQ-2.3.1 Delete

Delete a note from its actions without an extra confirmation dialog. Each note is an article containing a button named `More options`; activating it exposes a button named `Delete Note` scoped to that note. Deletion exposes a status message `Note trashed` and a button named `Undo`. Dropdown image: ![image](./reference/note_more_options_dropdown.png) Seed data: deletable note "Delete me 2.3.1".

**Type:** ATOMIC
**Dependencies:** REQ-2.2

**Scenarios:**

- Delete
  - **GIVEN:** User is on the home page and can see at least one note.
  - **WHEN:** Hover over the article for `Delete me 2.3.1`, activate its `More options` button, and activate its `Delete Note` button.
  - **THEN:** The `Delete me 2.3.1` article is absent from the main notes list, a visible status message displays exactly `Note trashed`, and a unique button named `Undo` is available.

#### REQ-2.3.2 Notification and Undo

Show a delete status notification with a unique `Undo` button after a note is deleted. Activating `Undo` restores the same note article and displays a status message exactly `Action undone`. Reference image for notification: ![image](./reference/note_delete_notification.png) Seed data: deletable note "Delete me 2.3.2".

**Type:** ATOMIC
**Dependencies:** REQ-2.3.1

**Scenarios:**

- Notification and Undo
  - **GIVEN:** User has just deleted a note from the home page.
  - **WHEN:** Activate the unique `Undo` button in the visible delete notification.
  - **THEN:** The `Delete me 2.3.2` note article is restored and the page shows a visible status message exactly `Action undone`.

#### REQ-2.3.3 Trash list

Open the Trash view from the sidebar and display deleted notes. The sidebar is exposed as a complementary landmark and contains a unique button named `Trash`. Reference image: ![image](./reference/trash_list.png) Seed data: deletable note "Delete me 2.3.3".

**Type:** ATOMIC
**Dependencies:** REQ-2.3.1

**Scenarios:**

- Trash list
  - **GIVEN:** User can see the sidebar.
  - **WHEN:** Activate the unique button named `Trash` in the sidebar.
  - **THEN:** The Trash view displays the deleted note article named `Delete me 2.3.3`.

### REQ-2.4 Update Note

Edit the content of an existing note and persist it after closing the editor. Activating the note article opens a dialog named `Note editor` containing a textbox named `Note content` and a button named `Close`. Reference image: ![image](./reference/note_editing.png) Seed data: note "Project ideas" with initial content "Initial editable content".

**Type:** ATOMIC
**Dependencies:** REQ-2.2

**Scenarios:**

- Update Note
  - **GIVEN:** User is on the home page and can see a note.
  - **WHEN:** Open the `Project ideas` note article, replace `Note content` with `Updated editable content for the note editor.`, and activate `Close`.
  - **THEN:** The `Note editor` dialog closes and the `Project ideas` article displays `Updated editable content for the note editor.`.

### REQ-2.5 Archive Note

Archive and unarchive notes, and show the archived notes list separately from active notes.

**Type:** FOLDER
**Dependencies:** REQ-2.2

#### REQ-2.5.1 Archive

Archive a note using the button named `Archive` inside its note article and show a status message exactly `Note archived` with a unique `Undo` button. Reference image: ![image](./reference/archive_button.png) Seed data: active note "Travel plans 2.5.1".

**Type:** ATOMIC
**Dependencies:** REQ-2.2

**Scenarios:**

- Archive
  - **GIVEN:** User is on the home page and can see a note.
  - **WHEN:** Activate the `Archive` button inside the `Travel plans 2.5.1` note article.
  - **THEN:** The note is absent from the main list, is stored in the archive list, and the page shows `Note archived` with a unique `Undo` button.

#### REQ-2.5.2 Archive Undo

Restore an archived note by using the Undo action from the archive notification. Seed data: active note "Travel plans 2.5.2".

**Type:** ATOMIC
**Dependencies:** REQ-2.5.1

**Scenarios:**

- Archive Undo
  - **GIVEN:** The archive notification is visible after archiving a note.
  - **WHEN:** Activate the unique `Undo` button in the archive notification.
  - **THEN:** The note article named `Travel plans 2.5.2` returns to the main notes list.

#### REQ-2.5.3 Show archived notes

Open the Archive view from the sidebar using the unique button named `Archive` and display archived note articles. Reference image: ![image](./reference/archived_notes_page.png) Seed data: active note "Travel plans 2.5.3".

**Type:** ATOMIC
**Dependencies:** REQ-2.5.1

**Scenarios:**

- Show archived notes
  - **GIVEN:** User can see the sidebar.
  - **WHEN:** Activate the unique `Archive` button in the sidebar.
  - **THEN:** The Archive view displays the note article named `Travel plans 2.5.3`.

#### REQ-2.5.4 Unarchive

Restore an archived note using the button named `Unarchive` inside its note article. Reference image: ![image](./reference/unarchive_button.png) Seed data: active note "Travel plans 2.5.4".

**Type:** ATOMIC
**Dependencies:** REQ-2.5.3

**Scenarios:**

- Unarchive
  - **GIVEN:** User is viewing the archived notes list.
  - **WHEN:** Activate the `Unarchive` button inside the `Travel plans 2.5.4` article.
  - **THEN:** The note is absent from the archived list and the `Travel plans 2.5.4` article is present in the main notes list.

### REQ-2.6 Note Coloring

Allow users to apply different background colors to notes during creation and after a note already exists. Reference image: ![image](./reference/note_coloring.png)

**Type:** FOLDER
**Dependencies:** REQ-2.2

#### REQ-2.6.1 Change note color

Change the color of an existing note using its `Change color` button and a color button named `Light green`. Light green is represented by computed background color `rgb(204, 255, 144)`. Seed data: regular note "Garden tasks existing" with a white background.

**Type:** ATOMIC
**Dependencies:** REQ-2.2

**Scenarios:**

- Change note color
  - **GIVEN:** User is on the home page and can see a note.
  - **WHEN:** Activate `Change color` in the `Garden tasks existing` article and activate the color button named `Light green`.
  - **THEN:** The note article background changes to computed color `rgb(204, 255, 144)`.

#### REQ-2.6.2 Choose note color when created

Set the color of a note during creation using the `Change color` and `Light green` buttons in the `Note editor` dialog.

**Type:** ATOMIC
**Dependencies:** REQ-2.2

**Scenarios:**

- Choose note color when created
  - **GIVEN:** User has opened the "Take a note" editor.
  - **WHEN:** Activate `Change color`, activate `Light green`, fill `Title` with `Garden tasks created`, fill `Note content` with `Color me later`, and activate `Close`.
  - **THEN:** The `Garden tasks created` note article is saved with computed background color `rgb(204, 255, 144)`.

### REQ-2.7 Labels Management

Allow users to assign labels to notes, manage labels, and filter notes by label.

**Type:** FOLDER
**Dependencies:** REQ-2.2

#### REQ-2.7.1 Assign label to a note

Assign labels to an existing note. The note article has a `More options` button; its menu has a `Change labels` button; the label editor exposes a checkbox named `Work`. Reference image: ![image](./reference/assign_label_to_note.png) Seed data: regular note "Team retro add label" without the "Work" label; label "Work".

**Type:** ATOMIC
**Dependencies:** REQ-2.2

**Scenarios:**

- Assign label to a note
  - **GIVEN:** User is on the home page and can see a note.
  - **WHEN:** In the `Team retro add label` article, activate `More options`, activate `Change labels`, check the `Work` checkbox, and activate `Close`.
  - **THEN:** The `Work` label is assigned and displayed inside the target note article.

#### REQ-2.7.2 Remove label from a note

Remove an assigned label from a note. The note article exposes `More options` and `Change labels`; the label editor exposes a checked checkbox named `Work` and a `Close` button. Seed data: regular note "Team retro remove label" with the "Work" label; label "Work".

**Type:** ATOMIC
**Dependencies:** REQ-2.7.1

**Scenarios:**

- Remove label from a note
  - **GIVEN:** User is on the home page and can see a note that already has a label.
  - **WHEN:** In the `Team retro remove label` article, activate `More options`, activate `Change labels`, uncheck `Work`, and activate `Close`.
  - **THEN:** The `Work` label is absent from the target note article; other notes and the sidebar remain unchanged.

#### REQ-2.7.3 Default label

Provide `Reminders` as a default label in the sidebar. The sidebar exposes it as a unique button named `Reminders`. Seed data: default label "Reminders".

**Type:** ATOMIC
**Dependencies:** None

**Scenarios:**

- Default label
  - **GIVEN:** The system has been initialized.
  - **WHEN:** View the labels list.
  - **THEN:** The sidebar includes a unique button named `Reminders`.

#### REQ-2.7.4 Assign default label when creating note

Assign the default "Reminders" label during note creation. Seed data: default label "Reminders".

**Type:** ATOMIC
**Dependencies:** REQ-2.7.3

**Scenarios:**

- Assign default label when creating note
  - **GIVEN:** User is on the home page and the "Take a note" editor is open.
  - **WHEN:** Open "More options", choose "Change labels", select the "Reminders" label, enter a title and content, and click "Close".
  - **THEN:** The created note is saved with the "Reminders" label.

#### REQ-2.7.5 Edit labels

Create, rename, and delete labels from the label management list. Each label row is a named group, for example `Label Work editable`, containing a textbox labelled `Label Work editable` and a unique `Save` button. Reference image: ![image](./reference/manage_labels.png) Seed data: editable label "Work editable".

**Type:** ATOMIC
**Dependencies:** REQ-2.7.1

**Scenarios:**

- Edit labels
  - **GIVEN:** User can see the sidebar.
  - **WHEN:** Activate the unique `Edit labels` sidebar button, replace the `Label Work editable` textbox value with `Projects`, and activate its `Save` button.
  - **THEN:** The label list contains a textbox named `Label Projects`.

#### REQ-2.7.6 View by labels

Show all labels in the sidebar and allow users to filter the notes list by the selected label. Reference image: ![image](./reference/label_filtered_list.png)

**Type:** FOLDER
**Dependencies:** REQ-2.7.1

##### REQ-2.7.6.1 View list filtered by label

Filter the notes list by a selected label. The sidebar exposes the label as a unique button named `Work`. Seed data: note "Design review" with the "Work" label and note "Movie list" without the "Work" or "Reminders" label; label "Work".

**Type:** ATOMIC
**Dependencies:** REQ-2.7.1

**Scenarios:**

- View list filtered by label
  - **GIVEN:** User can see the sidebar.
  - **WHEN:** Activate the unique `Work` button in the sidebar.
  - **THEN:** The notes list contains `Design review` and does not contain `Movie list`.

##### REQ-2.7.6.2 View all notes

Return from a label-filtered view to the full notes list. Seed data: note "Design review" with the "Work" label and note "Movie list" without the "Work" or "Reminders" label; label "Work".

**Type:** ATOMIC
**Dependencies:** REQ-2.7.6.1

**Scenarios:**

- View all notes
  - **GIVEN:** User can see the sidebar.
  - **WHEN:** Activate the unique `Notes` button in the sidebar.
  - **THEN:** The notes list contains both `Design review` and `Movie list`.

##### REQ-2.7.6.3 View Reminders

Filter the notes list by the default "Reminders" label. Seed data: note "Call dentist existing" with the "Reminders" label and note "Movie list" without the "Work" or "Reminders" label; label "Reminders".

**Type:** ATOMIC
**Dependencies:** REQ-2.7.3

**Scenarios:**

- View Reminders
  - **GIVEN:** User can see the sidebar.
  - **WHEN:** Activate the unique `Reminders` button in the sidebar.
  - **THEN:** The notes list contains `Call dentist existing` and does not contain `Movie list`.

### REQ-2.8 Pinned Notes

Allow users to pin frequently used notes to the top of the notes list and unpin them later.

**Type:** FOLDER
**Dependencies:** REQ-2.2

#### REQ-2.8.1 Pin note

Pin an existing note from its article using a button named `Pin note`. The pinned article exposes a title attribute `Pinned`. Reference image: ![image](./reference/pin_button.png) Seed data: regular note "Meeting agenda 2.8.1" that is not pinned.

**Type:** ATOMIC
**Dependencies:** REQ-2.2

**Scenarios:**

- Pin note
  - **GIVEN:** User is on the home page and can see a note.
  - **WHEN:** Activate the `Pin note` button inside the `Meeting agenda 2.8.1` article.
  - **THEN:** The article has title `Pinned` and appears in the `Pinned` section.

#### REQ-2.8.2 Unpin note

Remove the pinned state from a pinned note using its `Unpin note` button. The article no longer exposes title `Pinned`. Seed data: regular note "Meeting agenda 2.8.2" that is not pinned.

**Type:** ATOMIC
**Dependencies:** REQ-2.8.1

**Scenarios:**

- Unpin note
  - **GIVEN:** User is on the home page and the note is pinned.
  - **WHEN:** Activate the `Unpin note` button inside the `Meeting agenda 2.8.2` article.
  - **THEN:** The article is absent from the pinned section, is present in the regular notes list, and has no `Pinned` title.

#### REQ-2.8.3 Pin note when creating it

Create a note in the pinned state. The `Note editor` dialog contains a button named `Pin note` and a button named `Close`.

**Type:** ATOMIC
**Dependencies:** REQ-2.2

**Scenarios:**

- Pin note when creating it
  - **GIVEN:** User is on the home page and the "Take a note" editor is open.
  - **WHEN:** Fill `Title` with `Meeting agenda created`, fill `Note content` with `Pin this note`, activate `Pin note`, and activate `Close`.
  - **THEN:** The `Meeting agenda created` article is displayed in `Pinned` and exposes title `Pinned`.

## REQ-3 Search

Allow users to search notes by keywords and supported filters.

**Type:** FOLDER
**Dependencies:** REQ-2

### REQ-3.1 Initial suggested filters

Show suggested search filters after the textbox named `Search` is focused. The suggestions are exposed as a listbox containing a button named `Reminders`; activating it filters the notes list. Image reference: ![image](./reference/search_suggested_filters.png) Seed data: note "Call dentist existing" with the "Reminders" label; label "Reminders".

**Type:** ATOMIC
**Dependencies:** REQ-1.1

**Scenarios:**

- Initial suggested filters
  - **GIVEN:** User is on the home page.
  - **WHEN:** Focus the `Search` textbox and activate the `Reminders` button in the visible suggestions listbox.
  - **THEN:** The notes list contains `Call dentist existing`.

### REQ-3.2 Search by keyword

Search notes by keyword and highlight matching text in the results. The search control is a textbox named `Search`; matching occurrences are exposed in `mark` elements. Image reference: ![image](./reference/search_keyword.png) Seed data: note "Study schedule" whose title or content contains the keyword "st".

**Type:** ATOMIC
**Dependencies:** REQ-3.1

**Scenarios:**

- Search by keyword
  - **GIVEN:** User is on the home page.
  - **WHEN:** Fill the `Search` textbox with `st`.
  - **THEN:** The notes list contains `Study schedule` and at least one `mark` element contains `st`.

## REQ-4 Settings

Allow users to manage common application settings.

**Type:** FOLDER
**Dependencies:** REQ-2

### REQ-4.1 Setting options list

Display the settings options menu from a unique button named `Settings`. The opened menu has role `menu` and contains unique menuitems named `Settings`, `Help & feedback`, and `Send feedback`. Reference image: ![image](./reference/settings_dropdown.png)

**Type:** ATOMIC
**Dependencies:** REQ-1.1

**Scenarios:**

- Setting options list
  - **GIVEN:** User is on the home page.
  - **WHEN:** Activate the unique `Settings` button.
  - **THEN:** A visible `menu` displays menuitems `Settings`, `Help & feedback`, and `Send feedback`.

### REQ-4.2 Detailed settings

Open the detailed settings page and display visible controls or text for `Move new notes to the bottom`, `Move checked items to the bottom`, `Save`, and `Cancel`. ![image](./reference/settings_settings.png)

**Type:** ATOMIC
**Dependencies:** REQ-4.1

**Scenarios:**

- Detailed settings
  - **GIVEN:** User is on the home page and the settings options list is visible.
  - **WHEN:** Activate the unique `Settings` menuitem.
  - **THEN:** The detailed settings page displays `Move new notes to the bottom`, `Move checked items to the bottom`, and unique controls named `Save` and `Cancel`.

## REQ-5 List View & Grid View

Allow users to switch between grid view and list view for notes. Reference image for list view: ![image](./reference/list_view.png)

**Type:** FOLDER
**Dependencies:** REQ-2

### REQ-5.1 Toggle between list and grid views

Switch between list view and grid view from the home page toolbar. The toolbar contains buttons named `List view` and `Grid view`; exactly one has aria-pressed=true at a time.

**Type:** ATOMIC
**Dependencies:** REQ-1.1

**Scenarios:**

- Toggle between list and grid views
  - **GIVEN:** User is on the home page.
  - **WHEN:** Activate `List view` and then activate `Grid view`.
  - **THEN:** `List view` has aria-pressed=true after the first activation; `Grid view` has aria-pressed=true after the second activation.

### REQ-5.2 Grid View by default

Display notes in grid view by default when the home page first loads. The `List view` button has aria-pressed=false and the `Grid view` button has aria-pressed=true.

**Type:** ATOMIC
**Dependencies:** REQ-1.1

**Scenarios:**

- Grid View by default
  - **GIVEN:** User has a browser or app with network access.
  - **WHEN:** Open the application entry URL.
  - **THEN:** The notes page opens in grid view; `List view` has aria-pressed=false and `Grid view` has aria-pressed=true.

## REQ-6 Sidebar

Sidebar for common navigation actions such as notes, labels, archive, and trash.

**Type:** FOLDER
**Dependencies:** REQ-2

### REQ-6.1 Items and styling

Display an expanded complementary sidebar containing unique buttons named `Notes`, `Reminders`, `Edit labels`, `Archive`, and `Trash`. Reference image: ![image](./reference/sidebar.png)

**Type:** ATOMIC
**Dependencies:** REQ-1.1

**Scenarios:**

- Items and styling
  - **GIVEN:** User has opened the application.
  - **WHEN:** View the page after the home page loads.
  - **THEN:** The page shows the expanded sidebar with unique buttons named `Notes`, `Reminders`, `Edit labels`, `Archive`, and `Trash`.

### REQ-6.2 Collapsible Sidebar

Collapse the sidebar to an icon-only view and expand it again using a unique button named `Toggle sidebar`. The button exposes aria-expanded=true when expanded and false when collapsed. Reference image: ![image](./reference/sidebar_collapsed.png)

**Type:** ATOMIC
**Dependencies:** REQ-6.1

**Scenarios:**

- Collapsible Sidebar
  - **GIVEN:** The sidebar is expanded.
  - **WHEN:** Activate `Toggle sidebar` twice.
  - **THEN:** The sidebar first has aria-expanded=false and then aria-expanded=true, with the named sidebar buttons visible again.
