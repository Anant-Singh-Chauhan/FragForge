"""
FragForge — Automated Tactical Shorts Engine
--------------------------------------------
Standalone desktop GUI to trigger and monitor highlight compilation for
VALORANT and CS2. Built with CustomTkinter.

Install the dependency:
    pip install customtkinter
"""

import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

PROJECT_ROOT = Path(__file__).resolve().parent
RAW_CLIPS_DIR = PROJECT_ROOT / "raw_clips"
OUTPUT_DIR = PROJECT_ROOT / "output"
CONFIG_PATH = PROJECT_ROOT / "config.json"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
BATCH_SCRIPT = SCRIPTS_DIR / "batch_compile.py"

# --- Brand palette ---
COLOR_BG = "#15161c"
COLOR_CARD = "#1c1e27"
COLOR_ACCENT = "#0077ff"
COLOR_ACCENT_HOVER = "#005ecb"
COLOR_TEXT = "#f0f0f5"
COLOR_SUBTEXT = "#7e8597"
COLOR_BORDER = "#2a2d3a"
COLOR_SUCCESS = "#98c379"
COLOR_ERROR = "#e06c75"
COLOR_CONSOLE_BG = "#0e0f13"

ctk.set_appearance_mode("dark")


class Badge(ctk.CTkFrame):
    """Small rounded pill showing a label + count, used for per-game clip status."""
    def __init__(self, master, label: str, accent: str):
        super().__init__(master, fg_color=COLOR_BG, corner_radius=14, border_width=1, border_color=COLOR_BORDER)
        self._label = label
        self._dot = ctk.CTkLabel(self, text="●", text_color=accent, font=("Segoe UI", 11))
        self._dot.pack(side="left", padx=(10, 4), pady=4)
        self._text = ctk.CTkLabel(self, text=f"{label}: 0 clip(s)", text_color=COLOR_TEXT, font=("Segoe UI", 11))
        self._text.pack(side="left", padx=(0, 12), pady=4)

    def set_count(self, count: int):
        self._text.configure(text=f"{self._label}: {count} clip(s)")


class FragForgeApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("FragForge — Automated Tactical Shorts Engine")
        self.geometry("920x700")
        self.minsize(820, 580)
        self.configure(fg_color=COLOR_BG)

        self.log_queue = queue.Queue()
        self.is_running = False
        self.process = None

        self._build_ui()
        self.scan_staged_clips()
        self.after(100, self._process_log_queue)

        # Handle window close gracefully so running background renders aren't orphaned
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------------- UI ---

    def _build_ui(self):
        self._build_header()
        self._build_control_card()
        self._build_run_button()
        self._build_console()

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(18, 6))

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left")

        ctk.CTkLabel(
            title_box, text="FragForge", text_color=COLOR_ACCENT,
            font=("Segoe UI", 22, "bold"),
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_box, text="Automated Tactical Shorts Engine · VALORANT & CS2",
            text_color=COLOR_SUBTEXT, font=("Segoe UI", 12),
        ).pack(anchor="w")

        btn_box = ctk.CTkFrame(header, fg_color="transparent")
        btn_box.pack(side="right")

        ctk.CTkButton(
            btn_box, text="⚙  Config", command=self.open_config,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER, corner_radius=8, width=100,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_box, text="📁  Exports", command=self.open_output_folder,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER, corner_radius=8, width=100,
        ).pack(side="right")

    def _build_control_card(self):
        card = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        card.pack(fill="x", padx=20, pady=10)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(
            inner, text="BATCH CONTROLS & STAGING", text_color=COLOR_SUBTEXT,
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 12))

        # Row 1: game selector, auto-compile toggle, action buttons
        row1 = ctk.CTkFrame(inner, fg_color="transparent")
        row1.grid(row=1, column=0, columnspan=6, sticky="ew")
        row1.columnconfigure(2, weight=1)

        ctk.CTkLabel(row1, text="Target Game", text_color=COLOR_TEXT, font=("Segoe UI", 11)).grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )

        self.game_var = tk.StringVar(value="all")
        self.game_menu = ctk.CTkOptionMenu(
            row1, values=["all", "valo", "cs2"], variable=self.game_var,
            command=lambda _: self.scan_staged_clips(),
            fg_color=COLOR_BG, button_color=COLOR_BORDER, button_hover_color=COLOR_ACCENT,
            text_color=COLOR_TEXT, corner_radius=8, width=110,
        )
        self.game_menu.grid(row=0, column=1, sticky="w", padx=(0, 24))

        self.auto_yes_var = tk.BooleanVar(value=True)
        ctk.CTkSwitch(
            row1, text="Auto-compile if over 54s limit", variable=self.auto_yes_var,
            text_color=COLOR_TEXT, font=("Segoe UI", 11),
            progress_color=COLOR_ACCENT, button_color=COLOR_TEXT,
        ).grid(row=0, column=2, sticky="w")

        ctk.CTkButton(
            row1, text="+ Stage Clip(s)", command=self.stage_new_clips,
            fg_color=COLOR_BG, hover_color=COLOR_BORDER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER, corner_radius=8, width=130,
        ).grid(row=0, column=3, padx=(0, 8))

        ctk.CTkButton(
            row1, text="🔄  Refresh", command=self.scan_staged_clips,
            fg_color=COLOR_BG, hover_color=COLOR_BORDER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER, corner_radius=8, width=100,
        ).grid(row=0, column=4)

        # Row 2: status badges
        row2 = ctk.CTkFrame(inner, fg_color="transparent")
        row2.grid(row=2, column=0, columnspan=6, sticky="w", pady=(14, 0))

        ctk.CTkLabel(row2, text="raw_clips/", text_color=COLOR_SUBTEXT, font=("Segoe UI", 11)).pack(
            side="left", padx=(0, 10)
        )

        self.badge_valo = Badge(row2, "VALORANT", "#ff4655")
        self.badge_valo.pack(side="left", padx=(0, 8))

        self.badge_cs2 = Badge(row2, "CS2", "#f2a900")
        self.badge_cs2.pack(side="left")

    def _build_run_button(self):
        self.run_btn = ctk.CTkButton(
            self, text="▶    Forge Shorts Batch", command=self.start_pipeline,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, text_color="#ffffff",
            font=("Segoe UI", 14, "bold"), corner_radius=10, height=48,
        )
        self.run_btn.pack(fill="x", padx=20, pady=(4, 10))

    def _build_console(self):
        card = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        card.pack(fill="both", expand=True, padx=20, pady=(0, 18))

        ctk.CTkLabel(
            card, text="BUILD & OCR CONSOLE", text_color=COLOR_SUBTEXT,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=16, pady=(12, 6))

        self.log_text = ctk.CTkTextbox(
            card, fg_color=COLOR_CONSOLE_BG, text_color=COLOR_TEXT,
            font=("Consolas", 11), corner_radius=8, wrap="word",
            border_width=1, border_color=COLOR_BORDER,
        )
        self.log_text.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        # Color tags for log lines
        self.log_text.tag_config("success", foreground=COLOR_SUCCESS)
        self.log_text.tag_config("error", foreground=COLOR_ERROR)
        self.log_text.tag_config("muted", foreground=COLOR_SUBTEXT)

    # ---------------------------------------------------------- Logging ---

    def _append_log(self, line: str):
        lowered = line.lower()
        if "failed" in lowered or "error" in lowered:
            tag = "error"
        elif "done" in lowered or "complete" in lowered or "peak at" in lowered:
            tag = "success"
        elif line.startswith("[FragForge]"):
            tag = "muted"
        else:
            tag = None

        if tag:
            self.log_text.insert("end", line, tag)
        else:
            self.log_text.insert("end", line)
        self.log_text.see("end")

    # ------------------------------------------------------------ Logic ---

    def scan_staged_clips(self):
        exts = {".mp4", ".mkv", ".mov"}
        counts = {"valo": 0, "cs2": 0}

        for fld in ["valo", "valorant"]:
            p = RAW_CLIPS_DIR / fld
            if p.exists() and p.is_dir():
                counts["valo"] += sum(1 for f in p.iterdir() if f.is_file() and f.suffix.lower() in exts)

        for fld in ["cs2", "cs", "counter-strike"]:
            p = RAW_CLIPS_DIR / fld
            if p.exists() and p.is_dir():
                counts["cs2"] += sum(1 for f in p.iterdir() if f.is_file() and f.suffix.lower() in exts)

        self.badge_valo.set_count(counts["valo"])
        self.badge_cs2.set_count(counts["cs2"])

    def stage_new_clips(self):
        target = self.game_var.get()

        # Guardrail: avoid accidentally dumping CS2 clips into VALO if dropdown is left on "all"
        if target == "all":
            messagebox.showinfo(
                "Select Specific Game",
                "Please choose either 'valo' or 'cs2' from the 'Target Game' dropdown before staging clips."
            )
            return

        dest_dir = RAW_CLIPS_DIR / target
        dest_dir.mkdir(parents=True, exist_ok=True)

        files = filedialog.askopenfilenames(
            title=f"Select Raw Gameplay Clips for {target.upper()}",
            filetypes=[("Video Files", "*.mp4 *.mkv *.mov"), ("All Files", "*.*")],
        )
        if not files:
            return

        copied = 0
        for f in files:
            src = Path(f)
            dest = dest_dir / src.name
            if not dest.exists():
                shutil.copy2(src, dest)
                copied += 1

        self._append_log(f"[FragForge] Staged {copied} clip(s) into raw_clips/{target}/\n")
        self.scan_staged_clips()

    def open_config(self):
        if CONFIG_PATH.exists():
            os.startfile(CONFIG_PATH)
        else:
            messagebox.showerror("Error", f"Config file not found at {CONFIG_PATH}")

    def open_output_folder(self):
        OUTPUT_DIR.mkdir(exist_ok=True)
        os.startfile(OUTPUT_DIR)

    def start_pipeline(self):
        if self.is_running:
            return

        self.is_running = True
        self.run_btn.configure(state="disabled", text="⏳  Forging Shorts...")
        self.log_text.delete("1.0", "end")
        self._append_log("[FragForge] Initializing pipeline run...\n")

        thread = threading.Thread(target=self._run_subprocess, daemon=True)
        thread.start()

    def _run_subprocess(self):
        cmd = [sys.executable, "-u", str(BATCH_SCRIPT)]

        game = self.game_var.get()
        if game != "all":
            cmd.extend(["--game", game])

        if self.auto_yes_var.get():
            cmd.append("--yes")

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )

            for line in self.process.stdout:
                self.log_queue.put(line)

            self.process.wait()
            self.log_queue.put(f"\n[FragForge] Complete. Exit code: {self.process.returncode}\n")
        except Exception as e:
            self.log_queue.put(f"\n[FragForge Error] {str(e)}\n")
        finally:
            self.log_queue.put("__PROCESS_COMPLETE__")

    def _process_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if msg == "__PROCESS_COMPLETE__":
                    self.is_running = False
                    self.run_btn.configure(state="normal", text="▶    Forge Shorts Batch")
                    self.scan_staged_clips()
                else:
                    self._append_log(msg)
        except queue.Empty:
            pass

        self.after(100, self._process_log_queue)

    def _on_close(self):
        if self.is_running and self.process and self.process.poll() is None:
            if messagebox.askyesno("Exit FragForge", "A batch compile is currently running.\nStop processing and exit?"):
                try:
                    self.process.terminate()
                except Exception:
                    pass
                self.destroy()
        else:
            self.destroy()


if __name__ == "__main__":
    app = FragForgeApp()
    app.mainloop()