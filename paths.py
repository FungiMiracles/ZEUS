# paths.py
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

FLAGI_DIR = os.path.join(BASE_DIR, "static", "flags")
MAPY_DIR = os.path.join(BASE_DIR, "static", "maps")

DESCRIPTIONS_FOLDER = os.path.join(BASE_DIR, "static", "descriptions")

# 🆕 OPISY WYDARZEŃ HISTORYCZNYCH
EVENTS_DESCRIPTIONS_FOLDER = os.path.join(DESCRIPTIONS_FOLDER, "events")

INFO_FILE = os.path.join(BASE_DIR, "static", "info", "info.md")
