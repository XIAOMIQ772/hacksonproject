import { test, expect, type Page } from '@playwright/test';
import * as h from './helpers';

async function items(page: Page) {
  await h.openWorkbook(page);
  await h.setCells(page, { A1: 'Item', B1: 'Qty', A2: 'Pen', B2: '4' });
}

test.describe('REQ-3-1-1 Edit a cell', () => {
  test('REQ-3-1-1 #1 edit in grid, commit with Enter and persist', async ({ page }) => {
    await items(page);
    await h.cell(page, 'A3').click();
    await page.keyboard.type('Pencil');
    await page.keyboard.press('Enter');
    await h.expectCell(page, 'A3', 'Pencil');
    await h.cell(page, 'B3').dblclick();
    await page.getByRole('textbox', { name: 'Edit B3' }).fill('TRUE');
    await h.cell(page, 'C3').click();
    await h.expectCell(page, 'B3', 'TRUE');
    await h.reload(page);
    await h.expectCell(page, 'A3', 'Pencil');
    await h.expectFormula(page, 'B3', 'TRUE');
  });

  test('REQ-3-1-1 #2 Escape cancels an uncommitted change', async ({ page }) => {
    await items(page);
    await h.cell(page, 'A2').dblclick();
    await page.getByRole('textbox', { name: 'Edit A2' }).fill('Marker');
    await page.getByRole('textbox', { name: 'Edit A2' }).press('Escape');
    await h.expectCell(page, 'A2', 'Pen');
    await h.cell(page, 'A2').click();
    await h.formulaBar(page).fill('Eraser');
    await h.formulaBar(page).press('Escape');
    await expect(h.formulaBar(page)).toHaveValue('Pen');
    await h.reload(page);
    await h.expectCell(page, 'A2', 'Pen');
  });

  test('REQ-3-1-1 #3 formula bar formula shows result in grid and formula in bar', async ({ page }) => {
    await items(page);
    await h.setViaFormulaBar(page, 'C2', '=B2*3');
    await h.expectCell(page, 'C2', '12');
    await expect(h.formulaBar(page)).toHaveValue('=B2*3');
    await h.setViaFormulaBar(page, 'D2', '2026-09-30');
    await h.expectCell(page, 'D2', '2026-09-30');
    await h.reload(page);
    await h.expectCell(page, 'C2', '12');
    await h.expectFormula(page, 'C2', '=B2*3');
  });

  test('REQ-3-1-1 #4 dependents update directly and indirectly', async ({ page }) => {
    await items(page);
    await h.setCell(page, 'C2', '=B2*2');
    await h.setCell(page, 'D2', '=C2+1');
    await h.setCell(page, 'B2', '10');
    await h.expectCell(page, 'C2', '20');
    await h.expectCell(page, 'D2', '21');
    await h.reload(page);
    await h.expectCell(page, 'D2', '21');
  });
});

test.describe('REQ-3-1-2 Paste table data', () => {
  test('REQ-3-1-2 #1 paste 2x2 block at B2', async ({ page }) => {
    await items(page);
    await h.pasteText(page, 'B2', 'East\t1200\nNorth\t800');
    await h.expectCell(page, 'B2', 'East');
    await h.expectCell(page, 'C2', '1200');
    await h.expectCell(page, 'B3', 'North');
    await h.expectCell(page, 'C3', '800');
    await h.expectCell(page, 'A2', 'Pen');
    await h.reload(page);
    await h.expectCell(page, 'C3', '800');
  });

  test('REQ-3-1-2 #2 empty fields overwrite target cells', async ({ page }) => {
    await items(page);
    await h.pasteText(page, 'A1', 'X\t\n\tY');
    await h.expectCell(page, 'A1', 'X');
    await h.expectCell(page, 'B1', '');
    await h.expectCell(page, 'A2', '');
    await h.expectCell(page, 'B2', 'Y');
    await h.reload(page);
    await h.expectCell(page, 'B1', '');
  });

  test('REQ-3-1-2 #3 paste replaces formulas and dependents recalc', async ({ page }) => {
    await items(page);
    await h.setCell(page, 'C1', '=B2*2');
    await h.setCell(page, 'C2', '=C1+1');
    await h.pasteText(page, 'B2', '5\t7');
    await h.expectCell(page, 'C2', '7');
    await h.expectCell(page, 'C1', '10');
    await h.expectFormula(page, 'C2', '7');
    await h.reload(page);
    await h.expectCell(page, 'C1', '10');
  });

  test('REQ-3-1-2 #4 context menu Paste at A1', async ({ page }) => {
    await items(page);
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
    await page.evaluate(() => navigator.clipboard.writeText('East\t1200\nNorth\t800'));
    await h.cell(page, 'A1').click({ button: 'right' });
    await page.getByRole('menuitem', { name: 'Paste' }).click();
    await h.expectCell(page, 'A1', 'East');
    await h.expectCell(page, 'B2', '800');
    await h.reload(page);
    await h.expectCell(page, 'A2', 'North');
  });

  test('REQ-3-1-2 #5 paste into C3 rejected by validation keeps all values', async ({ page }) => {
    await items(page);
    await h.addNumberRule(page, 'D3', 'D4', '0', '100');
    await h.pasteText(page, 'C3', 'a\t50\nb\t101');
    await expect(page.getByText('Please enter a number from 0 to 100')).toBeVisible();
    await h.expectCell(page, 'C3', 'Closed');
    await h.expectCell(page, 'D3', '');
    await h.expectCell(page, 'C4', 'Open');
    await h.reload(page);
    await h.expectCell(page, 'D3', '');
  });
});

test.describe('REQ-3-1-3 Select a rectangle', () => {
  test('REQ-3-1-3 #1 drag selection exposes aria-selected', async ({ page }) => {
    await items(page);
    await h.selectRange(page, 'A1', 'B2');
    await h.expectSelected(page, ['A1', 'A2', 'B1', 'B2'], ['C1', 'A3', 'C3', 'B3']);
    await h.selectRange(page, 'D1', 'E2');
    await h.expectSelected(page, ['D1', 'E2'], ['A1', 'B2']);
  });

  test('REQ-3-1-3 #2 selection persists per worksheet', async ({ page }) => {
    await items(page);
    await h.selectRange(page, 'B2', 'C4');
    await page.getByRole('tab', { name: 'Sheet2' }).click();
    await h.selectRange(page, 'A1', 'A3');
    await page.getByRole('tab', { name: 'Sheet1' }).click();
    await h.expectSelected(page, ['B2', 'C4', 'B4', 'C2'], ['A1', 'D4', 'B5']);
    await h.reload(page);
    await h.expectSelected(page, ['B2', 'C4', 'B4', 'C2', 'B3'], ['A1', 'D4', 'B5', 'A2']);
  });
});

test.describe('REQ-3-2-1 Copy, cut, paste ranges', () => {
  test('REQ-3-2-1 #1 copy A1:B2 to D1:E2 keeps source', async ({ page }) => {
    await items(page);
    await h.selectRange(page, 'A1', 'B2');
    await page.keyboard.press('ControlOrMeta+C');
    await h.cell(page, 'D1').click();
    await page.keyboard.press('ControlOrMeta+V');
    await h.expectCell(page, 'D1', 'Item');
    await h.expectCell(page, 'E2', '4');
    await h.expectCell(page, 'A1', 'Item');
    await h.reload(page);
    await h.expectCell(page, 'D2', 'Pen');
    await h.expectCell(page, 'B2', '4');
  });

  test('REQ-3-2-1 #2 cut A1:B2 to D1:E2 clears source', async ({ page }) => {
    await items(page);
    await h.setCell(page, 'A4', '=B2*10');
    await h.selectRange(page, 'A1', 'B2');
    await h.cell(page, 'A1').click({ button: 'right' });
    await page.getByRole('menuitem', { name: 'Cut' }).click();
    await h.cell(page, 'D1').click({ button: 'right' });
    await page.getByRole('menuitem', { name: 'Paste' }).click();
    await h.expectCell(page, 'D1', 'Item');
    await h.expectCell(page, 'E2', '4');
    await h.expectCell(page, 'A1', '');
    await h.expectCell(page, 'B2', '');
    await h.expectCell(page, 'A4', '40');
    await h.reload(page);
    await h.expectCell(page, 'A1', '');
    await h.expectCell(page, 'D2', 'Pen');
  });

  test('REQ-3-2-1 #3 copied formulas adjust relative refs only', async ({ page }) => {
    await items(page);
    await h.setCell(page, 'C2', '=B2*$B$2');
    await h.cell(page, 'C2').click();
    await page.keyboard.press('ControlOrMeta+C');
    await h.setCell(page, 'B3', '5');
    await h.cell(page, 'C3').click();
    await page.keyboard.press('ControlOrMeta+V');
    await h.expectCell(page, 'C3', '20');
    await h.expectFormula(page, 'C3', '=B3*$B$2');
    await h.expectFormula(page, 'C2', '=B2*$B$2');
    await h.reload(page);
    await h.expectCell(page, 'C3', '20');
  });

  test('REQ-3-2-1 #4 validation rejects paste into target', async ({ page }) => {
    await items(page);
    await h.setCell(page, 'B2', '400');
    await h.addNumberRule(page, 'E1', 'E2', '0', '100');
    await h.selectRange(page, 'A1', 'B2');
    await page.keyboard.press('ControlOrMeta+C');
    await h.cell(page, 'D1').click();
    await page.keyboard.press('ControlOrMeta+V');
    await expect(page.getByText('Please enter a number from 0 to 100')).toBeVisible();
    await h.expectCell(page, 'D1', '');
    await h.expectCell(page, 'E2', '');
    await h.reload(page);
    await h.expectCell(page, 'D2', '');
  });
});

test.describe('REQ-3-2-2 Undo and redo', () => {
  const undo = (page: Page) => page.getByRole('button', { name: 'Undo' }).click();
  const redo = (page: Page) => page.getByRole('button', { name: 'Redo' }).click();

  test('REQ-3-2-2 #1 undo a cell edit and persist', async ({ page }) => {
    await items(page);
    await h.setCell(page, 'B2', '9');
    await undo(page);
    await h.expectCell(page, 'B2', '4');
    await h.reload(page);
    await h.expectCell(page, 'B2', '4');
  });

  test('REQ-3-2-2 #2 redo reapplies', async ({ page }) => {
    await items(page);
    await h.setCell(page, 'B2', '9');
    await undo(page);
    await redo(page);
    await h.expectCell(page, 'B2', '9');
    await h.reload(page);
    await h.expectCell(page, 'B2', '9');
  });

  test('REQ-3-2-2 #3 consecutive undos in reverse order', async ({ page }) => {
    await items(page);
    await h.setCell(page, 'E1', 'one');
    await h.setCell(page, 'E2', 'two');
    await undo(page);
    await h.expectCell(page, 'E2', '');
    await h.expectCell(page, 'E1', 'one');
    await undo(page);
    await h.expectCell(page, 'E1', '');
  });

  test('REQ-3-2-2 #4 undo a bulk paste', async ({ page }) => {
    await items(page);
    await h.pasteText(page, 'A1', 'a\tb\nc\td');
    await h.expectCell(page, 'B2', 'd');
    await undo(page);
    await h.expectCell(page, 'A1', 'Item');
    await h.expectCell(page, 'B2', '4');
    await h.reload(page);
    await h.expectCell(page, 'A2', 'Pen');
  });

  test('REQ-3-2-2 #5 undo a row insertion restores structure and formulas', async ({ page }) => {
    await items(page);
    await h.setCell(page, 'C1', '=B2+1');
    await h.rowMenu(page, '2', 'Insert 1 row above');
    await h.expectCell(page, 'A3', 'Pen');
    await undo(page);
    await h.expectCell(page, 'A2', 'Pen');
    await h.expectFormula(page, 'C1', '=B2+1');
    await h.reload(page);
    await h.expectCell(page, 'A2', 'Pen');
  });

  test('REQ-3-2-2 #6 new edit after undo disables redo', async ({ page }) => {
    await items(page);
    await h.setCell(page, 'B2', '9');
    await undo(page);
    await expect(page.getByRole('button', { name: 'Redo' })).toBeEnabled();
    await h.setCell(page, 'B2', '7');
    await expect(page.getByRole('button', { name: 'Redo' })).toBeDisabled();
    await page.keyboard.press('Control+Y');
    await h.expectCell(page, 'B2', '7');
  });

  test('REQ-3-2-2 #7 Ctrl+Z and Ctrl+Y shortcuts', async ({ page }) => {
    await items(page);
    await h.setCell(page, 'A2', 'Ink');
    await h.cell(page, 'D5').click();
    await page.keyboard.press('Control+Z');
    await h.expectCell(page, 'A2', 'Pen');
    await page.keyboard.press('Control+Y');
    await h.expectCell(page, 'A2', 'Ink');
    await h.reload(page);
    await h.expectCell(page, 'A2', 'Ink');
  });
});
