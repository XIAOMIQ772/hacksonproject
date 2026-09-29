import { test, expect } from '@playwright/test';
import * as h from './helpers';

// requirement: REQ-9.1
// fixtures: shareable_note

test('REQ-9.1: add a collaborator to a note', async ({ page }) => {
  await h.openHome(page);
  const title = h.FIXTURES.notes.regularTitle;

  await h.openMoreOptionsForNote(page, title);
  await h.clickFirstAvailable(page, [[/collaborator/i, /share/i]]);
  await h.fillField(page, [/email|person|collaborator/i], h.FIXTURES.evolution.collaboratorEmail);
  await h.clickFirstAvailable(page, [[/^save$/i, /^done$/i, /^ok$/i]]);

  const card = await h.noteCard(page, title);
  await expect(card).toBeVisible();
  await h.openMoreOptionsForNote(page, title);
  await h.clickFirstAvailable(page, [[/collaborator/i, /share/i]]);
  await h.expectTextsVisible(page, [h.FIXTURES.evolution.collaboratorEmail]);
});
