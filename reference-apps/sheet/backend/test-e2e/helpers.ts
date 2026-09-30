import { expect, type Locator, type Page } from '@playwright/test';

export const WB = 'Q3 Sales';

export function cell(page: Page, ref: string): Locator {
  return page.getByRole('gridcell', { name: ref, exact: true });
}

export const grid = (page: Page) => page.getByRole('grid', { name: 'Worksheet grid' });
export const formulaBar = (page: Page) => page.getByRole('textbox', { name: 'Formula bar' });

export async function openHome(page: Page) {
  await page.goto('/');
  await expect(page.getByRole('link', { name: WB, exact: true })).toBeVisible();
}

export async function openWorkbook(page: Page, name = WB) {
  await page.goto('/');
  await page.getByRole('link', { name, exact: true }).click();
  await expect(grid(page)).toBeVisible();
}

export async function reload(page: Page) {
  await page.waitForTimeout(150);
  await page.reload();
  await expect(grid(page)).toBeVisible();
}

export async function setCell(page: Page, ref: string, value: string) {
  await cell(page, ref).dblclick();
  const editor = page.getByRole('textbox', { name: `Edit ${ref}`, exact: true });
  await editor.fill(value);
  await editor.press('Enter');
}

export async function setCells(page: Page, values: Record<string, string>) {
  for (const [ref, v] of Object.entries(values)) await setCell(page, ref, v);
}

export async function setViaFormulaBar(page: Page, ref: string, value: string) {
  await cell(page, ref).click();
  await formulaBar(page).fill(value);
  await formulaBar(page).press('Enter');
}

export async function expectCell(page: Page, ref: string, text: string) {
  await expect(cell(page, ref)).toHaveText(text);
}

export async function expectFormula(page: Page, ref: string, raw: string) {
  await cell(page, ref).click();
  await expect(formulaBar(page)).toHaveValue(raw);
}

export async function selectRange(page: Page, from: string, to: string) {
  await cell(page, from).dragTo(cell(page, to));
}

export async function dataMenu(page: Page, item: string) {
  await page.getByRole('button', { name: 'Data', exact: true }).click();
  await page.getByRole('menuitem', { name: item, exact: true }).click();
}

export async function tabMenu(page: Page, sheet: string, item: string) {
  await page.getByRole('button', { name: `Worksheet options for ${sheet}`, exact: true }).click();
  await page.getByRole('menuitem', { name: item, exact: true }).click();
}

export async function rowMenu(page: Page, row: string, item: string) {
  await page.getByRole('rowheader', { name: row, exact: true }).click({ button: 'right' });
  await page.getByRole('menuitem', { name: item, exact: true }).click();
}

export async function colMenu(page: Page, col: string, item: string) {
  await page.getByRole('columnheader', { name: col, exact: true }).click({ button: 'right' });
  await page.getByRole('menuitem', { name: item, exact: true }).click();
}

export async function expectSelected(page: Page, selected: string[], notSelected: string[]) {
  for (const r of selected) await expect(cell(page, r)).toHaveAttribute('aria-selected', 'true');
  for (const r of notSelected) await expect(cell(page, r)).toHaveAttribute('aria-selected', 'false');
}

export async function addNumberRule(page: Page, from: string, to: string, min: string, max: string) {
  await selectRange(page, from, to);
  await dataMenu(page, 'Data validation');
  const dlg = page.getByRole('dialog', { name: 'Data validation' });
  await choose(dlg, 'Rule type', 'Number range');
  await dlg.getByRole('textbox', { name: 'Minimum' }).fill(min);
  await dlg.getByRole('textbox', { name: 'Maximum' }).fill(max);
  await dlg.getByRole('button', { name: 'Save' }).click();
  await expect(dlg).toBeHidden();
}

export async function addDropdownRule(page: Page, from: string, to: string, values: string) {
  await selectRange(page, from, to);
  await dataMenu(page, 'Data validation');
  const dlg = page.getByRole('dialog', { name: 'Data validation' });
  await choose(dlg, 'Rule type', 'Dropdown');
  await dlg.getByRole('textbox', { name: 'Allowed values' }).fill(values);
  await dlg.getByRole('button', { name: 'Save' }).click();
  await expect(dlg).toBeHidden();
}

export async function pasteText(page: Page, ref: string, text: string) {
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await cell(page, ref).click();
  await page.evaluate((t) => navigator.clipboard.writeText(t), text);
  await page.keyboard.press('ControlOrMeta+V');
}

export async function createPivot(page: Page, from = 'A1', to = 'C4') {
  await selectRange(page, from, to);
  await dataMenu(page, 'Create pivot table');
  const dlg = page.getByRole('dialog', { name: 'Create pivot table' });
  await expect(dlg.getByText(`Source range: ${from}:${to}`)).toBeVisible();
  await dlg.getByRole('radio', { name: 'New worksheet' }).check();
  await dlg.getByRole('button', { name: 'Create' }).click();
  await expect(page.getByRole('tab', { name: 'Pivot1' })).toHaveAttribute('aria-selected', 'true');
  return page.getByRole('region', { name: 'Pivot table editor' });
}

export async function applyPivot(page: Page, rows: string, values: string, agg: string, columns?: string) {
  const ed = page.getByRole('region', { name: 'Pivot table editor' });
  await choose(ed, 'Rows', rows);
  if (columns) await choose(ed, 'Columns', columns);
  await choose(ed, 'Values', values);
  await choose(ed, 'Summarize by', agg);
  await ed.getByRole('button', { name: 'Apply' }).click();
}

/** Custom ARIA combobox: click it, then click the visible option by role and name. */
export async function choose(scope: Page | Locator, combo: string, option: string) {
  await scope.getByRole('combobox', { name: combo, exact: true }).click();
  const page = 'page' in scope ? scope.page() : scope;
  await page.getByRole('option', { name: option, exact: true }).click();
  await expect(scope.getByRole('combobox', { name: combo, exact: true })).toHaveText(option);
}
