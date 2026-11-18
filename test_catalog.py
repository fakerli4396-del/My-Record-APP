import unittest
from urllib.error import HTTPError

import app
import catalog
import test_app as support


class CategoryDesignTests(unittest.TestCase):
    setUp = support.LocalAppTests.setUp
    start = support.LocalAppTests.start
    stop = staticmethod(support.LocalAppTests.stop)
    get = support.LocalAppTests.get
    post = support.LocalAppTests.post
    state = support.LocalAppTests.state
    baseline = support.LocalAppTests.baseline
    spending = support.LocalAppTests.spending
    file_action = support.LocalAppTests.file_action

    def test_presets_are_rich_and_do_not_recreate_renamed_or_disabled_categories(self):
        before=self.state()["categories"]
        self.assertGreaterEqual(len(before),50)
        self.assertTrue(all(c["icon"] in catalog.ICONS for c in before))
        for label in ("蔬菜","水果","饮品","医疗","宠物","兼职","奖学金"):
            self.assertTrue(any(c["name"]==label for c in before),label)
        self.post("category",id=3,name="我的餐饮",icon="meal")
        self.post("category_enabled",id=3,enabled=False)
        with app.connect(self.path) as db:
            catalog.ensure(db)
        rows=self.state()["categories"]
        self.assertEqual(len(rows),len(before))
        self.assertEqual(next(c for c in rows if c["id"]==3)["enabled"],0)
        self.assertFalse(any(c["name"]=="餐饮" for c in rows))

    def test_custom_icon_persists_with_historical_bills_and_backup(self):
        book, _, account=self.baseline()
        key=self.post("category",name="花园",kind="expense",icon="vegetable")["id"]
        self.post("bill",**self.spending(book,account,category_id=key))
        backup=self.file_action("backup",self.path.parent)
        self.post("category",id=key,name="花园新名",icon="home")
        self.assertEqual(self.state()["bills"][0]["category_id"],key)
        with self.assertRaises(HTTPError):
            self.post("category",id=key,name="花园",icon="<script>")
        preview=self.file_action("preview",backup["path"])
        self.file_action("restore",backup["path"],fingerprint=preview["fingerprint"])
        restored=next(c for c in self.state()["categories"] if c["id"]==key)
        self.assertEqual((restored["name"],restored["icon"]),("花园","vegetable"))
        self.assertEqual(self.state()["accounts"][0]["balance"],80000)
