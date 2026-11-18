"""Offline category icons and additive, one-time category presets."""
ICONS = {"meal":"🍚","shop":"🛍️","home":"🏠","bus":"🚌","vegetable":"🥦","fruit":"🍎",
         "snack":"🧁","sport":"🏸","game":"🎮","phone":"☎️","clothes":"👕","beauty":"🪞",
         "family":"💗","people":"👥","travel":"✈️","wine":"🍷","digital":"📷","car":"🚙",
         "health":"🩺","book":"📚","study":"🎓","pet":"🐱","gift":"🎁","office":"💻",
         "repair":"🔧","charity":"💝","lottery":"🎟️","redpacket":"🧧","delivery":"📦",
         "drink":"🧋","star":"⭐","fine":"⚖️","work":"💼","salary":"💳","rent":"🏡",
         "money":"💰","growth":"📈","bonus":"🏅","interest":"🪙","water":"💧","other":"🌿"}
PRESETS = {
 "expense": [("餐饮","meal",[("早餐","meal"),("午餐","meal"),("晚餐","meal"),("蔬菜","vegetable"),("水果","fruit"),("零食","snack"),("饮品","drink")]),
 ("交通","bus",[("公共交通","bus"),("打车","car"),("停车","car")]),
 ("居住","home",[("水电费","water"),("房租","rent"),("物业费","home")]),
 ("日常购物","shop",[("日用品","shop"),("服饰","clothes"),("数码","digital")]),
 ("运动","sport",[]),("娱乐","game",[("游戏","game"),("追星","star")]),
 ("通讯","phone",[]),("美容","beauty",[]),("家庭","family",[("育儿","family"),("长辈","family")]),
 ("社交","people",[("礼品","gift"),("礼金","money"),("红包","redpacket")]),
 ("旅行","travel",[]),("烟酒","wine",[]),("汽车","car",[("加油","car"),("保养","repair")]),
 ("医疗","health",[("药品","health"),("看诊","health")]),("学习","study",[("书籍","book"),("课程","study")]),
 ("宠物","pet",[]),("办公","office",[]),("维修","repair",[]),("捐赠","charity",[]),
 ("彩票","lottery",[]),("快递","delivery",[]),("罚款","fine",[]),("工会","work",[])],
 "income": [("工资","salary",[]),("红包","redpacket",[]),("租金","rent",[]),("礼金","money",[]),
 ("分红","people",[]),("年终奖","bonus",[]),("奖学金","study",[]),("兼职","work",[])]}


def ensure(db):
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    columns = [row[1] for row in db.execute("PRAGMA table_info(categories)")]
    if "icon" not in columns:
        db.execute("ALTER TABLE categories ADD COLUMN icon TEXT NOT NULL DEFAULT 'other'")
    if db.execute("SELECT 1 FROM settings WHERE key='category_presets_v1'").fetchone():
        return
    def insert(label,kind,icon,parent=None):
        row = db.execute("SELECT id FROM categories WHERE name=? AND kind=? AND parent_id IS ?",(label,kind,parent)).fetchone()
        if row:
            db.execute("UPDATE categories SET icon=? WHERE id=? AND icon='other'",(icon,row[0]))
            return row[0]
        return db.execute("INSERT INTO categories(name,kind,parent_id,icon) VALUES (?,?,?,?)",(label,kind,parent,icon)).lastrowid
    for kind, groups in PRESETS.items():
        for label, icon, children in groups:
            parent = insert(label,kind,icon)
            for child, symbol in children:
                insert(child,kind,symbol,parent)
    for label,icon in [("利息收入","interest"),("利息支出","interest"),("投资收益","growth"),("投资亏损","growth")]:
        db.execute("UPDATE categories SET icon=? WHERE name=? AND icon='other'",(icon,label))
    db.execute("INSERT INTO settings VALUES ('category_presets_v1','1')")
