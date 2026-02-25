from dotenv import load_dotenv
import os
load_dotenv()

from google import genai

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# listează primele modele disponibile
models = list(client.models.list())
print("MODELS:", [m.name for m in models[:15]])

# încearcă un model comun (alege unul din listă dacă diferă)
model_name = "gemini-2.0-flash"

resp = client.models.generate_content(
    model=model_name,
    contents="Spune salut în română."
)
print(resp.text)
