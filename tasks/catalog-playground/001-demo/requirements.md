# Demo
A small web-based ticket booking system covering user authentication, train search and result display, and basic booking capabilities.

## REQ-1 Public Homepage and User Authentication
Defines the public homepage, shared navigation, authentication entry points, and session-related public APIs. This node can guide generation of the shared header, route entry points, login/register entry styling, and shared logic for session loading. Optional visual reference: ![image](./reference/homepage.png)

**Type:** FOLDER
**Dependencies:** None

### REQ-1.1 User Registration
An unauthenticated visitor can open the registration page, fill in username, email, password, and confirm password, and submit the registration form. The system must validate the input, create and persist a user account, establish a login session, and move the UI into an authenticated state after success. Invalid input or duplicate accounts must return explicit errors and must not create a new user record. Optional visual reference: ![image](./reference/register.png)

**Type:** ATOMIC
**Dependencies:** None

**Scenarios:**
- Successfully register a new user
  - **GIVEN:** The visitor is on a public page and is currently not logged in.
  - **WHEN:** The user opens the registration page, enters a unique username, a valid email, matching passwords, and submits the form.
  - **THEN:** The system creates and persists the new user, establishes a login session, and moves the UI into an authenticated state.
