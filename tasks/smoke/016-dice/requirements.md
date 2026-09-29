# ARC Dice Smoke Test

Use ARC to build an extremely small dice application for verifying the metered competition submission and leaderboard pipeline.

## REQ-1 Roll a six-sided die

The home page displays a button named "Roll" and a dice value with the test id "dice-value". Clicking Roll chooses an integer from 1 through 6 and displays it. No styling or layout is required.

**Type:** ATOMIC
**Dependencies:** None

**Scenarios:**

- Roll and display a dice value
  - **GIVEN:** The visitor opens the home page.
  - **THEN:** A button named "Roll" is visible.
  - **WHEN:** The visitor clicks Roll.
  - **THEN:** The dice value displays an integer from 1 through 6.
