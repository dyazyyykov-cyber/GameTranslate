import asyncio
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from difflib import SequenceMatcher
from queue import Queue, Full, Empty
from typing import Optional

import cv2
import numpy as np
import sentencepiece as spm

import ctranslate2
from .config import cfg

try:
    # winocr: обёртка над Windows.Media.Ocr (работает только на Windows)
    from winocr import WinOCR
except Exception:  # pragma: no cover - импорт проверяется на целевой системе
    WinOCR = None


@dataclass
class TranslationResult:
    name: str
    gender: str
    text: str


class TextStabilizer:
    def __init__(self, history: int = 3, threshold: float = 0.85):
        self.queue = deque(maxlen=history)
        self.threshold = threshold

    def push(self, text: str) -> Optional[str]:
        clean_text = text.strip()
        if not clean_text or len(clean_text) < 2:
            return None

        self.queue.append(clean_text)
        if len(self.queue) < self.queue.maxlen:
            return None

        last_item = self.queue[-1]
        is_stable = True
        for item in self.queue:
            if SequenceMatcher(None, last_item, item).ratio() < self.threshold:
                is_stable = False
                break
        return last_item if is_stable else None


class WindowsOCREngine:
    """Синхронная обёртка над winocr.

    OCR вызывается из OCR-потока, в котором создаётся event loop один раз,
    чтобы избежать накладных расходов на создание цикла для каждого кадра.
    """

    def __init__(self, lang: str = "en"):
        if WinOCR is None:
            raise RuntimeError("winocr is not available on this platform")
        self.lang = lang
        self.ocr = WinOCR(lang=self.lang)
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    async def _run(self, img: np.ndarray) -> str:
        # WinOCR ожидает BGR/PIL; библиотека умеет принимать numpy-массивы
        res = await self.ocr.recognize(img)
        return res or ""

    def run(self, img: np.ndarray) -> str:
        if self.loop is None:
            raise RuntimeError("Event loop is not attached for OCR thread")
        return self.loop.run_until_complete(self._run(img))


class CT2Translator:
    def __init__(self, model_dir: str, device: str = "cuda", compute_type: str = "int8_float16"):
        self.model_dir = os.path.abspath(model_dir)
        if not os.path.isdir(self.model_dir):
            raise FileNotFoundError(f"CT2 model not found: {self.model_dir}")

        self.translator = ctranslate2.Translator(
            self.model_dir,
            device=device,
            compute_type=compute_type,
        )

        # SentencePiece модели ищем в папке CT2
        src_sp = os.path.join(self.model_dir, "source.spm")
        tgt_sp = os.path.join(self.model_dir, "target.spm")
        if not os.path.exists(src_sp) or not os.path.exists(tgt_sp):
            raise FileNotFoundError("SentencePiece models not found in CT2 folder")

        self.src_sp = spm.SentencePieceProcessor(model_file=src_sp)
        self.tgt_sp = spm.SentencePieceProcessor(model_file=tgt_sp)

    def translate(self, text: str) -> Optional[TranslationResult]:
        tokens = self.src_sp.encode(text, out_type=str)
        if not tokens:
            return None

        results = self.translator.translate_batch(
            [tokens],
            beam_size=1,
            return_scores=False,
            max_decoding_length=128,
        )

        if not results or not results[0].hypotheses:
            return None

        tgt_tokens = results[0].hypotheses[0]
        decoded = self.tgt_sp.decode(tgt_tokens)
        if not decoded:
            return None

        return TranslationResult(name="", gender="m", text=decoded.strip())


class LatestQueue(Queue):
    """Очередь размера 1: сохраняем только последний элемент."""

    def __init__(self):
        super().__init__(maxsize=1)

    def put_latest(self, item):
        try:
            self.put(item, block=False)
        except Full:
            try:
                _ = self.get_nowait()
            except Empty:
                pass
            self.put(item, block=False)


class AIEngine:
    def __init__(self, log_func):
        self.log = log_func
        self.stabilizer = TextStabilizer(
            history=cfg.get("stabilizer_history"),
            threshold=cfg.get("stabilizer_threshold"),
        )
        self.ocr_engine = WindowsOCREngine(lang=cfg.get("ocr_lang"))
        self.translator = CT2Translator(
            model_dir=cfg.get("mt_model_dir"),
            device=cfg.get("mt_device"),
            compute_type=cfg.get("mt_compute_type"),
        )

        self.frame_queue: LatestQueue = LatestQueue()
        self.text_queue: LatestQueue = LatestQueue()
        self.running = threading.Event()
        self.running.set()
        self.last_hash = ""

        self.capture_thread: Optional[threading.Thread] = None
        self.ocr_thread: Optional[threading.Thread] = None

    def start_capture(self, capture_func):
        if self.capture_thread and self.capture_thread.is_alive():
            return

        self.capture_thread = threading.Thread(
            target=self._capture_loop,
            args=(capture_func,),
            daemon=True,
        )
        self.capture_thread.start()

    def start_ocr(self):
        if self.ocr_thread and self.ocr_thread.is_alive():
            return

        self.ocr_thread = threading.Thread(target=self._ocr_loop, daemon=True)
        self.ocr_thread.start()

    def _capture_loop(self, capture_func):
        target_fps = max(1, cfg.get("loop_fps"))
        delay = 1.0 / target_fps
        diff_threshold = cfg.get("frame_diff_threshold")

        prev_small = None
        while self.running.is_set():
            frame = capture_func()
            if frame is None:
                continue

            small = cv2.resize(frame, (0, 0), fx=0.3, fy=0.3)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

            if prev_small is not None:
                diff = cv2.absdiff(gray, prev_small)
                mean_diff = float(np.mean(diff))
                if mean_diff < diff_threshold:
                    time.sleep(delay)
                    continue
            prev_small = gray

            self.frame_queue.put_latest(frame)
            time.sleep(delay)

    def _ocr_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.ocr_engine.attach_loop(loop)

        while self.running.is_set():
            try:
                frame = self.frame_queue.get(timeout=0.05)
            except Empty:
                continue

            text = self.recognize(frame)
            if not text:
                continue

            stable = self.stabilizer.push(text)
            if stable:
                self.text_queue.put_latest(stable)

    def recognize(self, img) -> Optional[str]:
        text = self.ocr_engine.run(img)
        text = " ".join(text.split())  # нормализация пробелов
        if len(text) < 2:
            return None
        return text

    def translate(self, text: str) -> Optional[dict]:
        cleaned = text.strip()
        if len(cleaned) < 2:
            return None

        # Дедупликация
        norm = cleaned.lower()
        if SequenceMatcher(None, norm, self.last_hash).ratio() > 0.95:
            return None

        res = self.translator.translate(cleaned)
        if not res or not res.text:
            return None

        # Валидатор: русские буквы
        if not any("а" <= ch.lower() <= "я" or ch == "ё" for ch in res.text):
            return None

        self.last_hash = norm
        return {"name": res.name, "gender": res.gender, "text": res.text}

    def abort(self):
        # Совместимость со старым интерфейсом
        pass

    def stop(self):
        self.running.clear()
