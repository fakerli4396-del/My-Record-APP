"use strict";
const page = document.querySelector("#page");
const drawer = document.querySelector("#drawer");
const notice = document.querySelector("#notice");
const sections = {home:"首页总览",bills:"账单明细",stats:"统计分析",categories:"收支类目",assets:"资产与借贷",settings:"数据与设置"};
const kinds = {income:"收入",expense:"支出",transfer:"转账",inflow:"资金流入",outflow:"资金流出"};
const owners = {family:"家庭",personal:"个人"};
const h = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[ch]);
const money = cents => new Intl.NumberFormat("zh-CN",{style:"currency",currency:"CNY"}).format((cents || 0)/100);
const by = (list,id) => list.find(row => row.id === Number(id));
const pad = number => String(number).padStart(2,"0");
const localDate = d => String(d.getFullYear()).padStart(4,"0") + "-" + pad(d.getMonth()+1) + "-" + pad(d.getDate());
const today = () => localDate(new Date());
const thisMonth = () => today().slice(0,7);
const monthOf = value => /^\d{4}-(0[1-9]|1[0-2])$/.test(value || "") ? value : thisMonth();
const btn = (id,label,primary=false) => '<button type="button" data-act="' + h(id) + '"' + (primary?' class="primary"':'') + '>' + h(label) + '</button>';
const link = (href,label) => '<a class="button" href="#' + h(href) + '">' + h(label) + '</a>';
const options = (values,selected) => values.map(([key,label]) => '<option value="' + h(key) + '"' + (String(key)===String(selected)?" selected":"") + '>' + h(label) + '</option>').join("");
const field = (label,content) => '<label>' + h(label) + content + '</label>';
const select = (key,values,selected) => '<select name="' + key + '" required>' + options(values,selected) + '</select>';
const input = (key,value="",attributes="") => '<input name="' + key + '" value="' + h(value) + '" ' + attributes + '>';
const empty = (message,action="") => '<div class="panel empty"><p>' + h(message) + '</p>' + action + '</div>';
const heading = (title,sub="",tools="") => '<div class="heading"><div><h1>' + h(title) + '</h1>' + (sub?'<p class="muted">'+h(sub)+'</p>':'') + '</div><div class="toolbar">' + tools + '</div></div>';
const categoryLabel = c => c ? [by(state.categories,c.parent_id)?.name,c.name].filter(Boolean).join(" / ") : "";
const accountLabel = a => a ? owners[a.owner] + " · " + a.name : "";
let session, state, actions={}, noticeTimer;
let busy = false;
function flash(message) {
  clearTimeout(noticeTimer);
  notice.textContent = message;
  noticeTimer = setTimeout(() => { notice.textContent = ""; },3000);
}
async function api(path,data) {
  const settings = data ? {method:"POST",headers:{"Content-Type":"application/json","X-Record-Token":session.token},body:JSON.stringify(data)} : {};
  const response = await fetch(path,settings);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error);
  return result;
}
async function refresh() {
  const next=await api("/api/state");
  if(next.instance!==session.instance) throw new Error("数据已恢复，请刷新页面重新打开");
  state=next;
  AssetUI.clear();
}
function route() {
  const [path,query=""] = (location.hash.slice(1) || "home").split("?");
  return {parts:path.split("/"), q:new URLSearchParams(query)};
}
const {summarize,filterBills,rankExpenses} = RecordReports;
function metrics(stat,labels={income:"收入",expense:"支出",net:"结余"}) {
  return '<div class="metrics">' + Object.entries(labels).map(([key,label]) =>
    '<span><small>'+h(label)+'</small><strong class="'+h(key)+'">'+money(stat[key])+'</strong></span>').join("") + '</div>';
}
function parseMoney(value, signed=false, zero=false) {
  if (typeof value !== "string" || !/^-?\d+(\.\d{1,2})?$/.test(value.trim())) throw new Error("请输入最多两位小数的金额");
  const text=value.trim(), [whole,fraction=""]=text.replace(/^-/,"").split(".");
  const result=(Number(whole)*100+Number(fraction.padEnd(2,"0")))*(text.startsWith("-")?-1:1);
  if (!Number.isSafeInteger(result) || Math.abs(result)>999999999999 || (!signed && result<0) || (!zero && result===0)) throw new Error("金额超出允许范围");
  return result;
}
function moneyInput(key,cents) { return input(key,cents == null?"":(cents/100).toFixed(2),'required inputmode="decimal"'); }
function openForm(title,fields,onSave,label="保存") {
  drawer.innerHTML = '<form><h2>'+h(title)+'</h2>'+fields+'<p class="error" role="alert"></p><footer><button type="button" data-close>取消</button><button class="primary" type="submit">'+h(label)+'</button></footer></form>';
  const form=drawer.querySelector("form"), error=form.querySelector(".error"), submit=form.querySelector('[type="submit"]');
  drawer.querySelector("[data-close]").onclick=()=>{ if(!busy) drawer.close(); };
  drawer.oncancel=event=>{if(busy) event.preventDefault();};
  let previousPayload="", requestId="";
  form.onsubmit=async event=>{
    event.preventDefault();
    if(busy) return;
    busy=true; submit.disabled=true; error.textContent="";
    try {
      await onSave(Object.fromEntries(new FormData(form)),async data=>{
        const key=JSON.stringify(data);
        if (key!==previousPayload) { previousPayload=key; requestId=crypto.randomUUID(); }
        return api("/api/action",{...data,request_id:requestId});
      });
      drawer.close();
      flash("已保存");
    } catch (failure) { error.textContent=failure.message; }
    finally { busy=false; submit.disabled=false; }
  };
  if (!drawer.open) drawer.showModal();
  return form;
}
async function saveAndRender(send, data, message) {
  await send(data);
  await refresh();
  render();
  if(message) setTimeout(()=>flash(message),0);
}
function bookForm(book) {
  openForm(book?"修改账本名称":"新建账本",field("账本名称",input("name",book?.name,'required maxlength="80"')),
    (d,send)=>saveAndRender(send,{action:"book",...(book?{id:book.id}:{}),...d}));
}
function accountForm(owner="personal",old) { return AssetUI.accountForm(owner,old); }
function ask(title,message,onSave,label="确认") {
  openForm(title,"<p>"+h(message)+"</p>",(_,send)=>onSave(send),label);
}
function billForm(original,context={}) {
  const bill=original || {};
  const books=state.books.filter(b=>!b.archived || b.id===bill.book_id);
  const accountChoices=state.accounts.map(a=>[a.id,accountLabel(a)]);
  if (!books.length) { bookForm(); return; }
  if (!accountChoices.length) { accountForm(); return; }
  const form=openForm(original?"编辑账单":"记一笔",
    field("类型",select("kind",Object.entries(kinds).slice(0,3),bill.kind || "expense"))+
    field("金额（元）",moneyInput("amount",bill.amount))+
    field("账本",select("book_id",books.map(b=>[b.id,b.name]),bill.book_id||context.book))+
    field("日期",input("day",bill.day || context.day || today(),'required type="date"'))+
    '<div id="bill-fields"></div>'+field("备注",input("note",bill.note,'maxlength="500"')),
    (d,send)=>saveAndRender(send,{action:"bill",...(original?{id:original.id}:{}),...d,amount:parseMoney(d.amount),
      book_id:Number(d.book_id), account_id:Number(d.account_id),category_id:Number(d.category_id),
      to_account_id:Number(d.to_account_id)},original && d.day!==original.day ? "已移至 "+d.day : ""));
  const fields=form.querySelector("#bill-fields");
  const populate=()=>{
    const kind=form.elements.kind.value, selected=fields.querySelector('[name="account_id"]')?.value || bill.account_id;
    fields.className="fields";
    fields.innerHTML=field(kind==="transfer"?"转出账户":"资金账户",select("account_id",accountChoices,selected));
    if(kind==="transfer") fields.innerHTML+=field("转入账户",select("to_account_id",[["","请选择"],...accountChoices],bill.to_account_id));
    else {
      const list=state.categories.filter(c=>c.kind===kind && ((c.enabled && (!c.parent_id || by(state.categories,c.parent_id)?.enabled)) || c.id===bill.category_id));
      fields.innerHTML+=field("收支类目",select("category_id",[["","请选择"],...list.map(c=>[c.id,categoryLabel(c)])],bill.category_id));
    }
  };
  form.elements.kind.onchange=populate;
  populate();
}
function viewHome() {
  const current=state.books.filter(b=>!b.archived), archived=state.books.filter(b=>b.archived);
  const card=b=>'<article class="panel"><h2><a href="#book/'+b.id+'/'+thisMonth()+'">'+h(b.name)+'</a></h2>'+
    metrics(summarize(state.bills.filter(row=>row.book_id===b.id && row.day.startsWith(thisMonth()))))+
    '<div class="toolbar">'+link("book/"+b.id+"/"+thisMonth(),"打开月历")+
    '<details><summary>账本操作</summary>'+btn("rename:"+b.id,"改名")+btn("archive:"+b.id,b.archived?"恢复":"归档")+'</details></div></article>';
  return heading("首页总览",thisMonth()+" · 账本收支",btn("newbook","新建账本",true))+
    AssetUI.home()+
    (current.length?'<div class="grid">'+current.map(card).join("")+'</div>':empty(state.books.length?"暂无使用中的账本":"还没有账本",btn("newbook",state.books.length?"新建账本":"新建第一个账本",true)))+
    '<details class="panel"><summary>已归档账本（'+archived.length+'）</summary><div class="grid">'+archived.map(card).join("")+'</div></details>';
}
function monthShift(month,offset) {
  const [y,m]=month.split("-").map(Number);
  const date=new Date(2000,0,1);
  date.setFullYear(y,m-1+offset,1);
  return localDate(date).slice(0,7);
}
function viewCalendar(book,month) {
  const [year,num]=month.split("-").map(Number), date=new Date(2000,0,1);
  date.setFullYear(year,num-1,1);
  const offset=(date.getDay()+6)%7;
  date.setFullYear(year,num,0);
  const list=state.bills.filter(b=>b.book_id===book.id && b.day.startsWith(month));
  const base="book/"+book.id+"/";
  let grid=["一","二","三","四","五","六","日"].map(d=>'<span class="weekday">周'+d+'</span>').join("")+"<span></span>".repeat(offset);
  for(let i=1;i<=date.getDate();i++){
    const value=month+"-"+pad(i), stat=summarize(list.filter(b=>b.day===value));
    grid+='<a class="cell'+(value===today()?' today':'')+'" href="#'+base+month+'/'+value+'">'+i+
      (stat.income?'<small class="income">入 '+money(stat.income)+'</small>':'')+
      (stat.expense?'<small class="expense">出 '+money(stat.expense)+'</small>':'')+'</a>';
  }
  return heading(book.name,month+" 月历",link("home","返回首页"))+
    '<div class="panel"><div class="row">'+link(base+monthShift(month,-1),"上月")+link(base+thisMonth(),"回到本月")+
    link(base+monthShift(month,1),"下月")+'</div>'+metrics(summarize(list))+'</div><div class="calendar">'+grid+'</div>';
}
function billTable(list) {
  if (!list.length) return empty("没有符合条件的账单");
  let current="";
  const body=list.map(b=>{
    const account=accountLabel(by(state.accounts,b.account_id));
    const description=b.kind==="transfer"?account+" → "+accountLabel(by(state.accounts,b.to_account_id)):account;
    const group=current===b.day?"":'<tr class="date-row"><th colspan="5">'+h(b.day)+'</th></tr>';
    current=b.day;
    const controls=b.source_type?link("assets/"+b.source_type+"/"+b.source_id,"查看关联详情"):btn("edit:"+b.id,"编辑")+btn("del:"+b.id,"删除");
    return group+'<tr><td>'+h(categoryLabel(by(state.categories,b.category_id)) || kinds[b.kind])+'<br><small>'+h(kinds[b.kind])+'</small></td><td>'+h(by(state.books,b.book_id)?.name)+'<br><small>'+h(description)+'</small></td>'+
      '<td class="'+h(b.kind)+'">'+money(b.amount)+'</td><td>'+h(b.note)+'</td><td>'+controls+'</td></tr>';
  }).join("");
  return '<div class="panel"><table class="table"><thead><tr><th>类目 / 类型</th><th>账本与账户</th><th>金额</th><th>备注</th><th>操作</th></tr></thead><tbody>'+body+'</tbody></table></div>';
}
function filterRoute(values) {
  const params=new URLSearchParams();
  for (const [key,value] of Object.entries(values)) if(value) params.set(key,value);
  return params.size ? "?"+params.toString() : "";
}
function viewBills(q) {
  const filters=Object.fromEntries(q);
  const all=(key,label,choices)=>field(label,select(key,[["", "全部"],...choices],q.get(key)||"").replace(" required",""));
  const form='<form id="filters" class="filter-grid">'+
    field("开始日期",input("from",q.get("from"),'type="date"'))+field("结束日期",input("to",q.get("to"),'type="date"'))+
    all("book","账本",state.books.map(b=>[b.id,b.name]))+all("kind","类型",Object.entries(kinds))+
    all("category","类目",state.categories.map(c=>[c.id,categoryLabel(c)]))+
    all("account","账户",state.accounts.map(a=>[a.id,accountLabel(a)]))+
    field("搜索备注",input("note",q.get("note"),'placeholder="输入关键词"'))+
    '<div class="toolbar"><button class="primary">筛选</button>'+link("bills","清空")+'</div></form>';
  const list=filterBills(state.bills,filters);
  return heading("账单明细",list.length+" 笔记录",btn("quick","记一笔",true))+
    '<div class="panel">'+form+'</div>'+billTable(list);
}
function viewStats(q) {
  const month=monthOf(q.get("month")), book=q.get("book") || "";
  const list=filterBills(state.bills,{book}), current=list.filter(b=>b.day.startsWith(month));
  const previous=monthShift(month,-1);
  const now=summarize(current), before=summarize(list.filter(b=>b.day.startsWith(previous)));
  const comparison={income:now.income-before.income,expense:now.expense-before.expense,net:now.net-before.net};
  const months=Array.from({length:6},(_,i)=>monthShift(month,i-5));
  const trend=months.map(m=>[m,summarize(list.filter(b=>b.day.startsWith(m)))]);
  const ceiling=Math.max(1,...trend.flatMap(([,s])=>[s.income,s.expense]));
  const last=new Date(2000,0,1);
  last.setFullYear(Number(month.slice(0,4)),Number(month.slice(5,7)),0);
  const rank=rankExpenses(current);
  const statsForm='<form id="statsfilter" class="row">'+field("月份",input("month",month,'type="month" required'))+
    field("账本",select("book",[["","全部账本"],...state.books.map(b=>[b.id,b.name])],book).replace(" required",""))+
    '<button class="primary">查看</button></form>';
  const monthly='<div class="panel"><h2>近六个月收支趋势</h2><div class="trend">'+trend.map(([m,s])=>
    '<div><strong>'+m+'</strong><span class="income">入 '+money(s.income)+'</span><meter min="0" max="'+ceiling+'" value="'+s.income+'" aria-label="'+m+' 收入"></meter>'+
    '<span class="expense">出 '+money(s.expense)+'</span><meter min="0" max="'+ceiling+'" value="'+s.expense+'" aria-label="'+m+' 支出"></meter></div>').join("")+'</div></div>';
  const ranking=rank.map(([id,value],i)=>'<li><a href="#bills'+h(filterRoute({book,from:month+"-01",to:localDate(last),kind:"expense",category:id}))+'">'+
    h(categoryLabel(by(state.categories,id)) || "其他支出")+'</a><strong>'+money(value)+'</strong><meter min="0" max="'+rank[0][1]+'" value="'+value+'" aria-label="排行 '+(i+1)+'"></meter></li>').join("");
  return heading("统计分析",month+" · 月度收支")+'<div class="panel">'+statsForm+metrics(now)+'</div>'+
    '<div class="panel"><h2>上月对比 · '+previous+'</h2>'+metrics(before)+
    '<p class="muted">本月与上月差额</p>'+metrics(comparison)+'</div>'+
    monthly+'<div class="panel"><h2>支出类目排行</h2>'+(ranking?'<ol class="ranking">'+ranking+'</ol>':'<p class="muted">本月暂无支出</p>')+'</div>';
}
function viewCategories(q) {
  const kind=q.get("kind")==="income"?"income":"expense";
  const list=state.categories.filter(c=>c.kind===kind);
  const controls=c=>btn("catrename:"+c.id,"改名")+btn("cattoggle:"+c.id,c.enabled?"停用":"启用");
  const line=c=>'<div class="category-line"><span>'+h(c.name)+'</span><div class="toolbar">'+controls(c)+'</div></div>';
  const group=c=>{
    const children=list.filter(k=>k.parent_id===c.id), active=children.filter(k=>k.enabled), off=children.filter(k=>!k.enabled);
    return '<details class="panel" open><summary>'+h(c.name)+(c.enabled?"":" · 已停用")+'</summary><div class="toolbar">'+controls(c)+
      (c.enabled?btn("catchild:"+c.id,"添加二级类目"):"")+'</div>'+active.map(line).join("")+
      (off.length?'<details><summary>已停用的二级类目</summary>'+off.map(line).join("")+'</details>':"")+'</details>';
  };
  const roots=list.filter(c=>!c.parent_id), off=roots.filter(c=>!c.enabled);
  return heading("收支类目","管理两级分类",btn("catnew:"+kind,"新建一级类目",true))+
    '<div class="row">'+link("categories?kind=income","收入")+link("categories?kind=expense","支出")+'</div>'+
    roots.filter(c=>c.enabled).map(group).join("")+(off.length?'<details class="panel"><summary>已停用的一级类目</summary>'+off.map(group).join("")+'</details>':"");
}
function categoryForm(kind,parent,old) {
  openForm(old?"修改类目名称":parent?"在「"+parent.name+"」下添加类目":"新建"+kinds[kind]+"类目",
    field("类目名称",input("name",old?.name,'required maxlength="80"')),
    (d,send)=>saveAndRender(send,{action:"category",name:d.name,kind,...(parent?{parent_id:parent.id}:{}),...(old?{id:old.id}:{})}));
}
const assetTabs={accounts:"资金账户",asset:"其他资产",invest:"投资",borrow:"借入",lend:"借出"};
const eventLabels={origin:"初始本金",repay:"本金与利息",buy:"投入",redeem:"赎回",valuation:"更新市值",yield:"到账收益"};
function assetURL(owner,tab) { return "assets"+filterRoute({owner,tab}); }
function viewAssets(q,sub,id) { return AssetUI.view(q,sub,id); }
function tabLink(url,label,current) {
  return '<a class="button'+(current?' active':'')+'" '+(current?'aria-current="true" ':'')+'href="#'+h(url)+'">'+h(label)+'</a>';
}
function viewPosition(p) {
  const title=heading(p.name,owners[p.owner]+" · "+assetTabs[p.kind],link(assetURL(p.owner,p.kind),"返回列表")+btn("posedit:"+p.id,"编辑"));
  if (p.kind==="asset") return title+positionMeta(p)+AssetUI.physical(p);
  const invest=p.kind==="invest";
  const amounts=invest?metrics(p,{cost:"剩余成本",market:"当前市值",unrealized:"浮动盈亏",realized:"已实现盈亏",earnings:"到账收益"}):
    metrics(p,{cost:"剩余本金",earnings:p.kind==="borrow"?"累计已付利息":"累计已收利息"});
  const buttons=invest?["buy","redeem","valuation","yield"].map(type=>btn("event:"+p.id+":"+type,eventLabels[type])).join(""):
    btn("event:"+p.id+":repay",p.kind==="borrow"?"记还款":"记收款",true);
  const header='<tr><th>日期</th><th>类型</th><th>金额 / 本金</th><th>到账 / 利息</th><th>账本与账户</th><th>备注</th><th>操作</th></tr>';
  const history=p.events.slice().reverse().map(e=>'<tr><td>'+h(e.day)+'</td><td>'+h(eventLabels[e.kind])+'</td><td>'+money(e.principal)+'</td><td>'+
    (["repay","redeem"].includes(e.kind)?money(e.extra):"")+'</td><td>'+h(by(state.books,e.book_id)?.name)+'<br><small>'+h(accountLabel(by(state.accounts,e.account_id)))+
    '</small></td><td>'+h(e.note)+'</td><td>'+btn("eventedit:"+p.id+":"+e.id,"编辑")+
    (e.kind==="origin"?"":btn("eventdel:"+e.id,"删除"))+'</td></tr>').join("");
  return title+positionMeta(p)+'<div class="panel">'+amounts+(p.due?'<p>到期日 '+h(p.due)+'</p>':"")+'</div><div class="row">'+buttons+'</div>'+
    (history?'<div class="panel"><table class="table"><thead>'+header+'</thead><tbody>'+history+'</tbody></table></div>':empty("暂无业务记录"));
}
function positionMeta(p) {
  return '<div class="panel"><p>'+h(state.asset_options.positions[p.kind][p.subtype])+' · '+h(p.institution||"未填写机构 / 对方")+'</p><p>'+h(p.note)+'</p></div>';
}
function creditPayment(account) {
  const sources=state.accounts.filter(a=>a.id!==account.id);
  if(!sources.length) {flash("请先添加用于还款的资金账户");return;}
  if(!state.books.some(b=>!b.archived)) {bookForm();return;}
  openForm("记信用卡还款",field("日期",input("day",today(),'required type="date"'))+
    field("账本",select("book_id",state.books.filter(b=>!b.archived).map(b=>[b.id,b.name])))+
    field("付款账户",select("account_id",sources.map(a=>[a.id,accountLabel(a)])))+
    field("还款金额（元）",moneyInput("amount",Math.max(0,-account.balance)))+
    '<p>还款按账户转账记录，减少现金与信用卡欠款。</p>',
    (d,send)=>saveAndRender(send,{...d,action:"bill",kind:"transfer",book_id:Number(d.book_id),account_id:Number(d.account_id),
      to_account_id:account.id,amount:parseMoney(d.amount),note:"信用卡还款 · "+account.name}));
}
function fundingFields(old={}) {
  const books=state.books.filter(b=>!b.archived || b.id===old.book_id);
  const choices=state.accounts.map(a=>[a.id,accountLabel(a)]);
  return field("账本",select("book_id",[["","请选择"],...books.map(b=>[b.id,b.name])],old.book_id))+
    field("资金账户",select("account_id",[["","请选择"],...choices],old.account_id));
}
function positionForm(owner,kind,old) { return AssetUI.positionForm(owner,kind,old); }
function eventForm(p,kind,old) {
  const cash=kind!=="valuation"&&!old?.opening_only, extra=kind==="redeem"||kind==="repay";
  const label={repay:"本次归还或收回本金",redeem:"本次收回成本",valuation:"当前市值",origin:"初始本金",buy:"投入金额",yield:"到账收益"}[kind];
  openForm((old?"编辑":"登记")+eventLabels[kind],field("日期",input("day",old?.day||today(),'type="date" required'))+
    field(label+"（元）",moneyInput("principal",old?.principal ?? (kind==="repay"?0:undefined)))+
    (extra?field((kind==="repay"?"利息":"实际到账金额")+"（元）",moneyInput("extra",old?.extra ?? (kind==="repay"?0:undefined))):"")+
    (cash?fundingFields(old):"")+field("备注",input("note",old?.note,"maxlength=500")),
    (d,send)=>saveAndRender(send,{...d,action:"finance_event",position_id:p.id,event_kind:kind,...(old?{id:old.id}:{}),
      principal:parseMoney(d.principal,false,kind==="valuation"||kind==="repay"),extra:extra?parseMoney(d.extra,false,true):0,
      book_id:Number(d.book_id),account_id:Number(d.account_id)}));
}
function viewSettings() {
  return heading("数据与设置","本地数据和完整备份")+
    '<div class="panel"><h2>本地数据文件</h2><code>'+h(session.database)+'</code><p>最近成功备份 '+h(state.last_backup || "暂无")+'</p></div>'+
    '<div class="grid"><section class="panel"><h2>创建备份</h2><p>将所有账本、流水和资产记录保存到指定目录。</p>'+
    btn("backup","创建备份",true)+'</section><section class="panel"><h2>恢复备份</h2><p>选择文件后先预览。确认恢复时会替换当前账本。</p>'+
    btn("restore","选择备份文件")+'</section></div>';
}
function fileForm(restoring) {
  const title=restoring?"选择备份文件":"选择备份目录";
  const form=openForm(title,field(restoring?"备份文件完整路径":"备份目录完整路径",input("path","","required"))+
    btn("unused",title+"…"),async d=>{
      if(restoring) {
        const preview=await api("/api/files",{action:"preview",path:d.path});
        setTimeout(()=>confirmRestore(d.path,preview),0);
      } else {
        const result=await api("/api/files",{action:"backup",path:d.path});
        await refresh();render();
        setTimeout(()=>flash("备份已保存至 "+result.path),0);
      }
    },restoring?"预览备份":"保存备份");
  const browse=form.querySelector('[data-act="unused"]');
  browse.onclick=async()=>{
    if (busy) return;
    busy=true;
    browse.disabled=true;
    const submit=form.querySelector('[type="submit"]');
    submit.disabled=true;
    const error=form.querySelector(".error");
    error.textContent="";
    try {
      const result=await api("/api/files",{action:restoring?"browse_file":"browse_folder"});
      if(result.path) form.elements.path.value=result.path;
    } catch(failure) {error.textContent=failure.message;}
    finally{busy=false;browse.disabled=false;submit.disabled=false;}
  };
}
function confirmRestore(path,preview) {
  openForm("确认替换当前账本",
    '<p>备份时间 '+h(preview.time || "未记录")+'</p><p>账本 '+preview.books+' 个 · 账单 '+preview.bills+' 笔</p>'+
    '<p>确认后先备份当前数据，再用所选文件替换。也可以取消。</p>',
    async()=>{
      await api("/api/files",{action:"restore",path,fingerprint:preview.fingerprint});
      session=await api("/api/session");
      await refresh();
      location.hash="home";
      render();
      setTimeout(()=>flash("已恢复备份"),0);
    },"确认恢复");
}
function render() {
  if (!state) return;
  try {
  const {parts:[key,id,month,day],q}=route();
  document.querySelectorAll("nav a").forEach(link=>link.setAttribute("aria-current", link.hash==="#"+(key==="book"?"home":key)?"page":"false"));
  const book=by(state.books,id);
  if(key==="book" && book) {
    const selected=monthOf(month);
    const list=state.bills.filter(b=>b.book_id===book.id && b.day===day);
    page.innerHTML=day ? heading(day,book.name,link("book/"+book.id+"/"+selected,"返回月历")+btn("quick","记一笔",true))+
      '<div class="panel">'+metrics(summarize(list))+'</div>'+(list.length?billTable(list):empty("当天暂无账单",btn("quick","记一笔",true))) : viewCalendar(book,selected);
    return;
  }
  const views={home:viewHome,bills:viewBills,stats:viewStats,categories:viewCategories,
    assets:viewAssets,
    settings:viewSettings};
  page.innerHTML=Object.hasOwn(views,key) ? views[key](q,id,month) : viewHome();
  AssetUI.mount();
  } catch(error) {
    page.innerHTML=heading("页面加载失败")+'<div class="panel"><p>'+h(error.message)+'</p><p>请关闭旧的应用窗口，重新运行 start.cmd，并使用新打开的页面。</p></div>';
  }
}
function quick() {
  const {parts:[key,id,,day],q}=route();
  billForm(null,{book:key==="book"?id:q.get("book"),day});
}
actions={
  newbook:()=>bookForm(), rename:id=>bookForm(by(state.books,id)), quick, newaccount:owner=>accountForm(owner),
  edit:id=>billForm(by(state.bills,id)),
  addasset:owner=>AssetUI.add(owner),
  accountedit:id=>accountForm(by(state.accounts,id).owner,by(state.accounts,id)),
  creditpay:id=>creditPayment(by(state.accounts,id)),
  value:id=>AssetUI.valueForm(by(state.positions,id)),
  valueedit:(id,valueID)=>AssetUI.valueForm(by(state.positions,id),by(state.asset_values,valueID)),
  valuedel:id=>ask("删除估值","删除后将按照剩余估值记录重新计算。",
    send=>saveAndRender(send,{action:"delete_value",id:Number(id)}),"删除"),
  catnew:kind=>categoryForm(kind),
  catchild:id=>{const parent=by(state.categories,id);categoryForm(parent.kind,parent);},
  catrename:id=>{const old=by(state.categories,id);categoryForm(old.kind,null,old);},
  cattoggle:id=>{
    const c=by(state.categories,id), label=c.enabled?"停用":"启用";
    ask(label+"类目",label+"「"+c.name+"」？历史账单仍可查看。",
      send=>saveAndRender(send,{action:"category_enabled",id:c.id,enabled:!c.enabled}),label);
  },
  backup:()=>fileForm(false), restore:()=>fileForm(true),
  newpos:(owner,kind)=>positionForm(owner,kind),
  posedit:id=>{const p=by(state.positions,id);positionForm(p.owner,p.kind,p);},
  event:(id,kind)=>eventForm(by(state.positions,id),kind),
  eventedit:(id,eventID)=>{const p=by(state.positions,id), e=by(p.events,eventID);eventForm(p,e.kind,e);},
  eventdel:id=>ask("删除业务记录","删除后将重新计算该笔业务的余额、资产与收支。",
    send=>saveAndRender(send,{action:"delete_event",id:Number(id)}),"删除"),
  archive:id=>{
    const book=by(state.books,id);
    const label=book.archived?"恢复":"归档";
    ask(label+"账本",label+"「"+book.name+"」？历史数据会继续保留。",
      send=>saveAndRender(send,{action:"archive",id:Number(id),archived:!book.archived}),label);
  },
  del:id=>{
    const b=by(state.bills,id), names=[b.account_id,b.to_account_id].filter(Boolean).map(i=>accountLabel(by(state.accounts,i)));
    ask("删除账单",b.day+" · "+money(b.amount)+" · "+names.join(" → ")+"。删除后会更新账户余额和统计。",
      send=>saveAndRender(send,{action:"delete_bill",id:Number(id)}),"删除");
  }
};
page.onclick=event=>{
  const button=event.target.closest("[data-act]");
  if(!button) return;
  const [key,...args]=button.dataset.act.split(":");
  actions[key]?.(...args);
};
page.onsubmit=event=>{
  const routes={filters:"bills",statsfilter:"stats",assetchart:"assets"};
  const path=routes[event.target.id];
  if (!path) return;
  event.preventDefault();
  const data=Object.fromEntries(new FormData(event.target));
  if (data.from && data.to && data.from>data.to) {flash("结束日期不能早于开始日期");return;}
  location.hash=path+filterRoute(data);
};
document.querySelector("#quick").onclick=()=>{if(state) quick();};
addEventListener("hashchange",render);
(async()=>{try{
  if(typeof AssetUI === "undefined") throw new Error("资产组件未加载，请关闭旧服务后重新运行 start.cmd，并使用新打开的页面");
  session=await api("/api/session");await refresh();render();
}catch(error){page.textContent="无法读取本地数据："+error.message;}})();
