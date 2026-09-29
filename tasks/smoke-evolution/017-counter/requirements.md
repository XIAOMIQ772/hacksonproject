# ARC Counter Evolution Smoke Test

Extend the existing counter application with a reset control without breaking its increment and decrement behavior.

## REQ-1 Counter controls

The home page displays the current count, initially 0, and buttons named "Increment" and "Decrement". Increment increases the displayed count by one and Decrement decreases it by one. The count display has the test id "count". No styling or layout is required.

**Type:** ATOMIC
**Dependencies:** None

**Scenarios:**

- Increment and decrement the count
  - **GIVEN:** The visitor opens the home page and the displayed count is 0.
  - **THEN:** Buttons named "Increment" and "Decrement" are visible.
  - **WHEN:** The visitor clicks Increment twice.
  - **THEN:** The displayed count is 2.
  - **WHEN:** The visitor clicks Decrement three times.
  - **THEN:** The displayed count is -1.

## REQ-2 Reset the counter

Add a button named "Reset" that sets the displayed count to 0 from any current value while preserving the existing counter controls.

**Type:** ATOMIC
**Dependencies:** REQ-1

**Scenarios:**

- Reset a changed count
  - **GIVEN:** The displayed count is not 0.
  - **WHEN:** The visitor clicks Reset.
  - **THEN:** The displayed count is 0.
