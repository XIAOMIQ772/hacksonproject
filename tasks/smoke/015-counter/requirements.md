# ARC Counter Smoke Test

Use ARC to build an extremely small counter application for verifying the metered competition submission and leaderboard pipeline.

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
