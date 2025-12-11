from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QCheckBox, QTextEdit, QApplication, QFrame)
from PyQt6.QtCore import Qt, QRect, QPoint, QSize
from PyQt6.QtGui import QPainter, QPen, QColor, QPixmap, QImage, QIcon, QFont
from .config import cfg
import mss
import numpy as np
import cv2


class ModernButton(QPushButton):
    def __init__(self, text, bg_color="#2ea043", hover_color="#3fb950"):
        super().__init__(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_color};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-family: 'Segoe UI', sans-serif;
            }}
            QPushButton:hover {{ background-color: {hover_color}; }}
            QPushButton:pressed {{ background-color: {bg_color}; opacity: 0.8; }}
        """)


class HUD(QWidget):
    """Плавающее окно управления с обновленным дизайном"""

    def __init__(self, ctrl):
        super().__init__()
        self.ctrl = ctrl
        # Убираем рамки, оставляем поверх всех окон
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        pos = cfg.get("win_pos")
        self.move(pos.get('x', 50), pos.get('y', 50))

        # Основной контейнер с эффектом стекла и неоновой обводкой
        self.container = QFrame(self)
        self.container.setStyleSheet("""
            QFrame {
                background-color: rgba(20, 20, 25, 240);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 12px;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # === Заголовок ===
        h_header = QHBoxLayout()
        title = QLabel("PROJECT BABEL")
        title.setStyleSheet(
            "color: #00ff88; font-weight: 900; font-size: 14px; letter-spacing: 1px; border: none; background: transparent;")

        btn_close = QPushButton("×")
        btn_close.setFixedSize(24, 24)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton { color: #888; border: none; font-size: 18px; font-weight: bold; background: transparent;}
            QPushButton:hover { color: #ff5555; }
        """)
        btn_close.clicked.connect(QApplication.quit)

        h_header.addWidget(title)
        h_header.addStretch()
        h_header.addWidget(btn_close)
        layout.addLayout(h_header)

        layout.addWidget(self.create_divider())

        # === Кнопки управления ===
        btn_snip = ModernButton("🎯 ВЫБРАТЬ ЗОНУ", "#333", "#444")
        btn_snip.clicked.connect(self.ctrl.start_snip)
        layout.addWidget(btn_snip)

        self.btn_mode = ModernButton("ПЕРЕВОД: ВКЛ", "#238636", "#2ea043")
        self.btn_mode.setCheckable(True)
        self.btn_mode.setChecked(cfg.get("translate"))
        self.btn_mode.clicked.connect(self.toggle_mode)
        layout.addWidget(self.btn_mode)

        # === Чекбоксы ===
        cb_layout = QHBoxLayout()
        self.chk_debug = self.create_checkbox("Логи", cfg.get("debug"))
        self.chk_debug.toggled.connect(lambda c: self.ctrl.update_cfg("debug", c))

        self.chk_border = self.create_checkbox("Рамка", cfg.get("border"))
        self.chk_border.toggled.connect(self.ctrl.toggle_border)

        cb_layout.addWidget(self.chk_debug)
        cb_layout.addWidget(self.chk_border)
        layout.addLayout(cb_layout)

        # === Консоль ===
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFixedHeight(80)
        self.console.setStyleSheet("""
            QTextEdit {
                background-color: rgba(0, 0, 0, 0.5);
                color: #a0a0a0;
                border: none;
                border-radius: 6px;
                font-family: 'Consolas', monospace;
                font-size: 10px;
                padding: 5px;
            }
        """)
        layout.addWidget(self.console)

        # Тень для окна
        # (в простом PyQt тени сложные, проще эмулировать через композицию, но пока оставим без внешней тени)

    def create_divider(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: rgba(255, 255, 255, 0.1); border: none; max-height: 1px;")
        return line

    def create_checkbox(self, text, checked):
        cb = QCheckBox(text)
        cb.setChecked(checked)
        cb.setStyleSheet("""
            QCheckBox { color: #ccc; font-size: 12px; spacing: 5px; border: none; background: transparent;}
            QCheckBox::indicator { width: 14px; height: 14px; border-radius: 3px; border: 1px solid #555; background: #222; }
            QCheckBox::indicator:checked { background: #00ff88; border: 1px solid #00ff88; }
        """)
        return cb

    def toggle_mode(self, checked):
        self.ctrl.update_cfg("translate", checked)
        if checked:
            self.btn_mode.setText("ПЕРЕВОД: ВКЛ")
            self.btn_mode.setStyleSheet(
                self.btn_mode.styleSheet().replace("#333", "#238636").replace("#444", "#2ea043"))
        else:
            self.btn_mode.setText("ПЕРЕВОД: ВЫКЛ")
            self.btn_mode.setStyleSheet(
                self.btn_mode.styleSheet().replace("#238636", "#333").replace("#2ea043", "#444"))

    def log(self, text):
        self.console.append(text)
        sb = self.console.verticalScrollBar()
        sb.setValue(sb.maximum())

    # Перетаскивание
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self.drag_pos)
            self.ctrl.update_cfg("win_pos", {"x": self.x(), "y": self.y()})


class Sniper(QWidget):
    """
    Полноэкранный виджет для захвата координат.
    FIX: Использует математический пересчет координат вместо DPI,
    чтобы избежать эффекта 'лупы'.
    """

    def __init__(self, callback):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowState(Qt.WindowState.WindowFullScreen)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.callback = callback

        # Захват экранов через MSS (Физические пиксели)
        with mss.mss() as sct:
            monitor = sct.monitors[0]  # Весь виртуальный экран
            sct_img = sct.grab(monitor)

            img = np.array(sct_img)
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
            h, w, ch = img.shape
            bytes_per_line = ch * w

            # Создаем QImage без привязки к DevicePixelRatio
            self.orig_image = QImage(img.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            self.pixmap = QPixmap.fromImage(self.orig_image)

            self.offset_x = monitor['left']
            self.offset_y = monitor['top']

        # Растягиваем окно на все мониторы
        geo = QRect()
        for s in QApplication.screens():
            geo = geo.united(s.geometry())
        self.setGeometry(geo)

        self.start_pos = None
        self.current_pos = None
        self.is_selecting = False
        self.show()

    def paintEvent(self, event):
        painter = QPainter(self)
        # Рисуем скриншот, растягивая его на весь размер виджета
        # Это устраняет проблему зума, так как мы принудительно вписываем картинку в окно
        painter.drawPixmap(self.rect(), self.pixmap)

        # Затемнение
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))

        if self.is_selecting and self.start_pos and self.current_pos:
            selection_rect = QRect(self.start_pos, self.current_pos).normalized()

            # Рисуем "чистую" область
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)

            # Нам нужно вырезать кусок из исходного pixmap, соответствующий месту на экране
            # Считаем коэффициент масштабирования (Физика / Логика)
            scale_x = self.pixmap.width() / self.width()
            scale_y = self.pixmap.height() / self.height()

            src_x = int(selection_rect.x() * scale_x)
            src_y = int(selection_rect.y() * scale_y)
            src_w = int(selection_rect.width() * scale_x)
            src_h = int(selection_rect.height() * scale_y)

            painter.drawPixmap(selection_rect, self.pixmap, QRect(src_x, src_y, src_w, src_h))

            # Рамка
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            pen = QPen(QColor(0, 255, 136), 2)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRect(selection_rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.close()  # Выход по ПКМ
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = event.pos()
            self.current_pos = event.pos()
            self.is_selecting = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.is_selecting:
            self.current_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.is_selecting:
            self.close()
            if not self.start_pos or not self.current_pos: return

            rect = QRect(self.start_pos, event.pos()).normalized()

            # МАТЕМАТИЧЕСКИЙ ПЕРЕСЧЕТ
            # Переводим координаты клика (Логические) в координаты скриншота (Физические)
            scale_x = self.pixmap.width() / self.width()
            scale_y = self.pixmap.height() / self.height()

            final_rect = {
                'left': int(rect.x() * scale_x) + self.offset_x,
                'top': int(rect.y() * scale_y) + self.offset_y,
                'width': int(rect.width() * scale_x),
                'height': int(rect.height() * scale_y)
            }

            # Защита от микро-выделений
            if final_rect['width'] > 10 and final_rect['height'] > 10:
                self.callback(final_rect)