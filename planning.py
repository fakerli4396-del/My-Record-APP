"""Book budgets and manually agreed repayment schedules."""
import re
from decimal import Decimal

def ensure(db):
    db.execute("""CREATE TABLE IF NOT EXISTS budgets(
      book_id INTEGER NOT NULL REFERENCES books(id), month TEXT NOT NULL, amount INTEGER NOT NULL,
      PRIMARY KEY(book_id,month))""")
    db.execute("""CREATE TABLE IF NOT EXISTS loan_plans(
      position_id INTEGER PRIMARY KEY REFERENCES positions(id), book_id INTEGER REFERENCES books(id),
      annual_rate TEXT NOT NULL DEFAULT '')""")
    db.execute("""CREATE TABLE IF NOT EXISTS installments(
      position_id INTEGER NOT NULL REFERENCES positions(id), month TEXT NOT NULL, amount INTEGER NOT NULL,
      PRIMARY KEY(position_id,month))""")

    db.execute("""CREATE TABLE IF NOT EXISTS credit_plans(
      account_id INTEGER PRIMARY KEY REFERENCES accounts(id), book_id INTEGER REFERENCES books(id),
      annual_rate TEXT NOT NULL DEFAULT '')""")
    db.execute("""CREATE TABLE IF NOT EXISTS credit_installments(
      account_id INTEGER NOT NULL REFERENCES accounts(id), month TEXT NOT NULL, amount INTEGER NOT NULL,
      PRIMARY KEY(account_id,month))""")

    for table, predicate in (
        ("loan_plans", "position_id IN (SELECT id FROM positions WHERE kind IN ('borrow','lend'))"),
        ("forecast_items", "kind IN ('borrow','lend')"),
        ("credit_plans", "1=1"),
    ):
        info=db.execute("PRAGMA table_info("+table+")").fetchall()
        if not any(row[1]=="book_id" and row[3] for row in info):
            continue
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        schema=db.execute("SELECT sql FROM sqlite_master WHERE name=?",(table,)).fetchone()[0]
        db.execute("ALTER TABLE "+table+" RENAME TO "+table+"_legacy")
        db.execute(schema.replace("book_id INTEGER NOT NULL","book_id INTEGER"))
        columns=",".join("CASE WHEN "+predicate+" THEN NULL ELSE book_id END" if row[1]=="book_id" else row[1] for row in info)
        db.execute("INSERT INTO "+table+" SELECT "+columns+" FROM "+table+"_legacy")
        db.execute("DROP TABLE "+table+"_legacy")
    if not any(r[1]=="paid" for r in db.execute("PRAGMA table_info(installments)")):
        db.execute("ALTER TABLE installments ADD COLUMN paid INTEGER NOT NULL DEFAULT 0")
    db.execute("UPDATE loan_plans SET book_id=NULL WHERE book_id IS NOT NULL AND position_id IN (SELECT id FROM positions WHERE kind IN ('borrow','lend'))")
    db.execute("UPDATE credit_plans SET book_id=NULL WHERE book_id IS NOT NULL")
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='forecast_items'").fetchone():
        db.execute("UPDATE forecast_items SET book_id=NULL WHERE book_id IS NOT NULL AND kind IN ('borrow','lend')")

def create_loan_schedule(db, key, data):
    import ledger
    principal=ledger.cents(data.get("principal"))
    interest=ledger.cents(data.get("total_interest"),0)
    terms=data.get("term_months")
    if type(terms) is not int or not 1<=terms<=600:
        raise ValueError("还款期数须为 1–600 个月")
    first=month(data.get("first_month"))
    start_year,start_month=map(int,first.split("-"))
    if first < data["day"][:7] or start_year+(start_month+terms-2)//12>9999:
        raise ValueError("首期还款月份须不早于登记月份，且计划须在有效年份内")
    total=ledger.cents(principal+interest)
    if data.get("monthly_payment") is not None:
        monthly=ledger.cents(data["monthly_payment"])
        last=total-monthly*(terms-1)
        if last<=0 or (terms==1 and monthly!=total):
            raise ValueError("每月应还与本金、总利息及期数不匹配，请核对")
        payments=[monthly]*(terms-1)+[last]
    else:
        monthly,remainder=divmod(total,terms)
        if not monthly:
            raise ValueError("总应还不足以分配到每一期，请减少期数")
        payments=[monthly+(index<remainder) for index in range(terms)]
    rate=format((Decimal(interest)*1200/(principal*terms)).quantize(Decimal("0.0001")).normalize(),"f")
    db.execute("INSERT INTO loan_plans(position_id,book_id,annual_rate) VALUES (?,NULL,?)",(key,rate))
    for index,amount in enumerate(payments):
        offset=start_month-1+index
        installment=f"{start_year+offset//12:04d}-{offset%12+1:02d}"
        db.execute("INSERT INTO installments(position_id,month,amount) VALUES (?,?,?)",
                   (key,installment,amount))

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
    if data["action"]=="budget":
        book=ledger.find(db,"books",data.get("book_id"))
        if book["archived"]: raise ValueError("账本已归档")
        db.execute("INSERT OR REPLACE INTO budgets VALUES (?,?,?)",
                   (book["id"],month(data.get("month")),ledger.cents(data.get("amount"),0)))
        return book["id"]
    credit=data.get("account_id") is not None
    p=ledger.find(db,"accounts" if credit else "positions",data.get("account_id") if credit else data.get("position_id"))
    if credit:
        if p["account_type"]!="credit": raise ValueError("请选择信用卡")
    elif p["kind"] not in ("borrow","lend"): raise ValueError("请选择借入或借出")
    rate=str(data.get("annual_rate","")).strip()
    if rate and (not re.fullmatch(r"[0-9]{1,7}(\.[0-9]{1,4})?",rate) or float(rate)>1200000):
        raise ValueError("年化利率无效")
    entries=data.get("months")
    if not isinstance(entries,list) or len(entries)!=12: raise ValueError("请填写全年12个月计划")
    year=data.get("year")
    if type(year)!=int or not 1<=year<=9999: raise ValueError("年份无效")
    table="credit_plans" if credit else "loan_plans"
    installments="credit_installments" if credit else "installments"
    db.execute("INSERT OR REPLACE INTO "+table+" VALUES (?,?,?)",(p["id"],None,rate))
    for i,value in enumerate(entries):
        columns="account_id" if credit else "position_id"
        db.execute("INSERT INTO "+installments+"("+columns+",month,amount) VALUES (?,?,?) "
                   "ON CONFLICT("+columns+",month) DO UPDATE SET amount=excluded.amount",
                   (p["id"],str(year).zfill(4)+"-"+str(i+1).zfill(2),ledger.cents(value,0)))
    return p["id"]
