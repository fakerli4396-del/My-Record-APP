"""Repair only recognizable OCR artifacts, retaining a recoverable source backup."""
import json
from image_import import clean_name

def plan(db):
    rows=[dict(r) for r in db.execute("SELECT * FROM positions WHERE kind IN ('borrow','lend')")]
    renames=[(p["id"],clean_name(p["name"])) for p in rows if clean_name(p["name"]) and clean_name(p["name"])!=p["name"]]
    def signature(p):
        events=[tuple(e) for e in db.execute("SELECT kind,day,book_id,account_id,principal,extra,note,opening_only FROM finance_events WHERE position_id=? ORDER BY day,id",(p["id"],))]
        if len(events)!=1 or events[0][0]!="origin" or not events[0][-1]:
            return None
        config=db.execute("SELECT book_id,annual_rate FROM loan_plans WHERE position_id=?",(p["id"],)).fetchone()
        months=[tuple(r) for r in db.execute("SELECT month,amount FROM installments WHERE position_id=? ORDER BY month",(p["id"],))]
        return (p["kind"],p["owner"],p["due"],p["note"],tuple(events),tuple(config) if config else None,tuple(months))
    signatures={p["id"]:signature(p) for p in rows}
    removed=[]
    for p in rows:
        if clean_name(p["name"]) or signatures[p["id"]] is None:continue
        if any(clean_name(other["name"]) and signatures[other["id"]]==signatures[p["id"]] for other in rows):
            referenced=any(any(r.get("kind")=="position" and r.get("id")==p["id"] for r in json.loads(x[0]))
                           for x in db.execute("SELECT records FROM inventories"))
            if not referenced:removed.append(p["id"])
    forecasts=[(r["id"],clean_name(r["name"])) for r in db.execute("SELECT id,name FROM forecast_items")
               if clean_name(r["name"]) and clean_name(r["name"])!=r["name"]]
    return dict(renames=renames,removed=removed,forecasts=forecasts)

def apply(db,changes):
    for key,label in changes["renames"]:db.execute("UPDATE positions SET name=? WHERE id=?",(label,key))
    for key,label in changes["forecasts"]:db.execute("UPDATE forecast_items SET name=? WHERE id=?",(label,key))
    for key in changes["removed"]:
        db.execute("DELETE FROM installments WHERE position_id=?",(key,))
        db.execute("DELETE FROM loan_plans WHERE position_id=?",(key,))
        db.execute("DELETE FROM finance_events WHERE position_id=?",(key,))
        db.execute("DELETE FROM positions WHERE id=?",(key,))
    if any(changes.values()):
        db.execute("INSERT OR REPLACE INTO settings VALUES ('ocr_repair',?)",
                   (json.dumps(dict(renamed=len(changes["renames"])+len(changes["forecasts"]),duplicates=len(changes["removed"]))),))
