import requests
import re
import time
import ast
import textwrap
from config import OLLAMA_BASE_URL, OLLAMA_MODEL


class OllamaClient:
    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = OLLAMA_MODEL):
        self.api_url = f"{base_url}/api/chat"
        self.model = model

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 600,
        max_retries: int = 2
    ) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": 4096,
                "num_predict": max_tokens
            }
        }

        last_error = None
        for attempt in range(max_retries):
            try:
                response = requests.post(self.api_url, json=payload, timeout=600)
                response.raise_for_status()
                data = response.json()
                return data.get("message", {}).get("content", "").strip()
            except requests.exceptions.RequestException as e:
                last_error = e
                time.sleep(2)

        raise RuntimeError(f"Failed to communicate with local Ollama instance ({self.model} at {self.api_url}): {last_error}")

    @staticmethod
    def _clean_block(raw_block: str) -> str:
        lines = []
        for ln in raw_block.strip().splitlines():
            if re.match(r"^\s*`{1,3}(?:python|py)?\s*$", ln, re.IGNORECASE):
                continue
            # Strip accidental " 35: " line-number prefixes
            ln_clean = re.sub(r"^\s*\d{1,3}:\s?", "", ln)
            lines.append(ln_clean)
        return textwrap.dedent("\n".join(lines)).strip()

    @classmethod
    def extract_code_block(cls, text: str) -> str:
        """
        Extracts Python code from markdown code fences.
        If the model outputs multiple methods across separate code blocks,
        dedents each block individually and joins all valid Python blocks.
        """
        pattern = r"```(?:python|py)?\s*\n(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
        if not matches:
            unclosed = re.search(r"```(?:python|py)?\s*\n(.*)$", text, re.DOTALL | re.IGNORECASE)
            raw = unclosed.group(1) if unclosed else text
            return cls._clean_block(raw)

        if len(matches) == 1:
            return cls._clean_block(matches[0])

        cleaned_blocks = []
        for m in matches:
            cb = cls._clean_block(m)
            if cb:
                cleaned_blocks.append(cb)

        if not cleaned_blocks:
            return ""

        longest = max(cleaned_blocks, key=len)
        if "class " in longest and "def __init__" in longest and len(cleaned_blocks) > 1:
            extra = [b for b in cleaned_blocks if b != longest and "class " not in b]
            if extra:
                return longest + "\n\n" + "\n\n".join(extra)
            return longest

        return "\n\n".join(cleaned_blocks)
