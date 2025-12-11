import mss
import numpy as np


class ScreenCap:
    def __init__(self):
        # Инициализация MSS один раз при старте [Optimized]
        self.sct = mss.mss()

    def grab(self, rect):
        """
        rect: dict {top, left, width, height}
        Возвращает: numpy array (BGR)
        """
        if rect['width'] <= 0 or rect['height'] <= 0: return None

        # MSS требует int для монитора
        monitor = {
            "top": int(rect['top']),
            "left": int(rect['left']),
            "width": int(rect['width']),
            "height": int(rect['height']),
            "mon": 0  # 0 = Виртуальный рабочий стол (все мониторы)
        }

        try:
            # Grab возвращает BGRA (оптимизировано на уровне C библиотеки)
            sct_img = self.sct.grab(monitor)
            img = np.array(sct_img)

            # Удаляем альфа-канал для OCR (BGRA -> BGR)
            # Слайсинг в numpy - очень быстрая операция (zero-copy view)
            return img[:, :, :3]
        except Exception:
            return None