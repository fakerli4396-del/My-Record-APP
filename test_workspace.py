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

    def test_reset_requires_confirmation_and_backup_restores_records(self):
        book,_,account=self.baseline()
        self.post("bill",**self.spending(book,account))
        token=self.app.token
        with self.assertRaises(HTTPError):
            self.post("reset",endpoint="files",confirm="")
        self.assertEqual(len(self.state()["bills"]),1)
        result=self.post("reset",endpoint="files",confirm="清空")
        self.assertNotEqual(self.app.token,token)
        for key in ("books","accounts","bills","positions","forecast_items"):
            self.assertEqual(self.state()[key],[])
        self.assertTrue(self.state()["categories"])
        preview=self.post("import_preview",endpoint="files",path=result["backup"])
        self.post("import_restore",endpoint="files",path=result["backup"],fingerprint=preview["fingerprint"])
        self.assertEqual(len(self.state()["bills"]),1)

    def test_bulk_loan_delete_rolls_back_an_invalid_selection(self):
        position=self.post("position",kind="lend",owner="personal",name="样例借出",principal=10000,
                           opening_only=True,day="2026-01-01")["id"]
        self.post("image_import",owner="personal",kind="lend",year=2026,day="2026-01-01",
                  items=[dict(name="样例计划",mode="plan",principal=None,annual_rate="",months=[100]*12)])
        forecast=self.state()["forecast_items"][0]["id"]
        entries=[dict(id=position,forecast=False),dict(id=forecast,forecast=True)]
        with self.assertRaises(HTTPError):
            self.post("delete_loans",kind="lend",owner="personal",entries=[entries[0],dict(id=999,forecast=True)])
        self.assertEqual(len(self.state()["positions"]),1)
        self.post("delete_loans",kind="lend",owner="personal",entries=entries)
        self.assertEqual(self.state()["positions"],[])
        self.assertEqual(self.state()["forecast_items"],[])

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

    def test_unassigned_borrow_schedule_paid_status_and_delete(self):
        key=self.post("position",kind="borrow",owner="family",name="示例分期甲",day="2026-11-19",
                      opening_only=True,principal=100000,total_interest=10001,
                      term_months=4,first_month="2026-12",monthly_payment=27500)["id"]
        current=self.state()
        self.assertEqual(current["loan_plans"],[{"position_id":key,"book_id":None,"annual_rate":"30.003"}])
        self.assertEqual([(r["month"],r["amount"]) for r in current["installments"]],
                         [("2026-12",27500),("2027-01",27500),("2027-02",27500),("2027-03",27501)])
        self.post("installment_paid",id=key,month="2027-01",paid=True)
        self.post("loan_plan",position_id=key,year=2027,annual_rate="30.003",months=[27500,27500,27501]+[0]*9)
        self.assertEqual(next(r["paid"] for r in self.state()["installments"] if r["month"]=="2027-01"),1)
        self.assertEqual(self.state()["positions"][0]["cost"],100000)
        self.assertEqual(self.state()["bills"],[])
        self.post("delete_borrow",id=key)
        self.assertEqual(self.state()["positions"],[])
        self.assertEqual(self.state()["installments"],[])
        self.assertEqual(self.state()["loan_plans"],[])

    def test_asset_card_data_and_book_icon_survive_export_import(self):
        book=self.post("book",name="我的账本",icon="car")["id"]
        items=[dict(name="家庭房产",subtype="property",value=204000,purchase_price=200000,
                    purchase_day="2025-03-02",asset_icon="home",has_loan=True)]
        result=self.post("asset_image_import",owner="family",items=items)
        self.assertEqual(self.post("asset_image_import",owner="family",items=items),result)
        bad=[dict(items[0],name="另一套房"),dict(items[0],name="错误日期",purchase_day="9999-01-01")]
        with self.assertRaises(HTTPError): self.post("asset_image_import",owner="family",items=bad)
        state=self.state()
        self.assertEqual(len(state["positions"]),1)
        self.assertEqual(state["book_icons"],{str(book):"car"})
        asset=state["positions"][0]
        self.assertEqual((asset["purchase_price"],asset["purchase_day"],asset["asset_icon"],asset["has_loan"],asset["value"]),
                         (200000,"2025-03-02","home",1,204000))
        result=self.post("export_data",endpoint="files",format="xlsx",book="",owner="all",path=str(self.path.parent))
        preview=self.post("import_preview",endpoint="files",path=result["path"])
        self.post("import_restore",endpoint="files",path=result["path"],fingerprint=preview["fingerprint"])
        self.assertEqual(self.state()["positions"],state["positions"])
        self.assertEqual(self.state()["book_icons"],state["book_icons"])

    def test_lend_schedule_and_imported_forecast_are_independent_of_books(self):
        key=self.post("position",kind="lend",owner="personal",name="借给朋友",day="2026-11-19",
                      opening_only=True,principal=200000,total_interest=20000,
                      term_months=4,first_month="2026-12")["id"]
        state=self.state()
        self.assertEqual(state["books"],[])
        self.assertEqual(state["loan_plans"],[{"position_id":key,"book_id":None,"annual_rate":"30"}])
        self.assertEqual([r["amount"] for r in state["installments"]],[55000]*4)
        self.post("installment_paid",id=key,month="2027-01",paid=True)
        self.assertEqual(next(r["paid"] for r in self.state()["installments"] if r["month"]=="2027-01"),1)
        self.assertEqual(self.state()["positions"][0]["cost"],200000)
        self.post("image_import",owner="personal",kind="lend",year=2026,day="2026-11-19",
                  items=[dict(name="我的工",mode="plan",months=[10000]+[0]*11,annual_rate="")])
        forecast=self.state()["forecast_items"][0]
        self.assertIsNone(forecast["book_id"])
        self.post("installment_paid",id=forecast["id"],month="2026-01",forecast=True,paid=True)
        self.assertEqual(json.loads(self.state()["forecast_items"][0]["paid_months"]),["2026-01"])
        self.post("delete_lend_forecast",id=forecast["id"])
        self.post("delete_lend",id=key)
        self.assertEqual(self.state()["positions"],[])
        self.assertEqual(self.state()["forecast_items"],[])
        self.assertEqual(self.state()["installments"],[])

    def test_custom_icon_thumbnail_round_trip_and_remove(self):
        from PIL import Image
        from io import BytesIO
        import base64
        source=BytesIO()
        Image.new("RGBA",(250,100),(180,35,165,128)).save(source,format="PNG")
        upload=base64.b64encode(source.getvalue()).decode()
        asset=self.post("position",kind="asset",owner="family",name="自定义图标资产",value=1000,
                        purchase_price=1000,purchase_day="2025-01-01",asset_icon="home",has_loan=False,
                        icon_image=upload)["id"]
        category=self.post("category",name="自定义图标类目",kind="expense",icon="home",icon_image=upload)["id"]
        book=self.post("book",name="图片账本",icon="home",icon_image=upload)["id"]
        state=self.state()
        icon=state["positions"][0]["icon_image"]
        self.assertEqual(next(b for b in state["books"] if b["id"]==book)["icon_image"],icon)
        self.assertEqual(next(c for c in state["categories"] if c["id"]==category)["icon_image"],icon)
        with Image.open(BytesIO(base64.b64decode(icon))) as thumbnail:
            self.assertEqual(thumbnail.format,"PNG")
            self.assertEqual(thumbnail.size,(64,26))
        with self.assertRaises(HTTPError):
            self.post("category",id=category,name="无效图标",kind="expense",icon="home",icon_image="aW52YWxpZA==")
        result=self.post("export_data",endpoint="files",format="xls",book="",owner="all",path=str(self.path.parent))
        preview=self.post("import_preview",endpoint="files",path=result["path"])
        self.post("import_restore",endpoint="files",path=result["path"],fingerprint=preview["fingerprint"])
        self.assertEqual(self.state()["positions"][0]["icon_image"],icon)
        self.assertEqual(next(b for b in self.state()["books"] if b["id"]==book)["icon_image"],icon)
        self.assertEqual(next(c for c in self.state()["categories"] if c["id"]==category)["icon_image"],icon)
        self.post("position",id=asset,name="自定义图标资产",owner="family",purchase_price=1000,purchase_day="2025-01-01",
                  asset_icon="home",has_loan=False,icon_image="")
        self.post("category",id=category,name="自定义图标类目",kind="expense",icon="home",icon_image="")
        self.assertEqual(self.state()["positions"][0]["icon_image"],"")
        self.assertEqual(next(c for c in self.state()["categories"] if c["id"]==category)["icon_image"],"")
