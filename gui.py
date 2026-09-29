"""
FragForge — Automated Tactical Shorts Engine
--------------------------------------------
Standalone desktop GUI with integrated tabs:
  1. ⚡ Forge       : Live pipeline execution, clip staging, and terminal console
  2. 📹 Raw Clips   : In-app browser for staged clips (Play, Reveal, Filter, Delete)
  3. 📁 Exports     : In-app video browser for completed Shorts and trimmed pieces
  4. ⚙ Config      : In-app JSON editor with live syntax validation and saving

Requires:
  pip install customtkinter pillow
"""

import ctypes
from datetime import datetime
import json
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
from PIL import Image, ImageTk

# Force Windows to treat FragForge as its own application on the Taskbar
if sys.platform == "win32":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "fragforge.shortsengine.desktop.1.0"
        )
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent
RAW_CLIPS_DIR = PROJECT_ROOT / "raw_clips"
OUTPUT_DIR = PROJECT_ROOT / "output"
TRIMMED_DIR = OUTPUT_DIR / "trimmed"
CONFIG_PATH = PROJECT_ROOT / "config.json"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
BATCH_SCRIPT = SCRIPTS_DIR / "batch_compile.py"

# Public & Branding Asset Directories
PUBLIC_ASSETS_DIR = PROJECT_ROOT / "assets" / "public"
BRANDING_DIR = PROJECT_ROOT / "assets" / "branding"

# Primary App Icons
APP_ICON_ICO = PUBLIC_ASSETS_DIR / "appIcon.ico"
APP_ICON_PNG = PUBLIC_ASSETS_DIR / "appIcon.png"

# --- Tactical Palette ---
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
COLOR_VALO = "#ff4655"
COLOR_CS2 = "#f2a900"

ctk.set_appearance_mode("dark")


class Badge(ctk.CTkFrame):
    """Small pill showing a label + count for clip status."""
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
        self.geometry("980x750")
        self.minsize(880, 600)
        self.configure(fg_color=COLOR_BG)

        # Apply Windows titlebar and taskbar application icons
        self._set_app_icon()

        self.log_queue = queue.Queue()
        self.is_running = False
        self.process = None

        self._build_ui()
        self.scan_staged_clips()
        self.refresh_raw_clips()
        self.refresh_exports()
        self.load_config_to_editor()
        self.after(100, self._process_log_queue)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # -------------------------------------------------------- Window Icon ---

    def _set_app_icon(self):
        """Sets the native Windows icon for the Titlebar, Taskbar, and Alt+Tab."""
        # 1. Primary: Load native Windows multi-res .ico from assets/public/appIcon.ico
        if APP_ICON_ICO.exists():
            try:
                self.iconbitmap(str(APP_ICON_ICO.resolve()))
                return
            except Exception:
                pass

        # 2. Fallback: Load PNG if .ico is unavailable
        png_candidates = [
            APP_ICON_PNG,
            PUBLIC_ASSETS_DIR / "logo.png",
            BRANDING_DIR / "app_logo.png",
        ]
        for p in png_candidates:
            if p.exists():
                try:
                    pil_img = Image.open(p)
                    self._taskbar_icon_ref = ImageTk.PhotoImage(pil_img)
                    self.wm_iconphoto(True, self._taskbar_icon_ref)
                    break
                except Exception:
                    pass

    # ---------------------------------------------------------------- UI ---

    def _build_ui(self):
        # Header (Persistent across all tabs)
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 4))

        brand_cluster = ctk.CTkFrame(header, fg_color="transparent")
        brand_cluster.pack(side="left")

        # In-App Visual Logo
        logo_path = None
        for candidate in [
            APP_ICON_PNG,
            APP_ICON_ICO,
            PUBLIC_ASSETS_DIR / "logo.png",
            BRANDING_DIR / "app_logo.png",
        ]:
            if candidate.exists():
                logo_path = candidate
                break

        if logo_path:
            try:
                pil_logo = Image.open(logo_path)
                self.header_logo = ctk.CTkImage(
                    light_image=pil_logo,
                    dark_image=pil_logo,
                    size=(40, 40)
                )
                logo_label = ctk.CTkLabel(brand_cluster, image=self.header_logo, text="")
                logo_label.pack(side="left", padx=(0, 12))
            except Exception:
                pass

        title_box = ctk.CTkFrame(brand_cluster, fg_color="transparent")
        title_box.pack(side="left")

        ctk.CTkLabel(
            title_box, text="FragForge", text_color=COLOR_ACCENT,
            font=("Segoe UI", 24, "bold"),
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_box, text="Automated Tactical Shorts Engine · VALORANT & CS2",
            text_color=COLOR_SUBTEXT, font=("Segoe UI", 12),
        ).pack(anchor="w")

        # Tabs View
        self.tabview = ctk.CTkTabview(
            self,
            fg_color=COLOR_BG,
            segmented_button_fg_color=COLOR_CARD,
            segmented_button_selected_color=COLOR_ACCENT,
            segmented_button_selected_hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_TEXT,
        )
        self.tabview.pack(fill="both", expand=True, padx=20, pady=(6, 16))

        self.tab_forge = self.tabview.add("⚡  Forge")
        self.tab_raw = self.tabview.add("📹  Raw Clips")
        self.tab_exports = self.tabview.add("📁  Exports")
        self.tab_config = self.tabview.add("⚙  Configuration")

        self._build_tab_forge()
        self._build_tab_raw()
        self._build_tab_exports()
        self._build_tab_config()

    # --------------------------------------------------------- Tab 1: Forge ---

    def _build_tab_forge(self):
        card = ctk.CTkFrame(self.tab_forge, fg_color=COLOR_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        card.pack(fill="x", pady=(8, 10))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=12)

        ctk.CTkLabel(
            inner, text="BATCH CONTROLS & STAGING", text_color=COLOR_SUBTEXT,
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 10))

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
        self.game_menu.grid(row=0, column=1, sticky="w", padx=(0, 20))

        self.auto_yes_var = tk.BooleanVar(value=True)
        ctk.CTkSwitch(
            row1, text="Auto-compile if over 54s limit", variable=self.auto_yes_var,
            text_color=COLOR_TEXT, font=("Segoe UI", 11),
            progress_color=COLOR_ACCENT, button_color=COLOR_TEXT,
        ).grid(row=0, column=2, sticky="w")

        ctk.CTkButton(
            row1, text="+ Stage Clip(s)", command=self.stage_new_clips,
            fg_color=COLOR_BG, hover_color=COLOR_BORDER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER, corner_radius=8, width=125,
        ).grid(row=0, column=3, padx=(0, 8))

        ctk.CTkButton(
            row1, text="🔄  Refresh", command=self.scan_staged_clips,
            fg_color=COLOR_BG, hover_color=COLOR_BORDER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER, corner_radius=8, width=95,
        ).grid(row=0, column=4)

        row2 = ctk.CTkFrame(inner, fg_color="transparent")
        row2.grid(row=2, column=0, columnspan=6, sticky="w", pady=(12, 0))

        ctk.CTkLabel(row2, text="raw_clips/", text_color=COLOR_SUBTEXT, font=("Segoe UI", 11)).pack(
            side="left", padx=(0, 10)
        )

        self.badge_valo = Badge(row2, "VALORANT", COLOR_VALO)
        self.badge_valo.pack(side="left", padx=(0, 8))

        self.badge_cs2 = Badge(row2, "CS2", COLOR_CS2)
        self.badge_cs2.pack(side="left", padx=(0, 12))

        ctk.CTkButton(
            row2, text="👁 View Staged", width=105, height=26,
            fg_color=COLOR_BG, hover_color=COLOR_BORDER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER, corner_radius=13, font=("Segoe UI", 11),
            command=lambda: self.tabview.set("📹  Raw Clips")
        ).pack(side="left")

        self.run_btn = ctk.CTkButton(
            self.tab_forge, text="▶    Forge Shorts Batch", command=self.start_pipeline,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, text_color="#ffffff",
            font=("Segoe UI", 14, "bold"), corner_radius=10, height=46,
        )
        self.run_btn.pack(fill="x", pady=(2, 10))

        console_card = ctk.CTkFrame(self.tab_forge, fg_color=COLOR_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        console_card.pack(fill="both", expand=True)

        ctk.CTkLabel(
            console_card, text="BUILD & OCR CONSOLE", text_color=COLOR_SUBTEXT,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=16, pady=(10, 6))

        self.log_text = ctk.CTkTextbox(
            console_card, fg_color=COLOR_CONSOLE_BG, text_color=COLOR_TEXT,
            font=("Consolas", 11), corner_radius=8, wrap="word",
            border_width=1, border_color=COLOR_BORDER,
        )
        self.log_text.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        self.log_text.tag_config("success", foreground=COLOR_SUCCESS)
        self.log_text.tag_config("error", foreground=COLOR_ERROR)
        self.log_text.tag_config("muted", foreground=COLOR_SUBTEXT)

    # ----------------------------------------------------- Tab 2: Raw Clips ---

    def _build_tab_raw(self):
        bar = ctk.CTkFrame(self.tab_raw, fg_color="transparent")
        bar.pack(fill="x", pady=(6, 10))

        ctk.CTkLabel(
            bar, text="STAGED RAW FOOTAGE", text_color=COLOR_SUBTEXT,
            font=("Segoe UI", 10, "bold")
        ).pack(side="left", padx=4)

        self.raw_filter_var = tk.StringVar(value="All")
        self.raw_filter = ctk.CTkSegmentedButton(
            bar, values=["All", "VALORANT", "CS2"],
            variable=self.raw_filter_var,
            command=lambda _: self.refresh_raw_clips(),
            selected_color=COLOR_ACCENT, selected_hover_color=COLOR_ACCENT_HOVER,
            corner_radius=8
        )
        self.raw_filter.pack(side="left", padx=16)

        ctk.CTkButton(
            bar, text="📂 Open Folder", command=self.open_raw_folder,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER, corner_radius=8, width=120,
        ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(
            bar, text="+ Stage Clip(s)", command=self.stage_new_clips,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER, corner_radius=8, width=120,
        ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(
            bar, text="🔄  Refresh", command=self.refresh_raw_clips,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER, corner_radius=8, width=95,
        ).pack(side="right")

        self.raw_scroll = ctk.CTkScrollableFrame(
            self.tab_raw, fg_color=COLOR_CARD, corner_radius=12,
            border_width=1, border_color=COLOR_BORDER
        )
        self.raw_scroll.pack(fill="both", expand=True, pady=(0, 6))

    def refresh_raw_clips(self):
        for widget in self.raw_scroll.winfo_children():
            widget.destroy()

        exts = {".mp4", ".mov", ".mkv"}
        items = []

        for fld in ["valo", "valorant"]:
            p = RAW_CLIPS_DIR / fld
            if p.exists() and p.is_dir():
                for f in p.iterdir():
                    if f.is_file() and f.suffix.lower() in exts and f not in [i[0] for i in items]:
                        items.append((f, "VALORANT", COLOR_VALO))

        for fld in ["cs2", "cs", "counter-strike"]:
            p = RAW_CLIPS_DIR / fld
            if p.exists() and p.is_dir():
                for f in p.iterdir():
                    if f.is_file() and f.suffix.lower() in exts and f not in [i[0] for i in items]:
                        items.append((f, "CS2", COLOR_CS2))

        filter_choice = self.raw_filter_var.get()
        if filter_choice != "All":
            items = [it for it in items if it[1] == filter_choice]

        items.sort(key=lambda it: it[0].stat().st_mtime, reverse=True)

        if not items:
            empty_lbl = ctk.CTkLabel(
                self.raw_scroll,
                text="No raw clips staged in raw_clips/ for this view.\nClick '+ Stage Clip(s)' to add gameplay files.",
                text_color=COLOR_SUBTEXT, font=("Segoe UI", 13), justify="center"
            )
            empty_lbl.pack(pady=60)
            return

        for path, game_tag, color in items:
            self._create_raw_clip_row(path, game_tag, color)

    def _create_raw_clip_row(self, path: Path, game_tag: str, tag_color: str):
        row = ctk.CTkFrame(self.raw_scroll, fg_color=COLOR_BG, corner_radius=8, border_width=1, border_color=COLOR_BORDER)
        row.pack(fill="x", padx=10, pady=4)

        stat = path.stat()
        size_mb = stat.st_size / (1024 * 1024)
        date_str = datetime.fromtimestamp(stat.st_mtime).strftime("%b %d, %Y · %I:%M %p")

        info_box = ctk.CTkFrame(row, fg_color="transparent")
        info_box.pack(side="left", padx=12, pady=8, fill="x", expand=True)

        title_line = ctk.CTkFrame(info_box, fg_color="transparent")
        title_line.pack(anchor="w")

        ctk.CTkLabel(
            title_line, text=f" {game_tag} ", text_color=tag_color,
            fg_color=COLOR_CARD, corner_radius=4, font=("Segoe UI", 10, "bold")
        ).pack(side="left", padx=(0, 8))

        ctk.CTkLabel(title_line, text=path.name, font=("Segoe UI", 12, "bold"), text_color=COLOR_TEXT).pack(side="left")

        ctk.CTkLabel(
            info_box,
            text=f"{size_mb:.1f} MB  |  {date_str}  |  raw_clips/{path.parent.name}/",
            font=("Segoe UI", 10), text_color=COLOR_SUBTEXT
        ).pack(anchor="w", pady=(2, 0))

        btn_box = ctk.CTkFrame(row, fg_color="transparent")
        btn_box.pack(side="right", padx=10, pady=8)

        ctk.CTkButton(
            btn_box, text="▶  Play", width=70, height=28,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, font=("Segoe UI", 11, "bold"),
            command=lambda p=path: os.startfile(str(p.resolve()))
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_box, text="📂 Reveal", width=70, height=28,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER, font=("Segoe UI", 11),
            command=lambda p=path: subprocess.Popen(f'explorer /select,"{p.resolve()}"')
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_box, text="✕", width=32, height=28,
            fg_color=COLOR_CARD, hover_color=COLOR_ERROR, text_color=COLOR_ERROR,
            command=lambda p=path: self._delete_raw_clip(p)
        ).pack(side="left", padx=4)

    def _delete_raw_clip(self, path: Path):
        if messagebox.askyesno("Delete Raw Clip", f"Are you sure you want to remove staged clip:\n\n{path.name}?"):
            try:
                path.unlink(missing_ok=True)
                self.scan_staged_clips()
                self.refresh_raw_clips()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to delete file: {e}")

    def open_raw_folder(self):
        choice = self.raw_filter_var.get()
        if choice == "VALORANT":
            target = RAW_CLIPS_DIR / "valo"
        elif choice == "CS2":
            target = RAW_CLIPS_DIR / "cs2"
        else:
            target = RAW_CLIPS_DIR

        target.mkdir(parents=True, exist_ok=True)
        os.startfile(target)

    # ------------------------------------------------------- Tab 3: Exports ---

    def _build_tab_exports(self):
        bar = ctk.CTkFrame(self.tab_exports, fg_color="transparent")
        bar.pack(fill="x", pady=(6, 10))

        ctk.CTkLabel(
            bar, text="COMPILED VIDEOS & CLIPS", text_color=COLOR_SUBTEXT,
            font=("Segoe UI", 10, "bold")
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            bar, text="📂 Open Folder in Explorer", command=self.open_output_folder,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER, corner_radius=8, width=170,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            bar, text="🔄  Refresh List", command=self.refresh_exports,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER, corner_radius=8, width=110,
        ).pack(side="right")

        self.exports_scroll = ctk.CTkScrollableFrame(
            self.tab_exports, fg_color=COLOR_CARD, corner_radius=12,
            border_width=1, border_color=COLOR_BORDER
        )
        self.exports_scroll.pack(fill="both", expand=True, pady=(0, 6))

    def refresh_exports(self):
        for widget in self.exports_scroll.winfo_children():
            widget.destroy()

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        TRIMMED_DIR.mkdir(parents=True, exist_ok=True)

        exts = {".mp4", ".mov", ".mkv"}
        final_shorts = [f for f in OUTPUT_DIR.iterdir() if f.is_file() and f.suffix.lower() in exts]
        trimmed_clips = [f for f in TRIMMED_DIR.iterdir() if f.is_file() and f.suffix.lower() in exts]

        final_shorts.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        trimmed_clips.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        if not final_shorts and not trimmed_clips:
            empty_lbl = ctk.CTkLabel(
                self.exports_scroll,
                text="No exported videos found yet.\nRun a batch from the '⚡ Forge' tab to generate Shorts.",
                text_color=COLOR_SUBTEXT, font=("Segoe UI", 13), justify="center"
            )
            empty_lbl.pack(pady=60)
            return

        if final_shorts:
            ctk.CTkLabel(
                self.exports_scroll, text="✦ FINAL COMPILED SHORTS (Ready to Upload)",
                text_color=COLOR_ACCENT, font=("Segoe UI", 11, "bold")
            ).pack(anchor="w", padx=12, pady=(12, 6))

            for video in final_shorts:
                self._create_video_row(video, is_master=True)

        if trimmed_clips:
            ctk.CTkLabel(
                self.exports_scroll, text="✦ INDIVIDUAL TRIMMED CLIPS",
                text_color=COLOR_SUBTEXT, font=("Segoe UI", 11, "bold")
            ).pack(anchor="w", padx=12, pady=(16, 6))

            for video in trimmed_clips:
                self._create_video_row(video, is_master=False)

    def _create_video_row(self, video_path: Path, is_master: bool):
        row = ctk.CTkFrame(self.exports_scroll, fg_color=COLOR_BG, corner_radius=8, border_width=1, border_color=COLOR_BORDER)
        row.pack(fill="x", padx=10, pady=4)

        stat = video_path.stat()
        size_mb = stat.st_size / (1024 * 1024)
        date_str = datetime.fromtimestamp(stat.st_mtime).strftime("%b %d, %Y · %I:%M %p")

        info_box = ctk.CTkFrame(row, fg_color="transparent")
        info_box.pack(side="left", padx=12, pady=8, fill="x", expand=True)

        name_color = COLOR_TEXT if not is_master else "#61afef"
        ctk.CTkLabel(info_box, text=video_path.name, font=("Segoe UI", 12, "bold"), text_color=name_color).pack(anchor="w")
        ctk.CTkLabel(info_box, text=f"{size_mb:.1f} MB  |  {date_str}", font=("Segoe UI", 10), text_color=COLOR_SUBTEXT).pack(anchor="w")

        btn_box = ctk.CTkFrame(row, fg_color="transparent")
        btn_box.pack(side="right", padx=10, pady=8)

        ctk.CTkButton(
            btn_box, text="▶  Play", width=70, height=28,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, font=("Segoe UI", 11, "bold"),
            command=lambda p=video_path: os.startfile(str(p.resolve()))
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_box, text="📂 Reveal", width=70, height=28,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER, font=("Segoe UI", 11),
            command=lambda p=video_path: subprocess.Popen(f'explorer /select,"{p.resolve()}"')
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_box, text="✕", width=32, height=28,
            fg_color=COLOR_CARD, hover_color=COLOR_ERROR, text_color=COLOR_ERROR,
            command=lambda p=video_path: self._delete_video(p)
        ).pack(side="left", padx=4)

    def _delete_video(self, path: Path):
        if messagebox.askyesno("Delete Video", f"Are you sure you want to delete:\n\n{path.name}?"):
            try:
                path.unlink(missing_ok=True)
                self.refresh_exports()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to delete file: {e}")

    # -------------------------------------------------------- Tab 4: Config ---

    def _build_tab_config(self):
        bar = ctk.CTkFrame(self.tab_config, fg_color="transparent")
        bar.pack(fill="x", pady=(6, 10))

        ctk.CTkLabel(
            bar, text="PROJECT CONFIGURATION (config.json)", text_color=COLOR_SUBTEXT,
            font=("Segoe UI", 10, "bold")
        ).pack(side="left", padx=4)

        self.config_status_lbl = ctk.CTkLabel(bar, text="", font=("Segoe UI", 11))
        self.config_status_lbl.pack(side="left", padx=16)

        ctk.CTkButton(
            bar, text="💾  Save Changes", command=self.save_config_from_editor,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, text_color="#ffffff",
            font=("Segoe UI", 11, "bold"), corner_radius=8, width=130,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            bar, text="🔄  Reload", command=self.load_config_to_editor,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER, text_color=COLOR_TEXT,
            border_width=1, border_color=COLOR_BORDER, corner_radius=8, width=95,
        ).pack(side="right")

        editor_card = ctk.CTkFrame(self.tab_config, fg_color=COLOR_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        editor_card.pack(fill="both", expand=True, pady=(0, 6))

        self.config_editor = ctk.CTkTextbox(
            editor_card, fg_color=COLOR_CONSOLE_BG, text_color=COLOR_TEXT,
            font=("Consolas", 12), corner_radius=8, wrap="none",
            border_width=1, border_color=COLOR_BORDER,
        )
        self.config_editor.pack(fill="both", expand=True, padx=14, pady=14)

    def load_config_to_editor(self):
        if not CONFIG_PATH.exists():
            self.config_editor.insert("1.0", f"// config.json not found at {CONFIG_PATH}")
            return

        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                content = f.read()
            self.config_editor.delete("1.0", "end")
            self.config_editor.insert("1.0", content)
            self._set_config_status("Configuration loaded successfully.", COLOR_SUCCESS)
        except Exception as e:
            self._set_config_status(f"Error loading config: {e}", COLOR_ERROR)

    def save_config_from_editor(self):
        content = self.config_editor.get("1.0", "end").strip()
        try:
            parsed = json.loads(content)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(parsed, f, indent=2)

            self._set_config_status("✓ Saved config.json successfully!", COLOR_SUCCESS)
        except json.JSONDecodeError as err:
            self._set_config_status(f"Syntax Error: {err.msg} (Line {err.lineno})", COLOR_ERROR)
            messagebox.showerror("Invalid JSON", f"Syntax Error on line {err.lineno}:\n{err.msg}\n\nConfig was not saved.")
        except Exception as e:
            self._set_config_status(f"Save error: {e}", COLOR_ERROR)

    def _set_config_status(self, msg: str, color: str):
        self.config_status_lbl.configure(text=msg, text_color=color)

    # ---------------------------------------------------------- Logging ---

    def _append_log(self, line: str):
        lowered = line.lower()
        if "failed" in lowered or "error" in lowered:
            tag = "error"
        elif "done" in lowered or "complete" in lowered or "frag detected" in lowered or "peak at" in lowered:
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
        self.refresh_raw_clips()

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

        sub_env = os.environ.copy()
        sub_env["PYTHONIOENCODING"] = "utf-8"

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=sub_env,
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
                    self.refresh_raw_clips()
                    self.refresh_exports()
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