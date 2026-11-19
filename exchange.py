"""Portable SQLite and Excel packages with guarded import."""
import sys
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from contextlib import closing
from uuid import uuid4
import backups
sys.path.insert(0,str(Path(__file__).parent / '.runtime-deps'))

TABLES=("settings","books","accounts","categories","positions","finance_events","bills",
        "asset_values","inventories","budgets","loan_plans","installments","credit_plans","credit_installments","forecast_items","image_imports")
LABELS=("设置","账本","账户","类目","资产借贷","业务记录","账单","资产估值","盘点","预算","借贷计划","月度计划","信用卡计划","信用卡月度计划","预计月度项目","图片导入记录")

def subset(source,target,book,owner):
    import app
    backups.snapshot(source,target)
    app.initialize(target)
    with app.connect(target) as db:
        import ledger
        original_balances={a["id"]:a["balance"] for a in ledger.snapshot(db)["accounts"]}
        # Keep all linked events and cash accounts to preserve opening balances and business history.
        bills=[dict(r) for r in db.execute("SELECT * FROM bills") if not book or r["book_id"]==int(book)]
        positions={r["id"] for r in db.execute("SELECT * FROM positions") if owner=="all" or r["owner"]==owner}
        if owner=="none": positions=set()
        event_ids={r["source_id"] for r in bills if r["source_type"]}
        positions|={r["position_id"] for r in db.execute("SELECT * FROM finance_events") if r["id"] in event_ids}
        inventories=[dict(r) for r in db.execute("SELECT * FROM inventories") if (not book or r["book_id"]==int(book)) and owner in ("all","family")]
        accounts=set()
        for row in inventories:
            for record in json.loads(row["records"]):
                (positions if record["kind"]=="position" else accounts).add(record["id"])
        events=[dict(r) for r in db.execute("SELECT * FROM finance_events") if r["position_id"] in positions]
        event_ids={r["id"] for r in events}
        bills=[r for r in db.execute("SELECT * FROM bills") if (not book or r["book_id"]==int(book)) or r["source_id"] in event_ids]
        # Opening balances for explicitly selected owners are exported as well.
        accounts|={r["id"] for r in db.execute("SELECT * FROM accounts") if owner=="all" or r["owner"]==owner}
        accounts|={r[k] for r in bills for k in ("account_id","to_account_id") if r[k]}
        accounts|={r["account_id"] for r in events if r["account_id"]}
        books={int(book)} if book else {r["id"] for r in db.execute("SELECT id FROM books")}
        books|={r["book_id"] for r in bills}|{r["book_id"] for r in events if r["book_id"]}
        plans=[r for r in db.execute("SELECT * FROM loan_plans") if r["position_id"] in positions]
        for record in db.execute("SELECT * FROM forecast_items").fetchall():
            if (book and record["book_id"] is not None and record["book_id"]!=int(book)) or (owner!="all" and record["owner"]!=owner):
                db.execute("DELETE FROM forecast_items WHERE id=?",(record["id"],))
        books|={r["book_id"] for r in db.execute("SELECT * FROM forecast_items")}
        books|={r["book_id"] for r in plans}
        books|={r["book_id"] for r in db.execute("SELECT * FROM credit_plans") if r["account_id"] in accounts}
        keep={"bills":{r["id"] for r in bills},"finance_events":event_ids,"positions":positions,"accounts":accounts,
              "books":books,"inventories":{r["id"] for r in inventories}}
        db.execute("DELETE FROM requests")
        for table,key,allowed in [("credit_installments","account_id",accounts),("credit_plans","account_id",accounts),("installments","position_id",positions),("loan_plans","position_id",positions),
                                  ("budgets","book_id",books),("asset_values","position_id",positions)]:
            for r in db.execute("SELECT rowid,"+key+" FROM "+table).fetchall():
                if r[1] not in allowed: db.execute("DELETE FROM "+table+" WHERE rowid=?",(r[0],))
        for table in ("bills","finance_events","asset_values","inventories","positions","accounts","books"):
            if table=="asset_values": continue
            for r in db.execute("SELECT id FROM "+table).fetchall():
                if r[0] not in keep[table]: db.execute("DELETE FROM "+table+" WHERE id=?",(r[0],))
        for account in ledger.snapshot(db)["accounts"]:
            delta=original_balances[account["id"]]-account["balance"]
            if delta: db.execute("UPDATE accounts SET opening=opening+? WHERE id=?",(delta,account["id"]))
    backups.validate(target)

def export(source,data):
    fmt=data.get("format")
    if fmt not in ("db","xlsx","xls"): raise ValueError("请选择 db、xlsx 或 xls 格式")
    owner=data.get("owner")
    if owner not in ("all","family","personal","none"): raise ValueError("资产范围无效")
    folder=backups.user_path(data.get("path"))
    if not folder.is_dir(): raise ValueError("导出目录不存在")
    name="MyRecord-"+uuid4().hex[:12]+"."+fmt
    with tempfile.TemporaryDirectory(dir=folder) as work:
        dbfile=Path(work)/"package.db"
        subset(source,dbfile,data.get("book"),owner)
        staged=Path(work)/name
        if fmt=="db": os.replace(dbfile,staged)
        else:
            try:
                if fmt=="xlsx":
                    import openpyxl
                    wb=openpyxl.Workbook();wb.remove(wb.active)
                else:
                    import xlwt
                    wb=xlwt.Workbook()
            except ImportError as e:
                raise ValueError("请先运行 python -m pip install -r requirements.txt 安装表格支持") from e
            with closing(backups.readonly(dbfile)) as db:
                for table,label in zip(TABLES,LABELS):
                    sheet=wb.create_sheet(label) if fmt=="xlsx" else wb.add_sheet(label)
                    columns=[r[1] for r in db.execute("PRAGMA table_info("+table+")")]
                    rows=[columns]+[list(r) for r in db.execute("SELECT * FROM "+table)]
                    if fmt=="xls" and len(rows)>65536: raise ValueError("xls最多65535条数据，请选择xlsx")
                    for i,row in enumerate(rows):
                        for j,value in enumerate(row):
                            if isinstance(value,str) and len(value)>32767: raise ValueError("单元格内容过长，请导出db")
                            if fmt=="xlsx":
                                cell=sheet.cell(i+1,j+1,value)
                                if isinstance(value,str): cell.data_type="s"
                            else: sheet.write(i,j,value)
                    if fmt=="xlsx":
                        sheet.freeze_panes="A2";sheet.auto_filter.ref=sheet.dimensions
            instructions=[
                ["My Record 数据包","由本应用导出，支持原结构导入"],
                ["金额单位","所有金额列以整数分保存，100表示1元"],
                ["文件结构","请保留所有工作表、列名和编号关联"],
                ["导入方式","预览确认后替换当前全部数据，并自动备份原数据"],
                ["范围","关联的资金账户及业务资料随所选账本一并保留"]]
            sheet=wb.create_sheet("说明") if fmt=="xlsx" else wb.add_sheet("说明")
            for i,row in enumerate(instructions):
                for j,value in enumerate(row):
                    if fmt=="xlsx":sheet.cell(i+1,j+1,value)
                    else:sheet.write(i,j,value)
            wb.save(str(staged))
        os.replace(staged,folder/name)
    return {"path":str(folder/name)}

def workbook_db(source,target):
    import app
    try:
        if source.suffix.lower()==".xlsx":
            import openpyxl
            with source.open("rb") as handle:
                wb=openpyxl.load_workbook(handle,read_only=True,data_only=False)
                sheets={s.title:[list(row) for row in s.iter_rows(values_only=True)] for s in wb}
                wb.close()
        elif source.suffix.lower()==".xls":
            import xlrd
            wb=xlrd.open_workbook(source)
            sheets={s.name:[s.row_values(i) for i in range(s.nrows)] for s in wb.sheets()}
        else: raise ValueError("请选择db、xlsx或xls文件")
        app.initialize(target)
        with app.connect(target) as db:
            db.execute("PRAGMA defer_foreign_keys=ON")
            for table in reversed(TABLES): db.execute("DELETE FROM "+table)
            for table,label in zip(TABLES,LABELS):
                rows=sheets.get(label)
                if not rows:
                    if table in ("budgets","loan_plans","installments","credit_plans","credit_installments","forecast_items","image_imports","inventories"):continue
                    raise ValueError("表格缺少工作表："+label+"，请使用本应用导出的文件")
                columns=[r[1] for r in db.execute("PRAGMA table_info("+table+")")]
                if not set(rows[0]).issubset(columns) or len(rows[0])!=len(set(rows[0])): raise ValueError("工作表列名不匹配："+label)
                columns=rows[0]
                required_text={r[1] for r in db.execute("PRAGMA table_info("+table+")") if r[2]=="TEXT" and r[3]}
                numeric={r[1] for r in db.execute("PRAGMA table_info("+table+")") if r[2]=="INTEGER"}
                for row in rows[1:]:
                    if all(v is None or v=="" for v in row): continue
                    values=[]
                    for c,v in zip(columns,row):
                        if c in required_text and v is None: v=""
                        if c in numeric:
                            if v in (None,""): v=None
                            elif isinstance(v,bool) or not isinstance(v,(int,float)) or int(v)!=v: raise ValueError("整数金额或编号无效："+label)
                            else: v=int(v)
                        values.append(v if v!="" or c not in ("due","purchase_day","source_type","source_id") else None)
                    db.execute("INSERT INTO "+table+"("+",".join(columns)+") VALUES ("+",".join("?" for _ in columns)+")",values)
        backups.upgrade_copy(target)
        backups.validate(target)
    except ImportError as e: raise ValueError("请安装 requirements.txt 中的表格依赖") from e
    except (sqlite3.Error,KeyError,TypeError) as e: raise ValueError("表格数据或关联无效") from e
    except ValueError: raise
    except Exception as e: raise ValueError("无法读取表格，请使用本应用导出的有效文件") from e

def incoming(database,data,restore=False):
    source=backups.user_path(data.get("path"));backups.check_source(database,source)
    if source.stat().st_size>100*1024*1024: raise ValueError("导入文件不能超过100MB")
    with tempfile.TemporaryDirectory(dir=database.parent) as work:
        copied=Path(work)/("source"+source.suffix.lower())
        digest=backups.copy_and_hash(source,copied)
        if restore and digest!=data.get("fingerprint"): raise ValueError("文件已变化，请重新预览")
        staged=Path(work)/"incoming.db"
        if source.suffix.lower()==".db": backups.snapshot(copied,staged)
        else: workbook_db(copied,staged)
        info=backups.validate(staged)
        if restore:
            preview=backups.preview(database,staged)
            return backups.restore(database,staged,preview["fingerprint"])
        return dict(info,fingerprint=digest)

def upload(database,data):
    import base64
    suffix=Path(str(data.get("name",""))).suffix.lower()
    if suffix not in (".db",".xls",".xlsx"):raise ValueError("请选择.db、.xls或.xlsx文件")
    try:raw=base64.b64decode(data.get("content",""),validate=True)
    except ValueError as e:raise ValueError("文件内容无效") from e
    if not raw or len(raw)>10*1024*1024:raise ValueError("上传文件应在10MB以内，更大文件请填写完整路径")
    folder=database.parent/"import-staging";folder.mkdir(exist_ok=True)
    target=folder/(uuid4().hex+suffix)
    target.write_bytes(raw)
    try:return dict(incoming(database,{"path":str(target)}),path=str(target))
    except Exception:
        target.unlink(missing_ok=True)
        raise
