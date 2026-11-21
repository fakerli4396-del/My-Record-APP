"""Asset configuration, dated balances and one shared portfolio report."""
from datetime import date
import calendar

ACCOUNT_TYPES = {"cash": "现金", "bank": "储蓄卡", "credit": "信用卡", "wallet": "虚拟账户",
                 "investment_cash": "投资账户资金", "other": "其他资金账户"}
CASH_ACCOUNT_TYPES = ("cash", "bank", "other")
SUBTYPES = {"asset": {"property": "房产", "vehicle": "车辆", "custom": "自定义资产"},
            "invest": {"stock": "股票", "fund": "基金", "gold": "黄金", "deposit": "理财", "other": "其他投资"},
            "borrow": {"loan": "贷款", "payable": "应付款"},
            "lend": {"receivable": "应收款"}}


def upgrade(db):
    """Upgrade the original schema transactionally, preserving IDs and money."""
    if db.execute("PRAGMA user_version").fetchone()[0] != 1:
        return
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    today = date.today().isoformat()
    for table, columns in {
        "accounts": {"account_type": "TEXT NOT NULL DEFAULT 'other'", "institution": "TEXT NOT NULL DEFAULT ''",
                     "note": "TEXT NOT NULL DEFAULT ''", "opening_day": "TEXT NOT NULL DEFAULT '0001-01-01'",
                     "credit_limit": "INTEGER NOT NULL DEFAULT 0", "bill_day": "INTEGER", "repay_day": "INTEGER"},
        "positions": {"subtype": "TEXT NOT NULL DEFAULT ''", "institution": "TEXT NOT NULL DEFAULT ''",
                      "note": "TEXT NOT NULL DEFAULT ''", "start_day": "TEXT NOT NULL DEFAULT '0001-01-01'"},
        "finance_events": {"opening_only": "INTEGER NOT NULL DEFAULT 0"},
    }.items():
        for key, definition in columns.items():
            db.execute(f"ALTER TABLE {table} ADD COLUMN {key} {definition}")
    db.execute("""CREATE TABLE asset_values (
        id INTEGER PRIMARY KEY AUTOINCREMENT, position_id INTEGER NOT NULL REFERENCES positions(id),
        day TEXT NOT NULL, value INTEGER NOT NULL, note TEXT NOT NULL DEFAULT '')""")
    # Original cash opening dates were not collected. Use their earliest movement,
    # or migration day, so charts never invent a past history before that date.
    for row in db.execute("SELECT id FROM accounts").fetchall():
        earliest = db.execute("SELECT min(day) FROM bills WHERE account_id=? OR to_account_id=?", (row[0],row[0])).fetchone()[0]
        db.execute("UPDATE accounts SET opening_day=? WHERE id=?", (min(today, earliest or today),row[0]))
    defaults = {"asset":"custom", "invest":"other", "borrow":"loan", "lend":"receivable"}
    for row in db.execute("SELECT id,kind,value FROM positions").fetchall():
        earliest = db.execute("SELECT min(day) FROM finance_events WHERE position_id=?", (row[0],)).fetchone()[0]
        db.execute("UPDATE positions SET subtype=?, start_day=? WHERE id=?", (defaults[row[1]],earliest or today,row[0]))
        if row[1] == "asset":
            db.execute("INSERT INTO asset_values(position_id,day,value,note) VALUES (?,?,?,?)",
                       (row[0],today,row[2],"旧版资产估值迁移，之前日期无估值记录"))
    db.execute("PRAGMA user_version=2")


def optional_text(value, limit=120):
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise ValueError(f"文字最多 {limit} 个字符")
    return value.strip()


def account_save(db, data):
    import ledger
    key = data.get("id")
    old = ledger.find(db,"accounts",key) if key is not None else None
    kind = ledger.one_of(data.get("account_type", old["account_type"] if old else "other"), ACCOUNT_TYPES)
    opening = ledger.cents(data.get("opening"), -ledger.LIMIT)
    opening_day = ledger.day(data.get("opening_day", old["opening_day"] if old else "0001-01-01"))
    if old:
        earliest = db.execute("SELECT min(day) FROM bills WHERE account_id=? OR to_account_id=?", (key,key)).fetchone()[0]
        if earliest and opening_day > earliest:
            raise ValueError("期初日期不能晚于账户已有流水日期")
    credit_limit = ledger.cents(data.get("credit_limit",0),0) if kind == "credit" else 0
    def cycle(field):
        value = data.get(field)
        if kind != "credit" or value in (None, ""):
            return None
        if type(value) is not int or not 1 <= value <= 31:
            raise ValueError("账单日与还款日应在 1 到 31 之间")
        return value
    values = (ledger.name(data.get("name")),ledger.one_of(data.get("owner"),("family","personal")),opening,kind,
              optional_text(data.get("institution","")),ledger.note(data),opening_day,credit_limit,cycle("bill_day"),cycle("repay_day"))
    columns = "name,owner,opening,account_type,institution,note,opening_day,credit_limit,bill_day,repay_day"
    if old:
        assignments = ",".join(c+"=?" for c in columns.split(","))
        db.execute(f"UPDATE accounts SET {assignments} WHERE id=?", (*values,key))
    else:
        key = db.execute(f"INSERT INTO accounts({columns}) VALUES ({','.join('?' for _ in values)})", values).lastrowid
    return key


def account_date(db, key, business_day):
    import ledger
    if business_day < ledger.find(db,"accounts",key)["opening_day"]:
        raise ValueError("业务日期不能早于账户期初日期，请在账户配置中核对")


def configure_position(db, key, data):
    import ledger
    old = ledger.find(db,"positions",key)
    subtype = ledger.one_of(data.get("subtype",old["subtype"]), SUBTYPES[old["kind"]])
    db.execute("UPDATE positions SET subtype=?,institution=?,note=? WHERE id=?",
               (subtype,optional_text(data.get("institution",old["institution"])),ledger.note(data),key))


def save_value(db, data):
    import ledger
    key = data.get("id")
    old = ledger.find(db,"asset_values",key) if key is not None else None
    p = ledger.find(db,"positions",old["position_id"] if old else data.get("position_id"))
    if p["kind"] != "asset":
        raise ValueError("请在投资详情记录投资估值")
    values = (ledger.day(data.get("day")),ledger.cents(data.get("value"),0),ledger.note(data))
    if old:
        db.execute("UPDATE asset_values SET day=?,value=?,note=? WHERE id=?", (*values,key))
    else:
        key = db.execute("INSERT INTO asset_values(day,value,note,position_id) VALUES (?,?,?,?)",(*values,p["id"])).lastrowid
    sync_asset(db,p["id"])
    return key


def sync_asset(db, key):
    value = db.execute("SELECT value FROM asset_values WHERE position_id=? ORDER BY day DESC,id DESC LIMIT 1",(key,)).fetchone()
    db.execute("UPDATE positions SET value=? WHERE id=?",(value[0] if value else 0,key))


def point(db, owner, cutoff):
    """Reconstruct balances at a date using the same rules as current totals."""
    import ledger
    entries = []
    for account in db.execute("SELECT * FROM accounts WHERE owner=? AND opening_day<=?", (owner,cutoff)):
        outgoing = db.execute("""SELECT coalesce(sum(CASE WHEN kind IN ('income','inflow') THEN amount ELSE -amount END),0)
                                FROM bills WHERE account_id=? AND day<=?""",(account["id"],cutoff)).fetchone()[0]
        incoming = db.execute("SELECT coalesce(sum(amount),0) FROM bills WHERE to_account_id=? AND kind='transfer' AND day<=?",
                              (account["id"],cutoff)).fetchone()[0]
        balance = account["opening"] + outgoing + incoming
        entries.append(dict(kind="account",id=account["id"],name=account["name"],group=ACCOUNT_TYPES[account["account_type"]],
                            cash=balance if account["account_type"] in CASH_ACCOUNT_TYPES else None,
                            assets=max(0,balance),debts=max(0,-balance)))
    for position in db.execute("SELECT * FROM positions WHERE owner=?",(owner,)):
        kind = position["kind"]
        if kind == "asset":
            row = db.execute("SELECT value FROM asset_values WHERE position_id=? AND day<=? ORDER BY day DESC,id DESC LIMIT 1",
                             (position["id"],cutoff)).fetchone()
            value = row[0] if row else 0
        else:
            value = ledger.position_financials(db,position,cutoff)["market" if kind=="invest" else "cost"]
        entries.append(dict(kind="position",id=position["id"],name=position["name"],group=SUBTYPES[kind][position["subtype"]],
                            assets=0 if kind=="borrow" else value,debts=value if kind=="borrow" else 0))
    assets = sum(e["assets"] for e in entries)
    debts = sum(e["debts"] for e in entries)
    cash = sum(entry["cash"] for entry in entries if entry.get("cash") is not None)
    return dict(day=cutoff,assets=assets,debts=debts,net=assets-debts,cash=cash,ratio=debts/assets if assets else None,entries=entries)


def report(db, owner, year):
    import ledger
    ledger.one_of(owner,("family","personal"))
    if type(year) is not int or not 1 <= year <= 9999:
        raise ValueError("年份无效")
    today = date.today()
    current = point(db,owner,today.isoformat())
    months = []
    for month in range(1,13):
        end = date(year,month,calendar.monthrange(year,month)[1])
        if date(year,month,1) > today:
            months.append(dict(month=month,assets=None,debts=None,net=None))
        else:
            item = point(db,owner,min(today,end).isoformat())
            months.append(dict(month=month,assets=item["assets"],debts=item["debts"],net=item["net"]))
    return dict(owner=owner,year=year,current=current,months=months)
