import mss
import numpy as np
import threading


class ScreenCap:
    def __init__(self):
        # Используем thread-local хранилище.
        # Это гарантирует, что у каждого потока будет свой собственный экземпляр mss.
        self._thread_local = threading.local()

    def grab(self, rect):
        """
        Захватывает область экрана. Безопасен для использования в потоках.
        """
        if rect['width'] <= 0 or rect['height'] <= 0:
            return None

        monitor = {
            "top": int(rect['top']),
            "left": int(rect['left']),
            "width": int(rect['width']),
            "height": int(rect['height']),
            "mon": 0
        }

        # Проверяем, есть ли mss для ТЕКУЩЕГО потока
        if not hasattr(self._thread_local, "sct"):
            self._thread_local.sct = mss.mss()

        try:
            # Захват
            sct_img = self._thread_local.sct.grab(monitor)
            img = np.array(sct_img)
            # Удаляем альфа-канал (BGRA -> BGR)
            return img[:, :, :3]
        except Exception:
            return None
