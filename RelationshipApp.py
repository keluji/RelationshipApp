import sys
import math
import sqlite3
from PySide6.QtCore import Qt, QPointF, QDate, QRectF, QMimeData
from PySide6.QtGui import (
    QPen, QBrush, QColor, QAction, QPainter, QFont, QClipboard,
    QIcon, QPixmap, QPainterPath, QCursor, QDrag
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QToolBar, QListWidget, QListWidgetItem,
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsPathItem,
    QGraphicsTextItem, QStatusBar, QDialog, QFormLayout, QLineEdit,
    QTextEdit, QDateEdit, QDialogButtonBox, QSplitter, QWidget,
    QHBoxLayout, QVBoxLayout, QLabel, QScrollArea, QPushButton,
    QFrame, QAbstractItemView, QMenu, QMessageBox, QToolButton
)

DB_FILE = "relation.db"
MIN_SAFE_DISTANCE = 100  # 节点安全距离，匹配卡片尺寸

# ---------------------- 数据库初始化（修复字段兼容问题） ----------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    # 创建表（不存在时才创建）
    cur.execute('''
    CREATE TABLE IF NOT EXISTS person (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        pos_x REAL DEFAULT NULL,
        pos_y REAL DEFAULT NULL,
        intro TEXT DEFAULT '',
        birth TEXT DEFAULT '',
        phone TEXT DEFAULT ''
    )
    ''')
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

    # 兼容旧库：自动追加缺失的phone字段
    try:
        cur.execute("ALTER TABLE person ADD COLUMN phone TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # 字段已存在则忽略

    conn.commit()
    conn.close()

def save_data(persons, nodes, lines):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM person")
    cur.execute("DELETE FROM relation")
    
    for pid, data in persons.items():
        node = nodes.get(pid)
        pos_x = node.pos().x() if node else None
        pos_y = node.pos().y() if node else None
        cur.execute("""
        INSERT INTO person(id, name, pos_x, pos_y, intro, birth, phone)
        VALUES (?,?,?,?,?,?,?)
        """, (pid, data["name"], pos_x, pos_y, data["intro"], data["birth"], data.get("phone", "")))
    
    for line in lines:
        cur.execute("INSERT INTO relation(person_a, person_b, rel_name) VALUES (?,?,?)",
                    (line["pid_a"], line["pid_b"], line["rel_name"]))
    conn.commit()
    conn.close()

def load_data():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, name, pos_x, pos_y, intro, birth, phone FROM person")
    person_rows = cur.fetchall()
    cur.execute("SELECT person_a, person_b, rel_name FROM relation")
    rel_rows = cur.fetchall()
    conn.close()
    return person_rows, rel_rows

# ---------------------- 自定义画布视图 ----------------------
class RelationGraphicsView(QGraphicsView):
    def __init__(self, scene, main_window):
        super().__init__(scene)
        self.main_window = main_window
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAcceptDrops(True)  # 接受拖放

    def wheelEvent(self, event):
        # 仅Ctrl+滚轮无级缩放，普通滚轮无效果
        if event.modifiers() & Qt.ControlModifier:
            scale_factor = 1.15
            if event.angleDelta().y() < 0:
                scale_factor = 1.0 / scale_factor
            self.scale(scale_factor, scale_factor)
        event.accept()

    def mousePressEvent(self, event):
        # 单击节点选中，严格单选
        if event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.position().toPoint())
            item = self.scene().itemAt(scene_pos, self.transform())
            self.scene().clearSelection()
            if isinstance(item, PersonNode):
                item.setSelected(True)
        super().mousePressEvent(event)

    # 拖入事件
    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/person-id"):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/person-id"):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasFormat("application/person-id"):
            pid = int(event.mimeData().data("application/person-id").data())
            scene_pos = self.mapToScene(event.position().toPoint())
            self.main_window.create_node_at(pid, scene_pos)
            event.acceptProposedAction()

# ---------------------- 圆角正方形人物卡片 ----------------------
class PersonNode(QGraphicsItem):
    def __init__(self, person_id, name, intro="", birth="", phone=""):
        super().__init__()
        self.person_id = person_id
        self.name = name
        self.intro = intro
        self.birth = birth
        self.phone = phone

        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setZValue(10)  # 最高层级，覆盖连线

    def boundingRect(self):
        return QRectF(-45, -45, 90, 90)  # 90x90 适中尺寸

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.boundingRect()

        # 背景与边框
        if self.isSelected():
            painter.setBrush(QBrush(QColor("#eef4ff")))
            painter.setPen(QPen(QColor("#2563eb"), 2))
        else:
            painter.setBrush(QBrush(QColor("#ffffff")))
            painter.setPen(QPen(QColor("#cccccc"), 1.5))
        painter.drawRoundedRect(rect, 10, 10)

        # 居中姓名
        painter.setPen(QColor("#1f2937"))
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, self.name)

    def itemChange(self, change, value):
        # 位置变化时处理碰撞排斥 + 更新连线
        if change == QGraphicsItem.ItemPositionChange and self.scene() is not None:
            final_pos = self._resolve_collision(value, depth=0)
            for line in self.scene().lines:
                if "item" in line and line["item"] is not None:
                    line["item"].update_path()
            return final_pos
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        if self.scene() and hasattr(self.scene(), "main_window"):
            self.scene().main_window.show_person_detail(self)
        super().mouseDoubleClickEvent(event)

    def _resolve_collision(self, new_pos, depth):
        if depth > 20:
            return new_pos
        scene = self.scene()
        if not scene:
            return new_pos

        for item in scene.items():
            if not isinstance(item, PersonNode) or item is self:
                continue

            other_pos = item.pos()
            dx = new_pos.x() - other_pos.x()
            dy = new_pos.y() - other_pos.y()
            distance = math.sqrt(dx * dx + dy * dy)

            if distance < MIN_SAFE_DISTANCE:
                if distance == 0:
                    dx, dy = 1.0, 0.0
                    distance = 1.0

                push_dist = MIN_SAFE_DISTANCE - distance
                nx = dx / distance
                ny = dy / distance

                new_pos = QPointF(
                    new_pos.x() + nx * push_dist / 2,
                    new_pos.y() + ny * push_dist / 2
                )
                other_new_pos = QPointF(
                    other_pos.x() - nx * push_dist / 2,
                    other_pos.y() - ny * push_dist / 2
                )
                item.setPos(item._resolve_collision(other_new_pos, depth + 1))

        return new_pos

# ---------------------- 弯曲关系连线 ----------------------
class RelationLine(QGraphicsPathItem):
    def __init__(self, node_a, node_b, relation_name):
        super().__init__()
        self.node_a = node_a
        self.node_b = node_b
        self.relation_name = relation_name
        self.setZValue(5)  # 在节点下方

        self.setPen(QPen(QColor("#6b7280"), 1.5))
        self.text = QGraphicsTextItem(relation_name, self)
        self.text.setDefaultTextColor(QColor("#374151"))
        self.text.setScale(0.9)
        font = self.text.font()
        font.setPointSize(9)
        self.text.setFont(font)

        self.update_path()

    def update_path(self):
        p1 = self.node_a.pos()
        p2 = self.node_b.pos()
        
        # 计算贝塞尔曲线控制点（中点向上偏移，形成自然弯曲）
        mid = (p1 + p2) / 2
        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        length = math.sqrt(dx*dx + dy*dy)
        if length > 0:
            offset = length * 0.15  # 弯曲程度
            nx = -dy / length
            ny = dx / length
            control = mid + QPointF(nx * offset, ny * offset)
        else:
            control = mid

        # 绘制二次贝塞尔曲线
        path = QPainterPath()
        path.moveTo(p1)
        path.quadTo(control, p2)
        self.setPath(path)

        # 文字沿线路径居中放置
        text_rect = self.text.boundingRect()
        mid_point = path.pointAtPercent(0.5)
        self.text.setPos(mid_point.x() - text_rect.width()/2, mid_point.y() - text_rect.height()/2 - 8)

        # 文字随线条角度旋转
        angle = math.atan2(dy, dx) * 180 / math.pi
        # 保持文字正向，不倒置
        if angle > 90 or angle < -90:
            angle += 180
        self.text.setRotation(angle)
        self.text.setTransformOriginPoint(text_rect.center())

# ---------------------- 人物编辑弹窗 ----------------------
class EditPersonDialog(QDialog):
    def __init__(self, parent=None, node=None, person_data=None):
        super().__init__(parent)
        self.setWindowTitle("编辑人物信息" if (node or person_data) else "新增人物")
        layout = QFormLayout(self)

        self.edit_name = QLineEdit()
        self.edit_birth = QDateEdit()
        self.edit_birth.setCalendarPopup(True)
        self.edit_birth.setDisplayFormat("yyyy-MM-dd")
        self.edit_birth.setDate(QDate.currentDate())
        self.edit_phone = QLineEdit()  # 新增手机号
        self.edit_intro = QTextEdit()

        layout.addRow("姓名：", self.edit_name)
        layout.addRow("生日：", self.edit_birth)
        layout.addRow("手机号：", self.edit_phone)
        layout.addRow("简介：", self.edit_intro)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("确定")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        layout.addWidget(btns)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        # 回填数据
        data = person_data
        if node:
            data = {"name": node.name, "birth": node.birth, "intro": node.intro, "phone": node.phone}
        if data:
            self.edit_name.setText(data["name"])
            if data["birth"]:
                date = QDate.fromString(data["birth"], "yyyy-MM-dd")
                if date.isValid():
                    self.edit_birth.setDate(date)
            self.edit_phone.setText(data.get("phone", ""))
            self.edit_intro.setPlainText(data["intro"])

    def get_data(self):
        return {
            "name": self.edit_name.text().strip(),
            "birth": self.edit_birth.date().toString("yyyy-MM-dd"),
            "phone": self.edit_phone.text().strip(),
            "intro": self.edit_intro.toPlainText().strip()
        }

# ---------------------- 选择人物弹窗 ----------------------
class SelectPersonDialog(QDialog):
    def __init__(self, persons_dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择人物")
        self.resize(300, 400)
        self.persons_dict = persons_dict
        self.selected_pids = []

        layout = QVBoxLayout(self)
        tip = QLabel("请选择2个人物以创建关系：")
        layout.addWidget(tip)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.MultiSelection)
        for pid, data in persons_dict.items():
            item = QListWidgetItem(data["name"])
            item.setData(Qt.UserRole, pid)
            item.setIcon(self._make_icon(data["name"]))
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("确定")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(self.on_confirm)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _make_icon(self, name):
        pix = QPixmap(32, 32)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(QColor("#e0e7ff")))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, 32, 32)
        painter.setPen(QColor("#4338ca"))
        font = QFont()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(pix.rect(), Qt.AlignCenter, name[0] if name else "")
        painter.end()
        return QIcon(pix)

    def on_confirm(self):
        items = self.list_widget.selectedItems()
        if len(items) != 2:
            QMessageBox.warning(self, "提示", "请恰好选择2个人物")
            return
        self.selected_pids = [item.data(Qt.UserRole) for item in items]
        self.accept()

# ---------------------- 人物详情竖版窗口 ----------------------
class PersonDetailDialog(QDialog):
    def __init__(self, node, all_nodes, lines, parent=None):
        super().__init__(parent)
        self.setWindowTitle("人物详情")
        self.setFixedWidth(340)
        self.node = node
        self.all_nodes = all_nodes
        self.lines = lines

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(18)

        # 头像区域
        self.avatar = QLabel()
        self.avatar.setFixedSize(120, 120)
        self.avatar.setAlignment(Qt.AlignCenter)
        self.avatar.setText("人物头像")
        self.avatar.setStyleSheet("""
            QLabel {
                border: 1px solid #e5e7eb;
                border-radius: 10px;
                background-color: #f9fafb;
                color: #9ca3af;
            }
        """)
        main_layout.addWidget(self.avatar, alignment=Qt.AlignCenter)

        # 基础信息
        info_layout = QFormLayout()
        info_layout.setLabelAlignment(Qt.AlignRight)
        info_layout.setSpacing(10)

        name_label = QLabel(node.name)
        name_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #111827;")
        age = self._calc_age(node.birth)
        age_label = QLabel(f"{age} 岁" if age else "未知")
        birth_label = QLabel(node.birth if node.birth else "未填写")
        phone_label = QLabel(node.phone if node.phone else "未填写")
        intro_label = QLabel(node.intro if node.intro else "暂无简介")
        intro_label.setWordWrap(True)
        intro_label.setStyleSheet("color: #4b5563;")

        info_layout.addRow("姓名：", name_label)
        info_layout.addRow("年龄：", age_label)
        info_layout.addRow("生日：", birth_label)
        info_layout.addRow("手机号：", phone_label)
        info_layout.addRow("简介：", intro_label)
        main_layout.addLayout(info_layout)

        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #e5e7eb;")
        main_layout.addWidget(line)

        # 相关人物横向滑动
        title = QLabel("相关人物")
        title.setStyleSheet("font-weight: bold; color: #374151;")
        main_layout.addWidget(title)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setFixedHeight(120)
        scroll_area.setStyleSheet("border: none;")

        scroll_content = QWidget()
        scroll_layout = QHBoxLayout(scroll_content)
        scroll_layout.setSpacing(12)
        scroll_layout.setContentsMargins(4, 4, 4, 4)

        related_list = self._get_related()
        for rel_node, rel_text in related_list:
            card = self._build_small_card(rel_node, rel_text)
            scroll_layout.addWidget(card)

        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        main_layout.addWidget(close_btn)

    def _calc_age(self, birth_str):
        if not birth_str:
            return None
        birth = QDate.fromString(birth_str, "yyyy-MM-dd")
        if not birth.isValid():
            return None
        now = QDate.currentDate()
        age = now.year() - birth.year()
        if now.month() < birth.month() or (now.month() == birth.month() and now.day() < birth.day()):
            age -= 1
        return age

    def _get_related(self):
        res = []
        for line in self.lines:
            if line["pid_a"] == self.node.person_id and line["pid_b"] in self.all_nodes:
                res.append((self.all_nodes[line["pid_b"]], line["rel_name"]))
            elif line["pid_b"] == self.node.person_id and line["pid_a"] in self.all_nodes:
                res.append((self.all_nodes[line["pid_a"]], line["rel_name"]))
        return res

    def _build_small_card(self, node, rel_text):
        card = QWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(4)
        card_layout.setContentsMargins(0, 0, 0, 0)

        box = QLabel()
        box.setFixedSize(56, 56)
        box.setAlignment(Qt.AlignCenter)
        box.setText(node.name[:2])
        box.setStyleSheet("""
            QLabel {
                border: 1px solid #d1d5db;
                border-radius: 8px;
                background-color: white;
                font-weight: bold;
                color: #374151;
            }
            QLabel:hover {
                border-color: #2563eb;
                background-color: #eff6ff;
            }
        """)

        name_lb = QLabel(node.name)
        name_lb.setAlignment(Qt.AlignCenter)
        name_lb.setStyleSheet("font-size: 10px; color: #4b5563;")

        card_layout.addWidget(box, alignment=Qt.AlignCenter)
        card_layout.addWidget(name_lb, alignment=Qt.AlignCenter)

        card.mousePressEvent = lambda e: self._switch_person(node)
        return card

    def _switch_person(self, node):
        self.accept()
        if self.parent():
            self.parent().show_person_detail(node)

# ---------------------- 可拖拽人物列表 ----------------------
class DragPersonList(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item:
            return
        pid = item.data(Qt.UserRole)
        
        mime_data = QMimeData()
        mime_data.setData("application/person-id", str(pid).encode())

        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(Qt.CopyAction)

# ---------------------- 主窗口 ----------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RelationshipApp")
        self.resize(1200, 750)
        self.person_id_counter = 1
        self.persons = {}   # 所有人物数据 {pid: {name, birth, intro, phone}}
        self.nodes = {}     # 画布上的节点 {pid: PersonNode}
        self.lines = []     # 连线列表 [{pid_a, pid_b, rel_name, item}]
        self.layout_mode = "normal"  # normal / center
        self.center_pid = None

        # ========== 顶部工具栏 ==========
        self.toolbar = QToolBar("主工具栏")
        self.addToolBar(self.toolbar)
        self.toolbar.setMovable(False)

        self.action_relation = QAction("新增关系", self)
        self.action_relation.triggered.connect(self.start_add_relation)

        self.action_save = QAction("手动保存", self)
        self.action_save.triggered.connect(self.manual_save)

        # 重置画面按钮
        self.action_reset = QAction("重置画面", self)
        self.action_reset.triggered.connect(self.auto_layout)

        # 展示方式下拉菜单
        self.style_menu = QMenu(self)
        self.act_normal = self.style_menu.addAction("普通模式")
        self.act_normal.setCheckable(True)
        self.act_normal.setChecked(True)
        self.act_normal.triggered.connect(lambda: self.switch_mode("normal"))

        self.act_center = self.style_menu.addAction("中心模式")
        self.act_center.setCheckable(True)
        self.act_center.triggered.connect(lambda: self.switch_mode("center"))

        self.style_btn = QToolButton()
        self.style_btn.setText("展示方式")
        self.style_btn.setMenu(self.style_menu)
        self.style_btn.setPopupMode(QToolButton.InstantPopup)
        self.toolbar.addWidget(self.style_btn)

        self.toolbar.addAction(self.action_relation)
        self.toolbar.addAction(self.action_save)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.action_reset)

        # ========== 中心分割布局 ==========
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Horizontal)

        # 左侧面板
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)
        left_panel.setFixedWidth(220)
        left_panel.setStyleSheet("background-color: #f9fafb;")

        # 新增人物按钮
        self.btn_add_person = QPushButton("+ 新增人物")
        self.btn_add_person.setFixedHeight(42)
        self.btn_add_person.setCursor(Qt.PointingHandCursor)
        self.btn_add_person.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
            QPushButton:pressed {
                background-color: #1e40af;
            }
        """)
        self.btn_add_person.clicked.connect(self.add_person_dialog)
        left_layout.addWidget(self.btn_add_person)

        # 人物列表
        self.list_person = DragPersonList()
        self.list_person.setStyleSheet("""
            QListWidget {
                border: none;
                background-color: transparent;
                outline: none;
            }
            QListWidget::item {
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 10px 12px;
                margin-bottom: 6px;
                background-color: white;
                color: #1f2937;
            }
            QListWidget::item:selected {
                background-color: #eff6ff;
                border-color: #2563eb;
                color: #1f2937;
            }
            QListWidget::item:hover {
                border-color: #93c5fd;
            }
        """)
        self.list_person.customContextMenuRequested.connect(self.show_list_right_menu)
        self.list_person.itemClicked.connect(self.on_list_click)
        left_layout.addWidget(self.list_person)

        # 中央画布
        self.scene = QGraphicsScene()
        self.scene.main_window = self
        self.scene.lines = self.lines
        self.scene.setSceneRect(-5000, -5000, 10000, 10000)

        self.view = RelationGraphicsView(self.scene, self)

        self.splitter.addWidget(left_panel)
        self.splitter.addWidget(self.view)
        self.splitter.setStretchFactor(1, 1)
        main_layout.addWidget(self.splitter)

        # ========== 底部状态栏 ==========
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪 | 拖拽左侧人物到画布 · Ctrl+滚轮缩放 · 双击卡片查看详情")

        self.load_history_data()

    # ---------------------- 右键菜单 ----------------------
    def show_list_right_menu(self, pos):
        item = self.list_person.itemAt(pos)
        if not item:
            return
        pid = item.data(Qt.UserRole)

        menu = QMenu(self)
        act_edit = menu.addAction("编辑")
        act_delete = menu.addAction("删除")
        act_share = menu.addAction("分享")

        action = menu.exec_(self.list_person.mapToGlobal(pos))
        if action == act_edit:
            self.edit_person(pid)
        elif action == act_delete:
            self.delete_person(pid)
        elif action == act_share:
            self.share_person(pid)

    def edit_person(self, pid):
        data = self.persons.get(pid)
        if not data:
            return
        dlg = EditPersonDialog(self, person_data=data)
        if dlg.exec():
            new_data = dlg.get_data()
            if not new_data["name"]:
                return
            self.persons[pid].update(new_data)
            # 同步更新画布节点
            if pid in self.nodes:
                node = self.nodes[pid]
                node.name = new_data["name"]
                node.birth = new_data["birth"]
                node.intro = new_data["intro"]
                node.phone = new_data["phone"]
                node.update()
            self.refresh_list()
            self.status_bar.showMessage(f"已更新：{new_data['name']}", 2000)

    def delete_person(self, pid):
        data = self.persons.get(pid)
        if not data:
            return
        reply = QMessageBox.question(self, "确认删除", f"确定要删除人物「{data['name']}」吗？\n相关关系也会一并删除。")
        if reply != QMessageBox.Yes:
            return

        # 删除关联连线
        to_remove = []
        for line in self.lines:
            if line["pid_a"] == pid or line["pid_b"] == pid:
                if "item" in line and line["item"] is not None:
                    self.scene.removeItem(line["item"])
                to_remove.append(line)
        for line in to_remove:
            self.lines.remove(line)

        # 删除画布节点
        if pid in self.nodes:
            self.scene.removeItem(self.nodes[pid])
            del self.nodes[pid]

        # 删除人物数据
        del self.persons[pid]
        self.refresh_list()
        self.status_bar.showMessage(f"已删除：{data['name']}", 2000)

    def share_person(self, pid):
        data = self.persons.get(pid)
        if not data:
            return
        text = f"人物：{data['name']}\n生日：{data['birth'] if data['birth'] else '未填写'}\n手机号：{data['phone'] if data['phone'] else '未填写'}\n简介：{data['intro'] if data['intro'] else '暂无'}"
        QApplication.clipboard().setText(text, QClipboard.Clipboard)
        self.status_bar.showMessage("人物信息已复制到剪贴板", 2000)

    # ---------------------- 数据加载与刷新 ----------------------
    def load_history_data(self):
        person_rows, rel_rows = load_data()
        if not person_rows:
            return

        max_id = 0
        for pid, name, x, y, intro, birth, phone in person_rows:
            self.persons[pid] = {
                "name": name,
                "intro": intro,
                "birth": birth,
                "phone": phone if phone else ""
            }
            # 有位置坐标则创建节点
            if x is not None and y is not None:
                node = PersonNode(pid, name, intro, birth, phone if phone else "")
                self.scene.addItem(node)
                node.setPos(x, y)
                self.nodes[pid] = node
            if pid > max_id:
                max_id = pid
        self.person_id_counter = max_id + 1

        # 加载关系，两端都在画布上才显示连线
        for aid, bid, rel_name in rel_rows:
            if aid in self.nodes and bid in self.nodes:
                line_item = RelationLine(self.nodes[aid], self.nodes[bid], rel_name)
                self.scene.addItem(line_item)
                self.lines.append({
                    "pid_a": aid,
                    "pid_b": bid,
                    "rel_name": rel_name,
                    "item": line_item
                })

        self.refresh_list()

    def refresh_list(self):
        self.list_person.clear()
        for pid, data in self.persons.items():
            item_text = f"{data['name']} | {data['birth']}" if data["birth"] else data["name"]
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, pid)
            self.list_person.addItem(item)

    def manual_save(self):
        save_data(self.persons, self.nodes, self.lines)
        self.status_bar.showMessage("✅ 数据已保存到本地数据库", 2000)

    def closeEvent(self, event):
        save_data(self.persons, self.nodes, self.lines)
        event.accept()

    # ---------------------- 新增人物 ----------------------
    def add_person_dialog(self):
        dlg = EditPersonDialog(self)
        if dlg.exec():
            data = dlg.get_data()
            if not data["name"]:
                return
            pid = self.person_id_counter
            self.person_id_counter += 1
            self.persons[pid] = data
            self.refresh_list()
            self.status_bar.showMessage(f"已添加人物：{data['name']}，可拖拽到画布中", 2000)

    # ---------------------- 拖拽创建节点 ----------------------
    def create_node_at(self, pid, pos):
        if pid in self.nodes:
            self.status_bar.showMessage("该人物已在画布中", 2000)
            return
        data = self.persons.get(pid)
        if not data:
            return

        node = PersonNode(pid, data["name"], data["intro"], data["birth"], data["phone"])
        self.scene.addItem(node)
        node.setPos(pos)
        self.nodes[pid] = node

        # 创建已有的关系连线
        for line in self.lines:
            if line["pid_a"] == pid and line["pid_b"] in self.nodes:
                line_item = RelationLine(node, self.nodes[line["pid_b"]], line["rel_name"])
                self.scene.addItem(line_item)
                line["item"] = line_item
            elif line["pid_b"] == pid and line["pid_a"] in self.nodes:
                line_item = RelationLine(self.nodes[line["pid_a"]], node, line["rel_name"])
                self.scene.addItem(line_item)
                line["item"] = line_item

    # ---------------------- 新增关系 ----------------------
    def start_add_relation(self):
        if len(self.persons) < 2:
            self.status_bar.showMessage("至少需要2个人物才能添加关系", 2000)
            return

        dlg = SelectPersonDialog(self.persons, self)
        if dlg.exec():
            pid1, pid2 = dlg.selected_pids
            # 弹窗输入关系名
            rel_dlg = QDialog(self)
            rel_dlg.setWindowTitle("设置关系")
            layout = QFormLayout(rel_dlg)
            edit_rel = QLineEdit()
            layout.addRow("关系描述：", edit_rel)
            btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            btns.button(QDialogButtonBox.Ok).setText("确定")
            btns.button(QDialogButtonBox.Cancel).setText("取消")
            layout.addWidget(btns)
            btns.accepted.connect(rel_dlg.accept)
            btns.rejected.connect(rel_dlg.reject)

            if rel_dlg.exec():
                rel_name = edit_rel.text().strip()
                if not rel_name:
                    return

                # 确保两个人物都在画布上，不在则自动添加
                if pid1 not in self.nodes:
                    self.create_node_at(pid1, QPointF(-100, 0))
                if pid2 not in self.nodes:
                    self.create_node_at(pid2, QPointF(100, 0))

                # 检查是否已存在关系
                for line in self.lines:
                    if {line["pid_a"], line["pid_b"]} == {pid1, pid2}:
                        QMessageBox.information(self, "提示", "两人之间已存在关系")
                        return

                line_item = RelationLine(self.nodes[pid1], self.nodes[pid2], rel_name)
                self.scene.addItem(line_item)
                self.lines.append({
                    "pid_a": pid1,
                    "pid_b": pid2,
                    "rel_name": rel_name,
                    "item": line_item
                })
                self.status_bar.showMessage(f"已添加关系：{rel_name}", 2000)

    # ---------------------- 列表点击定位 ----------------------
    def on_list_click(self, item):
        pid = item.data(Qt.UserRole)
        if pid in self.nodes:
            self.scene.clearSelection()
            self.nodes[pid].setSelected(True)
            self.view.centerOn(self.nodes[pid])
        else:
            self.status_bar.showMessage("该人物尚未添加到画布，可拖拽放入", 2000)

    # ---------------------- 人物详情 ----------------------
    def show_person_detail(self, node):
        dlg = PersonDetailDialog(node, self.nodes, self.lines, self)
        dlg.exec()

    # ---------------------- 模式切换 ----------------------
    def switch_mode(self, mode):
        self.layout_mode = mode
        self.act_normal.setChecked(mode == "normal")
        self.act_center.setChecked(mode == "center")

        if mode == "center":
            selected = [i for i in self.scene.selectedItems() if isinstance(i, PersonNode)]
            if not selected:
                QMessageBox.information(self, "提示", "请先在画布中选中一个人物作为中心")
                self.switch_mode("normal")
                return
            self.center_pid = selected[0].person_id
            self.status_bar.showMessage("已切换为中心模式", 2000)
            self.auto_layout()
        else:
            self.center_pid = None
            # 恢复所有节点可拖动
            for node in self.nodes.values():
                node.setFlag(QGraphicsItem.ItemIsMovable, True)
            self.status_bar.showMessage("已切换为普通模式", 2000)

    # ---------------------- 自动布局 ----------------------
    def auto_layout(self):
        node_list = list(self.nodes.values())
        count = len(node_list)
        if count <= 1:
            self.status_bar.showMessage("人物数量不足，无需整理", 2000)
            return

        if self.layout_mode == "center" and self.center_pid and self.center_pid in self.nodes:
            center_node = self.nodes[self.center_pid]
            center_node.setPos(0, 0)
            center_node.setFlag(QGraphicsItem.ItemIsMovable, False)
            
            others = [n for n in node_list if n.person_id != self.center_pid]
            r = 180 + len(others) * 25
            for i, n in enumerate(others):
                angle = 2 * math.pi * i / len(others)
                x = r * math.cos(angle)
                y = r * math.sin(angle)
                n.setPos(x, y)
        else:
            # 普通环形布局
            r = 150 + count * 30
            center = QPointF(0, 0)
            for i, n in enumerate(node_list):
                angle = 2 * math.pi * i / count
                x = center.x() + r * math.cos(angle)
                y = center.y() + r * math.sin(angle)
                n.setPos(x, y)

        # 更新所有连线
        for line in self.lines:
            if "item" in line and line["item"] is not None:
                line["item"].update_path()

        # 适配视图
        items_rect = QRectF()
        for node in self.nodes.values():
            items_rect = items_rect.united(node.sceneBoundingRect())
        items_rect.adjust(-100, -100, 100, 100)
        self.view.fitInView(items_rect, Qt.KeepAspectRatio)

        self.status_bar.showMessage("已自动整理布局", 2000)

if __name__ == "__main__":
    init_db()
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
