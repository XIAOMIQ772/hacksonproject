import { test, expect, type Page } from '@playwright/test';
import * as h from './helpers';

async function sortDialog(page: Page, from: string, to: string, by: string, order: string, header = true) {
  await h.selectRange(page, from, to);
  await h.dataMenu(page, 'Sort range');
  const dlg = page.getByRole('dialog', { name: 'Sort range' });
  await h.choose(dlg, 'Sort by', by);
  await h.choose(dlg, 'Order', order);
  const cb = dlg.getByRole('checkbox', { name: 'Data has header row' });
  if (header) await cb.check();
  else await cb.uncheck();
  await dlg.getByRole('button', { name: 'Sort' }).click();
  await expect(dlg).toBeHidden();
}

const col = async (page: Page, c: string, n: number) => {
  const out: string[] = [];
  for (let i = 1; i <= n; i++) out.push(((await h.cell(page, `${c}${i}`).textContent()) ?? '').trim());
  return out;
};

test.describe('REQ-5-1-1 Sort range', () => {
  test('REQ-5-1-1 #1 sort by Sales ascending with header row', async ({ page }) => {
    await h.openWorkbook(page);
    await sortDialog(page, 'A1', 'C4', 'Sales', 'Ascending');
    expect(await col(page, 'A', 4)).toEqual(['Region', 'South', 'North', 'East']);
    expect(await col(page, 'C', 4)).toEqual(['Status', 'Open', 'Closed', 'Open']);
    await h.reload(page);
    expect(await col(page, 'B', 4)).toEqual(['Sales', '700', '800', '1200']);
  });

  test('REQ-5-1-1 #2 ISO dates sort chronologically', async ({ page }) => {
    await h.openWorkbook(page);
    await h.setCells(page, { D1: 'Date', D2: '2024-03-01', D3: '2023-12-31', D4: '2024-01-15' });
    await sortDialog(page, 'A1', 'D4', 'Date', 'Ascending');
    expect(await col(page, 'D', 4)).toEqual(['Date', '2023-12-31', '2024-01-15', '2024-03-01']);
    expect(await col(page, 'A', 4)).toEqual(['Region', 'North', 'South', 'East']);
  });

  test('REQ-5-1-1 #3 descending text', async ({ page }) => {
    await h.openWorkbook(page);
    await sortDialog(page, 'A1', 'C4', 'Region', 'Descending');
    expect(await col(page, 'A', 4)).toEqual(['Region', 'South', 'North', 'East']);
    expect(await col(page, 'B', 4)).toEqual(['Sales', '700', '800', '1200']);
  });

  test('REQ-5-1-1 #4 equal keys keep original order', async ({ page }) => {
    await h.openWorkbook(page);
    await sortDialog(page, 'A1', 'C4', 'Status', 'Ascending');
    expect(await col(page, 'A', 4)).toEqual(['Region', 'North', 'East', 'South']);
  });

  test('REQ-5-1-1 #5 data outside selection unchanged', async ({ page }) => {
    await h.openWorkbook(page);
    await h.setCells(page, { D2: 'x', D3: 'y', D4: 'z', A6: 'Total' });
    await sortDialog(page, 'A1', 'C4', 'Sales', 'Descending');
    expect(await col(page, 'D', 4)).toEqual(['', 'x', 'y', 'z']);
    await h.expectCell(page, 'A6', 'Total');
    expect(await col(page, 'A', 4)).toEqual(['Region', 'East', 'North', 'South']);
  });

  test('REQ-5-1-1 #6 formula moves with its record', async ({ page }) => {
    await h.openWorkbook(page);
    await h.setCell(page, 'C2', '=B2*2');
    await sortDialog(page, 'A1', 'C4', 'Sales', 'Ascending');
    await h.expectCell(page, 'A4', 'East');
    await h.expectCell(page, 'C4', '2400');
    await h.expectFormula(page, 'C4', '=B4*2');
    await h.reload(page);
    await h.expectCell(page, 'C4', '2400');
  });
});

async function createFilter(page: Page) {
  await h.selectRange(page, 'A1', 'C4');
  await h.dataMenu(page, 'Create filter');
  await expect(page.getByRole('button', { name: 'Filter Region' })).toBeVisible();
}

test.describe('REQ-5-1-2 Filter', () => {
  test('REQ-5-1-2 #1 value filter on Region and condition on Sales', async ({ page }) => {
    await h.openWorkbook(page);
    await createFilter(page);
    await page.getByRole('button', { name: 'Filter Region' }).click();
    let dlg = page.getByRole('dialog', { name: 'Filter Region' });
    await dlg.getByRole('button', { name: 'Clear selection' }).click();
    await dlg.getByRole('checkbox', { name: 'East' }).check();
    await dlg.getByRole('checkbox', { name: 'North' }).check();
    await dlg.getByRole('button', { name: 'Apply' }).click();
    await expect(h.cell(page, 'A4')).toBeHidden();
    await page.getByRole('button', { name: 'Filter Sales' }).click();
    dlg = page.getByRole('dialog', { name: 'Filter Sales' });
    await h.choose(dlg, 'Condition', 'Greater than');
    await dlg.getByRole('textbox', { name: 'Value' }).fill('1000');
    await dlg.getByRole('button', { name: 'Apply' }).click();
    await expect(h.cell(page, 'A2')).toHaveText('East');
    await expect(h.cell(page, 'A3')).toBeHidden();
    await h.reload(page);
    await expect(h.cell(page, 'A2')).toBeVisible();
    await expect(h.cell(page, 'A3')).toBeHidden();
    await expect(h.cell(page, 'A4')).toBeHidden();
  });

  test('REQ-5-1-2 #2 text contains and is empty conditions', async ({ page }) => {
    await h.openWorkbook(page);
    await h.setCells(page, { A5: 'Southwest' });
    await createFilter(page);
    await h.expectCell(page, 'A5', 'Southwest');
    await page.getByRole('button', { name: 'Filter Region' }).click();
    const dlg = page.getByRole('dialog', { name: 'Filter Region' });
    await h.choose(dlg, 'Condition', 'Text contains');
    await dlg.getByRole('textbox', { name: 'Value' }).fill('south');
    await dlg.getByRole('button', { name: 'Apply' }).click();
    await expect(h.cell(page, 'A4')).toBeVisible();
    await expect(h.cell(page, 'A5')).toBeVisible();
    await expect(h.cell(page, 'A2')).toBeHidden();
    await page.getByRole('button', { name: 'Filter Sales' }).click();
    const d2 = page.getByRole('dialog', { name: 'Filter Sales' });
    await h.choose(d2, 'Condition', 'Is empty');
    await d2.getByRole('button', { name: 'Apply' }).click();
    await expect(h.cell(page, 'A5')).toBeVisible();
    await expect(h.cell(page, 'A4')).toBeHidden();
  });

  test('REQ-5-1-2 #3 CSV export includes hidden rows', async ({ page }) => {
    await h.openWorkbook(page);
    await createFilter(page);
    await page.getByRole('button', { name: 'Filter Status' }).click();
    const dlg = page.getByRole('dialog', { name: 'Filter Status' });
    await dlg.getByRole('checkbox', { name: 'Open' }).uncheck();
    await dlg.getByRole('button', { name: 'Apply' }).click();
    await expect(h.cell(page, 'A2')).toBeHidden();
    const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Export CSV' }).click()]);
    const fs = await import('fs');
    const text = fs.readFileSync((await dl.path())!, 'utf-8');
    expect(text).toContain('East,1200,Open');
    expect(text).toContain('South,700,Open');
    await expect(h.cell(page, 'A2')).toBeHidden();
  });

  test('REQ-5-1-2 #4 before condition on dates', async ({ page }) => {
    await h.openWorkbook(page);
    await h.setCells(page, { D1: 'Date', D2: '2024-03-01', D3: '2023-12-31', D4: '2024-01-15' });
    await h.selectRange(page, 'A1', 'D4');
    await h.dataMenu(page, 'Create filter');
    await page.getByRole('button', { name: 'Filter Date' }).click();
    const dlg = page.getByRole('dialog', { name: 'Filter Date' });
    await h.choose(dlg, 'Condition', 'Before');
    await dlg.getByRole('textbox', { name: 'Value' }).fill('2024-02-01');
    await dlg.getByRole('button', { name: 'Apply' }).click();
    await expect(h.cell(page, 'A2')).toBeHidden();
    await expect(h.cell(page, 'A3')).toBeVisible();
    await expect(h.cell(page, 'A4')).toBeVisible();
  });

  test('REQ-5-1-2 #5 clear filter restores rows', async ({ page }) => {
    await h.openWorkbook(page);
    await createFilter(page);
    await page.getByRole('button', { name: 'Filter Sales' }).click();
    const dlg = page.getByRole('dialog', { name: 'Filter Sales' });
    await h.choose(dlg, 'Condition', 'Greater than');
    await dlg.getByRole('textbox', { name: 'Value' }).fill('750');
    await dlg.getByRole('button', { name: 'Apply' }).click();
    await expect(h.cell(page, 'A4')).toBeHidden();
    await page.getByRole('button', { name: 'Clear filter' }).click();
    await expect(h.cell(page, 'A4')).toHaveText('South');
    await h.reload(page);
    await expect(h.cell(page, 'A4')).toHaveText('South');
    await h.expectCell(page, 'A2', 'East');
  });
});

test.describe('REQ-5-2-1 Data validation', () => {
  test('REQ-5-2-1 #1 dropdown rule on A2:A4 with options', async ({ page }) => {
    await h.openWorkbook(page);
    await h.addDropdownRule(page, 'A2', 'A4', ' East , North ,South, West ');
    await page.getByRole('button', { name: 'Open dropdown for A3' }).click();
    await expect(page.getByRole('option', { name: 'West', exact: true })).toBeVisible();
    await page.getByRole('option', { name: 'West', exact: true }).click();
    await h.expectCell(page, 'A3', 'West');
    await h.reload(page);
    await h.expectCell(page, 'A3', 'West');
    await expect(page.getByRole('button', { name: 'Open dropdown for A2' })).toBeVisible();
  });

  test('REQ-5-2-1 #2 invalid dropdown value rejected', async ({ page }) => {
    await h.openWorkbook(page);
    await h.addDropdownRule(page, 'A2', 'A4', 'East, North, South');
    await h.setCell(page, 'A2', 'Mars');
    await expect(page.getByText('Please select one of the following values: East, North, South')).toBeVisible();
    await h.expectCell(page, 'A2', 'East');
    await h.reload(page);
    await h.expectCell(page, 'A2', 'East');
  });

  test('REQ-5-2-1 #3 numeric 0-100 rule rejects 101 in B3', async ({ page }) => {
    await h.openWorkbook(page);
    await h.setCells(page, { B2: '10', B3: '20', B4: '30' });
    await h.addNumberRule(page, 'B2', 'B4', '0', '100');
    await h.reload(page);
    await h.setViaFormulaBar(page, 'B3', '101');
    await expect(page.getByText('Please enter a number from 0 to 100')).toBeVisible();
    await h.expectCell(page, 'B3', '20');
    await h.setCell(page, 'B3', '100');
    await h.expectCell(page, 'B3', '100');
  });

  test('REQ-5-2-1 #4 number range between message', async ({ page }) => {
    await h.openWorkbook(page);
    await h.addNumberRule(page, 'D2', 'D3', '10', '20');
    await h.setCell(page, 'D2', '25');
    await expect(page.getByText('Please enter a number between 10 and 20')).toBeVisible();
    await h.expectCell(page, 'D2', '');
    await h.setCell(page, 'D2', '15');
    await h.expectCell(page, 'D2', '15');
  });

  test('REQ-5-2-1 #5 reopen rule prefilled and modify range', async ({ page }) => {
    await h.openWorkbook(page);
    await h.addNumberRule(page, 'D2', 'D3', '0', '100');
    await h.selectRange(page, 'D2', 'D3');
    await h.dataMenu(page, 'Data validation');
    const dlg = page.getByRole('dialog', { name: 'Data validation' });
    await expect(dlg.getByRole('combobox', { name: 'Rule type' })).toHaveValue('Number range');
    await expect(dlg.getByRole('textbox', { name: 'Minimum' })).toHaveValue('0');
    await expect(dlg.getByRole('textbox', { name: 'Maximum' })).toHaveValue('100');
    await expect(dlg.getByRole('button', { name: 'Delete rule' })).toBeVisible();
    await dlg.getByRole('textbox', { name: 'Maximum' }).fill('50');
    await dlg.getByRole('button', { name: 'Save' }).click();
    await expect(dlg).toBeHidden();
    await h.setCell(page, 'D3', '60');
    await expect(page.getByText('Please enter a number between 0 and 50')).toBeVisible();
  });

  test('REQ-5-2-1 #6 delete rule removes constraint', async ({ page }) => {
    await h.openWorkbook(page);
    await h.addDropdownRule(page, 'C2', 'C4', 'Open, Closed');
    await h.cell(page, 'C3').click();
    await h.dataMenu(page, 'Data validation');
    const dlg = page.getByRole('dialog', { name: 'Data validation' });
    await expect(dlg.getByRole('textbox', { name: 'Allowed values' })).toHaveValue('Open, Closed');
    await dlg.getByRole('button', { name: 'Delete rule' }).click();
    await expect(dlg).toBeHidden();
    await expect(page.getByRole('button', { name: 'Open dropdown for C3' })).toHaveCount(0);
    await h.setCell(page, 'C3', 'Pending');
    await h.expectCell(page, 'C3', 'Pending');
    await h.expectCell(page, 'C2', 'Open');
    await h.reload(page);
    await h.expectCell(page, 'C3', 'Pending');
  });
});

test.describe('REQ-5-3-1 Pivot tables', () => {
  test('REQ-5-3-1 #1 create Pivot1 with Region rows and SUM of Sales', async ({ page }) => {
    await h.openWorkbook(page);
    await h.createPivot(page);
    await h.applyPivot(page, 'Region', 'Sales', 'SUM');
    await h.expectCell(page, 'A1', 'Region');
    await h.expectCell(page, 'B1', 'SUM of Sales');
    await h.expectCell(page, 'A2', 'East');
    await h.expectCell(page, 'B3', '800');
    await h.expectCell(page, 'A5', 'Grand Total');
    await h.expectCell(page, 'B5', '2700');
    await h.reload(page);
    await expect(page.getByRole('tab', { name: 'Pivot1' })).toHaveAttribute('aria-selected', 'true');
    await h.expectCell(page, 'B5', '2700');
    await page.getByRole('tab', { name: 'Sheet1' }).click();
    await h.expectCell(page, 'A1', 'Region');
    await h.expectCell(page, 'B2', '1200');
  });

  test('REQ-5-3-1 #2 column field layout', async ({ page }) => {
    await h.openWorkbook(page);
    await h.createPivot(page);
    await h.applyPivot(page, 'Region', 'Sales', 'SUM', 'Status');
    await h.expectCell(page, 'B1', 'Open');
    await h.expectCell(page, 'C1', 'Closed');
    await h.expectCell(page, 'D1', 'Grand Total');
    await h.expectCell(page, 'B2', '1200');
    await h.expectCell(page, 'C3', '800');
    await h.expectCell(page, 'D5', '2700');
    await h.expectCell(page, 'B5', '1900');
  });

  test('REQ-5-3-1 #3 COUNT with column field shows 0 for empty combos', async ({ page }) => {
    await h.openWorkbook(page);
    await h.createPivot(page);
    await h.applyPivot(page, 'Region', 'Status', 'COUNT', 'Status');
    await h.expectCell(page, 'B1', 'Open');
    await h.expectCell(page, 'B2', '1');
    await h.expectCell(page, 'C2', '0');
    await h.expectCell(page, 'D5', '3');
  });

  test('REQ-5-3-1 #4 AVERAGE summary', async ({ page }) => {
    await h.openWorkbook(page);
    await h.setCells(page, { A5: 'East', B5: '800', C5: 'Closed' });
    await h.createPivot(page, 'A1', 'C5');
    await h.applyPivot(page, 'Region', 'Sales', 'AVERAGE');
    await h.expectCell(page, 'B1', 'AVERAGE of Sales');
    await h.expectCell(page, 'B2', '1000');
    await h.expectCell(page, 'A5', 'Grand Total');
    await h.expectCell(page, 'B5', '875');
  });

  test('REQ-5-3-1 #5 refresh after source change', async ({ page }) => {
    await h.openWorkbook(page);
    await h.createPivot(page);
    await h.applyPivot(page, 'Region', 'Sales', 'SUM');
    await page.getByRole('tab', { name: 'Sheet1' }).click();
    await h.setCell(page, 'B2', '1500');
    await page.getByRole('tab', { name: 'Pivot1' }).click();
    await h.expectCell(page, 'B2', '1200');
    await page.getByRole('button', { name: 'Refresh pivot table' }).click();
    await h.expectCell(page, 'B2', '1500');
    await h.expectCell(page, 'B5', '3000');
    await h.reload(page);
    await h.expectCell(page, 'B5', '3000');
  });

  test('REQ-5-3-1 #6 refresh after row insertion uses adjusted range', async ({ page }) => {
    await h.openWorkbook(page);
    await h.createPivot(page);
    await h.applyPivot(page, 'Region', 'Sales', 'SUM');
    await page.getByRole('tab', { name: 'Sheet1' }).click();
    await h.rowMenu(page, '3', 'Insert 1 row above');
    await h.setCells(page, { A3: 'West', B3: '100', C3: 'Open' });
    await page.getByRole('tab', { name: 'Pivot1' }).click();
    await h.expectCell(page, 'B5', '2700');
    await page.getByRole('button', { name: 'Refresh pivot table' }).click();
    await h.expectCell(page, 'A3', 'West');
    await h.expectCell(page, 'B6', '2800');
  });

  test('REQ-5-3-1 #7 SUM on non-numeric field rejected', async ({ page }) => {
    await h.openWorkbook(page);
    await h.createPivot(page);
    await h.applyPivot(page, 'Region', 'Sales', 'SUM');
    await h.applyPivot(page, 'Region', 'Status', 'SUM');
    await expect(page.getByText('Value field requires numeric values')).toBeVisible();
    await h.expectCell(page, 'B1', 'SUM of Sales');
    await h.reload(page);
    await h.expectCell(page, 'B1', 'SUM of Sales');
  });

  test('REQ-5-3-1 #8 deleted header shows field error in editor', async ({ page }) => {
    await h.openWorkbook(page);
    await h.createPivot(page);
    await h.applyPivot(page, 'Status', 'Sales', 'SUM');
    await page.getByRole('tab', { name: 'Sheet1' }).click();
    await h.colMenu(page, 'C', 'Delete column');
    await page.getByRole('tab', { name: 'Pivot1' }).click();
    await expect(page.getByText('Pivot field is no longer available. Select a new field.')).toBeVisible();
    await page.getByRole('button', { name: 'Refresh pivot table' }).click();
    await expect(page.getByText('Pivot field is no longer available. Select a new field.')).toBeVisible();
    await h.expectCell(page, 'A2', 'Open');
    await h.expectCell(page, 'B2', '1900');
  });

  test('REQ-5-3-1 #9 COUNT counts non-empty text values', async ({ page }) => {
    await h.openWorkbook(page);
    await h.setCells(page, { A5: 'East', C5: 'Open' });
    await h.createPivot(page, 'A1', 'C5');
    await h.applyPivot(page, 'Status', 'Region', 'COUNT');
    await h.expectCell(page, 'B1', 'COUNT of Region');
    await h.expectCell(page, 'A2', 'Open');
    await h.expectCell(page, 'B2', '3');
    await h.expectCell(page, 'B3', '1');
    await h.expectCell(page, 'B4', '4');
  });
});
