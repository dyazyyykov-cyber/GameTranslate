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
            # OCR + MT
            "ocr_engine": "winocr",
            "ocr_lang": "en-US",
            "mt_model_dir": "models/ct2-opus-mt-en-ru",
            "mt_device": "cuda",
            "mt_compute_type": "int8_float16",
            # Runtime tuning (настройка под RTX 4060)
            "loop_fps": 30,
            "frame_diff_threshold": 3.0,
            "stabilizer_history": 3,
            "stabilizer_threshold": 0.85,
        }
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return self.defaults.copy()

    def save(self):
        try:
            with open(self.path, 'w') as f:
                json.dump(self.data, f, indent=4)
        except Exception:
            pass

    def get(self, key):
        return self.data.get(key, self.defaults.get(key))

    def set(self, key, value):
        self.data[key] = value
        self.save()


cfg = Config()
