from typing import Callable
from state import HarnessState
from llm_client import OllamaClient

class BaseAgent:
    def __init__(self, name: str, llm: OllamaClient, ui_callback: Callable[[HarnessState], None]):
        self.name = name
        self.llm = llm
        self.ui_callback = ui_callback

    def log(self, state: HarnessState, message: str, level: str = "INFO"):
        state.add_log(self.name, message, level)
        if self.ui_callback:
            self.ui_callback(state)
