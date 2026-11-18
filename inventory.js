"use strict";
const InventoryUI=(()=>{
  const sections={physical:"固定及实物资产",investment:"投资与有价证券",cash:"现金及应收款",insurance:"保险现金价值",debt:"其他负债"};
  const types={physical:{property:"房产",vehicle:"汽车",custom:"车位 / 收藏 / 其他"},
    investment:{stock:"股票",fund:"基金",gold:"贵金属",deposit:"存款理财",other:"债券 / 其他投资"},
    cash:{bank:"银行存款",cash:"现金",wallet:"电子钱包",receivable:"应收款"},
    insurance:{custom:"保险"},debt:{loan:"贷款 / 私人借款",credit:"信用卡透支",payable:"应付款"}};
  let draft={day:"",items:[]},bookID="";
  function view(q){
    const books=state.books.filter(b=>!b.archived), selected=q.get("book")||books[0]?.id;
    const saved=state.inventories.find(r=>r.book_id===Number(selected));
    if(saved){
      const rows=JSON.parse(saved.payload).items, records=JSON.parse(saved.records);
      return heading("家庭资产盘点",by(state.books,selected)?.name||"",link("assets?owner=family","返回资产概览"))+
        '<section class="panel"><h2>'+saved.day+' 期初盘点</h2>'+metrics({assets:saved.assets,debts:saved.debts,net:saved.assets-saved.debts},{assets:"盘点资产",debts:"盘点负债",net:"盘点净资产"})+
        '<p class="muted">当前余额与后续变动可在对应账户和资产详情中更新。</p><div class="row">'+records.map(r=>link("assets/"+(r.kind==="account"?"account":"detail")+"/"+r.id,(r.kind==="account"?by(state.accounts,r.id):by(state.positions,r.id))?.name||"查看记录")).join("")+
        '</div><details><summary>查看原始盘点表</summary><div class="inventory-scroll"><table class="table"><thead><tr><th>部分</th><th>名称</th><th>现值</th><th>负债</th><th>购买总价 / 已投金额</th><th>授信额度</th><th>购买及贷款信息</th><th>备注</th></tr></thead><tbody>'+rows.map(r=>'<tr><td>'+sections[r.kind]+'</td><td>'+h(r.name)+'</td><td>'+money(r.value)+'</td><td>'+money(r.debt)+'</td><td>'+money(r.cost)+'</td><td>'+money(r.limit)+'</td><td>'+h(r.detail)+'</td><td>'+h(r.note)+'</td></tr>').join("")+'</tbody></table></div></details></section>';
    }
    bookID=String(selected||"");
    if(!draft.day)draft.day=today();
    return heading("家庭资产盘点","参照家庭资产盘点表填写，预览后一次导入所选账本",link("assets?owner=family","返回资产概览"))+
      '<section class="panel"><div class="inventory-controls">'+field("关联家庭账本",select("inventory_book",books.map(b=>[b.id,b.name]),selected))+
      field("盘点日期",input("inventory_day",draft.day,'type="date" required'))+btn("newbook","新建账本")+'</div><p>以盘点日期登记已有余额。投资填写当前市值，保险填写现金价值，贷款填写剩余本金。</p><p class="muted">同一资产及贷款只填写一次。货币基金填入投资，应收款填入现金及应收款；盘点不会产生收入或支出流水。</p></section>'+
      Object.entries(sections).map(([kind,label])=>'<section class="panel"><div class="heading"><h2>'+label+'</h2><button type="button" data-inventory-add="'+kind+'">＋ 添加一项</button></div><div class="inventory-rows">'+draft.items.map((r,i)=>r.kind===kind?row(r,i):"").join("")+'</div></section>').join("")+
      '<section class="panel inventory-footer"><p role="alert" id="inventory-error"></p><div id="inventory-totals"></div><button type="button" class="primary" id="inventory-preview">预览并导入</button></section>';
  }
  function row(r,i){
    const amount=(key,label)=>field(label,input(key,(r[key]||0)/100,'type="number" min="0" step="0.01" required'));
    return '<div class="inventory-item" data-inventory-row="'+i+'">'+field("名称",input("name",r.name,'maxlength="80" required'))+
      field("类型",select("subtype",Object.entries(types[r.kind]),r.subtype))+
      (r.kind!=="debt"?amount("value",r.kind==="insurance"?"现金价值（元）":"当前金额 / 市值（元）"):"")+
      (["physical","investment","insurance"].includes(r.kind)?amount("cost",r.kind==="insurance"?"已投金额（元）":"购买总价 / 投资成本（元）"):"")+
      (r.kind!=="cash"?amount("debt","剩余贷款 / 已欠本金（元）"):"")+
      (r.kind==="debt"?amount("limit","总授信额度（元，信用卡必填）"):"")+
      field("购买日期、面积、已投年限、贷款年限与年利率",input("detail",r.detail,'maxlength="300" placeholder="例如：2020年购入，90㎡，剩余20年，年利率3%"'))+
      field("备注 / 诊断",input("note",r.note,'maxlength="500"'))+'<button type="button" data-inventory-remove="'+i+'">移除此项</button></div>';
  }
  function collect(){
    draft.day=page.querySelector('[name="inventory_day"]').value;
    bookID=page.querySelector('[name="inventory_book"]').value;
    for(const node of page.querySelectorAll('[data-inventory-row]')){
      const r=draft.items[Number(node.dataset.inventoryRow)];
      for(const el of node.querySelectorAll('input,select'))r[el.name]=["value","cost","debt","limit"].includes(el.name)?parseMoney(el.value,false,true):el.value;
    }
    return {action:"inventory",book_id:Number(bookID),...draft};
  }
  function mount(){
    if(!page.querySelector('#inventory-preview'))return;
    const error=page.querySelector('#inventory-error');
    const attempt=fn=>{try{fn();error.textContent="";}catch(e){error.textContent=e.message;}};
    for(const button of page.querySelectorAll('[data-inventory-add]'))button.onclick=()=>attempt(()=>{
      collect();const kind=button.dataset.inventoryAdd;
      draft.items.push({kind,name:"",subtype:Object.keys(types[kind])[0],value:0,cost:0,debt:0,limit:0,detail:"",note:""});render();
    });
    for(const button of page.querySelectorAll('[data-inventory-remove]'))button.onclick=()=>attempt(()=>{collect();draft.items.splice(Number(button.dataset.inventoryRemove),1);render();});
    page.querySelector('[name="inventory_book"]').onchange=()=>attempt(()=>{collect();location.hash="inventory?book="+bookID;});
    const totals=()=>{
      const data=collect(),assets=data.items.reduce((sum,r)=>sum+r.value,0),debts=data.items.reduce((sum,r)=>sum+r.debt,0);
      page.querySelector('#inventory-totals').innerHTML=metrics({assets,debts,net:assets-debts},{assets:"盘点总资产",debts:"盘点总负债",net:"净资产"});
    };
    for(const el of page.querySelectorAll('.inventory-item input'))el.onchange=()=>attempt(totals);
    totals();
    page.querySelector('#inventory-preview').onclick=()=>attempt(()=>{
      if(!page.querySelectorAll('[data-inventory-row]').length)throw new Error("请至少添加一项资产或负债");
      if(!Array.from(page.querySelectorAll('input,select')).every(el=>el.reportValidity()))return;
      const data=structuredClone(collect()),book=by(state.books,data.book_id);
      if(!book)throw new Error("请先新建并选择家庭账本");
      const assets=data.items.reduce((sum,r)=>sum+r.value,0),debts=data.items.reduce((sum,r)=>sum+r.debt,0);
      openForm("确认导入家庭盘点",'<p>关联账本 '+h(book.name)+' · '+h(data.day)+'</p>'+metrics({assets,debts,net:assets-debts},{assets:"总资产",debts:"总负债",net:"净资产"})+
        '<p>共 '+data.items.length+' 项，将创建家庭账户、资产与借贷记录。每个账本可初始化一次，请核对是否包含已登记的资产。</p>',async(_,send)=>{
          await send(data);draft={day:"",items:[]};await refresh();render();
        },"确认导入");
    });
  }
  return {view,mount};
})();
