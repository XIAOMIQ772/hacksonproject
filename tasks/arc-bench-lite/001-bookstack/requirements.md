# BookStack Knowledge Base System

Web-based knowledge base system for browsing, organizing, and reading shelves, books, chapters, and pages.

## REQ-1 Homepage

Default landing page of the system. It presents the global navigation bar, search input, and visible entry points to core areas of the product. Reference image ![image](./reference/index.png)

**Type:** FOLDER
**Dependencies:** None

### REQ-1.1 Open Homepage

Open the application and display the homepage. The page contains exactly one visible heading with accessible name `BookStack`.

**Type:** ATOMIC
**Dependencies:** None

**Scenarios:**

- Open Homepage
  - **GIVEN:** The system is accessible.
  - **WHEN:** The user opens the application URL.
  - **THEN:** The homepage is displayed as the default page with exactly one visible heading named `BookStack`.

### REQ-1.2 Back to Homepage from Other Pages

Return to the homepage by activating exactly one button with accessible name `BookStack` in the global navigation. The button is keyboard accessible and is present on every non-homepage page used by this benchmark.

**Type:** ATOMIC
**Dependencies:** REQ-1.1

**Scenarios:**

- Back to Homepage from Other Pages
  - **GIVEN:** The user is on a non-homepage page and the global navigation bar is visible.
  - **WHEN:** The user activates the unique button named `BookStack` in the global navigation.
  - **THEN:** The system navigates to the homepage, where exactly one visible heading named `BookStack` is present.

## REQ-2 User Authentication and Session

Provides login entry and authenticated session state. The login page and the authenticated homepage state follow the referenced layouts. Login page ![image](./reference/login.png) Homepage after login ![image](./reference/index_after_login.png)

**Type:** FOLDER
**Dependencies:** REQ-1

### REQ-2.1 Enter Login Page

Open the login form from the homepage navigation bar. The login page contains exactly one visible heading named `Login` and exactly one form with role `form` and accessible name `Login form`.

**Type:** ATOMIC
**Dependencies:** REQ-1.1

**Scenarios:**

- Enter Login Page
  - **GIVEN:** The user is on the homepage and is not logged in.
  - **WHEN:** The user activates the unique link or button named `Login` in the homepage navigation bar.
  - **THEN:** The system displays the login form page with exactly one visible heading named `Login` and a form named `Login form`.

### REQ-2.2 Log In Successfully

Authenticate with valid credentials and enter the authenticated homepage state. Seed data: verified account with nickname "BookStack User", email "bookstack_user@example.com", and password "Password123!".

**Type:** ATOMIC
**Dependencies:** REQ-2.1

**Scenarios:**

- Log In Successfully
  - **GIVEN:** The user is on the login form page.
  - **WHEN:** The user enters `bookstack_user@example.com` in the uniquely labelled email textbox `Email address`, enters `Password123!` in the uniquely labelled password textbox `Password`, checks the checkbox named `Remember Me`, and activates the `Login` button inside the `Login form`.
  - **THEN:** The system logs the user in, returns to the homepage, and displays the nickname `BookStack User` in the authenticated navigation area.

## REQ-3 Authenticated Homepage Dashboard

Authenticated homepage dashboard that shows recent drafts, recently viewed items, most viewed favorites, recently updated pages, recent activity, and the dashboard controls shown in the reference image. Reference image ![image](./reference/index_after_login.png)

**Type:** FOLDER
**Dependencies:** REQ-2

### REQ-3.1 Enter Authenticated Homepage

Display the dashboard layout after a successful login, including four visible named regions or headings: "My Recent Drafts", "My Recently Viewed", "My Most Viewed Favorites", and "Recently Updated Pages". Seed data: verified account with nickname "BookStack User", email "bookstack_user@example.com", and password "Password123!".

**Type:** ATOMIC
**Dependencies:** REQ-2.2

**Scenarios:**

- Enter Authenticated Homepage
  - **GIVEN:** The user has logged in successfully.
  - **WHEN:** The system finishes the post-login navigation.
  - **THEN:** The authenticated homepage dashboard is displayed with visible headings or named regions exactly matching "My Recent Drafts", "My Recently Viewed", "My Most Viewed Favorites", and "Recently Updated Pages".

## REQ-4 Shelves Module

Shelves are top-level content containers with name, description, related books, and tags. This module covers listing shelves, opening shelf details, creating shelves, editing shelves, and deleting shelves. Shelf list page ![image](./reference/shelves.png)

**Type:** FOLDER
**Dependencies:** REQ-1

### REQ-4.1 View Shelf List

Open the shelf list page from the global navigation bar. The navigation control may be a link or button named exactly "Shelves". The page exposes a visible heading "Shelves" and a named region "Shelf list" containing the seeded shelf "Shelf 4.1" as a unique link or button with that accessible name.

**Type:** ATOMIC
**Dependencies:** REQ-1.1

**Scenarios:**

- View Shelf List
  - **GIVEN:** The user is on a page where the global navigation bar is visible.
  - **WHEN:** The user activates the unique link or button named `Shelves` in the top navigation bar.
  - **THEN:** The system displays the shelf list page with heading `Shelves` and a unique shelf entry named `Shelf 4.1` in the `Shelf list` region.

### REQ-4.2 Shelf Details Page

Shelf details page that shows shelf information, included books, and the related action panel. Reference image ![image](./reference/shelf.png)

**Type:** FOLDER
**Dependencies:** REQ-4.1

#### REQ-4.2.1 Enter Shelf Details Page

Open the details page of a shelf from the shelf list. The shelf list contains the shelf as a unique link or button named exactly "Shelf 4.2.1". The destination displays a visible heading named "Shelf 4.2.1" and a shelf action region.

**Type:** ATOMIC
**Dependencies:** REQ-4.1

**Scenarios:**

- Enter Shelf Details Page
  - **GIVEN:** The user is on the shelf list page and at least one shelf is visible.
  - **WHEN:** The user activates the unique link or button named `Shelf 4.2.1` in the shelf list.
  - **THEN:** The system displays the shelf details page with a visible heading named `Shelf 4.2.1`.

### REQ-4.3 Create New Shelf

Provide a shelf creation flow with fields for shelf name, description, and tags. Reference image ![image](./reference/create_shelf.png)

**Type:** FOLDER
**Dependencies:** REQ-4.2

#### REQ-4.3.1 Create Shelf

Create a shelf from the shelf creation form. The form is exposed as role `form` named `Create shelf form` and contains uniquely labelled textboxes `Name` and `Description`, a control named `Shelf Tags` that reveals a textbox with exact placeholder `tag1, tag2`, a button named `Save Shelf`, and a button named `Cancel`. Seed data: shelf "Shelf 4.3.1".

**Type:** ATOMIC
**Dependencies:** REQ-4.2.1

**Scenarios:**

- Create Shelf
  - **GIVEN:** The user is on the shelf details page and can access the action panel.
  - **WHEN:** The user activates the unique button named `New Shelf`, fills `Name` with `Shelf Created 4.3.1`, fills `Description` with `Shelf created by REQ-4.3.1.`, activates `Shelf Tags`, fills the revealed `tag1, tag2` textbox with `created, shelf`, and activates the `Save Shelf` button.
  - **THEN:** The system persists the shelf and displays the shelf list with exactly one entry named `Shelf Created 4.3.1`.

#### REQ-4.3.2 Cancel Creation

Exit the shelf creation flow without saving a new shelf. The creation form has a unique button named `Cancel`. Seed data: shelf "Shelf 4.3.2".

**Type:** ATOMIC
**Dependencies:** REQ-4.2.1

**Scenarios:**

- Cancel Creation
  - **GIVEN:** The user is on the shelf creation page.
  - **WHEN:** The user activates the unique `Cancel` button.
  - **THEN:** The system returns to the shelf list and does not persist any shelf entered in the cancelled form.

### REQ-4.4 Delete Shelf

Delete the current shelf from the shelf details flow with confirmation. Confirmation page ![image](./reference/delete_shelves.png)

**Type:** FOLDER
**Dependencies:** REQ-4.2

#### REQ-4.4.1 Confirm Delete Shelf

Delete a shelf after the user confirms the action. The details action area contains a unique button named `Delete`. Confirmation displays a dialog or confirmation page containing a unique button named `Confirm Delete` and a unique button named `Cancel`. Seed data: deletable shelf "Shelf 4.4.1".

**Type:** ATOMIC
**Dependencies:** REQ-4.2.1

**Scenarios:**

- Confirm Delete Shelf
  - **GIVEN:** The user is on the shelf details page and can access the action panel.
  - **WHEN:** The user activates `Delete`, then activates the unique `Confirm Delete` control on the confirmation view.
  - **THEN:** The system deletes the shelf, returns to the shelf list page, and the entry named `Shelf 4.4.1` is absent.

#### REQ-4.4.2 Cancel Delete Shelf

Exit the delete flow without deleting the shelf. The confirmation view contains a unique button named `Cancel`. Seed data: deletable shelf "Shelf 4.4.2".

**Type:** ATOMIC
**Dependencies:** REQ-4.2.1

**Scenarios:**

- Cancel Delete Shelf
  - **GIVEN:** The user is on the delete shelf confirmation page.
  - **WHEN:** The user activates the unique `Cancel` button.
  - **THEN:** The system returns to the shelf details page and keeps the shelf named `Shelf 4.4.2` unchanged.

### REQ-4.5 Edit Shelf

Provide a shelf editing flow for changing shelf information, related books, and tags. Shelf edit page ![image](./reference/edit_shelve.png)

**Type:** FOLDER
**Dependencies:** REQ-4.2

#### REQ-4.5.1 Save Shelf Edits

Save changes made in the shelf edit form. The form is exposed as role `form` named `Edit shelf form` and contains uniquely labelled textboxes `Name` and `Description`, a `Shelf Tags` control with a `tag1, tag2` textbox, and a button named `Save Shelf`. Seed data: editable shelf "Shelf 4.5.1" with valid initial description and tags.

**Type:** ATOMIC
**Dependencies:** REQ-4.2.1

**Scenarios:**

- Save Shelf Edits
  - **GIVEN:** The user is on the shelf details page and can access the action panel.
  - **WHEN:** The user activates `Edit`, fills `Name` with `Shelf Updated 4.5.1`, fills `Description` with `Shelf updated by REQ-4.5.1.`, activates `Shelf Tags`, fills `tag1, tag2` with `knowledge-base, docs`, and activates `Save Shelf`.
  - **THEN:** The system saves the changes and returns to a shelf details page displaying `Shelf Updated 4.5.1`.

#### REQ-4.5.2 Cancel Shelf Edits

Exit the shelf editing flow without saving changes. The edit form has a unique button named `Cancel`. Seed data: editable shelf "Shelf 4.5.2" with valid initial description and tags.

**Type:** ATOMIC
**Dependencies:** REQ-4.2.1

**Scenarios:**

- Cancel Shelf Edits
  - **GIVEN:** The user is on the shelf edit page.
  - **WHEN:** The user activates the unique `Cancel` button.
  - **THEN:** The system returns to the shelf details page without applying the edits; `Shelf 4.5.2` remains unchanged.

## REQ-5 Books Module

Books contain a name, description, chapters, and pages. This module covers viewing books, opening book details, creating books, editing books, deleting books, and creating books from a shelf context. Book list page ![image](./reference/books.png)

**Type:** FOLDER
**Dependencies:** REQ-1

### REQ-5.1 View Books List

Open the books list page from the global navigation bar. The navigation control may be a link or button named exactly "Books". The page exposes a visible heading "Books" and a named region "Book list" containing the seeded book "Book 5.1" as a unique link or button.

**Type:** ATOMIC
**Dependencies:** REQ-1.1

**Scenarios:**

- View Books List
  - **GIVEN:** The user is on a page where the global navigation bar is visible.
  - **WHEN:** The user activates the unique link or button named `Books` in the top navigation bar.
  - **THEN:** The system displays the books list page with heading `Books`, a `Book list` region, and the seeded book `Book 5.1` as a unique link or button.

### REQ-5.2 Book Details Page

Book details page that can be opened from supported book entry points and displays the selected book information. Book details page ![image](./reference/book.png)

**Type:** FOLDER
**Dependencies:** REQ-5.1

#### REQ-5.2.1 Enter Book Details Page through Book List Page

Open a book details page from the books list. The book list contains a unique link or button named exactly "Book 5.2.1". The destination displays a visible heading named "Book 5.2.1".

**Type:** ATOMIC
**Dependencies:** REQ-5.1

**Scenarios:**

- Enter Book Details Page through Book List Page
  - **GIVEN:** The user is on the books list page and at least one book card is visible.
  - **WHEN:** The user activates the unique link or button named `Book 5.2.1` in the book list.
  - **THEN:** The system displays the book details page with a visible heading named `Book 5.2.1`.

#### REQ-5.2.2 Enter Book Details Page through Shelf Details Page

Open a book details page from a shelf details page. The shelf contains a unique link or button named exactly "Book 5.2.2". The destination displays a visible heading named "Book 5.2.2". Seed data: shelf "Shelf 5.2.2" containing book "Book 5.2.2" with valid initial metadata.

**Type:** ATOMIC
**Dependencies:** REQ-4.2.1

**Scenarios:**

- Enter Book Details Page through Shelf Details Page
  - **GIVEN:** The user is on a shelf details page and at least one book is listed on the shelf.
  - **WHEN:** The user activates the unique link or button named `Book 5.2.2` in the shelf details page.
  - **THEN:** The system displays the book details page with a visible heading named `Book 5.2.2`.

### REQ-5.3 Create Book in Book List Page

Provide a book creation flow from the books list page with fields for name, rich-text description, optional cover image, book tags, and default page template. Reference image ![image](./reference/create_book.png)

**Type:** FOLDER
**Dependencies:** REQ-5.1

#### REQ-5.3.1 Fill out and Save Book

Create a new book from the books list page. The form is exposed as role `form` named `Create book form` and contains uniquely labelled textboxes `Name` and `Description`, a `Book Tags` control that reveals a `tag1, tag2` textbox, and a button named `Save Book`.

**Type:** ATOMIC
**Dependencies:** REQ-5.1

**Scenarios:**

- Fill out and Save Book
  - **GIVEN:** The user is on the books list page and can access the action panel.
  - **WHEN:** The user activates `Create New Book`, fills `Name` with `Book Created 5.3.1`, fills `Description` with `Book created by REQ-5.3.1.`, activates `Book Tags`, fills `tag1, tag2` with `created, book`, and activates `Save Book`.
  - **THEN:** The system creates the book and opens its details page, displaying `Book Created 5.3.1` as a visible heading.

#### REQ-5.3.2 Cancel Creating Book

Exit the book creation flow without creating a book. The creation form contains a unique button named `Cancel`.

**Type:** ATOMIC
**Dependencies:** REQ-5.1

**Scenarios:**

- Cancel Creating Book
  - **GIVEN:** The user is on the create new book page.
  - **WHEN:** The user activates the unique `Cancel` button.
  - **THEN:** The system returns to the books list and does not persist a book entered in the cancelled form.

### REQ-5.4 Edit Book

Provide a book editing flow for changing book metadata on the book details page. Reference image ![image](./reference/edit_book.png)

**Type:** FOLDER
**Dependencies:** REQ-5.2

#### REQ-5.4.1 Save Book Edits

Save changes made in the book edit form. The form is exposed as role `form` named `Edit book form` and contains uniquely labelled textboxes `Name` and `Description`, a `Book Tags` control with a `tag1, tag2` textbox, and a button named `Save Book`. Seed data: editable book "Book 5.4.1" with valid initial description and tags.

**Type:** ATOMIC
**Dependencies:** REQ-5.2.1

**Scenarios:**

- Save Book Edits
  - **GIVEN:** The user is on the book details page and can access the action panel.
  - **WHEN:** The user activates `Edit`, fills `Name` with `Book Updated 5.4.1`, fills `Description` with `Book updated by REQ-5.4.1.`, activates `Book Tags`, fills `tag1, tag2` with `manual, handbook`, and activates `Save Book`.
  - **THEN:** The system saves the changes and returns to a book details page displaying `Book Updated 5.4.1`.

#### REQ-5.4.2 Cancel Book Edits

Exit the book editing flow without saving changes. The edit form has a unique button named `Cancel`. Seed data: editable book "Book 5.4.2" with valid initial description and tags.

**Type:** ATOMIC
**Dependencies:** REQ-5.2.1

**Scenarios:**

- Cancel Book Edits
  - **GIVEN:** The user is on the book edit page.
  - **WHEN:** The user activates the unique `Cancel` button.
  - **THEN:** The system returns to the book details page without applying the edits; `Book 5.4.2` remains unchanged.

### REQ-5.5 Delete Book

Delete the current book from the book details flow with confirmation. Confirmation page ![image](./reference/delete_book.png)

**Type:** FOLDER
**Dependencies:** REQ-5.2

#### REQ-5.5.1 Confirm Delete Book

Delete a book after the user confirms the action. The details action area contains a unique button named `Delete`; the confirmation view contains a unique button named `Confirm Delete` and a unique button named `Cancel`. Seed data: deletable book "Book 5.5.1".

**Type:** ATOMIC
**Dependencies:** REQ-5.2.1

**Scenarios:**

- Confirm Delete Book
  - **GIVEN:** The user is on the book details page and can access the action panel.
  - **WHEN:** The user activates `Delete`, then activates the unique `Confirm Delete` control.
  - **THEN:** The system deletes the book, returns to the books list page, and the entry named `Book 5.5.1` is absent.

#### REQ-5.5.2 Cancel Delete Book

Exit the delete flow without deleting the book. The confirmation view contains a unique button named `Cancel`. Seed data: deletable book "Book 5.5.2".

**Type:** ATOMIC
**Dependencies:** REQ-5.2.1

**Scenarios:**

- Cancel Delete Book
  - **GIVEN:** The user is on the delete book confirmation page.
  - **WHEN:** The user activates the unique `Cancel` button.
  - **THEN:** The system returns to the book details page and keeps `Book 5.5.2` unchanged.

### REQ-5.6 Create Book from Shelf Details Page

Provide a book creation flow from a shelf details page so the created book is associated with the current shelf.

**Type:** FOLDER
**Dependencies:** REQ-4.2

#### REQ-5.6.1 Fill out and Save Book with Shelf

Create a new book from the current shelf context. The form has uniquely labelled textboxes `Name` and `Description`, a `Book Tags` control with a `tag1, tag2` textbox, and a button named `Save Book`. The created book remains associated with the current shelf. Seed data: shelf "Shelf 5.6.1".

**Type:** ATOMIC
**Dependencies:** REQ-4.2.1

**Scenarios:**

- Fill out and Save Book with Shelf
  - **GIVEN:** The user is on a shelf details page and can access the action panel.
  - **WHEN:** The user activates `New Book`, fills `Name` with `Book Created 5.6.1`, fills `Description` with `Book created by REQ-5.6.1.`, activates `Book Tags`, fills `tag1, tag2` with `created, shelf-book`, and activates `Save Book`.
  - **THEN:** The system creates the book, associates it with `Shelf 5.6.1`, and displays both names on the resulting page.

## REQ-6 Pages and Chapters Module

Pages are the basic reading units of a book, and chapters organize groups of pages. This module covers page editing, draft handling, chapter creation, and page reading.

**Type:** FOLDER
**Dependencies:** REQ-5

### REQ-6.1 Page Edit Page

Provide the page editing flow for creating pages, saving drafts, and deleting drafts. Page edit page ![image](./reference/page_draft.png) Delete draft confirmation page ![image](./reference/delete_draft.png)

**Type:** FOLDER
**Dependencies:** REQ-5.2

#### REQ-6.1.1 Save Page

Create and save a new page in a book. The editor contains exactly one textbox with placeholder `Page title`, exactly one multiline textbox with placeholder `Write your page content here...`, and a button named `Save Page`. Seed data: book "Book 6.1.1".

**Type:** ATOMIC
**Dependencies:** REQ-5.2.1

**Scenarios:**

- Save Page
  - **GIVEN:** The user is on a book details page.
  - **WHEN:** The user activates `New Page`, fills `Page title` with `Page Created 6.1.1`, fills `Write your page content here...` with `Page content created by REQ-6.1.1.`, and activates `Save Page`.
  - **THEN:** The system saves the page, adds exactly one entry named `Page Created 6.1.1` to the book, and returns to the book details page.

#### REQ-6.1.2 Save Draft

Save the current page content as a draft. The editor contains a textbox with placeholder `Page title`, a multiline textbox with placeholder `Write your page content here...`, and a button named `Save Draft`. Seed data: book "Book 6.1.2"; verified account with nickname "BookStack User", email "bookstack_user@example.com", and password "Password123!".

**Type:** ATOMIC
**Dependencies:** REQ-5.2.1

**Scenarios:**

- Save Draft
  - **GIVEN:** The authenticated user is on the page edit page.
  - **WHEN:** The user fills `Page title` with `Page Draft 6.1.2`, fills `Write your page content here...` with `Draft content created by REQ-6.1.2.`, and activates `Save Draft`.
  - **THEN:** The system stores the draft and shows exactly one entry named `Page Draft 6.1.2` in the `My Recent Drafts` list on the homepage.

#### REQ-6.1.3 Delete Draft

Delete an existing page draft. The draft editor exposes a unique control named `Delete Draft`; the confirmation view exposes a unique control named `Confirm Delete`. Seed data: book "Book 6.1.3" with existing draft page "Draft 6.1.3".

**Type:** ATOMIC
**Dependencies:** REQ-6.1.2

**Scenarios:**

- Delete Draft
  - **GIVEN:** The user is on the page edit page and a draft already exists.
  - **WHEN:** The user opens the draft actions, activates `Delete Draft`, and activates the unique `Confirm Delete` control.
  - **THEN:** The system deletes the draft, returns to the related book details page, and the draft named `Draft 6.1.3` is absent.

### REQ-6.2 Create New Chapter

Provide a chapter creation flow from the book details page and support entering the chapter view after a chapter is available. Add chapter page ![image](./reference/create_chapter.png) Inside chapter page ![image](./reference/chapter.png)

**Type:** FOLDER
**Dependencies:** REQ-5.2

#### REQ-6.2.1 Create Chapter

Create a new chapter within a book. The chapter form contains uniquely labelled textboxes `Name` and `Description` and a button named `Save Chapter`. Seed data: book "Book 6.2.1".

**Type:** ATOMIC
**Dependencies:** REQ-5.2.1

**Scenarios:**

- Create Chapter
  - **GIVEN:** The user is on the book details page.
  - **WHEN:** The user activates `New Chapter`, fills `Name` with `Chapter Created 6.2.1`, fills `Description` with `Chapter created by REQ-6.2.1.`, and activates `Save Chapter`.
  - **THEN:** The system creates the chapter and displays exactly one entry named `Chapter Created 6.2.1` in the current book.

### REQ-6.3 Page Reading Page

Page reading page that opens from a book or chapter page list and shows the selected page content. Reference image ![image](./reference/page.png)

**Type:** FOLDER
**Dependencies:** REQ-6.1, REQ-6.2

#### REQ-6.3.1 Enter Page Reading Page

Open the reading page for a selected page. The page entry is a unique link or button named exactly "Page 6.3.1"; activating it displays a visible heading named "Page 6.3.1" and the page content. Seed data: book "Book 6.3.1" with readable page "Page 6.3.1" and page content.

**Type:** ATOMIC
**Dependencies:** REQ-6.1.1

**Scenarios:**

- Enter Page Reading Page
  - **GIVEN:** The user is viewing a list of pages within a book or chapter.
  - **WHEN:** The user activates the unique link or button named `Page 6.3.1`.
  - **THEN:** The system displays the page reading page with a visible heading named `Page 6.3.1`.

#### REQ-6.3.2 Redirect to Page Edit Page

Open the page edit flow from the page reading page. The action area contains a unique button named `Edit`. The editor contains a button named `Save Page`. Seed data: book "Book 6.3.2" with editable page "Page 6.3.2" and page content.

**Type:** ATOMIC
**Dependencies:** REQ-6.3.1

**Scenarios:**

- Redirect to Page Edit Page
  - **GIVEN:** The user is on the page reading page and can access the action area.
  - **WHEN:** The user activates the unique `Edit` button.
  - **THEN:** The system opens the edit page for the current page, where the `Save Page` button is visible.

## REQ-7 Recently Viewed

Display recently viewed shelves, books, chapters, and pages in the `My Recently Viewed` list on the homepage, with up to ten records.

**Type:** FOLDER
**Dependencies:** REQ-4, REQ-5, REQ-6

### REQ-7.1 Add to Recently Viewed

Add supported content to the recently viewed list after it is opened. Seed data: shelf "Shelf 7.1"; verified account with nickname "BookStack User", email "bookstack_user@example.com", and password "Password123!".

**Type:** ATOMIC
**Dependencies:** REQ-4.2.1, REQ-5.2.1, REQ-6.3.1

**Scenarios:**

- Add to Recently Viewed
  - **GIVEN:** The user is browsing supported content pages in the system.
  - **WHEN:** The user opens a shelf details page, book details page, page reading page, or chapter view.
  - **THEN:** The system adds the item to `My Recently Viewed` on the homepage.

### REQ-7.2 Quick Navigation from Recently Viewed

Open a content page from the recently viewed list. Seed data: shelf "Shelf 7.2"; verified account with nickname "BookStack User", email "bookstack_user@example.com", and password "Password123!".

**Type:** ATOMIC
**Dependencies:** REQ-7.1

**Scenarios:**

- Quick Navigation from Recently Viewed
  - **GIVEN:** The authenticated homepage shows `My Recently Viewed` with at least one item.
  - **WHEN:** The user activates the unique link or button named after the target item in `My Recently Viewed`.
  - **THEN:** The system opens the corresponding content page.

## REQ-8 Favorites

Allow shelves, books, chapters, and pages to be favorited and displayed in the `My Most Viewed Favorites` list on the homepage, with up to four items. A dedicated favorites page is available for viewing the complete list. Favorites page ![image](./reference/favourites.png)

**Type:** FOLDER
**Dependencies:** REQ-4, REQ-5, REQ-6

### REQ-8.1 Favorite Items

Add supported content items to the favorites list. The current content page contains exactly one button named `Favorite` with aria-pressed=false. Activating it changes the same control to name `Unfavorite` with aria-pressed=true. Seed data: book "Book 8.1".

**Type:** ATOMIC
**Dependencies:** REQ-4.2.1, REQ-5.2.1, REQ-6.3.1, REQ-6.2.1

**Scenarios:**

- Favorite Items
  - **GIVEN:** The user is on a supported shelf, book, chapter, or page view.
  - **WHEN:** The user activates the unique button named `Favorite` for the current content item.
  - **THEN:** The system adds the item to the favorites list and changes the control to `Unfavorite` with aria-pressed=true.

### REQ-8.2 Quick Navigation from Favorites

Open a content page from a favorites list entry. Seed data: book "Book 8.2"; verified account with nickname "BookStack User", email "bookstack_user@example.com", and password "Password123!".

**Type:** ATOMIC
**Dependencies:** REQ-8.1

**Scenarios:**

- Quick Navigation from Favorites
  - **GIVEN:** The authenticated homepage or favorites page shows at least one favorite item.
  - **WHEN:** The user activates the unique link or button named after the target item in `My Most Viewed Favorites`.
  - **THEN:** The system opens the corresponding content page.

## REQ-9 Recently Updated Pages

Show recently created or edited pages on the homepage, with up to five items.

**Type:** FOLDER
**Dependencies:** REQ-6.1

### REQ-9.1 Quick Navigation from Recently Updated

Open a page from the recently updated pages list. Seed data: book "Book 9.1".

**Type:** ATOMIC
**Dependencies:** REQ-6.1.1

**Scenarios:**

- Quick Navigation from Recently Updated
  - **GIVEN:** The homepage shows `Recently Updated Pages` with at least one item.
  - **WHEN:** The user activates the unique link or button named after the target page in the `Recently Updated Pages` list.
  - **THEN:** The system opens the reading page for the selected page.
