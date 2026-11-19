import unittest
from urllib.error import HTTPError
import app
import backups
import image_import
import test_app as support

class OCRRepairTests(unittest.TestCase):
    setUp=support.LocalAppTests.setUp
    start=support.LocalAppTests.start
    stop=staticmethod(support.LocalAppTests.stop)
    get=support.LocalAppTests.get
    post=support.LocalAppTests.post
    state=support.LocalAppTests.state
    baseline=support.LocalAppTests.baseline

    def test_parser_rejects_symbol_rows_and_deduplicates_identical_named_rows(self):
        def word(text,x,y,w=100):
            return dict(text=text,x=x,y=y,w=w,h=20)
        words=[word("5月应还",700,10),word("6月应还",1000,10)]
        for y,label in [(70,"%支付宝借呗"),(103,"·"),(145,"支付宝借呗"),(190,"另一笔借款")]:
            words += [word(label,180,y,180),word("184809",420,y),word("297",700,y),word("405",1000,y)]
        result=image_import.parse(words)
        self.assertEqual([r["name"] for r in result["items"]],["支付宝借呗","另一笔借款"])
        self.assertEqual(result["items"][0]["principal"],18480900)
        self.assertEqual(result["items"][0]["months"][4:6],[29700,40500])

    def test_review_cleans_names_but_rejects_punctuation_and_duplicate_names(self):
        book,_,_=self.baseline()
        data=dict(book_id=book,owner="family",kind="borrow",year=2026,day="2026-11-19",
                  items=[dict(name="%支付宝借呗",mode="loan",principal=10000,annual_rate="3",months=[100]*12)])
        self.post("image_import",**data)
        self.assertEqual(self.state()["positions"][0]["name"],"支付宝借呗")
        before=self.state()
        for name in (".","·","%"):
            data["items"][0]["name"]=name
            with self.assertRaises(HTTPError):self.post("image_import",**data)
            self.assertEqual(self.state(),before)
        data["items"]=[dict(name=n,mode="loan",principal=10000,annual_rate="3",months=[100]*12)
                       for n in ("%京东金条","京东金条")]
        with self.assertRaises(HTTPError):self.post("image_import",**data)
        self.assertEqual(self.state(),before)

    def test_startup_repairs_existing_records_with_full_original_backup(self):
        book,_,_=self.baseline()
        ids=[]
        for name in ("%支付宝借呗",".","相同金额的正常借款","·"):
            key=self.post("position",kind="borrow",owner="family",name=name,principal=18480900,
                          opening_only=True,day="2026-11-19")["id"]
            ids.append(key)
            # The final symbol row has a different schedule and must remain for review.
            self.post("loan_plan",position_id=key,book_id=book,year=2026,annual_rate="3",
                      months=([100]*12 if name=="·" else [29700]*12))
        before=self.state()
        self.stop(self.app,self.thread);self.start()
        after=self.state()
        self.assertEqual([p["name"] for p in after["positions"]],
                         ["支付宝借呗","相同金额的正常借款","·"])
        self.assertEqual(after["portfolio"]["family"]["current"]["debts"],
                         before["portfolio"]["family"]["current"]["debts"]-18480900)
        self.assertFalse(any(r["position_id"]==ids[1] for r in after["loan_plans"]))
        files=list((self.path.parent/"recognition-repair-backups").glob("*.db"))
        self.assertEqual(len(files),1)
        with app.connect(files[0]) as db:
            self.assertEqual([r[0] for r in db.execute("SELECT name FROM positions")],
                             ["%支付宝借呗",".","相同金额的正常借款","·"])
        self.stop(self.app,self.thread);self.start()
        self.assertEqual(len(list((self.path.parent/"recognition-repair-backups").glob("*.db"))),1)
