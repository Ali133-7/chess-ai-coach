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

test('player names colours and recorded scores stay aligned with both game boards',async({page},info)=>{
 await navigate(page,'games');const first=page.locator('#game-list [data-open-game]').first();
 await expect(first.locator('[data-side="white"] .match-name')).toHaveText('browser_fixture'+projects.indexOf(info.project.name));
 await expect(first.locator('[data-side="white"] .match-color')).toHaveText('الأبيض');
 await expect(first.locator('[data-side="black"] .match-name')).toHaveText('Test Opponent');
 await expect(first.locator('[data-side="black"] .match-color')).toHaveText('الأسود');
 await first.focus();await page.keyboard.press('Enter');await expect(page.locator('#review-modal')).toBeVisible();
 const personal=page.locator('.match-player-rail[data-match-board="board"]');
 await expect(personal.first()).toHaveAttribute('data-side','black');await expect(personal.last().locator('.match-you')).toBeVisible();
 await expect(personal.last().locator('.match-turn')).toBeVisible();await page.locator('#next-move').click();await expect(personal.first().locator('.match-turn')).toBeVisible();
 await page.locator('#flip-board').click();await expect(personal.first()).toHaveAttribute('data-side','white');await expect(personal.last()).toHaveAttribute('data-side','black');
 await page.locator('#review-modal .language-select').selectOption('en');await expect(personal.first().locator('.match-color')).toHaveText('White');await expect(personal.last().locator('.match-color')).toHaveText('Black');
 await page.locator('#last-move').click();await expect(personal.locator('.match-turn:visible')).toHaveCount(0);await expect(personal.first().locator('.match-score')).toHaveText('1');await fits(page);
 if(['desktop','phone390'].includes(info.project.name))await page.screenshot({path:info.outputPath('personal-players.png')});
 await page.locator('#close-review').click();await navigate(page,'knowledge');await page.locator('[data-kc-tab="masters"]').click();
 await page.locator('#master-query').fill('Mikhail Tal');await page.locator('#master-search-form button').click();const card=page.locator('.master-game');await expect(card).toHaveCount(1);
 await expect(card.locator('[data-side="white"] .match-name')).toHaveText('Tal, Mihail');await expect(card.locator('[data-side="white"] .match-color')).toHaveText('White');await expect(card.locator('.match-title')).toHaveCount(0);
 await page.locator('[data-master-game]').click();const historical=page.locator('.match-player-rail[data-match-board="kc-board"]');await expect(historical.first()).toHaveAttribute('data-side','black');await expect(historical.last().locator('.match-name')).toHaveText('Tal, Mihail');
 await page.locator('#kc-flip').click();await expect(historical.first().locator('.match-name')).toHaveText('Tal, Mihail');await expect(historical.last()).toHaveAttribute('data-side','black');
 await page.locator('#kc-study-dialog .language-select').selectOption('ar');await expect(historical.first().locator('.match-color')).toHaveText('الأبيض');await expect(historical.last().locator('.match-color')).toHaveText('الأسود');
 for(const rail of await historical.all()){expect(await rail.evaluate(node=>node.scrollWidth<=node.clientWidth)).toBeTruthy();expect(Math.abs((await rail.boundingBox()).width-(await page.locator('#kc-board').boundingBox()).width)).toBeLessThan(2);}
 await expect(page.locator('#kc-first')).toBeInViewport();await fits(page);
 if(['desktop','phone390'].includes(info.project.name))await page.screenshot({path:info.outputPath('historical-players.png')});
});

test('expanded local game catalogue replays full PGN with offline autoplay',async({page},info)=>{
 await navigate(page,'knowledge');await page.locator('[data-kc-tab="masters"]').click();await expect(page.locator('[data-master-game]')).toHaveCount(3);
 await page.locator('#master-query').fill('Pragg Giri');await page.locator('#master-search-form button').click();await expect(page.locator('[data-master-game]')).toHaveCount(1);
 await page.locator('[data-master-game]').click();await expect(page.locator('#kc-study-dialog')).toBeVisible();await expect(page.locator('#kc-opening-title')).toContainText('2024');await expect(page.locator('#kc-board img').first()).toBeVisible();
 const max=Number(await page.locator('#kc-study-seek').getAttribute('max'));expect(max).toBeGreaterThan(40);let requests=0;page.on('request',()=>requests++);
 await page.locator('#kc-study-mode').click();await expect(page.locator('#kc-study-seek')).not.toHaveValue('0');await page.locator('#kc-study-mode').click();expect(requests).toBe(0);
 await page.locator('#kc-study-seek').evaluate((element,value)=>{element.value=String(value);element.dispatchEvent(new Event('input',{bubbles:true}));},max);await expect(page.locator('#kc-study-total')).toHaveText(max+' / '+max);
 const analysed=page.waitForResponse(r=>r.url().endsWith('/api/knowledge/position')&&r.request().method()==='POST'&&r.request().postDataJSON()?.refresh_engine===true);await page.locator('#master-analyse-position').click();const response=await analysed;expect(response.ok()).toBeTruthy();const position=await response.json();expect(position.engine.source).toBe('stockfish-local');expect(position.engine.pvs[0].moves.length).toBeGreaterThan(0);await expect(page.locator('#kc-engine')).toContainText('stockfish-local');
 const afterAnalysis=requests;await page.locator('#kc-first').click();await page.locator('#kc-study-mode').click();await expect(page.locator('#kc-study-seek')).not.toHaveValue('0');await page.locator('#kc-study-mode').click();expect(requests).toBe(afterAnalysis);
 await page.keyboard.press('Escape');await expect(page.locator('#kc-study-dialog')).toBeVisible();await fits(page);if(info.project.name==='phone390')await page.screenshot({path:info.outputPath('expanded-master-library.png')});
 await page.locator('#kc-study-close').click();await page.locator('.topbar .language-select').selectOption('en');await expect(page.locator('#master-scope option[value="all"]')).toHaveText('All archived games');await fits(page);
});

test('historical source filter and original license remain visible',async({page})=>{
 await navigate(page,'knowledge');await page.locator('[data-kc-tab="masters"]').click();await expect(page.locator('#master-source option[value="figshare-4276523-v1"]')).toHaveCount(1);
 await page.locator('#master-source').selectOption('figshare-4276523-v1');await page.locator('#master-search-form button').click();await expect(page.locator('[data-master-game]')).toHaveCount(2);await expect(page.locator('#master-games')).toContainText('Kasparov');
 await page.locator('[data-master-game]').first().click();await expect(page.locator('#kc-study-dialog')).toBeVisible();await expect(page.locator('#kc-opening-title')).toContainText('2000');await expect(page.locator('#master-license')).toHaveText('CC-BY-4.0');await expect(page.locator('#master-license')).toHaveAttribute('href','https://creativecommons.org/licenses/by/4.0/');await expect(page.locator('#master-source-credit')).toContainText('Ana Schaigorodsky');expect(await page.locator('#kc-study-seek').getAttribute('max')).toBe('67');await fits(page);
 await page.locator('#kc-study-close').click();await page.locator('#master-scope').selectOption('gm');await page.locator('#master-search-form button').click();await expect(page.locator('[data-master-game]')).toHaveCount(0);
 await page.locator('.topbar .language-select').selectOption('en');await expect(page.locator('#master-source option[value=""]')).toHaveText('All sources');await fits(page);
});

test('Mikhail Tal spelling finds real historical games and explains the GM filter',async({page})=>{
 await navigate(page,'knowledge');await page.locator('[data-kc-tab="masters"]').click();
 await page.locator('#master-query').fill('Mikhail Tal');await page.locator('#master-search-form button').click();await expect(page.locator('[data-master-game]')).toHaveCount(1);await expect(page.locator('#master-games')).toContainText('Tal, Mihail');await expect(page.locator('#master-count')).toContainText('Mikhail Tal');
 await page.locator('[data-master-game]').click();await expect(page.locator('#kc-opening-title')).toContainText('1958');await expect(page.locator('#master-license')).toHaveText('CC-BY-4.0');expect(await page.locator('#kc-study-seek').getAttribute('max')).toBe('39');await page.locator('#kc-study-close').click();
 await page.locator('#master-scope').selectOption('gm');await page.locator('#master-search-form button').click();await expect(page.locator('[data-master-game]')).toHaveCount(0);await expect(page.locator('#master-games')).toContainText('GM');await page.locator('#master-games button').click();await expect(page.locator('[data-master-game]')).toHaveCount(1);
 await page.locator('.topbar .language-select').selectOption('en');await expect(page.locator('#master-games')).toContainText('Tal, Mihail');await fits(page);
});
test('queue prioritization cancellation and saved-progress resume',async({page},info)=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));await navigate(page,'games');await page.locator('#analysis-queue summary').first().click();
 await expect(page.locator('[data-job]').first()).toBeVisible();const gid=await page.locator('[data-job]').first().getAttribute('data-job');const row=page.locator(`[data-job="${gid}"]`);await row.locator('[data-job-action="prioritize"]').click();await row.locator('[data-job-action="cancel"]').click();await expect(row.locator('[data-job-action="resume"]')).toBeVisible();await row.locator('[data-job-action="resume"]').click();await expect(row.locator('[data-job-action="cancel"]')).toBeVisible();await fits(page);expect(errors).toEqual([]);if(['phone390','desktop'].includes(info.project.name))await page.screenshot({path:info.outputPath('verified-queue.png')});
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
 const mine=await (await page.request.get('/api/analysis/jobs')).json();expect(mine.items.length).toBe(2);const denied=await page.request.get('/api/games/'+(projects.indexOf(info.project.name)===0?3:1));expect(denied.status()).toBe(404);
 await test.info().attach('performance.json',{body:JSON.stringify(metrics),contentType:'application/json'});await fits(page);
});
test('logout clears session state before another account signs in',async({page},info)=>{
 const old=await (await page.request.get('/api/me')).json();await page.locator('#logout').click();await expect(page.locator('#auth-screen')).toBeVisible();expect((await page.request.get('/api/me')).status()).toBe(401);
 const next=(projects.indexOf(info.project.name)+1)%4;await page.locator('#auth-email').fill(`browser${next}@example.test`);await page.locator('#auth-pass').fill('browser-fixture-only-password');await page.locator('#auth-submit').click();await expect(page.locator('#workspace')).toBeVisible();const me=await (await page.request.get('/api/me')).json();expect(me.id).not.toBe(old.id);await navigate(page,'games');await page.locator('#analysis-queue summary').first().click();await expect(page.locator('[data-job]')).toHaveCount(2);await fits(page);
});

test('account security status and individual session revocation',async({page,browser})=>{
 await navigate(page,'settings');await page.locator('#account-security-panel>summary').click();await expect(page.locator('#account-mfa-manage')).toBeVisible();await expect(page.locator('#account-send-verify')).toBeDisabled();
 const me=await (await page.request.get('/api/me')).json();const context=await browser.newContext();const r=await context.request.post('http://127.0.0.1:18024/api/auth/login',{data:{email:me.email,password:'browser-fixture-only-password'}});expect(r.ok()).toBeTruthy();
 const other=await (await context.request.get('http://127.0.0.1:18024/api/account/sessions')).json();const sid=other.items.find(x=>x.current).id;
 await page.locator('#account-security-panel>summary').click();await page.locator('#account-security-panel>summary').click();const deleted=page.waitForResponse(r=>r.request().method()==='DELETE'&&r.url().includes('/api/account/sessions/'));await page.locator(`[data-revoke-session="${sid}"]`).click();expect((await deleted).ok()).toBeTruthy();expect((await context.request.get('http://127.0.0.1:18024/api/me')).status()).toBe(401);await context.close();await fits(page);
});

function otp(secret){const crypto=require('node:crypto'),alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';let bits='';for(const c of secret)bits+=alphabet.indexOf(c).toString(2).padStart(5,'0');const key=Buffer.from(bits.match(/.{8}/g).map(b=>parseInt(b,2)));const counter=Buffer.alloc(8);counter.writeBigUInt64BE(BigInt(Math.floor(Date.now()/30000)));const mac=crypto.createHmac('sha1',key).update(counter).digest(),at=mac[19]&15;return String((mac.readUInt32BE(at)&0x7fffffff)%1000000).padStart(6,'0');}
test('MFA enrollment recovery-code login and safe disabling',async({page})=>{
 const me=await (await page.request.get('/api/me')).json();let codes=null;
 try{
  await navigate(page,'settings');await page.locator('#account-security-panel>summary').click();await page.locator('#account-mfa-manage input[name="password"]').fill('browser-fixture-only-password');await page.locator('#account-mfa-manage button').click();const secret=await page.locator('#account-enrollment code').textContent();await page.locator('#account-mfa-confirm input').fill(otp(secret));await page.locator('#account-mfa-confirm button').click();await expect(page.locator('#account-enrollment textarea')).toBeVisible();codes=(await page.locator('#account-enrollment textarea').inputValue()).split('\n');expect(codes.length).toBe(10);
  await page.locator('#logout').click();await expect(page.locator('#auth-screen')).toBeVisible();await page.locator('#auth-email').fill(me.email);await page.locator('#auth-pass').fill('browser-fixture-only-password');await page.locator('#auth-submit').click();await expect(page.locator('#account-mfa-login')).toBeVisible();await page.locator('#account-mfa-code').fill(codes[0]);await page.locator('#account-mfa-login button[type="submit"]').click();await expect(page.locator('#workspace')).toBeVisible();await fits(page);
 }finally{if(codes){const current=await (await page.request.get('/api/me')).json();const response=await page.request.post('/api/account/mfa/disable',{headers:{'X-CSRF-Token':current.csrf},data:{password:'browser-fixture-only-password',code:codes[1]}});expect(response.ok()).toBeTruthy();}}
});

test('diagnostics disclose missing evidence and additional search preserves original',async({page})=>{
 await navigate(page,'knowledge');await page.locator('#player-diagnostics>summary').click();await page.locator('#diagnostics-refresh').click();await expect(page.locator('#diagnostics-content')).toContainText('0');await fits(page);
 await navigate(page,'games');await page.locator('#game-list [data-open-game]').first().click();await expect(page.locator('#review-modal')).toBeVisible();await page.evaluate(()=>{S.ply=1;drawReview();});await page.locator('#analysis-evidence>summary').click();await expect(page.locator('#evidence-search')).toBeVisible();await page.locator('#evidence-search').click();await expect(page.locator('#evidence-result')).not.toBeEmpty();await page.locator('#close-review').click();await fits(page);
});
