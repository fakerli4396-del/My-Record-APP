"""Consistent snapshots and guarded replacement of the local database."""
from contextlib import closing
from datetime import datetime
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from uuid import uuid4

import ledger
import portfolio
import inventory
import catalog


def user_path(value):
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ValueError("请输入完整的本地路径")
    candidate = Path(value.strip())
    if not candidate.is_absolute() or str(candidate).startswith(("\\\\", "//")):
        raise ValueError("请选择此电脑上的完整路径")
    return candidate.resolve()


def clock():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def readonly(path):
    db = sqlite3.connect(path.as_uri()+"?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def validate(path):
    try:
        with closing(readonly(path)) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 1:
                with tempfile.TemporaryDirectory(dir=path.parent) as work:
                    staged = Path(work) / "upgraded.db"
                    snapshot(path,staged)
                    upgrade_copy(staged)
                    return validate(staged)
            if version != 2:
                raise ValueError("备份版本不受支持")
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("备份文件或关联数据已损坏")
            db.execute("SELECT key,result_id FROM requests LIMIT 1").fetchall()
            state = ledger.snapshot(db)
            for account in state["accounts"]:
                if account["account_type"] not in portfolio.ACCOUNT_TYPES or account["owner"] not in ("family","personal"):
                    raise ValueError("备份账户配置无效")
                ledger.day(account["opening_day"])
            for position in state["positions"]:
                if position["kind"] not in portfolio.SUBTYPES or position["subtype"] not in portfolio.SUBTYPES[position["kind"]]:
                    raise ValueError("备份资产类型无效")
            event_ids = {event["id"] for p in state["positions"] for event in p["events"]}
            if any(row["source_type"] and row["source_id"] not in event_ids for row in state["bills"]):
                raise ValueError("备份中的业务流水关联已损坏")
            row = db.execute("SELECT value FROM settings WHERE key='snapshot_time'").fetchone()
            return {"time":row[0] if row else None,"books":len(state["books"]),"bills":len(state["bills"])}
    except sqlite3.Error as error:
        raise ValueError("所选文件不是有效的账本备份") from error


def upgrade_copy(path):
    with closing(sqlite3.connect(path)) as db, db:
        portfolio.upgrade(db)
        catalog.ensure(db)
        inventory.ensure(db)


def stamp(path, key, value):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key,value))


def snapshot(source, destination):
    with closing(readonly(source)) as original, closing(sqlite3.connect(destination)) as copy:
        original.backup(copy)


def create_backup(source, folder, *, record=True):
    if not folder.is_dir():
        raise ValueError("备份目录不存在")
    timestamp = clock()
    basename = "MyRecord-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
    final = folder / (basename + ".db")
    with tempfile.TemporaryDirectory(dir=folder) as work:
        staged = Path(work) / "snapshot.db"
        snapshot(source, staged)
        stamp(staged, "snapshot_time", timestamp)
        validate(staged)
        os.replace(staged, final)
    if record:
        stamp(source, "last_backup", timestamp)
    return {"path":str(final), "time":timestamp}


def copy_and_hash(source, target):
    digest = hashlib.sha256()
    with source.open("rb") as incoming, target.open("wb") as outgoing:
        for block in iter(lambda: incoming.read(1024*1024), b""):
            digest.update(block)
            outgoing.write(block)
    return digest.hexdigest()


def check_source(database, source):
    if not source.is_file() or source.samefile(database):
        raise ValueError("请选择独立的账本备份文件")


def preview(database, source):
    check_source(database, source)
    with tempfile.TemporaryDirectory(dir=database.parent) as work:
        candidate = Path(work) / "preview.db"
        fingerprint = copy_and_hash(source,candidate)
        return dict(validate(candidate),fingerprint=fingerprint)


def restore(database, source, fingerprint):
    check_source(database, source)
    with tempfile.TemporaryDirectory(dir=database.parent) as work:
        candidate = Path(work) / "restore.db"
        if copy_and_hash(source,candidate) != fingerprint:
            raise ValueError("备份内容已变化，请重新预览")
        validate(candidate)
        upgrade_copy(candidate)
        backup = create_restore_backup(database)
        stamp(candidate,"last_backup",backup["time"])
        validate(candidate)
        rollback = Path(work) / "rollback.db"
        snapshot(database,rollback)
        os.replace(candidate,database)
        try:
            validate(database)
        except (ValueError,OSError):
            os.replace(rollback,database)
            raise
        return {"backup":backup["path"]}


def create_restore_backup(database):
    folder = database.parent / "restore-backups"
    folder.mkdir(exist_ok=True)
    return create_backup(database,folder,record=False)


def choose_path(action):
    chooser = """
import json
import sys
import tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
root.attributes('-topmost', True)
try:
    path = filedialog.askdirectory(title='选择备份目录') if sys.argv[1]=='browse_folder' else filedialog.askopenfilename(
        title='选择账本备份', filetypes=[('账本备份','*.db'),('所有文件','*.*')])
    print(json.dumps({'path':path}))
finally:
    root.destroy()
"""
    result = subprocess.run([sys.executable,"-c",chooser,action],capture_output=True,text=True)
    if result.returncode:
        raise ValueError("无法打开文件选择器，可以直接输入完整路径")
    import json
    return json.loads(result.stdout)
