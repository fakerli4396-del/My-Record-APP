"use strict";
const assert=require("node:assert/strict");
const {test}=require("node:test");
const {summarize,filterBills,rankExpenses}=require("./reports");
const bill=(data)=>({day:"2026-11-14",book_id:1,kind:"expense",account_id:3,category_id:6,note:"",amount:20000,...data});
const list=[bill({note:"Grocery"}),bill({book_id:2,amount:15000,category_id:3}),
  bill({kind:"income",amount:100000,category_id:1}),bill({kind:"transfer",amount:100000,to_account_id:4,category_id:null}),
  bill({day:"2026-10-31",amount:5000,category_id:6})];
test("A02 and A06: summaries are traceable across books and months",()=>{
  const current=filterBills(list,{from:"2026-11-01",to:"2026-11-30"});
  assert.deepEqual(summarize(current),{income:100000,expense:35000,net:65000});
  assert.deepEqual(summarize(filterBills(current,{book:"1"})),{income:100000,expense:20000,net:80000});
  assert.deepEqual(rankExpenses(current),[[6,20000],[3,15000]]);
  assert.deepEqual(filterBills(current,{book:"1",kind:"expense",category:"6",note:"GROC"}),[list[0]]);
  assert.equal(summarize(filterBills(list,{from:"2026-10-01",to:"2026-10-31"})).expense,5000);
});
test("A04: recipient account filter includes transfers without changing income or spending",()=>{
  const rows=filterBills(list,{account:"4"});
  assert.deepEqual(rows,[list[3]]);
  assert.deepEqual(summarize(rows),{income:0,expense:0,net:0});
});
