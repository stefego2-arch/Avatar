from __future__ import annotations
import os
from dotenv import load_dotenv

load_dotenv()

def gemini_available() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))

def make_client():
    # SDK oficial: google-genai (GenAI SDK)  :contentReference[oaicite:2]{index=2}
    from google import genai
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY lipsă în .env")
    return genai.Client(api_key=api_key)

def generate_quiz_from_text(text: str, n: int = 5) -> str:
    client = make_client()
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    prompt = f"""
Ești un profesor pentru copii (clasa 1-4). Generează {n} întrebări scurte
din textul de mai jos. Format:
1) întrebare
   - răspuns corect
   - 2 explicații scurte (de ce e corect)

TEXT:
{text}
"""
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
    )
    return (resp.text or "").strip()
