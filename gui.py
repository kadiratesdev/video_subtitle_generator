#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone GUI for Spanish -> Turkish Subtitle Pipeline
- No web interface
- Single video or entire folder
- Outputs .srt and optional muxed video next to the source video(s)
- Uses large-v3 (STT) + NLLB-1.3B (fast batched greedy translation)
"""

import os
import sys
import threading
import queue
import tempfile
import time
from pathlib import Path
from tkinter import Tk, filedialog, messagebox, StringVar, BooleanVar
from tkinter import ttk
import tkinter as tk
from typing import Optional, Callable

# Add project root to path so we can import steps
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from config import get_config
from steps.extract_audio import extract_audio
from steps.transcribe import transcribe_to_srt
from steps.translate_srt_fast import translate_srt
from steps.embed_subs import embed_soft_subs
from ffmpeg_util import run_ffmpeg
from srt_parser import parse_srt


class SubtitleGUI:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title("İspanyolca → Türkçe Altyazı (Büyük Model)")
        self.root.geometry("780x580")
        self.root.minsize(700, 500)

        self.config = get_config()
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.progress_queue: queue.Queue[dict] = queue.Queue()
        self.is_running = False

        # For ETA / elapsed
        self._proc_start: Optional[float] = None
        self._translate_start: Optional[float] = None
        self._current_eta: str = ""

        self._build_ui()
        self.root.after(80, self._poll_queues)

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        # Title
        title = ttk.Label(main, text="Altyazı Çevirici (Local NLLB / Groq API)", font=("Segoe UI", 14, "bold"))
        title.pack(anchor="w", pady=(0, 10))

        # Options
        opt_frame = ttk.LabelFrame(main, text="Çıktı Seçenekleri", padding=8)
        opt_frame.pack(fill=tk.X, pady=4)

        self.make_srt = BooleanVar(value=True)
        self.make_muxed = BooleanVar(value=True)

        ttk.Checkbutton(opt_frame, text="Türkçe .srt dosyası üret (orijinal video ile aynı klasöre)", variable=self.make_srt).pack(anchor="w")
        ttk.Checkbutton(opt_frame, text="Altyazılı video üret (_tr.mp4)", variable=self.make_muxed).pack(anchor="w")

        # Translator choice
        trans_frame = ttk.LabelFrame(main, text="Çeviri Motoru", padding=8)
        trans_frame.pack(fill=tk.X, pady=4)

        self.use_groq = BooleanVar(value=False)
        ttk.Checkbutton(
            trans_frame,
            text="API kullan (Groq - çok daha hızlı + kaliteli, internet gerekir)",
            variable=self.use_groq
        ).pack(anchor="w")

        ttk.Label(trans_frame, text="Not: Groq kullanıldığında local NLLB modele hiç dokunulmaz.", foreground="#555").pack(anchor="w")

        # Buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=8)

        self.btn_single = ttk.Button(btn_frame, text="Tek Video Seç ve İşle", command=self.select_single_video, width=28)
        self.btn_single.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_folder = ttk.Button(btn_frame, text="Klasör Seç ve Tüm Videoları İşle", command=self.select_folder, width=32)
        self.btn_folder.pack(side=tk.LEFT)

        self.btn_stop = ttk.Button(btn_frame, text="Durdur", command=self.stop, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.RIGHT)

        # Progress
        self.progress = ttk.Progressbar(main, orient="horizontal", mode="determinate", maximum=100)
        self.progress.pack(fill=tk.X, pady=4)

        # Step + time info
        info_frame = ttk.Frame(main)
        info_frame.pack(fill=tk.X, pady=(0, 4))

        self.step_var = StringVar(value="Hazır")
        ttk.Label(info_frame, textvariable=self.step_var, font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)

        ttk.Label(info_frame, text="   |   Geçen: ").pack(side=tk.LEFT)
        self.elapsed_var = StringVar(value="00:00")
        ttk.Label(info_frame, textvariable=self.elapsed_var, font=("Consolas", 10)).pack(side=tk.LEFT)

        ttk.Label(info_frame, text="   Kalan (tahmini): ").pack(side=tk.LEFT)
        self.eta_var = StringVar(value="--:--")
        ttk.Label(info_frame, textvariable=self.eta_var, font=("Consolas", 10)).pack(side=tk.LEFT)

        self.model_info_base = f"STT: {self.config.whisper_model}"
        self.status_var = StringVar(value=f"Hazır • {self.model_info_base} | Çeviri: Local NLLB")
        ttk.Label(main, textvariable=self.status_var).pack(anchor="w")

        # Update status when checkbox changes
        def _update_translator_label(*_):
            if self.use_groq.get():
                self.status_var.set(f"Hazır • {self.model_info_base} | Çeviri: Groq API ({self.config.groq_model})")
            else:
                self.status_var.set(f"Hazır • {self.model_info_base} | Çeviri: Local NLLB")
        self.use_groq.trace_add("write", _update_translator_label)

        # Initial values for new indicators
        self.step_var.set("Hazır")
        self.elapsed_var.set("00:00")
        self.eta_var.set("--:--")

        # Log
        log_frame = ttk.LabelFrame(main, text="İşlem Günlüğü", padding=6)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=8)

        self.log_text = tk.Text(log_frame, height=18, wrap=tk.WORD, font=("Consolas", 10))
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)

        # Bottom
        bottom = ttk.Frame(main)
        bottom.pack(fill=tk.X)
        ttk.Label(bottom, text="Not: API (Groq) seçeneği ile local model yüklenmez ve çok daha hızlı olur. Local için CUDA önerilir.").pack(anchor="w")

    def log(self, msg: str):
        self.log_queue.put(msg)

    def update_progress(self, pct: float, step: str = "", eta: str = ""):
        """Thread-safe progress update (called from worker thread)."""
        if eta:
            self._current_eta = eta
        self.progress_queue.put({
            "pct": max(0.0, min(1.0, pct)),
            "step": step,
            "eta": eta,
        })

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        if seconds < 0:
            seconds = 0
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _poll_queues(self):
        # Logs
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.insert(tk.END, msg + "\n")
                self.log_text.see(tk.END)
        except queue.Empty:
            pass

        # Structured progress / ETA updates
        try:
            while True:
                upd = self.progress_queue.get_nowait()
                if "pct" in upd:
                    try:
                        val = max(0.0, min(100.0, float(upd["pct"]) * 100))
                        self.progress["value"] = val
                    except Exception:
                        pass
                if "step" in upd and upd["step"]:
                    self.step_var.set(str(upd["step"]))
                if "eta" in upd:
                    self.eta_var.set(str(upd.get("eta") or self._current_eta or "--:--"))
        except queue.Empty:
            pass

        # Live elapsed timer while running
        if self._proc_start and self.is_running:
            try:
                elapsed = time.perf_counter() - self._proc_start
                self.elapsed_var.set(self._fmt_time(elapsed))
            except Exception:
                pass

        self.root.after(80, self._poll_queues)

    def set_running(self, running: bool):
        self.is_running = running
        state = tk.DISABLED if running else tk.NORMAL
        self.btn_single.config(state=state)
        self.btn_folder.config(state=state)
        self.btn_stop.config(state=tk.NORMAL if running else tk.DISABLED)

    def stop(self):
        # Soft stop - we don't have hard cancel yet, but we can disable buttons
        self.log("[!] Durdurma istendi (şu anki işlem bitene kadar bekleyecek)")
        self.set_running(False)

    # ---------------------- Core Processing ----------------------

    def process_single(self, video_path: Path):
        if not video_path.exists():
            self.log(f"[HATA] Video bulunamadı: {video_path}")
            return False

        if not self.make_srt.get() and not self.make_muxed.get():
            self.log("[!] Hiçbir çıktı seçilmedi.")
            return False

        self.log(f"\n=== İŞLENİYOR: {video_path.name} ===")

        # Capture API choice early (thread safe snapshot)
        use_api = self.use_groq.get()

        # Announce translation backend immediately
        if use_api:
            self.log(">>> API MODU AKTİF: Çeviri Groq ile yapılacak. Local çeviri modeli (NLLB) yüklenmeyecek.")
            self.log("    (Eğer video ile aynı klasörde .srt varsa, Whisper bile atlanacak.)")
        else:
            self.log(">>> LOCAL MOD: NLLB local model ile çeviri.")

        # Reset timers + progress for this video
        self._proc_start = time.perf_counter()
        self._translate_start = None
        self._current_eta = ""
        self.update_progress(0.0, "Başlıyor...")
        self.elapsed_var.set("00:00")
        self.eta_var.set("--:--")

        out_dir = video_path.parent
        stem = video_path.stem

        # Target outputs next to the video
        final_srt = out_dir / f"{stem}.srt"
        final_video = out_dir / f"{stem}_tr.mp4"

        with tempfile.TemporaryDirectory(prefix="subtitle_") as tmp:
            tmp = Path(tmp)
            audio = tmp / "audio.wav"
            es_srt = tmp / "es.srt"
            tr_srt_temp = tmp / "tr.srt"

            try:
                # Smart skip for API mode if Spanish SRT already exists next to the video
                source_srt = video_path.with_suffix(".srt")
                skip_audio_transcribe = False

                if use_api and source_srt.exists():
                    self.log(f"[1/2] API modu + mevcut SRT bulundu → Ses çıkarma ve Whisper atlanıyor (hiç local model yok).")
                    self.log(f"         Kaynak: {source_srt}")
                    try:
                        es_srt.write_bytes(source_srt.read_bytes())
                    except Exception as copy_err:
                        self.log(f"[UYARI] SRT kopyalanamadı, transkripsiyon yapılacak: {copy_err}")
                    skip_audio_transcribe = True
                    self.update_progress(0.45, "Mevcut SRT ile devam (API)")

                if not skip_audio_transcribe:
                    # 1. Extract (~0-12%)
                    self.log("[1/4] Ses çıkarılıyor...")
                    self.update_progress(0.02, "Ses çıkarılıyor...")
                    extract_audio(video_path, audio)
                    self.update_progress(0.12, "Ses çıkarıldı")

                    # 2. Transcribe (~12-50%)
                    self.log("[2/4] large-v3 ile İspanyolca transkripsiyon...")
                    self.update_progress(0.15, "İspanyolca transkribe ediliyor (Whisper)...")

                    # Run transcribe and report line count live
                    # (we don't know final count in advance, so we show "X satır işlendi")
                    transcribe_to_srt(audio, es_srt, self.config)
                    try:
                        es_content = es_srt.read_text(encoding="utf-8")
                        seg_count = len(parse_srt(es_content))
                        self.log(f"         → {es_srt.stat().st_size} bayt  ({seg_count} satır)")
                        self.update_progress(0.50, f"Transkripsiyon tamam ({seg_count} satır)")
                    except Exception:
                        self.log(f"         → {es_srt.stat().st_size} bayt")
                        self.update_progress(0.50, "Transkripsiyon tamam")
                else:
                    # When we skipped, we are already at ~45-50%
                    self.update_progress(0.50, "SRT hazır (transkripsiyon atlandı)")

                if self.make_srt.get() or self.make_muxed.get():
                    # 3. Translate (50% → 88%, with real-time sub-progress)
                    # Use the captured flag so thread + checkbox race is avoided
                    if use_api:
                        self.log("[3/4] Groq API ile Türkçe çeviri (70B sınıfı model)...")
                        self.update_progress(0.52, "Groq API ile çeviri başlıyor...")
                        try:
                            from steps.translate_groq import translate_srt as groq_translate
                        except Exception as e:
                            self.log(f"[HATA] Groq modülü yüklenemedi: {e}. Lütfen 'pip install groq' yapın.")
                            raise

                        self._translate_start = time.perf_counter()

                        def _on_groq_progress(p: float, done: int, total: int):
                            overall = 0.52 + (p * 0.36)
                            step_txt = f"[API] Çeviri: {done}/{total} satır"
                            eta_str = ""
                            if self._translate_start and done > 2:
                                rate = done / max(time.perf_counter() - self._translate_start, 0.001)
                                remain_sec = (total - done) / max(rate, 1.0)
                                eta_str = self._fmt_time(remain_sec)
                                self._current_eta = eta_str
                            self.update_progress(overall, step_txt, eta_str)

                        groq_translate(es_srt, tr_srt_temp, self.config, progress_cb=_on_groq_progress)
                        self.log("         → Groq ile çevrildi (çok hızlı)")

                    else:
                        self.log("[3/4] Local NLLB ile Türkçe çeviri (hızlı optimize mod)...")
                        self.update_progress(0.52, "Çeviri hazırlanıyor...")

                        # Prepare for real-time progress + ETA
                        es_content = es_srt.read_text(encoding="utf-8")
                        entries = parse_srt(es_content)
                        _ = len(entries)

                        self._translate_start = time.perf_counter()

                        def _on_translate_progress(p: float, done: int, total: int):
                            overall = 0.52 + (p * 0.36)
                            step_txt = f"Çeviri: {done}/{total} satır"
                            eta_str = ""
                            if self._translate_start and done > 3:
                                rate = done / max(time.perf_counter() - self._translate_start, 0.001)
                                remain_sec = (total - done) / max(rate, 1.0)
                                eta_str = self._fmt_time(remain_sec)
                                self._current_eta = eta_str
                            self.update_progress(overall, step_txt, eta_str)

                        translate_srt(es_srt, tr_srt_temp, self.config, progress_cb=_on_translate_progress)

                    if self.make_srt.get():
                        final_srt.write_bytes(tr_srt_temp.read_bytes())
                        self.log(f"         → {final_srt}")

                    self.update_progress(0.88, "Çeviri tamamlandı")

                if self.make_muxed.get():
                    # 4. Embed (88% → 100%)
                    self.log("[4/4] Altyazı videoya gömülüyor...")
                    self.update_progress(0.90, "Altyazı videoya gömülüyor...")
                    embed_soft_subs(video_path, tr_srt_temp, final_video)
                    self.log(f"         → {final_video}")

                self.update_progress(1.0, "Tamamlandı ✓")
                elapsed = time.perf_counter() - self._proc_start
                self.log(f"[✓] BİTTİ: {video_path.name}  (toplam {self._fmt_time(elapsed)})")
                return True

            except Exception as e:
                self.log(f"[HATA] {video_path.name}: {e}")
                import traceback
                self.log(traceback.format_exc())
                self.update_progress(1.0, "Hata oluştu")
                return False

    def process_folder(self, folder: Path):
        # Recursive search for .mp4
        videos = sorted([p for p in folder.rglob("*.mp4") if p.is_file()])
        if not videos:
            self.log(f"[!] {folder} içinde .mp4 video bulunamadı.")
            return

        self.log(f"\n=== KLASÖR İŞLEME (özyinelemeli): {len(videos)} video ===")
        success = 0

        for i, video in enumerate(videos, 1):
            if not self.is_running:
                self.log("[!] İşlem kullanıcı tarafından durduruldu.")
                break

            self.status_var.set(f"İşleniyor ({i}/{len(videos)}): {video.name}")
            self.step_var.set(f"Video {i}/{len(videos)}")
            self.root.update_idletasks()

            if self.process_single(video):
                success += 1

            pct = int((i / len(videos)) * 100)
            self.progress["value"] = pct
            self.eta_var.set("--:--")  # reset per video eta for folder view

        self.progress["value"] = 100
        self.status_var.set(f"Tamamlandı. Başarılı: {success}/{len(videos)}")
        self.step_var.set("Klasör tamamlandı")
        messagebox.showinfo("Bitti", f"Klasör işleme tamamlandı!\nBaşarılı: {success} / {len(videos)}\n\nDosyalar orijinal videoların yanına yazıldı.")

    # ---------------------- UI Actions ----------------------

    def select_single_video(self):
        if self.is_running:
            return
        path = filedialog.askopenfilename(
            title="Video dosyası seç",
            filetypes=[("MP4 Videolar", "*.mp4"), ("Tüm dosyalar", "*.*")]
        )
        if not path:
            return

        video = Path(path)
        self.set_running(True)
        self.progress["value"] = 0
        self.log_text.delete("1.0", tk.END)
        self.status_var.set(f"İşleniyor: {video.name}")
        self.elapsed_var.set("00:00")
        self.eta_var.set("--:--")
        self.step_var.set("Hazırlanıyor...")

        # Snapshot API choice before starting thread (safer + used inside process_single)
        # process_single will read self.use_groq.get() once at start

        def worker():
            try:
                ok = self.process_single(video)
                if ok:
                    self.status_var.set("Tamamlandı ✓")
                    messagebox.showinfo("Tamam", f"{video.name} için işlem bitti.\nDosyalar aynı klasöre yazıldı.")
            finally:
                self.set_running(False)
                self.progress["value"] = 100

        threading.Thread(target=worker, daemon=True).start()

    def select_folder(self):
        if self.is_running:
            return
        folder = filedialog.askdirectory(title="İçinde .mp4 videolar olan klasör seç")
        if not folder:
            return

        folder = Path(folder)
        self.set_running(True)
        self.progress["value"] = 0
        self.log_text.delete("1.0", tk.END)
        self.status_var.set(f"Klasör taranıyor: {folder}")
        self.elapsed_var.set("00:00")
        self.eta_var.set("--:--")
        self.step_var.set("Klasör taranıyor...")

        def worker():
            try:
                self.process_folder(folder)
            finally:
                self.set_running(False)

        threading.Thread(target=worker, daemon=True).start()


def main():
    root = Tk()
    app = SubtitleGUI(root)

    # Optional: set icon if exists
    try:
        root.iconbitmap("icon.ico")
    except Exception:
        pass

    root.mainloop()


if __name__ == "__main__":
    main()


# ==================== KURULUMSUZ / PORTABLE İÇİN ====================
#
# 1. Bu klasörde (aaaaaaa) şu komutla çalıştır:
#    python gui.py
#
# 2. Tek .exe yapmak istersen (PyInstaller ile):
#
#    pip install pyinstaller
#    pyinstaller --onefile --windowed --name "TurkceAltyazi" gui.py
#
#    Oluşan dist/TurkceAltyazi.exe dosyasını modellerin olduğu bilgisayarda çalıştır.
#    Modeller ilk seferde HuggingFace cache'ine iner (C:\Users\...\ .cache\huggingface)
#
# 3. Not: CUDA (NVIDIA) kurulu olmalı ve torch CUDA sürümü yüklü olmalı.
#    Aksi halde CPU'da çok yavaş çalışır.
#
# ================================================================