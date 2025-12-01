"""
Real-time game subtitle translator for Windows.

Dependencies (install in a virtual environment):
  pip install mss pillow numpy easyocr argostranslate pyttsx3 keyboard

Usage:
  1) Install Argos Translate language package for SRC_LANG -> TGT_LANG.
  2) Run: python main.py
  3) Select the subtitle region when prompted (drag rectangle).
  4) Press F9 to start/pause capture; press F10 to exit.
"""
import sys
import time
import threading
import queue
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import mss
import keyboard
import pyttsx3
from argostranslate import translate as argos_translate

try:
    import easyocr
except Exception as exc:  # pragma: no cover - defensive import handling
    print("Failed to import easyocr. Please install it via `pip install easyocr`.")
    raise exc

# --- Settings ---
SRC_LANG = "en"  # Source language code for OCR/translation
TGT_LANG = "ru"  # Target language code for translation/TTS
CAPTURE_INTERVAL_MS = 150  # Interval between screen captures
DIFF_THRESHOLD = 5.0  # Percentage difference threshold to detect text change

# Captured region will be assigned after user selection.
CAPTURE_REGION: Optional[Tuple[int, int, int, int]] = None


@dataclass
class FrameData:
    """Container for a captured frame and timestamp."""

    image: np.ndarray
    captured_at: float


def select_region_with_tk() -> Tuple[int, int, int, int]:
    """Let the user select a rectangular region using a transparent tkinter overlay."""

    try:
        import tkinter as tk
    except Exception as exc:  # pragma: no cover - tkinter availability check
        print("tkinter is required for region selection. Install or enable it on your system.")
        raise exc

    coords = {"start": None, "end": None}

    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.attributes("-alpha", 0.3)
    root.attributes("-topmost", True)
    root.configure(background="black")
    root.title("Select subtitle region (drag to draw)")

    canvas = tk.Canvas(root, cursor="cross", bg="black", highlightthickness=0)
    canvas.pack(fill=tk.BOTH, expand=True)
    rect = None

    def on_press(event):
        coords["start"] = (event.x_root, event.y_root)

    def on_drag(event):
        nonlocal rect
        if coords["start"] is None:
            return
        if rect:
            canvas.delete(rect)
        rect = canvas.create_rectangle(
            coords["start"][0],
            coords["start"][1],
            event.x_root,
            event.y_root,
            outline="red",
            width=2,
        )

    def on_release(event):
        coords["end"] = (event.x_root, event.y_root)
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)

    print("Draw a rectangle over the subtitle area. Release mouse to confirm.")
    root.mainloop()

    if not coords["start"] or not coords["end"]:
        raise RuntimeError("Region selection was not completed.")

    x1, y1 = coords["start"]
    x2, y2 = coords["end"]
    left, top = min(x1, x2), min(y1, y2)
    width, height = abs(x2 - x1), abs(y2 - y1)
    if width == 0 or height == 0:
        raise RuntimeError("Invalid region size. Please try again.")

    print(f"Selected region: left={left}, top={top}, width={width}, height={height}")
    return left, top, width, height


def capture_loop(
    frame_queue: queue.Queue,
    running_event: threading.Event,
    stop_event: threading.Event,
):
    """Continuously capture the selected screen region and enqueue new frames."""

    global CAPTURE_REGION
    with mss.mss() as sct:
        last_frame: Optional[np.ndarray] = None
        while not stop_event.is_set():
            if not running_event.is_set() or CAPTURE_REGION is None:
                time.sleep(0.1)
                continue

            left, top, width, height = CAPTURE_REGION
            monitor = {"left": left, "top": top, "width": width, "height": height}
            raw = sct.grab(monitor)
            frame = np.array(raw)[..., :3]  # Drop alpha channel

            if last_frame is not None:
                diff = np.mean(np.abs(frame.astype(np.int16) - last_frame.astype(np.int16)))
                diff = (diff / 255.0) * 100.0
                if diff < DIFF_THRESHOLD:
                    time.sleep(CAPTURE_INTERVAL_MS / 1000.0)
                    continue

            last_frame = frame
            try:
                frame_queue.put(FrameData(frame, time.time()), timeout=0.1)
            except queue.Full:
                pass
            time.sleep(CAPTURE_INTERVAL_MS / 1000.0)


def ocr_worker(
    frame_queue: queue.Queue,
    text_queue: queue.Queue,
    stop_event: threading.Event,
):
    """Run OCR on frames and pass recognized text to the translation queue."""

    reader = easyocr.Reader([SRC_LANG], gpu=False)
    while not stop_event.is_set():
        try:
            frame_data: FrameData = frame_queue.get(timeout=0.2)
        except queue.Empty:
            continue

        result = reader.readtext(frame_data.image, detail=0, paragraph=True)
        text = "\n".join(result) if result else ""
        if text.strip():
            try:
                text_queue.put(text, timeout=0.1)
            except queue.Full:
                pass
        frame_queue.task_done()


def load_translator():
    """Load Argos Translate model for configured languages."""

    installed_languages = argos_translate.get_installed_languages()
    for lang in installed_languages:
        if lang.code == SRC_LANG:
            for to_lang in lang.translation_languages:
                if to_lang.code == TGT_LANG:
                    return lang.get_translation(to_lang)
    return None


def translation_worker(
    text_queue: queue.Queue,
    tts_queue: queue.Queue,
    stop_event: threading.Event,
):
    """Translate text, avoid duplicates, and enqueue for TTS playback."""

    translator = load_translator()
    if translator is None:
        print(
            f"No Argos Translate package found for {SRC_LANG}->{TGT_LANG}. "
            "Please install the model and restart."
        )
        stop_event.set()
        return

    cache = {}
    last_text = ""
    while not stop_event.is_set():
        try:
            text = text_queue.get(timeout=0.2)
        except queue.Empty:
            continue

        cleaned = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if not cleaned or cleaned == last_text:
            text_queue.task_done()
            continue

        if cleaned in cache:
            translated = cache[cleaned]
        else:
            try:
                translated = translator.translate(cleaned)
                cache[cleaned] = translated
            except Exception as exc:  # pragma: no cover - runtime translation error
                print(f"Translation failed: {exc}")
                text_queue.task_done()
                continue

        last_text = cleaned
        print("\n--- New subtitle ---")
        print(f"Original: {cleaned}")
        print(f"Translated: {translated}")

        try:
            tts_queue.put(translated, timeout=0.1)
        except queue.Full:
            pass

        text_queue.task_done()


def tts_worker(tts_queue: queue.Queue, stop_event: threading.Event):
    """Speak translated text using local TTS engine."""

    engine = pyttsx3.init()
    while not stop_event.is_set():
        try:
            text = tts_queue.get(timeout=0.2)
        except queue.Empty:
            continue

        try:
            engine.stop()  # Interrupt previous speech if necessary
            engine.say(text)
            engine.runAndWait()
        except Exception as exc:  # pragma: no cover - runtime TTS error
            print(f"TTS error: {exc}")

        tts_queue.task_done()


def setup_hotkeys(running_event: threading.Event, stop_event: threading.Event):
    """Configure keyboard shortcuts for start/pause and exit."""

    def toggle_running():
        if running_event.is_set():
            running_event.clear()
            print("[STATE] Paused")
        else:
            running_event.set()
            print("[STATE] Running")

    def request_exit():
        print("[STATE] Stopping...")
        stop_event.set()

    keyboard.add_hotkey("f9", toggle_running)
    keyboard.add_hotkey("f10", request_exit)
    print("Hotkeys: F9 start/pause, F10 exit")


def main():
    """Entry point: select region, start worker threads, manage lifecycle."""

    global CAPTURE_REGION
    print("Starting subtitle translator...")
    CAPTURE_REGION = select_region_with_tk()

    running_event = threading.Event()
    stop_event = threading.Event()

    frame_queue: queue.Queue[FrameData] = queue.Queue(maxsize=5)
    text_queue: queue.Queue[str] = queue.Queue(maxsize=5)
    tts_queue: queue.Queue[str] = queue.Queue(maxsize=5)

    setup_hotkeys(running_event, stop_event)

    capture_thread = threading.Thread(
        target=capture_loop, args=(frame_queue, running_event, stop_event), daemon=True
    )
    ocr_thread = threading.Thread(
        target=ocr_worker, args=(frame_queue, text_queue, stop_event), daemon=True
    )
    translator_thread = threading.Thread(
        target=translation_worker, args=(text_queue, tts_queue, stop_event), daemon=True
    )
    speaker_thread = threading.Thread(
        target=tts_worker, args=(tts_queue, stop_event), daemon=True
    )

    capture_thread.start()
    ocr_thread.start()
    translator_thread.start()
    speaker_thread.start()

    print("Press F9 to start/pause, F10 to quit.")
    try:
        while not stop_event.is_set():
            time.sleep(0.2)
    except KeyboardInterrupt:
        stop_event.set()

    running_event.set()  # Allow threads to exit any waits
    capture_thread.join(timeout=1.0)
    ocr_thread.join(timeout=1.0)
    translator_thread.join(timeout=1.0)
    speaker_thread.join(timeout=1.0)
    print("Shutdown complete.")


if __name__ == "__main__":
    if sys.platform != "win32":
        print("Warning: This script is designed for Windows. Some features may not work here.")
    main()
