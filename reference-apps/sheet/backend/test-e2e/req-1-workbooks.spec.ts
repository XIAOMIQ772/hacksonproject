import { test, expect } from '@playwright/test';
import * as h from './helpers';

test.describe('REQ-1-1-1 View and open a workbook', () => {
  test('REQ-1-1-1 #1 open seeded workbook from home, same state after refresh', async ({ page }) => {
    await page.goto('/');
    const row = page.getByRole('listitem').filter({ has: page.getByRole('link', { name: 'Q3 Sales', exact: true }) });
    const updated = (await row.getByText(/Last updated: /).textContent())!.trim();
    await page.getByRole('link', { name: 'Q3 Sales', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Q3 Sales' })).toBeVisible();
    await expect(page.getByText(updated)).toBeVisible();
    await expect(page.getByRole('tab', { name: 'Sheet1' })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('tab', { name: 'Sheet2' })).toHaveAttribute('aria-selected', 'false');
    await expect(h.grid(page)).toHaveAttribute('aria-multiselectable', 'true');
    await h.expectCell(page, 'A1', 'Region');
    await expect(h.cell(page, 'A1')).toHaveAttribute('aria-selected', 'true');
    await expect(h.formulaBar(page)).toHaveValue('Region');
    await h.reload(page);
    await expect(page.getByRole('heading', { name: 'Q3 Sales' })).toBeVisible();
    await h.expectCell(page, 'A1', 'Region');
    await expect(page.getByText(updated)).toBeVisible();
  });

  test('REQ-1-1-1 #2 editor entry is directly accessible in a later session', async ({ page, browser }) => {
    await h.openWorkbook(page);
    await h.setCell(page, 'A5', 'West');
    await page.waitForTimeout(200);
    const url = page.url();
    const ctx = await browser.newContext();
    const p2 = await ctx.newPage();
    await p2.goto(url);
    await expect(p2.getByRole('heading', { name: 'Q3 Sales' })).toBeVisible();
    await expect(h.cell(p2, 'A1')).toHaveText('Region');
    await expect(h.cell(p2, 'A5')).toHaveText('West');
    await p2.goto('/');
    await expect(p2.getByRole('link', { name: 'Q3 Sales', exact: true })).toHaveCount(1);
    await ctx.close();
  });
});

test.describe('REQ-1-2-1 Create a blank workbook', () => {
  test('REQ-1-2-1 #1 create blank workbook with Sheet1 and A1 selected', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'New blank workbook' }).click();
    await page.getByLabel('Workbook name').fill('Budget 2026');
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page.getByRole('heading', { name: 'Budget 2026' })).toBeVisible();
    await expect(page.getByRole('tab')).toHaveCount(1);
    await expect(page.getByRole('tab', { name: 'Sheet1' })).toHaveAttribute('aria-selected', 'true');
    await expect(h.cell(page, 'A1')).toHaveAttribute('aria-selected', 'true');
    await h.expectCell(page, 'A1', '');
    await h.reload(page);
    await expect(page.getByRole('tab', { name: 'Sheet1' })).toHaveAttribute('aria-selected', 'true');
    await expect(h.cell(page, 'A1')).toHaveAttribute('aria-selected', 'true');
    await page.goto('/');
    await expect(page.getByRole('link', { name: 'Budget 2026', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Q3 Sales', exact: true })).toBeVisible();
  });
});

test.describe('REQ-1-2-2 Rename a workbook', () => {
  test('REQ-1-2-2 #1 rename trims and updates title and home link', async ({ page }) => {
    await h.openWorkbook(page);
    await page.getByRole('button', { name: 'Rename workbook' }).click();
    const box = page.getByRole('textbox', { name: 'Workbook name' });
    await expect(box).toHaveValue('Q3 Sales');
    await box.fill('  Q3 Sales Final  ');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByRole('heading', { name: 'Q3 Sales Final' })).toBeVisible();
    await h.reload(page);
    await expect(page.getByRole('heading', { name: 'Q3 Sales Final' })).toBeVisible();
    await page.goto('/');
    await expect(page.getByRole('link', { name: 'Q3 Sales Final', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Q3 Sales', exact: true })).toHaveCount(0);
  });

  test('REQ-1-2-2 #2 empty name rejected and original kept', async ({ page }) => {
    await h.openWorkbook(page);
    await page.getByRole('button', { name: 'Rename workbook' }).click();
    await page.getByRole('textbox', { name: 'Workbook name' }).fill('   ');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('Workbook name cannot be empty')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Q3 Sales' })).toBeVisible();
    await h.reload(page);
    await expect(page.getByRole('heading', { name: 'Q3 Sales' })).toBeVisible();
    await page.goto('/');
    await expect(page.getByRole('link', { name: 'Q3 Sales', exact: true })).toBeVisible();
  });
});

async function importCsv(page: import('@playwright/test').Page, name: string, content: string) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Import CSV' }).click();
  const dlg = page.getByRole('dialog', { name: 'Import CSV' });
  await dlg.getByLabel('CSV file').setInputFiles({ name, mimeType: 'text/csv', buffer: Buffer.from(content, 'utf-8') });
  await dlg.getByRole('button', { name: 'Confirm import' }).click();
}

test.describe('REQ-1-3-1 Import CSV', () => {
  test('REQ-1-3-1 #1 UTF-8 CSV with Chinese and numeric text', async ({ page }) => {
    await importCsv(page, '区域销售.csv', '地区,销售额,Status\n华东,1200,Open\n华北,800,Closed\n');
    await expect(page.getByRole('heading', { name: '区域销售' })).toBeVisible();
    await expect(page.getByRole('tab', { name: 'Sheet1' })).toHaveAttribute('aria-selected', 'true');
    await h.expectCell(page, 'A1', '地区');
    await h.expectCell(page, 'B2', '1200');
    await h.expectCell(page, 'C3', 'Closed');
    await h.reload(page);
    await h.expectCell(page, 'A2', '华东');
    await page.goto('/');
    await expect(page.getByRole('link', { name: '区域销售', exact: true })).toBeVisible();
  });

  test('REQ-1-3-1 #2 quoted commas, escaped quotes and line breaks', async ({ page }) => {
    await importCsv(page, 'quotes.csv', 'Name,Note\n"Smith, John","He said ""hi"""\n"Multi\nline",x\n');
    await h.expectCell(page, 'A2', 'Smith, John');
    await h.expectCell(page, 'B2', 'He said "hi"');
    await h.cell(page, 'A3').click();
    await expect(h.formulaBar(page)).toHaveValue('Multi\nline');
    await h.reload(page);
    await h.expectCell(page, 'B2', 'He said "hi"');
  });

  test('REQ-1-3-1 #3 invalid CSV rejected with no workbook created', async ({ page }) => {
    await importCsv(page, 'broken.csv', 'a,b\n"unterminated,c\n');
    await expect(page.getByText('Invalid CSV file format. Import failed.')).toBeVisible();
    await page.goto('/');
    await expect(page.getByRole('link', { name: 'broken', exact: true })).toHaveCount(0);
  });

  test('REQ-1-3-1 #4 empty fields preserved, first row is data, final .csv stripped', async ({ page }) => {
    await importCsv(page, 'q3.backup.csv', 'Region,,Sales\n,East,\nNorth,,800\n');
    await expect(page.getByRole('heading', { name: 'q3.backup' })).toBeVisible();
    await h.expectCell(page, 'A1', 'Region');
    await h.expectCell(page, 'B1', '');
    await h.expectCell(page, 'C1', 'Sales');
    await h.expectCell(page, 'A2', '');
    await h.expectCell(page, 'B2', 'East');
    await h.expectCell(page, 'C3', '800');
    await h.reload(page);
    await h.expectCell(page, 'C1', 'Sales');
    await h.expectCell(page, 'B2', 'East');
  });
});

async function download(page: import('@playwright/test').Page) {
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Export CSV' }).click()]);
  expect(dl.suggestedFilename()).toMatch(/\.csv$/);
  const fs = await import('fs');
  return fs.readFileSync((await dl.path())!, 'utf-8');
}

test.describe('REQ-1-3-2 Export CSV', () => {
  test('REQ-1-3-2 #1 export seeded sheet', async ({ page }) => {
    await h.openWorkbook(page);
    const text = await download(page);
    expect(text.split(/\r?\n/)).toEqual(['Region,Sales,Status', 'East,1200,Open', 'North,800,Closed', 'South,700,Open']);
    await h.expectCell(page, 'A1', 'Region');
  });

  test('REQ-1-3-2 #2 formulas export results and escaping', async ({ page }) => {
    await h.openWorkbook(page);
    await h.setCell(page, 'D1', 'Note');
    await h.setCell(page, 'D2', 'a, "b"');
    await h.setCell(page, 'B5', '=SUM(B2:B4)');
    const text = await download(page);
    const lines = text.split(/\r?\n/);
    expect(lines[0]).toBe('Region,Sales,Status,Note');
    expect(lines[1]).toBe('East,1200,Open,"a, ""b"""');
    expect(lines[4]).toBe(',2700,,');
    await h.expectFormula(page, 'B5', '=SUM(B2:B4)');
  });

  test('REQ-1-3-2 #3 empty cells inside used range preserved', async ({ page }) => {
    await h.openWorkbook(page);
    await h.setCell(page, 'E6', 'End');
    const text = await download(page);
    const lines = text.split(/\r?\n/);
    expect(lines.length).toBe(6);
    expect(lines[5]).toBe(',,,,End');
    expect(lines[4]).toBe(',,,,');
  });

  test('REQ-1-3-2 #4 exports only the active Sheet2 and keeps state', async ({ page }) => {
    await h.openWorkbook(page);
    await page.getByRole('tab', { name: 'Sheet2' }).click();
    await h.setCell(page, 'A1', 'Only2');
    await h.cell(page, 'A1').click();
    const text = await download(page);
    expect(text.trim()).toBe('Only2');
    await expect(page.getByRole('tab', { name: 'Sheet2' })).toHaveAttribute('aria-selected', 'true');
    await expect(h.formulaBar(page)).toHaveValue('Only2');
    await h.reload(page);
    await expect(page.getByRole('tab', { name: 'Sheet2' })).toHaveAttribute('aria-selected', 'true');
  });
});
