# markdown_utils.py
import os
import markdown
from paths import DESCRIPTIONS_FOLDER

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

EVENT_MD_DIR = os.path.join(
    BASE_DIR,
    "static",
    "descriptions",
    "event"
)

def get_event_description(rok, slug):
    """
    Szuka pliku w formacie:
    {rok}_{slug}.md
    np. 1450_bitwa-pod-innomeburgiem.md
    """
    filename = f"{rok}_{slug}.md"
    path = os.path.join(EVENT_MD_DIR, filename)

    if not os.path.exists(path):
        return "_Brak opisu wydarzenia._"

    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_panstwo_description(panstwo_nazwa: str):
    """
    Zwraca HTML wygenerowany z pliku Markdown opisu państwa.
    Nazwa pliku: panstwo_nazwa z _ zamiast spacji, rozszerzenie .md
    """
    filename = panstwo_nazwa.replace(" ", "_") + ".md"
    filepath = os.path.join(DESCRIPTIONS_FOLDER, filename)

    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            html_content = markdown.markdown(
                content, extensions=["tables", "fenced_code"]
            )
            return html_content
        return None
    except Exception as e:
        # Możesz to zamienić na logger
        print(f"Błąd podczas odczytywania opisu: {e}")
        return None

def get_panstwo_description_raw(panstwo_nazwa: str):
    filename = panstwo_nazwa.replace(" ", "_") + ".md"
    filepath = os.path.join(DESCRIPTIONS_FOLDER, filename)

    if not os.path.exists(filepath):
        return ""

    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()