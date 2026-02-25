from dotenv import load_dotenv
import os
load_dotenv()

from google import genai

key = os.getenv("GEMINI_API_KEY")
print("KEY loaded:", bool(key), key[:8] + "..." if key else "")

client = genai.Client(api_key=key)

try:
    models = list(client.models.list())
    print("MODELS (first 15):", [m.name for m in models[:15]])
except Exception as e:
    print("❌ models.list failed:", repr(e))
    raise

# IMPORTANT: alege un model chiar din listă dacă nu există gemini-2.0-flash
model_name = "gemini-2.0-flash"

try:
    resp = client.models.generate_content(
        model=model_name,
        contents="Spune salut în română."
    )
    print("✅ RESPONSE:", resp.text)
except Exception as e:
    print("❌ generate_content failed:", repr(e))
    raise
