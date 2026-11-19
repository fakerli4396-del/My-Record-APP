"use strict";
const assert = require("node:assert/strict");
const { spawn, spawnSync } = require("node:child_process");
const { once } = require("node:events");
const { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, realpathSync, statSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join, dirname } = require("node:path");
const { setTimeout: delay } = require("node:timers/promises");
const { test } = require("node:test");

const browser = [
  process.env.RECORD_BROWSER,
  join(process.env["ProgramFiles(x86)"] || "", "Microsoft", "Edge", "Application", "msedge.exe"),
  join(process.env.ProgramFiles || "", "Google", "Chrome", "Application", "chrome.exe"),
].find(path => path && existsSync(path));

async function waitFor(probe, label, ms=12000) {
  const deadline = Date.now()+ms;
  do {
    const result = await probe();
    if (result) return result;
    await delay(45);
  } while (Date.now()<deadline);
  throw new Error("Timed out: "+label);
}

async function stop(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  const closed=once(child,"exit");
  child.kill();
  await closed;
}

async function socket(url) {
  const ws = new WebSocket(url);
  const listeners = new Map();
  const pending = new Map();
  let next = 0;
  await new Promise((resolve,reject)=>{
    ws.addEventListener("open",resolve,{once:true});
    ws.addEventListener("error",reject,{once:true});
  });
  ws.addEventListener("message",({data})=>{
    const reply=JSON.parse(data);
    if(reply.id) {
      const handle=pending.get(reply.id);
      if(!handle) return;
      pending.delete(reply.id);
      if (reply.error) handle.reject(new Error(reply.error.message));
      else handle.resolve(reply.result);
    } else for(const handler of listeners.get(reply.method)||[]) handler(reply.params);
  });
  ws.addEventListener("close",()=>{
    for(const {reject} of pending.values()) reject(new Error("Browser closed"));
    pending.clear();
  });
  return {
    on(method,handler) { listeners.set(method,[...(listeners.get(method)||[]),handler]); },
    send(method,params={}) {
      const id=++next;
      return new Promise((resolve,reject)=>{
        if(ws.readyState!==WebSocket.OPEN) { reject(new Error("Browser connection closed")); return; }
        pending.set(id,{resolve,reject});
        ws.send(JSON.stringify({id,method,params}));
      });
    },
    close() { ws.close(); }
  };
}

test("Windows browser: record, reconcile, navigate, back up and restore with all external requests blocked", {timeout:90000}, async () => {
  assert.ok(browser,"Install Microsoft Edge or Chrome, or set RECORD_BROWSER");
  const base=realpathSync(tmpdir());
  const temp=mkdtempSync(join(base,"my-record-browser-"));
  const file=join(temp,"中文 账本","record.db");
  const folder=join(temp,"中文 备份");
  mkdirSync(folder);
  const profile=join(temp,"profile");
  let server, child, cdp, browserControl, failure;
  const blocked=[], exceptions=[];
  let browserLog="", step="startup";
  try {
    server=spawn("python",["app.py","--db",file,"--port","0","--no-browser"],{windowsHide:true});
    let log="";
    server.stdout.on("data",buf=>{log+=buf;});
    server.stderr.on("data",buf=>{log+=buf;});
    const origin=await waitFor(()=> {
      if(server.exitCode!==null) throw new Error(log);
      return log.match(/http:\/\/127\.0\.0\.1:\d+/)?.[0];
    },"local Python process");
    child=spawn(browser,["--headless=new","--disable-gpu","--disable-background-networking","--disable-extensions",
      "--no-first-run","--no-default-browser-check","--disable-breakpad","--disable-crash-reporter","--disable-features=EdgeBackgroundModeEnabled","--remote-debugging-port=0","--user-data-dir="+profile,"about:blank"],
      {windowsHide:true});
    child.stderr.on("data",chunk=>{browserLog += chunk;});
    const port=await waitFor(()=>{
      const portFile=join(profile,"DevToolsActivePort");
      if (existsSync(portFile)) return readFileSync(portFile,"utf8").split(/\r?\n/)[0];
      if(child.exitCode!==null) throw new Error("Browser exited: "+browserLog);
    },"browser debugging port");
    const controlURL="http://127.0.0.1:"+port;
    const version=await (await fetch(controlURL+"/json/version")).json();
    browserControl=await socket(version.webSocketDebuggerUrl);
    const pages=await (await fetch(controlURL+"/json/list")).json();
    cdp=await socket(pages.find(tab=>tab.type==="page").webSocketDebuggerUrl);
    cdp.on("Runtime.exceptionThrown",e=>exceptions.push(e.exceptionDetails.exception?.description||e.exceptionDetails.text));
    cdp.on("Fetch.requestPaused", e=>{
      const local=new URL(e.request.url).origin===origin;
      if (!local) blocked.push(e.request.url);
      cdp.send(local?"Fetch.continueRequest":"Fetch.failRequest",
        local?{requestId:e.requestId}:{requestId:e.requestId,errorReason:"BlockedByClient"}).catch(()=>{});
    });
    await cdp.send("Runtime.enable");
    await cdp.send("Page.enable");
    await cdp.send("Fetch.enable",{patterns:[{urlPattern:"http://*"},{urlPattern:"https://*"}]});
    await cdp.send("Page.navigate",{url:origin});
    async function evaluate(expression) {
      const reply=await cdp.send("Runtime.evaluate",{expression,awaitPromise:true,returnByValue:true});
      if(reply.exceptionDetails) throw new Error(reply.exceptionDetails.exception?.description||reply.exceptionDetails.text);
      return reply.result.value;
    }
    const visible=label => waitFor(()=>evaluate("Boolean(document.querySelector('main')?.innerText.includes("+JSON.stringify(label)+"))"),label);
    const text=()=>evaluate("document.querySelector('main').innerText");
    async function click(selector) {
      assert.equal(await evaluate("(()=>{const el=document.querySelector("+JSON.stringify(selector)+");if(!el)return false;el.click();return true})()"),true,selector);
    }
    async function fill(values) {
      await evaluate("(()=>{for(const [key,value] of Object.entries("+JSON.stringify(values)+
        ")){const el=document.querySelector('dialog [name='+key+']');if(!el)throw new Error(key);el.value=value;el.dispatchEvent(new Event('change',{bubbles:true}));}})()");
    }
    async function submit(nextDialog) {
      await click('dialog [type="submit"]');
      await waitFor(async()=>{
        const error=await evaluate("document.querySelector('dialog[open] [role=alert]')?.textContent");
        if(error) throw new Error(error);
        return nextDialog ? evaluate("document.querySelector('dialog[open] h2')?.textContent === "+JSON.stringify(nextDialog)) :
          evaluate("!document.querySelector('dialog[open]')");
      },"successful form submission");
    }
    const action=key=>click('[data-act="'+key+'"]');
    const goto=async(hash,title)=>{
      await evaluate("location.hash="+JSON.stringify(hash));
      await visible(title);
    };
    step="home load";
    await visible("首页总览");
    assert.equal(await evaluate("typeof AssetUI"),"object");
    step="category and asset navigation";
    await goto("categories","收支类目");
    assert.equal(await evaluate("document.querySelectorAll('.category-grid .category-card').length >= 20"),true);
    assert.equal(await evaluate("document.querySelectorAll('.category-icon').length >= 40"),true);
    await cdp.send("Emulation.setDeviceMetricsOverride",{width:1440,height:900,deviceScaleFactor:2,mobile:false});
    const geometry=await evaluate(`(()=>{
      const boxes=selector=>Array.from(document.querySelectorAll(selector),e=>e.getBoundingClientRect());
      const nav=boxes('nav a'), cards=boxes('.category-card'), row=cards.filter(c=>c.top===cards[0].top);
      return {brand:document.querySelector('.brand').innerText,navCount:nav.length,
        even:nav.every(r=>Math.abs(r.height-nav[0].height)<1),height:nav.at(-1).bottom-nav[0].top,
        columns:row.length,aligned:row.every(c=>Math.abs(c.bottom-row[0].bottom)<1)};
    })()`);
    assert.match(geometry.brand,/My Record/);
    assert.equal(geometry.navCount,6);
    assert.ok(geometry.even && geometry.height>700);
    assert.ok(geometry.columns>=2 && geometry.aligned);
    await click('nav a[href="#assets"]');
    await visible("家庭资产概览");
    assert.doesNotMatch(await text(),/新建一级类目/);
    await visible("当前资产配置");
    await goto("home","首页总览");
    assert.equal(await evaluate("document.querySelectorAll('.home-wealth [data-owner]').length"),2);
    step="book and account setup";
    await action("newbook"); await fill({name:"家庭账本"}); await submit();
    await action("newbook"); await fill({name:"个人账本"}); await submit();
    await goto("assets?owner=personal&tab=accounts","个人资产概览");
    await action("newaccount:personal"); await fill({name:"银行卡",opening:"1000.00",opening_day:"2026-01-01"}); await submit();
    await goto("assets?owner=personal&tab=overview","当前资产配置");
    assert.match(await evaluate("document.querySelector('.allocation-ring').textContent"),/100.0%/);
    assert.equal(await evaluate("document.querySelector('.ring-total').textContent"),"¥1,000.00");
    assert.equal(await evaluate("document.querySelector('.slice').getAttribute('stroke-dasharray')"),"100 0");
    await goto("home","首页总览");
    step="current book defaults";
    for(const id of ["2","1"]){
      await evaluate("(()=>{const el=document.querySelector('[name=current_book]');el.value="+JSON.stringify(id)+";el.dispatchEvent(new Event('change'));})()");
      await waitFor(()=>evaluate("state.current_book === "+JSON.stringify(id)),"current book saved");
      await click("#quick");
      assert.equal(await evaluate("document.querySelector('dialog [name=book_id]').value"),id);
      await click("dialog [data-close]");
    }
    await click('a[href^="#book/1/"]');
    await visible("月历");
    const dayPath=await evaluate("document.querySelectorAll('.cell')[11].hash");
    await click('.cell[href="'+dayPath+'"]');
    await visible("当天暂无账单");
    await click("#quick");
    assert.equal(await evaluate("document.querySelectorAll('dialog .category-picker button').length >= 30"),true);
    assert.equal(await evaluate("document.querySelector('dialog [name=day]').value"),dayPath.split("/").at(-1));
    await fill({amount:"200.00",category_id:"6",note:"超市购物"});
    await submit();
    await visible("超市购物");
    assert.match(await text(),/200\.00/);
    await click('a[href="'+dayPath.split("/").slice(0,-1).join("/")+'"]');
    await visible("月历");
    assert.match(await evaluate("document.querySelector("+JSON.stringify('.cell[href="'+dayPath+'"]')+").innerText"),/200\.00/);
    const month=dayPath.split("/")[2];
    step="budget, bill calendar and period analysis";
    await goto("bills?book=1&month="+month,"账单明细");
    await goto("bills?month="+month,"账单明细");
    const alignment=await evaluate(`(()=>{
      const fields=[...document.querySelectorAll('#filters>label')];
      const boxes=fields.map(f=>f.querySelector('input,select').getBoundingClientRect());
      return {heights:boxes.map(b=>b.height),tops:fields.slice(0,2).map(f=>f.getBoundingClientRect().top),
        toolbar:[...document.querySelectorAll('#filters>.toolbar>button,#filters>.toolbar>.button')].map(b=>b.getBoundingClientRect().height)};
    })()`);
    assert.ok(alignment.heights.every(h=>Math.abs(h-44)<1));
    assert.ok(alignment.toolbar.every(h=>Math.abs(h-44)<1));
    assert.ok(Math.abs(alignment.tops[0]-alignment.tops[1])<1);
    await action("budget::"+month);
    assert.equal(await evaluate("document.querySelectorAll('dialog [name=book_id] option').length"),2);
    await fill({book_id:"1"});await fill({amount:"100"});await submit();
    assert.match(await text(),/本月预算超支/);
    await goto("bills?book=1&month="+month+"&view=calendar&day="+dayPath.split("/").at(-1),"当日收支明细");
    assert.match(await text(),/超市购物/);
    assert.ok(await evaluate("document.querySelector('.selected-day')"));
    for(const period of ["week","month","year"]){
      await goto("stats?book=1&month="+month+"&period="+period+"&kind=income","收入明细排行");
      assert.equal(await evaluate("document.querySelector('#statsfilter [name=period]').value"),period);
    }
    await evaluate("(async()=>{await api('/api/action',{action:'position',kind:'borrow',owner:'family',name:'测试借贷',day:today(),opening_only:true,principal:100000,request_id:crypto.randomUUID()});await refresh();})()");
    await goto("assets?owner=family&tab=borrow","负债明细看板");
    const loanID=await evaluate("state.positions.find(p=>p.name==='测试借贷').id");
    await action("loanplan:"+loanID);await fill({book_id:"1",annual_rate:"3.5",m0:"100"});await submit();
    assert.match(await text(),/3.5%/);
    assert.equal(await evaluate("document.querySelectorAll('.board-content button').length"),0);
    assert.equal(await evaluate("document.querySelector('.loan-board thead th:last-child').textContent"),"操作");
    assert.ok(await evaluate("[...document.querySelectorAll('.loan-board th,.loan-board td')].every(e=>getComputedStyle(e).textAlign==='center'&&getComputedStyle(e).verticalAlign==='middle')"));
    const boardAlignment=await evaluate(`(()=>{
      const form=document.querySelector('.board-controls'),controls=[...form.querySelectorAll('input:not([type=hidden]),select,button')].map(e=>e.getBoundingClientRect());
      return {bottoms:controls.map(c=>c.bottom),left:controls[0].left,right:controls.at(-1).right,center:form.getBoundingClientRect().left+form.getBoundingClientRect().width/2};
    })()`);
    assert.ok(Math.max(...boardAlignment.bottoms)-Math.min(...boardAlignment.bottoms)<1);
    assert.ok(Math.abs((boardAlignment.left+boardAlignment.right)/2-boardAlignment.center)<2);
    await cdp.send("Emulation.setDeviceMetricsOverride",{width:800,height:800,deviceScaleFactor:1,mobile:false});
    assert.ok(await evaluate("document.querySelector('.loan-panel').getBoundingClientRect().right<=innerWidth"));
    await cdp.send("Emulation.clearDeviceMetricsOverride");

    await goto("assets?owner=personal&tab=lend","借款应收看板");
    await goto("settings","本地数据文件");
    await action("restore");
    assert.equal(await evaluate("document.querySelector('#import-upload').accept"),".db,.xls,.xlsx");
    await click("dialog [data-close]");
    await goto("assets?owner=family&tab=borrow","负债明细看板");
    await action("imageimport:family:borrow");
    assert.ok(await evaluate("document.querySelector('#ocr-file').accept.includes('image/png')"));
    await click("dialog [data-close]");
    await goto("settings","本地数据文件");
    await action("exportdata");
    assert.equal(await evaluate("document.querySelectorAll('dialog [name=format] option').length"),3);
    await click("dialog [data-close]");
    step="statistics regression";
    await goto("stats?book=1&month="+month,"支出类目排行");
    const bars=await evaluate(`Array.from(document.querySelectorAll('.stat-bar'),bar=>({
      color:getComputedStyle(bar).getPropertyValue('--fill').trim(),height:bar.getBoundingClientRect().height,
      value:bar.value,kind:bar.classList[1]}))`);
    assert.equal(bars.filter(b=>b.kind==="income-bar").length,6);
    assert.equal(bars.filter(b=>b.kind==="expense-bar").length,6);
    assert.ok(bars.every(b=>b.height>=15));
    assert.equal(new Set(bars.map(b=>b.color)).size,3);
    assert.ok(bars.some(b=>b.kind==="rank-bar" && b.value===20000));
    await cdp.send("Emulation.setDeviceMetricsOverride",{width:700,height:740,deviceScaleFactor:1,mobile:false});
    assert.ok(await evaluate("document.querySelector('.trend').scrollWidth<=document.querySelector('.trend').clientWidth"));
    await cdp.send("Emulation.clearDeviceMetricsOverride");
    await click('.ranking a');
    await visible("超市购物");
    assert.equal(await evaluate("document.querySelector('#filters [name=book]').value"),"1");
    assert.equal(await evaluate("document.querySelector('#filters [name=category]').value"),"6");
    await evaluate("history.back()");
    await visible("支出类目排行");
    assert.equal(await evaluate("document.querySelector('#statsfilter [name=book]').value"),"1");
    assert.equal(await evaluate("document.querySelector('#statsfilter [name=month]').value"),month);
    await click('.ranking a');
    await visible("超市购物");
    await cdp.send("Page.reload");
    await visible("超市购物");
    await goto("assets/account/1","当前余额");
    assert.match(await text(),/800\.00/);
    for(const [hash,title] of [["categories","收支类目"],["assets?owner=family&tab=invest","新增投资"],["settings","本地数据文件"]]) await goto(hash,title);
    step="family opening inventory";
    await goto("inventory?book=1","家庭资产盘点");
    await click('[data-inventory-add="physical"]');
    await evaluate(`(()=>{
      const row=document.querySelector('[data-inventory-row="0"]');
      for(const [key,value] of Object.entries({name:"盘点住宅",subtype:"property",value:"10000",cost:"8000",debt:"3000",detail:"90平方米，剩余20年"}))
        row.querySelector('[name="'+key+'"]').value=value;
    })()`);
    await click("#inventory-preview");
    assert.match(await evaluate("document.querySelector('dialog').innerText"),/10,000.00/);
    await submit();
    await visible("期初盘点");
    assert.match(await text(),/盘点住宅/);
    await goto("assets?owner=family&tab=charts","走势图");
    const controls=await evaluate(`(()=>{
      const bottom=e=>e.getBoundingClientRect().bottom;
      const form=document.querySelector('#assetchart');
      return [bottom(form.querySelector('input:not([type=hidden])')),bottom(form.querySelector('select')),bottom(form.querySelector('button'))];
    })()`);
    assert.ok(Math.max(...controls)-Math.min(...controls)<2);
    assert.equal(await evaluate("document.querySelectorAll('.asset-trend .trend-point').length"),new Date().getMonth()+1);
    assert.match(await evaluate("document.querySelector('.peak-label').textContent"),/10,000.00/);
    await goto("settings","本地数据文件");
    const shown=await evaluate("document.querySelector('main code').textContent");
    const displayed=statSync(shown,{bigint:true}), expected=statSync(file,{bigint:true});
    assert.deepEqual([displayed.dev,displayed.ino],[expected.dev,expected.ino]);
    step="backup";
    if(process.env.RECORD_SCREENSHOT) {
      await goto("categories","收支类目");
      const shot=await cdp.send("Page.captureScreenshot",{format:"png"});
      require("node:fs").writeFileSync(process.env.RECORD_SCREENSHOT,Buffer.from(shot.data,"base64"));
      await goto("settings","本地数据文件");
    }
    await action("backup"); await fill({path:folder});
    step="backup submit"; await submit();
    step="backup result";
    const source=await waitFor(async()=>{
      const notice=await evaluate("document.querySelector('#notice').textContent");
      return notice.match(/^备份已保存至 (.+)$/u)?.[1];
    },"backup path");
    step="edit after backup";
    await goto("home","首页总览");
    await action("newbook"); await fill({name:"临时账本"}); await submit();
    await goto("settings","本地数据文件");
    step="restore preview and cancel";
    await action("restore"); await fill({path:source}); await submit("确认替换当前账本");
    await waitFor(()=>evaluate("document.querySelector('dialog[open]')?.innerText.includes('账本 2 个')"),"restore preview");
    await click("dialog [data-close]");
    await goto("home","临时账本");
    step="restore confirm";
    await goto("settings","本地数据文件");
    await action("restore"); await fill({path:source}); await submit("确认替换当前账本");
    await waitFor(()=>evaluate("document.querySelector('dialog[open]')?.innerText.includes('确认替换')"),"restore confirmation");
    await submit();
    await visible("家庭账本");
    assert.doesNotMatch(await text(),/临时账本/);
    assert.deepEqual(exceptions,[]);
    assert.deepEqual(blocked,[],"The app must not request external resources");
  } catch(error) {
    failure=new Error(step+" · browser exit "+child?.exitCode+"\n"+browserLog,{cause:error});
  } finally {
    if (cdp) cdp.close();
    if (browserControl) {
      const exited=child.exitCode===null ? once(child,"exit") : Promise.resolve();
      try { await browserControl.send("Browser.close"); } catch {}
      browserControl.close();
      await Promise.race([exited,delay(4000,{},{ref:false})]);
    }
    await stop(child);
    await stop(server);
    try {
      assert.equal(dirname(realpathSync(temp)),base,"Temporary directory must remain under the test base");
      try { rmSync(temp,{recursive:true,force:true,maxRetries:3,retryDelay:100}); }
      catch(error) {
        const cleanup=spawnSync("python",["-c","import shutil,sys; shutil.rmtree(sys.argv[1])",temp],{encoding:"utf8",windowsHide:true});
        if(cleanup.status!==0) throw new Error(cleanup.stderr,{cause:error});
      }
    } catch(error) {
      if(failure) throw new AggregateError([failure,error],"Browser scenario and cleanup failed");
      throw error;
    }
    if(failure) throw failure;
  }
});
