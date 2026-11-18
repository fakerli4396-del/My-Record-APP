from datetime import date
from pathlib import Path
import sqlite3
import unittest
from urllib.error import HTTPError

import app
import ledger
import test_app as support


class PortfolioTests(unittest.TestCase):
    setUp = support.LocalAppTests.setUp
    start = support.LocalAppTests.start
    stop = staticmethod(support.LocalAppTests.stop)
    get = support.LocalAppTests.get
    post = support.LocalAppTests.post
    state = support.LocalAppTests.state
    baseline = support.LocalAppTests.baseline
    spending = support.LocalAppTests.spending
    finance = support.LocalAppTests.finance
    file_action = support.LocalAppTests.file_action

    def account(self, **values):
        return self.post("account", **dict({"name":"信用卡","owner":"personal","account_type":"credit",
            "opening":-50000,"opening_day":"2026-01-01","credit_limit":100000,"bill_day":10,"repay_day":28},**values))["id"]

    def test_credit_payment_changes_composition_not_income(self):
        book, _, cash = self.baseline()
        credit = self.account()
        before = self.state()["portfolio"]["personal"]["current"]
        self.assertEqual((before["assets"],before["debts"],before["net"]),(100000,50000,50000))
        self.post("bill", **self.spending(book,credit,amount=20000))
        bill = self.post("bill", **self.spending(book,cash,kind="transfer",amount=30000,to_account_id=credit))["id"]
        state = self.state()
        current = state["portfolio"]["personal"]["current"]
        self.assertEqual((current["assets"],current["debts"],current["net"]),(70000,40000,30000))
        self.assertEqual(sum(r["amount"] for r in state["bills"] if r["kind"]=="income"),0)
        self.post("delete_bill",id=bill)
        self.assertEqual(self.state()["portfolio"]["personal"]["current"]["debts"],70000)

    def test_edit_account_configuration_preserves_existing_movements(self):
        book, _, account = self.baseline()
        self.post("bill",**self.spending(book,account))
        self.post("account",id=account,name="支付宝",owner="family",account_type="wallet",opening=150000,
                  opening_day="2026-01-01",institution="支付宝",note="日常账户")
        state = self.state()
        self.assertEqual(state["accounts"][0]["balance"],130000)
        self.assertEqual(state["portfolio"]["family"]["current"]["assets"],130000)
        self.assertEqual(state["portfolio"]["personal"]["current"]["assets"],0)
        before = self.state()
        with self.assertRaises(HTTPError):
            self.post("account",id=account,name="支付宝",owner="family",account_type="wallet",opening=1,opening_day="2026-12-01")
        self.assertEqual(self.state(),before)
        with self.assertRaises(HTTPError):
            self.account(bill_day=32)
        with self.assertRaises(HTTPError):
            self.account(account_type="fake")

    def test_dated_physical_asset_values_and_yearly_trend(self):
        position = self.post("position",kind="asset",owner="family",name="住房",subtype="property",
                             value=30000000,day="2025-01-01",institution="自住",note="估值") ["id"]
        value = self.post("asset_value",position_id=position,day="2025-03-01",value=28000000)["id"]
        report = __import__("json").loads(self.get("/api/portfolio?owner=family&year=2025"))
        self.assertEqual([m["assets"] for m in report["months"][:4]],[30000000,30000000,28000000,28000000])
        self.post("asset_value",id=value,day="2025-04-01",value=29000000)
        report = __import__("json").loads(self.get("/api/portfolio?owner=family&year=2025"))
        self.assertEqual([m["assets"] for m in report["months"][:4]],[30000000,30000000,30000000,29000000])
        self.post("delete_value",id=value)
        self.assertEqual(self.state()["portfolio"]["family"]["current"]["assets"],30000000)

    def test_existing_debt_and_receivable_do_not_create_cash(self):
        book, _, account = self.baseline()
        loan = self.post("position",kind="borrow",owner="family",name="房贷",subtype="loan",day="2026-01-01",
                         principal=500000,opening_only=True,institution="银行",due="2030-01-01")["id"]
        lend = self.post("position",kind="lend",owner="personal",name="应收",day="2026-01-01",
                         principal=100000,opening_only=True)["id"]
        self.assertEqual(self.state()["bills"],[])
        self.assertEqual(self.state()["accounts"][0]["balance"],100000)
        self.finance(loan,book,account,"repay",10000,200)
        self.finance(lend,book,account,"repay",20000,100)
        state = self.state()
        self.assertEqual(state["portfolio"]["family"]["current"]["debts"],490000)
        self.assertEqual(state["portfolio"]["personal"]["current"]["assets"],189900)

    def test_empty_ratio_and_future_months_are_explicit(self):
        today = date.today()
        current = self.state()["portfolio"]["family"]
        self.assertIsNone(current["current"]["ratio"])
        self.assertTrue(all(m["net"] is None for m in current["months"][today.month:]))

    def test_extended_configuration_histories_and_totals_restore_together(self):
        self.account()
        self.post("position",kind="asset",owner="family",name="车",subtype="vehicle",value=1000000,
                  day="2025-01-01",note="车辆")
        backup = self.file_action("backup",self.path.parent)
        before = self.state()
        self.account(name="微信",account_type="wallet",owner="family",opening=10000)
        preview = self.file_action("preview",backup["path"])
        self.file_action("restore",backup["path"],fingerprint=preview["fingerprint"])
        state = self.state()
        for key in ("accounts","asset_values","positions","portfolio"):
            self.assertEqual(state[key],before[key])

    def test_v1_migration_backup_and_legacy_restore(self):
        legacy = self.path.parent / "old.db"
        with app.connect(legacy) as db:
            db.executescript(app.SCHEMA+ledger.SCHEMA+"PRAGMA user_version=1;")
            db.execute("INSERT INTO accounts(name,owner,opening) VALUES ('旧银行卡','personal',12345)")
            db.execute("INSERT INTO positions(kind,owner,name,value) VALUES ('asset','family','旧房产',90000)")
        preview = self.file_action("preview",legacy)
        with app.connect(legacy) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0],1)
        self.file_action("restore",legacy,fingerprint=preview["fingerprint"])
        state = self.state()
        self.assertEqual(state["accounts"][0]["opening"],12345)
        self.assertEqual(state["accounts"][0]["account_type"],"other")
        self.assertEqual(state["portfolio"]["family"]["current"]["assets"],90000)
        app.initialize(legacy)
        self.assertTrue(list((legacy.parent/"upgrade-backups").glob("before-v2-*.db")))
        with app.connect(legacy) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0],2)
            self.assertEqual(db.execute("SELECT opening FROM accounts").fetchone()[0],12345)
