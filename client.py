#!/usr/bin/env python3
import threading, time, webbrowser, platform, subprocess, socket, io, contextlib
import tkinter as tk
from tkinter import ttk, messagebox
import requests
from datetime import datetime, timedelta
from urllib.parse import urlparse

# Try to import GPUtil for GPU info; if not available, use None.
try:
    import GPUtil
except ImportError:
    GPUtil = None

# Global variable to store the parsed expiry in UTC (microseconds set to 0)
current_expiry_dt = None

########################################################################
# Part 1: Execution Agent (Flask-based) in a Background Thread
########################################################################
def run_execution_agent():
    from flask import Flask, request, jsonify
    import os, io, contextlib

    app = Flask(__name__)
    # Use API token from environment if needed (not enforced here)
    API_TOKEN = os.getenv("GPU_AGENT_API_TOKEN", "RIwBCAdOIfC_ubOcnZ1zluUJKTkWdl7s")
    connected = True

    @app.route("/update_connection", methods=["POST"])
    def update_connection():
        nonlocal connected
        data = request.get_json() or {}
        connected = data.get("connected", True)
        return jsonify({"message": "Connection state updated", "connected": connected}), 200

    @app.route("/execute_code", methods=["POST"])
    def execute_code_endpoint():
        if not connected:
            return jsonify({"error": "GPU is disconnected. Code execution not allowed."}), 400
        data = request.get_json() or {}
        code = data.get("code", "")
        if not code:
            return jsonify({"error": "No code provided"}), 400
        output_buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(output_buffer):
                exec(code, {})  # Warning: using exec can be unsafe.
            output = output_buffer.getvalue()
            return jsonify({"message": "Code executed", "output": output}), 200
        except Exception as e:
            return jsonify({"error": "Code execution failed", "details": str(e)}), 400

    app.run(host="0.0.0.0", port=6000, threaded=True)

# Start execution agent in a daemon thread.
threading.Thread(target=run_execution_agent, daemon=True).start()

########################################################################
# Part 2: Host Agent & GUI
########################################################################

DEFAULT_SERVER = "https://gpushare.srimanhq.com"
DEFAULT_TOKEN  = "replace api token here."

# Global flags and variables.
stop_event = threading.Event()
agent_running = False         # True when host agent is running.
heartbeat_state = False
registration_time = None      # Time when registration occurs.
global_gpu_id = None          # Will be set after registration.
gpu_idle_state = False        # False = GPU active; True = GPU idle.

# Host Agent Loop: Registers the GPU and sends heartbeat updates.
def host_agent_loop(server, token, status_var):
    global registration_time, global_gpu_id
    registration_time = time.time()
    status_var.set("🟢 Host Agent running...")

    # Build GPU info payload.
    gpu_info = {}
    try:
        if GPUtil:
            gpus = GPUtil.getGPUs()
            if not gpus:
                gpu_info = {"error": "No GPUs detected"}
            else:
                gpu = gpus[0]
                gpu_info = {
                    "name": gpu.name,
                    "id": gpu.id,
                    "memory_total": gpu.memoryTotal,
                    "memory_used": gpu.memoryUsed,
                    "memory_free": gpu.memoryFree,
                    "driver": gpu.driver,
                    "uuid": gpu.uuid,
                    "host_address": socket.gethostbyname(socket.gethostname())
                }
        else:
            gpu_info = {"error": "GPUtil not available"}
    except Exception as e:
        gpu_info = {"error": f"Error retrieving GPU info: {e}"}

    # Register GPU with the server.
    try:
        resp = requests.post(
            f"{server.rstrip('/')}/api/register_gpu",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"gpu_info": gpu_info},
            timeout=5
        )
        resp.raise_for_status()
        global_gpu_id = resp.json().get("gpu_id")
    except Exception as e:
        status_var.set(f"⚠️ Registration error: {e}")
        return

    # Send heartbeat updates every 20 seconds.
    while not stop_event.is_set():
        elapsed = int(time.time() - registration_time)
        try:
            r2 = requests.post(
                f"{server.rstrip('/')}/api/update_gpu_stats",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"gpu_id": global_gpu_id, "usage_time": elapsed},
                timeout=5
            )
            r2.raise_for_status()
            status_var.set(f"Heartbeat sent (uptime {elapsed}s)")
        except Exception as e:
            status_var.set(f"⚠️ Heartbeat error: {e}")
        time.sleep(20)

# System-level Ping: Checks server connectivity.
def ping_server_action():
    server = server_var.get().strip()
    parsed = urlparse(server)
    hostname = parsed.hostname
    if not hostname:
        messagebox.showerror("Ping Error", "Invalid server URL.")
        return
    count_flag = "-n" if platform.system().lower() == "windows" else "-c"
    try:
        result = subprocess.run(["ping", count_flag, "1", hostname],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            server_status_label.config(text="Online", foreground="green")
        else:
            server_status_label.config(text="Offline", foreground="red")
    except Exception as e:
        messagebox.showerror("Ping Error", str(e))

# Execution Agent Caller: Sends code to the local execution agent including current API token.
def execute_code_remote(code: str) -> str:
    token = token_var.get().strip()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        r = requests.post("http://localhost:6000/execute_code", json={"code": code}, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data.get("output", data.get("message", "No output returned."))
    except Exception as e:
        return f"Error: {e}"

# Execution Agent Window: Allows the user to enter and execute Python code.
def execute_code_action():
    exec_win = tk.Toplevel(root)
    exec_win.title("Execution Agent")
    exec_win.geometry("500x400")
    
    ttk.Label(exec_win, text="Enter Python code to execute:", font=("Helvetica", 10)).pack(padx=10, pady=(10,0))
    code_text = tk.Text(exec_win, height=10)
    code_text.pack(fill="x", padx=10, pady=5)
    # Insert placeholder code.
    code_text.insert("1.0", 'print("Hello :)")')
    
    # Create a frame for the Run Code button so it's clearly separated.
    btn_frame = ttk.Frame(exec_win)
    btn_frame.pack(pady=5)
    run_btn = ttk.Button(btn_frame, text="Run Code", command=lambda: run_code())
    run_btn.pack()
    
    ttk.Label(exec_win, text="(Only Python code is accepted for testing.)", font=("Helvetica", 8, "italic")).pack(pady=(0,5))
    
    ttk.Label(exec_win, text="Output:", font=("Helvetica", 10)).pack(padx=10, pady=(10,0))
    output_text = tk.Text(exec_win, height=10)
    output_text.pack(expand=True, fill="both", padx=10, pady=5)
    output_text.config(state="disabled")
    
    def run_code():
        code = code_text.get("1.0", "end-1c")
        if not code.strip():
            messagebox.showwarning("Input Error", "Please enter some Python code to execute.")
            return
        out = execute_code_remote(code)
        output_text.config(state="normal")
        output_text.delete("1.0", tk.END)
        output_text.insert("1.0", out)
        output_text.config(state="disabled")
    
    run_btn = ttk.Button(exec_win, text="Run Code", command=run_code)
    run_btn.pack(pady=5)
    ttk.Label(exec_win, text="(Only Python code is accepted for now.)", font=("Helvetica", 8, "italic")).pack(pady=(0,5))

# Validate: Converts the server's expiry time (UTC) to a neat UTC display.
def validate():
    server = server_var.get().strip()
    token = token_var.get().strip()
    status_var.set("…validating…")
    def _validate():
        global current_expiry_dt
        try:
            r = requests.get(
                f"{server.rstrip('/')}/api/token_info",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5
            )
            r.raise_for_status()
            info = r.json()
            expiry = info.get("expires_at")
            if expiry:
                if expiry.endswith("Z"):
                    expiry = expiry[:-1] + "+00:00"
                try:
                    expiry_dt = datetime.fromisoformat(expiry).replace(microsecond=0)
                    formatted_expiry = expiry_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                    current_expiry_dt = expiry_dt
                except Exception:
                    formatted_expiry = expiry
                    current_expiry_dt = None
            else:
                formatted_expiry = "N/A"
                current_expiry_dt = None
            status_var.set("✅ Valid! Token is valid.")
            expiry_var.set(f"Expiry: {formatted_expiry}")
            server_entry.config(state="disabled")
            token_entry.config(state="disabled")
            validate_btn.config(state="disabled")
            start_btn.config(state="normal")
        except Exception as e:
            status_var.set(f"❌ Validation failed: {e}")
    threading.Thread(target=_validate, daemon=True).start()

def start_agent():
    global agent_running
    start_btn.config(state="disabled")
    stop_btn.config(state="normal")
    stop_event.clear()
    agent_running = True
    threading.Thread(
        target=host_agent_loop,
        args=(server_var.get(), token_var.get(), status_var),
        daemon=True
    ).start()

def stop_agent():
    global agent_running
    stop_event.set()
    agent_running = False
    stop_btn.config(state="disabled")
    start_btn.config(state="normal")
    status_var.set("🛑 Agents stopped.")
    server_entry.config(state="normal")
    token_entry.config(state="normal")
    validate_btn.config(state="normal")

def show_gpu_details():
    details = ""
    try:
        if GPUtil:
            gpus = GPUtil.getGPUs()
            if gpus:
                g = gpus[0]
                details = (
                    f"Name: {g.name}\n"
                    f"ID: {g.id}\n"
                    f"Memory Total: {g.memoryTotal}\n"
                    f"Memory Used: {g.memoryUsed}\n"
                    f"Memory Free: {g.memoryFree}\n"
                    f"Driver: {g.driver}\n"
                    f"UUID: {g.uuid}\n"
                    f"Host: {socket.gethostbyname(socket.gethostname())}\n"
                )
            else:
                details = "No GPU detected."
        else:
            details = "GPUtil is missing. (pip install gputil)"
    except Exception as ex:
        details = f"Error retrieving GPU info: {ex}"
    pop = tk.Toplevel(root)
    pop.title("GPU Details")
    pop.geometry("400x300")
    txt = tk.Text(pop, wrap="word")
    txt.insert("1.0", details)
    txt.config(state="disabled")
    txt.pack(expand=True, fill="both", padx=10, pady=10)
    ttk.Button(pop, text="Close", command=pop.destroy).pack(pady=(0,10))

def toggle_gpu_idle_action():
    global gpu_idle_state
    server = server_var.get().strip()
    token = token_var.get().strip()
    if not global_gpu_id:
        status_var.set("No GPU ID available.")
        return
    try:
        new_idle = not gpu_idle_state
        r = requests.post(
            f"{server.rstrip('/')}/api/set_gpu_idle/{global_gpu_id}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"idle": new_idle},
            timeout=5
        )
        r.raise_for_status()
        data = r.json()
        status_var.set(data.get("message", "GPU idle state changed."))
        gpu_idle_state = new_idle
        toggle_gpu_idle_btn.config(text=("Set GPU Active" if gpu_idle_state else "Set GPU Idle"))
    except Exception as e:
        status_var.set(f"Error toggling GPU idle: {e}")

def refresh_token_action():
    global current_expiry_dt
    server = server_var.get().strip()
    token = token_var.get().strip()
    try:
        now = datetime.now().astimezone()
        if current_expiry_dt is not None and (current_expiry_dt - now) > timedelta(hours=1):
            answer = messagebox.askyesno("Confirm Refresh",
                    f"Your token has {(current_expiry_dt - now)} remaining. Refreshing now will reset the expiry to 1 hour from now.\nAre you sure?")
            if not answer:
                status_var.set("Token refresh cancelled.")
                return
    except Exception:
        pass
    try:
        r = requests.post(
            f"{server.rstrip('/')}/api/refresh_token",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=5
        )
        r.raise_for_status()
        data = r.json()
        new_token = data.get("token")
        if new_token:
            token_var.set(new_token)
            status_var.set("Token refreshed.")
            refreshed_expiry = data.get("expires_at", "N/A")
            if refreshed_expiry.endswith("Z"):
                refreshed_expiry = refreshed_expiry[:-1] + "+00:00"
            try:
                expiry_dt = datetime.fromisoformat(refreshed_expiry).replace(microsecond=0)
                formatted_expiry = expiry_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                current_expiry_dt = expiry_dt
            except Exception:
                formatted_expiry = refreshed_expiry
                current_expiry_dt = None
            expiry_var.set(f"Expiry: {formatted_expiry}")
        else:
            status_var.set("Refresh token error: no new token returned.")
    except Exception as e:
        status_var.set(f"Error refreshing token: {e}")

def kill_token_action():
    answer = messagebox.askyesno(
        "Kill Token Confirmation",
        "If you think your token is leaked, this will kill your current API token.\nYou can always generate a new API Key.\nContinue?"
    )
    if not answer:
        return
    server = server_var.get().strip()
    token = token_var.get().strip()
    try:
        r = requests.post(
            f"{server.rstrip('/')}/api/revoke_token",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=5
        )
        r.raise_for_status()
        status_var.set("Token revoked.")
        token_var.set("")
        kill_token_btn.config(state="disabled")
        refresh_token_btn.config(state="disabled")
        toggle_gpu_idle_btn.config(state="disabled")
    except Exception as e:
        status_var.set(f"Error killing token: {e}")

def open_link(url: str):
    webbrowser.open(url)

def update_heartbeat():
    global heartbeat_state
    if agent_running and not stop_event.is_set():
        heartbeat_state = not heartbeat_state
        heartbeat_label.config(foreground="green" if heartbeat_state else "grey")
    else:
        heartbeat_label.config(foreground="grey")
    root.after(1000, update_heartbeat)

def update_uptime():
    if registration_time is not None:
        elapsed = int(time.time() - registration_time)
        uptime_var.set(f"Uptime: {elapsed} seconds")
    else:
        uptime_var.set("Uptime: 0 seconds")
    root.after(1000, update_uptime)

########################################################################
# Build Main GUI
########################################################################
root = tk.Tk()
root.title("GPUShare Agent Controller + Execution Agent")
root.update_idletasks()

win_width, win_height = 640, 480
x = (root.winfo_screenwidth() // 2) - (win_width // 2)
y = (root.winfo_screenheight() // 2) - (win_height // 2)
root.geometry(f"{win_width}x{win_height}+{x}+{y}")
root.resizable(False, False)

style = ttk.Style(root)
try:
    style.theme_use("clam")
    style.configure("Green.TButton", foreground="white", background="green")
    style.configure("Red.TButton", foreground="white", background="red")
except:
    pass

main_frame = ttk.Frame(root, padding=15)
main_frame.pack(fill="both", expand=True)

title_lbl = ttk.Label(main_frame, text="GPUShare Agent Controller", font=("Helvetica", 16, "bold"))
title_lbl.pack(pady=(0,10))

# Server Row (Grid Layout)
server_row = ttk.Frame(main_frame)
server_row.pack(pady=3, fill="x")
server_row.columnconfigure(1, weight=1)
ttk.Label(server_row, text="Server URL:", font=("Helvetica", 10)).grid(row=0, column=0, sticky="e", padx=5)
server_var = tk.StringVar(value=DEFAULT_SERVER)
server_entry = ttk.Entry(server_row, textvariable=server_var, width=35)
server_entry.grid(row=0, column=1, sticky="we", padx=5)
ping_btn = ttk.Button(server_row, text="Ping Server", command=ping_server_action)
ping_btn.grid(row=0, column=2, padx=5)
server_status_label = ttk.Label(server_row, text="Unknown", font=("Helvetica", 10))
server_status_label.grid(row=0, column=3, padx=5)

# API Token Row (Grid Layout)
token_row = ttk.Frame(main_frame)
token_row.pack(pady=3, fill="x")
token_row.columnconfigure(1, weight=1)
ttk.Label(token_row, text="API Token:", font=("Helvetica", 10)).grid(row=0, column=0, sticky="e", padx=5)
token_var = tk.StringVar(value=DEFAULT_TOKEN)
token_entry = ttk.Entry(token_row, textvariable=token_var, width=35, show="*")
token_entry.grid(row=0, column=1, sticky="we", padx=5)
validate_btn = ttk.Button(token_row, text="Validate", command=validate)
validate_btn.grid(row=0, column=2, padx=5)

# Heartbeat + Uptime Row
hb_frame = ttk.Frame(main_frame)
hb_frame.pack(pady=8)
heartbeat_label = ttk.Label(hb_frame, text="●", font=("Helvetica", 20), foreground="grey")
heartbeat_label.pack(side="left", padx=8)
heartbeat_text = ttk.Label(hb_frame, text="Heartbeat", font=("Helvetica", 10))
heartbeat_text.pack(side="left", padx=8)
uptime_var = tk.StringVar(value="Uptime: 0 seconds")
uptime_label = ttk.Label(hb_frame, textvariable=uptime_var, font=("Helvetica", 10))
uptime_label.pack(side="left", padx=8)

# Status Row
status_frame = ttk.Frame(main_frame)
status_frame.pack(pady=3, fill="x")
ttk.Label(status_frame, text="Status:", font=("Helvetica", 10)).pack(side="left", padx=5)
status_var = tk.StringVar(value="Idle")
ttk.Label(status_frame, textvariable=status_var, font=("Helvetica", 10)).pack(side="left", padx=5)

# Expiry Row
expiry_frame = ttk.Frame(main_frame)
expiry_frame.pack(pady=3, fill="x")
ttk.Label(expiry_frame, text="Expiry:", font=("Helvetica", 10)).pack(side="left", padx=5)
expiry_var = tk.StringVar(value="Expiry: N/A")
ttk.Label(expiry_frame, textvariable=expiry_var, font=("Helvetica", 10)).pack(side="left", padx=5)

# Agent Control Row
agent_ctrl_frame = ttk.Frame(main_frame)
agent_ctrl_frame.pack(pady=8)
start_btn = ttk.Button(agent_ctrl_frame, text="Start Host Agent", command=start_agent, state="disabled")
stop_btn = ttk.Button(agent_ctrl_frame, text="Stop Agents", command=stop_agent, state="disabled")
start_btn.pack(side="left", padx=5)
stop_btn.pack(side="left", padx=5)

# GPU Details Button
gpu_btn = ttk.Button(main_frame, text="Show GPU Details", command=show_gpu_details)
gpu_btn.pack(pady=5)

# Admin / Owner Actions Row (5 options in one line)
admin_frame = ttk.Frame(main_frame)
admin_frame.pack(pady=8)
toggle_gpu_idle_btn = ttk.Button(admin_frame, text="Set GPU Idle", command=toggle_gpu_idle_action)
toggle_gpu_idle_btn.pack(side="left", padx=4)
list_devices_btn = ttk.Button(admin_frame, text="List Devices", 
    command=lambda: open_link(f"{server_var.get().rstrip('/')}/my_gpu"))
list_devices_btn.pack(side="left", padx=4)
get_api_btn = ttk.Button(admin_frame, text="Get API Key",
    command=lambda: open_link(f"{server_var.get().rstrip('/')}/manage_token"))
get_api_btn.pack(side="left", padx=4)
refresh_token_btn = ttk.Button(admin_frame, text="Refresh Token", command=refresh_token_action, style="Green.TButton")
refresh_token_btn.pack(side="left", padx=4)
kill_token_btn = ttk.Button(admin_frame, text="Kill Token", command=kill_token_action, style="Red.TButton")
kill_token_btn.pack(side="left", padx=4)

# Execution Agent Button Row
exec_frame = ttk.Frame(main_frame)
exec_frame.pack(pady=5)
exec_btn = ttk.Button(exec_frame, text="Execute Code", command=execute_code_action)
exec_btn.pack()

# Bottom Brand Row
brand_frame = ttk.Frame(main_frame)
brand_frame.pack(side="bottom", pady=5)
ttk.Button(brand_frame, text="GitHub", command=lambda: open_link("https://github.com/Srimany123/gpushare")).pack(side="left", padx=5)
ttk.Button(brand_frame, text="PyPI", command=lambda: open_link("https://pypi.org/project/gpushare")).pack(side="left", padx=5)
ttk.Button(brand_frame, text="Version", command=lambda: messagebox.showinfo("Version", "gpushare client version: 1.0.0")).pack(side="left", padx=5)

def periodic_updates():
    update_heartbeat()
    update_uptime()

periodic_updates()
root.mainloop()
