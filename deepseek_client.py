#!/usr/bin/env python3
"""
🤖 DEEPSEEK CLIENT — Ollama local
Client complet pentru DeepSeek prin Ollama.
Apeluri MINIME și inteligente — nu la fiecare eveniment.

Import în alte scripturi:
    from deepseek_client import DeepSeekClient

Necesită: pip install requests
          Ollama rulând: ollama serve
          Model: ollama pull deepseek-r1:7b
"""

import json
import re
import time
import threading
from typing import Optional, Callable, Generator

# Elimină blocurile <think>...</think> pe care deepseek-r1 le adaugă uneori
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


# ─── Client principal ────────────────────────────────────────────────────────

class DeepSeekClient:
    """
    Client pentru DeepSeek via Ollama local.

    Utilizare:
        ds = DeepSeekClient()
        if ds.available:
            raspuns = ds.ask("Explică adunarea pentru un copil de 7 ani.")

        # Streaming (afișează pe măsură ce vine)
        ds.ask_stream("Generează 3 exerciții...", callback=print)

        # Verifică răspuns elev
        ok, feedback = ds.check_answer(
            enunt="3 + 4 = ?",
            raspuns_corect="7",
            raspuns_elev="6"
        )

        # Generează exerciții noi (pentru populare DB)
        exercises = ds.generate_exercises(
            lesson_title="Adunarea până la 10",
            grade=1, subject="Matematică", count=5
        )
    """

    MODEL = "deepseek-r1:7b"   # Ajustează dacă ai alt model
    OLLAMA_URL = "http://localhost:11434"
    TIMEOUT_QUICK = 15  # Secunde pentru răspuns scurt
    TIMEOUT_LONG  = 60  # Secunde pentru generare exerciții

    def __init__(self, model: str = None, url: str = None):
        self.model = model or self.MODEL
        self.url = (url or self.OLLAMA_URL).rstrip("/")
        self._available = None  # Lazy check
        self._call_count = 0
        self._total_tokens = 0

        # Circuit breaker: pauză după timeout-uri consecutive
        self._consecutive_timeouts = 0
        self._cooldown_until: float = 0.0   # timestamp până când nu mai încercăm

        # Cache simplu în memorie
        self._cache: dict[str, str] = {}
        self.USE_CACHE = True

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _strip_think(text: str) -> str:
        """Elimină blocurile <think>...</think> din răspunsurile deepseek-r1."""
        return _THINK_RE.sub("", text).strip()

    # ── Disponibilitate ───────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """Verifică dacă Ollama rulează și modelul e disponibil."""
        # Circuit breaker: în cooldown după timeout-uri repetate
        if self._cooldown_until and time.time() < self._cooldown_until:
            return False
        if self._available is None:
            self._available = self._check_available()
        return self._available

    def _check_available(self) -> bool:
        try:
            import requests
            r = requests.get(f"{self.url}/api/tags", timeout=3)
            if r.status_code != 200:
                print("⚠️  DeepSeek: Ollama nu răspunde")
                return False

            models = [m["name"] for m in r.json().get("models", [])]
            if not any(self.model in m for m in models):
                print(f"⚠️  DeepSeek: Modelul '{self.model}' nu e instalat.")
                print(f"    Disponibile: {models}")
                print(f"    Rulează: ollama pull {self.model}")
                # Încearcă alt model deepseek
                for m in models:
                    if "deepseek" in m.lower() or "llama" in m.lower():
                        self.model = m
                        print(f"    Folosesc: {self.model}")
                        return True
                return False

            print(f"✅ DeepSeek: {self.model} disponibil")
            return True

        except Exception as e:
            print(f"⚠️  DeepSeek: Ollama nu rulează ({e})")
            print("    Pornește cu: ollama serve")
            return False

    # ── API principal ─────────────────────────────────────────────────────────

    def ask(self, prompt: str, system: str = None,
            cache_key: str = None, timeout: int = None,
            _force_json: bool = False) -> Optional[str]:
        """
        Trimite o întrebare și returnează răspunsul complet.

        Args:
            prompt: Mesajul pentru model
            system: Instrucțiune de sistem (opțional)
            cache_key: Cheie pentru cache (None = nu cache)
            timeout: Timeout în secunde

        Returns:
            Răspunsul ca string, sau None la eroare
        """
        if not self.available:
            return None

        # Verifică cache
        if cache_key and self.USE_CACHE and cache_key in self._cache:
            return self._cache[cache_key]

        try:
            import requests
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "num_predict": 1024,
                }
            }
            if system:
                payload["system"] = system
            if _force_json:
                payload["format"] = "json"   # Ollama returnează JSON valid garantat

            t_start = time.time()
            r = requests.post(
                f"{self.url}/api/generate",
                json=payload,
                timeout=timeout or self.TIMEOUT_QUICK
            )
            t_end = time.time()

            if r.status_code != 200:
                print(f"❌ DeepSeek: HTTP {r.status_code}")
                return None

            data = r.json()
            response = self._strip_think(data.get("response", ""))

            # Statistici
            self._call_count += 1
            self._consecutive_timeouts = 0   # reset circuit breaker la succes
            tokens = data.get("eval_count", 0)
            self._total_tokens += tokens
            print(f"🤖 DeepSeek: {len(response)} chars, {tokens} tokens, {t_end-t_start:.1f}s")

            # Salvează în cache
            if cache_key and self.USE_CACHE:
                self._cache[cache_key] = response

            return response

        except Exception as e:
            print(f"❌ DeepSeek: Eroare: {e}")
            # Circuit breaker: timeout-uri consecutive → pauză 5 minute
            err_str = str(e).lower()
            if "timeout" in err_str or "timed out" in err_str or "read timeout" in err_str:
                self._consecutive_timeouts += 1
                if self._consecutive_timeouts >= 2:
                    self._cooldown_until = time.time() + 300   # 5 min
                    print(f"⏸️  DeepSeek: {self._consecutive_timeouts} timeout-uri consecutive "
                          f"— pauză 5 minute (Ollama supraîncărcat)")
            else:
                self._consecutive_timeouts = 0   # resetăm la alte tipuri de erori
            return None

    def ask_collect(self, prompt: str, system: str = None,
                    cache_key: str = None,
                    _force_json: bool = False) -> Optional[str]:
        """
        Varianta streaming a lui ask(): colectează răspunsul token cu token.
        Avantaj față de ask(): NU există read timeout (timeout=(15, None)).
        Util pentru generări lungi (deepseek-r1:8b + JSON structurat).

        Returns:
            Răspunsul complet ca string, sau None la eroare.
        """
        if not self.available:
            return None

        if cache_key and self.USE_CACHE and cache_key in self._cache:
            return self._cache[cache_key]

        try:
            import requests, json as _json
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": True,
                "options": {
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "num_predict": 1024,
                },
            }
            if system:
                payload["system"] = system
            if _force_json:
                payload["format"] = "json"

            t_start = time.time()
            chunks: list[str] = []

            with requests.post(
                f"{self.url}/api/generate",
                json=payload,
                stream=True,
                timeout=(15, None),   # 15s connect, fără timeout pe read
            ) as r:
                if r.status_code != 200:
                    print(f"❌ DeepSeek collect: HTTP {r.status_code}")
                    return None
                for line in r.iter_lines():
                    if line:
                        try:
                            data = _json.loads(line)
                            chunks.append(data.get("response", ""))
                            if data.get("done"):
                                break
                        except Exception:
                            pass

            t_end = time.time()
            response = self._strip_think("".join(chunks))

            self._call_count += 1
            self._consecutive_timeouts = 0
            print(f"🤖 DeepSeek: {len(response)} chars, {t_end - t_start:.1f}s (streaming)")

            if cache_key and self.USE_CACHE and response:
                self._cache[cache_key] = response

            return response or None

        except Exception as e:
            print(f"❌ DeepSeek: Eroare collect: {e}")
            err_str = str(e).lower()
            if "timeout" in err_str or "connect" in err_str:
                self._consecutive_timeouts += 1
                if self._consecutive_timeouts >= 2:
                    self._cooldown_until = time.time() + 300
                    print(f"⏸️  DeepSeek: {self._consecutive_timeouts} erori — pauză 5 minute")
            else:
                self._consecutive_timeouts = 0
            return None

    def ask_stream(self, prompt: str, callback: Callable[[str], None],
                   system: str = None, on_done: Callable = None):
        """
        Streaming: apelează callback pentru fiecare chunk de text.
        Rulează în thread separat (non-blocking).

        Args:
            prompt: Mesajul
            callback: fn(chunk: str) — apelat per token
            system: System prompt
            on_done: fn() — apelat la final
        """
        def _stream_thread():
            try:
                import requests
                payload = {
                    "model": self.model,
                    "prompt": prompt,
                    "stream": True,
                    "options": {"temperature": 0.7, "num_predict": 512}
                }
                if system:
                    payload["system"] = system

                with requests.post(
                    f"{self.url}/api/generate",
                    json=payload,
                    stream=True,
                    timeout=self.TIMEOUT_LONG
                ) as r:
                    for line in r.iter_lines():
                        if line:
                            chunk = json.loads(line)
                            token = chunk.get("response", "")
                            if token:
                                callback(token)
                            if chunk.get("done"):
                                break

            except Exception as e:
                print(f"❌ DeepSeek stream: {e}")
            finally:
                if on_done:
                    on_done()

        if not self.available:
            if on_done:
                on_done()
            return

        t = threading.Thread(target=_stream_thread, daemon=True)
        t.start()

    # ── Metode specializate (utilizate de lesson_engine) ─────────────────────

    def check_answer(self, enunt: str, raspuns_corect: str,
                     raspuns_elev: str, subject: str = "",
                     grade: int = 1) -> tuple[bool, str]:
        """
        Verifică răspunsul elevului cu DeepSeek.
        Folosit DOAR pentru răspunsuri text liber (nu multiple choice).

        Returns:
            (is_correct: bool, feedback: str)
        """
        # Verificare rapidă înainte de LLM
        if raspuns_elev.strip().lower() == raspuns_corect.strip().lower():
            return True, "Corect! Bravo! 🌟"

        # Verificare numerică
        try:
            if float(raspuns_elev.strip()) == float(raspuns_corect.strip()):
                return True, "Corect! 🌟"
        except ValueError:
            pass

        if not self.available:
            # Fallback simplu fără LLM
            is_correct = raspuns_elev.strip().lower() == raspuns_corect.strip().lower()
            feedback = "Corect! 🎉" if is_correct else f"Nu e corect. Răspunsul corect: {raspuns_corect}"
            return is_correct, feedback

        system = (
            f"Ești profesor blând pentru copii de clasa {grade} din România.\n"
            "Verifică dacă răspunsul elevului este corect sau echivalent cu cel așteptat.\n"
            "Răspunde EXACT în formatul:\n"
            "  CORECT | <feedback scurt, max 1-2 propoziții, încurajator>\n"
            "sau:\n"
            "  GRESIT | <ce era greșit și care este răspunsul corect>\n"
            "NU adăuga alt text în afara acestui format."
        )

        prompt = f"""Exercițiu: {enunt}
Răspuns corect: {raspuns_corect}
Răspuns elev: {raspuns_elev}

Este răspunsul elevului corect?"""

        response = self.ask(prompt, system=system, timeout=10)

        if not response:
            is_correct = raspuns_elev.strip().lower() == raspuns_corect.strip().lower()
            feedback = "Corect! 🎉" if is_correct else f"Răspunsul corect este: {raspuns_corect}"
            return is_correct, feedback

        # Parsing format: "CORECT | feedback" sau "GRESIT | feedback"
        # Fallback la vechiul format (separare pe linie) dacă modelul nu respectă |
        if "|" in response:
            parts = response.split("|", 1)
            verdict  = parts[0].strip().upper()
            feedback = parts[1].strip() if len(parts) > 1 else ""
        else:
            lines    = response.strip().split("\n", 1)
            verdict  = lines[0].upper().strip()
            feedback = lines[1].strip() if len(lines) > 1 else response

        is_correct = "CORECT" in verdict and "GRESIT" not in verdict
        if not feedback:
            feedback = "Corect! 🌟" if is_correct else f"Răspunsul corect este: {raspuns_corect}"

        return is_correct, feedback

    # Răspunsuri generice pe care LLM le produce când nu are context bun
    _GENERIC_INVALID = {
        "da", "nu", "da.", "nu.", "corect", "incorect",
        "raspuns", "răspuns", "...", "—", "-", "?", "!",
        "adevărat", "fals", "adevarat", "fals.", "true", "false",
    }

    @staticmethod
    def _validate_exercise(ex: dict) -> bool:
        """
        Returnează True dacă exercițiul e utilizabil.
        Filtrează: enunțuri prea scurte, răspunsuri generice/invalide,
        răspunsuri-întrebări (LLM confuz), dificultate out-of-range.
        """
        enunt   = (ex.get("enunt")   or "").strip()
        raspuns = (ex.get("raspuns") or "").strip()

        # Enunț prea scurt — nu e o întrebare reală
        if len(enunt) < 15:
            return False

        # Răspuns absent sau prea lung (LLM a pus explicație în loc de răspuns)
        if not raspuns or len(raspuns) > 120:
            return False

        # LLM a generat o întrebare ca răspuns
        if raspuns.endswith("?"):
            return False

        # Răspuns generic fără valoare pedagogică
        if raspuns.lower() in DeepSeekClient._GENERIC_INVALID:
            return False

        # Dificultate — normalizează în loc să respingem
        try:
            d = int(ex.get("dificultate") or 1)
            ex["dificultate"] = max(1, min(3, d))
        except (ValueError, TypeError):
            ex["dificultate"] = 1

        return True

    def generate_exercises(self, lesson_title: str, grade: int,
                           subject: str, theory: str = "",
                           count: int = 5, phase: str = "practice",
                           chunk_context: str = "",
                           streaming: bool = False) -> list[dict]:
        """
        Generează exerciții noi pentru o lecție.
        RULAT OFFLINE (la setup), nu în timp real.

        Returns:
            list of dicts cu: enunt, raspuns, hint1, hint2, hint3, explicatie, dificultate
        """
        if not self.available:
            print("⚠️  DeepSeek indisponibil, nu pot genera exerciții")
            return []

        system = f"""Ești expert în pedagogie pentru copii de clasa {grade} din România.
Generezi exerciții clare, potrivite vârstei, în limba română.
RĂSPUNZI DOAR CU JSON VALID, fără explicații sau text suplimentar."""

        difficulty_desc = {
            "pretest": "ușoare (dificultate 1-2), să testăm cunoștințe anterioare",
            "practice": "progresive (dificultate 1-3), pentru exersare",
            "posttest": "moderate (dificultate 2-3), să testăm ce s-a învățat"
        }.get(phase, "moderate")

        # Use chunk_context if provided (actual textbook text), else fall back to theory
        content_for_prompt = (chunk_context or theory or "")[:600]

        prompt = f"""Generează {count} exerciții {difficulty_desc} pentru:
- Materie: {subject}
- Clasa: {grade}
- Lecție: {lesson_title}
- Text lecție (folosește-l pentru a crea exerciții RELEVANTE):
{content_for_prompt if content_for_prompt else "N/A"}

REGULI IMPORTANTE:
1. Exercițiile trebuie să fie ÎNTREBĂRI la care copilul răspunde (NU soluții gata-scrise)
2. Răspunsul trebuie să fie scurt (1-5 cuvinte) pentru a putea fi verificat automat
3. Bazează exercițiile pe textul de mai sus, nu inventa conținut
4. Adaptat vârstei clasei {grade} — propoziții simple, cuvinte cunoscute

Format JSON array:
[
  {{
    "enunt": "întrebarea / cerința pentru elev",
    "raspuns": "raspunsul corect (scurt, 1-5 cuvinte)",
    "hint1": "indiciu vag",
    "hint2": "indiciu mai clar",
    "hint3": "aproape raspunsul",
    "explicatie": "explicatie daca raspunde gresit",
    "dificultate": 1
  }}
]

IMPORTANT: Răspunde NUMAI cu JSON-ul, fără ```json sau altceva."""

        # Cache key includes content hash so different lessons get different exercises
        import hashlib
        content_hash = hashlib.md5(content_for_prompt.encode()).hexdigest()[:8]
        ck = f"ex_{lesson_title}_{phase}_{count}_{content_hash}"
        if streaming:
            response = self.ask_collect(prompt, system=system, cache_key=ck, _force_json=True)
        else:
            response = self.ask(prompt, system=system,
                               cache_key=ck, timeout=self.TIMEOUT_LONG,
                               _force_json=True)

        if not response:
            return []

        try:
            # Curăță răspunsul dacă are markdown
            clean = response.strip()
            if clean.startswith("```"):
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
            if "```" in clean:
                clean = clean.split("```")[0]

            raw = json.loads(clean.strip())
            if not isinstance(raw, list):
                print(f"❌ DeepSeek: JSON returnat nu e o listă")
                return []

            exercises = [e for e in raw if self._validate_exercise(e)]
            skipped = len(raw) - len(exercises)
            if skipped:
                print(f"⚠️  DeepSeek: {skipped}/{len(raw)} exerciții respinse (răspunsuri invalide)")
            if len(exercises) < len(raw) * 0.5:
                print(f"⚠️  DeepSeek: Mai puțin de 50% din exerciții au trecut validarea")
            print(f"✅ DeepSeek: {len(exercises)} exerciții valide generate pentru '{lesson_title}'")
            return exercises

        except json.JSONDecodeError as e:
            print(f"❌ DeepSeek: JSON invalid: {e}")
            print(f"   Răspuns brut: {response[:200]}...")
            return []

    def explain_for_student(self, concept: str, grade: int,
                            student_question: str = "") -> str:
        """
        Generează o explicație personalizată pentru un elev.
        Apelat când elevul nu înțelege ceva.
        """
        system = f"""Ești un profesor prietenos și răbdător pentru copii de clasa {grade} din România.
Explici conceptele simplu, cu exemple din viața de zi cu zi, cu entuziasm.
Ești scurt (max 3-4 propoziții) și folosești cuvinte simple.
Uneori folosești emoji pentru a fi mai prietenos."""

        prompt = f"""Conceptul de explicat: {concept}
{"Întrebarea elevului: " + student_question if student_question else ""}

Explică acest concept simplu, pentru clasa {grade}."""

        response = self.ask(
            prompt, system=system,
            cache_key=f"explain_{concept[:30]}_{grade}" if not student_question else None,
            timeout=15
        )
        return response or f"Hai să mai citim împreună lecția despre {concept}!"

    def get_motivation_message(self, student_name: str, score: float,
                               subject: str, grade: int) -> str:
        """Generează un mesaj motivațional personalizat."""
        if not self.available:
            # Mesaje predefinite
            if score >= 80:
                return f"Bravo, {student_name}! Ai trecut testul! 🎉"
            elif score >= 60:
                return f"Bine, {student_name}! Puțin mai mult și treci! 💪"
            else:
                return f"Nu te descuraja, {student_name}! Hai să mai exersăm! 📚"

        system = "Ești un mentor pozitiv pentru copii. Răspunzi în 1-2 propoziții, entuziast și încurajator."

        prompt = f"""Elevul {student_name} (clasa {grade}, {subject}) a obținut scorul {score:.0f}%.
Scrie un mesaj motivațional scurt, personalizat, în română."""

        response = self.ask(prompt, system=system, timeout=8)
        return response or f"Bine, {student_name}! Continuă să lucrezi! 💪"

    def answer_free_question(self, question: str, subject: str,
                             grade: int, lesson_context: str = "") -> str:
        """
        Răspunde la o întrebare spontană a elevului în timpul lecției.
        """
        system = f"""Ești un profesor virtual pentru un copil de clasa {grade} din România.
Ești prietenos, răbdător și explici simplu.
Contextul lecției: {subject} - {lesson_context[:200] if lesson_context else "N/A"}
Răspunde scurt (3-5 propoziții max), în română, simplu."""

        response = self.ask(question, system=system, timeout=20)
        return response or "E o întrebare bună! Hai să mai citim lecția împreună și să găsim răspunsul!"

    # ── Statistici ────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        return {
            "calls": self._call_count,
            "tokens": self._total_tokens,
            "cache_hits": len(self._cache),
            "model": self.model,
        }


# ─── Test standalone ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("🤖 TEST DEEPSEEK CLIENT")
    print("=" * 60)

    ds = DeepSeekClient()
    print(f"\nDisponibil: {ds.available}")

    if ds.available:
        print("\n1. Test răspuns simplu:")
        r = ds.ask("Spune 'Funcționez!' în română, doar atât.")
        print(f"   Răspuns: {r}")

        print("\n2. Test verificare răspuns:")
        ok, feedback = ds.check_answer(
            enunt="3 + 4 = ?",
            raspuns_corect="7",
            raspuns_elev="7",
            grade=1
        )
        print(f"   Corect: {ok}")
        print(f"   Feedback: {feedback}")

        print("\n3. Test explicație:")
        expl = ds.explain_for_student("adunarea", grade=1)
        print(f"   Explicație: {expl[:150]}...")

        print("\n4. Test generare exerciții:")
        ex = ds.generate_exercises(
            "Adunarea până la 10", grade=1, subject="Matematică",
            count=2, phase="practice"
        )
        for i, e in enumerate(ex, 1):
            print(f"   Exercițiu {i}: {e.get('enunt', 'N/A')}")
            print(f"               Răspuns: {e.get('raspuns', 'N/A')}")

        print(f"\n📊 Statistici: {ds.get_stats()}")
    else:
        print("\nOllama nu rulează. Pornește cu: ollama serve")
        print("Și instalează modelul: ollama pull deepseek-r1:7b")
