"""Screenshot pages of the running site, so the design can be looked at.

    python shoot.py http://127.0.0.1:8010 out/  [--dark]

Uses QtWebEngine, which PySide6 already provides -- no extra browser download.
"""
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QPageSize
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "shots")
DARK = "--dark" in sys.argv

PAGES = ["index.html", "features.html", "calculator.html",
         "documentation.html", "download.html"]

app = QApplication(sys.argv)
if DARK:
    # Qt maps this to prefers-color-scheme for the page.
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)

view = QWebEngineView()
view.resize(1280, 1000)
view.show()
OUT.mkdir(parents=True, exist_ok=True)
queue = list(PAGES)
current = {"name": None}


def shoot_next():
    if not queue:
        print(f"\n{len(PAGES)} screenshots in {OUT}")
        app.quit()
        return
    current["name"] = queue.pop(0)
    view.load(QUrl(f"{BASE}/{current['name']}"))


def on_load(ok):
    name = current["name"]
    if not ok:
        print(f"  FAILED to load {name}")
        QTimer.singleShot(50, shoot_next)
        return
    # Give fonts/JS a moment; this page has no network dependencies.
    def grab():
        suffix = "_dark" if DARK else ""
        p = OUT / f"{Path(name).stem}{suffix}.png"
        view.grab().save(str(p))
        print(f"  {p}")
        QTimer.singleShot(50, shoot_next)
    QTimer.singleShot(900, grab)


view.loadFinished.connect(on_load)
QTimer.singleShot(300, shoot_next)
sys.exit(app.exec())
