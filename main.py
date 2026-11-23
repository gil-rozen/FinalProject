import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import queue
import os
from state import HarnessState
from llm_client import OllamaClient
from agents.manager_agent import ManagerAgent
from tools.sandbox import SandboxRunner
from config import OLLAMA_MODEL

class HarnessGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"Autonomous Multi-Agent Game Harness (Ollama: {OLLAMA_MODEL})")
        self.root.geometry("1150x750")
        self.root.configure(bg="#1e1e2e")

        self.state_queue = queue.Queue()
        self.latest_state: HarnessState = None
        self.displayed_log_count = 0

        self._setup_styles()
        self._build_layout()
        self.root.after(100, self._poll_queue)

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#1e1e2e")
        style.configure("TLabel", background="#1e1e2e", foreground="#cdd6f4", font=("Segoe UI", 10, "bold"))
        style.configure("TButton", background="#89b4fa", foreground="#11111b", font=("Segoe UI", 10, "bold"), padding=6)

    def _build_layout(self):
        # Top Control Bar
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill=tk.X)

        ttk.Label(top_frame, text="Game Request:").pack(side=tk.LEFT, padx=(0, 8))

        self.prompt_entry = tk.Entry(
            top_frame, font=("Segoe UI", 11), bg="#313244", fg="#cdd6f4",
            insertbackground="#cdd6f4", relief=tk.FLAT
        )
        self.prompt_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8, ipady=5)
        self.prompt_entry.insert(0, "Create a playable Snake game with score tracking")

        self.run_btn = ttk.Button(top_frame, text="Run Autonomous Agents", command=self.start_pipeline)
        self.run_btn.pack(side=tk.LEFT, padx=5)

        self.launch_btn = ttk.Button(top_frame, text="Launch Verified Game", command=self.launch_game, state=tk.DISABLED)
        self.launch_btn.pack(side=tk.LEFT, padx=5)

        # Main Split Pane
        paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg="#181825", sashwidth=6)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Left Panel: Sub-Agent Telemetry & Logs
        left_frame = ttk.Frame(paned)
        ttk.Label(left_frame, text="Sub-Agent Activity & Telemetry Stream").pack(anchor=tk.W, pady=(0, 5))

        self.log_box = scrolledtext.ScrolledText(
            left_frame, bg="#181825", fg="#a6adc8", font=("Consolas", 10), state=tk.DISABLED, wrap=tk.WORD
        )
        self.log_box.pack(fill=tk.BOTH, expand=True)
        self.log_box.tag_config("INFO", foreground="#89b4fa")
        self.log_box.tag_config("SUCCESS", foreground="#a6e3a1")
        self.log_box.tag_config("WARNING", foreground="#f9e2af")
        self.log_box.tag_config("ERROR", foreground="#f38ba8")
        paned.add(left_frame, width=550)

        # Right Panel: Live Code & Rules Notebook
        right_frame = ttk.Frame(paned)
        notebook = ttk.Notebook(right_frame)
        notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 1: Generated Python Code
        code_tab = ttk.Frame(notebook)
        self.code_box = scrolledtext.ScrolledText(
            code_tab, bg="#11111b", fg="#cdd6f4", font=("Consolas", 10), wrap=tk.NONE
        )
        self.code_box.pack(fill=tk.BOTH, expand=True)
        notebook.add(code_tab, text="Generated Game Code")

        # Tab 2: Wikipedia Rules & Architecture Plan
        rules_tab = ttk.Frame(notebook)
        self.rules_box = scrolledtext.ScrolledText(
            rules_tab, bg="#11111b", fg="#cdd6f4", font=("Segoe UI", 10), wrap=tk.WORD
        )
        self.rules_box.pack(fill=tk.BOTH, expand=True)
        notebook.add(rules_tab, text="Rules & Architecture Plan")

        paned.add(right_frame, width=580)

    def start_pipeline(self):
        prompt = self.prompt_entry.get().strip()
        if not prompt:
            messagebox.showwarning("Input Required", "Please enter a game description.")
            return

        self.run_btn.config(state=tk.DISABLED)
        self.launch_btn.config(state=tk.DISABLED)
        self.displayed_log_count = 0

        self.log_box.config(state=tk.NORMAL)
        self.log_box.delete("1.0", tk.END)
        self.log_box.config(state=tk.DISABLED)
        self.code_box.delete("1.0", tk.END)
        self.rules_box.delete("1.0", tk.END)

        # Run agent workflow on a background daemon thread so Tkinter doesn't freeze
        worker = threading.Thread(target=self._agent_worker, args=(prompt,), daemon=True)
        worker.start()

    def _agent_worker(self, prompt: str):
        llm = OllamaClient()
        manager = ManagerAgent(llm=llm, ui_callback=self._enqueue_state)
        final_state = manager.execute_workflow(prompt)
        if not final_state.is_complete and final_state.current_code:
            failed_path = os.path.abspath("failed_candidate.py")
            with open(failed_path, "w", encoding="utf-8") as f:
                f.write(final_state.current_code)
            last_err = final_state.syntax_error if not final_state.syntax_valid else final_state.runtime_error
            summary_msg = (
                f"Verification failed. Saved unverified candidate code to '{failed_path}' for inspection "
                f"instead of launching play_game.py.\nError Summary:\n{last_err or 'Unknown verification failure.'}"
            )
            print(summary_msg)
            final_state.add_log("Manager Agent", summary_msg, "WARNING")
        self._enqueue_state(final_state)

    def _enqueue_state(self, state: HarnessState):
        self.state_queue.put(state)

    def _poll_queue(self):
        while not self.state_queue.empty():
            state: HarnessState = self.state_queue.get_nowait()
            self.latest_state = state
            self._update_ui(state)
        self.root.after(100, self._poll_queue)

    def _update_ui(self, state: HarnessState):
        # Append new logs
        new_logs = state.logs[self.displayed_log_count:]
        if new_logs:
            self.log_box.config(state=tk.NORMAL)
            for entry in new_logs:
                header = f"[{entry.timestamp}] [{entry.agent_name}]\n"
                body = f"{entry.message}\n{'-'*50}\n"
                self.log_box.insert(tk.END, header, entry.level)
                self.log_box.insert(tk.END, body)
            self.log_box.see(tk.END)
            self.log_box.config(state=tk.DISABLED)
            self.displayed_log_count = len(state.logs)

        # Update Code Viewer
        if state.current_code:
            self.code_box.delete("1.0", tk.END)
            self.code_box.insert(tk.END, state.current_code)

        # Update Rules & Plan Viewer
        if state.summarized_rules or state.development_plan:
            self.rules_box.delete("1.0", tk.END)
            combined = (
                f"=== WIKIPEDIA RULES SPECIFICATION ===\n{state.summarized_rules}\n\n"
                f"=== MANAGER ARCHITECTURAL PLAN ===\n{state.development_plan}"
            )
            self.rules_box.insert(tk.END, combined)

        # Check completion status to re-enable buttons
        if state.is_complete or state.iteration >= 5 or any(l.level == "ERROR" and "Critical" in l.message for l in state.logs):
            self.run_btn.config(state=tk.NORMAL)
            if state.is_complete and state.current_code:
                self.launch_btn.config(state=tk.NORMAL)

    def launch_game(self):
        if not self.latest_state or not self.latest_state.current_code:
            return
        if not self.latest_state.is_complete:
            failed_path = os.path.abspath("failed_candidate.py")
            with open(failed_path, "w", encoding="utf-8") as f:
                f.write(self.latest_state.current_code)
            last_err = self.latest_state.syntax_error if not self.latest_state.syntax_valid else self.latest_state.runtime_error
            print(f"Cannot launch unverified game. Candidate saved to {failed_path}.\nError:\n{last_err}")
            return
        SandboxRunner.launch_interactive(self.latest_state.current_code)

if __name__ == "__main__":
    root = tk.Tk()
    app = HarnessGUI(root)
    root.mainloop()
