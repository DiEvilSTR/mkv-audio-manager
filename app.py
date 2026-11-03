"""A small English-language desktop interface for MKV audio management."""
from pathlib import Path
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from media import Cancelled, audio_streams, export, inspect


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MKV Audio Manager")
        self.geometry("940x540")
        self.minsize(820, 460)
        self.events = queue.Queue()
        self.folder = None
        self.current = None
        self.info = None
        self.files = []
        self.removed = set()
        self.default_choices = {}
        self.generation = 0
        self.busy = False
        self.cancel = threading.Event()
        self.last_output = None
        self.search = tk.StringVar()
        self.folder_text = tk.StringVar(value="Open a folder to get started")
        self.status = tk.StringVar(value="Ready")
        self.summary = tk.StringVar(value="Select an MKV file to inspect its audio tracks.")
        self.default = tk.StringVar(value="Keep existing defaults")
        self.overwrite = tk.BooleanVar(value=True)
        self._build()
        self.search.trace_add("write", lambda *_: self.show_files())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_timer = self.after(80, self.poll)

    def _build(self):
        self._dark_theme()
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        # Only the tables grow/shrink. Action rows always keep their own space.
        outer.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(outer)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar.columnconfigure(2, weight=1)
        self.open_button = ttk.Button(toolbar, text="Open folder…", command=self.open_folder)
        self.open_button.grid(row=0, column=0)
        self.refresh_button = ttk.Button(toolbar, text="Refresh", command=self.refresh)
        self.refresh_button.grid(row=0, column=1, padx=6)
        ttk.Label(toolbar, textvariable=self.folder_text, width=1).grid(row=0, column=2, sticky="ew", padx=(4, 0))
        panes = ttk.Panedwindow(outer, orient="horizontal")
        panes.grid(row=1, column=0, sticky="nsew")
        left = ttk.Frame(panes, padding=(0, 0, 6, 0))
        right = ttk.Frame(panes, padding=(6, 0, 0, 0))
        for pane in (left, right):
            pane.columnconfigure(0, weight=1)
            pane.rowconfigure(2, weight=1)
        panes.add(left, weight=1)
        panes.add(right, weight=3)
        ttk.Label(left, text="FILES · filter by name", style="Heading.TLabel").grid(row=0, column=0, sticky="w")
        self.filter_entry = ttk.Entry(left, textvariable=self.search)
        self.filter_entry.grid(row=1, column=0, sticky="ew", pady=(5, 6))
        self.file_tree = self.scrolled(left, row=2, columns=("name",), show="headings", selectmode="browse", height=5)
        self.file_tree.heading("name", text="MKV files")
        self.file_tree.column("name", width=210, minwidth=100)
        self.file_tree.bind("<<TreeviewSelect>>", self.select_file)
        ttk.Label(right, text="AUDIO TRACKS · check boxes to remove", style="Heading.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(right, textvariable=self.summary, width=1).grid(row=1, column=0, sticky="ew", pady=(5, 6))
        columns = ("remove", "track", "language", "title", "codec", "channels", "default")
        self.tracks = self.scrolled(right, row=2, columns=columns, show="headings", selectmode="browse", height=5)
        for key, title, width in zip(columns, ["Remove", "Track", "Language", "Title", "Codec", "Channels", "Default"],
                                     [64, 45, 74, 110, 65, 74, 62]):
            self.tracks.heading(key, text=title)
            self.tracks.column(key, width=width, minwidth=45, stretch=key == "title")
        self.tracks.bind("<Button-1>", self.click_track)
        self.tracks.bind("<space>", self.space_track)
        controls = ttk.Frame(right)
        controls.grid(row=3, column=0, sticky="ew", pady=(5, 0))
        ttk.Button(controls, text="Select all", command=lambda: self.mark_all(True)).pack(side="left")
        ttk.Button(controls, text="Clear", command=lambda: self.mark_all(False)).pack(side="left", padx=5)
        default_row = ttk.Frame(right)
        default_row.grid(row=4, column=0, sticky="ew", pady=(5, 0))
        default_row.columnconfigure(1, weight=1)
        ttk.Label(default_row, text="Default audio").grid(row=0, column=0, padx=(0, 6))
        self.default_box = ttk.Combobox(default_row, textvariable=self.default, state="readonly", width=1)
        self.default_box.grid(row=0, column=1, sticky="ew")
        output_options = ttk.Frame(outer)
        output_options.grid(row=2, column=0, sticky="ew", pady=(7, 5))
        output_options.columnconfigure(1, weight=1)
        self.overwrite_box = ttk.Checkbutton(output_options, text="Overwrite original", variable=self.overwrite)
        self.overwrite_box.grid(row=0, column=0, sticky="w")
        ttk.Label(output_options, text="Unchecked: save as filename-clear.mkv · No re-encoding", width=1).grid(
            row=0, column=1, sticky="ew", padx=(12, 0))
        footer = ttk.Frame(outer)
        footer.grid(row=3, column=0, sticky="ew")
        footer.columnconfigure(1, weight=1)
        self.save_button = ttk.Button(footer, text="Remove selected / Save MKV", command=self.save,
                                      style="Accent.TButton", state="disabled")
        self.save_button.grid(row=0, column=3)
        self.cancel_button = ttk.Button(footer, text="Cancel", command=self.cancel.set, state="disabled")
        self.cancel_button.grid(row=0, column=2, padx=6)
        self.output_button = ttk.Button(footer, text="Open output folder", command=self.open_output, state="disabled")
        self.output_button.grid(row=0, column=0)
        bottom = ttk.Frame(outer)
        bottom.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.status, width=1).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.progress = ttk.Progressbar(bottom, maximum=100, length=160)
        self.progress.grid(row=0, column=1, sticky="e")

    def _dark_theme(self):
        background, surface, button = "#181c24", "#202631", "#303949"
        text, muted, border = "#e4e9f2", "#8995a8", "#3b4658"
        selected, accent = "#294a70", "#346db0"
        style = ttk.Style(self)
        style.theme_use("clam")
        self.configure(background=background)
        style.configure(".", font=("Segoe UI", 9), background=background, foreground=text,
                        bordercolor=border, lightcolor=border, darkcolor=border,
                        troughcolor=background, selectbackground=selected, selectforeground=text)
        style.configure("Treeview", rowheight=26, background=surface, fieldbackground=surface,
                        foreground=text)
        style.map("Treeview", background=[("selected", selected)], foreground=[("selected", text)])
        style.configure("Treeview.Heading", background=button, foreground=text, relief="flat")
        style.map("Treeview.Heading", background=[("active", border)])
        style.configure("TButton", background=button, foreground=text, focuscolor=text)
        style.map("TButton", background=[("disabled", surface), ("pressed", selected), ("active", border)],
                  foreground=[("disabled", muted)])
        style.configure("Accent.TButton", background=accent)
        style.map("Accent.TButton", background=[("disabled", surface), ("pressed", "#28558a"),
                                                ("active", "#407fc8")])
        for control in ("TEntry", "TCombobox"):
            style.configure(control, fieldbackground=surface, background=button, foreground=text,
                            insertcolor=text, arrowcolor=text, selectbackground=selected,
                            selectforeground=text)
            style.map(control, fieldbackground=[("disabled", background), ("readonly", surface)],
                      foreground=[("disabled", muted), ("readonly", text)],
                      background=[("active", border), ("readonly", button)],
                      arrowcolor=[("disabled", muted)])
        style.configure("TScrollbar", background=button, arrowcolor=muted, troughcolor=background)
        style.map("TScrollbar", background=[("pressed", selected), ("active", border)])
        style.configure("TProgressbar", background=accent, troughcolor=surface,
                        lightcolor=accent, darkcolor=accent, bordercolor=border)
        style.configure("TCheckbutton", indicatorbackground=surface, indicatorforeground=text)
        style.map("TCheckbutton", background=[("active", background)], foreground=[("disabled", muted)],
                  indicatorbackground=[("disabled", button), ("selected", accent), ("active", border)])
        style.configure("Heading.TLabel", font=("Segoe UI", 9, "bold"))
        self.option_add("*Font", ("Segoe UI", 9))
        self.option_add("*TCombobox*Listbox.background", surface)
        self.option_add("*TCombobox*Listbox.foreground", text)
        self.option_add("*TCombobox*Listbox.selectBackground", selected)
        self.option_add("*TCombobox*Listbox.selectForeground", text)

    def scrolled(self, parent, row, **options):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, sticky="nsew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        tree = ttk.Treeview(frame, **options)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        tree.grid(row=0, column=0, sticky="nsew")
        return tree

    def open_folder(self):
        folder = filedialog.askdirectory(title="Choose a folder with MKV files")
        if folder:
            self.folder = Path(folder)
            self.folder_text.set(str(self.folder))
            self.search.set("")
            self.refresh()

    def clear_tracks(self):
        self.generation += 1
        self.current = self.info = None
        self.removed.clear()
        self.tracks.delete(*self.tracks.get_children())
        self.default.set("Keep existing defaults")
        self.default_box.configure(values=["Keep existing defaults"])
        self.save_button.configure(state="disabled")

    def refresh(self):
        if self.busy or not self.folder:
            return
        self.clear_tracks()
        try:
            self.files = sorted((p for p in self.folder.iterdir() if p.is_file() and p.suffix.lower() == ".mkv"), key=lambda p: p.name.casefold())
        except OSError as exc:
            messagebox.showerror("Could not open folder", str(exc))
            self.files = []
        self.show_files()
        self.summary.set("Select an MKV file to inspect its audio tracks.")
        self.status.set(f"{len(self.files)} MKV files found")

    def show_files(self):
        if self.busy:
            return
        self.file_tree.delete(*self.file_tree.get_children())
        query = self.search.get().casefold()
        for i, path in enumerate(self.files):
            if query in path.name.casefold():
                self.file_tree.insert("", "end", iid=str(i), values=(path.name,))

    def select_file(self, _event=None):
        if self.busy:
            return
        selection = self.file_tree.selection()
        if not selection:
            return
        path = self.files[int(selection[0])]
        if path == self.current:
            return
        self.load_file(path)

    def load_file(self, path):
        self.clear_tracks()
        self.current = path
        token = self.generation
        self.summary.set(path.name)
        self.status.set("Reading audio tracks…")

        def read():
            try:
                self.events.put(("loaded", token, inspect(path)))
            except Exception as exc:
                self.events.put(("load_error", token, str(exc)))
        threading.Thread(target=read, daemon=True).start()

    def render_tracks(self):
        self.tracks.delete(*self.tracks.get_children())
        audio = audio_streams(self.info)
        choices = {"Keep existing defaults": None}
        for number, s in enumerate(audio, 1):
            index = s["index"]
            tags = s.get("tags", {})
            language = tags.get("language", "und")
            title = tags.get("title", "—")
            self.tracks.insert("", "end", iid=str(index), values=(
                "☑" if index in self.removed else "☐", number, language, title,
                s.get("codec_name", "?"), s.get("channel_layout") or s.get("channels", "?"),
                "Yes" if s.get("disposition", {}).get("default") else ""))
            if index not in self.removed:
                choices[f"Track {number} · {language} · {title}"] = index
        self.default_choices = choices
        self.default_box.configure(values=list(choices))
        if self.default.get() not in choices:
            self.default.set("Keep existing defaults")
        self.save_button.configure(state="normal" if audio and not self.busy else "disabled")
        self.status.set(f"{len(audio)} audio tracks · {len(self.removed)} marked for removal")

    def toggle(self, item):
        if self.busy or not item:
            return
        index = int(item)
        if index in self.removed:
            self.removed.remove(index)
        else:
            self.removed.add(index)
        self.render_tracks()
        self.tracks.selection_set(item)
        self.tracks.focus(item)

    def click_track(self, event):
        if self.tracks.identify_region(event.x, event.y) == "cell" and self.tracks.identify_column(event.x) == "#1":
            self.toggle(self.tracks.identify_row(event.y))
            return "break"

    def space_track(self, _event):
        selected = self.tracks.selection()
        if selected:
            self.toggle(selected[0])
        return "break"

    def mark_all(self, selected):
        if self.info and not self.busy:
            self.removed = {s["index"] for s in audio_streams(self.info)} if selected else set()
            self.render_tracks()

    def set_busy(self, busy):
        self.busy = busy
        for widget in (self.open_button, self.refresh_button, self.filter_entry, self.overwrite_box):
            widget.configure(state="disabled" if busy else "normal")
        self.default_box.configure(state="disabled" if busy else "readonly")
        self.save_button.configure(state="disabled" if busy or not self.info else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")

    def save(self):
        if self.busy or not self.info:
            return
        default = self.default_choices.get(self.default.get())
        if not self.removed and default is None:
            messagebox.showinfo("Nothing selected", "Mark audio tracks to remove or choose a new default audio track.")
            return
        if len(self.removed) == len(audio_streams(self.info)):
            if not messagebox.askyesno("Remove all audio?", "All audio tracks are selected. The saved file will have no sound. Continue?"):
                return
        self.set_busy(True)
        self.cancel.clear()
        self.progress["value"] = 0
        self.status.set("Saving MKV…")
        path, info, removed = self.current, self.info, self.removed.copy()
        overwrite = self.overwrite.get()

        def work():
            try:
                output = export(path, info, removed, default, self.cancel,
                                lambda value: self.events.put(("progress", value)), overwrite=overwrite)
                self.events.put(("saved", output, overwrite))
            except Cancelled:
                self.events.put(("cancelled",))
            except Exception as exc:
                self.events.put(("save_error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind in ("loaded", "load_error"):
                    if event[1] != self.generation:
                        continue
                    if kind == "loaded":
                        self.info = event[2]
                        self.render_tracks()
                    else:
                        self.status.set("Could not read file")
                        messagebox.showerror("Could not read file", event[2])
                elif kind == "progress":
                    self.progress["value"] = event[1]
                else:
                    self.set_busy(False)
                    if kind == "saved":
                        self.last_output = event[1]
                        self.output_button.configure(state="normal")
                        self.status.set(f"Saved: {event[1].name}")
                        if event[2]:
                            self.load_file(event[1])
                        else:
                            self.files = sorted(set(self.files + [event[1]]), key=lambda p: p.name.casefold())
                            current = self.current
                            self.show_files()
                            if current in self.files:
                                item = str(self.files.index(current))
                                if self.file_tree.exists(item):
                                    self.file_tree.selection_set(item)
                        detail = "The original file was replaced." if event[2] else "The original file was kept."
                        messagebox.showinfo("MKV saved", f"Saved to:\n{event[1]}\n\n{detail}")
                    elif kind == "cancelled":
                        self.progress["value"] = 0
                        self.status.set("Cancelled · No output file saved")
                    elif kind == "save_error":
                        self.status.set("Save failed")
                        messagebox.showerror("Could not save MKV", event[1])
        except queue.Empty:
            pass
        self.poll_timer = self.after(80, self.poll)

    def destroy(self):
        self.after_cancel(self.poll_timer)
        super().destroy()

    def open_output(self):
        if self.last_output:
            try:
                os.startfile(self.last_output.parent)
            except OSError as exc:
                messagebox.showerror("Could not open folder", str(exc))

    def close(self):
        if self.busy:
            if not messagebox.askyesno("Cancel and exit?", "A file is being saved. Cancel this operation and exit?"):
                return
            self.cancel.set()
            self.status.set("Cancelling before exit…")
            self.after(150, self.close_when_idle)
        else:
            self.destroy()

    def close_when_idle(self):
        if self.busy:
            self.after(150, self.close_when_idle)
        else:
            self.destroy()


if __name__ == "__main__":
    App().mainloop()
