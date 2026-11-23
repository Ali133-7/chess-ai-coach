const {test,expect}=require('@playwright/test');
const projects=['phone320','phone390','tablet','desktop'];
test.beforeEach(async({page},info)=>{
 page.browserErrors=[];page.on('pageerror',error=>page.browserErrors.push(error.message));
 const index=projects.indexOf(info.project.name);const response=await page.request.post('/api/auth/login',{data:{email:`browser${index}@example.test`,password:'browser-fixture-only-password'}});expect(response.ok()).toBeTruthy();
 await page.goto('/');await expect(page.locator('#workspace')).toBeVisible();
});
test.afterEach(async({page})=>{expect(page.browserErrors).toEqual([]);});
async function navigate(page,view){
 if(await page.locator('#menu').isVisible())await page.locator('#menu').click();
 await page.locator(`#nav button[data-view="${view}"]`).click();await expect(page.locator('#view-'+view)).toBeVisible();
}
async function fits(page){expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();}
test('queue prioritization cancellation and saved-progress resume',async({page},info)=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));await navigate(page,'games');await page.locator('#analysis-queue summary').first().click();
 const row=page.locator('[data-job]').first();await expect(row).toBeVisible();await row.locator('[data-job-action="prioritize"]').click();await row.locator('[data-job-action="cancel"]').click();await expect(row.locator('[data-job-action="resume"]')).toBeVisible();await row.locator('[data-job-action="resume"]').click();await expect(row.locator('[data-job-action="cancel"]')).toBeVisible();await fits(page);expect(errors).toEqual([]);if(['phone390','desktop'].includes(info.project.name))await page.screenshot({path:info.outputPath('verified-queue.png')});
});
test('adaptive exercise uses existing legal board and switches languages',async({page})=>{
 await navigate(page,'knowledge');await page.locator('#adaptive-training summary').first().click();await expect(page.locator('[data-adaptive-id]').first()).toBeVisible();const pid=await page.locator('[data-adaptive-id]').first().getAttribute('data-adaptive-id');await page.locator('[data-adaptive-id]').first().click();await expect(page.locator('#kc-puzzle-panel')).toBeVisible();await expect(page.locator('#kc-puzzle-board img').first()).toBeVisible();await page.locator('#kc-puzzle-reveal').click();await expect(page.locator(`[data-adaptive-id="${pid}"]`)).toHaveCount(0);
 await page.locator('.topbar .language-select').selectOption('en');await expect(page.locator('#adaptive-training>summary')).toHaveText('Training for your progress');await fits(page);
});
test('review modal remains accessible with keyboard and closes by X',async({page})=>{
 await navigate(page,'games');const buttons=page.locator('#game-list [data-open-game]');await expect(buttons.first()).toBeVisible();await buttons.first().click();await expect(page.locator('#review-modal')).toBeVisible();await page.keyboard.press('Escape');await expect(page.locator('#review-modal')).toBeVisible();await page.locator('#close-review').click();await expect(page.locator('#review-modal')).not.toBeVisible();await fits(page);
});
test('GET coalescing performance budget and owner-scoped APIs',async({page},info)=>{
 let count=0;page.on('request',r=>{if(r.url().endsWith('/api/analysis/jobs'))count++;});
 const metrics=await page.evaluate(async()=>{await Promise.all(Array.from({length:8},()=>request('/analysis/jobs')));return StudioRequests.metrics();});expect(count).toBe(1);expect(metrics.coalesced_gets).toBeGreaterThanOrEqual(7);
 const mine=await (await page.request.get('/api/analysis/jobs')).json();expect(mine.items.length).toBe(1);const denied=await page.request.get('/api/games/'+(projects.indexOf(info.project.name)===0?2:1));expect(denied.status()).toBe(404);
 await test.info().attach('performance.json',{body:JSON.stringify(metrics),contentType:'application/json'});await fits(page);
});
test('logout clears session state before another account signs in',async({page},info)=>{
 const old=await (await page.request.get('/api/me')).json();await page.locator('#logout').click();await expect(page.locator('#auth-screen')).toBeVisible();expect((await page.request.get('/api/me')).status()).toBe(401);
 const next=(projects.indexOf(info.project.name)+1)%4;await page.locator('#auth-email').fill(`browser${next}@example.test`);await page.locator('#auth-pass').fill('browser-fixture-only-password');await page.locator('#auth-submit').click();await expect(page.locator('#workspace')).toBeVisible();const me=await (await page.request.get('/api/me')).json();expect(me.id).not.toBe(old.id);await navigate(page,'games');await page.locator('#analysis-queue summary').first().click();await expect(page.locator('[data-job]')).toHaveCount(1);await fits(page);
});
