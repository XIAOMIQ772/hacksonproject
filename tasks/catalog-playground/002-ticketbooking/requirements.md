# Railway Ticket Booking Demo

A small website where visitors can register or sign in, search published trains, select a journey, and create a booking. Accounts, sessions, and confirmed bookings persist. Payment, cancellation, refunds, seat inventory, order history, and timetable administration are outside scope.

## REQ-1 Public home page and account access

The public header provides Register and Login when signed out, and the username and Sign out when signed in. Registration creates an account and session; login restores a session for an existing account.

**Type:** FOLDER
**Dependencies:** None

### REQ-1.1 Register a traveler account

Function: Register displays Nationality, Name, Passport number, Passport expiration date, Date of birth, Gender, Username, Email address, Password, Confirm password, a Terms of service/Privacy policy checkbox, and Next step. All fields are required. Name must contain 2–100 non-whitespace characters; passport number must contain 6–30 ASCII letters, digits, or hyphens; birth date must be in the past and passport expiration in the future. Username must be 3–32 ASCII letters, digits, hyphens, or underscores. Email must be valid and at most 254 characters. Password must be 12–128 characters and include uppercase, lowercase, digit, and special characters; confirmation must match. Username and email are unique, with email compared case-insensitively. A valid submission saves the account, signs the user in, and returns home. Invalid or duplicate input shows an error and creates no account or session.

Required system data: The system must allow creation of independent accounts with username `tb-user-<timestamp>-<random>`, an email generated from that username using a valid domain, password `Valid-password-123!`, name `Ticket User <timestamp>-<random>`, nationality `Vietnam`, passport number `P<timestamp-digits>`, passport expiration date `2035-12-31`, date of birth `1995-06-15`, and gender `Male`. Duplicate-account examples reuse the same username or email. Invalid examples include username `bad username!`, email `not-an-email`, password `short`, a mismatched confirmation, a missing passport number, and unchecked terms.

Optional visual reference: ![image](./reference/register.png)

**Type:** ATOMIC
**Dependencies:** None

**Scenarios:**

- Register a valid traveler
  - **GIVEN:** A signed-out visitor has unique valid account and traveler details.
  - **WHEN:** The visitor completes Register, accepts the terms, and clicks Next step.
  - **THEN:** The home page shows the username and Sign out, including after reload.
- Reject invalid or duplicate details
  - **GIVEN:** Registration contains missing, malformed, mismatched, or already-used values.
  - **WHEN:** The visitor clicks Next step.
  - **THEN:** Register shows the relevant error and no signed-in session is created.

### REQ-1.2 Sign in with an existing account

Function: Login provides Username or email, Password, and Login controls. The identifier is trimmed; email matching is case-insensitive and the password must match exactly. Valid credentials create a reload-persistent session and return home. Empty, unknown, or incorrect credentials show one generic error and leave the visitor signed out.

Required system data: The system must contain an account created through REQ-1.1 with username `tb-user-<timestamp>-<random>`, an email generated from that username using a valid domain, and password `Valid-password-123!`. Valid login examples use that username or email, including values with leading and trailing spaces. Invalid examples use password `incorrect-password` or an email that does not belong to any account.

Optional visual reference: ![image](./reference/login.png)

**Type:** ATOMIC
**Dependencies:** REQ-1.1

**Scenarios:**

- Sign in with username or email
  - **GIVEN:** A saved account exists and the visitor is signed out.
  - **WHEN:** The visitor submits its username or email, optionally surrounded by spaces, and the correct password.
  - **THEN:** The home page shows the saved username and Sign out, including after reload.
- Reject invalid credentials
  - **GIVEN:** The identifier or password is missing or incorrect.
  - **WHEN:** The visitor clicks Login.
  - **THEN:** Login shows a generic error without revealing whether the account exists.

## REQ-2 Search trains and select a journey

Any visitor can search the timetable by origin, destination, and date. Results show matching trains and allow one journey to be opened for booking. Searching does not create an account or booking.

**Type:** FOLDER
**Dependencies:** None

### REQ-2.1 Search valid criteria and show matching trains

Function: The home page provides required From, To, Date, and Search controls. Values are trimmed; From and To must differ case-insensitively, and Date must use a published date value. A valid search opens results showing the normalized criteria, result count, and matching train cards with train number, route, times, and Book. Each Book action has an accessible name identifying its train number. Invalid input stays on the home page with an error.

Required system data: The system must contain a bookable train `G532` from `Shanghai` to `Beijing` on `Sun, May 31`, with Shanghai/ShanghaiHongqiao as its displayed departure location and Beijing/BeijingNan as its displayed arrival location. It must also contain a bookable train `G561` from `Beijing` to `Tianjin` on the same date. Both records must have stable displayed departure and arrival times. Invalid search examples omit From, To, or Date, or use `Shanghai` and ` shanghai ` as the same-city pair.

Optional visual reference: ![image](./reference/search-form.png) ![image](./reference/search-results.png)

**Type:** ATOMIC
**Dependencies:** None

**Scenarios:**

- Show matching trains
  - **GIVEN:** The timetable contains a train matching the entered route and date.
  - **WHEN:** The visitor searches with valid criteria, optionally surrounded by spaces.
  - **THEN:** Results show normalized criteria and only the matching train cards.
- Reject invalid criteria
  - **GIVEN:** A field is missing, the cities are equal, or the date is invalid.
  - **WHEN:** The visitor clicks Search.
  - **THEN:** The home page shows an error and no result list.
- Normalize criteria and routes
  - **GIVEN:** The timetable contains more than one supported route and the visitor may enter surrounding whitespace or a same-city route.
  - **WHEN:** The visitor searches each supported route with normalized or invalid criteria.
  - **THEN:** Valid routes show only their matching train, while same-city and incomplete searches remain on the homepage with an error.

### REQ-2.2 Select a train and open its booking entry

Function: Clicking the Book action identified by a train number opens the booking entry for that exact train and searched date, showing its train number, route, and times. The system must not substitute another result.

Required system data: The system must provide the two bookable records defined in REQ-2.1: `G532` for `Shanghai` to `Beijing` and `G561` for `Beijing` to `Tianjin`, both on `Sun, May 31`.

Optional visual reference: ![image](./reference/search-results.png) ![image](./reference/booking-page.png)

**Type:** ATOMIC
**Dependencies:** REQ-2.1

**Scenarios:**

- Open the selected train
  - **GIVEN:** Search results contain a bookable train.
  - **WHEN:** The visitor clicks that train's Book button.
  - **THEN:** The booking entry shows the same train, route, times, and date.
- Open each supported route
  - **GIVEN:** Search results contain either supported bookable route.
  - **WHEN:** The visitor clicks Book on the selected train.
  - **THEN:** The booking page preserves the exact train and date for that route.

## REQ-3 Create and view a booking

A signed-in user can review the selected train, enter passenger and ticket details, and confirm one persistent booking. Invalid or unauthorized actions create no booking.

**Type:** FOLDER
**Dependencies:** REQ-1, REQ-2

### REQ-3.1 Display a selected train on the protected booking page

Function: For a signed-in user, the Booking page shows the selected train number, route, times, and date above Passenger information and the booking form. Opening the page is read-only. A signed-out visitor must sign in and cannot submit; missing or unavailable train context shows the REQ-2.2 error instead of the form.

Required system data: The system must allow creation of a unique REQ-1.1 account and provide the bookable `G532` (`Shanghai` to `Beijing`) and `G561` (`Beijing` to `Tianjin`) journeys on `Sun, May 31`. The selected train summary must display the corresponding train number, cities or stations, times, and date. The signed-out case uses the same valid selected journey after the account signs out.

**Type:** ATOMIC
**Dependencies:** REQ-1.2, REQ-2.2

**Scenarios:**

- Show the selected journey
  - **GIVEN:** A signed-in traveler selected a published train.
  - **WHEN:** The Booking page opens.
  - **THEN:** It shows the selected train summary and Passenger information without creating a booking.
- Block a signed-out visitor
  - **GIVEN:** A visitor has a valid selected journey but no session.
  - **WHEN:** The visitor opens its booking page.
  - **THEN:** The page requests sign-in and provides no working submission action.
- Preserve summaries across journeys
  - **GIVEN:** A signed-in traveler opens booking entries for different supported trains.
  - **WHEN:** The traveler changes the selected journey before submitting.
  - **THEN:** Each booking page shows the corresponding train summary without mixing route or date data.

### REQ-3.2 Confirm passenger details and create one booking record

Function: The booking form requires Passenger name, ID number, Nationality, Ticket class, Ticket type, and Terms of service acceptance. Trimmed name and nationality must contain 2–100 and 2–60 visible characters; ID number must contain 6–30 ASCII letters, digits, or hyphens. Place order opens a summary; Confirm creates exactly one booking and shows its booking number and submitted details. Invalid fields create no booking, and repeated confirmation or reload must keep the same record.

Required system data: Each booking example uses a unique REQ-1.1 account and an independent selected journey. The system must provide `G532` from `Shanghai` to `Beijing` and `G561` from `Beijing` to `Tianjin` on `Sun, May 31`. Valid booking data is (1) passenger `Nguyen Duc Minh`, ID `C612345677`, nationality `Vietnam`, class `standing ticket`, type `Adult`; and (2) passenger `Chen Li`, ID `D712345678`, nationality `Vietnam`, class `Business Class`, type `Adult`. Invalid examples use name `A`, ID `12345`, an empty nationality, or unchecked terms. Ticket class and type are selected explicitly rather than relying on defaults. Confirmation state and booking IDs must remain independent between accounts.

Optional visual reference: ![image](./reference/booking-page.png)

**Type:** ATOMIC
**Dependencies:** REQ-3.1

**Scenarios:**

- Create one valid booking
  - **GIVEN:** A signed-in traveler has an isolated account and selected journey.
  - **WHEN:** The traveler enters valid details, accepts the terms, reviews the summary, and confirms.
  - **THEN:** One booking number and the submitted journey, passenger, and ticket details are shown and persist after reload.
- Reject invalid passenger details
  - **GIVEN:** A required field is missing or invalid, or terms are not accepted.
  - **WHEN:** The traveler clicks Place order.
  - **THEN:** The form shows an error and opens neither the confirmation summary nor a booking.
- Prevent duplicate confirmation
  - **GIVEN:** A valid confirmation has already succeeded.
  - **WHEN:** The traveler repeats Confirm or reloads the completed page.
  - **THEN:** The original booking number remains and no second booking is created.
- Create supported ticket variants
  - **GIVEN:** A signed-in traveler selects a supported route and ticket class such as standing ticket or Business Class.
  - **WHEN:** The traveler submits valid passenger details and confirms the order.
  - **THEN:** One booking is created with the selected route, class, and passenger details.
- Reject short passenger values
  - **GIVEN:** Passenger name or ID is shorter than the documented minimum.
  - **WHEN:** The traveler attempts to place the order.
  - **THEN:** Validation errors are shown and no booking or confirmation summary is created.
