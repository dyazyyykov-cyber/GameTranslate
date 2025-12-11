import json
import os

class Config:
    def __init__(self):
        self.path = "config.json"
        self.defaults = {
            "monitor": {"top": 0, "left": 0, "width": 0, "height": 0},
            "translate": True,
            "debug": True,
            "border": True,
            "win_pos": {"x": 50, "y": 50},
            "ocr_gpu": True,    # Принудительно использовать GPU для OCR [2]
            "ocr_detail": 0     # Оптимизация EasyOCR
        }
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r') as f: return json.load(f)
            except: pass
        return self.defaults.copy()

    def save(self):
        try:
            with open(self.path, 'w') as f: json.dump(self.data, f, indent=4)
        except: pass

    def get(self, key): return self.data.get(key, self.defaults.get(key))
    def set(self, key, value):
        self.data[key] = value
        self.save()

cfg = Config()