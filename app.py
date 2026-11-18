"""My Record APP local HTTP entry point."""
import argparse
import errno
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sqlite3
import socket
import threading
import webbrowser
from urllib.parse import urlsplit, parse_qs

import ledger
import backups
import portfolio

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "My Record APP" / "record.db"
SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@contextmanager
def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2):
            raise ValueError("数据库版本不受支持")
        if version == 1:
            from contextlib import closing
            from datetime import datetime
            backup_folder = path.parent / "upgrade-backups"
            backup_folder.mkdir(exist_ok=True)
            target = backup_folder / ("before-v2-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".db")
            with closing(sqlite3.connect(target)) as copy:
                db.backup(copy)
        if version == 0:
            db.executescript("BEGIN;\n" + SCHEMA + ledger.SCHEMA + "\nPRAGMA user_version = 1;\nCOMMIT;")
        portfolio.upgrade(db)


class Application(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket,"SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()

    def __init__(self, database, port=0):
        self.database = Path(database).resolve()
        initialize(self.database)
        self.token = secrets.token_urlsafe(32)
        self.instance = secrets.token_urlsafe(18)
        self.lock = threading.RLock()
        super().__init__(("127.0.0.1", port), Handler)

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, status, content_type, content):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, status, payload):
        self.send_bytes(status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode())

    def valid_host(self):
        return self.headers.get("Host") == self.server.origin.removeprefix("http://")

    def do_GET(self):
        if not self.valid_host():
            return self.send_json(403, {"error": "请通过本机应用地址访问"})
        if self.path == "/api/session":
            return self.send_json(200, {"database": str(self.server.database), "token": self.server.token, "instance": self.server.instance})
        if self.path == "/api/state":
            try:
                with self.server.lock, connect(self.server.database) as db:
                    return self.send_json(200, dict(ledger.snapshot(db), instance=self.server.instance))
            except (sqlite3.Error, ValueError):
                return self.send_json(500, {"error": "无法读取本地数据"})
        if urlsplit(self.path).path == "/api/portfolio":
            try:
                query = parse_qs(urlsplit(self.path).query)
                with self.server.lock, connect(self.server.database) as db:
                    result = portfolio.report(db,query.get("owner",["family"])[0],int(query.get("year",["0"])[0]))
                return self.send_json(200,result)
            except (ValueError,sqlite3.Error):
                return self.send_json(400,{"error":"资产图表参数或数据无效"})
        files = {"/": ("index.html", "text/html"), "/style.css": ("style.css", "text/css"),
                 "/ui.js": ("ui.js", "text/javascript"), "/reports.js": ("reports.js", "text/javascript"),
                 "/assets.js": ("assets.js", "text/javascript")}
        if self.path in files:
            name, content_type = files[self.path]
            return self.send_bytes(200, content_type + "; charset=utf-8", (ROOT / name).read_bytes())
        self.send_json(404, {"error": "页面不存在"})

    def do_POST(self):
        if not self.valid_host() or self.headers.get("Origin") != self.server.origin or not secrets.compare_digest(
            self.headers.get("X-Record-Token", ""), self.server.token
        ):
            return self.send_json(403, {"error": "请求来源无效，请刷新页面"})
        if self.path not in ("/api/action", "/api/files"):
            return self.send_json(404, {"error": "操作不存在"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                raise ValueError("请求内容大小无效")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("请求格式无效")
            if self.path=="/api/files" and data.get("action") in ("browse_folder","browse_file"):
                result = backups.choose_path(data["action"])
            else:
                with self.server.lock:
                    if not secrets.compare_digest(self.headers.get("X-Record-Token", ""), self.server.token):
                        return self.send_json(409, {"error": "数据已恢复，请刷新页面后重试"})
                    result = self.perform(data) if self.path=="/api/action" else self.files(data)
            self.send_json(200, result)
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except OSError:
            self.send_json(500, {"error": "无法访问所选文件或目录，请检查路径、权限和磁盘空间"})
        except sqlite3.IntegrityError:
            self.send_json(400, {"error": "数据重复或关联记录无效"})
        except sqlite3.Error:
            self.send_json(500, {"error": "无法写入本地数据，请检查文件和磁盘后重试"})

    def files(self, data):
        action = data.get("action")
        path = self.server.database
        if action == "backup":
            return backups.create_backup(path, backups.user_path(data.get("path")))
        if action == "preview":
            return backups.preview(path, backups.user_path(data.get("path")))
        if action == "restore":
            result = backups.restore(path, backups.user_path(data.get("path")), data.get("fingerprint"))
            self.server.token = secrets.token_urlsafe(32)
            self.server.instance = secrets.token_urlsafe(18)
            return result
        raise ValueError("未知文件操作")

    def perform(self, data):
        with connect(self.server.database) as db:
            return ledger.action(db, data)

    def log_message(self, format, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        server = Application(args.db, args.port)
    except OSError as error:
        if error.errno != errno.EADDRINUSE and getattr(error, "winerror", None) != 10048:
            raise
        server = Application(args.db, 0)
        print("Requested port is occupied. Opening a new local app address.", flush=True)
    with server as app:
        print(f"My Record APP: {app.origin}", flush=True)
        if not args.no_browser:
            threading.Thread(target=webbrowser.open, args=(app.origin,), daemon=True).start()
        try:
            app.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
