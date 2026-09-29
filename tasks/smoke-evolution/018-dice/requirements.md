# ARC Dice Evolution Smoke Test

Extend the existing dice application with a roll counter without breaking its six-sided roll behavior.

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

## REQ-2 Count completed rolls

Display the number of completed rolls with the test id "roll-count". The roll count starts at 0 and increases by one each time Roll is clicked.

**Type:** ATOMIC
**Dependencies:** REQ-1

**Scenarios:**

- Display and update the roll count
  - **GIVEN:** The visitor opens the home page and the roll count is 0.
  - **WHEN:** The visitor clicks Roll twice.
  - **THEN:** The roll count is 2 and the dice value displays an integer from 1 through 6.
