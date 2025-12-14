import sys
import threading
import time
import io
import ctypes
import datetime
from PyQt6.QtWidgets import QApplication, QMainWindow, QFrame, QLabel, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QRect
from PyQt6.QtGui import QColor
from difflib import SequenceMatcher

# --- ИМПОРТ МОДУЛЕЙ ПРОЕКТА ---
from src.config import cfg
from src.capture import ScreenCap
from src.ai_engine import AIEngine, TextStabilizer
from src.audio import AudioPlayer
from src.ui import HUD, Sniper

# === НАСТРОЙКА DPI ===
if hasattr(Qt.HighDpiScaleFactorRoundingPolicy, 'PassThrough'):
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass


class WorkerSignals(QObject):
    log = pyqtSignal(str)
    subtitle = pyqtSignal(str, str)


class MainApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.signals = WorkerSignals()
        self.init_ui()
        self.signals.log.connect(self.hud.log)
        self.signals.subtitle.connect(self.show_subtitle)
        self.running = True
        self.engine_thread = threading.Thread(target=self.run_engine, daemon=True)
        self.engine_thread.start()

    def init_ui(self):
        # (Весь код UI оставляем без изменений, он корректен из предыдущих версий)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        geo = QRect()
        for s in QApplication.screens():
            geo = geo.united(s.geometry())
        self.setGeometry(geo)
        self.hud = HUD(self)
        self.hud.show()
        self.border_frame = QFrame(self)
        self.border_frame.setStyleSheet("border: 2px solid #00FF00; background: transparent;")
        self.border_frame.hide()
        self.sub_container = QWidget(self)
        self.sub_container.hide()
        vl = QVBoxLayout(self.sub_container)
        vl.setSpacing(2)
        self.lbl_name = QLabel("")
        self.lbl_name.setStyleSheet(
            "color: #FFD700; font-size: 18px; font-weight: bold; background-color: rgba(0, 0, 0, 0.7); padding: 4px 8px; border-radius: 4px;")
        self.lbl_text = QLabel("Ожидание...")
        self.lbl_text.setStyleSheet(
            "color: #FFFFFF; font-size: 22px; font-weight: 600; background-color: rgba(0, 0, 0, 0.7); padding: 8px 12px; border-radius: 6px;")
        self.lbl_text.setWordWrap(True)
        vl.addWidget(self.lbl_name, alignment=Qt.AlignmentFlag.AlignLeft)
        vl.addWidget(self.lbl_text, alignment=Qt.AlignmentFlag.AlignLeft)
        self.restore_view()

    def start_snip(self):
        self.hud.hide()
        self.border_frame.hide()
        self.sub_container.hide()
        self.sniper = Sniper(self.on_snip_finished)

    def on_snip_finished(self, rect):
        cfg.set("monitor", rect)
        self.hud.show()
        self.restore_view()
        self.signals.log.emit(f"Область захвата: {rect}")

    def restore_view(self):
        r = cfg.get("monitor")
        if r['width'] > 0:
            ratio = self.devicePixelRatio()
            x, y, w, h = int(r['left'] / ratio), int(r['top'] / ratio), int(r['width'] / ratio), int(
                r['height'] / ratio)
            self.border_frame.setGeometry(x, y, w, h)
            self.border_frame.setVisible(cfg.get("border"))
            sub_y = y + h + 15
            if sub_y + 150 > self.height(): sub_y = y + h - 150
            self.sub_container.setGeometry(x, sub_y, max(500, w), 200)
            self.sub_container.show()

    def show_subtitle(self, name, text):
        self.lbl_name.setText(name)
        self.lbl_name.setVisible(bool(name))
        self.lbl_text.setText(text)
        self.sub_container.adjustSize()
        self.sub_container.show()

    def update_cfg(self, key, val):
        cfg.set(key, val)
        if key == "border": self.restore_view()

    def toggle_border(self, checked):
        self.update_cfg("border", checked)

    # ==========================================
    #      ГЛАВНЫЙ ЦИКЛ (ENGINE THREAD)
    # ==========================================
    def run_engine(self):
        self.signals.log.emit("Инициализация движка...")
        try:
            cap = ScreenCap()
            ai = AIEngine(self.signals.log.emit)
            audio = AudioPlayer()
            stab = ai.stabilizer
            self.signals.log.emit("✅ Система готова к работе!")
        except Exception as e:
            self.signals.log.emit(f"FATAL ERROR: {e}")
            return

        last_audio_finish_time = 0.0

        def capture_job():
            def safe_grab():
                rect = cfg.get("monitor")
                if rect.get("width", 0) <= 0 or rect.get("height", 0) <= 0:
                    return None
                return cap.grab(rect)

            ai.start_capture(safe_grab)

        def ocr_job():
            ai.start_ocr()

        def mt_tts_job():
            nonlocal last_audio_finish_time
            while self.running:
                try:
                    stable_text = ai.text_queue.get(timeout=0.05)
                except Exception:
                    continue

                similarity = SequenceMatcher(None, stable_text, getattr(mt_tts_job, "last_text", "")).ratio()
                if similarity >= 0.95:
                    continue

                audio.stop()
                ai.abort()

                translated_text = ""
                speaker_name = ""
                voice_duration = 0.0
                t_mt = 0.0

                if cfg.get("translate"):
                    t_mt_start = time.time()
                    res = ai.translate(stable_text)
                    t_mt = time.time() - t_mt_start

                    if res and res['text']:
                        translated_text = res['text']
                        self.signals.subtitle.emit(res['name'], res['text'])
                        voice_duration, speaker_name = audio.speak(res['text'], res['name'], res['gender'])
                else:
                    translated_text = stable_text
                    self.signals.subtitle.emit("", stable_text)
                    voice_duration, speaker_name = audio.speak(stable_text, "", "m")

                current_time_str = datetime.datetime.now().strftime("%H:%M:%S")
                prev_status = "🔴 Interrupted" if time.time() < last_audio_finish_time else "🟢 Completed"

                log_block = (
                    f"\n{'━' * 10} ⏱️ {current_time_str} {'━' * 10}\n"
                    f"📥 OCR -> MT pipeline\n"
                    f"🔄 MT ({t_mt:.2f}s) -> 🗣️ TTS ({voice_duration:.1f}s):\n"
                    f"   [{speaker_name}] \"{translated_text}\"\n"
                    f"ℹ️ Prev Status: {prev_status}"
                )
                self.signals.log.emit(log_block)

                setattr(mt_tts_job, "last_text", stable_text)
                last_audio_finish_time = time.time() + voice_duration

        capture_thread = threading.Thread(target=capture_job, daemon=True)
        ocr_thread = threading.Thread(target=ocr_job, daemon=True)
        mt_tts_thread = threading.Thread(target=mt_tts_job, daemon=True)

        capture_thread.start()
        ocr_thread.start()
        mt_tts_thread.start()

        while self.running:
            time.sleep(0.1)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainApp()
    sys.exit(app.exec())