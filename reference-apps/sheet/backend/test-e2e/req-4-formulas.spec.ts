import { test, expect, type Page } from '@playwright/test';
import * as h from './helpers';

async function base(page: Page) {
  await h.openWorkbook(page);
  await page.getByRole('tab', { name: 'Sheet2' }).click();
  await h.setCells(page, { A1: '2', B1: '3', C1: '=A1+B1', D1: '=C1*2' });
}

test.describe('REQ-4-1-1 Basic expressions and aggregates', () => {
  test('REQ-4-1-1 #1 references and arithmetic', async ({ page }) => {
    await base(page);
    await h.expectCell(page, 'C1', '5');
    await h.expectCell(page, 'D1', '10');
    await h.expectFormula(page, 'C1', '=A1+B1');
    await h.reload(page);
    await h.expectCell(page, 'D1', '10');
    await h.expectFormula(page, 'D1', '=C1*2');
  });

  test('REQ-4-1-1 #2 constants, parentheses, precedence and division', async ({ page }) => {
    await base(page);
    await h.setCell(page, 'A2', '=(1+2)*4-10/5');
    await h.setCell(page, 'B2', '=-A1*(B1-0.5)');
    await h.expectCell(page, 'A2', '10');
    await h.expectCell(page, 'B2', '-5');
  });

  test('REQ-4-1-1 #3 SUM and AVERAGE ignore blanks and text', async ({ page }) => {
    await base(page);
    await h.setCells(page, { A3: '10', A4: 'text', A6: '20' });
    await h.setCell(page, 'B3', '=SUM(A3:A6)');
    await h.setCell(page, 'B4', '=AVERAGE(A3:A6)');
    await h.expectCell(page, 'B3', '30');
    await h.expectCell(page, 'B4', '15');
    await h.reload(page);
    await h.expectCell(page, 'B4', '15');
    await h.expectFormula(page, 'B4', '=AVERAGE(A3:A6)');
  });

  test('REQ-4-1-1 #4 COUNT, MIN and MAX', async ({ page }) => {
    await base(page);
    await h.setCells(page, { A3: '10', A4: 'text', A6: '-4' });
    await h.setCell(page, 'B3', '=COUNT(A3:A6)');
    await h.setCell(page, 'B4', '=MIN(A3:A6)');
    await h.setCell(page, 'B5', '=MAX(A3:A6)');
    await h.expectCell(page, 'B3', '2');
    await h.expectCell(page, 'B4', '-4');
    await h.expectCell(page, 'B5', '10');
  });

  test('REQ-4-1-1 #5 function names are case-insensitive', async ({ page }) => {
    await base(page);
    await h.setCell(page, 'E1', '=sum(A1:D1)');
    await h.setCell(page, 'E2', '=Max(a1:b1)');
    await h.expectCell(page, 'E1', '20');
    await h.expectCell(page, 'E2', '3');
    await h.expectFormula(page, 'E1', '=sum(A1:D1)');
  });
});

test.describe('REQ-4-1-2 Copy formulas', () => {
  test('REQ-4-1-2 #1 relative references follow the offset', async ({ page }) => {
    await base(page);
    await h.setCells(page, { A2: '4', B2: '6' });
    await h.cell(page, 'C1').click();
    await page.keyboard.press('ControlOrMeta+C');
    await h.cell(page, 'C2').click();
    await page.keyboard.press('ControlOrMeta+V');
    await h.expectFormula(page, 'C2', '=A2+B2');
    await h.expectCell(page, 'C2', '10');
    await h.expectFormula(page, 'C1', '=A1+B1');
    await h.expectCell(page, 'C1', '5');
    await h.reload(page);
    await h.expectCell(page, 'C2', '10');
  });

  test('REQ-4-1-2 #2 out of bounds reference becomes #REF!', async ({ page }) => {
    await base(page);
    await h.cell(page, 'C1').click();
    await page.keyboard.press('ControlOrMeta+C');
    await h.cell(page, 'A3').click();
    await page.keyboard.press('ControlOrMeta+V');
    await h.expectCell(page, 'A3', '#REF!');
    await h.expectFormula(page, 'A3', '=#REF!');
    await h.reload(page);
    await h.expectCell(page, 'A3', '#REF!');
  });
});

test.describe('REQ-4-2-1 Dependent recalculation', () => {
  test('REQ-4-2-1 #1 editing source updates chain', async ({ page }) => {
    await base(page);
    await h.setCell(page, 'A1', '7');
    await h.expectCell(page, 'C1', '10');
    await h.expectCell(page, 'D1', '20');
    await h.reload(page);
    await h.expectCell(page, 'D1', '20');
    await h.expectFormula(page, 'D1', '=C1*2');
    await page.getByRole('tab', { name: 'Sheet1' }).click();
    await h.expectCell(page, 'A1', 'Region');
  });

  test('REQ-4-2-1 #2 paste into sources recalculates', async ({ page }) => {
    await base(page);
    await h.pasteText(page, 'A1', '10\t20');
    await h.expectCell(page, 'C1', '30');
    await h.expectCell(page, 'D1', '60');
    await h.reload(page);
    await h.expectCell(page, 'D1', '60');
  });

  test('REQ-4-2-1 #3 column insert keeps results consistent', async ({ page }) => {
    await base(page);
    await h.colMenu(page, 'B', 'Insert 1 column left');
    await h.expectFormula(page, 'D1', '=A1+C1');
    await h.expectCell(page, 'E1', '10');
    await h.setCell(page, 'C1', '8');
    await h.expectCell(page, 'E1', '20');
    await h.reload(page);
    await h.expectCell(page, 'E1', '20');
  });
});

test.describe('REQ-4-2-2 Formula errors', () => {
  test('REQ-4-2-2 #1 division by zero then fix', async ({ page }) => {
    await base(page);
    await h.setCell(page, 'E1', '=A1/0');
    await h.expectCell(page, 'E1', '#DIV/0!');
    await h.expectFormula(page, 'E1', '=A1/0');
    await h.reload(page);
    await h.expectCell(page, 'E1', '#DIV/0!');
    await h.setCell(page, 'E1', '=A1/2');
    await h.expectCell(page, 'E1', '1');
    await h.reload(page);
    await h.expectCell(page, 'E1', '1');
  });

  test('REQ-4-2-2 #2 unsupported function shows #NAME?', async ({ page }) => {
    await base(page);
    await h.setCell(page, 'E1', '=FOO(A1)');
    await h.expectCell(page, 'E1', '#NAME?');
    await h.expectCell(page, 'D1', '10');
    await h.expectFormula(page, 'E1', '=FOO(A1)');
  });

  test('REQ-4-2-2 #3 malformed expression shows #ERROR!', async ({ page }) => {
    await base(page);
    await h.setCell(page, 'E1', '=(A1+');
    await h.expectCell(page, 'E1', '#ERROR!');
    await h.reload(page);
    await h.expectFormula(page, 'E1', '=(A1+');
  });

  test('REQ-4-2-2 #4 circular reference shows #REF! and can be fixed', async ({ page }) => {
    await base(page);
    await h.setCell(page, 'A1', '=D1');
    await h.expectCell(page, 'A1', '#REF!');
    await h.expectCell(page, 'D1', '#REF!');
    await h.setCell(page, 'E2', '=B1*2');
    await h.expectCell(page, 'E2', '6');
    await h.setCell(page, 'A1', '1');
    await h.expectCell(page, 'D1', '8');
    await h.reload(page);
    await h.expectCell(page, 'D1', '8');
  });

  test('REQ-4-2-2 #5 invalid reference shows #REF!', async ({ page }) => {
    await base(page);
    await h.setCell(page, 'E1', '=#REF!+1');
    await h.expectCell(page, 'E1', '#REF!');
    await h.setCell(page, 'E2', '=A0');
    await h.expectCell(page, 'E2', '#REF!');
    await h.expectCell(page, 'C1', '5');
  });
});
