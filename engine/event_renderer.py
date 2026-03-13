from jinja2 import Template
from engine.event_context import build_event_context


def render_event_description(event, template_text):

    context = build_event_context(event)

    template = Template(template_text)

    return template.render(**context)

