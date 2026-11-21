"use strict";
const WorkspaceUI=(()=>{
  function budget(book,month){
    const entries=state.budgets.filter(r=>r.month===month&&(!book||r.book_id===Number(book)));
    const rows=state.bills.filter(b=>b.day.startsWith(month)&&(!book||b.book_id===Number(book)));
    const s=summarize(rows),limit=entries.reduce((n,r)=>n+r.amount,0);
    return '<section class="panel budget-card">'+metrics(s,{net:"本月结余",expense:"本月支出",income:"本月收入"})+
      '<div class="budget-bottom">'+(entries.length?'<strong class="'+(s.expense>limit?'expense':'income')+'">'+(s.expense>limit?'本月预算超支 '+money(s.expense-limit):'预算剩余 '+money(limit-s.expense))+'</strong><span>预算 '+money(limit)+'</span>':'<span>尚未设置本月预算</span>')+
      btn("budget:"+book+":"+month,"预算设定")+'</div></section>';
  }
  function budgetForm(book,month){
    const books=state.books.filter(b=>!b.archived);
    if(!books.length){bookForm();return;}
    book=book||state.current_book||books[0].id;
    const old=state.budgets.find(r=>r.book_id===Number(book)&&r.month===month);
    const form=openForm("月度预算",field("选择账本",select("book_id",books.map(b=>[b.id,b.name]),book))+'<p>'+month+'</p>'+field("预算金额（元）",moneyInput("amount",old?.amount||0)),
      (d,send)=>saveAndRender(send,{action:"budget",book_id:Number(d.book_id),month,amount:parseMoney(d.amount,false,true)}));
    form.elements.book_id.onchange=()=>{
      form.elements.amount.value=(state.budgets.find(r=>r.book_id===Number(form.elements.book_id.value)&&r.month===month)?.amount||0)/100;
    };
  }
  function bills(q){
    const month=monthOf(q.get("month")||q.get("from")?.slice(0,7)),book=q.get("book")||"";
    const base=Object.fromEntries(q);delete base.day;
    const tabs='<div class="row"><label>当前账本<select id="bill-book-select"><option value="">全部账本</option>'+state.books.map(b=>'<option value="'+b.id+'"'+(String(b.id)===book?' selected':'')+'>'+h(b.name)+'</option>').join("")+'</select></label>'+tabLink("bills"+filterRoute({...base,month,view:"list"}),"明细",q.get("view")!=="calendar")+
      tabLink("bills"+filterRoute({...base,month,view:"calendar"}),"日历",q.get("view")==="calendar")+'</div>';
    let calendar="";
    if(q.get("view")==="calendar"){
      const rows=filterBills(state.bills,{...Object.fromEntries(q),from:month+"-01",to:month+"-"+pad(DatePicker.lastDay(month))});
      calendar='<section class="panel"><div class="row">'+link("bills"+filterRoute({...base,month:monthShift(month,-1)}),"上月")+
        field("跳转月份",input("calendar_month",month,'type="month" data-calendar-month="bills"'))+
        link("bills"+filterRoute({...base,month:monthShift(month,1)}),"下月")+'</div><div class="calendar">'+
        DatePicker.monthGrid(month,(day,n)=>calendarCell(day,"bills"+filterRoute({...base,month,day}),
          summarize(rows.filter(b=>b.day===day)),day===q.get("day"),n));
      calendar+='</div></section>';
    }
    const filtered=new URLSearchParams(q);
    if(q.get("view")==="calendar"||(!q.get("from")&&!q.get("to"))){filtered.set("month",month);filtered.set("from",month+"-01");filtered.set("to",localDate(new Date(Number(month.slice(0,4)),Number(month.slice(5,7)),0)));}
    if(q.get("day")){filtered.set("from",q.get("day"));filtered.set("to",q.get("day"));}
    const content=baseBills(filtered);
    const end=content.indexOf('</form></div>')+'</form></div>'.length;
    return content.slice(0,end)+tabs+budget(book,month)+calendar+
      (q.get("day")?'<h2>'+h(q.get("day"))+' 当日收支明细</h2>':"")+content.slice(end);
  }
  function period(q){
    const month=monthOf(q.get("month")),scope=q.get("period")||"month";
    let start=month+"-01",end=localDate(new Date(Number(month.slice(0,4)),Number(month.slice(5,7)),0));
    if(scope==="year"){start=month.slice(0,4)+"-01-01";end=month.slice(0,4)+"-12-31";}
    if(scope==="week"){
      const d=new Date((q.get("date")||today())+"T12:00:00");d.setDate(d.getDate()-(d.getDay()+6)%7);start=localDate(d);d.setDate(d.getDate()+6);end=localDate(d);
    }
    return {start,end,scope,month};
  }
  function more(rows){return rows.slice(0,3).join("")+(rows.length>3?'<details class="more-ranking"><summary>查看更多</summary>'+rows.slice(3).join("")+'</details>':"");}
  function stats(q){
    const {start,end,scope,month}=period(q),book=q.get("book")||"",kind=q.get("kind")==="income"?"income":"expense",label=kind==="income"?"收入":"支出";
    const all=filterBills(state.bills,{book,from:start,to:end,category:q.get("category")}),rows=all.filter(b=>b.kind===kind),s=summarize(all);
    const grouped=new Map(),daily=new Map();
    for(const b of rows){grouped.set(b.category_id,(grouped.get(b.category_id)||0)+b.amount);const key=scope==="year"?b.day.slice(0,7):b.day;daily.set(key,(daily.get(key)||0)+b.amount);}
    const rank=[...grouped].sort((a,b)=>b[1]-a[1]),top=rows.slice().sort((a,b)=>b.amount-a.amount||b.id-a.id);
    const days=[];for(let d=new Date(start+"T12:00:00");localDate(d)<=end;d.setDate(d.getDate()+1)){
      const key=scope==="year"?localDate(d).slice(0,7):localDate(d);if(!days.includes(key))days.push(key);
    }
    const values=days.map(d=>daily.get(d)||0),max=Math.max(1,...values),peak=values.indexOf(Math.max(...values));
    const x=i=>60+i*740/Math.max(1,days.length-1);
    const y=value=>230-value/max*170;
    const points=values.map((value,i)=>x(i)+","+y(value)).join(" ");
    const trend=title=>'<div class="asset-trend-wrap"><svg class="analysis-trend trend-'+kind+'" viewBox="0 0 860 285" aria-label="'+title+'">'+
      '<line x1="60" y1="230" x2="810" y2="230"/><polyline points="'+points+'"/>'+
      values.map((value,i)=>{
        const date=days[i],periodStart=scope==="year"?date+"-01":date;
        const periodEnd=scope==="year"?date+"-"+pad(DatePicker.lastDay(date)):date;
        const width=Math.min(54,740/Math.max(1,days.length-1));
        const tooltipX=Math.max(115,Math.min(745,x(i)));
        const url="bills"+filterRoute({book,kind,category:q.get("category"),from:periodStart,to:periodEnd,month:periodStart.slice(0,7)});
        return '<a class="analysis-point" href="#'+h(url)+'" aria-label="'+h(date+" "+money(value)+"，查看明细")+'">'+
          '<rect class="analysis-hit" x="'+(x(i)-width/2)+'" y="46" width="'+width+'" height="200"/>'+
          '<circle cx="'+x(i)+'" cy="'+y(value)+'" r="4"/>'+
          '<g class="analysis-tooltip" transform="translate('+tooltipX+' '+(y(value)-27)+')"><rect x="-110" y="-19" width="220" height="27" rx="7"/>'+
          '<text text-anchor="middle">'+h(date+" · "+money(value))+'</text></g></a>';
      }).join("")+'<text x="60" y="266">'+start+'</text><text x="680" y="266">'+end+'</text></svg></div>';
    const controls='<form id="statsfilter" class="row aligned-controls">'+field("月份",input("month",month,'type="month" required'))+
      field("账本",select("book",[["","全部账本"],...state.books.map(b=>[b.id,b.name])],book).replace(" required",""))+
      field("统计范围",select("period",[["week","本周"],["month","本月"],["year","本年"]],scope))+
      (scope==="week"?field("所在周日期",input("date",q.get("date")||today(),'type="date"')):"")+
      field("分析类型",select("kind",[["expense","支出"],["income","收入"]],kind))+'<button class="primary">查看</button></form>';
    const legacy=legacyStats(q), monthly=legacy.slice(legacy.indexOf('<div class="panel"><h2>近六个月'),legacy.indexOf('<div class="panel"><h2>支出类目排行'));
    const previousStart=new Date(start+"T12:00:00"),previousEnd=new Date(end+"T12:00:00");
    if(scope==="year"){previousStart.setFullYear(previousStart.getFullYear()-1);previousEnd.setFullYear(previousEnd.getFullYear()-1);}
    else if(scope==="week"){previousStart.setDate(previousStart.getDate()-7);previousEnd.setDate(previousEnd.getDate()-7);}
    else {previousStart.setMonth(previousStart.getMonth()-1,1);previousEnd.setDate(0);}
    const before=summarize(filterBills(state.bills,{book,from:localDate(previousStart),to:localDate(previousEnd)}));
    const categoryRows=rank.map(([id,value],i)=>'<li class="rank-item">'+categoryIcon(by(state.categories,id))+'<div><a href="#stats'+h(filterRoute({book,month,period:scope,date:q.get("date"),kind,category:id}))+'">'+h(categoryLabel(by(state.categories,id)))+'</a><strong>'+money(value)+'</strong><progress class="stat-bar rank-bar" max="'+(rank[0]?.[1]||1)+'" value="'+value+'"></progress><small>'+rows.filter(b=>b.category_id===id).length+' 笔 · '+(value/(s[kind]||1)*100).toFixed(1)+'%</small></div></li>');
    const detailRows=top.map(b=>'<li class="rank-item">'+categoryIcon(by(state.categories,b.category_id))+'<div>'+h(categoryLabel(by(state.categories,b.category_id)))+'<strong>'+money(b.amount)+'</strong><p><small>'+b.day+' '+h(b.note)+'</small></p>'+btn(b.source_type?"eventedit:"+state.positions.find(p=>p.events.some(e=>e.id===b.source_id))?.id+":"+b.source_id:"edit:"+b.id,"查看记录")+'</div></li>');
    if(q.get("category")){
      const category=by(state.categories,q.get("category"));
      const back=new URLSearchParams(q);back.delete("category");back.delete("sort");
      const sorted=rows.slice().sort(q.get("sort")==="amount"?(a,b)=>b.amount-a.amount:(a,b)=>b.day.localeCompare(a.day)||b.id-a.id);
      return heading(categoryLabel(category)+" · 类目明细",start+" 至 "+end,link("stats?"+back,"返回统计分析"))+
        '<section class="panel"><h2>'+h(categoryLabel(category))+'类目下已'+label+'</h2>'+
        metrics({total:s[kind],average:rows.length?Math.round(s[kind]/rows.length):0},{total:"合计",average:"平均每次"+label})+'<p>共 '+rows.length+' 笔记录</p>'+
        trend("类目趋势")+'</section>'+
        '<div class="heading"><h2>类目明细</h2><div class="toolbar">'+link("stats"+filterRoute({...Object.fromEntries(q),sort:"time"}),"按时间")+link("stats"+filterRoute({...Object.fromEntries(q),sort:"amount"}),"按金额")+'</div></div>'+billTable(sorted);
    }
    return heading("统计分析",start+" 至 "+end)+'<section class="panel">'+controls+'</section>'+
      '<section class="panel"><h2>'+(scope==="month"?"本月结余":"期间结余")+'</h2>'+metrics(s)+'<p class="muted">较上一'+({week:"周",month:"月",year:"年"})[scope]+'结余变化 '+money(s.net-before.net)+'</p></section>'+
      '<section class="panel"><h2>'+label+'趋势概况</h2><p>最高'+(scope==="year"?'月份':'日期')+' '+days[peak]+' <strong class="expense">'+money(values[peak])+'</strong></p>'+
      metrics({avg:Math.round(s[kind]/days.length)},{avg:scope==="year"?"平均每月":"平均每日"})+'<p>累计 '+rows.length+' 笔</p>'+
      trend(label+"趋势")+'</section>'+
      '<section class="panel"><h2>'+label+'占比概况</h2>'+(rank.length?AssetUI.ring(rank.map(([id,v])=>[categoryLabel(by(state.categories,id)),v]),s[kind],label,rank.map(([id])=>"stats"+filterRoute({book,month,period:scope,date:q.get("date"),kind,category:id}))):'<p>暂无数据</p>')+'</section>'+
      '<section class="panel"><h2>'+label+'类目排行</h2><ol class="ranking">'+more(categoryRows)+'</ol></section>'+
      '<section class="panel"><h2>'+label+'明细排行</h2><ol class="ranking">'+more(detailRows)+'</ol></section>'+monthly;
  }
  function loanForm(id){
    if(String(id).startsWith("f")){forecastForm(Number(String(id).slice(1)));return;}
    const credit=String(id).startsWith("a"),p=credit?by(state.accounts,String(id).slice(1)):by(state.positions,id),key=credit?"account_id":"position_id";
    const schedules=credit?state.credit_installments:state.installments;
    const query=route().q;
    const backQuery=new URLSearchParams((query.get("return")||"").split("?")[1]);
    const old=(credit?state.credit_plans:state.loan_plans).find(r=>r[key]===p.id),year=boardYear(query.has("year")?query:backQuery);
    const form=openForm("借贷月度计划",
      field("年份",input("year",year,'type="number" min="1" max="9999" required'))+
      field("年化利率（%，选填）",input("annual_rate",old?.annual_rate,'type="number" min="0" step="0.0001"'))+
      '<p>按约定填写各月应还 / 应收总额，包含本金与利息。计划不生成实际流水。</p>'+
      Array.from({length:12},(_,i)=>field((i+1)+"月（元）",moneyInput("m"+i,schedules.find(r=>r[key]===p.id&&r.month===String(year).padStart(4,"0")+"-"+pad(i+1))?.amount||0))).join(""),
      (d,send)=>saveAndRender(send,{action:"loan_plan",[key]:p.id,year:Number(d.year),annual_rate:d.annual_rate,
        months:Array.from({length:12},(_,i)=>parseMoney(d["m"+i],false,true))}));
    form.elements.year.onchange=()=>{
      const yearKey=String(Number(form.elements.year.value)).padStart(4,"0");
      for(let i=0;i<12;i++)form.elements["m"+i].value=(schedules.find(r=>r[key]===p.id&&r.month===yearKey+"-"+pad(i+1))?.amount||0)/100;
    };
  }
  function forecastForm(id){
    const p=by(state.forecast_items,id);
    openForm("编辑月度计划",field("年份",input("year",p.year,'type="number" min="1" max="9999" required'))+
      Array.from({length:12},(_,i)=>field((i+1)+"月（元）",moneyInput("m"+i,JSON.parse(p.months)[i]))).join(""),
      (d,send)=>saveAndRender(send,{action:"forecast_plan",id,year:Number(d.year),months:Array.from({length:12},(_,i)=>parseMoney(d["m"+i],false,true))}));
  }
  function remainingPrincipal(p){
    const entry=state.portfolio[p.owner].current.entries.find(e=>e.kind==="position"&&e.id===p.id);
    return (p.kind==="borrow"?entry?.debts:entry?.assets)??0;
  }
  function boardYear(q){
    const year=Number(q.get("year"));
    return Number.isInteger(year)&&year>=1&&year<=9999?year:new Date().getFullYear();
  }
  function yearlyPrincipalPreview(row){
    const output=row.querySelector("[data-yearly-principal]");
    if(!output)return;
    try{
      const total=Array.from({length:12},(_,i)=>parseMoney(row.querySelector('[name="m'+i+'"]').value||"0",false,true))
        .reduce((sum,amount)=>sum+amount,0);
      output.textContent=money(total);
    }catch{output.textContent="—";}
  }
  function principalForm(id){
    const forecast=String(id).startsWith("f");
    const p=forecast?by(state.forecast_items,String(id).slice(1)):by(state.positions,id);
    openForm(p.kind==="lend"?"设置账务本金":"设置剩余本金",'<p>'+h(p.name)+'</p>'+
      field("剩余本金（元）",moneyInput("principal",forecast?null:remainingPrincipal(p)))+
      (forecast?'<p>保存后会登记为正式借贷项目，并保留月度计划和已还 / 已收标记。</p>':"")+
      '<p>从今天起按新余额计算。此操作不生成收付款流水。</p>',
      async(d,send)=>{
        const result=await send({action:"loan_principal",id:p.id,forecast,principal:parseMoney(d.principal,false,true)});
        const [,detail]=route().parts;
        const back=detailReturn(assetURL(p.owner,p.kind));
        await refresh();
        if(forecast&&detail==="forecast")location.hash="assets/detail/"+result.id+"?return="+encodeURIComponent(back);
        render();
      });
  }
  function board(owner,kind,q){
    const borrowing=kind==="borrow";
    const year=boardYear(q), yearKey=String(year).padStart(4,"0");
    const plans=[...state.loan_plans,...state.credit_plans.map(r=>({...r,position_id:"a"+r.account_id}))];
    const credit=kind==="borrow"?state.accounts.filter(a=>a.owner===owner&&a.account_type==="credit"&&a.balance<0).map(a=>({...a,id:"a"+a.id,accountID:a.id,credit:true,cost:-a.balance})):[];

    const forecasts=state.forecast_items.filter(p=>p.owner===owner&&p.kind===kind).map(p=>({...p,id:"f"+p.id,forecast:true,cost:0}));
    const loans=state.positions.filter(p=>p.owner===owner&&p.kind===kind).map(p=>({...p,cost:remainingPrincipal(p)}));
    const list=[...loans,...credit,...forecasts];
    const sums=Array(12).fill(0);
    const rows=list.map(p=>{
      const plan=plans.find(r=>r.position_id===p.id),amounts=p.forecast?(p.year===year?JSON.parse(p.months):Array(12).fill(0)):sums.map((_,i)=>(p.credit?state.credit_installments:state.installments).find(r=>r[p.credit?"account_id":"position_id"]===(p.credit?p.accountID:p.id)&&r.month===yearKey+"-"+pad(i+1))?.amount||0);
      const total=amounts.reduce((sum,amount)=>sum+amount,0);
      const paidMonths=new Set(p.forecast?JSON.parse(p.paid_months||"[]"):
        (p.credit?[]:state.installments.filter(row=>row.position_id===p.id&&row.paid).map(row=>row.month)));
      amounts.forEach((v,i)=>sums[i]+=v);
      const operations=btn("loanplan:"+p.id,"设置月度计划")+(p.credit?"":btn("moveloan:"+p.id,"转到"+owners[otherOwner(owner)])+
        '<input type="checkbox" data-board-item value="'+p.id+'" aria-label="选择 '+h(p.name)+'">'+btn("deleteloan:"+kind+":"+p.id,"删除"));
      return '<tr><th scope="row" class="board-content">'+'<a class="board-name" href="#'+(p.forecast?"assets/forecast/"+p.id.slice(1):p.credit?"assets/account/"+p.accountID:"assets/detail/"+p.id)+'?return='+encodeURIComponent(location.hash.slice(1))+'">'+h(p.name)+'</a></th><td>'+h((p.annual_rate||plan?.annual_rate)?(p.annual_rate||plan.annual_rate)+"%":"—")+'</td><td>'+money(total)+'</td>'+amounts.map((v,i)=>'<td class="'+(v&&paidMonths.has(yearKey+"-"+pad(i+1))?'is-paid':'')+'">'+(v?money(v):"—")+'</td>').join("")+'<td class="board-actions"><div class="toolbar">'+operations+'</div></td></tr>';
    }).join("");
    const annualTotal=sums.reduce((sum,amount)=>sum+amount,0);
    return '<section class="panel loan-panel"><h2>'+(kind==="borrow"?"负债明细看板":"借款应收看板")+ '</h2>'+btn("imageimport:"+owner+":"+kind,"图片识别导入")+ '<form id="assetchart" class="row aligned-controls board-controls">'+input("owner",owner,'type="hidden"')+input("tab",kind,'type="hidden"')+
      field("年份",input("year",year,'type="number" min="1" max="9999" required'))+'<button>查看</button></form>'+
      '<p>'+(borrowing?"总负债 "+money(list.reduce((s,p)=>s+p.cost,0)):"本年应收合计 "+money(annualTotal))+' · 未配置计划的月份显示 —</p><div class="inventory-scroll board-frame" data-board-key="'+owner+':'+kind+':'+year+'"><table class="table loan-board"><thead><tr><th>内容</th><th>年化利率</th><th>全年合计</th>'+
      sums.map((_,i)=>'<th>'+(i+1)+'月'+(kind==="borrow"?"应还":"应收")+'</th>').join("")+'<th class="board-actions"><div class="toolbar board-selection"><label><input type="checkbox" data-board-all>全选</label><button type="button" data-act="deletechecked:'+kind+'" disabled>批量删除</button></div></th></tr></thead><tbody>'+rows+
      '<tr><th colspan="2">每月合计</th><td>'+money(annualTotal)+'</td>'+sums.map(v=>'<td>'+money(v)+'</td>').join("")+'<td></td></tr></tbody></table></div></section>';
  }
  function otherOwner(owner){return owner==="family"?"personal":"family";}
  function moveLoan(id){
    const forecast=id.startsWith("f"), key=Number(forecast?id.slice(1):id);
    const item=by(forecast?state.forecast_items:state.positions,key);
    const target=otherOwner(item.owner);
    const query=route().q;
    const sourceQuery=new URLSearchParams((query.get("return")||"").split("?")[1]);
    const year=boardYear(query.has("year")?query:sourceQuery);
    const back=assetURL(target,item.kind)+"&year="+year;
    ask("转到"+owners[target],"将「"+item.name+"」从"+owners[item.owner]+"转到"+owners[target]+"？月度计划、收还款标记和流水随项目保留。",async send=>{
      await send({action:"move_loan",id:key,forecast,kind:item.kind,owner:item.owner,target});
      await refresh();location.hash=back;render();
    },"确认转移");
  }
  function updateSelection(control){
    const frame=control.closest(".board-frame");
    const boxes=[...frame.querySelectorAll("[data-board-item]")];
    const all=frame.querySelector("[data-board-all]");
    if(control===all) boxes.forEach(box=>{box.checked=all.checked;});
    const count=boxes.filter(box=>box.checked).length;
    all.checked=count>0&&count===boxes.length;
    all.indeterminate=count>0&&count<boxes.length;
    frame.querySelector('[data-act^="deletechecked:"]').disabled=count===0;
  }
  function deleteLoan(kind,ids){
    if(!ids.length)return;
    const entries=ids.map(id=>{
      const forecast=String(id).startsWith("f");
      return {forecast,id:Number(forecast?String(id).slice(1):id)};
    });
    const first=entries[0];
    const item=by(first.forecast?state.forecast_items:state.positions,first.id);
    const text=ids.length===1?"删除「"+item.name+"」？":"删除已选中的 "+ids.length+" 个项目？";
    const [pageName,detail]=route().parts;
    const back=detailReturn(assetURL(item.owner,kind));
    ask("删除借贷项目",text+"这也会删除对应计划和关联流水，并重新计算账户余额。",async send=>{
      await send({action:"delete_loans",owner:item.owner,kind,entries});
      await refresh();
      if(pageName==="assets"&&detail) location.hash=back;
      render();
    },"确认删除");
  }
  function forecastDetail(item){
    return heading(item.name,owners[item.owner]+" · "+assetTabs[item.kind],link(detailReturn(assetURL(item.owner,item.kind)),"返回看板")+btn("moveloan:f"+item.id,"转到"+owners[otherOwner(item.owner)])+btn("loanprincipal:f"+item.id,item.kind==="lend"?"登记账务本金":"设置剩余本金")+btn("deleteloan:"+item.kind+":f"+item.id,"删除项目"))+
      paymentSchedule(item,true);
  }
  function paymentSchedule(position,forecast=false){
    const items=forecast?JSON.parse(position.months).map((amount,index)=>{
      const month=String(position.year).padStart(4,"0")+"-"+pad(index+1);
      return {amount,month,paid:JSON.parse(position.paid_months).includes(month)};
    }).filter(row=>row.amount>0):state.installments.filter(row=>row.position_id===position.id&&row.amount>0)
      .sort((a,b)=>a.month.localeCompare(b.month));
    const rate=forecast?position.annual_rate:state.loan_plans.find(row=>row.position_id===position.id)?.annual_rate;
    const lending=position.kind==="lend";
    return '<section class="panel"><h2>'+(lending?"每月应收":"每月应还")+'</h2>'+
      (rate?'<p>年化利率 '+h(rate)+'%</p>':"")+
      (items.length?'<div class="payment-list">'+items.map(row=>'<label class="payment-card'+(row.paid?' is-paid':'')+'">'+
        '<span>'+h(row.month)+'</span><strong>'+money(row.amount)+'</strong><span class="paid-control"><input type="checkbox" data-paid-id="'+position.id+
        '" data-forecast="'+forecast+'" data-paid-month="'+h(row.month)+'" '+(row.paid?"checked":"")+'>'+(lending?"已收回":"已还款")+'</span></label>').join("")+'</div>':
        '<p class="muted">暂无分期计划</p>')+
      '<div class="toolbar">'+btn("loanplan:"+(forecast?"f":"")+position.id,"设置月度计划")+'</div></section>';
  }
  async function markPaid(control){
    const paid=control.checked;
    control.disabled=true;
    try{
      await api("/api/action",{action:"installment_paid",id:Number(control.dataset.paidId),month:control.dataset.paidMonth,
        paid,forecast:control.dataset.forecast==="true",request_id:crypto.randomUUID()});
      await refresh();render();
    }catch(error){
      control.checked=!paid;
      flash(error.message);
    }finally{
      control.disabled=false;
    }
  }
  function exchange(){
    const form=openForm("导出数据",field("格式",select("format",[["db","SQLite .db"],["xlsx","Excel .xlsx"],["xls","Excel .xls"]],"db"))+
      field("账本",select("book",[["","全部账本"],...state.books.map(b=>[b.id,b.name])],"").replace(" required",""))+
      field("资产归属",select("owner",[["all","家庭与个人"],["family","家庭资产"],["personal","个人资产"],["none","仅账单"]],"all"))+
      field("导出目录完整路径",input("path","","required"))+'<p>SQLite .db 保留账单图片。Excel 导出只含表格数据。筛选导出保留账户当前余额，未选流水的影响结转至期初余额。</p>',async d=>{
        const result=await api("/api/files",{...d,action:"export_data"});flash("已导出至 "+result.path);
      },"导出");
  }
  return {bills,stats,budgetForm,board,boardYear,yearlyPrincipalPreview,loanForm,principalForm,remainingPrincipal,paymentSchedule,forecastDetail,markPaid,moveLoan,deleteLoan,updateSelection,exchange};
})();
