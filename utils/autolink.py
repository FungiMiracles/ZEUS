import re

from markupsafe import Markup

from models import (
    Panstwo,
    Region,
    Miasto
)


def _build_objects():

    objects = []

    for p in Panstwo.query.with_entities(
        Panstwo.PANSTWO_ID,
        Panstwo.panstwo_nazwa
    ).all():

        if p.panstwo_nazwa:
            objects.append({
                "name": p.panstwo_nazwa,
                "url": f"/panstwo/{p.PANSTWO_ID}"
            })

    for r in Region.query.with_entities(
        Region.region_id,
        Region.region_nazwa
    ).all():

        if r.region_nazwa:
            objects.append({
                "name": r.region_nazwa,
                "url": f"/region/{r.region_id}"
            })

    for m in Miasto.query.with_entities(
        Miasto.miasto_id,
        Miasto.miasto_nazwa
    ).all():

        if m.miasto_nazwa:
            objects.append({
                "name": m.miasto_nazwa,
                "url": f"/miasto/{m.miasto_id}"
            })

    # najpierw dłuższe nazwy
    objects.sort(
        key=lambda x: len(x["name"]),
        reverse=True
    )

    return objects


def autolink_description(text):

    if not text:
        return Markup("")

    objects = _build_objects()

    # zabezpieczenie istniejących linków
    placeholders = {}

    def hide_links(match):
        key = f"__LINK_{len(placeholders)}__"
        placeholders[key] = match.group(0)
        return key

    text = re.sub(
        r"<a\b[^>]*>.*?</a>",
        hide_links,
        text,
        flags=re.IGNORECASE | re.DOTALL
    )

    for obj in objects:

        escaped = re.escape(obj["name"])

        pattern = (
            rf"(?<![\w>])"
            rf"({escaped})"
            rf"(?![\w<])"
        )

        replacement = (
            f'<a href="{obj["url"]}" '
            f'target="_blank" '
            f'class="zeus-autolink">\\1</a>'
        )

        text = re.sub(
            pattern,
            replacement,
            text,
            flags=re.IGNORECASE
        )

    # przywrócenie istniejących linków
    for key, value in placeholders.items():
        text = text.replace(key, value)

    return Markup(text)