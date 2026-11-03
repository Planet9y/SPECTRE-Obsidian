"""Native SPECTRE desktop shell, embedding the existing local UI in Qt WebEngine."""
from __future__ import annotations

import secrets
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from ghost.webapp import Engine, create_handler


def main():
    # Import here so the backend's headless tests don't require Qt.
    from PySide6.QtCore import QUrl, Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow
    from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView

    app = QApplication(sys.argv)
    app.setApplicationName("SPECTRE")
    app.setOrganizationName("SPECTRE")
    engine = Engine()
    token = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(engine, token))
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    worker.start()

    window = QMainWindow()
    window.setWindowTitle("SPECTRE // OBSIDIAN")
    window.resize(1600, 960)
    window.setMinimumSize(1050, 650)
    window.setStyleSheet("QMainWindow { background-color: #090810; }")
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    icon = root / "assets" / "spectre.ico"
    if icon.exists():
        window.setWindowIcon(QIcon(str(icon)))
        app.setWindowIcon(QIcon(str(icon)))

    view = QWebEngineView(window)
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
    window.setCentralWidget(view)

    def save_download(download):
        filename = download.downloadFileName()
        target, _ = QFileDialog.getSaveFileName(window, "Export SPECTRE data", filename, "CSV files (*.csv);;All files (*)")
        if not target:
            download.cancel()
            return
        chosen = Path(target)
        download.setDownloadDirectory(str(chosen.parent))
        download.setDownloadFileName(chosen.name)
        download.accept()

    view.page().profile().downloadRequested.connect(save_download)
    view.setUrl(QUrl(f"http://127.0.0.1:{server.server_port}/?token={token}"))

    # Stop the local server and sampler on window close, not when a browser tab closes.
    def shutdown():
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
        engine.close()

    app.aboutToQuit.connect(shutdown)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
