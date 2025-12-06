#!/usr/bin/env python3
"""
GameTranslate - Real-Time Game Dialogue Translation
Перевод и озвучивание игровых диалогов в реальном времени

Оптимизировано для RTX 4060 (8GB VRAM)
"""

import cv2
import torch
import numpy as np
import argparse
from pathlib import Path

# Проверка CUDA
if not torch.cuda.is_available():
    print("⚠️ CUDA недоступна! Проверьте установку PyTorch с CUDA support")
    print("Установите: pip install torch --index-url https://download.pytorch.org/whl/cu124")
    exit(1)

print(f"✅ CUDA доступна: {torch.cuda.get_device_name(0)}")
print(f"✅ VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")


class GameTranslator:
    """
    Основной класс для перевода игровых диалогов
    """
    
    def __init__(self, models_dir="AImodels"):
        self.models_dir = Path(models_dir)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        print(f"\n🚀 Инициализация GameTranslator...")
        print(f"📁 Папка моделей: {self.models_dir}")
        print(f"🎮 Устройство: {self.device}")
        
        # Проверка моделей
        self._check_models()
        
        # Инициализация компонентов (загрузка по требованию)
        self.ocr_model = None
        self.translator_model = None  
        self.tts_model = None
        
    def _check_models(self):
        """Проверка наличия скачанных моделей"""
        if not self.models_dir.exists():
            print(f"\n❌ Папка {self.models_dir} не найдена!")
            print("📥 Запустите: python download_models.py")
            exit(1)
            
        required_models = ["qwen25_7b", "paddleocr", "kokoro"]
        missing = []
        
        for model in required_models:
            if not (self.models_dir / model).exists():
                missing.append(model)
        
        if missing:
            print(f"\n❌ Отсутствуют модели: {', '.join(missing)}")
            print("📥 Запустите: python download_models.py")
            exit(1)
            
        print("✅ Все модели найдены")
    
    def load_ocr(self):
        """Загрузка OCR модели (PaddleOCR + CLIP)"""
        if self.ocr_model is not None:
            return
            
        print("\n📷 Загрузка OCR модели...")
        from paddleocr import PaddleOCR
        
        self.ocr_model = PaddleOCR(
            use_angle_cls=True,
            lang='en',
            use_gpu=True,
            show_log=False
        )
        print("✅ OCR загружена")
    
    def load_translator(self):
        """Загрузка модели перевода (Qwen 2.5 7B)"""
        if self.translator_model is not None:
            return
            
        print("\n🔤 Загрузка модели перевода...")
        # TODO: Добавить загрузку Qwen 2.5 7B через llama-cpp-python
        # from llama_cpp import Llama
        # self.translator_model = Llama(...)
        print("⚠️ Модель перевода: заглушка (добавьте код загрузки)")
    
    def load_tts(self):
        """Загрузка TTS модели (Kokoro)"""
        if self.tts_model is not None:
            return
            
        print("\n🔊 Загрузка TTS модели...")
        # TODO: Добавить загрузку Kokoro TTS
        print("⚠️ TTS модель: заглушка (добавьте код загрузки)")
    
    def extract_text_from_frame(self, frame):
        """
        Извлечение текста из кадра игры через OCR
        
        Args:
            frame: numpy array с изображением
            
        Returns:
            str: распознанный текст
        """
        self.load_ocr()
        
        # OCR на нижней части экрана (где обычно субтитры)
        h, w = frame.shape[:2]
        dialogue_region = frame[h*3//4:h, :]
        
        results = self.ocr_model.ocr(dialogue_region, cls=True)
        
        if not results or not results[0]:
            return ""
        
        # Объединяем распознанный текст
        text_lines = []
        for line in results[0]:
            if line:
                text_lines.append(line[1][0])
        
        return ' '.join(text_lines)
    
    def translate_text(self, text, source_lang="en", target_lang="ru"):
        """
        Перевод текста
        
        Args:
            text: исходный текст
            source_lang: язык источника
            target_lang: целевой язык
            
        Returns:
            str: переведённый текст
        """
        if not text:
            return ""
            
        self.load_translator()
        
        # TODO: Добавить реальный перевод через Qwen
        # Заглушка для демонстрации
        print(f"🔤 Перевод: {text[:50]}...")
        return f"[ПЕРЕВОД] {text}"
    
    def speak_text(self, text, voice="ru_RU"):
        """
        Озвучивание текста через TTS
        
        Args:
            text: текст для озвучивания
            voice: голос TTS
            
        Returns:
            bytes: аудио данные
        """
        if not text:
            return None
            
        self.load_tts()
        
        # TODO: Добавить реальное озвучивание через Kokoro
        print(f"🔊 Озвучивание: {text[:30]}...")
        return None
    
    def process_frame(self, frame):
        """
        Полная обработка одного кадра
        
        Args:
            frame: кадр из игры
            
        Returns:
            tuple: (original_text, translated_text, audio)
        """
        # 1. Извлечение текста
        original = self.extract_text_from_frame(frame)
        
        if not original:
            return None, None, None
        
        # 2. Перевод
        translated = self.translate_text(original)
        
        # 3. Озвучивание
        audio = self.speak_text(translated)
        
        return original, translated, audio


def process_webcam(translator):
    """Тестовый режим с веб-камерой"""
    print("\n📹 Запуск в режиме веб-камеры")
    print("Нажмите 'q' для выхода")
    
    cap = cv2.VideoCapture(0)
    
    last_text = ""
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        # Показываем кадр
        cv2.imshow('GameTranslate - Webcam', frame)
        
        # Обработка каждого 30-го кадра
        if cap.get(cv2.CAP_PROP_POS_FRAMES) % 30 == 0:
            original, translated, _ = translator.process_frame(frame)
            
            if original and original != last_text:
                print(f"\n🎮 Оригинал: {original}")
                print(f"🔤 Перевод: {translated}")
                last_text = original
        
        # Выход по 'q'
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    
    cap.release()
    cv2.destroyAllWindows()


def process_game_window(translator, window_name=None):
    """Захват конкретного окна игры"""
    print(f"\n🎮 Захват окна игры: {window_name or 'любое'}")
    
    # TODO: Реализовать захват окна через mss или pyautogui
    print("⚠️ Режим захвата игры: в разработке")
    print("💡 Используйте --webcam для тестирования")


def main():
    parser = argparse.ArgumentParser(
        description="GameTranslate - Перевод игровых диалогов в реальном времени"
    )
    parser.add_argument(
        "--webcam",
        action="store_true",
        help="Тестовый режим с веб-камерой"
    )
    parser.add_argument(
        "--game",
        type=str,
        help="Название игры для захвата окна"
    )
    parser.add_argument(
        "--models-dir",
        type=str,
        default="AImodels",
        help="Папка с AI моделями"
    )
    
    args = parser.parse_args()
    
    # Инициализация переводчика
    translator = GameTranslator(models_dir=args.models_dir)
    
    # Выбор режима
    if args.webcam:
        process_webcam(translator)
    elif args.game:
        process_game_window(translator, args.game)
    else:
        print("\n❌ Укажите режим работы:")
        print("   --webcam          Тестирование с веб-камерой")
        print("   --game <name>     Захват окна игры")
        print("\nПример: python main.py --webcam")


if __name__ == "__main__":
    main()
