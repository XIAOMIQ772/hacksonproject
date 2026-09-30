import { test, expect } from '@playwright/test';
import * as h from './helpers';

const tab = (page: import('@playwright/test').Page, name: string) => page.getByRole('tab', { name, exact: true });

test.describe('REQ-2-1-1 Add a worksheet', () => {
  test('REQ-2-1-1 #1 blank workbook adds Sheet2 as active blank tab', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'New blank workbook' }).click();
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(tab(page, 'Sheet1')).toBeVisible();
    await h.setCell(page, 'A1', 'East');
    await page.getByRole('button', { name: 'Add worksheet' }).click();
    await expect(tab(page, 'Sheet2')).toHaveAttribute('aria-selected', 'true');
    await expect(h.cell(page, 'A1')).toHaveAttribute('aria-selected', 'true');
    await h.expectCell(page, 'A1', '');
    await h.reload(page);
    await expect(tab(page, 'Sheet2')).toHaveAttribute('aria-selected', 'true');
    await tab(page, 'Sheet1').click();
    await h.expectCell(page, 'A1', 'East');
  });

  test('REQ-2-1-1 #2 first unused SheetN is used', async ({ page }) => {
    await h.openWorkbook(page);
    await page.getByRole('button', { name: 'Add worksheet' }).click();
    await expect(tab(page, 'Sheet3')).toHaveAttribute('aria-selected', 'true');
    await h.tabMenu(page, 'Sheet2', 'Delete');
    await page.getByRole('dialog', { name: 'Delete worksheet' }).getByRole('button', { name: 'Delete worksheet' }).click();
    await expect(tab(page, 'Sheet2')).toHaveCount(0);
    await page.getByRole('button', { name: 'Add worksheet' }).click();
    await expect(tab(page, 'Sheet2')).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('tab')).toHaveText(['Sheet1', 'Sheet3', 'Sheet2']);
    await h.reload(page);
    await expect(page.getByRole('tab')).toHaveText(['Sheet1', 'Sheet3', 'Sheet2']);
    await tab(page, 'Sheet1').click();
    await h.expectCell(page, 'A2', 'East');
  });
});

test.describe('REQ-2-1-2 Switch worksheets', () => {
  test('REQ-2-1-2 #1 grid switches to target worksheet data', async ({ page }) => {
    await h.openWorkbook(page);
    await tab(page, 'Sheet2').click();
    await expect(tab(page, 'Sheet2')).toHaveAttribute('aria-selected', 'true');
    await h.expectCell(page, 'A1', '');
    await h.setCell(page, 'A1', 'North');
    await tab(page, 'Sheet1').click();
    await h.expectCell(page, 'A1', 'Region');
    await h.expectCell(page, 'A2', 'East');
  });

  test('REQ-2-1-2 #2 formula bar shows formula of selected cell per sheet', async ({ page }) => {
    await h.openWorkbook(page);
    await h.setCell(page, 'B5', '=B2+B3');
    await tab(page, 'Sheet2').click();
    await h.setCell(page, 'A1', '800');
    await expect(h.formulaBar(page)).toHaveValue('800');
    await tab(page, 'Sheet1').click();
    await h.expectCell(page, 'B5', '2000');
    await h.expectFormula(page, 'B5', '=B2+B3');
  });

  test('REQ-2-1-2 #3 per-sheet selection restored after switching and reopening', async ({ page }) => {
    await h.openWorkbook(page);
    await h.cell(page, 'B3').click();
    await tab(page, 'Sheet2').click();
    await expect(h.cell(page, 'A1')).toHaveAttribute('aria-selected', 'true');
    await h.cell(page, 'C2').click();
    await tab(page, 'Sheet1').click();
    await expect(h.cell(page, 'B3')).toHaveAttribute('aria-selected', 'true');
    await expect(h.formulaBar(page)).toHaveValue('800');
    await h.reload(page);
    await expect(tab(page, 'Sheet1')).toHaveAttribute('aria-selected', 'true');
    await expect(h.cell(page, 'B3')).toHaveAttribute('aria-selected', 'true');
    await tab(page, 'Sheet2').click();
    await expect(h.cell(page, 'C2')).toHaveAttribute('aria-selected', 'true');
  });

  test('REQ-2-1-2 #4 reopen shows last active tab', async ({ page }) => {
    await h.openWorkbook(page);
    await tab(page, 'Sheet2').click();
    await h.setCell(page, 'A1', 'Two');
    await page.goto('/');
    await page.getByRole('link', { name: 'Q3 Sales', exact: true }).click();
    await expect(tab(page, 'Sheet2')).toHaveAttribute('aria-selected', 'true');
    await h.expectCell(page, 'A1', 'Two');
  });

  test('REQ-2-1-2 #5 switching does not modify source sheet', async ({ page }) => {
    await h.openWorkbook(page);
    await h.cell(page, 'A2').click();
    await h.formulaBar(page).fill('Changed');
    await tab(page, 'Sheet2').click();
    await tab(page, 'Sheet1').click();
    await h.reload(page);
    await h.expectCell(page, 'A3', 'North');
    await h.expectCell(page, 'B2', '1200');
  });
});

test.describe('REQ-2-1-3 Rename a worksheet', () => {
  test('REQ-2-1-3 #1 rename successfully', async ({ page }) => {
    await h.openWorkbook(page);
    await h.tabMenu(page, 'Sheet1', 'Rename');
    const dlg = page.getByRole('dialog', { name: 'Rename worksheet' });
    await expect(dlg.getByRole('textbox', { name: 'Worksheet name' })).toHaveValue('Sheet1');
    await dlg.getByRole('textbox', { name: 'Worksheet name' }).fill('  Sales Data  ');
    await dlg.getByRole('button', { name: 'Save' }).click();
    await expect(tab(page, 'Sales Data')).toHaveAttribute('aria-selected', 'true');
    await h.reload(page);
    await expect(tab(page, 'Sales Data')).toBeVisible();
    await h.expectCell(page, 'A1', 'Region');
  });

  test('REQ-2-1-3 #2 empty name rejected', async ({ page }) => {
    await h.openWorkbook(page);
    await h.tabMenu(page, 'Sheet2', 'Rename');
    const dlg = page.getByRole('dialog', { name: 'Rename worksheet' });
    await dlg.getByRole('textbox', { name: 'Worksheet name' }).fill('   ');
    await dlg.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('Worksheet name cannot be empty')).toBeVisible();
    await h.reload(page);
    await expect(tab(page, 'Sheet2')).toBeVisible();
  });

  test('REQ-2-1-3 #3 duplicate name rejected', async ({ page }) => {
    await h.openWorkbook(page);
    await h.tabMenu(page, 'Sheet2', 'Rename');
    const dlg = page.getByRole('dialog', { name: 'Rename worksheet' });
    await dlg.getByRole('textbox', { name: 'Worksheet name' }).fill('Sheet1');
    await dlg.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('Worksheet name already exists')).toBeVisible();
    await h.reload(page);
    await expect(page.getByRole('tab')).toHaveText(['Sheet1', 'Sheet2']);
  });
});

test.describe('REQ-2-1-4 Delete a worksheet', () => {
  test('REQ-2-1-4 #1 delete Sheet2 after confirmation', async ({ page }) => {
    await h.openWorkbook(page);
    await tab(page, 'Sheet2').click();
    await h.setCell(page, 'A1', 'Temp');
    await h.tabMenu(page, 'Sheet2', 'Delete');
    const dlg = page.getByRole('dialog', { name: 'Delete worksheet' });
    await expect(dlg.getByText(/Sheet2/)).toBeVisible();
    await dlg.getByRole('button', { name: 'Delete worksheet' }).click();
    await expect(tab(page, 'Sheet2')).toHaveCount(0);
    await expect(tab(page, 'Sheet1')).toHaveAttribute('aria-selected', 'true');
    await h.reload(page);
    await expect(tab(page, 'Sheet2')).toHaveCount(0);
    await h.expectCell(page, 'A1', 'Region');
  });

  test('REQ-2-1-4 #2 last worksheet cannot be deleted', async ({ page }) => {
    await h.openWorkbook(page);
    await h.tabMenu(page, 'Sheet2', 'Delete');
    await page.getByRole('dialog', { name: 'Delete worksheet' }).getByRole('button', { name: 'Delete worksheet' }).click();
    await h.tabMenu(page, 'Sheet1', 'Delete');
    await expect(page.getByText('A workbook must contain at least one worksheet')).toBeVisible();
    await expect(page.getByRole('dialog', { name: 'Delete worksheet' })).toHaveCount(0);
    await h.reload(page);
    await expect(tab(page, 'Sheet1')).toBeVisible();
  });

  test('REQ-2-1-4 #3 pivot source worksheet cannot be deleted', async ({ page }) => {
    await h.openWorkbook(page);
    await h.createPivot(page);
    await h.applyPivot(page, 'Region', 'Sales', 'SUM');
    await h.expectCell(page, 'B2', '1200');
    await h.tabMenu(page, 'Sheet1', 'Delete');
    await page.getByRole('dialog', { name: 'Delete worksheet' }).getByRole('button', { name: 'Delete worksheet' }).click();
    await expect(page.getByText('Please delete or rebuild dependent pivot tables first')).toBeVisible();
    await expect(page.getByRole('dialog', { name: 'Delete worksheet' })).toHaveCount(0);
    await h.reload(page);
    await expect(tab(page, 'Sheet1')).toBeVisible();
    await h.expectCell(page, 'B2', '1200');
  });

  test('REQ-2-1-4 #4 deleting pivot sheet releases the source', async ({ page }) => {
    await h.openWorkbook(page);
    await h.createPivot(page);
    await h.applyPivot(page, 'Region', 'Sales', 'SUM');
    await h.tabMenu(page, 'Pivot1', 'Delete');
    await page.getByRole('dialog', { name: 'Delete worksheet' }).getByRole('button', { name: 'Delete worksheet' }).click();
    await expect(tab(page, 'Pivot1')).toHaveCount(0);
    await h.tabMenu(page, 'Sheet1', 'Delete');
    await page.getByRole('dialog', { name: 'Delete worksheet' }).getByRole('button', { name: 'Delete worksheet' }).click();
    await expect(tab(page, 'Sheet1')).toHaveCount(0);
    await expect(tab(page, 'Sheet2')).toHaveAttribute('aria-selected', 'true');
    await h.reload(page);
    await expect(page.getByRole('tab')).toHaveText(['Sheet2']);
  });
});

test.describe('REQ-2-2-1 Insert and delete rows', () => {
  test('REQ-2-2-1 #1 insert 1 row above row 3 shifts data and formulas', async ({ page }) => {
    await h.openWorkbook(page);
    await h.setCell(page, 'D1', '=B3*2');
    await h.rowMenu(page, '3', 'Insert 1 row above');
    await h.expectCell(page, 'A3', '');
    await h.expectCell(page, 'A4', 'North');
    await h.expectCell(page, 'B4', '800');
    await h.expectCell(page, 'D1', '1600');
    await h.expectFormula(page, 'D1', '=B4*2');
    await h.reload(page);
    await h.expectCell(page, 'A4', 'North');
    await h.expectFormula(page, 'D1', '=B4*2');
  });

  test('REQ-2-2-1 #2 insert 1 row below row 3', async ({ page }) => {
    await h.openWorkbook(page);
    await h.setCell(page, 'B6', '=SUM(B2:B4)');
    await h.rowMenu(page, '3', 'Insert 1 row below');
    await h.expectCell(page, 'A3', 'North');
    await h.expectCell(page, 'A4', '');
    await h.expectCell(page, 'A5', 'South');
    await h.expectFormula(page, 'B7', '=SUM(B2:B5)');
    await h.expectCell(page, 'B7', '2700');
    await h.reload(page);
    await h.expectCell(page, 'A5', 'South');
  });

  test('REQ-2-2-1 #3 delete row shifts up and adjusts formulas', async ({ page }) => {
    await h.openWorkbook(page);
    await h.setCell(page, 'D4', '=B4+1');
    await h.rowMenu(page, '2', 'Delete row');
    await h.expectCell(page, 'A2', 'North');
    await h.expectCell(page, 'A3', 'South');
    await h.expectFormula(page, 'D3', '=B3+1');
    await h.expectCell(page, 'D3', '701');
    await h.reload(page);
    await h.expectCell(page, 'A2', 'North');
  });

  test('REQ-2-2-1 #4 deleting a referenced row shows #REF!', async ({ page }) => {
    await h.openWorkbook(page);
    await h.setCell(page, 'D1', '=B3');
    await h.rowMenu(page, '3', 'Delete row');
    await h.expectCell(page, 'D1', '#REF!');
    await h.reload(page);
    await h.expectCell(page, 'D1', '#REF!');
    await h.expectCell(page, 'A3', 'South');
  });

  test('REQ-2-2-1 #5 shifted numeric validation keeps rejecting', async ({ page }) => {
    await h.openWorkbook(page);
    await h.addNumberRule(page, 'D2', 'D3', '0', '100');
    await h.rowMenu(page, '2', 'Insert 1 row above');
    await h.setCell(page, 'D3', '101');
    await expect(page.getByText('Please enter a number from 0 to 100')).toBeVisible();
    await h.expectCell(page, 'D3', '');
    await h.setCell(page, 'D2', '101');
    await h.expectCell(page, 'D2', '101');
    await h.reload(page);
    await h.setCell(page, 'D4', '500');
    await expect(page.getByText('Please enter a number from 0 to 100')).toBeVisible();
    await h.expectCell(page, 'D4', '');
  });
});

test.describe('REQ-2-2-2 Insert and delete columns', () => {
  test('REQ-2-2-2 #1 insert 1 column left of B', async ({ page }) => {
    await h.openWorkbook(page);
    await h.setCell(page, 'E1', '=B2+B3');
    await h.colMenu(page, 'B', 'Insert 1 column left');
    await h.expectCell(page, 'B2', '');
    await h.expectCell(page, 'C2', '1200');
    await h.expectCell(page, 'D1', 'Status');
    await h.expectFormula(page, 'F1', '=C2+C3');
    await h.expectCell(page, 'F1', '2000');
    await h.reload(page);
    await h.expectCell(page, 'C1', 'Sales');
  });

  test('REQ-2-2-2 #2 insert 1 column right of B', async ({ page }) => {
    await h.openWorkbook(page);
    await h.colMenu(page, 'B', 'Insert 1 column right');
    await h.expectCell(page, 'B1', 'Sales');
    await h.expectCell(page, 'C1', '');
    await h.expectCell(page, 'D1', 'Status');
    await h.reload(page);
    await h.expectCell(page, 'D2', 'Open');
  });

  test('REQ-2-2-2 #3 delete column B shows #REF! for direct refs', async ({ page }) => {
    await h.openWorkbook(page);
    await h.setCell(page, 'E1', '=B2');
    await h.setCell(page, 'E2', '=C2');
    await h.colMenu(page, 'B', 'Delete column');
    await h.expectCell(page, 'B1', 'Status');
    await h.expectCell(page, 'D1', '#REF!');
    await h.expectCell(page, 'D2', 'Open');
    await h.expectFormula(page, 'D2', '=B2');
    await h.reload(page);
    await h.expectCell(page, 'D1', '#REF!');
    await h.expectCell(page, 'A2', 'East');
  });

  test('REQ-2-2-2 #4 validation moves with column', async ({ page }) => {
    await h.openWorkbook(page);
    await h.addNumberRule(page, 'D2', 'D4', '0', '100');
    await h.colMenu(page, 'A', 'Insert 1 column left');
    await h.setCell(page, 'E3', '101');
    await expect(page.getByText('Please enter a number from 0 to 100')).toBeVisible();
    await h.expectCell(page, 'E3', '');
    await h.reload(page);
    await h.setCell(page, 'E2', '50');
    await h.expectCell(page, 'E2', '50');
  });

  test('REQ-2-2-2 #5 pivot refresh after deleting a selected source header', async ({ page }) => {
    await h.openWorkbook(page);
    await h.createPivot(page);
    await h.applyPivot(page, 'Region', 'Sales', 'SUM');
    await page.getByRole('tab', { name: 'Sheet1' }).click();
    await h.colMenu(page, 'B', 'Delete column');
    await page.getByRole('tab', { name: 'Pivot1' }).click();
    await h.expectCell(page, 'B2', '1200');
    await page.getByRole('button', { name: 'Refresh pivot table' }).click();
    await expect(page.getByText('Pivot field is no longer available. Select a new field.')).toBeVisible();
    await h.expectCell(page, 'B2', '1200');
    await page.getByRole('tab', { name: 'Sheet1' }).click();
    await h.expectCell(page, 'B1', 'Status');
  });
});
