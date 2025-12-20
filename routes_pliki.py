import os
from flask import (
    render_template,
    send_from_directory,
    request,
    redirect,
    url_for,
    flash,
    abort,
)
from werkzeug.utils import secure_filename
from permissions import wymaga_roli

# Katalog z plikami do pobrania
DOWNLOADS_DIR = os.path.join("static", "downloads")

# Dozwolone rozszerzenia
ALLOWED_EXTENSIONS = {
    "pdf", "zip", "md", "txt",
    "png", "jpg", "jpeg", "webp",
}

MAX_FILE_SIZE_MB = 50  # na przyszłość, gdybyś chciał dodać limit rozmiaru


def allowed_file(filename: str) -> bool:
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def init_pliki_routes(app):
    # ---------------------------------------------------------
    # LISTA PLIKÓW DO POBRANIA
    # ---------------------------------------------------------
    @app.route("/pliki/pobierz")
    def pliki_pobranie():
        if not os.path.exists(DOWNLOADS_DIR):
            files = []
        else:
            files = []
            for filename in os.listdir(DOWNLOADS_DIR):
                path = os.path.join(DOWNLOADS_DIR, filename)
                if os.path.isfile(path):
                    size_kb = round(os.path.getsize(path) / 1024, 1)
                    files.append(
                        {
                            "name": filename,
                            "size": size_kb,
                        }
                    )

        # Sortowanie alfabetyczne
        files.sort(key=lambda x: x["name"].lower())

        return render_template("pliki_pobranie.html", files=files)

    # ---------------------------------------------------------
    # POBIERANIE KONKRETNEGO PLIKU
    # ---------------------------------------------------------
    @app.route("/pliki/pobierz/<path:filename>")
    def pobierz_plik(filename):
        # Proste zabezpieczenie ścieżki
        if ".." in filename or filename.startswith("/"):
            abort(404)

        file_path = os.path.join(DOWNLOADS_DIR, filename)
        if not os.path.isfile(file_path):
            abort(404)

        return send_from_directory(
            DOWNLOADS_DIR,
            filename,
            as_attachment=True,
        )

    # ---------------------------------------------------------
    # UPLOAD PLIKÓW
    # ---------------------------------------------------------
    @app.route("/pliki/upload", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def pliki_upload():
        if request.method == "POST":
            if "file" not in request.files:
                flash("Nie wybrano pliku.", "error")
                return redirect(request.url)

            file = request.files["file"]

            if file.filename == "":
                flash("Nie wybrano pliku.", "error")
                return redirect(request.url)

            if not allowed_file(file.filename):
                flash("Niedozwolony typ pliku.", "error")
                return redirect(request.url)

            # Zabezpieczenie nazwy
            filename = secure_filename(file.filename)

            os.makedirs(DOWNLOADS_DIR, exist_ok=True)
            file_path = os.path.join(DOWNLOADS_DIR, filename)

            # Sprawdzenie nadpisania
            if os.path.exists(file_path):
                flash("Plik o takiej nazwie już istnieje.", "error")
                return redirect(request.url)

            # Zapis pliku
            try:
                file.save(file_path)
                flash("Plik został pomyślnie dodany.", "success")
                return redirect(url_for("pliki_pobranie"))
            except Exception as e:
                flash(f"Błąd zapisu pliku: {e}", "error")
                return redirect(request.url)

        return render_template("pliki_upload.html")

    @app.route("/pliki/usun/<path:filename>", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def plik_usun(filename):

        # 🔒 zabezpieczenie nazwy pliku
        filename = secure_filename(filename)

        if not filename:
            abort(404)

        file_path = os.path.join(DOWNLOADS_DIR, filename)

        # 🔍 sprawdzenie istnienia
        if not os.path.isfile(file_path):
            flash("Plik nie istnieje lub został już usunięty.", "error")
            return redirect(url_for("pliki_pobranie"))

        try:
            os.remove(file_path)
            flash(f"Plik „{filename}” został usunięty.", "success")

        except Exception as e:
            flash(f"Błąd podczas usuwania pliku: {e}", "error")

        return redirect(url_for("pliki_pobranie"))