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
const monthOf = value => /^\d{4}-(0[1-9]|1[0-2])$/.test(value || "") && !value.startsWith("0000") ? value : thisMonth();
const btn = (id,label,primary=false) => '<button type="button" data-act="' + h(id) + '"' + (primary?' class="primary"':'') + '>' + h(label) + '</button>';
const link = (href,label) => '<a class="button" href="#' + h(href) + '">' + h(label) + '</a>';
const options = (values,selected) => values.map(([key,label]) => '<option value="' + h(key) + '"' + (String(key)===String(selected)?" selected":"") + '>' + h(label) + '</option>').join("");
const iconChoices = () => Object.entries(state.category_icons).map(([key,icon])=>[key,icon]);
const field = (label,content) => '<label>' + h(label) + content + '</label>';
const select = (key,values,selected) => '<select name="' + key + '" required>' + options(values,selected) + '</select>';
const input = (key,value="",attributes="") => {
  const markup='<input name="'+key+'" value="'+h(value)+'" '+attributes+'>';
  if(!/type="(?:date|month)"/.test(attributes)&&!(key==="year"&&attributes.includes('type="number"')))return markup;
  return '<span class="date-field">'+markup+'<button type="button" data-date-picker aria-label="打开日期选择" aria-haspopup="dialog" aria-expanded="false">▦</button></span>';
};
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
    '<span><small>'+h(({income:"↗ ",expense:"↘ ",net:"◈ ",assets:"◈ ",debts:"↘ "})[key]||"")+h(label)+'</small><strong class="'+h(key)+'">'+money(stat[key])+'</strong></span>').join("") + '</div>';
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
  openForm(book?"编辑账本":"新建账本",field("账本名称",input("name",book?.name,'required maxlength="80"'))+
    field("账本图标",select("icon",[["default","📒"],...iconChoices()],state.book_icons[String(book?.id)]||"default"))+iconUpload(book),
    async(d,send)=>saveAndRender(send,{action:"book",...(book?{id:book.id}:{}),name:d.name,icon:d.icon,...await iconData(d)}));
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
    field("账本",select("book_id",books.map(b=>[b.id,b.name]),bill.book_id||context.book||state.current_book))+
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
      fields.innerHTML+='<div class="category-picker" role="group" aria-label="选择收支类目">'+list.map(c=>
        '<button type="button" data-category="'+c.id+'" aria-pressed="false">'+categoryIcon(c)+'<span>'+h(categoryLabel(c))+'</span></button>').join("")+'</div>';
      const selector=fields.querySelector('[name="category_id"]');
      const highlight=()=>fields.querySelectorAll('[data-category]').forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.category===selector.value)));
      fields.querySelectorAll('[data-category]').forEach(b=>b.onclick=()=>{selector.value=b.dataset.category;highlight();});
      selector.onchange=highlight;highlight();

    }
  };
  form.elements.kind.onchange=populate;
  populate();
}
function viewHome() {
  const current=state.books.filter(b=>!b.archived), archived=state.books.filter(b=>b.archived);
  const card=b=>'<article class="panel book-card"><h2><span class="book-symbol" aria-hidden="true">'+categoryIcon({icon:state.book_icons[b.id],icon_image:b.icon_image})+'</span><a href="#book/'+b.id+'/'+thisMonth()+'">'+h(b.name)+'</a></h2>'+
    metrics(summarize(state.bills.filter(row=>row.book_id===b.id && row.day.startsWith(thisMonth()))))+
    '<div class="toolbar">'+link("book/"+b.id+"/"+thisMonth(),"打开月历")+link("inventory?book="+b.id,state.inventories.some(r=>r.book_id===b.id)?"查看资产盘点":"初始化家庭资产")+
    '<details><summary>账本操作</summary>'+btn("rename:"+b.id,"编辑账本")+btn("archive:"+b.id,b.archived?"恢复":"归档")+'</details></div></article>';
  return heading("首页总览",thisMonth()+" · 账本收支",btn("newbook","新建账本",true))+
    '<section class="panel current-book">'+field("当前操作账本",select("current_book",current.map(b=>[b.id,(state.category_icons[state.book_icons[b.id]]||"📒")+" "+b.name]),state.current_book||current[0]?.id))+'<p class="muted">点击“记一笔”时默认使用此账本</p></section>'+
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
  const list=state.bills.filter(b=>b.book_id===book.id && b.day.startsWith(month));
  const base="book/"+book.id+"/";
  const grid=DatePicker.monthGrid(month,(value,i)=>calendarCell(value,base+month+'/'+value,summarize(list.filter(b=>b.day===value)),false,i));
  return heading(book.name,month+" 月历",link("home","返回首页"))+
    '<div class="panel"><div class="row">'+link(base+monthShift(month,-1),"上月")+
    field("跳转月份",input("calendar_month",month,'type="month" data-calendar-month="book"'))+
    link(base+monthShift(month,1),"下月")+'</div>'+metrics(summarize(list))+'</div><div class="calendar">'+grid+'</div>';
}
function calendarCell(day,path,stat,selected,n){
  return '<a class="cell'+(day===today()?' today':'')+(selected?' selected-day':'')+'" href="#'+h(path)+'">'+
    '<strong class="calendar-date">'+n+'</strong>'+
    (stat.income?'<small class="income">+'+money(stat.income)+'</small>':"")+
    (stat.expense?'<small class="expense">-'+money(stat.expense)+'</small>':"")+'</a>';
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
    return group+'<tr><td>'+categoryIcon(by(state.categories,b.category_id))+h(categoryLabel(by(state.categories,b.category_id)) || kinds[b.kind])+'<br><small>'+h(kinds[b.kind])+'</small></td><td>'+h(by(state.books,b.book_id)?.name)+'<br><small>'+h(description)+'</small></td>'+
      '<td class="'+h(b.kind)+'">'+money(b.amount)+'</td><td>'+h(b.note)+'</td><td>'+controls+'</td></tr>';
  }).join("");
  return '<div class="panel"><table class="table"><thead><tr><th>类目 / 类型</th><th>账本与账户</th><th>金额</th><th>备注</th><th>操作</th></tr></thead><tbody>'+body+'</tbody></table></div>';
}
function filterRoute(values) {
  const params=new URLSearchParams();
  for (const [key,value] of Object.entries(values)) if(value) params.set(key,value);
  return params.size ? "?"+params.toString() : "";
}
function baseBills(q) {
  const filters=Object.fromEntries(q);
  const all=(key,label,choices)=>field(label,select(key,[["", "全部"],...choices],q.get(key)||"").replace(" required",""));
  const form='<form id="filters" class="filter-grid">'+field("月份",input("month",q.get("month")||thisMonth(),'type="month"'))+input("view",q.get("view")||"list",'type="hidden"')+
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
function legacyStats(q) {
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
    '<div><strong>'+m+'</strong><div class="trend-module income" tabindex="0"><span>入 '+money(s.income)+'</span><progress class="stat-bar income-bar" max="'+ceiling+'" value="'+s.income+'" aria-label="'+m+' 收入"></progress></div>'+
    '<div class="trend-module expense" tabindex="0"><span>出 '+money(s.expense)+'</span><progress class="stat-bar expense-bar" max="'+ceiling+'" value="'+s.expense+'" aria-label="'+m+' 支出"></progress></div></div>').join("")+'</div></div>';
  const ranking=rank.map(([id,value],i)=>'<li><a href="#bills'+h(filterRoute({book,from:month+"-01",to:localDate(last),kind:"expense",category:id}))+'">'+
    h(categoryLabel(by(state.categories,id)) || "其他支出")+'</a><strong>'+money(value)+'</strong><progress class="stat-bar rank-bar" max="'+rank[0][1]+'" value="'+value+'" aria-label="排行 '+(i+1)+'"></progress></li>').join("");
  return heading("统计分析",month+" · 月度收支")+'<div class="panel">'+statsForm+metrics(now)+'</div>'+
    '<div class="panel"><h2>上月对比 · '+previous+'</h2>'+metrics(before)+
    '<p class="muted">本月与上月差额</p>'+metrics(comparison)+'</div>'+
    monthly+'<div class="panel"><h2>支出类目排行</h2>'+(ranking?'<ol class="ranking">'+ranking+'</ol>':'<p class="muted">本月暂无支出</p>')+'</div>';
}
function categoryIcon(item) {
  const image=item?.icon_image;
  const visual=image&&/^[A-Za-z0-9+/]+={0,2}$/.test(image)?
    '<img src="data:image/png;base64,'+h(image)+'" alt="">':h(state.category_icons?.[item?.icon]||"🌿");
  return '<span class="category-icon" aria-hidden="true">'+visual+'</span>';
}
function iconUpload(item){
  return field("上传自定义图标",'<input name="icon_file" type="file" accept="image/png,image/jpeg,image/webp">')+
    '<small>PNG、JPG 或 WebP，最大 1 MB</small>'+
    (item?.icon_image?'<div class="row">'+categoryIcon(item)+
      '<label class="checkline"><input type="checkbox" name="remove_icon">恢复为预设图标</label></div>':"");
}
async function iconData(data){
  const file=data.icon_file;
  if(file?.size){
    if(file.size>1024*1024)throw new Error("请选择小于 1 MB 的图标图片");
    const content=await new Promise((resolve,reject)=>{
      const reader=new FileReader();
      reader.onload=()=>resolve(String(reader.result).split(",")[1]);
      reader.onerror=()=>reject(new Error("无法读取图标图片"));
      reader.readAsDataURL(file);
    });
    return {icon_image:content};
  }
  return data.remove_icon?{icon_image:""}:{};
}
function viewCategories(q) {
  const kind=q.get("kind")==="income"?"income":"expense";
  const list=state.categories.filter(c=>c.kind===kind);
  const controls=c=>btn("catrename:"+c.id,"改名")+btn("cattoggle:"+c.id,c.enabled?"停用":"启用");
  const line=c=>'<div class="category-line"><span>'+categoryIcon(c)+h(c.name)+'</span><div class="toolbar">'+controls(c)+'</div></div>';
  const group=c=>{
    const children=list.filter(k=>k.parent_id===c.id), active=children.filter(k=>k.enabled), off=children.filter(k=>!k.enabled);
    return '<details class="panel category-card" open><summary>'+categoryIcon(c)+h(c.name)+(c.enabled?"":" · 已停用")+'</summary><div class="toolbar">'+controls(c)+
      (c.enabled?btn("catchild:"+c.id,"添加二级类目"):"")+'</div>'+active.map(line).join("")+
      (off.length?'<details><summary>已停用的二级类目</summary>'+off.map(line).join("")+'</details>':"")+'</details>';
  };
  const roots=list.filter(c=>!c.parent_id), off=roots.filter(c=>!c.enabled);
  return heading("收支类目","管理两级分类",btn("catnew:"+kind,"新建一级类目",true))+
    '<div class="row">'+link("categories?kind=income","收入")+link("categories?kind=expense","支出")+'</div>'+
    '<div class="category-grid">'+roots.filter(c=>c.enabled).map(group).join("")+'</div>'+(off.length?'<details class="panel"><summary>已停用的一级类目</summary>'+off.map(group).join("")+'</details>':"");
}
function categoryForm(kind,parent,old) {
  openForm(old?"修改类目名称":parent?"在「"+parent.name+"」下添加类目":"新建"+kinds[kind]+"类目",
    field("类目名称",input("name",old?.name,'required maxlength="80"'))+
      field("图标",select("icon",Object.entries(state.category_icons).map(([key,symbol])=>[key,symbol]),old?.icon||parent?.icon||"other"))+iconUpload(old),
    async(d,send)=>saveAndRender(send,{action:"category",name:d.name,icon:d.icon,kind,...await iconData(d),...(parent?{parent_id:parent.id}:{}),...(old?{id:old.id}:{})}));
}
const assetTabs={accounts:"资金账户",asset:"资产",invest:"投资",borrow:"借入",lend:"借出"};
const eventLabels={origin:"初始本金",repay:"本金与利息",buy:"投入",redeem:"赎回",valuation:"更新市值",yield:"到账收益"};
function assetURL(owner,tab) { return "assets"+filterRoute({owner,tab}); }
function viewAssets(q,sub,id) {
  if(q.has("group")&&!sub){
    const owner=q.get("owner")==="personal"?"personal":"family",metric=q.get("metric")==="debts"?"debts":"assets";
    const entries=state.portfolio[owner].current.entries.filter(e=>e.group===q.get("group")&&e[metric]>0);
    return heading(q.get("group")+" · 分类明细",owners[owner],link(detailReturn(assetURL(owner,"charts")),"返回图表"))+
      '<section class="panel">'+entries.map(e=>'<a class="asset-row" href="#assets/'+(e.kind==="account"?"account":"detail")+'/'+e.id+'?return='+encodeURIComponent(location.hash.slice(1))+'"><strong>'+h(e.name)+'</strong><strong>'+money(e[metric])+'</strong></a>').join("")+'</section>';
  }
  return '<div class="asset-module">'+AssetUI.view(q,sub,id)+'</div>';
}
function tabLink(url,label,current) {
  return '<a class="button'+(current?' active':'')+'" '+(current?'aria-current="true" ':'')+'href="#'+h(url)+'">'+h(label)+'</a>';
}
function viewPosition(p) {
  const title=heading(p.name,owners[p.owner]+" · "+assetTabs[p.kind],link(detailReturn(assetURL(p.owner,p.kind)),"返回列表")+btn("posedit:"+p.id,"编辑"));
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
  return title+positionMeta(p)+(!invest?WorkspaceUI.paymentSchedule(p):"")+'<div class="panel">'+amounts+(p.due?'<p>到期日 '+h(p.due)+'</p>':"")+'</div><div class="row">'+buttons+'</div>'+
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
    '<div class="grid settings-cards"><section class="panel"><h2>创建备份</h2><p>将所有账本、流水和资产记录保存到指定目录。</p>'+
    '<div class="toolbar">'+btn("backup","创建完整 .db 备份",true)+btn("exportdata","选择范围与格式导出")+'</div></section><section class="panel"><h2>导入 / 恢复</h2><p>支持 .db、.xlsx、.xls。选择文件后先预览，确认后替换当前全部数据，并先自动备份当前版本。</p>'+
    '<div class="toolbar">'+btn("restore","选择备份文件")+'</div></section></div>';
}
function fileForm(restoring) {
  const title=restoring?"选择备份文件":"选择备份目录";
  const form=openForm(title,(restoring?field("选择本机文件（.db / .xls / .xlsx）",'<input id="import-upload" type="file" accept=".db,.xls,.xlsx">'):"")+field(restoring?"备份文件完整路径":"备份目录完整路径",input("path","",restoring?"":"required"))+
    btn("unused",title+"…"),async d=>{
      if(restoring) {
        const file=form.querySelector("#import-upload").files[0];
        let preview,path=d.path;
        if(file){
          if(file.size>10*1024*1024)throw new Error("超过10MB，请通过完整路径导入");
          const content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(",")[1]);reader.onerror=()=>reject(new Error("文件读取失败"));reader.readAsDataURL(file);});
          preview=await api("/api/files",{action:"import_upload",name:file.name,content});path=preview.path;
        }else{
          if(!path.trim())throw new Error("请选择文件或填写完整路径");
          preview=await api("/api/files",{action:"import_preview",path});
        }
        setTimeout(()=>confirmRestore(path,preview),0);
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
      await api("/api/files",{action:"import_restore",path,fingerprint:preview.fingerprint});
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
  const views={home:viewHome,bills:WorkspaceUI.bills,stats:WorkspaceUI.stats,categories:viewCategories,
    assets:viewAssets,inventory:InventoryUI.view,
    settings:viewSettings};
  page.innerHTML=Object.hasOwn(views,key) ? views[key](q,id,month) : viewHome();
  AssetUI.mount();InventoryUI.mount();
  const currentBook=page.querySelector('[name="current_book"]');
  if(currentBook)currentBook.onchange=async()=>{
    try{await api("/api/action",{action:"current_book",book_id:Number(currentBook.value),request_id:crypto.randomUUID()});await refresh();render();}
    catch(e){flash(e.message);}
  };
  const billBook=page.querySelector('#bill-book-select');
  if(billBook)billBook.onchange=()=>{const q=route().q;q.set("book",billBook.value);location.hash="bills?"+q;};
  const monthPicker=page.querySelector('#filters [name=month]');
  if(monthPicker)monthPicker.onchange=()=>{
    const form=monthPicker.form,month=monthOf(monthPicker.value);
    form.elements.from.value=month+"-01";
    form.elements.to.value=localDate(new Date(Number(month.slice(0,4)),Number(month.slice(5,7)),0));
  };
  } catch(error) {
    page.innerHTML=heading("页面加载失败")+'<div class="panel"><p>'+h(error.message)+'</p><p>请关闭旧的应用窗口，重新运行 start.cmd，并使用新打开的页面。</p></div>';
  }
}
function quick() {
  const {parts:[key,id,,day],q}=route();
  billForm(null,{book:key==="book"?id:(q.get("book")||state.current_book),day});
}
actions={
  imageimport:(owner,kind)=>ImageImportUI.start(owner,kind),
  exportdata:()=>WorkspaceUI.exchange(),budget:(book,month)=>WorkspaceUI.budgetForm(book,month),loanplan:id=>WorkspaceUI.loanForm(id),
  newbook:()=>bookForm(), rename:id=>bookForm(by(state.books,id)), quick, newaccount:owner=>accountForm(owner),
  edit:id=>billForm(by(state.bills,id)),
  assetimage:owner=>ImageImportUI.startAsset(owner),
  deleteloan:(kind,id)=>WorkspaceUI.deleteLoan(kind,id),
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
page.addEventListener("change",event=>{
  const control=event.target;
  if(control.matches("[data-paid-id]")) WorkspaceUI.markPaid(control);
  if(!control.dataset.calendarMonth||!control.value||!control.validity.valid)return;
  const {parts,q}=route();
  if(control.dataset.calendarMonth==="book"){
    location.hash="book/"+parts[1]+"/"+control.value;
    return;
  }
  q.set("month",control.value);
  for(const key of ["day","from","to"])q.delete(key);
  location.hash="bills?"+q;
});
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

function detailReturn(fallback){const back=route().q.get("return");return back&&/^(assets[?]|stats[?])/.test(back)?back:fallback;}
