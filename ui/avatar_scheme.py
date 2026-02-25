"""
ui/avatar_scheme.py
===================
QWebEngineUrlSchemeHandler pentru schema "avatar://".

Înlocuiește subprocess.Popen(["python", "-m", "http.server", "8000"]).
Servește fișierele din assets/avatar/ direct din memorie, fără port de rețea.

Înregistrare (TREBUIE făcută ÎNAINTE de QApplication):
    from PyQt6.QtWebEngineCore import QWebEngineUrlScheme
    _sch = QWebEngineUrlScheme(b"avatar")
    _sch.setFlags(QWebEngineUrlScheme.Flag.SecureScheme |
                  QWebEngineUrlScheme.Flag.LocalScheme  |
                  QWebEngineUrlScheme.Flag.LocalAccessAllowed)
    QWebEngineUrlScheme.registerScheme(_sch)

Instalare (după QApplication):
    from PyQt6.QtWebEngineCore import QWebEngineProfile
    from ui.avatar_scheme import AvatarSchemeHandler
    _handler = AvatarSchemeHandler()
    QWebEngineProfile.defaultProfile().installUrlSchemeHandler(b"avatar", _handler)

URL de folosit în QWebEngineView:
    view.setUrl(QUrl("avatar://localhost/viewer.html"))
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtWebEngineCore import QWebEngineUrlSchemeHandler, QWebEngineUrlRequestJob


_MIME_MAP: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".htm":  "text/html; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".mjs":  "application/javascript; charset=utf-8",
    ".json": "application/json",
    ".glb":  "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg":  "image/svg+xml",
    ".css":  "text/css",
    ".txt":  "text/plain",
}


class AvatarSchemeHandler(QWebEngineUrlSchemeHandler):
    """Servește fișierele din assets/avatar/ pe schema avatar://."""

    # Directorul rădăcină: assets/avatar/ relativ la locul acestui fișier (ui/)
    BASE: Path = Path(__file__).resolve().parent.parent / "assets" / "avatar"

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:  # type: ignore[override]
        raw_path = job.requestUrl().path().lstrip("/")
        # Pagina principală implicită
        if not raw_path:
            raw_path = "viewer.html"

        file_path = (self.BASE / raw_path).resolve()

        # Protecție path traversal: fișierul trebuie să fie sub BASE
        try:
            file_path.relative_to(self.BASE)
        except ValueError:
            job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)
            return

        if not file_path.exists() or not file_path.is_file():
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return

        mime = _MIME_MAP.get(file_path.suffix.lower(), "application/octet-stream")

        try:
            data = file_path.read_bytes()
        except OSError:
            job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)
            return

        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.ReadWrite)
        buf.write(data)
        buf.seek(0)
        job.reply(mime.encode("ascii"), buf)
