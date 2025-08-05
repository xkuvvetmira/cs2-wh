# made by kuvvetmira

import ctypes
import ctypes.wintypes as wintypes
import struct
import time
import random
import json
import os
import threading
import customtkinter as ctk
from tkinter import colorchooser
from PIL import Image, ImageFilter, ImageDraw
from customtkinter import CTkImage

PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008

class Offsets:
    wLocalPlayerPawn = 28265344
    dwEntityList = 30139936
    m_iTeamNum = 1003
    m_hPlayerPawn = 2300
    m_lifeState = 848
    m_Glow = 3264
    m_glowColorOverride = 64
    m_bGlowing = 81
    m_iGlowType = 48

class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * wintypes.MAX_PATH),
    ]

class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD), ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", wintypes.DWORD), ("hModule", wintypes.HMODULE),
        ("szModule", ctypes.c_char * 256), ("szExePath", ctypes.c_char * wintypes.MAX_PATH),
    ]

class CS2GlowManager:
    def __init__(self, process_name=b"cs2.exe", module_name=b"client.dll"):
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.process_name = process_name
        self.module_name = module_name
        self.pid = self._get_pid()
        self.handle = self.k32.OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION | PROCESS_QUERY_INFORMATION, False, self.pid)
        if not self.handle:
            raise Exception("Failed to open process handle")
        self.client = self._get_module_base()
        if not self.client:
            raise Exception("Failed to find module base")

    def _get_pid(self):
        snapshot = self.k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == -1: raise Exception("Failed to create process snapshot")
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        success = self.k32.Process32First(snapshot, ctypes.byref(entry))
        while success:
            if entry.szExeFile[:len(self.process_name)].lower() == self.process_name.lower():
                self.k32.CloseHandle(snapshot)
                return entry.th32ProcessID
            success = self.k32.Process32Next(snapshot, ctypes.byref(entry))
        self.k32.CloseHandle(snapshot)
        raise Exception("Process not found")

    def _get_module_base(self):
        snap = self.k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, self.pid)
        if snap == -1: return None
        module = MODULEENTRY32()
        module.dwSize = ctypes.sizeof(MODULEENTRY32)
        success = self.k32.Module32First(snap, ctypes.byref(module))
        while success:
            if module.szModule[:len(self.module_name)].lower() == self.module_name.lower():
                self.k32.CloseHandle(snap)
                return ctypes.cast(module.modBaseAddr, ctypes.c_void_p).value
            success = self.k32.Module32Next(snap, ctypes.byref(module))
        self.k32.CloseHandle(snap)
        return None

    def _read(self, addr, size):
        buf = ctypes.create_string_buffer(size)
        bytes_read = ctypes.c_size_t()
        if not self.k32.ReadProcessMemory(self.handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(bytes_read)): return None
        if bytes_read.value != size: return None
        return buf.raw

    def _write(self, addr, data):
        buf = ctypes.create_string_buffer(data)
        bytes_written = ctypes.c_size_t()
        if not self.k32.WriteProcessMemory(self.handle, ctypes.c_void_p(addr), buf, len(data), ctypes.byref(bytes_written)): return False
        return bytes_written.value == len(data)

    def _read_i(self, addr): return struct.unpack("i", self._read(addr, 4))[0] if self._read(addr, 4) else 0
    def _read_u(self, addr): return struct.unpack("I", self._read(addr, 4))[0] if self._read(addr, 4) else 0
    def _read_ull(self, addr): return struct.unpack("Q", self._read(addr, 8))[0] if self._read(addr, 8) else 0
    def _write_u(self, addr, val): return self._write(addr, struct.pack("I", val))
    
    # --- DEĞİŞİKLİK BURADA ---
    def _to_argb(self, r, g, b, a):
        clamp = lambda x: max(0, min(1, x))
        r, g, b, a = [int(clamp(c) * 255) for c in (r, g, b, a)]
        # R ve B kanallarının yerini değiştiriyoruz. (r << 16) yerine (b << 16), b yerine r yazıldı.
        return (a << 24) | (b << 16) | (g << 8) | r
    # --- DEĞİŞİKLİK SONU ---

    def _get_local_team(self):
        local = self._read_ull(self.client + Offsets.wLocalPlayerPawn)
        if local == 0: return None
        return self._read_i(local + Offsets.m_iTeamNum)

    def update_glow(self, team_color, enemy_color):
        local = self._read_ull(self.client + Offsets.wLocalPlayerPawn)
        entity_list = self._read_ull(self.client + Offsets.dwEntityList)
        team_local = self._get_local_team()

        if not local or not entity_list or team_local is None:
            return

        for i in range(64):
            entry = self._read_ull(entity_list + 0x10)
            if not entry: continue
            controller = self._read_ull(entry + i * 0x78)
            if not controller: continue
            pawn_handle = self._read_i(controller + Offsets.m_hPlayerPawn)
            if not pawn_handle: continue
            entry2 = self._read_ull(entity_list + 0x8 * ((pawn_handle & 0x7FFF) >> 9) + 0x10)
            if not entry2: continue
            pawn = self._read_ull(entry2 + 0x78 * (pawn_handle & 0x1FF))
            if not pawn or pawn == local: continue
            life_state = self._read_u(pawn + Offsets.m_lifeState)
            if life_state != 256: continue

            is_team = self._read_i(pawn + Offsets.m_iTeamNum) == team_local
            color = team_color if is_team else enemy_color

            glow = pawn + Offsets.m_Glow
            self._write_u(glow + Offsets.m_glowColorOverride, self._to_argb(*color))
            self._write_u(glow + Offsets.m_bGlowing, 1)
            self._write_u(glow + Offsets.m_iGlowType, 3)

    def close_handle(self):
        if self.handle:
            self.k32.CloseHandle(self.handle)

class App(ctk.CTk):
    SETTINGS_FILE = "settings.json"
    DEFAULT_SETTINGS_FILE = "default.json"
    TEAM_PNG = "assets/ct.png"
    ENEMY_PNG = "assets/t.png"
    ICON_FILE = "assets/icon.ico"
    PALETTE_ICON = "assets/palette.png"
    
    TARGET_IMAGE_WIDTH = 140
    TARGET_IMAGE_HEIGHT = 248

    def __init__(self, cs2_manager):
        super().__init__()
        self.cs2_manager = cs2_manager
        self.glow_thread_running = True
        
        self.title("Kuvvethax")
        self.geometry("500x620")
        self.resizable(False, False)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        if os.path.exists(self.ICON_FILE):
            self.iconbitmap(self.ICON_FILE)

        self.settings = self.load_settings()

        self.glow_enabled_var = ctk.BooleanVar(value=self.settings.get("glow_enabled", True))
        self.team_check_var = ctk.BooleanVar(value=self.settings.get("team_check_enabled", True))
        
        self.palette_icon_image = self.load_icon(self.PALETTE_ICON, (20, 20))

        self.create_widgets()
        self.update_dynamic_colors()
        self.update_all_previews()
        self.update_ui_state()
        
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.glow_thread = threading.Thread(target=self.glow_loop, daemon=True)
        self.glow_thread.start()

    def _adjust_color_brightness(self, hex_color, factor=1.2):
        hex_color = hex_color.lstrip('#')
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        new_rgb = tuple(min(255, int(c * factor)) for c in rgb)
        return f"#{new_rgb[0]:02x}{new_rgb[1]:02x}{new_rgb[2]:02x}"

    def load_icon(self, path, size):
        if os.path.exists(path):
            return CTkImage(Image.open(path), size=size)
        return None

    def create_glow_image(self, image_path, glow_color_hex, glow_size=15):
        try:
            original_image = Image.open(image_path).convert("RGBA")
        except FileNotFoundError:
            placeholder = Image.new("RGBA", (self.TARGET_IMAGE_WIDTH, self.TARGET_IMAGE_HEIGHT), (0, 0, 0, 0))
            draw = ImageDraw.Draw(placeholder)
            draw.text((10, self.TARGET_IMAGE_HEIGHT / 2 - 10), "PNG Bulunamadı", fill="white")
            return CTkImage(placeholder, size=(self.TARGET_IMAGE_WIDTH, self.TARGET_IMAGE_HEIGHT))

        alpha = original_image.getchannel('A')
        glow = Image.new('RGBA', original_image.size, color=glow_color_hex)
        glow.putalpha(alpha)
        glow = glow.filter(ImageFilter.GaussianBlur(radius=glow_size))
        final_image = Image.alpha_composite(glow, original_image)
        
        final_image_resized = final_image.resize((self.TARGET_IMAGE_WIDTH, self.TARGET_IMAGE_HEIGHT), Image.Resampling.LANCZOS)
        
        return CTkImage(final_image_resized, size=(self.TARGET_IMAGE_WIDTH, self.TARGET_IMAGE_HEIGHT))

    def load_settings(self):
        try:
            with open(self.SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "glow_enabled": True,
                "team_check_enabled": True,
                "enemy_color": [1.0, 0.0, 0.0, 1.0],
                "team_color": [0.0, 0.3, 1.0, 1.0]
            }
    
    def save_settings(self):
        self.settings["glow_enabled"] = self.glow_enabled_var.get()
        self.settings["team_check_enabled"] = self.team_check_var.get()
        with open(self.SETTINGS_FILE, 'w') as f:
            json.dump(self.settings, f, indent=4)

    def create_widgets(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        title_label = ctk.CTkLabel(self, text="KUVVETHAX", font=ctk.CTkFont(size=28, weight="bold"))
        title_label.grid(row=0, column=0, padx=10, pady=(20, 10))

        subtitle_label = ctk.CTkLabel(
            self, 
            text="discord: @0kuv | crackturkey.com", 
            font=ctk.CTkFont(size=12), 
            text_color="gray"
        )
        subtitle_label.grid(row=4, column=0, padx=60, pady=0)

        preview_frame = ctk.CTkFrame(self, fg_color="transparent")
        preview_frame.grid(row=1, column=0, padx=20, pady=0, sticky="nsew")
        preview_frame.grid_columnconfigure(0, weight=1)
        preview_frame.grid_columnconfigure(1, weight=1)
        preview_frame.grid_rowconfigure(0, weight=1)

        self.enemy_box = ctk.CTkFrame(preview_frame, border_width=2)
        self.enemy_box.grid(row=0, column=0, padx=(0, 10), pady=10, sticky="nsew")
        self.enemy_box.grid_rowconfigure(1, weight=1)
        self.enemy_box.grid_columnconfigure(0, weight=1)
        
        enemy_label = ctk.CTkLabel(self.enemy_box, text="ÖRNEK DÜŞMAN", font=ctk.CTkFont(size=16, weight="bold"))
        enemy_label.grid(row=0, column=0, pady=(10, 5))
        self.enemy_image_label = ctk.CTkLabel(self.enemy_box, text="")
        self.enemy_image_label.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)

        self.team_box = ctk.CTkFrame(preview_frame, border_width=2)
        self.team_box.grid(row=0, column=1, padx=(10, 0), pady=10, sticky="nsew")
        self.team_box.grid_rowconfigure(1, weight=1)
        self.team_box.grid_columnconfigure(0, weight=1)

        team_label = ctk.CTkLabel(self.team_box, text="ÖRNEK TAKIM", font=ctk.CTkFont(size=16, weight="bold"))
        team_label.grid(row=0, column=0, pady=(10, 5))
        self.team_image_label = ctk.CTkLabel(self.team_box, text="")
        self.team_image_label.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)

        control_frame = ctk.CTkFrame(self)
        control_frame.grid(row=2, column=0, padx=20, pady=20, sticky="ew")
        control_frame.grid_columnconfigure(0, weight=1)

        self.glow_switch = ctk.CTkSwitch(
            control_frame, text="Hileyi Aktif Et", variable=self.glow_enabled_var, command=self.update_ui_state,
            progress_color="#FF0000", font=ctk.CTkFont(size=14))
        self.glow_switch.grid(row=0, column=0, padx=20, pady=(15, 10), sticky="w")
        
        self.team_check_switch = ctk.CTkSwitch(
            control_frame, text="Takım Glow", variable=self.team_check_var, command=self.update_ui_state,
            progress_color="#007BFF", font=ctk.CTkFont(size=14))
        self.team_check_switch.grid(row=1, column=0, padx=20, pady=10, sticky="w")

        self.enemy_color_button = ctk.CTkButton(
            control_frame, text="Düşman Rengi", command=lambda: self.pick_color("enemy"),
            image=self.palette_icon_image, compound="left")
        self.enemy_color_button.grid(row=2, column=0, padx=20, pady=10, sticky="ew")

        self.team_color_button = ctk.CTkButton(
            control_frame, text="Takım Rengi", command=lambda: self.pick_color("team"),
            image=self.palette_icon_image, compound="left")
        self.team_color_button.grid(row=3, column=0, padx=20, pady=(10, 15), sticky="ew")

    def pick_color(self, target):
        title = "Düşman Rengi Seç" if target == "enemy" else "Takım Rengi Seç"
        
        color_code = colorchooser.askcolor(
            color=self.rgba_to_hex(self.settings[f"{target}_color"]),
            title=title
        )
        
        if color_code and color_code[0]:
            rgb = color_code[0]
            normalized_color = [rgb[0]/255, rgb[1]/255, rgb[2]/255, 1.0]
            self.settings[f"{target}_color"] = normalized_color
            
            self.update_single_preview(target)
            self.update_dynamic_colors()

    def update_dynamic_colors(self):
        enemy_hex = self.rgba_to_hex(self.settings["enemy_color"])
        team_hex = self.rgba_to_hex(self.settings["team_color"])
        
        enemy_hover_hex = self._adjust_color_brightness(enemy_hex)
        team_hover_hex = self._adjust_color_brightness(team_hex)

        self.enemy_box.configure(border_color=enemy_hex)
        self.team_box.configure(border_color=team_hex)
        
        self.enemy_color_button.configure(fg_color=enemy_hex, hover_color=enemy_hover_hex)
        self.team_color_button.configure(fg_color=team_hex, hover_color=team_hover_hex)

    def update_single_preview(self, target):
        color_hex = self.rgba_to_hex(self.settings[f"{target}_color"])
        
        if target == "enemy":
            is_enabled = self.glow_enabled_var.get()
            if not is_enabled: color_hex = "#000000"
            glow_image = self.create_glow_image(self.ENEMY_PNG, color_hex)
            self.enemy_image_label.configure(image=glow_image)
        elif target == "team":
            is_enabled = self.glow_enabled_var.get() and self.team_check_var.get()
            if not is_enabled: color_hex = "#000000"
            glow_image = self.create_glow_image(self.TEAM_PNG, color_hex)
            self.team_image_label.configure(image=glow_image)
            
    def update_all_previews(self):
        self.update_single_preview("enemy")
        self.update_single_preview("team")

    def update_ui_state(self):
        glow_on = self.glow_enabled_var.get()
        team_check_on = self.team_check_var.get()

        self.team_check_switch.configure(state=ctk.NORMAL if glow_on else ctk.DISABLED)
        self.enemy_color_button.configure(state=ctk.NORMAL if glow_on else ctk.DISABLED)
        self.team_color_button.configure(state=ctk.NORMAL if glow_on and team_check_on else ctk.DISABLED)
        
        self.update_all_previews()

    def glow_loop(self):
        no_glow_color = [0.0, 0.0, 0.0, 0.0]
        while self.glow_thread_running:
            try:
                if self.glow_enabled_var.get():
                    enemy_color = self.settings["enemy_color"]
                    team_color = self.settings["team_color"] if self.team_check_var.get() else no_glow_color
                    self.cs2_manager.update_glow(team_color=team_color, enemy_color=enemy_color)
                else:
                    self.cs2_manager.update_glow(team_color=no_glow_color, enemy_color=no_glow_color)
            except Exception as e:
                break
            time.sleep(0.01 + random.uniform(0, 0.005))

    def on_closing(self):
        self.glow_thread_running = False
        if self.glow_thread.is_alive():
            self.glow_thread.join(timeout=1.0)
        self.save_settings()
        self.cs2_manager.close_handle()
        self.destroy()

    @staticmethod
    def rgba_to_hex(rgba):
        r = int(rgba[0] * 255)
        g = int(rgba[1] * 255)
        b = int(rgba[2] * 255)
        return f"#{r:02x}{g:02x}{b:02x}"

if __name__ == "__main__":
    try:
        cs2_manager = CS2GlowManager()
        app = App(cs2_manager)
        app.mainloop()
        
    except Exception as e:
        input(f"Başlatma Hatası: {e}\nCS2 oyununun çalıştığından emin olun.\nÇıkmak için Enter'a basın...")
