from __future__ import annotations

import io
import threading
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from insta_downloader import (
    default_output_dir,
    download_images,
    download_reels,
    is_url_input,
    parse_date,
    sanitize_username,
)


class QueueWriter(io.TextIOBase):
    def __init__(self, callback):
        self._callback = callback

    def write(self, text: str) -> int:
        if text:
            self._callback(text)
        return len(text)

    def flush(self) -> None:
        return None


class InstaDownloaderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Instagram Media Downloader")
        self.root.geometry("860x620")
        self.root.minsize(760, 560)

        self.profile_var = tk.StringVar()
        self.media_type_var = tk.StringVar(value="reels")
        self.start_date_var = tk.StringVar()
        self.end_date_var = tk.StringVar()
        self.limit_var = tk.StringVar()
        self.output_dir_var = tk.StringVar(value=str(default_output_dir()))
        self.status_var = tk.StringVar(value="Ready")

        self._build_ui()
        self.worker_thread: threading.Thread | None = None

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(
            container,
            text="Instagram Media Downloader",
            font=("Segoe UI", 18, "bold"),
        )
        title.pack(anchor=tk.W, pady=(0, 4))

        subtitle = ttk.Label(
            container,
            text="Download reels or image posts from a public profile using browser cookies.",
            foreground="#505050",
        )
        subtitle.pack(anchor=tk.W, pady=(0, 14))

        form = ttk.LabelFrame(container, text="Download Settings", padding=12)
        form.pack(fill=tk.X)

        ttk.Label(form, text="Username or profile URL").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=6)
        ttk.Entry(form, textvariable=self.profile_var, width=60).grid(row=0, column=1, columnspan=3, sticky=tk.EW, pady=6)

        ttk.Label(form, text="Media type").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=6)
        media_frame = ttk.Frame(form)
        media_frame.grid(row=1, column=1, sticky=tk.W, pady=6)
        ttk.Radiobutton(media_frame, text="Reels", variable=self.media_type_var, value="reels").pack(side=tk.LEFT)
        ttk.Radiobutton(media_frame, text="Images", variable=self.media_type_var, value="images").pack(side=tk.LEFT, padx=(14, 0))

        ttk.Label(form, text="Start date (YYYY-MM-DD)").grid(row=2, column=0, sticky=tk.W, padx=(0, 8), pady=6)
        ttk.Entry(form, textvariable=self.start_date_var, width=24).grid(row=2, column=1, sticky=tk.W, pady=6)

        ttk.Label(form, text="End date (YYYY-MM-DD)").grid(row=2, column=2, sticky=tk.W, padx=(14, 8), pady=6)
        ttk.Entry(form, textvariable=self.end_date_var, width=24).grid(row=2, column=3, sticky=tk.W, pady=6)

        ttk.Label(form, text="Limit downloads (optional)").grid(row=3, column=0, sticky=tk.W, padx=(0, 8), pady=6)
        ttk.Entry(form, textvariable=self.limit_var, width=24).grid(row=3, column=1, sticky=tk.W, pady=6)

        ttk.Label(form, text="Output folder").grid(row=4, column=0, sticky=tk.W, padx=(0, 8), pady=6)
        ttk.Entry(form, textvariable=self.output_dir_var, width=56).grid(row=4, column=1, columnspan=2, sticky=tk.EW, pady=6)
        ttk.Button(form, text="Browse", command=self._choose_output_dir).grid(row=4, column=3, sticky=tk.E, pady=6)

        for col in (1, 2, 3):
            form.grid_columnconfigure(col, weight=1)

        controls = ttk.Frame(container)
        controls.pack(fill=tk.X, pady=(12, 10))
        self.start_button = ttk.Button(controls, text="Start Download", command=self._start_download)
        self.start_button.pack(side=tk.LEFT)

        self.clear_button = ttk.Button(controls, text="Clear Log", command=self._clear_log)
        self.clear_button.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(controls, textvariable=self.status_var, foreground="#0b5a89").pack(side=tk.RIGHT)

        log_frame = ttk.LabelFrame(container, text="Log", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_box = ScrolledText(log_frame, wrap=tk.WORD, height=18)
        self.log_box.pack(fill=tk.BOTH, expand=True)
        self.log_box.configure(state=tk.DISABLED)

    def _choose_output_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_dir_var.get() or str(default_output_dir()))
        if selected:
            self.output_dir_var.set(selected)

    def _clear_log(self) -> None:
        self.log_box.configure(state=tk.NORMAL)
        self.log_box.delete("1.0", tk.END)
        self.log_box.configure(state=tk.DISABLED)

    def _append_log(self, text: str) -> None:
        self.log_box.configure(state=tk.NORMAL)
        self.log_box.insert(tk.END, text)
        self.log_box.see(tk.END)
        self.log_box.configure(state=tk.DISABLED)

    def _safe_log(self, text: str) -> None:
        self.root.after(0, lambda: self._append_log(text))

    def _set_running_state(self, running: bool) -> None:
        if running:
            self.start_button.configure(state=tk.DISABLED)
            self.status_var.set("Downloading...")
        else:
            self.start_button.configure(state=tk.NORMAL)
            self.status_var.set("Ready")

    def _start_download(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Download in progress", "A download is already running.")
            return

        raw_profile = self.profile_var.get().strip()
        if not raw_profile:
            messagebox.showerror("Missing input", "Please enter a username or profile URL.")
            return

        try:
            profile = sanitize_username(raw_profile)
            source_was_url = is_url_input(raw_profile)

            start_raw = self.start_date_var.get().strip() or None
            end_raw = self.end_date_var.get().strip() or None
            start_date = parse_date(start_raw)
            end_date = parse_date(end_raw)

            if start_date and end_date and end_date < start_date:
                raise ValueError("End date must be the same as or later than start date.")

            limit: int | None = None
            limit_text = self.limit_var.get().strip()
            if limit_text:
                limit = int(limit_text)
                if limit <= 0:
                    raise ValueError("Limit must be a positive integer.")

            output_dir = Path(self.output_dir_var.get().strip() or str(default_output_dir())).expanduser()
            output_dir.mkdir(parents=True, exist_ok=True)
        except SystemExit as error:
            messagebox.showerror("Invalid input", str(error))
            return
        except ValueError as error:
            messagebox.showerror("Invalid input", str(error))
            return

        self._set_running_state(True)
        self._safe_log("\n" + "=" * 70 + "\n")
        self._safe_log(f"Starting request for @{profile}\n")
        self._safe_log(f"Media type: {self.media_type_var.get()}\n")
        self._safe_log(f"Output folder: {output_dir}\n")

        self.worker_thread = threading.Thread(
            target=self._run_download,
            args=(
                profile,
                self.media_type_var.get(),
                output_dir,
                limit,
                start_date,
                end_date,
                source_was_url,
            ),
            daemon=True,
        )
        self.worker_thread.start()

    def _run_download(
        self,
        profile: str,
        media_type: str,
        output_dir: Path,
        limit: int | None,
        start_date: datetime | None,
        end_date: datetime | None,
        source_was_url: bool,
    ) -> None:
        writer = QueueWriter(self._safe_log)
        try:
            with redirect_stdout(writer), redirect_stderr(writer):
                if media_type == "images":
                    download_images(
                        profile,
                        output_dir,
                        limit,
                        start_date=start_date,
                        end_date=end_date,
                        source_was_url=source_was_url,
                    )
                else:
                    download_reels(
                        profile,
                        output_dir,
                        limit,
                        start_date=start_date,
                        end_date=end_date,
                        source_was_url=source_was_url,
                    )
                print("Task completed.")
        except SystemExit as error:
            self._safe_log(f"\nError: {error}\n")
            self.root.after(0, lambda: messagebox.showerror("Download failed", str(error)))
        except Exception as error:
            self._safe_log(f"\nUnexpected error: {error}\n")
            self.root.after(0, lambda: messagebox.showerror("Unexpected error", str(error)))
        finally:
            self.root.after(0, lambda: self._set_running_state(False))


def main() -> None:
    root = tk.Tk()
    ttk.Style().theme_use("clam")
    app = InstaDownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
