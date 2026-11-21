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
from datetime import date, timedelta

def ensure(db):
    db.execute("""CREATE TABLE IF NOT EXISTS forecast_items(
      id INTEGER PRIMARY KEY, kind TEXT NOT NULL, owner TEXT NOT NULL,
      book_id INTEGER REFERENCES books(id), name TEXT NOT NULL,
      year INTEGER NOT NULL, annual_rate TEXT NOT NULL, months TEXT NOT NULL)""")
    if not any(row[1]=="paid_months" for row in db.execute("PRAGMA table_info(forecast_items)")):
        db.execute("ALTER TABLE forecast_items ADD COLUMN paid_months TEXT NOT NULL DEFAULT '[]'")
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

def group_rows(words):
    groups=[]
    for word in sorted(words,key=lambda w:(w["y"]+w["h"]/2,w["x"])):
        center=word["y"]+word["h"]/2
        punctuation=word["text"] in {".", "·", "。", ",", "，", "．"}
        group=next((g for g in groups if abs(g["y"]-center)<max(6,word["h"]*.6)
                    or (punctuation and word["h"]<g["height"]*.55
                        and abs(g["bottom"]-word["y"]-word["h"])<g["height"]*.22)),None)
        if group is None:
            group={"y":center,"height":word["h"],"bottom":word["y"]+word["h"],"words":[]}
            groups.append(group)
        group["words"].append(word)
    return groups


ASSET_NAME_CORRECTIONS = {"葆芬吹风机":"徕芬吹风机", "莱芬吹风机":"徕芬吹风机"}


def asset_price(line, numeric, row):
    """Read the first currency field, keeping separated thousands and cents together."""
    words=sorted(line,key=lambda word:word["x"])
    anchor=None
    fragments=[]
    edge=0
    for word in words:
        token=re.sub(r"\s+","",unicodedata.normalize("NFKC",word["text"])).replace("·",".").replace("。",".")
        if anchor is None:
            if "¥" not in token:
                continue
            if re.search(r"日均|消耗|/天",token.split("¥",1)[0]):
                return None,False
            anchor=word
            token=token.split("¥",1)[1]
        elif word["x"]-edge>row["height"]:
            break
        match=re.match(r"^[0-9,.]+",token)
        if match:
            if match.end()<len(token) and token[match.end():].startswith("天"):
                break
            fragments.append(match[0])
        elif token:
            break
        edge=word["x"]+word["w"]
    if anchor is None:
        return None,False
    if re.search(r"日均|日消耗|/天", "".join(w["text"] for w in words if w["x"]<anchor["x"])):
        return None,False
    pattern=r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?"
    raw="".join(fragments)
    chinese=money(raw) if re.fullmatch(pattern,raw) else None
    for word in numeric:
        token=unicodedata.normalize("NFKC",word["text"]).lstrip("¥")
        if (abs(word["y"]+word["h"]/2-row["y"])>row["height"]*.45 or
                abs(word["x"]-anchor["x"])>anchor["w"]+row["height"]*.8 or
                not re.fullmatch(pattern,token) or "." not in token):
            continue
        english=money(token)
        if english==chinese:
            return chinese,True
        if chinese is None or ("," in token and len(raw.split(".")[0].replace(",",""))==1):
            return english,True
        # Prefer a complete localized reading over a suffix clipped by the second pass.
        if raw.replace(",","").endswith(token.replace(",","")):
            continue
        if "," in raw and "." in raw and raw.split(".")[0].replace(",","")==token.split(".")[0].replace(",",""):
            return None,True
    return chinese,True


def parse_assets(words,numeric=None):
    rows=group_rows(words)
    numeric=numeric or []
    items=[]
    last_price_y=-1
    for index,row in enumerate(rows):
        words=sorted(row["words"],key=lambda word:word["x"])
        price,has_price=asset_price(words,numeric,row)
        if not has_price:
            continue
        text=" ".join(word["text"] for word in words)
        candidates=rows[max(0,index-3):index]
        for previous in reversed(candidates):
            if previous["y"]<=last_price_y:
                break
            label="".join(word["text"] for word in sorted(previous["words"],key=lambda word:word["x"]))
            if re.search(r"日均|日消耗|我的资产|默认排序|全部|已过保|已持有|在役|退役|[¥￥]|^\d+天",label):
                continue
            label=clean_name(re.sub(r"\s*(?:已持有)?\d+\s*天.*$","",label))
            if not label:
                continue
            label=ASSET_NAME_CORRECTIONS.get(label,label)
            next_row=rows[index+1] if index+1<len(rows) else {"words":[]}
            nearby=text+" "+" ".join(word["text"] for word in previous["words"]+next_row["words"])
            holding=re.search(r"(\d{1,5})\s*天",nearby)
            purchase_day=""
            if holding and 1<=int(holding[1])<=36500:
                purchase_day=(date.today()-timedelta(days=int(holding[1])-1)).isoformat()
            item={"name":label,"purchase_price":price,"purchase_day":purchase_day}
            if item not in items:
                items.append(item)
            break
        last_price_y=row["y"]
    return {"items":items,"warnings":["请核对名称、首购价和购买日期。金额不确定的项目保留空白。截图中的持有天数按今天倒推，日期可以修改。估值默认使用首购价，请按实际情况调整。"]}


def icon_thumbnail(source):
    if not isinstance(source,str) or len(source)>1_400_000:
        raise ValueError("图标图片须小于 1 MB")
    from PIL import Image, ImageOps
    try:
        raw=base64.b64decode(source,validate=True)
        if len(raw)>1024*1024:
            raise ValueError("图标图片须小于 1 MB")
        with Image.open(io.BytesIO(raw)) as original:
            if original.format not in ("PNG","JPEG","WEBP") or original.width*original.height>20_000_000:
                raise ValueError("请选择尺寸合适的 PNG、JPG 或 WebP 图片")
            icon=ImageOps.exif_transpose(original).convert("RGBA")
            icon.thumbnail((64,64),Image.Resampling.LANCZOS)
            result=io.BytesIO()
            icon.quantize(colors=128).save(result,format="PNG",optimize=True)
        return base64.b64encode(result.getvalue()).decode("ascii")
    except (OSError,ValueError,Image.DecompressionBombError) as error:
        raise ValueError("无法读取图标，请选择小于 1 MB 的 PNG、JPG 或 WebP 图片") from error


def save_assets(db,data):
    import ledger
    owner=ledger.one_of(data.get("owner"),("family","personal"))
    items=data.get("items")
    if not isinstance(items,list) or not 1<=len(items)<=100:
        raise ValueError("请确认 1–100 个资产")
    if any(not isinstance(item,dict) for item in items):
        raise ValueError("资产项目格式无效")
    fingerprint=hashlib.sha256(json.dumps({"kind":"asset","owner":owner,"items":items},sort_keys=True).encode()).hexdigest()
    old=db.execute("SELECT id FROM image_imports WHERE fingerprint=?",(fingerprint,)).fetchone()
    if old:
        return old[0]
    for item in items:
        if not item.get("purchase_day") or item.get("purchase_price") is None:
            raise ValueError("请核对购买日期和首购价格")
        ledger.write_position(db,dict(item,id=None,kind="asset",owner=owner,day=date.today().isoformat(),
                                      name=ledger.name(clean_name(item.get("name")))))
    return db.execute("INSERT INTO image_imports(fingerprint) VALUES (?)",(fingerprint,)).lastrowid


def table_amounts(words, headers, spacing):
    cells = {month: [] for month, _ in headers}
    fragments = []
    for word in sorted(words, key=lambda w: w["x"]):
        token = unicodedata.normalize("NFKC", word["text"]).replace("·", ".").replace("。", ".").strip().lstrip("¥")
        if not re.fullmatch(r"[0-9.,]+", token):
            continue
        previous = fragments[-1] if fragments else None
        if (previous and re.fullmatch(r"[0-9,]+", previous["text"]) and
                re.fullmatch(r"\.[0-9]{0,2}", token) and
                -word["h"]*.35 <= word["x"]-previous["end"] <= word["h"]*.65):
            previous["text"] += token
            previous["end"] = word["x"]+word["w"]
        elif (previous and previous["text"].endswith(".") and re.fullmatch(r"[0-9]{1,2}", token)
                and -word["h"]*.35 <= word["x"]-previous["end"] <= word["h"]*.65):
            previous["text"] += token
            previous["end"] = word["x"]+word["w"]
        else:
            fragments.append(dict(text=token, center=word["x"]+word["w"]/2, end=word["x"]+word["w"]))
    for fragment in fragments:
        month, x = min(headers, key=lambda header: abs(header[1]-fragment["center"]))
        if abs(x-fragment["center"]) <= spacing*.5:
            cells[month].append(fragment["text"])
    return cells


def reconcile_cell(chinese, english):
    def parse_parts(parts):
        candidate = "".join(parts)
        if not re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?", candidate):
            return "", None
        return candidate.replace(",", ""), money(candidate)

    left, left_value = parse_parts(chinese)
    right, right_value = parse_parts(english)
    if left_value is None: return right_value
    if right_value is None or right_value == left_value: return left_value
    if "." in left or "." in right:
        if left.startswith(right+"."): return left_value
        if right.startswith(left+"."): return right_value
    if len(left)>len(right) and len(right)>=2 and re.search(".*".join(map(re.escape,right)), left):
        return left_value
    if len(right)>len(left) and len(left)>=2 and re.search(".*".join(map(re.escape,left)), right):
        return right_value
    # OCR engines can disagree on a digit. Leave it available for review.
    return None


def parse(words, numeric=None, name_words=None):
    numeric=numeric or []
    groups=group_rows(words)
    headers=[]
    for group in groups:
        line=sorted(group["words"],key=lambda w:w["x"])
        text="";positions=[]
        for w in line:
            text+=w["text"];positions.extend([w["x"]+w["w"]/2]*len(w["text"]))
        matches=list(re.finditer(r"(?<![0-9])(1[0-2]|[1-9])月",text))
        if len(matches)>=2:
            columns=text[:matches[0].start()]
            total_only="全年合计" in columns and "本金" not in columns
            headers=[(int(m.group(1)),positions[m.start()]) for m in matches];header_y=group["y"];break
    if not headers:
        return {"items":[],"warnings":["未找到月份表头，请使用包含月份和完整数据行的清晰截图"]}
    spacing=min(b[1]-a[1] for a,b in zip(headers,headers[1:]))
    items=[]
    for group in groups:
        if group["y"]<=header_y+5: continue
        line=sorted(group["words"],key=lambda w:w["x"])
        values=[None]*12;left=[];rate="";left_words=[]
        cutoff=headers[0][1]-spacing*.5
        numeric_line=[w for w in numeric if abs(w["y"]+w["h"]/2-group["y"])<max(8,w["h"]*.65)]
        # Keep the entire Chinese name, even when English OCR overlaps part of it.
        left_line=[w for w in line if w["x"]+w["w"]/2<cutoff]
        left_words=[w["text"] for w in left_line if re.search(r"[\u4e00-\u9fff]",w["text"]) or not any(
            abs((w["x"]+w["w"]/2)-(n["x"]+n["w"]/2))<(w["w"]+n["w"])/2
            for n in numeric_line)]
        left_words += [n["text"] for n in sorted(numeric_line,key=lambda n:n["x"])
                       if n["x"]+n["w"]/2<cutoff and not any(
                           re.search(r"[\u4e00-\u9fff]",w["text"]) and
                           w["x"]<=n["x"]+n["w"]/2<=w["x"]+w["w"] for w in left_line)]
        cells=table_amounts(line,headers,spacing)
        numeric_cells=table_amounts(numeric_line,headers,spacing)
        review_line=[w for w in (name_words or []) if abs(w["y"]+w["h"]/2-group["y"])<max(6,w["h"]*.5)]
        review_cells=table_amounts(review_line,headers,spacing)
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
            values[month-1]=reconcile_cell(parts,numeric_cells[month])
        name=clean_name(name)
        if name_words:
            alternate="".join(w["text"] for w in sorted(name_words,key=lambda w:w["x"])
                              if abs(w["y"]+w["h"]/2-group["y"])<max(6,w["h"]*.5)
                              and re.search(r"[\u4e00-\u9fff]",w["text"]))
            alternate=clean_name(alternate)
            if alternate and len(alternate)>len(name) and (not name or name in alternate):
                name=alternate
        if not name or any(s in name for s in ("合计","总计","年支出","年收入")):continue
        if not any(cells.values()) and not any(numeric_cells.values()) and not any(review_cells.values()) and not left:continue
        principal=left[-1] if left and not total_only else None
        if any(r["name"]==name and r["principal"]==principal and r["months"]==values for r in items):
            continue
        items.append({"name":name,"principal":principal,"annual_rate":rate,
                      "months":values,"mode":"loan" if principal is not None else "plan"})
    return {"items":items,"warnings":["请逐行核对识别结果。空白月份保持待确认，缺少本金可补充，或仅保存月度计划。"]}

def read_ocr(image,work,asset):
    from PIL import Image
    scale=min(2,2200/image.width,13200/image.height)
    tile_height=max(1,int(2200/scale))
    if not asset:
        scale=min(2,2500/max(image.size))
        tile_height=image.height
    overlap=round(80/scale)
    words,numeric,lines,review_words=[],[],[],[]
    for top in range(0,image.height,tile_height):
        bottom=min(top+tile_height,image.height)
        crop_top=max(0,top-overlap)
        crop=image.crop((0,crop_top,image.width,min(image.height,bottom+overlap)))
        crop=crop.resize((max(1,round(crop.width*scale)),max(1,round(crop.height*scale))),Image.Resampling.LANCZOS)
        source=Path(work)/"input.png"
        def scan(bitmap):
            bitmap.save(source)
            result=subprocess.run(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",
                str(Path(__file__).with_name("ocr.ps1")),str(source)],capture_output=True,timeout=25,
                creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise ValueError("本地识别失败，请确认Windows中文OCR语言已安装："+result.stderr.decode("utf8",errors="replace")[-250:])
            return json.loads(result.stdout.decode("utf-8-sig"))

        page=scan(crop)
        if not asset:
            from PIL import ImageOps
            review=scan(ImageOps.autocontrast(crop.convert("L")).convert("RGB"))
            review_words.extend(review["words"])
        lines.append(page["text"])
        for field,target in (("words",words),("numeric",numeric)):
            for word in page.get(field,[]):
                word["y"]+=crop_top*scale
                if top*scale<=word["y"]+word["h"]/2<bottom*scale:
                    target.append(word)
    return {"words":words,"numeric":numeric,"review_words":review_words,"text":"\n".join(lines)}


def recognize(data):
    try:
        raw=base64.b64decode(data.get("content",""),validate=True)
        if not raw or len(raw)>10*1024*1024: raise ValueError("图片大小应在10MB以内")
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as original:
            if original.width*original.height>30000000:raise ValueError("图片尺寸过大")
            image=original.convert("RGB")
        with tempfile.TemporaryDirectory() as work:
            recognized=read_ocr(image,work,data.get("kind")=="asset")
        parsed=(parse_assets(recognized["words"],recognized.get("numeric")) if data.get("kind")=="asset"
                else parse(recognized["words"],recognized.get("numeric"),recognized.get("review_words")))
        if data.get("kind")=="lend":
            has_principal = any(term in recognized["text"].replace(" ","") for term in ("借出本金","剩余本金","应收本金"))
            for item in parsed["items"]:
                item["mode"] = "loan" if has_principal else "plan"
            parsed["warnings"].append("借出看板按每行 12 个月应收金额自动计算剩余本金，请核对各月金额。")
        return dict(parsed,text=recognized["text"])
    except ValueError:raise
    except Exception as e:raise ValueError("无法识别图片，请选择清晰的PNG或JPG表格图片") from e

def apply(db,data):
    import ledger
    import planning
    owner=ledger.one_of(data.get("owner"),("family","personal"))
    kind=ledger.one_of(data.get("kind"),("borrow","lend"))
    book_id=None
    year=data.get("year");day=ledger.day(data.get("day"))
    if type(year)!=int or not 1<=year<=9999:raise ValueError("年份无效")
    items=data.get("items")
    if not isinstance(items,list) or not 1<=len(items)<=100:raise ValueError("请确认1至100行数据")
    fingerprint=hashlib.sha256(json.dumps(dict(book_id=book_id,owner=owner,kind=kind,year=year,day=day,items=items),sort_keys=True).encode()).hexdigest()
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
        if item.get("mode")=="loan" and kind=="lend":
            ledger.write_position(db,dict(name=label,kind=kind,owner=owner,day=day,year=year,
                                          annual_rate=rate,months=months))
        elif item.get("mode")=="loan":
            principal=ledger.cents(item.get("principal"))
            key=ledger.write_position(db,dict(name=label,kind=kind,owner=owner,day=day,principal=principal,opening_only=True))
            planning.save(db,dict(action="loan_plan",position_id=key,book_id=book_id,year=year,annual_rate=rate,months=months))
        elif item.get("mode")=="plan":
            db.execute("INSERT INTO forecast_items(kind,owner,book_id,name,year,annual_rate,months) VALUES (?,?,?,?,?,?,?)",
                       (kind,owner,book_id,label,year,rate,json.dumps(months)))
        else:raise ValueError("请选择登记本金或仅月度计划")
    return db.execute("INSERT INTO image_imports(fingerprint) VALUES (?)",(fingerprint,)).lastrowid
