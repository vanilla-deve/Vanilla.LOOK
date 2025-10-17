import tkinter as tk
from tkinter import ttk, messagebox, filedialog, Toplevel
import psutil
import platform
import time
import datetime
import threading
import queue
import json
import os
import math

# matplotlib for embedded mini-charts
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
APP_NAME = "Vanilla LOOK"
APP_VERSION = "v1.0.0"
AUTHOR = "Camila Rose"
UPDATE_INTERVAL_MS = 1000  # main update interval
CHART_POINTS = 60  # how many points to show in mini charts

# -----------------------
# Helper utilities
# -----------------------
def now_iso():
    return datetime.datetime.now().isoformat(sep=' ', timespec='seconds')

def human_bytes(num, suffix='B'):
    """Convert bytes to a human-readable string format with suffixes."""
    if num is None:
        return "N/A"
    try:
        num = float(num)
    except Exception:
        return str(num)
    for unit in ['','K','M','G','T','P','E','Z']:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Y{suffix}"

# -----------------------
# Monitoring backend
# -----------------------
class SystemSampler:
    """Collects snapshots of system statistics using psutil."""
    def __init__(self):
        self.prev_net = psutil.net_io_counters(pernic=False)
        self.prev_disk = psutil.disk_io_counters()
        self.lock = threading.Lock()

    def snapshot(self):
        """Return a dictionary snapshot of current system state, including CPU, memory, disk, and network data."""
        with self.lock:
            t = now_iso()
            # CPU info
            cpu_percent = psutil.cpu_percent(interval=None, percpu=False)
            percore = psutil.cpu_percent(interval=None, percpu=True)
            cpu_count = psutil.cpu_count(logical=True)
            cpu_freq = psutil.cpu_freq(percpu=False)
            load_avg = os.getloadavg() if hasattr(os, "getloadavg") else (0.0,0.0,0.0)

            # Memory info
            virtual = psutil.virtual_memory()
            swap = psutil.swap_memory()

            # Disk info
            partitions = []
            for p in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(p.mountpoint)
                except PermissionError:
                    usage = None
                partitions.append({
                    "device": p.device,
                    "mountpoint": p.mountpoint,
                    "fstype": p.fstype,
                    "opts": p.opts,
                    "usage": {
                        "total": usage.total if usage else None,
                        "used": usage.used if usage else None,
                        "free": usage.free if usage else None,
                        "percent": usage.percent if usage else None
                    }
                })
            disk_io = psutil.disk_io_counters()

            # Network info
            net_io = psutil.net_io_counters(pernic=False)

            # Processes (top 50)
            procs = []
            for p in psutil.process_iter(['pid','name','username','cpu_percent','memory_info','memory_percent','status']):
                try:
                    info = p.info
                    procs.append({
                        "pid": info.get('pid'),
                        "name": info.get('name'),
                        "username": info.get('username'),
                        "cpu_percent": info.get('cpu_percent'),
                        "memory_percent": info.get('memory_percent'),
                        "memory_rss": info['memory_info'].rss if info.get('memory_info') else None,
                        "status": info.get('status')
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            procs_sorted = sorted(procs, key=lambda x: (x.get('cpu_percent') or 0.0, x.get('memory_percent') or 0.0), reverse=True)[:50]

            # I/O rates (delta)
            time_interval = 1.0
            net_delta = {
                "bytes_sent_per_sec": (net_io.bytes_sent - self.prev_net.bytes_sent)/time_interval if self.prev_net else None,
                "bytes_recv_per_sec": (net_io.bytes_recv - self.prev_net.bytes_recv)/time_interval if self.prev_net else None,
            }
            disk_delta = {
                "read_bytes_per_sec": (disk_io.read_bytes - self.prev_disk.read_bytes)/time_interval if self.prev_disk else None,
                "write_bytes_per_sec": (disk_io.write_bytes - self.prev_disk.write_bytes)/time_interval if self.prev_disk else None,
            }

            # save previous
            self.prev_net = net_io
            self.prev_disk = disk_io

            snapshot = {
                "timestamp": t,
                "platform": {
                    "system": platform.system(),
                    "node": platform.node(),
                    "release": platform.release(),
                    "version": platform.version(),
                    "machine": platform.machine(),
                    "processor": platform.processor(),
                },
                "cpu": {
                    "total_percent": cpu_percent,
                    "per_core": percore,
                    "count": cpu_count,
                    "freq": cpu_freq._asdict() if cpu_freq else None,
                    "load_avg": load_avg
                },
                "memory": {
                    "virtual": virtual._asdict() if hasattr(virtual, "_asdict") else vars(virtual),
                    "swap": swap._asdict() if hasattr(swap, "_asdict") else vars(swap)
                },
                "disk": {
                    "partitions": partitions,
                    "io": disk_io._asdict() if hasattr(disk_io, "_asdict") else vars(disk_io)
                },
                "network": {
                    "io": net_io._asdict() if hasattr(net_io, "_asdict") else vars(net_io),
                    "rates": net_delta
                },
                "processes": procs_sorted
            }
            return snapshot

# -----------------------
# GUI Application
# -----------------------
class VanillaLOOKApp:
    def __init__(self, root):
        self.root = root
        root.title(f"{APP_NAME} {APP_VERSION}")
        self.sampler = SystemSampler()
        self.updating = True
        self.log_history = []
        self.logging_enabled = False
        self.log_lock = threading.Lock()

        self.cpu_history = []
        self.mem_history = []
        self.time_history = []

        self.queue = queue.Queue()

        self._create_widgets()
        self._start_background_sampler()
        self._schedule_ui_update()

    def _create_widgets(self):
        style = ttk.Style(self.root)
        style.theme_use('clam')

        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Take Snapshot", command=self.take_snapshot)
        file_menu.add_command(label="Export Logs (JSON)", command=self.export_logs)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About Vanilla LOOK", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        # Main layout
        main = ttk.Frame(self.root, padding=(8,8))
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main)
        right = ttk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Overview section
        overview = ttk.LabelFrame(left, text="Overview")
        overview.pack(fill=tk.X, padx=4, pady=4)

        self.cpu_label = ttk.Label(overview, text="CPU: --%")
        self.cpu_label.pack(anchor=tk.W, padx=6, pady=2)

        self.mem_label = ttk.Label(overview, text="Memory: --%")
        self.mem_label.pack(anchor=tk.W, padx=6, pady=2)

        btn_frame = ttk.Frame(overview)
        btn_frame.pack(fill=tk.X, padx=6, pady=6)
        self.snap_button = ttk.Button(btn_frame, text="Take Snapshot", command=self.take_snapshot)
        self.snap_button.pack(side=tk.LEFT, padx=2)
        self.toggle_logging_btn = ttk.Button(btn_frame, text="Start Logging", command=self.toggle_logging)
        self.toggle_logging_btn.pack(side=tk.LEFT, padx=2)
        self.export_btn = ttk.Button(btn_frame, text="Export Logs", command=self.export_logs)
        self.export_btn.pack(side=tk.LEFT, padx=2)

        # Charts
        charts_frame = ttk.Frame(left)
        charts_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.fig = Figure(figsize=(5,3), dpi=80)
        self.cpu_ax = self.fig.add_subplot(211)
        self.mem_ax = self.fig.add_subplot(212)
        self.fig.tight_layout(pad=1.0)
        self.canvas = FigureCanvasTkAgg(self.fig, master=charts_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Tabs for details
        nb = ttk.Notebook(right)
        nb.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Disk tab
        disk_tab = ttk.Frame(nb)
        nb.add(disk_tab, text="Disk")
        self.disk_tree = ttk.Treeview(disk_tab, columns=("mount","fstype","total","used","free","percent"), show='headings')
        for col, txt in [("mount","Mountpoint"),("fstype","FS"),("total","Total"),("used","Used"),("free","Free"),("percent","%")]:
            self.disk_tree.heading(col, text=txt)
            self.disk_tree.column(col, anchor=tk.W, width=100)
        self.disk_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Network tab
        net_tab = ttk.Frame(nb)
        nb.add(net_tab, text="Network")
        self.net_text = tk.Text(net_tab, height=8, wrap=tk.NONE)
        self.net_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Processes tab
        proc_tab = ttk.Frame(nb)
        nb.add(proc_tab, text="Processes")
        proc_ctrl = ttk.Frame(proc_tab)
        proc_ctrl.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(proc_ctrl, text="Search:").pack(side=tk.LEFT)
        self.proc_search = ttk.Entry(proc_ctrl)
        self.proc_search.pack(side=tk.LEFT, padx=4)
        self.proc_search.bind("<Return>", lambda e: self.refresh_processes())
        ttk.Button(proc_ctrl, text="Refresh", command=self.refresh_processes).pack(side=tk.LEFT, padx=4)
        ttk.Label(proc_ctrl, text="Sort by:").pack(side=tk.LEFT, padx=(8,2))
        self.sort_by = ttk.Combobox(proc_ctrl, values=["cpu","memory"], state="readonly", width=8)
        self.sort_by.set("cpu")
        self.sort_by.pack(side=tk.LEFT)
        ttk.Button(proc_ctrl, text="Kill Selected", command=self.kill_selected_process).pack(side=tk.RIGHT, padx=4)
        self.proc_tree = ttk.Treeview(proc_tab, columns=("pid","name","user","cpu","mem","rss","status"), show='headings')
        for col, txt in [("pid","PID"),("name","Name"),("user","User"),("cpu","CPU%"),("mem","Mem%"),("rss","RSS"),("status","Status")]:
            self.proc_tree.heading(col, text=txt)
            self.proc_tree.column(col, anchor=tk.W, width=80)
        self.proc_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Logs tab
        log_tab = ttk.Frame(nb)
        nb.add(log_tab, text="Logs")
        log_btn_frame = ttk.Frame(log_tab)
        log_btn_frame.pack(fill=tk.X, padx=4, pady=4)
        ttk.Button(log_btn_frame, text="Clear Logs", command=self.clear_logs).pack(side=tk.LEFT)
        ttk.Button(log_btn_frame, text="Save Logs to JSON", command=self.export_logs).pack(side=tk.LEFT, padx=4)
        self.log_listbox = tk.Listbox(log_tab, height=10)
        self.log_listbox.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.log_text = tk.Text(log_tab, height=12, wrap=tk.NONE)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.status_var = tk.StringVar(value="Ready")
        statusbar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        statusbar.pack(side=tk.BOTTOM, fill=tk.X)

    # ---------------- About dialog ----------------
    def show_about(self):
        about_window = Toplevel(self.root)
        about_window.title(f"About {APP_NAME}")
        about_window.geometry("400x250")
        about_window.resizable(False, False)
        ttk.Label(about_window, text=f"{APP_NAME} {APP_VERSION}", font=("Helvetica", 14, "bold")).pack(pady=10)
        ttk.Label(about_window, text="A comprehensive system monitor built with Python and Tkinter.", wraplength=360, justify=tk.CENTER).pack(pady=5)
        ttk.Label(about_window, text="Features include real-time charts, process management,\nsystem logging, and JSON export.", wraplength=360, justify=tk.CENTER).pack(pady=5)
        ttk.Label(about_window, text=f"Made with ❤️  by {AUTHOR}", font=("Helvetica", 11, "italic"), foreground="purple").pack(pady=10)
        ttk.Button(about_window, text="Close", command=about_window.destroy).pack(pady=15)

    # ---------------- background sampling ----------------
    def _start_background_sampler(self):
        def sampler_thread():
            while True:
                try:
                    snap = self.sampler.snapshot()
                    self.queue.put(snap)
                except Exception as e:
                    self.queue.put({"timestamp": now_iso(), "error": str(e)})
                time.sleep(1.0)
        threading.Thread(target=sampler_thread, daemon=True).start()

    def _schedule_ui_update(self):
        self._process_queue()
        self.root.after(UPDATE_INTERVAL_MS, self._schedule_ui_update)

    def _process_queue(self):
        processed = False
        while not self.queue.empty():
            snap = self.queue.get_nowait()
            self._apply_snapshot(snap)
            processed = True
        if not processed:
            pass

    # ---------------- snapshot handling ----------------
    def _apply_snapshot(self, s):
        if "error" in s:
            self.status_var.set("Sampler error: " + s["error"])
            return
        cpu_total = s['cpu']['total_percent']
        mem_percent = s['memory']['virtual']['percent']
        self.cpu_label.config(text=f"CPU: {cpu_total:.1f}% ({len(s['cpu']['per_core'])} cores)")
        self.mem_label.config(text=f"Memory: {mem_percent:.1f}% ({human_bytes(s['memory']['virtual']['used'])} used)")
        ts = time.time()
        self.time_history.append(ts)
        self.cpu_history.append(cpu_total)
        self.mem_history.append(mem_percent)
        if len(self.time_history) > CHART_POINTS:
            self.time_history = self.time_history[-CHART_POINTS:]
            self.cpu_history = self.cpu_history[-CHART_POINTS:]
            self.mem_history = self.mem_history[-CHART_POINTS:]
        self._update_charts()
        for i in self.disk_tree.get_children():
            self.disk_tree.delete(i)
        for p in s['disk']['partitions']:
            usage = p.get('usage')
            self.disk_tree.insert("", tk.END, values=(
                p.get('mountpoint'),
                p.get('fstype'),
                human_bytes(usage.get('total')) if usage else "N/A",
                human_bytes(usage.get('used')) if usage else "N/A",
                human_bytes(usage.get('free')) if usage else "N/A",
                f"{usage.get('percent')}%" if usage else "N/A"
            ))
        net = s['network']
        self.net_text.delete(1.0, tk.END)
        io = net['io']
        rates = net.get('rates') or {}
        self.net_text.insert(tk.END, f"Timestamp: {s['timestamp']}\n")
        self.net_text.insert(tk.END, f"Bytes Sent: {human_bytes(io['bytes_sent'])} (≈ {human_bytes(rates.get('bytes_sent_per_sec') or 0)}/s)\n")
        self.net_text.insert(tk.END, f"Bytes Recv: {human_bytes(io['bytes_recv'])} (≈ {human_bytes(rates.get('bytes_recv_per_sec') or 0)}/s)\n")
        self.net_text.insert(tk.END, f"Packets Sent: {io.get('packets_sent')}\n")
        self.net_text.insert(tk.END, f"Packets Recv: {io.get('packets_recv')}\n")
        self.latest_snapshot = s
        self.refresh_processes(use_latest=True)
        if self.logging_enabled:
            with self.log_lock:
                self.log_history.append(s)
                self.log_listbox.insert(tk.END, f"{s['timestamp']}  CPU {cpu_total:.1f}%  MEM {mem_percent:.1f}%")
        self.status_var.set(f"Last update: {s['timestamp']}")

    def _update_charts(self):
        self.cpu_ax.clear()
        self.mem_ax.clear()
        if self.time_history:
            x = list(range(len(self.cpu_history)))
            self.cpu_ax.plot(x, self.cpu_history, label="CPU %")
            self.mem_ax.plot(x, self.mem_history, label="Memory %", color="orange")
            self.cpu_ax.legend()
            self.mem_ax.legend()
            self.cpu_ax.set_ylim(0, 100)
            self.mem_ax.set_ylim(0, 100)
        else:
            self.cpu_ax.text(0.5, 0.5, "No data yet", ha="center", va="center")
        self.canvas.draw_idle()

    # ---------------- user actions ----------------
    def take_snapshot(self):
        s = getattr(self, "latest_snapshot", None)
        if not s:
            messagebox.showwarning(APP_NAME, "No data yet to snapshot.")
            return
        filename = f"snapshot_{int(time.time())}.json"
        with open(filename, "w") as f:
            json.dump(s, f, indent=2)
        messagebox.showinfo(APP_NAME, f"Snapshot saved to {filename}")
        self.status_var.set(f"Snapshot saved: {filename}")

    def toggle_logging(self):
        self.logging_enabled = not self.logging_enabled
        self.toggle_logging_btn.config(text="Stop Logging" if self.logging_enabled else "Start Logging")
        self.status_var.set("Logging started" if self.logging_enabled else "Logging stopped")

    def export_logs(self):
        if not self.log_history:
            messagebox.showwarning(APP_NAME, "No logs to export.")
            return
        fname = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON Files","*.json")])
        if not fname:
            return
        with open(fname, "w") as f:
            json.dump(self.log_history, f, indent=2)
        messagebox.showinfo(APP_NAME, f"Logs exported to {fname}")
        self.status_var.set(f"Logs exported: {fname}")

    def clear_logs(self):
        self.log_history.clear()
        self.log_listbox.delete(0, tk.END)
        self.log_text.delete(1.0, tk.END)
        self.status_var.set("Logs cleared")

    def refresh_processes(self, use_latest=False):
        if use_latest and hasattr(self, "latest_snapshot"):
            snap = self.latest_snapshot
            plist = snap['processes']
        else:
            snap = self.sampler.snapshot()
            plist = snap['processes']
        key = self.sort_by.get()
        if key == "memory":
            plist.sort(key=lambda x: (x['memory_percent'] or 0), reverse=True)
        else:
            plist.sort(key=lambda x: (x['cpu_percent'] or 0), reverse=True)
        query = self.proc_search.get().strip().lower()
        if query:
            plist = [p for p in plist if query in (p['name'] or "").lower()]
        for i in self.proc_tree.get_children():
            self.proc_tree.delete(i)
        for p in plist:
            self.proc_tree.insert("", tk.END, values=(
                p['pid'], p['name'], p.get('username'), f"{p.get('cpu_percent',0):.1f}", f"{p.get('memory_percent',0):.1f}", human_bytes(p.get('memory_rss')), p.get('status')
            ))

    def kill_selected_process(self):
        sel = self.proc_tree.selection()
        if not sel:
            messagebox.showwarning(APP_NAME, "Select a process to kill.")
            return
        pid = int(self.proc_tree.item(sel[0],'values')[0])
        name = self.proc_tree.item(sel[0],'values')[1]
        if messagebox.askyesno(APP_NAME, f"Terminate process {name} (PID {pid})?"):
            try:
                psutil.Process(pid).terminate()
                messagebox.showinfo(APP_NAME, f"Process {name} (PID {pid}) terminated.")
                self.refresh_processes()
            except Exception as e:
                messagebox.showerror(APP_NAME, f"Error: {e}")

# ---------------- main entry ----------------
if __name__ == "__main__":
    root = tk.Tk()
    app = VanillaLOOKApp(root)
    root.geometry("1200x700")
    root.mainloop()
