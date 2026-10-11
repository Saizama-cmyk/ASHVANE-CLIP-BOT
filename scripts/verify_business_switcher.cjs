/* Normal-motion navigation against the isolated, stopped-engine preview. */
const {chromium}=require('C:/Users/wilco/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'no-preference'});
 const base='http://127.0.0.1:8790';
 const login=await context.request.post(base+'/api/auth/login',{headers:{'X-ClipBot':'1'},data:{password:'packaged-preview-2026'}});
 if(!login.ok())throw Error('Isolated preview sign-in failed');
 const page=await context.newPage(), errors=[], checks=[];
 page.on('pageerror',error=>errors.push(error.message));
 let legacyCacheHits=0;
 await page.route(/\/static\/business\.js$/,route=>{
  legacyCacheHits++;
  return route.fulfill({contentType:'text/javascript',body:'/* simulated cached two-business navigation */'});
 });
 try {
  await page.goto(base+'/',{waitUntil:'networkidle'});
  for(const business of ['music','social','stories','clips']) {
   await page.locator('#businessToggle').click();
   await page.locator('button[data-business="'+business+'"]').click();
   await page.locator('body[data-business="'+business+'"] .view.active').waitFor();
   await page.locator('.story-portal').waitFor({state:'detached'});
   const active=await page.locator('.view.active').getAttribute('id');
   const expected={music:'view-music',social:'view-social',stories:'view-stories',clips:'view-clips'}[business];
   if(active!==expected)throw Error(business+' opened '+active);
   checks.push(business);
  }
  await page.screenshot({path:'artifacts/business-switcher-normal-motion.png'});
  if(errors.length)throw Error(errors.join('\n'));
  if(legacyCacheHits)throw Error('Dashboard requested the legacy cached navigation URL');
  fs.writeFileSync('artifacts/business-switcher-normal-motion.json',JSON.stringify({checks,errors,normalMotion:true,legacyCacheHits},null,2));
  console.log(JSON.stringify({checks,errors,legacyCacheHits}));
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
