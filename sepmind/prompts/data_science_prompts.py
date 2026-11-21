# Derived from Google Health PHA, Apache-2.0; see LICENSE.txt and docs/engineering/UPSTREAM_BASE.md.
# Only shared behavior used by the separation-design extension remains active.
import jinja2

def render_prompt(template: str, **kwargs) -> str:
    """Render a Jinja2 template with the given variables."""
    env = jinja2.Environment(
        loader=jinja2.BaseLoader(),
        undefined=jinja2.StrictUndefined,
    )
    jinja_template = env.from_string(template)
    return jinja_template.render(**kwargs)
