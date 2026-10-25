"""
AIM Suite — single-file build
GUI launcher with AIM TRAIN and UPDATE
AIM TRAIN mode uses fullscreen Tkinter and raw mouse input
UPDATE runs update.bat, which relaunches aim.exe when done
Compile: pyinstaller --onefile --name "aim" aim.py
"""
import os
import sys
import json
import time
import math
import random
import ctypes
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
import subprocess

# ═══════════════════════════════════════════════════════════
#  GLOBALS
# ═══════════════════════════════════════════════════════════

VERSION = "16.1"
CONFIG_FILE = Path.home() / ".aimsuite_config.json"
LOG_FILE = Path.home() / ".aimsuite_log.txt"

VALO_DPI = 1600
VALO_SENS = 0.085
VALO_YAW = 0.07
VALO_FOV_H = 103.0  # Valorant default horizontal FOV

MODE_AIMTRAIN = "aimtrain"
MODE_FOLLOW = "follow"
MODE_PLAY = "play"
MODE_SETTINGS = "settings"

BG = "#0a0a14"
BG2 = "#0f0f1a"
FG = "#e0e0f0"
ACCENT_PINK = "#ff00aa"
ACCENT_CYAN = "#00ffcc"
ACCENT_RED = "#ff0055"
ACCENT_ORANGE = "#ffaa00"
ACCENT_GREEN = "#00ff88"
ACCENT_PURPLE = "#aa66ff"
GREY = "#666688"
DARKGREY = "#222233"

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent

# ═══════════════════════════════════════════════════════════
#  SHARED UTILITIES
# ═══════════════════════════════════════════════════════════

def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{level}] {msg}\n")
    except Exception:
        pass

def load_cfg():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "hwid": "".join(random.choices("0123456789ABCDEF", k=16)),
        "features_used": {},
        "best_reaction_ms": None,
        "best_follow": None,
        "aim_scores": [],
        "total_points": 0,
        "high_scores": [],
        "precision_scores": [],
        "total_launches": 0,
        "valo_dpi": VALO_DPI,
        "valo_sens": VALO_SENS,
    }

def save_cfg(cfg):
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass

def get_valo_settings(cfg=None):
    cfg = cfg or {}
    dpi = float(cfg.get("valo_dpi") or VALO_DPI)
    sens = float(cfg.get("valo_sens") or VALO_SENS)
    dpi = max(100.0, min(32000.0, dpi))
    sens = max(0.001, min(10.0, sens))
    return dpi, sens

def valo_cm_per_360(dpi=None, sens=None):
    dpi = VALO_DPI if dpi is None else dpi
    sens = VALO_SENS if sens is None else sens
    return (360.0 / (VALO_YAW * sens)) / dpi * 2.54

def valo_deg_per_count(sens):
    return VALO_YAW * sens


# ═══════════════════════════════════════════════════════════
#  VALORANT RAW MOUSE (same yaw as in-game)
# ═══════════════════════════════════════════════════════════

WM_INPUT = 0x00FF
RID_INPUT = 0x10000003
RIM_TYPEMOUSE = 0
RIDEV_REMOVE = 0x00000001
RIDEV_INPUTSINK = 0x00000100
RI_MOUSE_LEFT_BUTTON_DOWN = 0x0001
GWLP_WNDPROC = -4
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)

class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]

class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]

class _RAWMOUSE_BUTTONS(ctypes.Structure):
    _fields_ = [
        ("usButtonFlags", wintypes.USHORT),
        ("usButtonData", wintypes.USHORT),
    ]

class _RAWMOUSE_UNION(ctypes.Union):
    _fields_ = [
        ("ulButtons", wintypes.ULONG),
        ("buttons", _RAWMOUSE_BUTTONS),
    ]

class RAWMOUSE(ctypes.Structure):
    _fields_ = [
        ("usFlags", wintypes.USHORT),
        ("u", _RAWMOUSE_UNION),
        ("ulRawButtons", wintypes.ULONG),
        ("lLastX", wintypes.LONG),
        ("lLastY", wintypes.LONG),
        ("ulExtraInformation", wintypes.ULONG),
    ]

class RAWINPUT(ctypes.Structure):
    _fields_ = [
        ("header", RAWINPUTHEADER),
        ("mouse", RAWMOUSE),
    ]

class MSG(ctypes.Structure):
    _fields_ = [
        ("hWnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]

class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HANDLE),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]

HWND_MESSAGE = wintypes.HWND(-3)
PM_REMOVE = 0x0001


class WinMouse:
    """Clip the OS cursor inside the play area and read mouse deltas.

    Prefers raw HID counts (Valorant). If WM_INPUT never arrives, falls
    back to GetCursorPos after recentering so the reticle always moves
    and the pointer cannot leave the window.
    """

    def __init__(self):
        self._user32 = ctypes.windll.user32
        self._active = False
        self._canvas = None
        self._hwnd = None
        self._proc = None
        self._class_name = None
        self._pending = [0, 0]
        self._clicks = 0
        self._got_raw = False
        self._cx = 0
        self._cy = 0
        self._user32.GetRawInputData.argtypes = [
            wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
            ctypes.POINTER(wintypes.UINT), wintypes.UINT,
        ]
        self._user32.GetRawInputData.restype = wintypes.UINT
        self._user32.PeekMessageW.argtypes = [
            ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT,
            wintypes.UINT, wintypes.UINT,
        ]
        self._user32.PeekMessageW.restype = wintypes.BOOL
        self._user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        self._user32.RegisterClassW.restype = wintypes.ATOM
        self._user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
            wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE,
            ctypes.c_void_p,
        ]
        self._user32.CreateWindowExW.restype = wintypes.HWND
        self._user32.RegisterRawInputDevices.argtypes = [
            ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT,
        ]
        self._user32.RegisterRawInputDevices.restype = wintypes.BOOL
        self._user32.DefWindowProcW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        ]
        self._user32.DefWindowProcW.restype = LRESULT
        self._user32.DestroyWindow.argtypes = [wintypes.HWND]
        self._user32.DestroyWindow.restype = wintypes.BOOL
        self._user32.UnregisterClassW.argtypes = [
            wintypes.LPCWSTR, wintypes.HINSTANCE,
        ]
        self._user32.UnregisterClassW.restype = wintypes.BOOL
        self._user32.ClipCursor.argtypes = [ctypes.c_void_p]
        self._user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self._user32.SetCursorPos.restype = wintypes.BOOL
        self._user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self._user32.GetCursorPos.restype = wintypes.BOOL
        self._user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
        self._user32.TranslateMessage.restype = wintypes.BOOL
        self._user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
        self._user32.DispatchMessageW.restype = LRESULT
        self._kernel32 = ctypes.windll.kernel32
        self._kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self._kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE

    def start(self, canvas):
        self.stop()
        self._canvas = canvas
        self._active = True
        self._pending = [0, 0]
        self._clicks = 0
        self._got_raw = False
        canvas.config(cursor="none")
        self._create_raw_window()
        self._refresh_lock()
        return True

    def pump(self):
        if not self._active:
            return 0, 0, False
        if self._hwnd:
            msg = MSG()
            while self._user32.PeekMessageW(
                ctypes.byref(msg), self._hwnd, 0, 0, PM_REMOVE
            ):
                self._user32.TranslateMessage(ctypes.byref(msg))
                self._user32.DispatchMessageW(ctypes.byref(msg))
        dx, dy = self._pending[0], self._pending[1]
        self._pending = [0, 0]
        clicked = self._clicks > 0
        self._clicks = 0
        if not self._got_raw or (dx == 0 and dy == 0):
            pdx, pdy = self._poll_cursor()
            if not self._got_raw:
                dx, dy = pdx, pdy
        else:
            self._center()
        self._refresh_lock()
        return dx, dy, clicked

    def stop(self):
        self._active = False
        try:
            self._user32.ClipCursor(None)
        except Exception:
            pass
        if self._canvas is not None:
            try:
                self._canvas.config(cursor="")
            except Exception:
                pass
        self._destroy_raw_window()
        self._canvas = None

    def _refresh_lock(self):
        c = self._canvas
        if c is None:
            return
        try:
            c.update_idletasks()
            x, y = c.winfo_rootx(), c.winfo_rooty()
            w, h = max(c.winfo_width(), 2), max(c.winfo_height(), 2)
        except Exception:
            return
        rect = wintypes.RECT(x, y, x + w, y + h)
        self._user32.ClipCursor(ctypes.byref(rect))
        self._cx = x + w // 2
        self._cy = y + h // 2

    def _center(self):
        self._user32.SetCursorPos(int(self._cx), int(self._cy))

    def _poll_cursor(self):
        pt = wintypes.POINT()
        self._user32.GetCursorPos(ctypes.byref(pt))
        dx, dy = pt.x - self._cx, pt.y - self._cy
        self._center()
        return dx, dy

    def _create_raw_window(self):
        try:
            hinst = self._kernel32.GetModuleHandleW(None)
            self._class_name = f"AimRawMouse{id(self)}"

            def _wndproc(hwnd, msg, wparam, lparam):
                if msg == WM_INPUT and self._active:
                    self._on_raw(lparam)
                    return 0
                return self._user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            self._proc = WNDPROC(_wndproc)
            wc = WNDCLASSW()
            wc.style = 0
            wc.lpfnWndProc = self._proc
            wc.hInstance = hinst
            wc.lpszClassName = self._class_name
            atom = self._user32.RegisterClassW(ctypes.byref(wc))
            if not atom:
                return
            hwnd = self._user32.CreateWindowExW(
                0, self._class_name, "", 0,
                0, 0, 0, 0, HWND_MESSAGE, None, hinst, None,
            )
            if not hwnd:
                return
            self._hwnd = wintypes.HWND(hwnd)
            rid = RAWINPUTDEVICE()
            rid.usUsagePage = 0x01
            rid.usUsage = 0x02
            rid.dwFlags = RIDEV_INPUTSINK
            rid.hwndTarget = self._hwnd
            self._user32.RegisterRawInputDevices(
                ctypes.byref(rid), 1, ctypes.sizeof(RAWINPUTDEVICE)
            )
        except Exception:
            self._hwnd = None

    def _destroy_raw_window(self):
        try:
            rid = RAWINPUTDEVICE()
            rid.usUsagePage = 0x01
            rid.usUsage = 0x02
            rid.dwFlags = RIDEV_REMOVE
            rid.hwndTarget = None
            self._user32.RegisterRawInputDevices(
                ctypes.byref(rid), 1, ctypes.sizeof(RAWINPUTDEVICE)
            )
        except Exception:
            pass
        if self._hwnd:
            try:
                self._user32.DestroyWindow(self._hwnd)
            except Exception:
                pass
        if self._class_name:
            try:
                hinst = self._kernel32.GetModuleHandleW(None)
                self._user32.UnregisterClassW(self._class_name, hinst)
            except Exception:
                pass
        self._hwnd = None
        self._proc = None
        self._class_name = None

    def _on_raw(self, lparam):
        size = wintypes.UINT(0)
        self._user32.GetRawInputData(
            wintypes.HANDLE(lparam), RID_INPUT, None,
            ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER)
        )
        if size.value == 0:
            return
        buf = ctypes.create_string_buffer(size.value)
        got = self._user32.GetRawInputData(
            wintypes.HANDLE(lparam), RID_INPUT, buf,
            ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER)
        )
        if got == 0 or got == 0xFFFFFFFF:
            return
        raw = ctypes.cast(buf, ctypes.POINTER(RAWINPUT)).contents
        if raw.header.dwType != RIM_TYPEMOUSE:
            return
        self._got_raw = True
        self._pending[0] += raw.mouse.lLastX
        self._pending[1] += raw.mouse.lLastY
        flags = raw.mouse.u.buttons.usButtonFlags
        if flags & RI_MOUSE_LEFT_BUTTON_DOWN:
            self._clicks += 1

# ═══════════════════════════════════════════════════════════
#  MODE: AIM TRAIN — FULLSCREEN + POINTS SYSTEM
# ═══════════════════════════════════════════════════════════

def run_aimtrain_mode(start_mode=None):
    import tkinter as tk

    cfg = load_cfg()
    root = tk.Tk()
    root.title(f"AIM TRAINER v{VERSION}")
    root.configure(bg=BG)

    try:
        root.attributes("-fullscreen", True)
    except Exception:
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{sw}x{sh}+0+0")

    grab_box = {"m": None}

    def release_mouse():
        m = grab_box.get("m")
        if m is not None:
            m.stop()
            grab_box["m"] = None

    root.bind("<Escape>", lambda e: (release_mouse(), root.destroy()))
    root.protocol("WM_DELETE_WINDOW", lambda: (release_mouse(), root.destroy()))

    accent = random.choice([ACCENT_CYAN, ACCENT_PINK, ACCENT_GREEN, ACCENT_ORANGE])

    container = tk.Frame(root, bg=BG)
    container.pack(fill="both", expand=True)

    # HEADER
    header = tk.Frame(container, bg=BG)
    header.pack(fill="x", pady=(10, 2))
    tk.Label(header, text="  AIM  TRAINER  ",
             font=("Consolas", 22, "bold"),
             fg=accent, bg=BG).pack()
    dpi0, sens0 = get_valo_settings(cfg)
    header_sub = tk.Label(
        header,
        text=f"v{VERSION} · VALORANT 1:1 · {dpi0:.0f} DPI / {sens0} · FOV {VALO_FOV_H:.0f} · ESC to quit",
        font=("Consolas", 9), fg=GREY, bg=BG,
    )
    header_sub.pack(pady=(2, 0))

    def refresh_header():
        d, s = get_valo_settings(cfg)
        header_sub.config(
            text=f"v{VERSION} · VALORANT 1:1 · {d:.0f} DPI / {s} · FOV {VALO_FOV_H:.0f} · ESC to quit"
        )

    # BUTTON ROW
    btn_row = tk.Frame(container, bg=BG)
    btn_row.pack(pady=10)

    class RoundBtn(tk.Canvas):
        def __init__(self, parent, text, command, radius=70,
                     fg_color=ACCENT_CYAN, hover_color=ACCENT_PINK):
            size = radius * 2 + 10
            super().__init__(parent, width=size, height=size,
                             bg=BG, highlightthickness=0)
            self.command = command
            self.color = fg_color
            self.hover_color = hover_color
            cx = cy = size // 2
            r = radius
            self.circle = self.create_oval(cx-r, cy-r, cx+r, cy+r,
                                           outline=fg_color, width=3, fill=BG2)
            self.inner = self.create_oval(cx-r+8, cy-r+8, cx+r-8, cy+r-8,
                                           outline="", fill="")
            self.label = self.create_text(cx, cy, text=text, fill=fg_color,
                                           font=("Consolas", 11, "bold"))
            self.tag_bind("all", "<Enter>", self._enter)
            self.tag_bind("all", "<Leave>", self._leave)
            self.tag_bind("all", "<Button-1>", lambda e: self.command())

        def _enter(self, _):
            self.itemconfig(self.circle, outline=self.hover_color, width=4)
            self.itemconfig(self.label, fill=self.hover_color)
            self.itemconfig(self.inner, fill=DARKGREY)

        def _leave(self, _):
            self.itemconfig(self.circle, outline=self.color, width=3)
            self.itemconfig(self.label, fill=self.color)
            self.itemconfig(self.inner, fill="")

    # CONTENT AREA
    content = tk.Frame(container, bg=BG)
    content.pack(fill="both", expand=True, padx=20, pady=10)

    def clear_content():
        for w in content.winfo_children():
            w.destroy()

    def clear_buttons():
        for w in btn_row.winfo_children():
            w.destroy()

    def go_back():
        release_mouse()
        clear_content()
        clear_buttons()
        show_home()

    def for_destroy(fn):
        release_mouse()
        clear_content()
        fn()

    # HOME
    def show_home():
        clear_buttons()
        RoundBtn(btn_row, "REACTION TIME", lambda: for_destroy(reaction_screen),
                 radius=58, fg_color=ACCENT_ORANGE).pack(side="top", pady=4)
        RoundBtn(btn_row, "AIM\nTRAIN", lambda: for_destroy(aimtrain_screen),
                 radius=58, fg_color=ACCENT_CYAN).pack(side="top", pady=4)
        RoundBtn(btn_row, "PRECISION", lambda: for_destroy(lambda: aimtrain_screen(True)),
             radius=58, fg_color=ACCENT_RED).pack(side="top", pady=4)
        RoundBtn(btn_row, "FOLLOW", lambda: for_destroy(follow_screen),
                 radius=58, fg_color=ACCENT_PINK).pack(side="top", pady=4)
        RoundBtn(btn_row, "SENS", lambda: for_destroy(sens_screen),
                 radius=58, fg_color=ACCENT_GREEN).pack(side="top", pady=4)
        RoundBtn(btn_row, "STATS", lambda: for_destroy(stats_screen),
                 radius=58, fg_color=ACCENT_PURPLE).pack(side="top", pady=4)

        # Show total points + best score
        total = cfg.get("total_points", 0)
        highs = cfg.get("high_scores", [])
        best = max(highs) if highs else 0

        info = tk.Frame(content, bg=BG2, highlightthickness=1,
                        highlightbackground=accent)
        info.pack(pady=20, ipadx=40, ipady=15)

        tk.Label(info, text=f"TOTAL POINTS: {total:,}",
                 font=("Consolas", 18, "bold"),
                 fg=ACCENT_ORANGE, bg=BG2).pack(pady=3)
        tk.Label(info, text=f"Best game: {best:,} pts",
                 font=("Consolas", 12),
                 fg=FG, bg=BG2).pack(pady=3)

        best_rt = cfg.get("best_reaction_ms")
        if best_rt:
            tk.Label(info, text=f"Best reaction: {best_rt:.0f} ms",
                     font=("Consolas", 11),
                     fg=ACCENT_CYAN, bg=BG2).pack(pady=3)
        best_fl = cfg.get("best_follow")
        if best_fl:
            tk.Label(info, text=f"Best follow: {best_fl:.0f}% on target",
                     font=("Consolas", 11),
                     fg=ACCENT_PINK, bg=BG2).pack(pady=3)

        tk.Label(content, text="Mouse = Valorant yaw · left click = shoot · ESC to quit",
                 font=("Consolas", 10), fg=GREY, bg=BG).pack(side="bottom", pady=10)

    # SENS
    def sens_screen():
        clear_buttons()
        dpi, sens = get_valo_settings(cfg)
        tk.Label(content, text="VALORANT SENS",
                 font=("Consolas", 20, "bold"), fg=accent, bg=BG).pack(pady=10)
        tk.Label(content, text="Same formula as in-game: degrees = counts × 0.07 × sens  ·  FOV 103",
                 font=("Consolas", 10), fg=GREY, bg=BG).pack()

        box = tk.Frame(content, bg=BG2, highlightthickness=1,
                       highlightbackground=accent)
        box.pack(pady=16, ipadx=30, ipady=16)

        form = tk.Frame(box, bg=BG2)
        form.pack(pady=6)
        tk.Label(form, text="Mouse DPI", font=("Consolas", 12),
                 fg=GREY, bg=BG2, width=16, anchor="w").grid(row=0, column=0, pady=4)
        dpi_var = tk.StringVar(value=str(int(dpi) if dpi == int(dpi) else dpi))
        tk.Entry(form, textvariable=dpi_var, font=("Consolas", 12), width=12,
                 bg=DARKGREY, fg=FG, insertbackground=FG, relief="flat").grid(row=0, column=1)
        tk.Label(form, text="In-game sens", font=("Consolas", 12),
                 fg=GREY, bg=BG2, width=16, anchor="w").grid(row=1, column=0, pady=4)
        sens_var = tk.StringVar(value=str(sens))
        tk.Entry(form, textvariable=sens_var, font=("Consolas", 12), width=12,
                 bg=DARKGREY, fg=FG, insertbackground=FG, relief="flat").grid(row=1, column=1)

        live = tk.Frame(box, bg=BG2)
        live.pack(pady=10)
        live_labels = {}
        for i, k in enumerate(("eDPI", "cm / 360", "deg / count", "FOV")):
            r = tk.Frame(live, bg=BG2)
            r.pack(fill="x", pady=2)
            tk.Label(r, text=f"{k:<14}", font=("Consolas", 12),
                     fg=GREY, bg=BG2, anchor="w", width=16).pack(side="left")
            live_labels[k] = tk.Label(r, text="—", font=("Consolas", 12, "bold"),
                                      fg=FG, bg=BG2, anchor="w")
            live_labels[k].pack(side="left")

        hint = tk.Label(content, text="", font=("Consolas", 10), fg=GREY, bg=BG)
        hint.pack(pady=4)

        def parse_vals():
            try:
                d = float(dpi_var.get().replace(",", "."))
                s = float(sens_var.get().replace(",", "."))
                return get_valo_settings({"valo_dpi": d, "valo_sens": s})
            except ValueError:
                return None

        def refresh_live(*_):
            vals = parse_vals()
            if not vals:
                hint.config(text="Enter valid numbers", fg=ACCENT_RED)
                return
            d, s = vals
            live_labels["eDPI"].config(text=f"{d * s:.1f}")
            live_labels["cm / 360"].config(text=f"{valo_cm_per_360(d, s):.2f} cm")
            live_labels["deg / count"].config(text=f"{valo_deg_per_count(s):.5f}°")
            live_labels["FOV"].config(text=f"{VALO_FOV_H:.0f}° H")
            hint.config(
                text="Raw mouse: matches Valorant even if Windows pointer speed is not 6/11",
                fg=GREY,
            )

        dpi_var.trace_add("write", refresh_live)
        sens_var.trace_add("write", refresh_live)
        refresh_live()

        def save_sens():
            vals = parse_vals()
            if not vals:
                hint.config(text="Could not save — check DPI / sens", fg=ACCENT_RED)
                return
            d, s = vals
            cfg["valo_dpi"] = d
            cfg["valo_sens"] = s
            save_cfg(cfg)
            refresh_header()
            hint.config(text=f"Saved · {d:.0f} DPI / {s}  — used in AIM TRAIN and FOLLOW",
                        fg=ACCENT_GREEN)

        btns = tk.Frame(content, bg=BG)
        btns.pack(pady=16)
        tk.Button(btns, text="SAVE", command=save_sens,
                  font=("Consolas", 12, "bold"), fg=ACCENT_GREEN, bg=BG2,
                  activebackground=DARKGREY, relief="flat",
                  padx=30, pady=10).pack(side="left", padx=10)
        tk.Button(btns, text="◂ BACK", command=go_back,
                  font=("Consolas", 12, "bold"), fg=accent, bg=BG2,
                  activebackground=DARKGREY, relief="flat",
                  padx=30, pady=10).pack(side="left", padx=10)

    # STATS — full history
    def stats_screen():
        clear_buttons()
        tk.Label(content, text="STATISTICS",
                 font=("Consolas", 20, "bold"), fg=ACCENT_PURPLE, bg=BG).pack(pady=10)

        box = tk.Frame(content, bg=BG2, highlightthickness=1,
                       highlightbackground=ACCENT_PURPLE)
        box.pack(pady=15, ipadx=40, ipady=15)

        total = cfg.get("total_points", 0)
        highs = cfg.get("high_scores", [])
        best = max(highs) if highs else 0
        avg_best = (sum(highs) / len(highs)) if highs else 0
        games = len(highs)

        rows = [
            ("Total points", f"{total:,}"),
            ("Games played", str(games)),
            ("Best game", f"{best:,} pts"),
            ("Best precision", f"{max(cfg.get('precision_scores', []), default=0):,} pts"),
            ("Avg of best", f"{avg_best:.0f} pts"),
            ("Best reaction", f"{cfg.get('best_reaction_ms') or 0:.0f} ms"),
            ("Best follow", f"{cfg.get('best_follow') or 0:.0f}%"),
        ]
        for k, v in rows:
            r = tk.Frame(box, bg=BG2)
            r.pack(fill="x", pady=3)
            tk.Label(r, text=f"{k:<15}", font=("Consolas", 13),
                     fg=GREY, bg=BG2, anchor="w", width=16).pack(side="left")
            tk.Label(r, text=v, font=("Consolas", 13, "bold"),
                     fg=FG, bg=BG2, anchor="w").pack(side="left")

        # Top 5
        if highs:
            tk.Label(content, text="TOP 5 GAMES",
                     font=("Consolas", 14, "bold"),
                     fg=ACCENT_ORANGE, bg=BG).pack(pady=(20, 5))
            top_box = tk.Frame(content, bg=BG2, highlightthickness=1,
                               highlightbackground=ACCENT_ORANGE)
            top_box.pack(pady=5, ipadx=30, ipady=10)
            top5 = sorted(highs, reverse=True)[:5]
            for i, sc in enumerate(top5, 1):
                r = tk.Frame(top_box, bg=BG2)
                r.pack(fill="x", pady=2)
                color = ACCENT_GREEN if i == 1 else FG
                tk.Label(r, text=f"#{i}", font=("Consolas", 12, "bold"),
                         fg=GREY, bg=BG2, width=4).pack(side="left")
                tk.Label(r, text=f"{sc:,} pts", font=("Consolas", 12, "bold"),
                         fg=color, bg=BG2).pack(side="left")

        # Reset button
        def reset_all():
            cfg["total_points"] = 0
            cfg["high_scores"] = []
            cfg["precision_scores"] = []
            cfg["aim_scores"] = []
            save_cfg(cfg)
            clear_content()
            stats_screen()

        tk.Button(content, text="◂ BACK", command=go_back,
                  font=("Consolas", 12, "bold"), fg=accent, bg=BG2,
                  activebackground=DARKGREY, relief="flat",
                  padx=30, pady=10).pack(side="left", padx=15, pady=20)
        tk.Button(content, text="RESET STATS", command=reset_all,
                  font=("Consolas", 12, "bold"), fg=ACCENT_RED, bg=BG2,
                  activebackground=DARKGREY, relief="flat",
                  padx=30, pady=10).pack(side="left", padx=15, pady=20)

    # REACTION
    def reaction_screen():
        clear_buttons()
        total_rounds = 8
        state = {
            "round": 0,
            "times": [],
            "start": None,
            "phase": "idle",  # idle | wait | go | freeze
            "token": 0,
            "early": 0,
        }

        tk.Label(content, text="REACTION TIME",
                 font=("Consolas", 20, "bold"), fg=ACCENT_ORANGE, bg=BG).pack(pady=(6, 2))
        tk.Label(content, text="Click ANYWHERE when the screen turns GREEN  ·  too early = retry that round",
                 font=("Consolas", 11), fg=GREY, bg=BG).pack(pady=(0, 8))

        hud = tk.Frame(content, bg=BG)
        hud.pack(fill="x", padx=20)
        round_lbl = tk.Label(hud, text=f"Round 0 / {total_rounds}",
                             font=("Consolas", 14, "bold"), fg=FG, bg=BG)
        round_lbl.pack(side="left")
        live_lbl = tk.Label(hud, text="", font=("Consolas", 12), fg=ACCENT_CYAN, bg=BG)
        live_lbl.pack(side="right")

        stage = tk.Frame(content, bg=BG2, highlightthickness=2,
                         highlightbackground=ACCENT_ORANGE, cursor="crosshair")
        stage.pack(fill="both", expand=True, padx=24, pady=10)
        msg = tk.Label(stage, text="GET READY", font=("Consolas", 42, "bold"),
                       fg=FG, bg=BG2)
        msg.pack(expand=True)
        sub = tk.Label(stage, text="click when GREEN", font=("Consolas", 14),
                       fg=GREY, bg=BG2)
        sub.pack(pady=(0, 30))

        hist = tk.Label(content, text="", font=("Consolas", 11), fg=GREY, bg=BG)
        hist.pack(pady=4)

        def set_stage(bg, title, subtitle, title_fg=FG):
            stage.config(bg=bg, highlightbackground=bg if bg != BG2 else ACCENT_ORANGE)
            msg.config(text=title, bg=bg, fg=title_fg)
            sub.config(text=subtitle, bg=bg)

        def times_line():
            if not state["times"]:
                return ""
            bits = "  ".join(f"{t:.0f}" for t in state["times"])
            return f"ms: {bits}"

        def schedule_wait():
            state["phase"] = "wait"
            state["start"] = None
            state["token"] += 1
            token = state["token"]
            set_stage(BG2, "WAIT", "don't click yet…")
            delay = int(random.uniform(1400, 4200))
            root.after(delay, lambda: arm_go(token))

        def next_round():
            if state["round"] >= total_rounds:
                finish_reaction()
                return
            state["round"] += 1
            round_lbl.config(text=f"Round {state['round']} / {total_rounds}")
            live_lbl.config(text=f"early: {state['early']}")
            hist.config(text=times_line())
            schedule_wait()

        def arm_go(token):
            if token != state["token"] or state["phase"] != "wait":
                return
            state["phase"] = "go"
            state["start"] = time.perf_counter()
            set_stage(ACCENT_GREEN, "GO", "click now", title_fg="#001108")

        def on_click(_event=None):
            phase = state["phase"]
            if phase == "freeze" or phase == "idle":
                return
            if phase == "wait":
                state["early"] += 1
                state["token"] += 1
                state["phase"] = "freeze"
                live_lbl.config(text=f"early: {state['early']}")
                set_stage(ACCENT_RED, "TOO EARLY", "same round again", title_fg="#fff")
                root.after(750, schedule_wait)
                return
            if phase != "go" or state["start"] is None:
                return
            elapsed_ms = (time.perf_counter() - state["start"]) * 1000
            state["times"].append(elapsed_ms)
            state["phase"] = "freeze"
            state["token"] += 1
            color = (ACCENT_GREEN if elapsed_ms < 180
                     else ACCENT_CYAN if elapsed_ms < 230
                     else ACCENT_ORANGE if elapsed_ms < 300
                     else ACCENT_RED)
            set_stage(color, f"{elapsed_ms:.0f} ms", f"round {state['round']}", title_fg="#000")
            hist.config(text=times_line())
            root.after(620, next_round)

        def finish_reaction():
            root.unbind("<Button-1>")
            times = state["times"]
            if not times:
                go_back()
                return
            avg = sum(times) / len(times)
            best = min(times)
            worst = max(times)
            mean = avg
            var = sum((t - mean) ** 2 for t in times) / len(times)
            std = math.sqrt(var)
            clear_content()

            tk.Label(content, text="REACTION RESULTS",
                     font=("Consolas", 22, "bold"), fg=ACCENT_ORANGE, bg=BG).pack(pady=12)
            box = tk.Frame(content, bg=BG2, highlightthickness=1,
                           highlightbackground=ACCENT_ORANGE)
            box.pack(pady=12, ipadx=40, ipady=16)
            rows = [
                ("Average", f"{avg:.0f} ms"),
                ("Best", f"{best:.0f} ms"),
                ("Worst", f"{worst:.0f} ms"),
                ("Consistency", f"±{std:.0f} ms"),
                ("False starts", str(state["early"])),
            ]
            for k, v in rows:
                r = tk.Frame(box, bg=BG2)
                r.pack(fill="x", pady=4)
                tk.Label(r, text=f"{k:<14}", font=("Consolas", 14),
                         fg=GREY, bg=BG2, anchor="w", width=14).pack(side="left")
                tk.Label(r, text=v, font=("Consolas", 14, "bold"),
                         fg=FG, bg=BG2).pack(side="left")

            tk.Label(content, text="  ".join(f"{t:.0f}" for t in times) + " ms",
                     font=("Consolas", 12), fg=ACCENT_CYAN, bg=BG).pack(pady=8)

            if avg < 180:
                rating, color = "INSANE", ACCENT_GREEN
            elif avg < 220:
                rating, color = "FAST", ACCENT_CYAN
            elif avg < 270:
                rating, color = "SOLID", ACCENT_ORANGE
            else:
                rating, color = "KEEP GOING", ACCENT_RED
            tk.Label(content, text=f"Rating: {rating}",
                     font=("Consolas", 16, "bold"), fg=color, bg=BG).pack(pady=4)

            prev = cfg.get("best_reaction_ms")
            if prev is None or best < prev:
                cfg["best_reaction_ms"] = best
                tk.Label(content, text="★ NEW PERSONAL BEST ★",
                         font=("Consolas", 16, "bold"),
                         fg=ACCENT_GREEN, bg=BG).pack(pady=8)

            cfg["features_used"]["reaction"] = cfg["features_used"].get("reaction", 0) + 1
            save_cfg(cfg)

            btns = tk.Frame(content, bg=BG)
            btns.pack(pady=16)
            tk.Button(btns, text="RETRY",
                      command=lambda: for_destroy(reaction_screen),
                      font=("Consolas", 12, "bold"), fg=ACCENT_ORANGE, bg=BG2,
                      relief="flat", padx=25, pady=8).pack(side="left", padx=10)
            tk.Button(btns, text="◂ BACK", command=go_back,
                      font=("Consolas", 12, "bold"), fg=accent, bg=BG2,
                      relief="flat", padx=25, pady=8).pack(side="left", padx=10)

        for w in (stage, msg, sub):
            w.bind("<Button-1>", on_click)
        root.bind("<Button-1>", on_click)

        def unbind_root():
            root.unbind("<Button-1>")

        content.bind("<Destroy>", lambda e: unbind_root() if e.widget is content else None)

        state["phase"] = "freeze"
        set_stage(BG2, "GET READY", "first round starts now")
        root.after(700, next_round)

    # ═══════════════════════════════════════════════════
    #  SHARED VALORANT CAMERA (raw mouse, FOV 103)
    # ═══════════════════════════════════════════════════
    def project_target(cam_yaw, cam_pitch, t_yaw, t_pitch, w, h):
        hfov = math.radians(VALO_FOV_H)
        vfov = 2.0 * math.atan(math.tan(hfov / 2.0) * (h / max(w, 1)))
        rel_y = math.radians(t_yaw - cam_yaw)
        rel_p = math.radians(t_pitch - cam_pitch)
        rel_y = (rel_y + math.pi) % (2.0 * math.pi) - math.pi
        if abs(rel_y) > math.radians(78) or abs(rel_p) > math.radians(68):
            return None
        x = w / 2.0 + math.tan(rel_y) * (w / 2.0) / math.tan(hfov / 2.0)
        y = h / 2.0 - math.tan(rel_p) * (h / 2.0) / math.tan(vfov / 2.0)
        if x < -80 or y < -80 or x > w + 80 or y > h + 80:
            return None
        return x, y

    def ang_to_px(ang_deg, w):
        hfov = math.radians(VALO_FOV_H)
        return max(4.0, math.tan(math.radians(ang_deg)) * (w / 2.0) / math.tan(hfov / 2.0))

    def make_camera():
        dpi, sens = get_valo_settings(cfg)
        dpc = valo_deg_per_count(sens)
        cam = {"yaw": 0.0, "pitch": 0.0, "dpc": dpc, "dpi": dpi, "sens": sens}

        def apply_delta(dx, dy):
            cam["yaw"] += dx * dpc
            cam["pitch"] = max(-85.0, min(85.0, cam["pitch"] - dy * dpc))

        return cam, apply_delta

    def draw_crosshair(canvas, w, h, color=ACCENT_CYAN):
        cx, cy = w / 2.0, h / 2.0
        g, s = 6, 15
        canvas.delete("xh")
        canvas.create_line(cx - s, cy, cx - g, cy, fill=color, width=2, tags="xh")
        canvas.create_line(cx + g, cy, cx + s, cy, fill=color, width=2, tags="xh")
        canvas.create_line(cx, cy - s, cx, cy - g, fill=color, width=2, tags="xh")
        canvas.create_line(cx, cy + g, cx, cy + s, fill=color, width=2, tags="xh")
        canvas.create_oval(cx - 1.5, cy - 1.5, cx + 1.5, cy + 1.5,
                           fill=color, outline="", tags="xh")

    def draw_target_at(canvas, x, y, r, fill_outline=ACCENT_PINK):
        canvas.delete("target")
        canvas.create_oval(x - r, y - r, x + r, y + r,
                           outline=fill_outline, width=3, fill=BG2, tags="target")
        canvas.create_oval(x - r * 0.62, y - r * 0.62, x + r * 0.62, y + r * 0.62,
                           outline=fill_outline, width=1, tags="target")
        canvas.create_oval(x - 5, y - 5, x + 5, y + 5,
                           outline=fill_outline, fill=fill_outline, tags="target")

    def attach_raw(canvas, on_delta, on_click):
        raw = WinMouse()
        ok = raw.start(canvas)

        def poll():
            if not raw._active:
                return
            dx, dy, clicked = raw.pump()
            if (dx or dy) and on_delta:
                on_delta(dx, dy)
            if clicked and on_click:
                on_click()
            if raw._active:
                root.after(8, poll)

        if ok:
            root.after(8, poll)
        return raw, ok

    def make_play_canvas(parent, accent_color):
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        canvas_w = int(sw * 0.88)
        canvas_h = int(sh * 0.66)
        frame = tk.Frame(parent, bg=accent_color, bd=2)
        frame.pack(pady=8)
        canvas = tk.Canvas(frame, width=canvas_w, height=canvas_h,
                           bg=BG2, highlightthickness=0, cursor="none")
        canvas.pack()
        return canvas, canvas_w, canvas_h

    # ═══════════════════════════════════════════════════
    #  AIM TRAIN — Valorant-matched flicks
    # ═══════════════════════════════════════════════════
    def aimtrain_screen(precision=False):
        clear_buttons()
        canvas, canvas_w, canvas_h = make_play_canvas(content, ACCENT_CYAN)
        cx, cy = canvas_w / 2.0, canvas_h / 2.0
        TOTAL_TARGETS = 20
        TARGET_ANG = 0.95

        cam, apply_delta = make_camera()
        state = {
            "hits": 0, "misses": 0, "spawned": 0,
            "shot_pending": False,
            "started_at": None, "current_start": None,
            "t_yaw": 0.0, "t_pitch": 0.0,
            "reaction_times": [], "running": True,
            "score": 0, "combo": 0, "max_combo": 0,
            "raw": None,
        }

        top = tk.Frame(content, bg=BG)
        top.pack(fill="x", pady=4, before=canvas.master)
        mode_title = "PRECISION" if precision else "AIM TRAIN"
        tk.Label(top, text=f"{mode_title}  ·  VALORANT",
                 font=("Consolas", 15, "bold"),
                 fg=ACCENT_CYAN, bg=BG).pack(side="left", padx=10)
        score_lbl = tk.Label(top, text="0 pts",
                             font=("Consolas", 18, "bold"),
                             fg=ACCENT_ORANGE, bg=BG)
        score_lbl.pack(side="right", padx=10)
        combo_lbl = tk.Label(top, text="",
                             font=("Consolas", 13, "bold"),
                             fg=ACCENT_PINK, bg=BG)
        combo_lbl.pack(side="right", padx=10)

        hud2 = tk.Frame(content, bg=BG)
        hud2.pack(fill="x", before=canvas.master)
        info_lbl = tk.Label(hud2, text="Hits: 0  Misses: 0  Target: 0/20  Acc: 0%",
                            font=("Consolas", 11), fg=FG, bg=BG)
        info_lbl.pack(side="left", padx=10)
        timer_lbl = tk.Label(hud2, text="0.0s",
                             font=("Consolas", 11, "bold"),
                             fg=ACCENT_ORANGE, bg=BG)
        timer_lbl.pack(side="right", padx=10)

        hint = tk.Label(
            content,
            text=(f"Move with Valorant sens ({cam['dpi']:.0f} DPI / {cam['sens']})  ·  "
                f"aim at the center  ·  left click to shoot" if precision else
                f"Move with Valorant sens ({cam['dpi']:.0f} DPI / {cam['sens']})  ·  "
                f"crosshair is locked  ·  left click to shoot"),
            font=("Consolas", 10), fg=GREY, bg=BG,
        )
        hint.pack(pady=4)

        def combo_multiplier(combo):
            return 1.0 + min(max(combo - 1, 0), 9) * (1.0 / 9)

        def update_hud():
            total_shots = state["hits"] + state["misses"]
            accuracy = (state["hits"] / total_shots * 100) if total_shots else 0
            info_lbl.config(
                text=f"Hits: {state['hits']}  Misses: {state['misses']}  "
                     f"Target: {state['spawned']}/{TOTAL_TARGETS}  "
                     f"Acc: {accuracy:.0f}%"
            )
            score_lbl.config(text=f"{state['score']:,} pts")
            if state["combo"] > 1:
                mult = combo_multiplier(state["combo"])
                combo_lbl.config(
                    text=f"COMBO x{state['combo']} ({mult:.1f}×)",
                    fg=ACCENT_GREEN if state["combo"] >= 5 else ACCENT_PINK,
                )
            else:
                combo_lbl.config(text="")

        def redraw():
            if not state["running"]:
                return
            pos = project_target(cam["yaw"], cam["pitch"],
                                 state["t_yaw"], state["t_pitch"],
                                 canvas_w, canvas_h)
            r = ang_to_px(TARGET_ANG, canvas_w)
            if pos is None:
                canvas.delete("target")
            else:
                draw_target_at(canvas, pos[0], pos[1], r)
            draw_crosshair(canvas, canvas_w, canvas_h)
            root.after(8, redraw)

        def spawn_target():
            if not state["running"]:
                return
            if state["spawned"] >= TOTAL_TARGETS:
                finish_game()
                return
            state["spawned"] += 1
            state["shot_pending"] = False
            for _ in range(20):
                dyaw = random.uniform(-22.0, 22.0)
                dpitch = random.uniform(-10.0, 10.0)
                if math.hypot(dyaw, dpitch) >= 7.0:
                    break
            state["t_yaw"] = cam["yaw"] + dyaw
            state["t_pitch"] = max(-70.0, min(70.0, cam["pitch"] + dpitch))
            state["current_start"] = time.perf_counter()
            if state["started_at"] is None:
                state["started_at"] = time.perf_counter()
            update_hud()

        def tick_timer():
            if not state["running"]:
                return
            if state["started_at"] is not None:
                timer_lbl.config(text=f"{time.perf_counter() - state['started_at']:.1f}s")
            root.after(100, tick_timer)

        def shoot():
            if (not state["running"] or state["current_start"] is None
                    or state["shot_pending"]):
                return
            pos = project_target(cam["yaw"], cam["pitch"],
                                 state["t_yaw"], state["t_pitch"],
                                 canvas_w, canvas_h)
            r = ang_to_px(TARGET_ANG, canvas_w)
            hit = False
            if pos is not None:
                hit_radius = max(3.0, r * 0.2) if precision else r
                hit = math.hypot(pos[0] - cx, pos[1] - cy) <= hit_radius
            react = time.perf_counter() - state["current_start"]
            if hit:
                state["shot_pending"] = True
                state["hits"] += 1
                state["combo"] += 1
                state["max_combo"] = max(state["max_combo"], state["combo"])
                state["reaction_times"].append(react)
                speed_ms = react * 1000
                speed_bonus = max(0, min(100, int((500 - speed_ms) / 4)))
                mult = combo_multiplier(state["combo"])
                gained = int((100 + speed_bonus) * mult * (2 if precision else 1))
                state["score"] += gained
                canvas.create_text(cx, cy - 42, text=f"+{gained}",
                                   font=("Consolas", 14, "bold"),
                                   fill=ACCENT_ORANGE, tags="flash")
                canvas.create_text(cx, cy - 62, text=f"{speed_ms:.0f}ms",
                                   font=("Consolas", 9),
                                   fill=ACCENT_CYAN, tags="flash")
                root.after(280, lambda: canvas.delete("flash"))
                update_hud()
                root.after(80, spawn_target)
            else:
                state["misses"] += 1
                state["combo"] = 0
                canvas.create_text(cx, cy - 36, text="MISS",
                                   font=("Consolas", 12, "bold"),
                                   fill=ACCENT_RED, tags="flash")
                root.after(220, lambda: canvas.delete("flash"))
                update_hud()

        def finish_game():
            state["running"] = False
            if state["raw"]:
                state["raw"].stop()
                state["raw"] = None
            canvas.delete("target")
            total_shots = state["hits"] + state["misses"]
            accuracy = (state["hits"] / total_shots * 100) if total_shots else 0
            total_time = (time.perf_counter() - state["started_at"]
                          if state["started_at"] else 0)
            avg_react = (sum(state["reaction_times"]) / len(state["reaction_times"]) * 1000
                         if state["reaction_times"] else 0)
            best_react = (min(state["reaction_times"]) * 1000
                          if state["reaction_times"] else 0)
            final_score = state["score"]
            cfg["total_points"] = cfg.get("total_points", 0) + final_score
            score_key = "precision_scores" if precision else "high_scores"
            previous_best = max(cfg.get(score_key, []), default=0)
            cfg.setdefault(score_key, []).append(final_score)
            cfg["aim_scores"].append(accuracy)
            feature_key = "precision" if precision else "aim_train"
            cfg["features_used"][feature_key] = cfg["features_used"].get(feature_key, 0) + 1
            save_cfg(cfg)

            clear_content()
            tk.Label(content, text="PRECISION RESULTS" if precision else "GAME OVER",
                     font=("Consolas", 26, "bold"), fg=ACCENT_PINK, bg=BG).pack(pady=12)
            tk.Label(content, text=f"{final_score:,}",
                     font=("Consolas", 42, "bold"), fg=ACCENT_ORANGE, bg=BG).pack()
            tk.Label(content, text="P O I N T S",
                     font=("Consolas", 14), fg=GREY, bg=BG).pack(pady=(0, 12))
            box = tk.Frame(content, bg=BG2, highlightthickness=1,
                           highlightbackground=ACCENT_CYAN)
            box.pack(pady=10, ipadx=50, ipady=16)
            rows = [
                ("Targets hit", f"{state['hits']} / {TOTAL_TARGETS}"),
                ("Misses", str(state["misses"])),
                ("Accuracy", f"{accuracy:.1f}%"),
                ("Max combo", f"x{state['max_combo']}"),
                ("Avg flick", f"{avg_react:.0f} ms"),
                ("Best flick", f"{best_react:.0f} ms"),
                ("Total time", f"{total_time:.2f} s"),
                ("Sens used", f"{cam['dpi']:.0f} DPI / {cam['sens']}"),
                ("Total points (all-time)", f"{cfg['total_points']:,}"),
            ]
            for k, v in rows:
                r = tk.Frame(box, bg=BG2)
                r.pack(fill="x", pady=3)
                tk.Label(r, text=f"{k:<24}", font=("Consolas", 12),
                         fg=GREY, bg=BG2, anchor="w", width=26).pack(side="left")
                tk.Label(r, text=v, font=("Consolas", 12, "bold"),
                         fg=FG, bg=BG2, anchor="w").pack(side="left")
            highs = cfg.get(score_key, [])
            if final_score > previous_best:
                record_text = "★ NEW PRECISION RECORD ★" if precision else "★ NEW HIGH SCORE ★"
                tk.Label(content, text=record_text,
                         font=("Consolas", 16, "bold"),
                         fg=ACCENT_GREEN, bg=BG).pack(pady=8)
            if accuracy >= 90:
                rating, color = "ELITE ★", ACCENT_GREEN
            elif accuracy >= 75:
                rating, color = "GREAT ◆", ACCENT_CYAN
            elif accuracy >= 60:
                rating, color = "GOOD ○", ACCENT_ORANGE
            else:
                rating, color = "TRAIN MORE", ACCENT_RED
            tk.Label(content, text=f"Rating: {rating}",
                     font=("Consolas", 16, "bold"), fg=color, bg=BG).pack(pady=4)
            btns = tk.Frame(content, bg=BG)
            btns.pack(pady=14)
            tk.Button(btns, text="RETRY",
                      command=lambda: for_destroy(lambda: aimtrain_screen(precision)),
                      font=("Consolas", 12, "bold"), fg=ACCENT_CYAN, bg=BG2,
                      relief="flat", padx=25, pady=8).pack(side="left", padx=10)
            tk.Button(btns, text="◂ BACK", command=go_back,
                      font=("Consolas", 12, "bold"), fg=accent, bg=BG2,
                      relief="flat", padx=25, pady=8).pack(side="left", padx=10)

        def on_delta(dx, dy):
            if state["running"]:
                apply_delta(dx, dy)

        raw, ok = attach_raw(canvas, on_delta, shoot)
        state["raw"] = raw if ok else None
        if not ok:
            hint.config(text="Raw mouse unavailable — using cursor move (not 1:1 Valorant)",
                        fg=ACCENT_ORANGE)
            last = {"p": None}

            def motion(e):
                if last["p"] is None:
                    last["p"] = (e.x, e.y)
                    return
                apply_delta(e.x - last["p"][0], e.y - last["p"][1])
                last["p"] = (e.x, e.y)

            canvas.bind("<Motion>", motion)
            canvas.config(cursor="crosshair")
            canvas.bind("<Button-1>", lambda e: shoot())

        def stop_raw(_e=None):
            if state["raw"]:
                state["raw"].stop()
                state["raw"] = None
        content.bind("<Destroy>", lambda e: stop_raw() if e.widget is content else None)

        update_hud()
        tick_timer()
        draw_crosshair(canvas, canvas_w, canvas_h)
        root.after_idle(spawn_target)
        root.after(8, redraw)

    # ═══════════════════════════════════════════════════
    #  FOLLOW — simple tracking
    # ═══════════════════════════════════════════════════
    def follow_screen():
        clear_buttons()
        canvas, canvas_w, canvas_h = make_play_canvas(content, ACCENT_PINK)
        cx, cy = canvas_w / 2.0, canvas_h / 2.0
        DURATION = 30.0
        TARGET_ANG = 1.15

        cam, apply_delta = make_camera()
        state = {
            "running": True, "started_at": None,
            "on_frames": 0, "tot_frames": 0,
            "score": 0, "streak": 0, "max_streak": 0,
            "raw": None, "t_yaw": 0.0, "t_pitch": 0.0,
        }

        top = tk.Frame(content, bg=BG)
        top.pack(fill="x", pady=4, before=canvas.master)
        tk.Label(top, text="FOLLOW  ·  SIMPLE",
                 font=("Consolas", 15, "bold"),
                 fg=ACCENT_PINK, bg=BG).pack(side="left", padx=10)
        score_lbl = tk.Label(top, text="0%",
                             font=("Consolas", 18, "bold"),
                             fg=ACCENT_ORANGE, bg=BG)
        score_lbl.pack(side="right", padx=10)

        hud2 = tk.Frame(content, bg=BG)
        hud2.pack(fill="x", before=canvas.master)
        info_lbl = tk.Label(hud2, text="Keep the crosshair on the orb",
                            font=("Consolas", 11), fg=FG, bg=BG)
        info_lbl.pack(side="left", padx=10)
        timer_lbl = tk.Label(hud2, text=f"{DURATION:.0f}s",
                             font=("Consolas", 11, "bold"),
                             fg=ACCENT_ORANGE, bg=BG)
        timer_lbl.pack(side="right", padx=10)

        hint = tk.Label(
            content,
            text=f"One slow target  ·  same Valorant sens ({cam['dpi']:.0f} DPI / {cam['sens']})  ·  no shooting",
            font=("Consolas", 10), fg=GREY, bg=BG,
        )
        hint.pack(pady=4)

        def target_pos(t):
            yaw = 16.0 * math.sin(t * 0.85)
            pitch = 7.0 * math.sin(t * 0.55 + 0.8)
            return yaw, pitch

        def finish_follow():
            if not state["running"]:
                return
            state["running"] = False
            if state["raw"]:
                state["raw"].stop()
                state["raw"] = None
            pct = (state["on_frames"] / state["tot_frames"] * 100.0) if state["tot_frames"] else 0
            pts = int(pct * 20 + state["max_streak"] * 2)
            cfg["total_points"] = cfg.get("total_points", 0) + pts
            prev = cfg.get("best_follow")
            new_best = prev is None or pct > prev
            if new_best:
                cfg["best_follow"] = pct
            cfg["features_used"]["follow"] = cfg["features_used"].get("follow", 0) + 1
            save_cfg(cfg)

            clear_content()
            tk.Label(content, text="FOLLOW RESULTS",
                     font=("Consolas", 24, "bold"), fg=ACCENT_PINK, bg=BG).pack(pady=14)
            tk.Label(content, text=f"{pct:.0f}%",
                     font=("Consolas", 48, "bold"), fg=ACCENT_ORANGE, bg=BG).pack()
            tk.Label(content, text="ON TARGET",
                     font=("Consolas", 14), fg=GREY, bg=BG).pack(pady=(0, 12))
            box = tk.Frame(content, bg=BG2, highlightthickness=1,
                           highlightbackground=ACCENT_PINK)
            box.pack(pady=10, ipadx=50, ipady=16)
            rows = [
                ("Time on target", f"{pct:.1f}%"),
                ("Best streak", f"{state['max_streak'] / 60.0:.1f}s"),
                ("Points", f"{pts:,}"),
                ("Sens used", f"{cam['dpi']:.0f} DPI / {cam['sens']}"),
            ]
            for k, v in rows:
                r = tk.Frame(box, bg=BG2)
                r.pack(fill="x", pady=4)
                tk.Label(r, text=f"{k:<18}", font=("Consolas", 13),
                         fg=GREY, bg=BG2, anchor="w", width=18).pack(side="left")
                tk.Label(r, text=v, font=("Consolas", 13, "bold"),
                         fg=FG, bg=BG2).pack(side="left")
            if new_best:
                tk.Label(content, text="★ NEW PERSONAL BEST ★",
                         font=("Consolas", 16, "bold"),
                         fg=ACCENT_GREEN, bg=BG).pack(pady=8)
            if pct >= 85:
                rating, color = "GLUED", ACCENT_GREEN
            elif pct >= 70:
                rating, color = "SMOOTH", ACCENT_CYAN
            elif pct >= 50:
                rating, color = "OK", ACCENT_ORANGE
            else:
                rating, color = "CHASE IT", ACCENT_RED
            tk.Label(content, text=f"Rating: {rating}",
                     font=("Consolas", 16, "bold"), fg=color, bg=BG).pack(pady=4)
            btns = tk.Frame(content, bg=BG)
            btns.pack(pady=16)
            tk.Button(btns, text="RETRY",
                      command=lambda: for_destroy(follow_screen),
                      font=("Consolas", 12, "bold"), fg=ACCENT_PINK, bg=BG2,
                      relief="flat", padx=25, pady=8).pack(side="left", padx=10)
            tk.Button(btns, text="◂ BACK", command=go_back,
                      font=("Consolas", 12, "bold"), fg=accent, bg=BG2,
                      relief="flat", padx=25, pady=8).pack(side="left", padx=10)

        def loop():
            if not state["running"]:
                return
            now = time.perf_counter()
            if state["started_at"] is None:
                state["started_at"] = now
            t = now - state["started_at"]
            left = max(0.0, DURATION - t)
            timer_lbl.config(text=f"{left:.1f}s")
            if t >= DURATION:
                finish_follow()
                return
            state["t_yaw"], state["t_pitch"] = target_pos(t)
            pos = project_target(cam["yaw"], cam["pitch"],
                                 state["t_yaw"], state["t_pitch"],
                                 canvas_w, canvas_h)
            r = ang_to_px(TARGET_ANG, canvas_w)
            on = False
            if pos is not None:
                draw_target_at(canvas, pos[0], pos[1], r, ACCENT_PINK)
                on = math.hypot(pos[0] - cx, pos[1] - cy) <= r
            else:
                canvas.delete("target")
            draw_crosshair(canvas, canvas_w, canvas_h,
                           ACCENT_GREEN if on else ACCENT_CYAN)
            state["tot_frames"] += 1
            if on:
                state["on_frames"] += 1
                state["streak"] += 1
                state["max_streak"] = max(state["max_streak"], state["streak"])
            else:
                state["streak"] = 0
            pct = state["on_frames"] / state["tot_frames"] * 100.0
            score_lbl.config(text=f"{pct:.0f}%")
            info_lbl.config(
                text=("ON TARGET" if on else "lost it") +
                     (f"  ·  streak {state['streak'] / 60.0:.1f}s" if state["streak"] > 12 else "")
            )
            root.after(16, loop)

        def on_delta(dx, dy):
            if state["running"]:
                apply_delta(dx, dy)

        raw, ok = attach_raw(canvas, on_delta, None)
        state["raw"] = raw if ok else None
        if not ok:
            hint.config(text="Raw mouse unavailable — using cursor move (not 1:1 Valorant)",
                        fg=ACCENT_ORANGE)
            last = {"p": None}

            def motion(e):
                if last["p"] is None:
                    last["p"] = (e.x, e.y)
                    return
                apply_delta(e.x - last["p"][0], e.y - last["p"][1])
                last["p"] = (e.x, e.y)

            canvas.bind("<Motion>", motion)
            canvas.config(cursor="crosshair")

        def stop_raw(_e=None):
            if state["raw"]:
                state["raw"].stop()
                state["raw"] = None
        content.bind("<Destroy>", lambda e: stop_raw() if e.widget is content else None)

        draw_crosshair(canvas, canvas_w, canvas_h)
        root.after_idle(loop)

    if start_mode == MODE_FOLLOW:
        root.after_idle(follow_screen)
    elif start_mode == MODE_SETTINGS:
        root.after_idle(sens_screen)
    else:
        show_home()
    root.mainloop()

# ═══════════════════════════════════════════════════════════
#  MODE DISPATCHER
# ═══════════════════════════════════════════════════════════

def run_mode(mode):
    if mode == MODE_PLAY:
        run_aimtrain_mode()
    elif mode == MODE_SETTINGS:
        run_aimtrain_mode(start_mode=MODE_SETTINGS)
    elif mode == MODE_AIMTRAIN:
        run_aimtrain_mode()
    elif mode == MODE_FOLLOW:
        run_aimtrain_mode(start_mode=MODE_FOLLOW)

# ═══════════════════════════════════════════════════════════
#  UPDATE — runs update.bat which relaunches aim.exe
# ═══════════════════════════════════════════════════════════

def run_update():
    candidates = ["update.bat", "build.bat", "update.cmd", "build.cmd"]
    paths = [BASE_DIR / name for name in candidates]
    paths.extend(BASE_DIR / "dist" / name for name in candidates)
    found = next((path for path in paths if path.is_file()), None)

    if not found:
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk(); root.withdraw()
            messagebox.showwarning("Update",
                f"No update script found beside the app or in its dist folder.\n\n"
                f"Place 'update.bat' next to the executable:\n\n{BASE_DIR}")
            root.destroy()
        except Exception:
            pass
        return False

    try:
        flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
        subprocess.Popen(
            ["cmd", "/c", str(found)] if os.name == "nt" else [str(found)],
            cwd=str(found.parent),
            creationflags=flags,
        )
        log(f"Update launched: {found.name}", "UPDATE")
        return True
    except Exception as e:
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk(); root.withdraw()
            messagebox.showerror("Update error", f"Failed to launch:\n{e}")
            root.destroy()
        except Exception:
            pass
        return False

# ═══════════════════════════════════════════════════════════
#  GUI LAUNCHER
# ═══════════════════════════════════════════════════════════

def run_gui():
    import tkinter as tk

    class RoundBtn(tk.Canvas):
        def __init__(self, parent, text, command, radius=90,
                     fg_color=ACCENT_CYAN, hover_color=ACCENT_PINK):
            size = radius * 2 + 10
            super().__init__(parent, width=size, height=size,
                             bg=BG, highlightthickness=0)
            self.command = command
            self.color = fg_color
            self.hover_color = hover_color
            cx = cy = size // 2
            r = radius
            self.circle = self.create_oval(cx-r, cy-r, cx+r, cy+r,
                                           outline=fg_color, width=3, fill=BG2)
            self.inner = self.create_oval(cx-r+10, cy-r+10, cx+r-10, cy+r-10,
                                           outline="", fill="")
            self.label = self.create_text(cx, cy, text=text, fill=fg_color,
                                           font=("Consolas", 13, "bold"))
            self.tag_bind("all", "<Enter>", self._enter)
            self.tag_bind("all", "<Leave>", self._leave)
            self.tag_bind("all", "<Button-1>", lambda e: self.command())

        def _enter(self, _):
            self.itemconfig(self.circle, outline=self.hover_color, width=4)
            self.itemconfig(self.label, fill=self.hover_color)
            self.itemconfig(self.inner, fill=DARKGREY)

        def _leave(self, _):
            self.itemconfig(self.circle, outline=self.color, width=3)
            self.itemconfig(self.label, fill=self.color)
            self.itemconfig(self.inner, fill="")

    root = tk.Tk()
    root.title(f"AIM.exe v{VERSION}")
    root.configure(bg=BG)
    root.resizable(False, False)

    w, h = 760, 620
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    x, y = (sw - w) // 2, (sh - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")

    tk.Label(root, text="▚▚  AIM.exe ▞▞",
             font=("Consolas", 24, "bold"),
             fg=ACCENT_PINK, bg=BG).pack(pady=(30, 5))
    tk.Label(root, text=f"v{VERSION} · valorant sens · reaction · follow",
             font=("Consolas", 10),
             fg=GREY, bg=BG).pack(pady=(0, 25))

    status = tk.Label(root, text="ready · select a mode",
                       font=("Consolas", 10),
                       fg="#444466", bg=BG)

    def launch(mode):
        exe = sys.executable
        try:
            if getattr(sys, "frozen", False):
                cmd = [exe, "--mode", mode]
            else:
                cmd = [exe, str(Path(__file__).resolve()), "--mode", mode]
            flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
            subprocess.Popen(cmd, creationflags=flags)
            status.config(text=f"launched · {mode}", fg=ACCENT_CYAN)
        except Exception as e:
            status.config(text=f"error: {e}", fg=ACCENT_RED)

    def on_update_click():
        status.config(text="running update...", fg=ACCENT_ORANGE)
        if run_update():
            status.config(text="update launched", fg=ACCENT_CYAN)
            root.after(1000, root.destroy)
        else:
            status.config(text="update could not be started", fg=ACCENT_RED)

    row = tk.Frame(root, bg=BG)
    row.pack(pady=10)
    RoundBtn(row, "PLAY", lambda: launch(MODE_PLAY),
             radius=74, fg_color=ACCENT_CYAN).pack(pady=5)
    RoundBtn(row, "SETTINGS", lambda: launch(MODE_SETTINGS),
             radius=74, fg_color=ACCENT_RED).pack(pady=5)
    RoundBtn(row, "UPDATE", on_update_click,
             radius=74, fg_color=ACCENT_PINK).pack(pady=5)

    # Total points displayed on launcher
    cfg = load_cfg()
    total = cfg.get("total_points", 0)
    pts_row = tk.Frame(root, bg=BG)
    pts_row.pack(pady=5)
    tk.Label(pts_row, text=f"★ {total:,} points total",
             font=("Consolas", 12, "bold"),
             fg=ACCENT_ORANGE, bg=BG).pack()

    status.pack(side="bottom", pady=15)

    tk.Label(root, text=f"hwid: {cfg.get('hwid', '')[:16]} · build: {VERSION}",
             font=("Consolas", 8),
             fg="#222233", bg=BG).pack(side="bottom", pady=(0, 5))

    root.mainloop()

# ═══════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════

def main():
    if "--mode" in sys.argv:
        idx = sys.argv.index("--mode")
        if idx + 1 < len(sys.argv):
            run_mode(sys.argv[idx + 1])
            return
    run_gui()

if __name__ == "__main__":
    main()