"use strict";
const AssetUI = (() => {
  const chartNames={assets:"资产",debts:"负债",net:"净资产"};
  const charts=new Map();
  let loading="";
  function clear() { charts.clear(); }
  function accountForm(owner="personal",old,type="bank") {
    const form=openForm(old?"配置账户":"新建资金账户",
      field("账户名称",input("name",old?.name,"required maxlength=80"))+
      field("归属",select("owner",Object.entries(owners),old?.owner||owner))+
      field("账户类型",select("account_type",Object.entries(state.asset_options.accounts),old?.account_type||type))+
      field("机构 / 平台",input("institution",old?.institution,"maxlength=120 placeholder=如：招商银行、支付宝"))+
      field("期初日期",input("opening_day",old?.opening_day||today(),'type="date" required'))+
      field("期初余额（元，欠款填负数）",moneyInput("opening",old?.opening||0))+
      '<div id="credit-fields">'+field("信用额度（元）",moneyInput("credit_limit",old?.credit_limit||0))+
      field("每月账单日（选填）",input("bill_day",old?.bill_day,'type="number" min="1" max="31"'))+
      field("每月还款日（选填）",input("repay_day",old?.repay_day,'type="number" min="1" max="31"'))+'</div>'+
      '<small>期初余额加上全部流水得到当前余额。修改期初配置会重新计算历史。投资账户资金只填未投资的现金，已购持仓在投资中登记。</small>'+
      field("备注",input("note",old?.note,"maxlength=500")),
      (d,send)=>saveAndRender(send,{...d,action:"account",...(old?{id:old.id}:{}),opening:parseMoney(d.opening,true,true),
        credit_limit:d.account_type==="credit"?parseMoney(d.credit_limit,false,true):0,
        bill_day:d.bill_day?Number(d.bill_day):null,repay_day:d.repay_day?Number(d.repay_day):null}));
    const update=()=>{const box=form.querySelector("#credit-fields"), credit=form.elements.account_type.value==="credit";
      box.hidden=!credit;box.querySelectorAll("input").forEach(el=>el.disabled=!credit);};
    form.elements.account_type.onchange=update;update();
  }
  function add(owner) {
    const choices=[...Object.entries(state.asset_options.accounts).map(([key,label])=>["account/"+key,label]),
      ["invest/other","投资持仓 · 股票 / 基金 / 理财"],["borrow/loan","负债 · 贷款 / 应付"],
      ["lend/receivable","债权 · 应收 / 借出"],["asset/custom","自定义资产 · 房产 / 车辆"]];
    openForm("添加资产或账户",field("归属",select("owner",Object.entries(owners),owner))+
      field("类型",select("choice",choices,"account/bank")),d=>{
        const [kind,type]=d.choice.split("/");
        setTimeout(()=>kind==="account"?accountForm(d.owner,null,type):positionForm(d.owner,kind,null,type),0);
      },"下一步");
  }
  function positionForm(owner,kind,old,subtype) {
    const loan=["borrow","lend"].includes(kind), init=loan&&!old;
    const form=openForm((old?"编辑":"新增")+assetTabs[kind],
      field("名称",input("name",old?.name,"required maxlength=80"))+
      field("归属",select("owner",Object.entries(owners),owner))+
      field("资产分类",select("subtype",Object.entries(state.asset_options.positions[kind]),old?.subtype||subtype))+
      field("机构 / 对方",input("institution",old?.institution,"maxlength=120"))+
      (kind==="asset"&&!old?field("初始估值（元）",moneyInput("value"))+field("估值日期",input("day",today(),'type="date" required')):"")+
      (kind==="invest"&&!old?field("已有持仓成本（元，无持仓填 0）",moneyInput("initial_cost",0))+
        field("已有持仓市值（元，无持仓填 0）",moneyInput("initial_market",0))+
        field("持仓登记日期",input("day",today(),'type="date" required'))+'<small>已有持仓只登记资产，不扣减资金账户；之后的新投入在详情中记录。</small>':"")+
      (loan?field("到期日",input("due",old?.due,'type="date"')):"")+
      (init?field("登记方式",select("opening_only",[["1","已有债务 / 应收，仅登记余额"],["0","本次新借入 / 借出，同步资金"]],"1"))+
        field("初始本金（元）",moneyInput("principal"))+field("业务日期",input("day",today(),'type="date" required'))+
        '<div id="loan-funding">'+fundingFields()+'</div>':"")+
      field("备注",input("note",old?.note,"maxlength=500")),async(d,send)=>{
        const result=await send({...d,action:"position",kind,...(old?{id:old.id}:{}),
          ...(kind==="asset"&&!old?{value:parseMoney(d.value,false,true)}:{}),
          ...(kind==="invest"&&!old?{initial_cost:parseMoney(d.initial_cost,false,true),initial_market:parseMoney(d.initial_market,false,true)}:{}),
          ...(init?{opening_only:d.opening_only==="1",principal:parseMoney(d.principal),book_id:Number(d.book_id),account_id:Number(d.account_id)}:{})});
        await refresh();location.hash="assets/detail/"+result.id;render();
      });
    if(init) {
      const update=()=>{const box=form.querySelector("#loan-funding"), only=form.elements.opening_only.value==="1";
        box.hidden=only;box.querySelectorAll("select").forEach(el=>el.disabled=only);};
      form.elements.opening_only.onchange=update;update();
    }
  }
  function valueForm(p,old) {
    openForm(old?"编辑估值":"更新资产估值",field("估值日期",input("day",old?.day||today(),'type="date" required'))+
      field("估值（元）",moneyInput("value",old?.value))+field("备注",input("note",old?.note,"maxlength=500")),
      (d,send)=>saveAndRender(send,{...d,action:"asset_value",position_id:p.id,...(old?{id:old.id}:{}),value:parseMoney(d.value,false,true)}));
  }
  function physical(p) {
    const values=state.asset_values.filter(v=>v.position_id===p.id);
    return '<div class="panel">'+metrics({value:p.value},{value:"最近登记估值"})+'</div><div class="row">'+btn("value:"+p.id,"更新估值",true)+'</div>'+
      '<div class="panel"><h2>估值历史</h2>'+(values.length?'<table class="table"><thead><tr><th>日期</th><th>估值</th><th>备注</th><th>操作</th></tr></thead><tbody>'+values.map(v=>
        '<tr><td>'+h(v.day)+'</td><td>'+money(v.value)+'</td><td>'+h(v.note)+'</td><td>'+btn("valueedit:"+p.id+":"+v.id,"编辑")+btn("valuedel:"+v.id,"删除")+'</td></tr>').join("")+'</tbody></table>':'<p>暂无估值记录</p>')+'</div>';
  }
  function ratio(value) {return value==null?"—":(value*100).toFixed(1)+"%";}
  function summary(owner,small=false) {
    const current=state.portfolio[owner].current;
    const entries=current.entries.filter(e=>e.assets||e.debts);
    const groups=new Map();
    for(const entry of entries) {
      if(!groups.has(entry.group)) groups.set(entry.group,{assets:0,debts:0});
      const group=groups.get(entry.group);group.assets+=entry.assets;group.debts+=entry.debts;
    }
    return '<section class="panel wealth-summary" data-owner="'+owner+'"><div class="heading"><h2>'+owners[owner]+'资产概况</h2>'+link(assetURL(owner,"overview"),"查看详情")+'</div>'+
      metrics(current,{net:"净资产",assets:"总资产",debts:"总负债"})+'<p>资产负债率 '+ratio(current.ratio)+'</p>'+
      (small?(groups.size?'<div class="home-allocation">'+[...groups].map(([label,value])=>'<div><span>'+h(label)+'</span><span>'+
        (value.assets?'资产 '+money(value.assets):'负债 '+money(value.debts))+'</span></div>').join("")+'</div>':'<p class="muted">尚未添加资产与账户</p>'):"")+'</section>';
  }
  function home() {return '<div class="grid home-wealth">'+summary("family",true)+summary("personal",true)+'</div>';}
  function accountView(a) {
    const debt=Math.max(0,-a.balance), available=Math.max(0,a.credit_limit+a.balance);
    return heading(a.name,owners[a.owner]+" · "+state.asset_options.accounts[a.account_type],link(assetURL(a.owner,"accounts"),"返回资金账户")+btn("accountedit:"+a.id,"配置账户"))+
      '<div class="panel">'+metrics({opening:a.opening,balance:a.balance},{opening:"期初余额",balance:"当前余额"})+
      '<p>期初日期 '+h(a.opening_day)+' · '+h(a.institution||"未填写机构")+'</p><p>'+h(a.note)+'</p>'+
      (a.account_type==="credit"?metrics({debt,limit:a.credit_limit,available},{debt:"当前欠款",limit:"信用额度",available:"可用额度"})+
        '<p>账单日 '+h(a.bill_day||"未设置")+' 日 · 还款日 '+h(a.repay_day||"未设置")+' 日（遇短月按月末）</p>'+btn("creditpay:"+a.id,"记信用卡还款"):'')+'</div>'+billTable(filterBills(state.bills,{account:a.id}));
  }
  function totalsRows(owner) {
    return state.portfolio[owner].current.entries;
  }
  function grouped(owner,tab) {
    const items=tab==="accounts"?state.accounts.filter(a=>a.owner===owner):state.positions.filter(p=>p.owner===owner&&p.kind===tab);
    if(!items.length) return empty("暂无"+assetTabs[tab]+"记录",btn("addasset:"+owner,"添加资产或账户",true)+(owner==="family"?link("inventory","家庭资产盘点"):""));
    const groups=new Map();
    for(const item of items) {
      const group=tab==="accounts"?state.asset_options.accounts[item.account_type]:state.asset_options.positions[tab][item.subtype];
      if(!groups.has(group))groups.set(group,[]);
      groups.get(group).push(item);
    }
    const entries=totalsRows(owner);
    return [...groups].map(([group,list])=>'<section class="panel"><h2>'+h(group)+'</h2>'+list.map(item=>{
      const entry=entries.find(e=>e.kind===(tab==="accounts"?"account":"position")&&e.id===item.id);
      const value=(entry?.assets||0)-(entry?.debts||0);
      return '<a class="asset-row" href="#assets/'+(tab==="accounts"?"account":"detail")+'/'+item.id+'"><div><strong>'+h(item.name)+'</strong><small>'+h(item.institution||group)+
        (item.due?' · 到期 '+h(item.due)+(item.due<today()&&item.cost?' · 已逾期':""):"")+'</small></div><strong class="'+(value<0?"expense":"")+'">'+money(value)+' ›</strong></a>';
    }).join("")+'</section>').join("");
  }
  function view(q,sub,id) {
    if(sub==="account" && by(state.accounts,id)) return accountView(by(state.accounts,id));
    if(sub==="position") {const p=state.positions.find(p=>p.events.some(e=>e.id===Number(id)));if(p)return viewPosition(p);}
    if(sub==="detail" && by(state.positions,id)) return viewPosition(by(state.positions,id));
    const owner=q.get("owner")==="personal"?"personal":"family";
    const valid={overview:"资产概览",...assetTabs,charts:"图表分析"};
    const tab=Object.hasOwn(valid,q.get("tab"))?q.get("tab"):"overview";
    const nav=Object.entries(owners).map(([key,label])=>tabLink(assetURL(key,tab),label,key===owner)).join("");
    const tabs=Object.entries(valid).map(([key,label])=>tabLink(assetURL(owner,key),label,key===tab)).join("");
    let body="";
    if(tab==="charts") body=chartView(owner,q);
    else if(tab==="overview") body=composition(state.portfolio[owner].current,"assets")+composition(state.portfolio[owner].current,"debts")+
      '<div class="row">'+Object.entries(assetTabs).map(([key,label])=>link(assetURL(owner,key),label)).join("")+'</div>';
    else body='<div class="row">'+btn(tab==="accounts"?"newaccount:"+owner:"newpos:"+owner+":"+tab,"新增"+assetTabs[tab],true)+'</div>'+grouped(owner,tab);
    return heading("资产与借贷",owners[owner]+"资产概览 · 截至 "+today(),btn("addasset:"+owner,"添加资产或账户",true)+(owner==="family"?link("inventory","家庭资产盘点"):""))+
      '<div class="row">'+nav+'</div>'+summary(owner)+'<div class="row asset-tabs">'+tabs+'</div>'+body;
  }
  function allocationRing(ranked,total,label) {
    const cx=210, cy=118, radius=74, labels=[];
    let offset=0;
    const slices=ranked.map(([group,value],i)=>{
      const percent=100*value/total;
      const angle=(offset+percent/2)*Math.PI/50-Math.PI/2;
      if(i<3) labels.push({group,percent,i,x:cx+96*Math.cos(angle),y:cy+96*Math.sin(angle)});
      // Keep a white separator while preserving even the smallest allocation.
      const gap=ranked.length===1?0:Math.min(.55,percent*.18);
      const arc='<circle class="slice tone-'+i%8+'" cx="'+cx+'" cy="'+cy+'" r="'+radius+'" pathLength="100" stroke-dasharray="'+(percent-gap)+' '+(100-percent+gap)+'" stroke-dashoffset="'+(-offset)+'" transform="rotate(-90 '+cx+' '+cy+')"/>';
      offset+=percent;
      return arc;
    });
    const notes=[];
    for(const right of [false,true]) {
      const side=labels.filter(point=>(point.x>=cx)===right).sort((a,b)=>a.y-b.y);
      let last=3;
      side.forEach(({group,percent,i,x,y},index)=>{
        const level=Math.min(217-27*(side.length-index-1),Math.max(y,last+27));
        last=level;
        const edge=right?414:6, elbow=right?316:104;
        notes.push('<g class="tone-'+i+'"><polyline points="'+x+','+y+' '+elbow+','+level+' '+edge+','+level+'"/><circle cx="'+x+'" cy="'+y+'" r="2.6"/><text x="'+edge+'" y="'+(level-5)+'" text-anchor="'+(right?'end':'start')+'">'+h([...group].slice(0,6).join(''))+' '+percent.toFixed(1)+'%</text></g>');
      });
    }
    return '<svg class="allocation-ring" viewBox="0 0 420 236" role="img" aria-label="'+label+'分类占比">'+slices.join('')+notes.join('')+
      '<text class="ring-caption" x="210" y="111">合计</text><text class="ring-total" x="210" y="136" font-size="'+Math.min(16,148/money(total).length)+'">'+money(total)+'</text></svg>';
  }
  function composition(current,metric) {
    const entries=current.entries.filter(e=>e[metric]>0).sort((a,b)=>b[metric]-a[metric]||a.id-b.id);
    const groups=new Map();
    for(const entry of entries) groups.set(entry.group,(groups.get(entry.group)||0)+entry[metric]);
    const ranked=[...groups].sort((a,b)=>b[1]-a[1]);
    const total=current[metric];
    return '<section class="panel composition"><h2>当前'+chartNames[metric]+'配置</h2>'+(!total?'<p class="muted">暂无'+chartNames[metric]+'数据</p>':
      '<div class="allocation">'+allocationRing(ranked,total,chartNames[metric])+'<div class="allocation-legend">'+ranked.map(([group,value],i)=>
        '<div class="legend-row"><span class="swatch tone-'+i%8+'"></span><span>'+h(group)+'</span><strong>'+money(value)+'</strong><span>'+ratio(value/total)+'</span></div>').join("")+'</div></div>')+
      '<h3>'+chartNames[metric]+'排行榜</h3>'+(entries.length?'<ol class="asset-ranking">'+entries.map(e=>'<li><a href="#assets/'+(e.kind==="account"?"account":"detail")+'/'+e.id+'">'+h(e.name)+'</a><strong>'+money(e[metric])+'</strong></li>').join("")+'</ol>':'<p class="muted">暂无记录</p>')+'</section>';
  }
  function chartView(owner,q) {
    const year=/^[0-9]{4}$/.test(q.get("year")||"")&&Number(q.get("year"))>0?Number(q.get("year")):new Date().getFullYear();
    const metric=Object.hasOwn(chartNames,q.get("metric"))?q.get("metric"):"assets";
    const key=owner+"/"+year;
    const report=year===new Date().getFullYear()?state.portfolio[owner]:charts.get(key);
    const controls='<form id="assetchart" class="row asset-chart-controls">'+input("owner",owner,'type="hidden"')+input("tab","charts",'type="hidden"')+
      field("年份",input("year",year,'type="number" min="1" max="9999" required'))+field("指标",select("metric",Object.entries(chartNames),metric))+'<button class="primary">查看</button></form>';
    if(!report) {
      if(loading!==key) {
        loading=key;const hash=location.hash;
        api("/api/portfolio?owner="+owner+"&year="+year).then(data=>{charts.set(key,data);if(location.hash===hash)render();})
          .catch(error=>flash(error.message)).finally(()=>{if(loading===key)loading="";});
      }
      return '<div class="panel">'+controls+'<p>正在读取年度记录…</p></div>';
    }
    const values=report.months.map(m=>m[metric]);
    const rows=report.months.map(m=>'<tr><td>'+m.month+'月</td><td>'+(m[metric]==null?'尚未发生':money(m[metric]))+'</td></tr>').join("");
    return '<section class="panel">'+controls+'<h2>'+year+'年'+chartNames[metric]+'走势图</h2><p class="muted">按月末记录重算，本月截至今天；未来月份留空。归属和期初配置修改后历史会重算。</p>'+
      trendChart(values,metric)+
      '<details><summary>查看每月金额</summary><table class="table"><thead><tr><th>月份</th><th>'+chartNames[metric]+'</th></tr></thead><tbody>'+rows+'</tbody></table></details></section>'+
      (metric==="net"?'<section class="panel"><h2>当前净资产状况</h2>'+metrics(report.current,{assets:"资产",debts:"负债",net:"净资产"})+
        '<div class="debt-comparison"><label>资产 <meter min="0" max="'+Math.max(1,report.current.assets,report.current.debts)+'" value="'+report.current.assets+'"></meter></label><label>负债 <meter min="0" max="'+Math.max(1,report.current.assets,report.current.debts)+'" value="'+report.current.debts+'"></meter></label></div>'+
        '<p>资产负债率 '+ratio(report.current.ratio)+'（负债 ÷ 资产，资产为零时显示 —）</p></section>':composition(report.current,metric));
  }
  function trendChart(values,metric) {
    const valid=values.map((value,i)=>({value,i})).filter(p=>p.value!=null);
    if(!valid.length)return '<p class="muted">该年份暂无已发生月份</p>';
    const peak=valid.reduce((best,p)=>p.value>best.value?p:best);
    const min=Math.min(0,...valid.map(p=>p.value)),max=Math.max(1,...valid.map(p=>p.value)),range=max-min;
    const x=i=>115+i*66,y=v=>285-(v-min)/range*200;
    const color={assets:"blue",debts:"red",net:"warm"}[metric];
    const grid=Array.from({length:5},(_,i)=>{
      const v=min+range*i/4;
      return '<line x1="110" y1="'+y(v)+'" x2="850" y2="'+y(v)+'"/><text class="axis-value" x="102" y="'+(y(v)+4)+'">'+money(v)+'</text>';
    }).join("");
    const monthLabels=values.map((v,i)=>'<text class="axis-month" x="'+x(i)+'" y="319">'+(i+1)+'月</text>').join("");
    const paths=[];let segment=[];
    for(let i=0;i<=values.length;i++){
      if(i<values.length&&values[i]!=null)segment.push([x(i),y(values[i])]);
      else if(segment.length){
        paths.push('<path class="trend-area" d="M '+segment[0][0]+' 285 L '+segment.map(p=>p.join(' ')).join(' L ')+' L '+segment.at(-1)[0]+' 285 Z"/><polyline class="trend-line" points="'+segment.map(p=>p.join(',')).join(' ')+'"/>');
        segment=[];
      }
    }
    const points=valid.map(p=>'<circle class="trend-point" tabindex="0" cx="'+x(p.i)+'" cy="'+y(p.value)+'" r="'+(p.i===peak.i?6:4.5)+'"><title>'+(p.i+1)+'月 '+money(p.value)+'</title></circle>').join("");
    const peakX=x(peak.i),peakY=y(peak.value),tipX=Math.max(112,Math.min(704,peakX-66));
    return '<div class="trend-highlights">'+metrics({peak:peak.value,latest:valid.at(-1).value},{peak:"最高月份 · "+(peak.i+1)+"月",latest:"最近记录 · "+(valid.at(-1).i+1)+"月"})+'</div>'+
      '<div class="asset-trend-wrap"><svg class="asset-trend '+color+'" viewBox="0 0 880 345" role="img" aria-label="年度'+chartNames[metric]+'走势，最高'+(peak.i+1)+'月'+money(peak.value)+'">'+
      '<g class="trend-grid">'+grid+'</g><line class="peak-guide" x1="'+peakX+'" y1="74" x2="'+peakX+'" y2="285"/>'+paths.join("")+points+monthLabels+
      '<rect class="peak-bubble" x="'+tipX+'" y="'+(peakY-44)+'" width="140" height="29" rx="8"/><text class="peak-label" x="'+(tipX+70)+'" y="'+(peakY-25)+'">'+money(peak.value)+'</text></svg></div>';
  }
  function mount() {}
  return {clear,home,view,accountForm,positionForm,add,valueForm,physical,mount};
})();
