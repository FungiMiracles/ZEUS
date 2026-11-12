from flask import render_template, request, redirect, url_for, Response, flash
from extensions import db
from models import Artykul
from permissions import wymaga_roli

def init_artykuly_routes(app):

    @app.route("/artykuly/lista")
    def artykuly_lista():

        tytul = request.args.get("tytul")
        autor = request.args.get("autor")
        data = request.args.get("data")

        query = Artykul.query

        if tytul:
            query = query.filter(Artykul.artykul_tytul.like(f"%{tytul}%"))

        if autor:
            query = query.filter(Artykul.artykul_autor.like(f"%{autor}%"))

        if data:
            query = query.filter(db.func.date(Artykul.data_utworzenia) == data)

        artykuly = query.order_by(Artykul.artykul_id.desc()).all()

        return render_template("artykuly_lista.html", artykuly=artykuly)

    @app.route("/artykul/<int:id>")
    def artykul_form(id):
        a = Artykul.query.get_or_404(id)
        return render_template("artykul_form.html", a=a)

    @app.route("/artykul/add", methods=["GET", "POST"])
    @wymaga_roli("tworzyciel", "wszechmocny")
    def artykul_add():

        if request.method == "POST":

            tytul = request.form.get("tytul")
            tresc = request.form.get("tresc")
            autor = request.form.get("autor")
            data_pub = request.form.get("data_publikacji")

            file = request.files.get("obraz")

            errors = []

            if not tytul:
                errors.append("Tytuł wymagany")
            if not tresc:
                errors.append("Treść wymagana")
            if not autor:
                errors.append("Autor wymagany")
            if not file or not file.filename:
                errors.append("Obraz wymagany")

            if errors:
                return render_template("artykul_form_add.html", error=" ".join(errors))

            a = Artykul(
                artykul_tytul=tytul,
                artykul_tresc=tresc,
                artykul_autor=autor,
                data_publikacji=data_pub or None
            )

            if file:
                a.artykul_obraz = file.read()
                a.artykul_obraz_mime = file.mimetype

            db.session.add(a)
            db.session.commit()

            return redirect(url_for("artykul_form", id=a.artykul_id))

        return render_template("artykul_form_add.html")

    @app.route("/artykul/<int:id>/edit", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def artykul_edit(id):

        a = Artykul.query.get_or_404(id)

        if request.method == "POST":

            a.artykul_tytul = request.form.get("tytul")
            a.artykul_tresc = request.form.get("tresc")
            a.artykul_autor = request.form.get("autor")
            a.data_publikacji = request.form.get("data_publikacji") or None

            file = request.files.get("obraz")

            if file and file.filename:
                a.artykul_obraz = file.read()
                a.artykul_obraz_mime = file.mimetype

            db.session.commit()

            return redirect(url_for("artykul_form", id=a.artykul_id))

        return render_template("artykul_form_edit.html", a=a)

    @app.route("/artykul/<int:id>/delete", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def artykul_delete(id):

        a = Artykul.query.get_or_404(id)

        db.session.delete(a)
        db.session.commit()

        return redirect(url_for("artykuly_lista"))

    @app.route("/artykul/<int:id>/obraz")
    def artykul_obraz(id):
        a = Artykul.query.get_or_404(id)

        return Response(
            a.artykul_obraz,
            mimetype=a.artykul_obraz_mime or "image/jpeg"
        )