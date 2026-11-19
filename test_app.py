import json
from pathlib import Path
import tempfile
import threading
import subprocess
import sys
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4
from unittest.mock import patch

from app import Application, connect


class LocalAppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="record-test-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "中文 账本" / "test.db"
        self.start()

    def start(self):
        self.app = Application(self.path)
        self.thread = threading.Thread(target=self.app.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop, self.app, self.thread)

    @staticmethod
    def stop(app, thread):
        if thread.is_alive():
            app.shutdown()
            thread.join()
            app.server_close()

    def get(self, path):
        with urlopen(self.app.origin + path, timeout=5) as response:
            return response.read()

    def post(self, action, request_id=None, endpoint="action", **data):
        payload = json.dumps(dict(data, action=action, request_id=request_id or str(uuid4()))).encode()
        headers = {"Origin": self.app.origin, "X-Record-Token": self.app.token,
                   "Content-Type": "application/json"}
        try:
            with urlopen(Request(self.app.origin + "/api/" + endpoint, payload, headers), timeout=5) as response:
                return json.load(response)
        except HTTPError as error:
            with error:
                error.details = json.load(error)
                raise

    def state(self):
        return json.loads(self.get("/api/state"))

    def baseline(self):
        book = self.post("book", name="家庭")["id"]
        other = self.post("book", name="个人")["id"]
        account = self.post("account", name="银行卡", owner="personal", opening=100000)["id"]
        return book, other, account

    def spending(self, book, account, **changes):
        return dict({"book_id":book,"account_id":account,"category_id":6,
                     "day":"2026-11-14","amount":20000,"kind":"expense","note":"买菜"}, **changes)

    def test_stage2_book_rename_archive_unchanged_history_and_restore(self):
        book, other, account = self.baseline()
        bill = self.post("bill", **self.spending(book, account))["id"]
        self.post("book", id=book, name="家庭支出")
        self.post("archive", id=book, archived=True)
        state = self.state()
        self.assertEqual(state["books"][0], {"id":book,"name":"家庭支出","archived":1,"icon_image":""})
        self.assertEqual(state["bills"][0]["id"], bill)
        with self.assertRaises(HTTPError):
            self.post("bill", **self.spending(book, account))
        self.post("archive", id=book, archived=False)
        self.assertEqual(self.state()["books"][0]["archived"], 0)

    def test_stage2_cross_book_spending_edit_move_delete(self):
        book, other, account = self.baseline()
        bill = self.post("bill", **self.spending(book, account))["id"]
        state = self.state()
        self.assertEqual([(b["book_id"],b["day"],b["amount"]) for b in state["bills"]],
                         [(book,"2026-11-14",20000)])
        self.assertEqual(state["accounts"][0]["balance"], 80000)
        self.post("bill", id=bill, **self.spending(book, account, day="2026-11-15", amount=31000))
        state = self.state()
        self.assertEqual([(b["day"],b["amount"]) for b in state["bills"]], [("2026-11-15",31000)])
        self.assertEqual(state["accounts"][0]["balance"], 69000)
        self.post("delete_bill", id=bill)
        state = self.state()
        self.assertEqual(state["bills"], [])
        self.assertEqual(state["accounts"][0]["balance"], 100000)

    def test_stage2_failure_rolls_back_and_retry_is_idempotent(self):
        book, other, account = self.baseline()
        key = str(uuid4())
        with connect(self.path) as db:
            db.execute("""CREATE TRIGGER stop_write BEFORE INSERT ON requests
                          BEGIN SELECT raise(FAIL, 'injected failure'); END""")
        with self.assertRaises(HTTPError) as failure:
            self.post("bill", request_id=key, **self.spending(book, account))
        self.assertEqual(failure.exception.code, 400)
        self.assertEqual(self.state()["bills"], [])
        self.assertEqual(self.state()["accounts"][0]["balance"], 100000)
        with connect(self.path) as db:
            db.execute("DROP TRIGGER stop_write")
        first = self.post("bill", request_id=key, **self.spending(book, account))
        second = self.post("bill", request_id=key, **self.spending(book, account))
        self.assertEqual(first, second)
        self.assertEqual(len(self.state()["bills"]), 1)
        self.assertEqual(self.state()["accounts"][0]["balance"], 80000)

    def test_stage3_transfer_updates_both_accounts_and_delete_reverses(self):
        book, other, source = self.baseline()
        target = self.post("account", name="现金", owner="family", opening=2500)["id"]
        data = self.spending(book, source, kind="transfer", amount=100000)
        with self.assertRaises(HTTPError):
            self.post("bill", to_account_id=source, **data)
        bill = self.post("bill", to_account_id=target, **data)["id"]
        state = self.state()
        self.assertEqual([a["balance"] for a in state["accounts"]], [0,102500])
        self.assertIsNone(state["bills"][0]["category_id"])
        self.post("delete_bill", id=bill)
        self.assertEqual([a["balance"] for a in self.state()["accounts"]], [100000,2500])

    def test_stage3_category_history_and_two_levels(self):
        book, other, account = self.baseline()
        parent = self.post("category", name="住宅", kind="expense")["id"]
        child = self.post("category", name="水费", kind="expense", parent_id=parent)["id"]
        with self.assertRaises(HTTPError):
            self.post("category", name="三级", kind="expense", parent_id=child)
        data = self.spending(book, account, category_id=child)
        record = self.post("bill", **data)["id"]
        self.post("category_enabled", id=child, enabled=False)
        with self.assertRaises(HTTPError):
            self.post("bill", **data)
        self.post("bill", id=record, **dict(data, note="保留停用类目"))
        self.assertEqual(self.state()["bills"][0]["category_id"], child)
        self.post("category_enabled", id=child, enabled=True)
        self.post("bill", **data)
        self.post("category_enabled", id=parent, enabled=False)
        with self.assertRaises(HTTPError):
            self.post("bill", **data)
        self.assertEqual(len(self.state()["bills"]), 2)

    def finance(self, position, book, account, kind, principal, extra=0, day="2026-11-15", **more):
        return self.post("finance_event", position_id=position, book_id=book, account_id=account,
                         event_kind=kind, principal=principal, extra=extra, day=day, **more)["id"]

    def test_stage4_borrow_and_lend_principal_interest_and_history(self):
        book, other, account = self.baseline()
        loan = self.post("position", kind="borrow", owner="personal", name="借款", book_id=book,
                         account_id=account, day="2026-11-14", principal=500000,due="2026-12-01")["id"]
        repayment = self.finance(loan, book, account, "repay", 50000, 2000)
        state = self.state()
        self.assertEqual(state["positions"][0]["cost"], 450000)
        self.assertEqual(state["accounts"][0]["balance"], 548000)
        self.assertEqual([(r["kind"],r["amount"],r["source_id"]) for r in state["bills"][:2]],
                         [("expense",2000,repayment),("outflow",50000,repayment)])
        origin = state["positions"][0]["events"][0]["id"]
        with self.assertRaises(HTTPError):
            self.finance(loan, book, account, "origin", 1000, day="2026-11-14", id=origin)
        self.assertEqual(self.state(), state)
        lent = self.post("position", kind="lend", owner="family", name="借给他人", book_id=book,
                         account_id=account, day="2026-11-14", principal=100000)["id"]
        self.finance(lent, book, account, "repay", 20000, 1000)
        state = self.state()
        self.assertEqual(state["positions"][1]["cost"], 80000)
        self.assertEqual(state["accounts"][0]["balance"], 469000)
        self.assertEqual(sum(r["amount"] for r in state["bills"] if r["kind"]=="income"),1000)
        with self.assertRaises(HTTPError):
            self.post("delete_bill", id=state["bills"][0]["id"])
        self.post("delete_event", id=repayment)
        self.assertEqual(self.state()["positions"][0]["cost"], 500000)

    def test_stage4_cash_and_manual_valuation_follow_prd(self):
        book, other, account = self.baseline()
        position = self.post("position", kind="invest", owner="personal", name="理财")["id"]
        self.finance(position, book, account, "buy", 100000, day="2026-11-14")
        self.assertEqual(self.state()["accounts"][0]["balance"], 0)
        self.finance(position, book, account, "valuation", 120000)
        state = self.state()
        self.assertEqual(state["positions"][0]["unrealized"], 20000)
        self.assertEqual([r["kind"] for r in state["bills"]], ["outflow"])
        self.finance(position, book, account, "redeem", 100000, 120000, day="2026-11-16")
        state = self.state()
        self.assertEqual(state["accounts"][0]["balance"], 120000)
        self.assertEqual(state["positions"][0]["cost"], 0)
        self.assertEqual(state["positions"][0]["market"], 0)
        self.assertEqual(state["positions"][0]["realized"], 20000)
        self.assertEqual([r["amount"] for r in state["bills"] if r["kind"]=="income"], [20000])

    def test_stage4_partial_loss_edit_does_not_leave_stale_funding(self):
        book, other, account = self.baseline()
        position = self.post("position", kind="invest", owner="family", name="基金")["id"]
        purchase = self.finance(position, book, account, "buy", 100000, day="2026-11-14")
        redemption = self.finance(position, book, account, "redeem", 40000, 30000)
        state = self.state()
        self.assertEqual(state["positions"][0]["cost"], 60000)
        self.assertEqual(state["positions"][0]["realized"], -10000)
        self.assertEqual(state["accounts"][0]["balance"], 30000)
        self.assertEqual([r["amount"] for r in state["bills"] if r["kind"]=="expense"], [10000])
        with self.assertRaises(HTTPError):
            self.post("delete_event", id=purchase)
        self.assertEqual(self.state(), state)
        self.finance(position, book, account, "redeem", 40000, 45000, id=redemption)
        self.assertEqual(self.state()["accounts"][0]["balance"], 45000)
        self.assertFalse(any(r["kind"]=="expense" for r in self.state()["bills"]))

    def file_action(self, action, path, **extra):
        return self.post(action, endpoint="files", path=str(path), **extra)

    def test_stage5_backup_preview_complete_restore_and_pre_restore_snapshot(self):
        book, other, account = self.baseline()
        self.post("bill", **self.spending(book, account))
        self.post("category_enabled", id=6, enabled=False)
        invest = self.post("position", kind="invest", owner="personal", name="理财")["id"]
        self.finance(invest, book, account, "buy", 20000)
        self.post("position", kind="borrow", owner="family", name="借款", book_id=book,
                  account_id=account, day="2026-11-14", principal=10000)
        self.post("archive", id=other, archived=True)
        directory = self.path.parent / "备份 中文"
        directory.mkdir()
        backup = self.file_action("backup",directory)
        baseline = self.state()
        self.assertTrue(Path(backup["path"]).is_file())
        self.assertEqual(baseline["last_backup"],backup["time"])
        self.post("book", name="只存在于旧数据")
        metadata = self.file_action("preview",backup["path"])
        self.assertEqual((metadata["books"],metadata["bills"],metadata["time"]),(2,3,backup["time"]))
        token = self.app.token
        result = self.file_action("restore",backup["path"],fingerprint=metadata["fingerprint"])
        state = self.state()
        self.assertNotEqual(state["instance"],baseline["instance"])
        self.assertNotEqual(self.app.token, token)
        for table in ("books","categories","accounts","bills","positions"):
            self.assertEqual(state[table],baseline[table])
        with connect(result["backup"]) as old:
            self.assertEqual(old.execute("SELECT count(*) FROM books").fetchone()[0],3)

    def test_stage5_invalid_cancel_changed_backup_and_backup_failure_preserve_data(self):
        book, other, account = self.baseline()
        invalid = self.path.parent / "invalid.db"
        invalid.write_text("not a database")
        with self.assertRaises(HTTPError) as error:
            self.file_action("preview",invalid)
        self.assertEqual(error.exception.code,400)
        backup = Path(self.file_action("backup",self.path.parent)["path"])
        preview = self.file_action("preview",backup)
        self.post("bill", **self.spending(book, account))
        before = self.state()
        # Closing preview without confirming must not affect current data.
        self.file_action("preview",backup)
        self.assertEqual(self.state(),before)
        with self.assertRaises(HTTPError):
            self.file_action("restore",backup,fingerprint="not-the-previewed-file")
        with patch("backups.create_restore_backup", side_effect=PermissionError("injected")):
            with self.assertRaises(HTTPError) as error:
                self.file_action("restore",backup,fingerprint=preview["fingerprint"])
            self.assertEqual(error.exception.code,500)
        self.assertEqual(self.state(),before)
        self.assertEqual(self.file_action("preview",backup)["fingerprint"],preview["fingerprint"])

    def test_stage5_rolls_back_when_reopening_replacement_fails(self):
        import backups
        book, other, account = self.baseline()
        backup = self.file_action("backup",self.path.parent)
        preview = self.file_action("preview",backup["path"])
        self.post("bill", **self.spending(book, account))
        before = self.state()
        original_validate = backups.validate
        def fail_after_replacement(path):
            if path == self.path.resolve():
                raise ValueError("injected reopen failure")
            return original_validate(path)
        with patch("backups.validate",side_effect=fail_after_replacement):
            with self.assertRaises(HTTPError):
                self.file_action("restore",backup["path"],fingerprint=preview["fingerprint"])
        self.assertEqual(self.state(),before)

    def test_stage6_new_windows_process_reads_saved_data(self):
        book, other, account = self.baseline()
        self.post("bill", **self.spending(book, account))
        self.stop(self.app, self.thread)
        with subprocess.Popen(
            [sys.executable, "app.py", "--db", str(self.path), "--port", "0", "--no-browser"],
            cwd=Path(__file__).parent, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        ) as process:
            try:
                line = process.stdout.readline()
                self.assertTrue(line.startswith("My Record APP: "), line)
                origin = line.strip().removeprefix("My Record APP: ")
                with urlopen(origin+"/api/state",timeout=5) as answer:
                    data = json.load(answer)
                self.assertEqual(data["accounts"][0]["balance"],80000)
                self.assertEqual(data["bills"][0]["note"],"买菜")
                with urlopen(origin+"/",timeout=5) as answer:
                    self.assertIn("首页总览",answer.read().decode())
            finally:
                process.terminate()
                process.wait(timeout=5)

    def test_stage6_rejects_cross_origin_and_missing_token(self):
        for origin,token in [("http://unrelated.test",self.app.token),(self.app.origin,"")]:
            request = Request(self.app.origin+"/api/action", b"{}", {"Origin":origin,"X-Record-Token":token})
            with self.assertRaises(HTTPError) as error:
                urlopen(request,timeout=5)
            self.assertEqual(error.exception.code,403)
            error.exception.close()
        self.assertEqual(self.state()["books"],[])

    def test_stage1_shell_navigation_and_settings(self):
        html = self.get("/").decode()
        for route in ("home", "bills", "stats", "categories", "assets", "settings"):
            self.assertIn(f'href="#{route}"', html)
        self.assertIn(b"/api/session", self.get("/ui.js"))
        self.assertIn('src="/assets.js"',html)
        self.assertIn(b"const AssetUI",self.get("/assets.js"))
        self.assertEqual(Path(json.loads(self.get("/api/session"))["database"]), self.path.resolve())
        self.assertEqual(self.app.server_address[0], "127.0.0.1")

    def test_start_with_occupied_port_opens_current_app_on_new_port(self):
        with subprocess.Popen(
            [sys.executable,"app.py","--db",str(self.path.parent/"new.db"),
             "--port",str(self.app.server_port),"--no-browser"],
            cwd=Path(__file__).parent,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True
        ) as process:
            try:
                first=process.stdout.readline()
                self.assertIn("occupied",first)
                line=process.stdout.readline()
                self.assertTrue(line.startswith("My Record APP: "),line)
                origin=line.strip().removeprefix("My Record APP: ")
                self.assertNotEqual(origin,self.app.origin)
                with urlopen(origin+"/assets.js",timeout=5) as response:
                    self.assertIn(b"const AssetUI",response.read())
                with urlopen(origin+"/api/state",timeout=5) as response:
                    self.assertIn("portfolio",json.load(response))
            finally:
                process.terminate()
                process.wait(timeout=5)

    def test_stage1_reopen_preserves_database(self):
        with connect(self.path) as db:
            db.execute("INSERT INTO settings VALUES ('proof','present')")
        self.stop(self.app, self.thread)
        self.start()
        with connect(self.path) as db:
            self.assertEqual(db.execute("SELECT value FROM settings WHERE key='proof'").fetchone()[0], "present")
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_stage1_rejects_unexpected_host(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.app.origin + "/api/session", headers={"Host": "example.test"}))
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
