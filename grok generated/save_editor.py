#!/usr/bin/env python3
"""
ULTRAKILL Save Editor – Python GUI (crash-resistant)
Supports Levels, General progress, and Cybergrind.
Improved money + Cybergrind parsing based on clean Rust-generated saves.
"""

import struct
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import Dict, List, Optional, Any

RANK_NAMES = {-1: "None", 0: "D", 1: "C", 2: "B", 3: "A", 4: "S", 12: "P"}
RANK_FROM_NAME = {v: k for k, v in RANK_NAMES.items()}
DIFFICULTIES = ["Harmless", "Lenient", "Standard", "Violent", "Brutal", "UKMD"]


# ---------------------------------------------------------------------------
# Parsers / patchers
# ---------------------------------------------------------------------------

def parse_rank_data(data: bytes) -> Optional[Dict[str, Any]]:
    try:
        ranks = None
        secrets_found = None
        major_assists = None

        pos = 0
        while pos < len(data) - 10:
            if data[pos] == 0x0F:
                try:
                    length = struct.unpack_from("<i", data, pos + 5)[0]
                    ptype = data[pos + 9]
                    if length == 6 and ptype == 8:
                        ranks = list(struct.unpack_from("<6i", data, pos + 10))
                        pos += 10 + 24
                        continue
                    if 1 <= length <= 12 and ptype == 1:
                        arr = list(data[pos + 10 : pos + 10 + length])
                        if secrets_found is None:
                            secrets_found = [bool(x) for x in arr]
                        elif major_assists is None:
                            major_assists = [bool(x) for x in arr]
                        pos += 10 + length
                        continue
                except Exception:
                    pass
            pos += 1

        if ranks is None:
            ranks = [-1] * 6
        if secrets_found is None:
            secrets_found = []
        if major_assists is None:
            major_assists = [False] * 6

        return {
            "ranks": ranks,
            "secrets_found": secrets_found,
            "major_assists": major_assists,
            "challenge": False,
            "has_stats": b"RankScoreData" in data,
            "raw": data,
            "dirty": False,
        }
    except Exception:
        return None


def patch_ranks_in_place(data: bytes, new_ranks: List[int]) -> bytes:
    pos = 0
    while pos < len(data) - 34:
        if data[pos] == 0x0F:
            length = struct.unpack_from("<i", data, pos + 5)[0]
            ptype = data[pos + 9]
            if length == 6 and ptype == 8:
                new_data = bytearray(data)
                struct.pack_into("<6i", new_data, pos + 10, *new_ranks[:6])
                return bytes(new_data)
        pos += 1
    return data


def parse_cybergrind(data: bytes) -> Optional[Dict[str, Any]]:
    """Parse cybergrindhighscore.bepis.
    Single = type 0x0B, Int32 = type 0x08, arrays of length 6.
    """
    try:
        waves, kills, style, times = None, None, None, None
        pos = 0
        while pos < len(data) - 10:
            if data[pos] == 0x0F:
                try:
                    length = struct.unpack_from("<i", data, pos + 5)[0]
                    ptype = data[pos + 9]
                    if length == 6:
                        if ptype == 0x0B:  # Single
                            arr = list(struct.unpack_from("<6f", data, pos + 10))
                            if waves is None:
                                waves = arr
                            elif times is None:
                                times = arr
                            pos += 10 + 24
                            continue
                        if ptype == 0x08:  # Int32
                            arr = list(struct.unpack_from("<6i", data, pos + 10))
                            if kills is None:
                                kills = arr
                            elif style is None:
                                style = arr
                            pos += 10 + 24
                            continue
                except Exception:
                    pass
            pos += 1

        if waves is None:
            waves = [0.0] * 6
        if kills is None:
            kills = [0] * 6
        if style is None:
            style = [0] * 6
        if times is None:
            times = [0.0] * 6

        return {
            "waves": waves,
            "kills": kills,
            "style": style,
            "times": times,
            "raw": data,
            "dirty": False,
        }
    except Exception:
        return None


def patch_cybergrind_in_place(data: bytes, waves, kills, style, times) -> bytes:
    new_data = bytearray(data)
    pos = 0
    wave_done = kill_done = style_done = time_done = False
    while pos < len(new_data) - 34:
        if new_data[pos] == 0x0F:
            length = struct.unpack_from("<i", new_data, pos + 5)[0]
            ptype = new_data[pos + 9]
            if length == 6:
                if ptype == 0x0B and not wave_done:
                    struct.pack_into("<6f", new_data, pos + 10, *[float(x) for x in waves[:6]])
                    wave_done = True
                    pos += 10 + 24
                    continue
                if ptype == 0x0B and wave_done and not time_done:
                    struct.pack_into("<6f", new_data, pos + 10, *[float(x) for x in times[:6]])
                    time_done = True
                    pos += 10 + 24
                    continue
                if ptype == 0x08 and not kill_done:
                    struct.pack_into("<6i", new_data, pos + 10, *[int(x) for x in kills[:6]])
                    kill_done = True
                    pos += 10 + 24
                    continue
                if ptype == 0x08 and kill_done and not style_done:
                    struct.pack_into("<6i", new_data, pos + 10, *[int(x) for x in style[:6]])
                    style_done = True
                    pos += 10 + 24
                    continue
        pos += 1
    return bytes(new_data)


def parse_general(data: bytes) -> Dict[str, Any]:
    """
    Extract money + key flags.
    Prefers the clean Rust-style layout:
    after type info → 02 00 00 00 <Int32 money> <bools...>
    """
    result = {
        "money": 0,
        "money_offset": None,
        "money_is_int": True,
        "intro_seen": False,
        "tutorial_beat": False,
        "clash_mode": False,
        "ghost_drone": False,
        "raw": data,
        "dirty": False,
    }

    try:
        candidates = []
        pos = 0
        while True:
            idx = data.find(b"\x02\x00\x00\x00", pos)
            if idx == -1 or idx + 8 > len(data):
                break
            val = struct.unpack_from("<i", data, idx + 4)[0]
            if 0 <= val <= 100_000_000:
                candidates.append((idx + 4, val))
            pos = idx + 1

        if candidates:
            good = [c for c in candidates if c[0] > 400] or candidates
            offset, money = good[0]
            result["money"] = money
            result["money_offset"] = offset
            result["money_is_int"] = True

            bpos = offset + 4
            if bpos + 3 <= len(data):
                result["intro_seen"] = data[bpos] == 1
                result["tutorial_beat"] = data[bpos + 1] == 1
                result["clash_mode"] = data[bpos + 2] == 1

    except Exception:
        pass

    return result


def patch_general_money(data: bytes, money: int, offset: Optional[int]) -> bytes:
    if offset is None or offset + 4 > len(data):
        return data
    new_data = bytearray(data)
    struct.pack_into("<i", new_data, offset, int(money))
    return bytes(new_data)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class UltrakillSaveEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ULTRAKILL Save Editor (Python)")
        self.geometry("960x720")
        self.minsize(820, 560)

        self.save_path: Optional[Path] = None
        self.level_data: Dict[str, Dict] = {}
        self.cyber_data: Optional[Dict] = None
        self.general_data: Optional[Dict] = None
        self.current_level: Optional[str] = None

        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill=tk.X)

        ttk.Label(top, text="Slot folder:").pack(side=tk.LEFT)
        self.path_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.path_var, width=55).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="Browse…", command=self.browse).pack(side=tk.LEFT)
        ttk.Button(top, text="Load", command=self.load).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="Save All", command=self.save_all).pack(side=tk.LEFT, padx=4)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # ========== Levels tab ==========
        levels_frame = ttk.Frame(self.nb)
        self.nb.add(levels_frame, text="Levels")

        left = ttk.Frame(levels_frame)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=4)
        ttk.Label(left, text="Level files:").pack(anchor=tk.W)
        self.level_list = tk.Listbox(left, width=28, height=26, exportselection=False)
        self.level_list.pack(fill=tk.Y, expand=True)
        self.level_list.bind("<<ListboxSelect>>", self.on_level_select)

        right = ttk.Frame(levels_frame, padding=10)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ttk.Label(right, text="Ranks by difficulty", font=("", 10, "bold")).grid(
            row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 6)
        )
        self.rank_vars = []
        for i, diff in enumerate(DIFFICULTIES):
            ttk.Label(right, text=diff + ":").grid(row=i + 1, column=0, sticky=tk.W, pady=2)
            var = tk.StringVar(value="None")
            cb = ttk.Combobox(right, textvariable=var, values=list(RANK_NAMES.values()),
                              width=8, state="readonly")
            cb.grid(row=i + 1, column=1, sticky=tk.W, pady=2)
            self.rank_vars.append(var)

        ttk.Label(right, text="Challenge completed:").grid(row=8, column=0, sticky=tk.W, pady=10)
        self.challenge_var = tk.BooleanVar()
        ttk.Checkbutton(right, variable=self.challenge_var).grid(row=8, column=1, sticky=tk.W)

        ttk.Label(right, text="Secrets found:").grid(row=9, column=0, sticky=tk.W)
        self.secrets_frame = ttk.Frame(right)
        self.secrets_frame.grid(row=9, column=1, sticky=tk.W)
        self.secret_vars: List[tk.BooleanVar] = []

        ttk.Label(right, text="Major assists:").grid(row=10, column=0, sticky=tk.W, pady=6)
        self.assists_frame = ttk.Frame(right)
        self.assists_frame.grid(row=10, column=1, sticky=tk.W)
        self.assist_vars: List[tk.BooleanVar] = []

        ttk.Button(right, text="Apply changes to selected level",
                   command=self.apply_level).grid(row=11, column=0, columnspan=2, pady=14)

        # ========== General tab ==========
        gen_frame = ttk.Frame(self.nb, padding=12)
        self.nb.add(gen_frame, text="General")

        ttk.Label(gen_frame, text="Money:", font=("", 10, "bold")).grid(row=0, column=0, sticky=tk.W, pady=4)
        self.money_var = tk.StringVar(value="0")
        ttk.Entry(gen_frame, textvariable=self.money_var, width=16).grid(row=0, column=1, sticky=tk.W, pady=4)
        self.money_hint = ttk.Label(gen_frame, text="", foreground="#666")
        self.money_hint.grid(row=0, column=2, sticky=tk.W, padx=8)

        self.intro_var = tk.BooleanVar()
        self.tutorial_var = tk.BooleanVar()
        self.clash_var = tk.BooleanVar()
        self.ghost_var = tk.BooleanVar()

        ttk.Checkbutton(gen_frame, text="Intro seen", variable=self.intro_var).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=2)
        ttk.Checkbutton(gen_frame, text="Tutorial beaten", variable=self.tutorial_var).grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=2)
        ttk.Checkbutton(gen_frame, text="Clash mode unlocked", variable=self.clash_var).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=2)
        ttk.Checkbutton(gen_frame, text="Ghost drone mode unlocked", variable=self.ghost_var).grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=2)

        ttk.Button(gen_frame, text="Apply General changes",
                   command=self.apply_general).grid(row=5, column=0, columnspan=2, pady=16)

        ttk.Label(gen_frame, text="Note: Money is read as Int32 (works with the Rust editor format).\n"
                                  "On some modern saves the exact layout differs – check the value after Load.\n"
                                  "Weapon unlocks / secret missions are not yet fully editable.",
                  foreground="#555", wraplength=520).grid(row=6, column=0, columnspan=3, sticky=tk.W)

        # ========== Cybergrind tab ==========
        cg_frame = ttk.Frame(self.nb, padding=12)
        self.nb.add(cg_frame, text="Cybergrind")

        headers = ["Difficulty", "Waves", "Kills", "Style", "Time"]
        for col, h in enumerate(headers):
            ttk.Label(cg_frame, text=h, font=("", 9, "bold")).grid(row=0, column=col, padx=6, pady=4)

        self.cg_vars = []
        for row, diff in enumerate(DIFFICULTIES):
            ttk.Label(cg_frame, text=diff).grid(row=row + 1, column=0, sticky=tk.W, padx=6)
            row_vars = []
            for col in range(4):
                var = tk.StringVar(value="0")
                ttk.Entry(cg_frame, textvariable=var, width=10).grid(row=row + 1, column=col + 1, padx=4, pady=2)
                row_vars.append(var)
            self.cg_vars.append(row_vars)

        ttk.Button(cg_frame, text="Apply Cybergrind changes",
                   command=self.apply_cyber).grid(row=8, column=0, columnspan=5, pady=16)

        self.cg_status = ttk.Label(cg_frame, text="Load a slot that contains cybergrindhighscore.bepis")
        self.cg_status.grid(row=9, column=0, columnspan=5, sticky=tk.W)

        # status bar
        self.status = ttk.Label(self, text="Ready – select a Slot folder and press Load.",
                                relief=tk.SUNKEN, anchor=tk.W)
        self.status.pack(fill=tk.X, side=tk.BOTTOM, padx=4, pady=2)

    # ---------- actions ----------
    def browse(self):
        path = filedialog.askdirectory(title="Select ULTRAKILL Slot folder")
        if path:
            self.path_var.set(path)

    def load(self):
        path = Path(self.path_var.get().strip())
        if not path.is_dir():
            messagebox.showerror("Error", "Select a valid Slot folder.")
            return

        self.save_path = path
        self.level_data.clear()
        self.level_list.delete(0, tk.END)
        self.current_level = None
        self.cyber_data = None
        self.general_data = None

        count = 0
        for f in sorted(path.glob("lvl*progress.bepis")):
            parsed = parse_rank_data(f.read_bytes())
            if parsed:
                self.level_data[f.name] = parsed
                self.level_list.insert(tk.END, f.name)
                count += 1

        # General
        gen_path = path / "generalprogress.bepis"
        if gen_path.exists():
            self.general_data = parse_general(gen_path.read_bytes())
            money = self.general_data.get("money", 0)
            self.money_var.set(str(money))
            if self.general_data.get("money_offset") is not None:
                self.money_hint.config(text=f"(offset {self.general_data['money_offset']})")
            else:
                self.money_hint.config(text="(could not locate money – edit may not save)")
            self.intro_var.set(self.general_data.get("intro_seen", False))
            self.tutorial_var.set(self.general_data.get("tutorial_beat", False))
            self.clash_var.set(self.general_data.get("clash_mode", False))
            self.ghost_var.set(self.general_data.get("ghost_drone", False))
            count += 1

        # Cybergrind
        cg_path = path / "cybergrindhighscore.bepis"
        if cg_path.exists():
            self.cyber_data = parse_cybergrind(cg_path.read_bytes())
            if self.cyber_data:
                for i, row_vars in enumerate(self.cg_vars):
                    row_vars[0].set(str(self.cyber_data["waves"][i]))
                    row_vars[1].set(str(self.cyber_data["kills"][i]))
                    row_vars[2].set(str(self.cyber_data["style"][i]))
                    row_vars[3].set(str(self.cyber_data["times"][i]))
                self.cg_status.config(text="Cybergrind data loaded – edit and press Apply")
            count += 1
        else:
            self.cg_status.config(text="No cybergrindhighscore.bepis found in this slot")

        self.status.config(text=f"Loaded {count} file(s) from {path}")
        if self.level_list.size():
            self.level_list.selection_set(0)
            self.on_level_select(None)

    def on_level_select(self, _event):
        sel = self.level_list.curselection()
        if not sel:
            return
        name = self.level_list.get(sel[0])
        self.current_level = name
        data = self.level_data.get(name)
        if not data:
            return

        for i, var in enumerate(self.rank_vars):
            r = data["ranks"][i] if i < len(data["ranks"]) else -1
            var.set(RANK_NAMES.get(r, "None"))

        self.challenge_var.set(data.get("challenge", False))

        for w in self.secrets_frame.winfo_children():
            w.destroy()
        self.secret_vars.clear()
        for i, s in enumerate(data.get("secrets_found", [])):
            var = tk.BooleanVar(value=s)
            ttk.Checkbutton(self.secrets_frame, variable=var, text=str(i + 1)).pack(side=tk.LEFT)
            self.secret_vars.append(var)
        if not data.get("secrets_found"):
            ttk.Label(self.secrets_frame, text="(none)").pack(side=tk.LEFT)

        for w in self.assists_frame.winfo_children():
            w.destroy()
        self.assist_vars.clear()
        for i, a in enumerate(data.get("major_assists", [False] * 6)[:6]):
            var = tk.BooleanVar(value=a)
            ttk.Checkbutton(self.assists_frame, variable=var, text=DIFFICULTIES[i][:3]).pack(side=tk.LEFT)
            self.assist_vars.append(var)

        self.status.config(text=f"Editing {name}  |  nested stats: {data.get('has_stats', False)}")

    def apply_level(self):
        name = self.current_level
        if not name or name not in self.level_data:
            messagebox.showinfo("Info", "Select a level first.")
            return
        data = self.level_data[name]
        data["ranks"] = [RANK_FROM_NAME.get(v.get(), -1) for v in self.rank_vars]
        data["challenge"] = self.challenge_var.get()
        data["secrets_found"] = [v.get() for v in self.secret_vars]
        data["major_assists"] = [v.get() for v in self.assist_vars]
        data["dirty"] = True
        self.status.config(text=f"Level changes staged for {name}")

    def apply_general(self):
        if not self.general_data:
            messagebox.showinfo("Info", "No generalprogress.bepis loaded.")
            return
        try:
            self.general_data["money"] = int(float(self.money_var.get()))
        except ValueError:
            messagebox.showerror("Error", "Money must be a whole number.")
            return
        self.general_data["intro_seen"] = self.intro_var.get()
        self.general_data["tutorial_beat"] = self.tutorial_var.get()
        self.general_data["clash_mode"] = self.clash_var.get()
        self.general_data["ghost_drone"] = self.ghost_var.get()
        self.general_data["dirty"] = True
        self.status.config(text="General changes staged")

    def apply_cyber(self):
        if not self.cyber_data:
            messagebox.showinfo("Info", "No cybergrindhighscore.bepis loaded.")
            return
        try:
            waves, kills, style, times = [], [], [], []
            for row in self.cg_vars:
                waves.append(float(row[0].get()))
                kills.append(int(float(row[1].get())))
                style.append(int(float(row[2].get())))
                times.append(float(row[3].get()))
            self.cyber_data["waves"] = waves
            self.cyber_data["kills"] = kills
            self.cyber_data["style"] = style
            self.cyber_data["times"] = times
            self.cyber_data["dirty"] = True
            self.status.config(text="Cybergrind changes staged")
        except ValueError:
            messagebox.showerror("Error", "All Cybergrind fields must be numbers.")

    def save_all(self):
        if not self.save_path:
            messagebox.showerror("Error", "No folder loaded.")
            return

        backup_dir = self.save_path / "_backup_before_edit"
        try:
            backup_dir.mkdir(exist_ok=True)
            for f in self.save_path.glob("*.bepis"):
                dest = backup_dir / f.name
                if not dest.exists():
                    dest.write_bytes(f.read_bytes())
        except Exception as e:
            if not messagebox.askyesno("Backup warning", f"Backup failed: {e}\nContinue?"):
                return

        saved = 0

        # Levels
        for name, data in self.level_data.items():
            if not data.get("dirty"):
                continue
            patched = patch_ranks_in_place(data["raw"], data["ranks"])
            (self.save_path / name).write_bytes(patched)
            data["raw"] = patched
            data["dirty"] = False
            saved += 1

        # General
        if self.general_data and self.general_data.get("dirty"):
            offset = self.general_data.get("money_offset")
            if offset is None:
                messagebox.showwarning("Money", "Could not locate money field – money was not written.")
            else:
                patched = patch_general_money(
                    self.general_data["raw"],
                    self.general_data["money"],
                    offset
                )
                (self.save_path / "generalprogress.bepis").write_bytes(patched)
                self.general_data["raw"] = patched
                saved += 1
            self.general_data["dirty"] = False

        # Cybergrind
        if self.cyber_data and self.cyber_data.get("dirty"):
            patched = patch_cybergrind_in_place(
                self.cyber_data["raw"],
                self.cyber_data["waves"],
                self.cyber_data["kills"],
                self.cyber_data["style"],
                self.cyber_data["times"],
            )
            (self.save_path / "cybergrindhighscore.bepis").write_bytes(patched)
            self.cyber_data["raw"] = patched
            self.cyber_data["dirty"] = False
            saved += 1

        self.status.config(text=f"Saved {saved} file(s). Backup → {backup_dir.name}/")
        messagebox.showinfo("Done", f"Wrote {saved} file(s).\nBackup in:\n{backup_dir}")


if __name__ == "__main__":
    app = UltrakillSaveEditor()
    app.mainloop()
