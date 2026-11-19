"use strict";
const ImageImportUI=(()=>{
  const fileData=file=>new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(",")[1]);reader.onerror=()=>reject(new Error("无法读取文件"));reader.readAsDataURL(file);});
  function start(owner,kind){
    const books=state.books.filter(b=>!b.archived);
    if(!books.length){bookForm();return;}
    const form=openForm("图片识别导入",field("所属账本",select("book_id",books.map(b=>[b.id,b.name]),state.current_book))+
      field("归属",select("owner",Object.entries(owners),owner))+field("看板",select("kind",[["borrow","负债 / 应还"],["lend","借款 / 应收"]],kind))+
      field("表格年份",input("year",new Date().getFullYear(),'type="number" min="1" max="9999" required'))+
      field("本金登记日期",input("day",today(),'type="date" required'))+
      field("上传表格图片",'<input id="ocr-file" type="file" accept="image/png,image/jpeg,image/webp" required>')+
      '<p>图片保留项目名称、月份表头和金额。识别后可逐行补充与修改，确认后导入。</p>',async d=>{
        const file=form.querySelector("#ocr-file").files[0];
        if(!file||file.size>10*1024*1024)throw new Error("请选择10MB以内的图片");
        const result=await api("/api/files",{action:"recognize_image",kind:d.kind,content:await fileData(file)});
        setTimeout(()=>review(d,result),0);
      },"开始识别");
  }
  function review(context,result){
    const entries=result.items||[];
    const form=openForm("核对识别结果",'<p>'+h((result.warnings||[]).join(" "))+'</p><details><summary>查看识别原文</summary><pre>'+h(result.text||"")+'</pre></details><div id="recognized-rows">'+
      entries.map((r,i)=>'<fieldset data-ocr-row="'+i+'"><legend>第 '+(i+1)+' 项</legend>'+
        field("项目名称",input("name",r.name,'required maxlength="80"'))+
        field("导入方式",select("mode",[["loan","登记借贷本金及计划"],["plan","仅月度计划，排除资产负债余额"]],r.mode))+
        field("剩余本金 / 借出本金（元，登记本金时必填）",input("principal",r.principal==null?"":r.principal/100,'type="number" min="0.01" step="0.01"'))+
        field("年化利率（%，选填）",input("annual_rate",r.annual_rate,'type="number" min="0" max="100" step="0.0001"'))+
        '<div class="ocr-months">'+r.months.map((v,m)=>field((m+1)+"月",input("m"+m,v==null?"":v/100,'type="number" min="0" step="0.01" placeholder="待确认"'))).join("")+'</div>'+
        '<button type="button" data-remove-ocr>移除此项</button></fieldset>').join("")+
      '</div><button type="button" id="add-ocr-row">补充一行</button>'+
      '<label class="checkline"><input type="checkbox" name="confirm_blank">将所有空白月份确认为0</label>'+
      '<p>缺少本金时可补填，或选择仅月度计划。工资等预计收入请选择仅月度计划。</p>',async(_,send)=>{
        const nodes=Array.from(form.querySelectorAll("[data-ocr-row]"));
        if(!nodes.length)throw new Error("请至少确认一行数据");
        const items=nodes.map(node=>{
          const value=n=>node.querySelector('[name="'+n+'"]').value;
          const months=Array.from({length:12},(_,i)=>{
            const v=value("m"+i);
            if(v===""){if(!form.elements.confirm_blank.checked)throw new Error("仍有空白月份，请补充或勾选确认为0");return 0;}
            return parseMoney(v,false,true);
          });
          return {name:value("name"),mode:value("mode"),annual_rate:value("annual_rate"),months,
            principal:value("mode")==="loan"?parseMoney(value("principal")):null};
        });
        await send({action:"image_import",book_id:Number(context.book_id),owner:context.owner,kind:context.kind,year:Number(context.year),day:context.day,items});
        await refresh();location.hash=assetURL(context.owner,context.kind)+"&book="+context.book_id+"&year="+context.year;render();
      },"确认导入");
    const wire=()=>{
      form.querySelectorAll('[data-remove-ocr]').forEach(b=>b.onclick=()=>b.closest('fieldset').remove());
      form.querySelectorAll('[data-ocr-row]').forEach(row=>{
        const mode=row.querySelector('[name=mode]'),principal=row.querySelector('[name=principal]');
        const update=()=>{principal.required=mode.value==="loan";principal.disabled=mode.value!=="loan";};
        mode.onchange=update;update();
      });
    };
    form.querySelector('#add-ocr-row').onclick=()=>{
      const empty={name:"",principal:null,annual_rate:"",mode:"plan",months:Array(12).fill(null)};

      // Reuse the same review row representation.

      const rows=Array.from(form.querySelectorAll('[data-ocr-row]')).map(row=>{
        const get=n=>row.querySelector('[name="'+n+'"]').value;
        return {name:get("name"),mode:get("mode"),principal:get("principal")?Math.round(Number(get("principal"))*100):null,annual_rate:get("annual_rate"),months:Array.from({length:12},(_,i)=>get("m"+i)===""?null:Math.round(Number(get("m"+i))*100))};
      });
      review(context,{...result,items:[...rows,empty]});
    };
    wire();
  }
  return {start};
})();
