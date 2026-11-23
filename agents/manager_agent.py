import json
import re
from typing import Callable, List, Dict, Tuple
from config import MAX_REPAIR_ITERATIONS
from state import HarnessState
from llm_client import OllamaClient
from agents.base_agent import BaseAgent
from agents.research_agent import ResearchAgent
from agents.coder_agent import CoderAgent
from agents.syntax_agent import SyntaxAgent
from agents.executor_agent import ExecutorAgent
from tools.ast_validator import ASTMerger

CANVAS_ARCADE_SCAFFOLD = '''import tkinter as tk
import random
import math

CANVAS_WIDTH = 600
CANVAS_HEIGHT = 400


class ArcadeGame:
    def __init__(self, root):
        self.root = root
        self.master = root
        self.root.title("{game_name}")
        self.root.resizable(False, False)

        self.score = 0
        self.score1 = 0
        self.score2 = 0
        self.game_over = False
        self.pressed_keys = set()

        self.score_label = tk.Label(
            self.root,
            text="Score: 0  |  Press 'R' to Restart",
            font=("Arial", 14, "bold"),
            bg="#1e1e2e",
            fg="white",
            pady=6
        )
        self.score_label.pack(fill=tk.X)

        self.canvas = tk.Canvas(
            self.root,
            width=CANVAS_WIDTH,
            height=CANVAS_HEIGHT,
            bg="black",
            highlightthickness=0
        )
        self.canvas.pack()

        self.setup_game()
        self.setup_controls()

    def _to_bbox(self, obj):
        if isinstance(obj, int):
            c = self.canvas.coords(obj)
            if c and len(c) >= 4:
                return c[:4]
            if c and len(c) == 2:
                return [c[0] - 5, c[1] - 5, c[0] + 5, c[1] + 5]
            return None
        if isinstance(obj, (tuple, list)):
            if len(obj) == 4 and all(isinstance(v, (int, float)) for v in obj):
                return list(obj)
            if len(obj) == 2 and all(isinstance(v, (int, float)) for v in obj):
                return [obj[0], obj[1], obj[0], obj[1]]
        return None

    def check_collision(self, id1, id2):
        try:
            if isinstance(id2, (list, tuple, set)) and not (
                len(id2) in (2, 4) and all(isinstance(v, (int, float)) for v in id2)
            ):
                return any(self.check_collision(id1, item) for item in id2)
            c1 = self._to_bbox(id1)
            c2 = self._to_bbox(id2)
            if not c1 or not c2:
                return False
            return not (c1[2] < c2[0] or c1[0] > c2[2] or c1[3] < c2[1] or c1[1] > c2[3])
        except Exception:
            return False

    def setup_controls(self):
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.bind("<KeyRelease>", self.on_key_release)
        self.root.after(25, self.game_loop)

    def on_key_press(self, event):
        self.pressed_keys.add(event.keysym)
        if event.keysym in ("r", "R"):
            self.reset_game()
        else:
            self.handle_key(event.keysym)

    def on_key_release(self, event):
        self.pressed_keys.discard(event.keysym)

    def game_loop(self):
        if not self.game_over:
            self.update_game()
        self.root.after(25, self.game_loop)

    def setup_game(self):
        pass

    def update_game(self):
        pass

    def handle_key(self, key):
        return

    def reset_game(self):
        self.score = 0
        self.score1 = 0
        self.score2 = 0
        self.game_over = False
        self.setup_game()


if __name__ == "__main__":
    root = tk.Tk()
    app = ArcadeGame(root)
    root.mainloop()
'''

WIDGET_GRID_SCAFFOLD = '''import tkinter as tk
from tkinter import messagebox
import random
import math


class WidgetGridApp:
    def __init__(self, root):
        self.root = root
        self.master = root
        self.root.title("{game_name}")
        self.root.geometry("480x540")

        self.score = 0
        self.game_over = False
        self.current_input = ""
        self.display_var = tk.StringVar(value="")

        self.display_label = tk.Label(
            self.root,
            textvariable=self.display_var,
            font=("Arial", 18, "bold"),
            bg="#1e1e2e",
            fg="white",
            anchor="center",
            padx=12,
            pady=12,
            relief=tk.SUNKEN,
            wraplength=440
        )
        self.display_label.pack(fill=tk.X, padx=8, pady=8)

        self.grid_frame = tk.Frame(self.root)
        self.grid_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self.setup_ui()
        self._configure_grid_weights()
        self.setup_controls()

    def _configure_grid_weights(self):
        try:
            cols, rows = self.grid_frame.grid_size()
            for r in range(rows):
                self.grid_frame.grid_rowconfigure(r, weight=1)
            for c in range(cols):
                self.grid_frame.grid_columnconfigure(c, weight=1)
        except Exception:
            pass

    def setup_controls(self):
        self.root.bind("<KeyPress>", self.on_key_press)

    def setup_ui(self):
        pass

    def on_button_click(self, value):
        pass

    def on_key_press(self, event):
        ch = event.char
        if event.keysym in ("Return", "KP_Enter"):
            self.on_button_click("=")
        elif event.keysym == "Escape":
            self.reset_game()
        elif ch and ch.isprintable() and not ch.isspace():
            self.on_button_click(ch.upper() if ch.isalpha() else ch)

    def reset_game(self):
        self.current_input = ""
        self.game_over = False
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.setup_ui()
        self._configure_grid_weights()


if __name__ == "__main__":
    root = tk.Tk()
    app = WidgetGridApp(root)
    root.mainloop()
'''

RESERVED_SCAFFOLD_METHODS = {
    "__init__", "setup_controls", "on_key_press", "on_key_release",
    "game_loop", "check_collision", "_to_bbox", "_configure_grid_weights"
}


class ManagerAgent(BaseAgent):
    def __init__(self, llm: OllamaClient, ui_callback: Callable[[HarnessState], None]):
        super().__init__("Manager Agent", llm, ui_callback)
        self.researcher = ResearchAgent("Research Agent", llm, ui_callback)
        self.coder = CoderAgent("Coder Agent", llm, ui_callback)
        self.syntax_checker = SyntaxAgent("Syntax Agent", llm, ui_callback)
        self.executor = ExecutorAgent("Sandbox Agent", llm, ui_callback)

    def _plan_dynamic_subtasks(self, state: HarnessState) -> Tuple[List[Dict[str, str]], str]:
        """
        Asks the Manager LLM to dynamically decompose the application into an appropriate
        number of method sub-tasks (2 to 6+) based on complexity, returning (subtasks, contract_text).
        """
        if state.app_archetype == "WIDGET_GRID":
            plan_sys = (
                "You are a Lead Software Architect decomposing a Python Tkinter `WidgetGridApp` into modular method sub-tasks.\n"
                "The base scaffold ALREADY implements `__init__` (providing `self.root`, `self.display_var`, `self.display_label`, "
                "`self.grid_frame`, `self.game_over`), `setup_controls`, `on_key_press`, and `reset_game`.\n"
                "The scaffold calls `self.setup_ui()` on startup/reset, and buttons/keys call `self.on_button_click(value)`.\n\n"
                "Decide dynamically how many method sub-tasks are appropriate for this application's complexity:\n"
                "- Simple apps may only need 2 sub-tasks (`setup_ui` and `on_button_click`).\n"
                "- More complex games/apps may need 3 to 5 sub-tasks (e.g. `setup_ui`, helper methods like `check_winner` or `update_display`, and `on_button_click`).\n"
                "- Sub-Task 1 MUST be `setup_ui` (`args`: `\"self\"`), which initializes all `self.*` state attributes, sets initial `self.display_var.set(...)`, "
                "and builds the `tk.Button` grid in `self.grid_frame` (storing button references on `self` if their text changes during play).\n"
                "- Include `on_button_click` (with `\"args\": \"self, value\"` for single-value buttons, or matching the button lambda arguments) and any helper methods (such as win/status check or display refresh).\n\n"
                "Output a JSON array of sub-task objects inside ```json ... ``` followed by a brief Shared State Contract.\n"
                "Example JSON Schema (choose 2 to 5 sub-tasks as needed):\n"
                "```json\n"
                "[\n"
                "  {\"target_method\": \"setup_ui\", \"args\": \"self\", \"title\": \"Initialize State & Build Button Grid\", \"focus\": \"...\"},\n"
                "  {\"target_method\": \"on_button_click\", \"args\": \"self, value\", \"title\": \"Handle Button Input & Update State\", \"focus\": \"...\"},\n"
                "  {\"target_method\": \"update_display\", \"args\": \"self\", \"title\": \"Refresh UI & Check Completion/Win Status\", \"focus\": \"...\"}\n"
                "]\n"
                "```"
            )
        else:
            plan_sys = (
                "You are a Lead Software Architect decomposing a Python Tkinter 2D `ArcadeGame` into modular method sub-tasks.\n"
                "The base scaffold ALREADY implements `__init__` (providing `self.root`, `self.score_label`, `self.canvas` [600x400], "
                "`self.pressed_keys`, `self.score`, `self.score1`, `self.score2`, `self.game_over`), `check_collision(self, id1, id2)`, "
                "`setup_controls`, `on_key_press` (which calls `self.handle_key(event.keysym)` and `self.reset_game()` on 'R'), and `game_loop` "
                "(which calls `self.update_game()` every frame).\n\n"
                "Decide dynamically how many method sub-tasks are appropriate for this game's complexity (typically 3 to 5 sub-tasks):\n"
                "- Sub-Task 1 MUST be `setup_game` (`args`: `\"self\"`), which calls `self.canvas.delete('all')`, initializes ALL `self.*` state/velocity/direction attributes, "
                "creates initial canvas shapes with 4 coordinates `create_rectangle(x1, y1, x2, y2)` / `create_oval(x1, y1, x2, y2)`, and updates `self.score_label.config(text=...)`.\n"
                "- Middle sub-tasks should implement modular helpers appropriate to the game (e.g. `handle_key` with `\"args\": \"self, key\"` for direction/action input, movement helpers, collision/spawning helpers).\n"
                "- The final sub-task MUST be `update_game` (`args`: `\"self\"`), which executes the per-frame game update and calls your helper methods.\n\n"
                "Output a JSON array of sub-task objects inside ```json ... ``` followed by a brief Shared State Contract.\n"
                "Example JSON Schema (choose 2 to 6 sub-tasks as needed):\n"
                "```json\n"
                "[\n"
                "  {\"target_method\": \"setup_game\", \"args\": \"self\", \"title\": \"Initialize State & Canvas Entities\", \"focus\": \"...\"},\n"
                "  {\"target_method\": \"handle_key\", \"args\": \"self, key\", \"title\": \"Handle Player Keyboard Input\", \"focus\": \"...\"},\n"
                "  {\"target_method\": \"update_game\", \"args\": \"self\", \"title\": \"Per-Frame Movement, Collisions & Scoring\", \"focus\": \"...\"}\n"
                "]\n"
                "```"
            )

        plan_user = (
            f"Target: {state.game_name} ({state.app_archetype})\n"
            f"User Request: {state.user_prompt}\n\n"
            f"Functional Specification:\n{state.summarized_rules}"
        )
        raw_plan = self.llm.chat(plan_sys, plan_user, temperature=0.2, max_tokens=450)
        subtasks = self._parse_dynamic_subtasks(raw_plan, state.app_archetype)
        return subtasks, raw_plan

    def _parse_dynamic_subtasks(self, raw_text: str, archetype: str) -> List[Dict[str, str]]:
        parsed_list = []
        # Extract JSON array from ```json ... ``` fence or outermost [ ... ]
        fence_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw_text, re.DOTALL | re.IGNORECASE)
        json_candidates = []
        if fence_match:
            json_candidates.append(fence_match.group(1))
        first_bracket = raw_text.find("[")
        last_bracket = raw_text.rfind("]")
        if first_bracket != -1 and last_bracket > first_bracket:
            json_candidates.append(raw_text[first_bracket : last_bracket + 1])

        for cand_str in json_candidates:
            try:
                candidate = json.loads(cand_str)
                if isinstance(candidate, list) and candidate:
                    parsed_list = candidate
                    break
            except Exception:
                continue

        valid_tasks: List[Dict[str, str]] = []
        seen_methods = set()

        for item in parsed_list:
            if not isinstance(item, dict):
                continue
            m_name = str(item.get("target_method", "")).strip()
            # Clean accidental "def foo(self):" in target_method
            m_name = re.sub(r"^def\s+", "", m_name).split("(")[0].strip()
            if not m_name or not m_name.isidentifier() or m_name in RESERVED_SCAFFOLD_METHODS or m_name in seen_methods:
                continue

            args_str = str(item.get("args", "self")).strip()
            if not args_str.startswith("self"):
                args_str = f"self, {args_str}" if args_str else "self"
            if m_name == "on_button_click" and "," not in args_str:
                args_str = "self, value"
            elif m_name == "handle_key" and "," not in args_str:
                args_str = "self, key"

            title = str(item.get("title", f"Implement `{m_name}`")).strip()
            focus = str(item.get("focus", f"Implement `{m_name}({args_str})`.")).strip()
            valid_tasks.append({
                "target_method": m_name,
                "args": args_str,
                "title": title,
                "focus": focus
            })
            seen_methods.add(m_name)

        # Scan sub-task focus descriptions for any self.<helper>() calls mentioned by Manager
        # that were omitted from the JSON array, and register them as sub-tasks before the final hook
        non_method_attrs = {
            "canvas", "root", "master", "score_label", "display_var",
            "display_label", "grid_frame", "pressed_keys", "score",
            "score1", "score2", "game_over", "current_input"
        }
        referenced_helpers: List[str] = []
        for t in list(valid_tasks):
            for match in re.finditer(r"self\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", t["focus"]):
                h_name = match.group(1)
                if (
                    h_name not in seen_methods
                    and h_name not in RESERVED_SCAFFOLD_METHODS
                    and h_name != "reset_game"
                    and h_name not in non_method_attrs
                    and h_name not in referenced_helpers
                ):
                    referenced_helpers.append(h_name)

        for h_name in referenced_helpers:
            valid_tasks.append({
                "target_method": h_name,
                "args": "self",
                "title": f"Implement Helper `{h_name}`",
                "focus": f"Implement helper method `def {h_name}(self):` as referenced in the architectural plan."
            })
            seen_methods.add(h_name)

        # Ensure essential lifecycle entry hooks exist for the archetype
        if archetype == "WIDGET_GRID":
            if "setup_ui" not in seen_methods:
                valid_tasks.insert(0, {
                    "target_method": "setup_ui",
                    "args": "self",
                    "title": "Initialize State & Build Widget Grid UI",
                    "focus": "Initialize all `self.*` state variables, set initial `self.display_var.set(...)`, and create `tk.Button` widgets inside `self.grid_frame` wired to `command=lambda v=val: self.on_button_click(v)`."
                })
                seen_methods.add("setup_ui")
            if "on_button_click" not in seen_methods:
                valid_tasks.append({
                    "target_method": "on_button_click",
                    "args": "self, value",
                    "title": "Handle Button/Key Input & Update State",
                    "focus": "Process the clicked/pressed `value`, update game/application state, check win/loss/completion conditions, and update `self.display_var.set(...)`."
                })
                seen_methods.add("on_button_click")
        else:
            if "setup_game" not in seen_methods:
                valid_tasks.insert(0, {
                    "target_method": "setup_game",
                    "args": "self",
                    "title": "Initialize State & Canvas Entities",
                    "focus": "Call `self.canvas.delete('all')`, initialize all `self.*` state/velocity attributes, create initial canvas shapes on `self.canvas`, and update `self.score_label.config(text=...)`."
                })
                seen_methods.add("setup_game")
            if "update_game" not in seen_methods:
                valid_tasks.append({
                    "target_method": "update_game",
                    "args": "self",
                    "title": "Per-Frame Game Update, Collisions & Scoring",
                    "focus": "Execute per-frame movement, boundary/collision checks, scoring updates on `self.score_label.config(text=...)`, and invoke any helper methods."
                })
                seen_methods.add("update_game")
            else:
                # Ensure update_game runs after helper methods so helpers are defined first
                ug_tasks = [t for t in valid_tasks if t["target_method"] == "update_game"]
                other_tasks = [t for t in valid_tasks if t["target_method"] != "update_game"]
                valid_tasks = other_tasks + ug_tasks

        # Number the dynamic tasks cleanly (1/N .. N/N)
        total = len(valid_tasks)
        for idx, t in enumerate(valid_tasks, start=1):
            t["id"] = str(idx)
            sig = f"def {t['target_method']}({t['args']}):"
            if not t["title"].startswith("Sub-Task"):
                t["title"] = f"Sub-Task {idx}/{total}: {t['title']} (`{sig}`)"

        return valid_tasks

    def execute_workflow(self, user_prompt: str) -> HarnessState:
        state = HarnessState(user_prompt=user_prompt)
        self.log(state, f"Initialized workflow for request: '{user_prompt}'")

        try:
            # Step 1: Research & classify UI archetype
            self.researcher.run(state)

            # Step 2: Initialize Base Scaffold & Dynamically Decompose into Sub-Tasks
            self.log(state, f"Initializing {state.app_archetype} base scaffold and dynamically planning sub-tasks for '{state.game_name}'...")
            safe_title = state.game_name.replace('"', "").replace("'", "")
            if state.app_archetype == "WIDGET_GRID":
                state.current_code = WIDGET_GRID_SCAFFOLD.replace("{game_name}", safe_title)
            else:
                state.current_code = CANVAS_ARCADE_SCAFFOLD.replace("{game_name}", safe_title)

            state.subtasks, raw_contract = self._plan_dynamic_subtasks(state)
            state.current_code = ASTMerger.register_planned_stubs(state.current_code, state.subtasks)

            task_summary = "\n".join(f"- {t['title']}:\n  {t['focus']}" for t in state.subtasks)
            state.development_plan = (
                f"=== DYNAMIC SUB-TASK PLAN ({len(state.subtasks)} SUB-TASKS) ===\n"
                f"{task_summary}\n\n"
                f"=== ARCHITECTURAL CONTRACT ===\n{raw_contract}"
            )
            self.log(
                state,
                f"Dynamically decomposed '{state.game_name}' into {len(state.subtasks)} sub-tasks.",
                "SUCCESS"
            )

            # Step 3: Execute each dynamically planned sub-task with incremental Syntax Agent validation
            max_microtask_retries = 3
            for idx, subtask in enumerate(state.subtasks, start=1):
                state.current_subtask_index = idx
                target_method = subtask["target_method"]
                self.log(state, f"Allocating {subtask['title']} to Coder Agent...", "INFO")

                candidate_code = self.coder.generate_microtask_candidate(state, idx, subtask)
                is_valid, err_msg = self.syntax_checker.validate_microtask(state, candidate_code, target_method)

                retry_count = 0
                while not is_valid and retry_count < max_microtask_retries:
                    retry_count += 1
                    self.log(
                        state,
                        f"Retrying {subtask['title']} (Sub-Task Retry {retry_count}/{max_microtask_retries})...",
                        "WARNING"
                    )
                    candidate_code = self.coder.generate_microtask_candidate(
                        state,
                        idx,
                        subtask,
                        retry_error=err_msg,
                        failed_candidate=candidate_code
                    )
                    is_valid, err_msg = self.syntax_checker.validate_microtask(state, candidate_code, target_method)

                state.current_code = candidate_code
                self.log(
                    state,
                    f"Committed {subtask['title']} (Code size: {len(state.current_code.splitlines())} lines).",
                    "SUCCESS"
                )

            self.log(
                state,
                f"All {len(state.subtasks)} dynamic sub-tasks validated and merged. Entering full verification loop...",
                "SUCCESS"
            )

            # Step 4: Full AST -> Interactive Sandbox -> Targeted Method Repair Loop
            while True:
                self.syntax_checker.run(state)
                if not state.syntax_valid:
                    if state.iteration >= MAX_REPAIR_ITERATIONS:
                        break
                    state.iteration += 1
                    self.log(
                        state,
                        f"Allocating Targeted Method Repair to Coder Agent for static issue (Attempt {state.iteration}/{MAX_REPAIR_ITERATIONS})...",
                        "WARNING"
                    )
                    self.coder.run_repair(state)
                    continue

                self.executor.run(state)
                if not state.execution_success:
                    if state.iteration >= MAX_REPAIR_ITERATIONS:
                        break
                    state.iteration += 1
                    self.log(
                        state,
                        f"Allocating Targeted Method Repair to Coder Agent for runtime issue (Attempt {state.iteration}/{MAX_REPAIR_ITERATIONS})...",
                        "WARNING"
                    )
                    self.coder.run_repair(state)
                    continue

                state.is_complete = True
                self.log(
                    state,
                    f"'{state.game_name}' successfully built and verified on repair iteration {state.iteration}!",
                    "SUCCESS"
                )
                break

            if not state.is_complete:
                last_err = state.syntax_error if not state.syntax_valid else state.runtime_error
                self.log(
                    state,
                    f"Reached maximum repair iterations ({MAX_REPAIR_ITERATIONS}/{MAX_REPAIR_ITERATIONS}). "
                    f"Returning best-effort candidate code ({len(state.current_code.splitlines())} lines) with latest error log:\n"
                    f"{last_err or 'Verification did not complete.'}",
                    "ERROR"
                )

        except Exception as e:
            self.log(state, f"Critical Orchestration Failure: {str(e)}", "ERROR")

        return state
