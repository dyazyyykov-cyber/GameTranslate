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
            stab = TextStabilizer(history=3, threshold=0.85)
            self.signals.log.emit("✅ Система готова к работе!")
        except Exception as e:
            self.signals.log.emit(f"FATAL ERROR: {e}")
            return

        last_stable_text = ""

        # Переменные для отслеживания статуса озвучки
        last_audio_finish_time = 0
        last_phrase_duration = 0

        while self.running:
            rect = cfg.get("monitor")
            if rect['width'] == 0:
                time.sleep(1.0)
                continue

            loop_start = time.time()

            try:
                # 1. ЗАХВАТ
                img = cap.grab(rect)
                if img is None:
                    time.sleep(0.1);
                    continue

                # 2. OCR (с замером времени)
                t_ocr_start = time.time()
                raw_text = ai.recognize(img)
                t_ocr = time.time() - t_ocr_start

                if raw_text:
                    stable_text = stab.push(raw_text)

                    if stable_text:
                        similarity = SequenceMatcher(None, stable_text, last_stable_text).ratio()

                        # --- НОВАЯ ФРАЗА ---
                        if similarity < 0.85:
                            # Проверяем, успела ли договорить прошлая фраза
                            now = time.time()
                            was_interrupted = now < last_audio_finish_time
                            prev_status = "🔴 Interrupted" if was_interrupted else "🟢 Completed"

                            # Если было прерывание, можно вывести лог о предыдущей фразе (опционально)
                            # Но мы сделаем красивый блок для ТЕКУЩЕЙ фразы

                            # Остановка предыдущего
                            audio.stop()
                            ai.abort()

                            # --- ЛОГИКА ПЕРЕВОДА И ОЗВУЧКИ ---
                            translated_text = ""
                            speaker_name = ""
                            voice_duration = 0.0
                            t_llm = 0.0

                            if cfg.get("translate"):
                                t_llm_start = time.time()
                                res = ai.translate(stable_text)
                                t_llm = time.time() - t_llm_start

                                if res and res['text']:
                                    translated_text = res['text']
                                    self.signals.subtitle.emit(res['name'], res['text'])

                                    # Озвучка
                                    voice_duration, speaker_name = audio.speak(res['text'], res['name'], res['gender'])
                            else:
                                # Режим чтения оригинала
                                translated_text = "(Original) " + stable_text
                                self.signals.subtitle.emit("", stable_text)
                                voice_duration, speaker_name = audio.speak(stable_text, "", "m")

                            # --- ФОРМИРОВАНИЕ БЛОКА ЛОГОВ ---
                            current_time_str = datetime.datetime.now().strftime("%H:%M:%S")

                            log_block = (
                                f"\n{'━' * 10} ⏱️ {current_time_str} {'━' * 10}\n"
                                f"📥 OCR ({t_ocr:.2f}s) [{int(similarity * 100)}% match]:\n"
                                f"   \"{stable_text[:50]}...\"\n"
                                f"🔄 LLM ({t_llm:.2f}s) -> 🗣️ TTS ({voice_duration:.1f}s):\n"
                                f"   [{speaker_name}] \"{translated_text}\"\n"
                                f"ℹ️ Prev Status: {prev_status}"
                            )

                            self.signals.log.emit(log_block)

                            # Обновляем состояние
                            last_stable_text = stable_text
                            last_audio_finish_time = time.time() + voice_duration
                            last_phrase_duration = voice_duration

            except Exception as e:
                self.signals.log.emit(f"Error loop: {e}")

            process_time = time.time() - loop_start
            sleep_time = max(0.15 - process_time, 0.01)
            time.sleep(sleep_time)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainApp()
    sys.exit(app.exec())