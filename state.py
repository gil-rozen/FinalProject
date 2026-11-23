from dataclasses import dataclass, field
from typing import List, Optional, Dict
import datetime

@dataclass
class AgentLog:
    timestamp: str
    agent_name: str
    message: str
    level: str = "INFO"  # INFO, SUCCESS, WARNING, ERROR

@dataclass
class HarnessState:
    user_prompt: str
    game_name: str = ""
    app_archetype: str = "CANVAS_ARCADE"  # "CANVAS_ARCADE" or "WIDGET_GRID"
    raw_wiki_content: str = ""
    summarized_rules: str = ""
    development_plan: str = ""
    subtasks: List[Dict[str, str]] = field(default_factory=list)
    current_subtask_index: int = 0
    current_code: str = ""

    # Validation & Execution status
    syntax_valid: bool = False
    syntax_error: Optional[str] = None
    execution_success: bool = False
    runtime_error: Optional[str] = None

    iteration: int = 0
    is_complete: bool = False
    logs: List[AgentLog] = field(default_factory=list)

    def add_log(self, agent_name: str, message: str, level: str = "INFO"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.logs.append(AgentLog(timestamp=ts, agent_name=agent_name, message=message, level=level))
