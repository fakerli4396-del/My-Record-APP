"use strict";
const RecordReports = (() => {
  function summarize(list) {
    let income=0,expense=0;
    for (const b of list) {
      if (b.kind==="income") income+=b.amount;
      if (b.kind==="expense") expense+=b.amount;
    }
    return {income,expense,net:income-expense};
  }
  function filterBills(list,f) {
    const note=(f.note||"").trim().toLowerCase();
    return list.filter(b=>(!f.from||b.day>=f.from)&&(!f.to||b.day<=f.to)&&
      (!f.book||b.book_id===Number(f.book))&&(!f.kind||b.kind===f.kind)&&
      (!f.category||b.category_id===Number(f.category))&&
      (!f.account||[b.account_id,b.to_account_id].includes(Number(f.account)))&&
      (!note||b.note.toLowerCase().includes(note)));
  }
  function rankExpenses(list) {
    const values=new Map();
    for (const bill of list) {
      if (bill.kind==="expense") values.set(bill.category_id,(values.get(bill.category_id)||0)+bill.amount);
    }
    return [...values].sort((a,b)=>b[1]-a[1] || a[0]-b[0]);
  }
  return {summarize,filterBills,rankExpenses};
})();
if (typeof module !== "undefined") module.exports=RecordReports;
