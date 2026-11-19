import base64
import json
import unittest
from pathlib import Path
from urllib.error import HTTPError
import test_workspace as support
import image_import

class ImprovementsTests(unittest.TestCase):
    setUp=support.WorkspaceTests.setUp
    start=support.WorkspaceTests.start
    stop=staticmethod(support.WorkspaceTests.stop)
    get=support.WorkspaceTests.get
    post=support.WorkspaceTests.post
    state=support.WorkspaceTests.state
    baseline=support.WorkspaceTests.baseline
    def test_active_book_persists_and_archived_book_rejected(self):
        book,other,_=self.baseline()
        self.post("current_book",book_id=other)
        self.assertEqual(self.state()["current_book"],str(other))
        self.stop(self.app,self.thread);self.start()
        self.assertEqual(self.state()["current_book"],str(other))
        self.post("archive",id=other,archived=True)
        with self.assertRaises(HTTPError):self.post("current_book",book_id=other)
        self.post("current_book",book_id=book)
        self.post("budget",book_id=book,month="2026-11",amount=10000)
        self.assertEqual(self.state()["budgets"][0]["book_id"],book)

    def test_upload_and_legacy_workbook_without_new_sheets(self):
        book,_,_=self.baseline()
        for fmt in ("db","xls","xlsx"):
            file=self.post("export_data",endpoint="files",format=fmt,book="",owner="all",path=str(self.path.parent))["path"]
            if fmt=="xlsx":
                import openpyxl
                wb=openpyxl.load_workbook(file)
                for name in ("信用卡计划","信用卡月度计划","预计月度项目","图片导入记录"):
                    del wb[name]
                wb.save(file);wb.close()
            preview=self.post("import_upload",endpoint="files",name="选择文件."+fmt,content=base64.b64encode(Path(file).read_bytes()).decode())
            self.post("import_restore",endpoint="files",path=preview["path"],fingerprint=preview["fingerprint"])
            self.assertEqual(self.state()["books"][0]["id"],book)

    def test_image_review_import_atomic_retry_and_backup(self):
        book,_,_=self.baseline()
        data=dict(book_id=book,owner="family",kind="borrow",year=2026,day="2026-11-19",items=[
            dict(name="京东金条",mode="loan",principal=2780545,annual_rate="3",months=[0]*4+[660096,670264]+[0]*6),
            dict(name="计划费用",mode="plan",principal=None,annual_rate="",months=[10000]*12)])
        result=self.post("image_import",**data)
        self.assertEqual(self.post("image_import",**data),result)
        state=self.state()
        self.assertEqual(state["portfolio"]["family"]["current"]["debts"],2780545)
        self.assertEqual(len(state["forecast_items"]),1)
        self.assertEqual(len(state["bills"]),0)
        bad=json.loads(json.dumps(data));bad["items"][0]["name"]="新行";bad["items"][1]["months"][0]=None
        with self.assertRaises(HTTPError):self.post("image_import",**bad)
        self.assertEqual(self.state(),state)
        exported=self.post("export_data",endpoint="files",format="xlsx",book="",owner="all",path=str(self.path.parent))
        preview=self.post("import_preview",endpoint="files",path=exported["path"])
        self.post("import_restore",endpoint="files",path=exported["path"],fingerprint=preview["fingerprint"])
        self.assertEqual(self.state()["forecast_items"],state["forecast_items"])

    def test_windows_ocr_recognizes_a_real_table_image(self):
        from PIL import Image,ImageDraw,ImageFont
        image=Image.new("RGB",(1800,250),"white");draw=ImageDraw.Draw(image)
        font=ImageFont.truetype("C:/Windows/Fonts/simhei.ttf",32)
        for x,text in [(20,"年化"),(160,"项目"),(420,"我的欠款"),(720,"5月应还"),(1050,"6月应还"),(1380,"7月应还")]:
            draw.text((x,20),text,font=font,fill="black")
        for y,name,p,a,b,c in [(100,"京东金条","27805.45","6600.96","6702.64","6830.29"),(175,"支付宝借呗","184809","297","405","419")]:
            for x,text in [(20,"3%"),(160,name),(420,p),(720,a),(1050,b),(1380,c)]:
                draw.text((x,y),text,font=font,fill="black")
        file=self.path.parent/"ocr.png";image.save(file)
        result=image_import.recognize(dict(content=base64.b64encode(file.read_bytes()).decode()))
        self.assertEqual(len(result["items"]),2,result)
        first=result["items"][0]
        self.assertEqual(first["principal"],2780545,result)
        self.assertEqual(first["months"][4:7],[660096,670264,683029],result)
        self.assertEqual(first["annual_rate"],"3",result)
