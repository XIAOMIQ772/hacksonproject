import { test, expect } from '@playwright/test';
import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';
import * as h from './helpers';

// requirement: REQ-9.2
// fixtures: public_homepage

test('REQ-9.2: create a note with an image attachment', async ({ page }) => {
  const imagePath = path.join(os.tmpdir(), `keep-image-note-${Date.now()}.png`);
  await fs.writeFile(imagePath, Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
    'base64',
  ));

  await h.openHome(page);
  await h.openComposer(page);
  await h.fillField(page, [/title/i], h.FIXTURES.evolution.imageTitle);
  await h.fillField(page, [/take a note/i, /note/i, /content/i], h.FIXTURES.evolution.imageContent);
  await h.clickFirstAvailable(page, [[/add image/i, /image/i, /photo/i]]);

  const fileInput = page.locator('input[type="file"]').last();
  await fileInput.setInputFiles(imagePath);
  await h.closeEditor(page);

  const card = await h.noteCard(page, h.FIXTURES.evolution.imageTitle);
  await expect(card).toBeVisible();
  await expect(card.getByText(h.FIXTURES.evolution.imageContent, { exact: true })).toBeVisible();
  await expect(card.locator('img, [role="img"]').first()).toBeVisible();
});
