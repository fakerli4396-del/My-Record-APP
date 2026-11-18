import json
import unittest
from urllib.error import HTTPError
import test_app as support


class InventoryTests(unittest.TestCase):
    setUp = support.LocalAppTests.setUp
    start = support.LocalAppTests.start
    stop = staticmethod(support.LocalAppTests.stop)
    get = support.LocalAppTests.get
    post = support.LocalAppTests.post
    state = support.LocalAppTests.state
    file_action = support.LocalAppTests.file_action

    def payload(self):
        book = self.post("book", name="家庭盘点")["id"]
        def row(kind, subtype, name, value=0, debt=0, cost=0, limit=0):
            return dict(kind=kind, subtype=subtype, name=name, value=value, debt=debt,
                        cost=cost, limit=limit, detail="2020年购买，90㎡，剩余20年，年利率3%", note="保留原始资料")
        return dict(book_id=book, day="2026-01-01", items=[
            row("physical", "property", "住宅", 10000000, 3000000, 8000000),
            row("investment", "fund", "基金", 120000, 20000, 100000),
            row("cash", "bank", "家庭存款", 300000),
            row("cash", "receivable", "应收款", 20000),
            row("insurance", "custom", "保险", 80000, 10000, 100000),
            row("debt", "credit", "信用卡", debt=50000, limit=100000),
            row("debt", "loan", "信用贷", debt=100000)])

    def test_import_totals_book_retry_and_full_backup_restore(self):
        data = self.payload()
        key = self.post("inventory", **data)["id"]
        self.assertEqual(self.post("inventory", **data)["id"], key)
        state = self.state()
        current = state["portfolio"]["family"]["current"]
        self.assertEqual((current["assets"], current["debts"], current["net"]),
                         (10520000, 3180000, 7340000))
        self.assertEqual(state["bills"], [])
        self.assertEqual(state["portfolio"]["personal"]["current"]["assets"], 0)
        self.assertEqual(state["inventories"][0]["book_id"], data["book_id"])
        self.assertEqual(json.loads(state["inventories"][0]["payload"])["items"][0]["detail"], data["items"][0]["detail"])
        backup = self.file_action("backup", self.path.parent)
        self.post("book", id=data["book_id"], name="改名")
        preview = self.file_action("preview", backup["path"])
        self.file_action("restore", backup["path"], fingerprint=preview["fingerprint"])
        self.assertEqual(self.state()["inventories"], state["inventories"])
        self.assertEqual(self.state()["portfolio"], state["portfolio"])

    def test_invalid_late_row_rolls_back_every_created_record(self):
        data = self.payload()
        # A collision occurs after the house, its loan and the investment were created.
        self.post("account", name="家庭存款", owner="family", opening=0)
        before = self.state()
        with self.assertRaises(HTTPError):
            self.post("inventory", **data)
        after = self.state()
        for field in ("positions", "accounts", "asset_values", "inventories", "bills"):
            self.assertEqual(after[field], before[field])

    def test_invalid_numbers_duplicates_archived_and_reinitialization_rejected(self):
        data = self.payload()
        for changes in ({"value": -1}, {"value": 1.25}, {"subtype": "unknown"}):
            bad = json.loads(json.dumps(data))
            bad["items"][0].update(changes)
            with self.assertRaises(HTTPError):
                self.post("inventory", **bad)
        self.post("archive", id=data["book_id"], archived=True)
        with self.assertRaises(HTTPError):
            self.post("inventory", **data)
        self.post("archive", id=data["book_id"], archived=False)
        self.post("inventory", **data)
        data["items"][0]["value"] += 1
        with self.assertRaises(HTTPError):
            self.post("inventory", **data)
