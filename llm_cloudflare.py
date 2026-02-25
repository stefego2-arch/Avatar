# llm_cloudflare.py
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

@dataclass
class QuizItem:
    q: str
    a: str
    choices: Optional[List[str]] = None


class CloudflareTutor:
    """
    Cloudflare Workers AI via OpenAI-compatible endpoint:
    POST https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions
    """
    def __init__(
        self,
        api_token: Optional[str] = None,
        account_id: Optional[str] = None,
        model: Optional[str] = None,
        timeout_s: int = 45,
    ):
        self.api_token = api_token or os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        self.account_id = account_id or os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
        self.model = model or os.getenv("CLOUDFLARE_AI_MODEL", "@cf/meta/llama-3.1-8b-instruct").strip()
        self.timeout_s = timeout_s

        if not self.api_token or not self.account_id:
            raise RuntimeError("Missing CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID in environment (.env).")

        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/v1"

    def _post_chat(self, messages, *, max_tokens: int = 600, temperature: float = 0.2, retries: int = 3) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        last_err = None
        for attempt in range(retries + 1):
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=self.timeout_s)
                if r.status_code == 429:
                    # rate limit -> mic backoff
                    time.sleep(1.5 + attempt * 1.5)
                    continue
                r.raise_for_status()
                data = r.json()
                # OpenAI-style: choices[0].message.content
                return (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
            except Exception as e:
                last_err = e
                time.sleep(1.0 + attempt * 1.0)

        raise RuntimeError(f"Cloudflare AI call failed: {last_err}")

    @staticmethod
    def _extract_json(text: str) -> Optional[dict]:
        """
        În practică, modelele mai “scapă” text în jur.
        Scoatem primul obiect JSON valid { ... }.
        """
        if not text:
            return None
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None

    def make_questions(self, chunk: str, *, grade: int, subject: str, n: int = 3) -> List[QuizItem]:
        # IMPORTANT: trimite chunk mai scurt ca să nu consume inutil
        chunk = (chunk or "").strip()
        if len(chunk) > 2500:
            chunk = chunk[:2500]

        system = (
            "Ești un tutor pentru elevi. Generezi întrebări scurte și clare, adaptate clasei și materiei. "
            "Răspunzi STRICT în JSON."
        )

        user = f"""
Generează {n} întrebări din textul de mai jos pentru clasa {grade}, materia {subject}.

Cerințe:
- Întrebări scurte, pe conținutul din text
- Dă și răspunsul corect
- Dacă are sens, pune variante (A/B/C/D). Dacă nu, lasă choices null.

Returnează STRICT JSON cu schema:
{{
  "items": [
    {{"q": "...", "a": "...", "choices": ["...","...","...","..."]}},
    ...
  ]
}}

TEXT:
\"\"\"{chunk}\"\"\"
""".strip()

        content = self._post_chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=700,
            temperature=0.2,
        )

        obj = self._extract_json(content)
        if not obj or "items" not in obj:
            # fallback minimal: o singură întrebare generică
            return [QuizItem(q="Care este ideea principală din acest fragment?", a="Răspuns liber", choices=None)]

        out: List[QuizItem] = []
        for it in obj.get("items", [])[:n]:
            q = str(it.get("q", "")).strip()
            a = str(it.get("a", "")).strip()
            choices = it.get("choices", None)
            if isinstance(choices, list):
                choices = [str(c).strip() for c in choices if str(c).strip()]
                if not choices:
                    choices = None
            else:
                choices = None
            if q and a:
                out.append(QuizItem(q=q, a=a, choices=choices))
        return out
