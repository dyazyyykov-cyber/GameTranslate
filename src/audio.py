import os
import torch
import sounddevice as sd
import random
import threading
import time
import re  # Добавлено для проверки языка

class AudioPlayer:
    def __init__(self):
        # Загрузка Silero V4 локально
        path = os.path.abspath("models/v4_ru.pt")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Models missing: {path}")

        self.device = torch.device('cpu')
        self.model = torch.package.PackageImporter(path).load_pickle("tts_models", "model")
        self.model.to(self.device)

        self.sample_rate = 48000
        self.speakers = {'m': ['aidar', 'eugene'], 'f': ['kseniya', 'xenia', 'baya']}
        self.char_map = {}
        self.current_stream = None

    def speak(self, text, name, gender):
        """
        Генерирует и воспроизводит аудио.
        Возвращает tuple: (duration_seconds, speaker_name)
        """
        if not text: return 0.0, "None"

        # ПРОВЕРКА ЯЗЫКА
        # Модель Silero RU сломается на чисто английском тексте.
        # Если в тексте нет ни одной русской буквы -> пропускаем озвучку.
        if not re.search(r'[а-яА-ЯёЁ]', text):
            return 0.0, "Skipped (No RU)"

        # Назначаем постоянный голос персонажу
        if name and name not in self.char_map:
            pool = self.speakers.get(gender.lower(), self.speakers['m'])
            self.char_map[name] = random.choice(pool)

        speaker = self.char_map.get(name, 'aidar')

        try:
            # Генерация аудио (Tensor)
            audio = self.model.apply_tts(text=text, speaker=speaker, sample_rate=self.sample_rate)
            audio_np = audio.numpy()

            self.stop()

            duration = len(audio_np) / self.sample_rate
            sd.play(audio_np, self.sample_rate)

            return duration, speaker

        except Exception as e:
            print(f"TTS Error: {e}")
            return 0.0, "Error"

    def stop(self):
        sd.stop()