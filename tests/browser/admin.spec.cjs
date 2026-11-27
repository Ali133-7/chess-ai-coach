const {test,expect}=require('@playwright/test');
test.beforeEach(async({page})=>{
 page.browserErrors=[];page.on('pageerror',error=>page.browserErrors.push(error.message));
 expect((await page.request.post('/api/auth/login',{data:{email:'browser3@example.test',password:'browser-fixture-only-password'}})).ok()).toBeTruthy();
 await page.goto('/');await expect(page.locator('#workspace')).toBeVisible();
 if(await page.locator('#menu').isVisible())await page.locator('#menu').click();
 await page.locator('#nav .nav-more summary').click();await page.locator('#admin-nav').click();await expect(page.locator('.control-stats')).toBeVisible();
});
test.afterEach(async({page})=>{expect(page.browserErrors).toEqual([]);});
async function navigateSection(page,id){if(await page.locator('#control-nav').isVisible())await page.locator(`[data-control-tab="${id}"]`).click();else{const input=page.locator('#admin-mobile-navigation [role=combobox]');await input.click();await page.locator(`#admin-mobile-navigation [role=option][data-select-index="${await page.locator('#control-section-picker').evaluate((select,value)=>[...select.options].findIndex(o=>o.value===value),id)}"]`).click();}}
async function section(page,id){await navigateSection(page,id);await expect(page.locator('#control-main')).toHaveAttribute('aria-busy','false');}
async function fits(page){expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();}

test('admin workspace offers responsive navigation actual user search and keyboard dropdowns',async({page},info)=>{
 await section(page,'users');await page.locator('#control-search [name=q]').fill('browser0@example.test');await page.locator('#control-search button[type=submit]').click();await expect(page.locator('.admin-data-table tbody tr')).toHaveCount(1);await expect(page.locator('.admin-data-table')).toContainText('browser0@example.test');await page.locator('[data-control-edit=user]').click();await expect(page.locator('#control-dialog')).toBeVisible();
 const plan=page.locator('#control-dialog [data-control-form=membership] [role=combobox]');await plan.fill('Free');await expect(page.locator('#control-dialog [role=option]')).toHaveCount(0);await plan.press('Escape');await expect(page.locator('#control-dialog')).toBeVisible();await plan.click();await plan.press('Home');await plan.press('Enter');
 await page.locator('#control-dialog-close').click();await section(page,'gateways');await page.locator('[data-control-edit=gateway][data-id=google_play]').click();await expect(page.locator('[name=service_account_file]')).toHaveValue('');await page.locator('[data-add-product]').click();await expect(page.locator('.control-product [role=combobox]')).toHaveCount(1);
 page.once('dialog',dialog=>dialog.accept());await page.locator('#control-dialog-close').click();await expect(page.locator('#control-dialog')).not.toBeVisible();await fits(page);
 await page.locator('.topbar .language-select').selectOption('en');await section(page,'users');await expect(page.locator('#control-context h2')).toHaveText('Users & memberships');await fits(page);
 if(['desktop','phone390'].includes(info.project.name))await page.screenshot({path:info.outputPath('admin-users.png')});
});

test('admin plan creation persists and unsaved provider edits survive language switches',async({page},info)=>{
 await section(page,'plans');await page.locator('[data-control-new=plan]').click();const form=page.locator('[data-control-form=plan]');
 await form.locator('[name=id]').fill('ui-'+info.project.name);await form.locator('[name=title_ar]').fill('خطة اختبار '+info.project.name);await form.locator('[name=title_en]').fill('UI plan '+info.project.name);await form.locator('[name=price_iqd]').fill('1500');
 const saved=page.waitForResponse(r=>r.url().includes('/api/control/plans/ui-')&&r.request().method()==='PUT');await form.locator('[type=submit]').click();expect((await saved).ok()).toBeTruthy();await expect(page.locator('#control-dialog')).not.toBeVisible();await expect(page.locator('#control-body')).toContainText('خطة اختبار '+info.project.name);
 await section(page,'providers');await page.locator('[name=key_groq]').fill('unsaved-fixture-key');await page.locator('.topbar .language-select').selectOption('en');await expect(page.locator('[name=key_groq]')).toHaveValue('unsaved-fixture-key');await expect(page.locator('[name=key_groq]')).toHaveAttribute('type','password');
 const primary=page.locator('[name=primary]').locator('..').getByRole('combobox');await primary.fill('openrouter');await expect(page.locator('.admin-select-menu:not([hidden]) [role=option]')).toHaveCount(1);await primary.press('Enter');await expect(page.locator('[name=primary]')).toHaveValue('openrouter');
 const fallback=page.locator('[name=fallback_0]').locator('..').getByRole('combobox');await fallback.fill('openrouter');await fallback.press('Enter');await page.locator('[name=confirm_password]').fill('browser-fixture-only-password');let providerWrites=0;page.on('request',r=>{if(r.method()==='PUT'&&r.url().endsWith('/api/control/providers'))providerWrites++;});await page.locator('[data-control-form=providers] [type=submit]').click();await expect(page.locator('#control-status')).toContainText('Choose a different provider');expect(providerWrites).toBe(0);
 page.once('dialog',dialog=>dialog.dismiss());await page.locator('#control-refresh').click();await expect(page.locator('[name=key_groq]')).toHaveValue('unsaved-fixture-key');await fits(page);
 if(['desktop','phone390'].includes(info.project.name))await page.screenshot({path:info.outputPath('admin-provider-form.png')});
 // Explicitly discard local edits; no provider credentials are sent by this test.
 page.once('dialog',dialog=>dialog.accept());await page.locator('#control-refresh').click();await expect(page.locator('[name=key_groq]')).toHaveValue('');
});

test('admin load failures retry and old responses cannot replace the active section',async({page})=>{
 let blocked=true;await page.route('**/api/control/users?*',async route=>{if(blocked)await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Temporary fixture outage'})});else await route.continue();});
 await section(page,'users');await expect(page.locator('[data-control-retry]')).toBeVisible();blocked=false;await page.locator('[data-control-retry]').click();await expect(page.locator('.admin-data-table')).toBeVisible();await fits(page);
 await section(page,'overview');await expect(page.locator('.control-stats')).toBeVisible();
 let release;const gate=new Promise(resolve=>release=resolve);await page.unroute('**/api/control/users?*');await page.route('**/api/control/users?*',async route=>{const response=await route.fetch();await gate;await route.fulfill({response});});
 await navigateSection(page,'users');await expect(page.locator('#control-main')).toHaveAttribute('aria-busy','true');await section(page,'overview');const late=page.waitForResponse(r=>r.url().includes('/api/control/users?'));release();await late;await page.evaluate(()=>new Promise(requestAnimationFrame));await expect(page.locator('#control-context h2')).toHaveText('نظرة عامة');await expect(page.locator('.control-stats')).toBeVisible();
});
