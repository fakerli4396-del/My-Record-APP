"""SQLite tables and the shared rules for cash movement and reporting."""
from datetime import date
import re
import portfolio

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS accounts (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL,
 opening INTEGER NOT NULL, UNIQUE(owner, name)
);
CREATE TABLE IF NOT EXISTS categories (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
 parent_id INTEGER REFERENCES categories(id), enabled INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS category_name ON categories(kind, coalesce(parent_id, 0), name);
CREATE TABLE IF NOT EXISTS bills (
 id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL REFERENCES books(id),
 day TEXT NOT NULL, kind TEXT NOT NULL, amount INTEGER NOT NULL,
 account_id INTEGER NOT NULL REFERENCES accounts(id),
 to_account_id INTEGER REFERENCES accounts(id), category_id INTEGER REFERENCES categories(id),
 note TEXT NOT NULL DEFAULT '', source_type TEXT, source_id INTEGER,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS bills_day ON bills(day, book_id);
CREATE TABLE IF NOT EXISTS positions (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, owner TEXT NOT NULL, name TEXT NOT NULL,
 due TEXT, value INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS finance_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, position_id INTEGER NOT NULL REFERENCES positions(id),
 kind TEXT NOT NULL, day TEXT NOT NULL, book_id INTEGER REFERENCES books(id),
 account_id INTEGER REFERENCES accounts(id), principal INTEGER NOT NULL,
 extra INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS finance_position ON finance_events(position_id,day,id);
CREATE TABLE IF NOT EXISTS requests (key TEXT PRIMARY KEY, result_id INTEGER);
INSERT OR IGNORE INTO categories(id, name, kind) VALUES
 (1,'工资','income'),(2,'其他收入','income'),(3,'餐饮','expense'),
 (4,'交通','expense'),(5,'居住','expense'),(6,'日常购物','expense'),(7,'其他支出','expense');
INSERT OR IGNORE INTO categories(id, name, kind) VALUES
 (9,'利息收入','income'),(10,'利息支出','expense'),(11,'投资收益','income'),(12,'投资亏损','expense');
INSERT OR IGNORE INTO categories(id, name, kind, parent_id) VALUES (8,'水电费','expense',5);
"""
LIMIT = 999_999_999_999


def name(value, limit=80):
    if not isinstance(value, str) or not (1 <= len(value.strip()) <= limit):
        raise ValueError(f"名称必填，最多 {limit} 个字符")
    return value.strip()


def note(data):
    value = data.get("note", "")
    if not isinstance(value, str) or len(value) > 500:
        raise ValueError("备注最多 500 个字符")
    return value.strip()


def cents(value, minimum=1):
    if type(value) is not int or not minimum <= value <= LIMIT:
        raise ValueError("金额超出允许范围")
    return value


def day(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("请选择有效的日期")
    return date.fromisoformat(value).isoformat()


def find(db, table, key):
    # Table names are supplied by application code.
    if type(key) is not int or key <= 0:
        raise ValueError("请选择有效的记录")
    row = db.execute(f"SELECT * FROM {table} WHERE id=?", (key,)).fetchone()
    if row is None:
        raise ValueError("记录不存在，请刷新后重试")
    return row


def one_of(value, options):
    if value not in options:
        raise ValueError("请选择有效的类型")
    return value


def scope(db, data, old=None):
    book = find(db, "books", data.get("book_id"))
    if book["archived"] and (old is None or old["book_id"] != book["id"]):
        raise ValueError("请先恢复归档账本")
    account = find(db, "accounts", data.get("account_id"))
    portfolio.account_date(db, account["id"], day(data.get("day")))
    return book["id"], account["id"]


def save_bill(db, data):
    existing = data.get("id")
    old = find(db, "bills", existing) if existing is not None else None
    if old and old["source_type"]:
        raise ValueError("请从关联业务详情修改")
    book, account = scope(db, data, old)
    kind = one_of(data.get("kind"), ("income", "expense", "transfer"))
    category = None
    target = None
    if kind == "transfer":
        target = find(db, "accounts", data.get("to_account_id"))["id"]
        portfolio.account_date(db, target, day(data.get("day")))
        if target == account:
            raise ValueError("转入与转出账户必须不同")
    else:
        selected = find(db, "categories", data.get("category_id"))
        category = selected["id"]
        parent = find(db, "categories", selected["parent_id"]) if selected["parent_id"] else None
        enabled = selected["enabled"] and (parent is None or parent["enabled"])
        if selected["kind"] != kind or (not enabled and (old is None or old["category_id"] != category)):
            raise ValueError("请选择对应类型且已启用的类目")
    values = (book, day(data.get("day")), kind, cents(data.get("amount")), account, target, category, note(data))
    if old:
        db.execute("""UPDATE bills SET book_id=?,day=?,kind=?,amount=?,account_id=?,to_account_id=?,
                      category_id=?,note=? WHERE id=?""", (*values, existing))
        return existing
    return db.execute("""INSERT INTO bills(book_id,day,kind,amount,account_id,to_account_id,category_id,note)
                         VALUES (?,?,?,?,?,?,?,?)""", values).lastrowid


def rows(db, query, params=()):
    return [dict(row) for row in db.execute(query, params)]


def write_position(db, data):
    key = data.get("id")
    old = find(db, "positions", key) if key is not None else None
    kind = old["kind"] if old else one_of(data.get("kind"), ("asset","invest","borrow","lend"))
    owner = one_of(data.get("owner"), ("family","personal"))
    due = day(data["due"]) if data.get("due") and kind in ("borrow","lend") else None
    value = cents(data.get("value",old["value"] if old else 0), 0) if kind == "asset" else 0
    label = name(data.get("name"))
    if old:
        db.execute("UPDATE positions SET owner=?, name=?, due=?, value=? WHERE id=?", (owner,label,due,value,key))
    else:
        key = db.execute("INSERT INTO positions(kind,owner,name,due,value) VALUES (?,?,?,?,?)",
                         (kind,owner,label,due,value)).lastrowid
        if kind in ("borrow","lend"):
            write_event(db, dict(data, id=None, position_id=key, event_kind="origin"))
        if kind == "invest" and data.get("initial_cost") is not None:
            cost = cents(data.get("initial_cost"),0)
            market = cents(data.get("initial_market",cost),0)
            if cost == 0 and market:
                raise ValueError("已有持仓请同时填写成本和市值")
            if cost:
                write_event(db,dict(data,id=None,position_id=key,event_kind="buy",principal=cost,opening_only=True))
                if market != cost:
                    write_event(db,dict(data,id=None,position_id=key,event_kind="valuation",principal=market))
        default_subtype = {"asset":"custom", "invest":"other", "borrow":"loan", "lend":"receivable"}[kind]
        db.execute("UPDATE positions SET subtype=?, start_day=? WHERE id=?",
                   (default_subtype, day(data.get("day",date.today().isoformat())), key))
    portfolio.configure_position(db,key,data)
    if kind == "asset" and (old is None or "value" in data):
        portfolio.save_value(db,dict(position_id=key,day=data.get("day",date.today().isoformat()),value=value,note=data.get("note","")))
    return key


def position_financials(db, position, cutoff=None):
    events = rows(db, "SELECT * FROM finance_events WHERE position_id=? ORDER BY day,id", (position["id"],))
    if cutoff:
        events = [event for event in events if event["day"] <= cutoff]
    cost = current = realized = profit = 0
    opened = False
    for event in events:
        kind, amount, extra = event["kind"], event["principal"], event["extra"]
        if kind == "origin":
            if opened:
                raise ValueError("借贷只能登记一笔初始本金")
            opened = True
            cost = amount
        elif kind == "repay":
            if not opened or amount > cost:
                raise ValueError("还款日期或本金超出该日的剩余本金")
            cost -= amount
            profit += extra
        elif kind == "buy":
            cost += amount
            current += amount
        elif kind == "redeem":
            if not cost or amount > cost:
                raise ValueError("赎回成本超出该日的剩余投资成本")
            cost -= amount
            realized += extra - amount
            current = max(0, current - extra) if cost else 0
        elif kind == "valuation":
            if not cost and amount:
                raise ValueError("有剩余持仓时才能登记非零市值")
            current = amount
        elif kind == "yield":
            profit += amount
    if position["kind"] in ("borrow","lend") and not opened and cutoff is None:
        raise ValueError("借贷必须保留初始本金记录")
    return dict(position, cost=cost, market=current, unrealized=current-cost if position["kind"]=="invest" else 0,
                realized=realized, earnings=profit, events=events)


def event_lines(position, kind, amount, extra):
    borrowing = position["kind"] == "borrow"
    if kind == "origin":
        return [("inflow" if borrowing else "outflow",amount,None)]
    if kind == "repay":
        return [("outflow" if borrowing else "inflow",amount,None),
                ("expense" if borrowing else "income",extra,10 if borrowing else 9)]
    if kind == "buy":
        return [("outflow",amount,None)]
    if kind == "redeem":
        gain = extra - amount
        return [("inflow",amount,None), ("income",gain,11)] if gain >= 0 else [
            ("inflow",amount,None), ("expense",-gain,12)]
    if kind == "yield":
        return [("income",amount,11)]
    return []


def write_event(db, data):
    key = data.get("id")
    old = find(db, "finance_events", key) if key is not None else None
    position = find(db, "positions", old["position_id"] if old else data.get("position_id"))
    choices = ("origin","repay") if position["kind"] in ("borrow","lend") else (
        ("buy","redeem","yield","valuation") if position["kind"]=="invest" else ())
    kind = one_of(old["kind"] if old else data.get("event_kind"), choices)
    amount = cents(data.get("principal"), 0 if kind in ("repay","valuation") else 1)
    extra = cents(data.get("extra",0),0) if kind in ("redeem","repay") else 0
    if kind=="repay" and not (amount or extra):
        raise ValueError("本金和利息至少填写一项金额")
    opening_only = old["opening_only"] if old else data.get("opening_only",False)
    if type(opening_only) not in (bool,int) or opening_only not in (0,1):
        raise ValueError("期初债务模式无效")
    if kind not in ("origin","buy"):
        opening_only = False
    book, account = (None,None) if kind=="valuation" or opening_only else scope(db, data, old)
    date_value, memo = day(data.get("day")), note(data)
    values = (date_value,book,account,amount,extra,memo)
    if old:
        db.execute("""UPDATE finance_events SET day=?,book_id=?,account_id=?,principal=?,extra=?,note=? WHERE id=?""",
                   (*values,key))
        db.execute("DELETE FROM bills WHERE source_type='position' AND source_id=?", (key,))
    else:
        key = db.execute("""INSERT INTO finance_events(position_id,kind,day,book_id,account_id,principal,extra,note)
                          VALUES (?,?,?,?,?,?,?,?)""", (position["id"],kind,*values)).lastrowid
        db.execute("UPDATE finance_events SET opening_only=? WHERE id=?",(opening_only,key))
    position_financials(db, position)
    source_labels = {"origin":"登记借贷","repay":"借贷还款/收款","buy":"投资投入","redeem":"投资赎回","yield":"投资收益"}
    for flow, value, category in ([] if opening_only else event_lines(position, kind, amount, extra)):
        if value:
            description = position["name"] + " · " + source_labels[kind] + (" · "+memo if memo else "")
            db.execute("""INSERT INTO bills(book_id,day,kind,amount,account_id,category_id,note,source_type,source_id)
                          VALUES (?,?,?,?,?,?,?,'position',?)""", (book,date_value,flow,value,account,category,description,key))
    return key


def delete_event(db, key):
    event = find(db, "finance_events", key)
    if event["kind"] == "origin":
        raise ValueError("初始本金记录可编辑")
    db.execute("DELETE FROM bills WHERE source_type='position' AND source_id=?", (key,))
    db.execute("DELETE FROM finance_events WHERE id=?", (key,))
    position_financials(db, find(db, "positions", event["position_id"]))
    return key


def snapshot(db):
    return {
        "last_backup": (db.execute("SELECT value FROM settings WHERE key='last_backup'").fetchone() or [None])[0],
        "asset_values": rows(db,"SELECT * FROM asset_values ORDER BY day DESC,id DESC"),
        "portfolio": {owner:portfolio.report(db,owner,date.today().year) for owner in ("family","personal")},
        "asset_options": {"accounts":portfolio.ACCOUNT_TYPES,"positions":portfolio.SUBTYPES},
        "positions": [position_financials(db, p) for p in db.execute("SELECT * FROM positions ORDER BY id")],
        "books": rows(db, "SELECT * FROM books ORDER BY id"),
        "categories": rows(db, "SELECT * FROM categories ORDER BY id"),
        "bills": rows(db, "SELECT * FROM bills ORDER BY day DESC,id DESC"),
        "accounts": rows(db, """
            SELECT a.*, a.opening + coalesce(sum(m.delta),0) AS balance
            FROM accounts a LEFT JOIN (
              SELECT account_id, CASE WHEN kind IN ('income','inflow') THEN amount ELSE -amount END AS delta FROM bills
              UNION ALL SELECT to_account_id, amount FROM bills WHERE kind='transfer'
            ) m ON m.account_id=a.id GROUP BY a.id ORDER BY a.id
        """),
    }


def save_category(db, data):
    key = data.get("id")
    label = name(data.get("name"))
    if key is not None:
        find(db, "categories", key)
        db.execute("UPDATE categories SET name=? WHERE id=?", (label, key))
        return key
    kind = one_of(data.get("kind"), ("income", "expense"))
    parent_id = data.get("parent_id")
    if parent_id is not None:
        parent = find(db, "categories", parent_id)
        if parent["kind"] != kind or parent["parent_id"] or not parent["enabled"]:
            raise ValueError("请选择启用中的同类型一级类目")
    return db.execute("INSERT INTO categories(name,kind,parent_id) VALUES (?,?,?)", (label,kind,parent_id)).lastrowid


def mutate(db, data):
    operation = data.get("action")
    key = data.get("id")
    if operation == "book":
        if key is None:
            return db.execute("INSERT INTO books(name) VALUES (?)", (name(data.get("name")),)).lastrowid
        find(db, "books", key)
        db.execute("UPDATE books SET name=? WHERE id=?", (name(data.get("name")), key))
        return key
    if operation == "archive":
        find(db, "books", key)
        if type(data.get("archived")) is not bool:
            raise ValueError("归档状态无效")
        db.execute("UPDATE books SET archived=? WHERE id=?", (data["archived"], key))
        return key
    if operation == "account":
        return portfolio.account_save(db,data)
    if operation == "asset_value":
        return portfolio.save_value(db,data)
    if operation == "delete_value":
        record = find(db,"asset_values",key)
        db.execute("DELETE FROM asset_values WHERE id=?",(key,))
        portfolio.sync_asset(db,record["position_id"])
        return key
    if operation == "position":
        return write_position(db, data)
    if operation == "finance_event":
        if data.get("id") is None and data.get("event_kind")=="origin":
            raise ValueError("请通过新增借贷登记初始本金")
        return write_event(db, data)
    if operation == "delete_event":
        return delete_event(db, key)
    if operation == "category":
        return save_category(db, data)
    if operation == "category_enabled":
        find(db, "categories", key)
        if type(data.get("enabled")) is not bool:
            raise ValueError("类目状态无效")
        db.execute("UPDATE categories SET enabled=? WHERE id=?", (data["enabled"], key))
        return key
    if operation == "bill":
        return save_bill(db, data)
    if operation == "delete_bill":
        if find(db, "bills", key)["source_type"]:
            raise ValueError("请从关联业务详情删除")
        db.execute("DELETE FROM bills WHERE id=?", (key,))
        return key
    raise ValueError("未知操作")


def action(db, data):
    request_key = data.get("request_id")
    if not isinstance(request_key, str) or not re.fullmatch(r"[a-zA-Z0-9-]{16,80}", request_key):
        raise ValueError("保存请求无效，请刷新后重试")
    previous = db.execute("SELECT result_id FROM requests WHERE key=?", (request_key,)).fetchone()
    if previous:
        return {"id": previous["result_id"]}
    key = mutate(db, data)
    db.execute("INSERT INTO requests VALUES (?,?)", (request_key, key))
    return {"id": key}
