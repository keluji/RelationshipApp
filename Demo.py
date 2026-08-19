import sys
import math
import sqlite3
import os
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPen, QBrush, QColor, QAction
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QToolBar,
    QListWidget,
    QListWidgetItem,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsEllipseItem,
    QGraphicsTextItem,
    QGraphicsLineItem,
    QComboBox,
    QStatusBar,
    QDialog,
    QFormLayout,
    QLineEdit,
    QDialogButtonBox,
    QSplitter,
    QWidget,
    QHBoxLayout
)

DB_FILE = "relation.db"

# ---------------------- 数据库初始化 ----------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    # 人物表
    cur.execute('''
    CREATE TABLE IF NOT EXISTS person (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        pos_x REAL DEFAULT 0,
        pos_y REAL DEFAULT 0
    )
    ''')
    # 关系表
    cur.execute('''
    CREATE TABLE IF NOT EXISTS relation (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_a INTEGER,
        person_b INTEGER,
        rel_name TEXT,
        FOREIGN KEY(person_a) REFERENCES person(id),
        FOREIGN KEY(person_b) REFERENCES person(id)
    )
    ''')
    conn.commit()
    conn.close()

# 保存全部数据
def save_data(nodes, lines):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    # 清空旧数据
    cur.execute("DELETE FROM person")
    cur.execute("DELETE FROM relation")
    # 写入人物
    for pid, node in nodes.items():
        p = node.pos()
        cur.execute("INSERT INTO person(id, name, pos_x, pos_y) VALUES (?,?,?,?)",
                    (pid, node.name, p.x(), p.y()))
    # 写入关系
    for line in lines:
        cur.execute("INSERT INTO relation(person_a, person_b, rel_name) VALUES (?,?,?)",
                    (line.node_a.person_id, line.node_b.person_id, line.relation_name))
    conn.commit()
    conn.close()

# 读取全部数据
def load_data():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, name, pos_x, pos_y FROM person")
    person_rows = cur.fetchall()
    cur.execute("SELECT person_a, person_b, rel_name FROM relation")
    rel_rows = cur.fetchall()
    conn.close()
    return person_rows, rel_rows

# ---------------------- 画布节点类（人物节点） ----------------------
class PersonNode(QGraphicsEllipseItem):
    def __init__(self, person_id, name):
        super().__init__(-40, -25, 80, 50)
        self.person_id = person_id
        self.name = name
        self.setBrush(QBrush(QColor("#ffffff")))
        self.setPen(QPen(QColor("#000000"), 2))
        self.setFlags(self.ItemIsMovable | self.ItemIsSelectable | self.ItemSendsGeometryChanges)

        self.text = QGraphicsTextItem(name, self)
        self.text.setDefaultTextColor(Qt.black)
        self.text.setPos(-35, -15)

    def itemChange(self, change, value):
        if change == self.ItemPositionChange:
            for line in self.scene().lines:
                line.update_line()
        return super().itemChange(change, value)

# ---------------------- 连线类（人物关系） ----------------------
class RelationLine(QGraphicsLineItem):
    def __init__(self, node_a, node_b, relation_name):
        super().__init__()
        self.node_a = node_a
        self.node_b = node_b
        self.relation_name = relation_name
        self.setPen(QPen(QColor("#333333"), 2))
        self.text = QGraphicsTextItem(relation_name)
        self.text.setDefaultTextColor(Qt.black)
        self.update_line()

    def update_line(self):
        p1 = self.node_a.pos()
        p2 = self.node_b.pos()
        self.setLine(p1.x(), p1.y(), p2.x(), p2.y())
        mid = (p1 + p2) / 2
        self.text.setPos(mid)

# ---------------------- 主窗口 ----------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("人物关系图谱工具（离线本地）")
        self.resize(1200, 800)
        self.person_id_counter = 1
        self.nodes = {}
        self.lines = []

        # ========== 顶部工具栏 ==========
        self.toolbar = QToolBar("Tools")
        self.addToolBar(self.toolbar)

        self.action_add_person = QAction("新增人物", self)
        self.action_add_person.triggered.connect(self.add_person_dialog)

        self.action_add_relation = QAction("新增关系", self)
        self.action_add_relation.triggered.connect(self.add_relation_dialog)

        self.action_del = QAction("删除选中", self)
        self.action_del.triggered.connect(self.delete_selected)

        self.action_fit = QAction("自适应视图", self)
        self.action_fit.triggered.connect(self.fit_view)

        self.action_save = QAction("手动保存", self)
        self.action_save.triggered.connect(self.manual_save)

        self.toolbar.addAction(self.action_add_person)
        self.toolbar.addAction(self.action_add_relation)
        self.toolbar.addAction(self.action_del)
        self.toolbar.addAction(self.action_fit)
        self.toolbar.addAction(self.action_save)

        # ========== 中心部件 + 分割布局 ==========
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        h_layout = QHBoxLayout(central_widget)
        self.splitter = QSplitter(Qt.Horizontal)

        # 左侧人物列表
        self.list_person = QListWidget()
        self.list_person.setFixedWidth(180)
        self.list_person.itemClicked.connect(self.on_list_click)

        # 中央画布
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.scene.lines = self.lines
        self.view.setDragMode(QGraphicsView.RubberBandDrag)

        self.splitter.addWidget(self.list_person)
        self.splitter.addWidget(self.view)
        h_layout.addWidget(self.splitter)

        # ========== 底部状态栏 + 右下角Mode下拉框 ==========
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["自由布局", "环形自动布局"])
        self.mode_combo.currentIndexChanged.connect(self.switch_layout_mode)
        self.status_bar.addPermanentWidget(self.mode_combo)

        # 加载历史数据
        self.load_history_data()

    def load_history_data(self):
        person_rows, rel_rows = load_data()
        if not person_rows:
            return
        max_id = 0
        for pid, name, x, y in person_rows:
            node = PersonNode(pid, name)
            node.setPos(x, y)
            self.scene.addItem(node)
            self.nodes[pid] = node
            QListWidgetItem(name, self.list_person)
            if pid > max_id:
                max_id = pid
        self.person_id_counter = max_id + 1

        for aid, bid, rel_name in rel_rows:
            na = self.nodes.get(aid)
            nb = self.nodes.get(bid)
            if na and nb:
                line = RelationLine(na, nb, rel_name)
                self.scene.addItem(line)
                self.scene.addItem(line.text)
                self.lines.append(line)

    def manual_save(self):
        save_data(self.nodes, self.lines)
        self.status_bar.showMessage("✅ 数据已保存到 relation.db", 2000)

    # 关闭窗口自动保存
    def closeEvent(self, event):
        save_data(self.nodes, self.lines)
        event.accept()

    # 添加人物弹窗
    def add_person_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("新增人物")
        layout = QFormLayout(dlg)
        edit_name = QLineEdit()
        layout.addRow("人物姓名：", edit_name)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        if dlg.exec():
            name = edit_name.text().strip()
            if not name:
                return
            pid = self.person_id_counter
            self.person_id_counter += 1
            node = PersonNode(pid, name)
            node.setPos(150 + len(self.nodes)*120, 200)
            self.scene.addItem(node)
            self.nodes[pid] = node
            QListWidgetItem(name, self.list_person)

    # 添加关系弹窗
    def add_relation_dialog(self):
        nodes_selected = [i for i in self.scene.selectedItems() if isinstance(i, PersonNode)]
        if len(nodes_selected) != 2:
            self.status_bar.showMessage("请框选2个人物节点！", 2000)
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("新增关系")
        layout = QFormLayout(dlg)
        edit_rel = QLineEdit()
        layout.addRow("关系描述：", edit_rel)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        if dlg.exec():
            rel_name = edit_rel.text().strip()
            if not rel_name:
                return
            line = RelationLine(nodes_selected[0], nodes_selected[1], rel_name)
            self.scene.addItem(line)
            self.scene.addItem(line.text)
            self.lines.append(line)

    # 删除选中节点/连线
    def delete_selected(self):
        for item in self.scene.selectedItems():
            if isinstance(item, RelationLine):
                self.scene.removeItem(item.text)
                self.lines.remove(item)
            elif isinstance(item, PersonNode):
                del self.nodes[item.person_id]
            self.scene.removeItem(item)
        self.refresh_list()

    def refresh_list(self):
        self.list_person.clear()
        for node in self.nodes.values():
            if node.scene():
                QListWidgetItem(node.name, self.list_person)

    # 左侧列表点击定位节点
    def on_list_click(self, item):
        for node in self.nodes.values():
            if node.name == item.text():
                self.view.centerOn(node)
                node.setSelected(True)

    def fit_view(self):
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    # 切换布局模式
    def switch_layout_mode(self, idx):
        if idx == 0:
            self.status_bar.showMessage("已切换：自由布局（手动拖拽节点）", 2000)
        else:
            self.auto_layout()
            self.status_bar.showMessage("已切换：环形自动布局", 2000)

    # 简易自动布局（环形排布）
    def auto_layout(self):
        node_list = list(self.nodes.values())
        count = len(node_list)
        if count <= 1:
            return
        r = 250
        center = QPointF(400, 300)
        for i, n in enumerate(node_list):
            angle = 2 * math.pi * i / count
            x = center.x() + r * math.cos(angle)
            y = center.y() + r * math.sin(angle)
            n.setPos(x, y)

if __name__ == "__main__":
    init_db()
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
class my_class(object):
    pass




