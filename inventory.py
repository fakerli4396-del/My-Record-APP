"""Atomic opening inventories, linked to a ledger book."""
import json
import hashlib
from datetime import date


def ensure(db):
    db.execute("""CREATE TABLE IF NOT EXISTS inventories (
        id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL UNIQUE REFERENCES books(id),
        day TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
        records TEXT NOT NULL, assets INTEGER NOT NULL, debts INTEGER NOT NULL)""")


def history(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='inventories'").fetchone():
        return []
    return [dict(row) for row in db.execute("SELECT * FROM inventories ORDER BY id")]


def normalize(data):
    import ledger
    report_day = ledger.day(data.get("day"))
    if report_day > date.today().isoformat():
        raise ValueError("盘点日期不能晚于今天")
    source = data.get("items")
    if not isinstance(source, list) or not 1 <= len(source) <= 100:
        raise ValueError("请填写 1 至 100 项资产或负债")
    items, names = [], set()
    for row in source:
        if not isinstance(row, dict):
            raise ValueError("盘点行格式无效")
        kind = ledger.one_of(row.get("kind"), ("physical", "investment", "cash", "insurance", "debt"))
        label = ledger.name(row.get("name"))
        if label in names:
            raise ValueError("盘点名称重复，请为每项填写不同名称")
        names.add(label)
        item = dict(kind=kind, name=label, value=ledger.cents(row.get("value"), 0),
                    debt=ledger.cents(row.get("debt", 0), 0), cost=ledger.cents(row.get("cost", 0), 0),
                    limit=ledger.cents(row.get("limit", 0), 0), note=ledger.note(row),
                    detail=ledger.name(row.get("detail") or "未填写", 300))
        item["subtype"] = ledger.one_of(row.get("subtype"), {
            "physical": ("property", "vehicle", "custom"),
            "investment": ("stock", "fund", "gold", "deposit", "other"),
            "cash": ("cash", "bank", "wallet", "receivable"),
            "insurance": ("custom",), "debt": ("loan", "credit", "payable")}[kind])
        if kind == "investment" and item["value"] and not item["cost"]:
            raise ValueError("投资持仓需填写投资成本")
        if kind == "debt" and (item["value"] or not item["debt"]):
            raise ValueError("其他负债请填写大于零的已欠本金")
        if kind == "cash" and item["debt"]:
            raise ValueError("现金及应收款的借款请填入其他负债")
        if kind != "debt" and not (item["value"] or item["cost"] or item["debt"]):
            raise ValueError("请移除金额全部为零的空白行")
        if kind == "debt" and item["subtype"] == "credit" and item["limit"] < item["debt"]:
            raise ValueError("信用额度不能小于已欠本金")
        items.append(item)
    return dict(day=report_day, items=items)


def apply(db, data):
    import ledger
    import portfolio
    book = ledger.find(db, "books", data.get("book_id"))
    if book["archived"]:
        raise ValueError("请选择使用中的家庭账本")
    payload = normalize(data)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
    previous = db.execute("SELECT * FROM inventories WHERE book_id=?", (book["id"],)).fetchone()
    if previous:
        if previous["fingerprint"] == fingerprint:
            return previous["id"]
        raise ValueError("该账本已经完成期初盘点，请在资产详情中更新余额")
    records = []

    def position(kind, label, item, **amounts):
        key = ledger.write_position(db, dict(kind=kind, name=label, owner="family",
            subtype=item["subtype"] if kind not in ("borrow", "lend") else
            ("loan" if kind == "borrow" else "receivable"), day=payload["day"], opening_only=True,
            note=("盘点账本：" + book["name"] + "；" + item["detail"] + "；" + item["note"])[:500], **amounts))
        records.append(dict(kind="position", id=key))

    for item in payload["items"]:
        kind = item["kind"]
        if kind in ("physical", "insurance"):
            position("asset", item["name"], item, value=item["value"])
        elif kind == "investment":
            position("invest", item["name"], item, initial_cost=item["cost"], initial_market=item["value"])
        elif kind == "cash" and item["subtype"] == "receivable":
            position("lend", item["name"], item, principal=item["value"])
        elif kind == "cash" or (kind == "debt" and item["subtype"] == "credit"):
            key = portfolio.account_save(db, dict(name=item["name"], owner="family",
                account_type="credit" if kind == "debt" else item["subtype"],
                opening=-item["debt"] if kind == "debt" else item["value"],
                opening_day=payload["day"], credit_limit=item["limit"],
                note=("盘点账本：" + book["name"] + "；" + item["detail"] + "；" + item["note"])[:500]))
            records.append(dict(kind="account", id=key))
        if item["debt"] and not (kind == "debt" and item["subtype"] == "credit"):
            position("borrow", item["name"] + " · 贷款", item, principal=item["debt"])
    return db.execute("""INSERT INTO inventories
        (book_id,day,fingerprint,payload,records,assets,debts) VALUES (?,?,?,?,?,?,?)""",
        (book["id"],payload["day"],fingerprint,encoded,json.dumps(records),
         sum(i["value"] for i in payload["items"]),sum(i["debt"] for i in payload["items"]))).lastrowid
