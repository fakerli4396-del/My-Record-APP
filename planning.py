"""Book budgets and manually agreed repayment schedules."""
import re

def ensure(db):
    db.execute("""CREATE TABLE IF NOT EXISTS budgets(
      book_id INTEGER NOT NULL REFERENCES books(id), month TEXT NOT NULL, amount INTEGER NOT NULL,
      PRIMARY KEY(book_id,month))""")
    db.execute("""CREATE TABLE IF NOT EXISTS loan_plans(
      position_id INTEGER PRIMARY KEY REFERENCES positions(id), book_id INTEGER NOT NULL REFERENCES books(id),
      annual_rate TEXT NOT NULL DEFAULT '')""")
    db.execute("""CREATE TABLE IF NOT EXISTS installments(
      position_id INTEGER NOT NULL REFERENCES positions(id), month TEXT NOT NULL, amount INTEGER NOT NULL,
      PRIMARY KEY(position_id,month))""")

    db.execute("""CREATE TABLE IF NOT EXISTS credit_plans(
      account_id INTEGER PRIMARY KEY REFERENCES accounts(id), book_id INTEGER NOT NULL REFERENCES books(id),
      annual_rate TEXT NOT NULL DEFAULT '')""")
    db.execute("""CREATE TABLE IF NOT EXISTS credit_installments(
      account_id INTEGER NOT NULL REFERENCES accounts(id), month TEXT NOT NULL, amount INTEGER NOT NULL,
      PRIMARY KEY(account_id,month))""")

def rows(db,table):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone():
        return []
    return [dict(r) for r in db.execute("SELECT * FROM "+table)]

def month(value):
    if not isinstance(value,str) or not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])",value) or value[:4]=="0000":
        raise ValueError("月份无效")
    return value

def save(db,data):
    import ledger
    book=ledger.find(db,"books",data.get("book_id"))
    if book["archived"]: raise ValueError("账本已归档")
    if data["action"]=="budget":
        db.execute("INSERT OR REPLACE INTO budgets VALUES (?,?,?)",
                   (book["id"],month(data.get("month")),ledger.cents(data.get("amount"),0)))
        return book["id"]
    credit=data.get("account_id") is not None
    p=ledger.find(db,"accounts" if credit else "positions",data.get("account_id") if credit else data.get("position_id"))
    if credit:
        if p["account_type"]!="credit": raise ValueError("请选择信用卡")
    elif p["kind"] not in ("borrow","lend"): raise ValueError("请选择借入或借出")
    rate=str(data.get("annual_rate","")).strip()
    if rate and (not re.fullmatch(r"[0-9]{1,3}(\.[0-9]{1,4})?",rate) or float(rate)>100):
        raise ValueError("年化利率应为0至100之间的百分数")
    entries=data.get("months")
    if not isinstance(entries,list) or len(entries)!=12: raise ValueError("请填写全年12个月计划")
    year=data.get("year")
    if type(year)!=int or not 1<=year<=9999: raise ValueError("年份无效")
    table="credit_plans" if credit else "loan_plans"
    installments="credit_installments" if credit else "installments"
    db.execute("INSERT OR REPLACE INTO "+table+" VALUES (?,?,?)",(p["id"],book["id"],rate))
    for i,value in enumerate(entries):
        db.execute("INSERT OR REPLACE INTO "+installments+" VALUES (?,?,?)",
                   (p["id"],str(year).zfill(4)+"-"+str(i+1).zfill(2),ledger.cents(value,0)))
    return p["id"]
