import cv2
import numpy as np
from PIL import ImageGrab, Image, ImageTk
import easyocr
from deep_translator import GoogleTranslator
import tkinter as tk
from tkinter import ttk
import threading
import time

class TranslatorOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Game Translator")
        self.root.geometry("400x300")
        self.root.attributes('-topmost', True)
        
        # OCR и переводчик
        self.reader = None
        self.translator = GoogleTranslator(source='auto', target='ru')
        self.region = None
        self.running = False
        
        self.setup_gui()
        
    def setup_gui(self):
        # Кнопки управления
        control_frame = ttk.Frame(self.root)
        control_frame.pack(pady=10)
        
        ttk.Button(control_frame, text="Инициализация OCR", 
                  command=self.init_ocr).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Выбрать область", 
                  command=self.select_region).pack(side=tk.LEFT, padx=5)
        
        self.start_btn = ttk.Button(control_frame, text="▶ Старт", 
                                     command=self.toggle_translation)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        
        # Настройки
        settings_frame = ttk.LabelFrame(self.root, text="Настройки")
        settings_frame.pack(padx=10, pady=5, fill=tk.X)
        
        ttk.Label(settings_frame, text="Интервал (сек):").grid(row=0, column=0, padx=5)
        self.interval_var = tk.DoubleVar(value=1.0)
        ttk.Spinbox(settings_frame, from_=0.5, to=5.0, increment=0.5, 
                   textvariable=self.interval_var, width=10).grid(row=0, column=1)
        
        # Текстовое поле для вывода
        text_frame = ttk.LabelFrame(self.root, text="Перевод")
        text_frame.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)
        
        self.text_widget = tk.Text(text_frame, wrap=tk.WORD, height=10)
        self.text_widget.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(self.text_widget)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_widget.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.text_widget.yview)
        
    def init_ocr(self):
        self.text_widget.insert(tk.END, "Загрузка OCR модели...\n")
        self.root.update()
        
        def load():
            self.reader = easyocr.Reader(['en'], gpu=False)
            self.text_widget.insert(tk.END, "✓ OCR готов!\n")
        
        threading.Thread(target=load, daemon=True).start()
    
    def select_region(self):
        self.root.iconify()
        time.sleep(0.3)
        
        screenshot = ImageGrab.grab()
        img = np.array(screenshot)
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        
        self.region = cv2.selectROI("Выбери область (Enter для подтверждения)", 
                                    img, fromCenter=False)
        cv2.destroyAllWindows()
        
        self.root.deiconify()
        self.text_widget.insert(tk.END, f"✓ Область: {self.region}\n")
    
    def capture_and_translate(self):
        if not self.region or not self.reader:
            return
        
        x, y, w, h = self.region
        screenshot = ImageGrab.grab(bbox=(x, y, x+w, y+h))
        img = np.array(screenshot)
        
        results = self.reader.readtext(img)
        
        if results:
            text = ' '.join([item[1] for item in results])
            if text.strip():
                try:
                    translated = self.translator.translate(text)
                    
                    self.text_widget.insert(tk.END, f"\n{'='*40}\n")
                    self.text_widget.insert(tk.END, f"EN: {text}\n")
                    self.text_widget.insert(tk.END, f"RU: {translated}\n")
                    self.text_widget.see(tk.END)
                except:
                    pass
    
    def translation_loop(self):
        while self.running:
            self.capture_and_translate()
            time.sleep(self.interval_var.get())
    
    def toggle_translation(self):
        if not self.running:
            self.running = True
            self.start_btn.config(text="⏸ Стоп")
            threading.Thread(target=self.translation_loop, daemon=True).start()
        else:
            self.running = False
            self.start_btn.config(text="▶ Старт")
    
    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    app = TranslatorOverlay()
    app.run()
