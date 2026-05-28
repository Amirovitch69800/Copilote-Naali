"""
launcher.py — Point d'entrée PyInstaller (Windows)
Lance Flask en local et ouvre le navigateur automatiquement.
"""
import sys
import os
import threading
import webbrowser
import time
import socket

# ── Répertoire de base (frozen = exe PyInstaller, sinon développement) ────────
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

# ── Import Flask app ──────────────────────────────────────────────────────────
from web.app import app

# Correction chemins Flask quand frozen (templates / static)
if getattr(sys, 'frozen', False):
    app.template_folder = os.path.join(BASE_DIR, 'web', 'templates')
    app.static_folder   = os.path.join(BASE_DIR, 'web', 'static')
    app.root_path       = os.path.join(BASE_DIR, 'web')

# ── Utilitaires ───────────────────────────────────────────────────────────────
def port_libre(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) != 0


def ouvrir_navigateur(port: int):
    time.sleep(2)
    webbrowser.open(f'http://127.0.0.1:{port}')


# ── Lancement ─────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    PORT = 5001
    if not port_libre(PORT):
        with socket.socket() as s:
            s.bind(('', 0))
            PORT = s.getsockname()[1]

    threading.Thread(target=ouvrir_navigateur, args=(PORT,), daemon=True).start()

    try:
        app.run(host='127.0.0.1', port=PORT, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, str(e), "Naali Planner - Erreur", 0x10)
        except Exception:
            input(f"Erreur: {e}\nAppuie sur Entrée pour quitter...")
