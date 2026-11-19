"""Offline OCR and reviewable table extraction."""
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unicodedata
from decimal import Decimal, InvalidOperation

def ensure(db):
    db.execute("""CREATE TABLE IF NOT EXISTS forecast_items(
      id INTEGER PRIMARY KEY, kind TEXT NOT NULL, owner TEXT NOT NULL,
      book_id INTEGER NOT NULL REFERENCES books(id), name TEXT NOT NULL,
      year INTEGER NOT NULL, annual_rate TEXT NOT NULL, months TEXT NOT NULL)""")
    db.execute("CREATE TABLE IF NOT EXISTS image_imports(id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE)")

def clean_name(value):
    text=unicodedata.normalize("NFKC",str(value or "")).strip()
    text=re.sub(r"^[\s%％·.。:：,，;；\-—_]+|[\s%％·.。:：,，;；\-—_]+$","",text)
    if not re.search(r"[A-Za-z\u4e00-\u9fff]",text):
        return ""
    return text

def money(text):
    try:
        n=Decimal(text.replace(",","").replace("，","").replace("¥","").replace("￥",""))
        if n<0 or n.as_tuple().exponent < -2: return None
        return int(n*100)
    except (InvalidOperation,ValueError): return None

def parse(words, numeric=None):
    numeric=numeric or []
    groups=[]
    for word in sorted(words,key=lambda w:(w["y"]+w["h"]/2,w["x"])):
        center=word["y"]+word["h"]/2
        group=next((g for g in groups if abs(g["y"]-center)<max(6,word["h"]*.6)),None)
        if group is None: group={"y":center,"words":[]};groups.append(group)
        group["words"].append(word)
    headers=[]
    for group in groups:
        line=sorted(group["words"],key=lambda w:w["x"])
        text="";positions=[]
        for w in line:
            text+=w["text"];positions.extend([w["x"]+w["w"]/2]*len(w["text"]))
        matches=list(re.finditer(r"(?<![0-9])(1[0-2]|[1-9])月",text))
        if len(matches)>=2:
            headers=[(int(m.group(1)),positions[m.start()]) for m in matches];header_y=group["y"];break
    if not headers:
        return {"items":[],"warnings":["未找到月份表头，请使用包含月份和完整数据行的清晰截图"]}
    spacing=min(b[1]-a[1] for a,b in zip(headers,headers[1:]))
    items=[]
    for group in groups:
        if group["y"]<=header_y+5: continue
        line=sorted(group["words"],key=lambda w:w["x"])
        values=[None]*12;left=[];rate="";cells={m:[] for m,_ in headers};left_words=[]
        for w in line:
            text=w["text"].strip();cx=w["x"]+w["w"]/2
            if cx<headers[0][1]-spacing*.5:left_words.append(text)
            else:
                nearest=min(headers,key=lambda pair:abs(pair[1]-cx))
                if abs(nearest[1]-cx)<=spacing*.48:cells[nearest[0]].append(text)
        # English recognition supplies decimal amounts and rates, Chinese recognition retains labels.
        numeric_line=[w for w in numeric if abs(w["y"]+w["h"]/2-group["y"])<max(8,w["h"]*.65)]
        if numeric_line:
            left_words=[w["text"] for w in line if w["x"]+w["w"]/2<headers[0][1]-spacing*.5 and not any(
                abs((w["x"]+w["w"]/2)-(n["x"]+n["w"]/2))<(w["w"]+n["w"])/2 for n in numeric_line)]
            left_words += [n["text"] for n in sorted(numeric_line,key=lambda n:n["x"]) if n["x"]+n["w"]/2<headers[0][1]-spacing*.5]
            for month,x in headers:
                parts=[n["text"] for n in sorted(numeric_line,key=lambda n:n["x"]) if abs(n["x"]+n["w"]/2-x)<spacing*.48]
                if parts:cells[month]=parts
        left_text="".join(left_words).replace("．",".").replace("。",".").replace("·",".")
        rate_match=re.search(r"([0-9]+(?:\.[0-9]+)?)%",left_text)
        if rate_match:
            rate=rate_match.group(1);left_text=left_text[:rate_match.start()]+left_text[rate_match.end():]
        amounts=list(re.finditer(r"[0-9][0-9,]*(?:\.[0-9]+)?",left_text))
        for match in amounts:
            value=money(match.group())
            if value is not None:left.append(value)
        name=re.sub(r"[0-9][0-9,]*(?:\.[0-9]+)?","",left_text).strip(" %：:")
        for month,parts in cells.items():
            text="".join(parts).replace("．",".").replace("。",".").replace("·",".")
            values[month-1]=money(text)
        name=clean_name(name)
        if not name or any(s in name for s in ("合计","总计","年支出","年收入")):continue
        if not any(v is not None for v in values) and not left:continue
        if any(r["name"]==name and r["principal"]==(left[-1] if left else None) and r["months"]==values for r in items):
            continue
        items.append({"name":name,"principal":left[-1] if left else None,"annual_rate":rate,
                      "months":values,"mode":"loan" if left else "plan"})
    return {"items":items,"warnings":["请逐行核对识别结果。空白月份保持待确认，缺少本金可补充，或仅保存月度计划。"]}

def recognize(data):
    try:
        raw=base64.b64decode(data.get("content",""),validate=True)
        if not raw or len(raw)>10*1024*1024: raise ValueError("图片大小应在10MB以内")
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as original:
            if original.width*original.height>30000000:raise ValueError("图片尺寸过大")
            image=original.convert("RGB")
            scale=min(2,2500/max(image.size))
            if scale!=1:image=image.resize((int(image.width*scale),int(image.height*scale)))
        with tempfile.TemporaryDirectory() as work:
            source=Path(work)/"input.png";image.save(source)
            result=subprocess.run(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",
                str(Path(__file__).with_name("ocr.ps1")),str(source)],capture_output=True,timeout=90,
                creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:raise ValueError("本地识别失败，请确认Windows中文OCR语言已安装："+result.stderr.decode("utf8",errors="replace")[-250:])
            recognized=json.loads(result.stdout.decode("utf-8-sig"))
        parsed=parse(recognized["words"],recognized.get("numeric"))
        if data.get("kind")=="lend" and not any(term in recognized["text"].replace(" ","") for term in ("借出本金","剩余本金","应收本金")):
            for item in parsed["items"]:item["mode"]="plan"
            parsed["warnings"].append("借出图片左侧金额可能是全年合计，默认仅月度计划；如需登记应收资产，请选择登记本金并核对本金。")
        return dict(parsed,text=recognized["text"])
    except ValueError:raise
    except Exception as e:raise ValueError("无法识别图片，请选择清晰的PNG或JPG表格图片") from e

def apply(db,data):
    import ledger
    import planning
    book=ledger.find(db,"books",data.get("book_id"))
    if book["archived"]:raise ValueError("请选择使用中的账本")
    owner=ledger.one_of(data.get("owner"),("family","personal"))
    kind=ledger.one_of(data.get("kind"),("borrow","lend"))
    year=data.get("year");day=ledger.day(data.get("day"))
    if type(year)!=int or not 1<=year<=9999:raise ValueError("年份无效")
    items=data.get("items")
    if not isinstance(items,list) or not 1<=len(items)<=100:raise ValueError("请确认1至100行数据")
    fingerprint=hashlib.sha256(json.dumps({k:data[k] for k in ("book_id","owner","kind","year","day","items")},sort_keys=True).encode()).hexdigest()
    old=db.execute("SELECT id FROM image_imports WHERE fingerprint=?",(fingerprint,)).fetchone()
    if old:return old[0]
    seen=set()
    for item in items:
        label=ledger.name(clean_name(item.get("name")))
        if label in seen:
            raise ValueError("发现同名识别行，请核对并移除重复项后导入")
        seen.add(label)
        months=item.get("months")
        if not isinstance(months,list) or len(months)!=12 or any(v is None for v in months):
            raise ValueError("请确认所有空白月份，可填写0表示没有计划")
        months=[ledger.cents(v,0) for v in months]
        rate=str(item.get("annual_rate",""))
        if rate and (not re.fullmatch(r"[0-9]{1,3}(\.[0-9]{1,4})?",rate) or float(rate)>100):raise ValueError("年化利率无效")
        if item.get("mode")=="loan":
            principal=ledger.cents(item.get("principal"))
            key=ledger.write_position(db,dict(name=label,kind=kind,owner=owner,day=day,principal=principal,opening_only=True))
            planning.save(db,dict(action="loan_plan",position_id=key,book_id=book["id"],year=year,annual_rate=rate,months=months))
        elif item.get("mode")=="plan":
            db.execute("INSERT INTO forecast_items(kind,owner,book_id,name,year,annual_rate,months) VALUES (?,?,?,?,?,?,?)",
                       (kind,owner,book["id"],label,year,rate,json.dumps(months)))
        else:raise ValueError("请选择登记本金或仅月度计划")
    return db.execute("INSERT INTO image_imports(fingerprint) VALUES (?)",(fingerprint,)).lastrowid
