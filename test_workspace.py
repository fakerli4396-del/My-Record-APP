import json
import unittest
from urllib.error import HTTPError
import app
import exchange
import test_app as support

class WorkspaceTests(unittest.TestCase):
    setUp=support.LocalAppTests.setUp
    start=support.LocalAppTests.start
    stop=staticmethod(support.LocalAppTests.stop)
    get=support.LocalAppTests.get
    post=support.LocalAppTests.post
    state=support.LocalAppTests.state
    baseline=support.LocalAppTests.baseline
    spending=support.LocalAppTests.spending
    file_action=support.LocalAppTests.file_action

    def test_budget_schedule_and_all_formats_round_trip(self):
        book,other,account=self.baseline()
        self.post("bill",**self.spending(book,account))
        self.post("bill",**self.spending(other,account,amount=3000))
        self.post("budget",book_id=book,month="2026-11",amount=15000)
        p=self.post("position",kind="borrow",owner="family",name="房贷",principal=500000,
                    opening_only=True,day="2026-01-01")["id"]
        self.post("loan_plan",position_id=p,book_id=book,year=2026,annual_rate="3.5",months=[10000]*12)
        credit=self.post("account",name="信用卡",owner="family",opening=-5000,account_type="credit",credit_limit=20000)["id"]
        self.post("loan_plan",account_id=credit,book_id=book,year=2026,annual_rate="0",months=[500]*12)
        original=self.state()
        for fmt in ("db","xlsx","xls"):
            with self.subTest(format=fmt):
                result=self.post("export_data",endpoint="files",format=fmt,book="",owner="all",path=str(self.path.parent))
                preview=self.post("import_preview",endpoint="files",path=result["path"])
                self.post("budget",book_id=book,month="2026-11",amount=999)
                self.post("import_restore",endpoint="files",path=result["path"],fingerprint=preview["fingerprint"])
                for key in ("books","bills","accounts","positions","budgets","loan_plans","installments","credit_plans","credit_installments"):
                    self.assertEqual(self.state()[key],original[key],(fmt,key))

    def test_scoped_export_and_invalid_import_are_safe(self):
        book,other,account=self.baseline()
        self.post("bill",**self.spending(book,account))
        self.post("bill",**self.spending(other,account,amount=3000))
        result=self.post("export_data",endpoint="files",format="db",book=str(book),owner="none",path=str(self.path.parent))
        with app.connect(__import__("pathlib").Path(result["path"])) as db:
            self.assertEqual([r[0] for r in db.execute("SELECT id FROM books")],[book])
            self.assertEqual(db.execute("SELECT count(*) FROM bills").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT count(*) FROM positions").fetchone()[0],0)
            self.assertEqual(__import__("ledger").snapshot(db)["accounts"][0]["balance"],77000)
        before=self.state()
        invalid=self.path.parent/"bad.xlsx";invalid.write_bytes(b"not an excel workbook")
        with self.assertRaises(HTTPError): self.post("import_preview",endpoint="files",path=str(invalid))
        self.assertEqual(self.state(),before)
        preview=self.post("import_preview",endpoint="files",path=result["path"])
        with open(result["path"],"ab") as f:f.write(b"changed")
        with self.assertRaises(HTTPError):self.post("import_restore",endpoint="files",path=result["path"],fingerprint=preview["fingerprint"])
        self.assertEqual(self.state(),before)

    def test_invalid_schedule_rolls_back(self):
        book,_,_=self.baseline()
        p=self.post("position",kind="lend",owner="personal",name="借款",principal=10000,opening_only=True,day="2026-01-01")["id"]
        before=self.state()
        with self.assertRaises(HTTPError):
            self.post("loan_plan",position_id=p,book_id=book,year=2026,annual_rate="3",months=[100]*11+[-1])
        self.assertEqual(self.state(),before)

    def test_asset_owner_scope_preserves_only_selected_assets(self):
        book,_,_=self.baseline()
        for owner in ("family","personal"):
            self.post("position",kind="asset",owner=owner,name=owner+"房产",value=500000,day="2026-01-01")
        for owner in ("family","personal"):
            result=self.post("export_data",endpoint="files",format="xlsx",book=str(book),owner=owner,path=str(self.path.parent))
            from pathlib import Path
            candidate=self.path.parent/(owner+".db")
            exchange.workbook_db(Path(result["path"]),candidate)
            with app.connect(candidate) as db:
                self.assertEqual([r[0] for r in db.execute("SELECT owner FROM positions")],[owner])
