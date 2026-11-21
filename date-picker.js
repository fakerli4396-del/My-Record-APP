"use strict";
const DatePicker=(()=>{
  const weekdays=["一","二","三","四","五","六","日"];
  let panel,trigger,control,period,mode;

  function monthGrid(month,cell,fill=false){
    const first=new Date(month+"-01T12:00:00");
    const offset=(first.getDay()+6)%7;
    const end=lastDay(month);
    let result=weekdays.map((day,index)=>'<span class="weekday'+(index>=5?" weekend":"")+'">'+day+'</span>').join("");
    if(!fill)result+="<span></span>".repeat(offset);
    for(let i=fill?-offset:0;i<(fill?Math.ceil((offset+end)/7)*7-offset:end);i++){
      const date=new Date(first);
      date.setDate(1+i);
      const key=localDate(date);
      result+=cell(key,date.getDate(),i<0||i>=end);
    }
    return result;
  }
  function lastDay(month){
    const date=new Date(month+"-01T12:00:00");
    date.setMonth(date.getMonth()+1,0);
    return date.getDate();
  }
  function step(delta){
    const year=Number(period.slice(0,4)),month=Number(period.slice(5));
    const serial=(year-1)*12+month-1+delta*(mode==="year"?12:1);
    if(serial<0||serial>=9999*12)return;
    period=String(Math.floor(serial/12)+1).padStart(4,"0")+"-"+pad(serial%12+1);
    render("step");
  }
  function canChoose(value){
    const yearField=control.type==="number";
    const min=control.min,max=control.max;
    if(!yearField&&!/^(?!0000)\d{4}-\d{2}/.test(value))return false;
    return (!min||(yearField?Number(value)>=Number(min):value>=min))&&
      (!max||(yearField?Number(value)<=Number(max):value<=max));
  }
  function choice(value,label,extra="",outside=false){
    return '<button type="button" class="picker-choice'+extra+'" data-date-value="'+h(value)+'"'+
      (outside?' tabindex="-1" disabled':"")+'>'+h(label)+'</button>';
  }
  function render(focus){
    const year=Number(period.slice(0,4)),month=Number(period.slice(5));
    const unit=mode==="year"?"一年":"一个月";
    const controls='<div class="picker-top"><button type="button" data-step="-1" aria-label="上'+unit+'">‹</button>'+
      '<button type="button" data-mode="year" aria-pressed="'+(mode==="year")+'">'+year+'年</button>'+
      (control.type==="number"?"":'<button type="button" data-mode="month" aria-pressed="'+(mode==="month")+'">'+month+'月</button>')+
      '<button type="button" data-step="1" aria-label="下'+unit+'">›</button></div>';
    let grid="";
    if(mode==="year"){
      const first=Math.max(1,Math.min(9988,year-5));
      grid=Array.from({length:12},(_,i)=>{
        const y=first+i,value=String(y);
        return choice(value,y+"年",y===year?" is-selected":"",control.type==="number"&&!canChoose(value));
      }).join("");
    }else if(mode==="month"){
      grid=Array.from({length:12},(_,i)=>{
        const value=period.slice(0,4)+"-"+pad(i+1);
        return choice(value,(i+1)+"月",value===period?" is-selected":"",control.type==="month"&&!canChoose(value));
      }).join("");
    }else{
      grid=monthGrid(period,(value,day,outside)=>choice(value,day,(outside?" is-outside":"")+
        (value===today()?" is-today":"")+(value===control.value?" is-selected":""),!canChoose(value)),true);
    }
    const todayValue=control.type==="date"?today():control.type==="month"?thisMonth():today().slice(0,4);
    panel.innerHTML=controls+'<div class="picker-grid '+(mode==="date"?"picker-days":"picker-periods")+'">'+grid+'</div>'+
      '<div class="toolbar"><button type="button" data-today="'+todayValue+'"'+(!canChoose(todayValue)?" disabled":"")+'>'+
      (control.type==="date"?"今天":control.type==="month"?"本月":"今年")+'</button>'+
      (!control.required&&!control.dataset.calendarMonth?'<button type="button" data-clear>清空</button>':"")+
      '<button type="button" data-cancel>关闭</button></div>';
    const target=focus==="step"?panel.querySelector('[data-step="'+panel.dataset.lastStep+'"]'):
      panel.querySelector(".is-selected:not([disabled]),.is-today:not([disabled])");
    (target||panel.querySelector("[data-mode]")).focus();
  }
  function dismiss(restore=true){
    if(!panel)return;
    panel.remove();panel=null;
    trigger.setAttribute("aria-expanded","false");
    if(restore&&trigger.isConnected)trigger.focus();
  }
  function commit(value){
    const input=control;
    dismiss();
    input.value=value;
    input.dispatchEvent(new Event("input",{bubbles:true}));
    input.dispatchEvent(new Event("change",{bubbles:true}));
  }
  function open(button){
    dismiss(false);
    trigger=button;
    control=button.previousElementSibling;
    if(control.disabled||control.readOnly)return;
    const value=control.value;
    period=control.type==="number"&&Number(value)>0&&Number(value)<10000?String(value).padStart(4,"0")+"-"+thisMonth().slice(5):
      monthOf(value.slice(0,7));
    mode=control.type==="number"?"year":control.type;
    panel=document.createElement("section");
    panel.className="date-picker";
    panel.setAttribute("popover","manual");
    panel.setAttribute("role","dialog");
    panel.setAttribute("aria-label","日期选择");
    (button.closest("dialog")||document.body).append(panel);
    panel.onclick=event=>{
      const button=event.target.closest("button");
      if(!button)return;
      if(button.dataset.mode){
        mode=button.dataset.mode;
        render();
      }else if(button.dataset.step){
        panel.dataset.lastStep=button.dataset.step;
        step(Number(button.dataset.step));
      }else if(button.dataset.today){
        commit(button.dataset.today);
      }else if("clear" in button.dataset){
        commit("");
      }else if("cancel" in button.dataset){
        dismiss();
      }else if(button.dataset.dateValue){
        const value=button.dataset.dateValue;
        if(mode==="year"&&control.type!=="number"){
          period=value.padStart(4,"0")+period.slice(4);
          mode="month";
          render();
        }else if(mode==="month"&&control.type==="date"){
          period=value;
          mode="date";
          render();
        }else{
          commit(value);
        }
      }
    };
    trigger.setAttribute("aria-expanded","true");
    panel.showPopover();
    render();
  }
  document.addEventListener("click",event=>{
    const button=event.target.closest("[data-date-picker]");
    if(button){
      if(panel&&button===trigger)dismiss();
      else open(button);
    }else if(panel&&!event.composedPath().includes(panel)){
      dismiss(false);
    }
  });
  document.addEventListener("keydown",event=>{
    if(panel&&event.target.closest(".picker-top")&&["ArrowLeft","ArrowRight"].includes(event.key)){
      event.preventDefault();
      const delta=event.key==="ArrowLeft"?-1:1;
      panel.dataset.lastStep=String(delta);
      step(delta);
    }
    if(panel&&event.key==="Escape"){
      event.preventDefault();
      event.stopPropagation();
      dismiss();
    }
  },true);
  window.addEventListener("hashchange",()=>dismiss(false));
  return {monthGrid,lastDay};
})();
