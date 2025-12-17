import mss
import numpy as np


class ScreenCap:
    def __init__(self):
        self.sct = mss.mss()

    def grab(self, rect):
        if rect['width'] <= 0 or rect['height'] <= 0:
            return None

        monitor = {
            "top": int(rect['top']),
            "left": int(rect['left']),
            "width": int(rect['width']),
            "height": int(rect['height']),
            "mon": 0
        }

        # ВАЖНО: не глотаем исключения, чтобы start.py показал их в HUD логах
        sct_img = self.sct.grab(monitor)
        img = np.array(sct_img)
        return img[:, :, :3]
