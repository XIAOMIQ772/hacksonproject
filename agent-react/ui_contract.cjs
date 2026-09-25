// Requirements-authored data, independently implemented exact DOM checks.
const {test, expect} = require(process.env.ARC_PLAYWRIGHT_MODULE);
const fs = require('fs');
const cases = JSON.parse(fs.readFileSync(process.env.ARC_UI_CONTRACT, 'utf8')).cases;
for (const scenario of cases) {
  test(`${scenario.req_ids.join(' ')} UI contract: ${scenario.name}`, async ({page}) => {
    try {
      await page.goto(scenario.path);
      for (const step of scenario.steps) {
        if (step.action === 'reload') {
          await page.reload();
          continue;
        }
        const scope = step.scope
          ? page.getByRole(step.scope.role, {name: step.scope.name, exact: true}) : page;
        if (step.scope) await expect(scope).toHaveCount(1);
        let target;
        if (step.action === 'assertText') {
          target = scope.getByText(step.name, {exact: true});
        } else if (step.by === 'label') {
          target = scope.getByLabel(step.name, {exact: true});
        } else {
          target = step.roles.map(role => scope.getByRole(role, {name: step.name, exact: true}))
            .reduce((combined, locator) => combined ? combined.or(locator) : locator, null);
        }
        // The union stays live while the DOM loads. Never choose a permanent
        // fallback from count()/isVisible() sampled before an async response.
        if (step.action === 'assertAbsent') {
          await expect(target, `Absent exact target: ${step.name}`).toHaveCount(0);
          continue;
        }
        await expect(target, `Unique exact target: ${step.name}`).toHaveCount(1);
        await expect(target).toBeVisible();
        switch (step.action) {
          case 'assert':
          case 'assertText':
            break;
          case 'click': await target.click(); break;
          case 'fill': await target.fill(step.value); break;
          case 'check': await target.check(); break;
          case 'uncheck': await target.uncheck(); break;
          case 'press': await target.press(step.key); break;
          case 'select': await target.selectOption({label: step.value}); break;
          case 'dblclick': await target.dblclick(); break;
          case 'contextmenu': await target.click({button: 'right'}); break;
          case 'assertDisabled': await expect(target).toBeDisabled(); break;
          case 'assertEnabled': await expect(target).toBeEnabled(); break;
          case 'assertAttribute':
            await expect(target).toHaveAttribute(step.attribute, step.value);
            break;
          default: throw new Error(`Unsupported UI contract action: ${step.action}`);
        }
      }
    } catch (error) {
      await test.info().attach('accessible-page', {
        body: await page.locator('body').ariaSnapshot().catch(() => 'Page unavailable'),
        contentType: 'text/plain',
      });
      throw error;
    }
  });
}
