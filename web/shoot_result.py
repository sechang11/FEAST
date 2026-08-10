"""Drive the calculator to a solved state and screenshot it."""
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "shots")

DRIVE = """
(async () => {
  const $ = (id) => document.getElementById(id);
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  $("sample").value = "system1"; $("load-sample").click();
  for (let i=0;i<60 && !$("matrix").value.trim();i++) await sleep(200);
  await sleep(300);
  $("emin").value = 0.18; $("emax").value = 1.0; $("m0").value = 30;
  $("solve").click();
  for (let i=0;i<200 && ($("solveinfo").textContent.includes("solving") || !$("solveinfo").textContent);i++) await sleep(250);
  window.scrollTo(0, document.body.scrollHeight * 0.42);
  return $("solveinfo").textContent;
})()
"""

app = QApplication(sys.argv)
view = QWebEngineView()
view.resize(1280, 1100)
view.show()
OUT.mkdir(parents=True, exist_ok=True)


def on_load(ok):
    if not ok:
        print("load failed"); app.quit(); return

    def drive():
        view.page().runJavaScript(DRIVE, lambda r: print("  solve:", r))
        QTimer.singleShot(9000, grab)

    def grab():
        p = OUT / "calculator_result.png"
        view.grab().save(str(p))
        print(f"  {p}")
        app.quit()

    QTimer.singleShot(800, drive)


view.loadFinished.connect(on_load)
view.load(QUrl(f"{BASE}/calculator.html"))
sys.exit(app.exec())
