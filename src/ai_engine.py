import os
import cv2
import easyocr
import json
import threading
import re
from llama_cpp import Llama, LlamaGrammar
from collections import deque
from difflib import SequenceMatcher
from .config import cfg

STOP_GENERATION = threading.Event()

# === GBNF ГРАММАТИКА ===
JSON_GBNF = r"""
root   ::= object
value  ::= object | array | string | number | ("true" | "false" | "null") ws

object ::=
  "{" ws (
            string ":" ws value
    ("," ws string ":" ws value)*
  )? "}" ws

array  ::=
  "[" ws (
            value
    ("," ws value)*
  )? "]" ws

string ::=
  "\"" (
    [^"\\] |
    "\\" (["\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F]) # escapes
  )* "\"" ws

number ::= ("-"? ([0-9] | [1-9] [0-9]*)) ("." [0-9]+)? ([eE] [-+]? [0-9]+)? ws

ws ::= ([ \t\n] ws)?
"""


class TextStabilizer:
    def __init__(self, history=3, threshold=0.85):
        self.queue = deque(maxlen=history)
        self.threshold = threshold

    def push(self, text):
        clean_text = text.strip()
        if not clean_text or len(clean_text) < 2: return None
        self.queue.append(clean_text)
        if len(self.queue) < self.queue.maxlen: return None

        last_item = self.queue[-1]
        is_stable = True
        for item in self.queue:
            if SequenceMatcher(None, last_item, item).ratio() < self.threshold:
                is_stable = False
                break
        return last_item if is_stable else None


class AIEngine:
    def __init__(self, log_func):
        self.log = log_func
        self.context = deque(maxlen=5)

        # --- OCR ---
        self.log("Загрузка OCR...")
        gpu_mode = cfg.get("ocr_gpu")
        try:
            self.reader = easyocr.Reader(['ru', 'en'], gpu=gpu_mode, verbose=False, quantize=False)
            self.log(f"✅ OCR init (GPU={gpu_mode})")
        except Exception as e:
            self.log(f"⚠️ GPU Error: {e}")
            self.reader = easyocr.Reader(['ru', 'en'], gpu=False, verbose=False)

        # --- LLM ---
        self.log("Загрузка LLM...")
        model_path = os.path.abspath("models/qwen2.5-1.5b-instruct-q4_k_m.gguf")
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model not found: {model_path}")

        self.llm = Llama(
            model_path=model_path,
            n_gpu_layers=-1,
            n_ctx=4096,
            verbose=False
        )

        try:
            self.grammar = LlamaGrammar.from_string(JSON_GBNF)
            self.log("✅ GBNF Grammar loaded (Strict JSON mode)")
        except Exception as e:
            self.log(f"❌ Grammar Load Error: {e}")
            self.grammar = None

    def recognize(self, img):
        h, w = img.shape[:2]
        # Оптимизация: не увеличивать картинку, если она достаточно большая
        if h < 50: img = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_LINEAR)

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Удаляем шум через Threshold, чтобы EasyOCR лучше видел буквы
        _, bin_img = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # detail=0 возвращает список строк, paragraph=True объединяет их в блоки
        res = self.reader.readtext(bin_img, detail=0, paragraph=True)
        return " ".join(res) if res else None

    def _generate(self, text, history_context):
        """Внутренний метод генерации"""
        prompt = (
            f"<|im_start|>system\n"
            f"Ты профессиональный переводчик и корректор. Твоя задача:\n"
            f"1. Исправить ошибки OCR (слипшиеся слова, опечатки) в английском тексте.\n"
            f"2. Перевести исправленный текст на русский язык (художественный перевод).\n"
            f"3. Если текст не требует перевода или это мусор, верни пустую строку.\n"
            f"Формат ответа JSON: {{\"name\": \"Имя (на английском)\", \"gender\": \"m/f\", \"text\": \"Только русский перевод\"}}.\n"
            f"{history_context}\n<|im_end|>\n"
            f"<|im_start|>user\n{text}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )

        output = self.llm.create_completion(
            prompt,
            max_tokens=196,  # Уменьшили для скорости (было 256)
            grammar=self.grammar,
            temperature=0.1,  # Снизили температуру для точности
            repeat_penalty=1.3,  # Увеличили штраф за повторы
            stop=["<|im_end|>"]
        )
        return output

    def translate(self, text):
        STOP_GENERATION.clear()

        # Формируем историю
        hist_str = ""
        if self.context:
            hist_str = "Контекст (НЕ ПОВТОРЯТЬ):\n" + "\n".join([f"- {line}" for line in self.context])

        try:
            # Первая попытка
            output = self._generate(text, hist_str)
            if STOP_GENERATION.is_set(): return None

            json_str = output['choices'][0]['text']
            res = json.loads(json_str)

            # Нормализация ключей
            res = {k.lower(): v for k, v in res.items()}

            final_res = {
                "name": res.get("name", ""),
                "gender": res.get("gender", "m"),
                "text": res.get("text", "").strip()
            }

            if not final_res['text']: return None

            # === ВАЛИДАЦИЯ: Проверка на русский язык ===
            # Если в ответе нет кириллицы, модель скорее всего просто повторила английский текст
            if not re.search(r'[а-яА-ЯёЁ]', final_res['text']):
                self.log(f"⚠️ Detect non-RU response: '{final_res['text']}'. Dropping.")
                return None

                # === ЗАЩИТА ОТ ЦИКЛОВ (Parrot Guard) ===
            is_hallucination = False
            for old_line in self.context:
                old_text = old_line.split(": ", 1)[-1] if ": " in old_line else old_line
                if SequenceMatcher(None, final_res['text'], old_text).ratio() > 0.85:
                    self.log("⚠️ Loop detected. Clearing context.")
                    is_hallucination = True
                    break

            if is_hallucination:
                self.context.clear()
                return None

            # === УСПЕХ: Добавляем в историю только качественный результат ===
            line = f"{final_res['name']}: {final_res['text']}" if final_res['name'] else final_res['text']
            self.context.append(line)

            return final_res

        except json.JSONDecodeError:
            self.log("⚠️ JSON Parse Error")
            return None
        except Exception as e:
            self.log(f"LLM Error: {e}")
            return None

    def abort(self):
        STOP_GENERATION.set()