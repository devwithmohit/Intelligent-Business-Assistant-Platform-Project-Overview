import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    _JINJA_AVAILABLE = True
except Exception:
    _JINJA_AVAILABLE = False


_DEFAULT_TEMPLATES_DIR = os.getenv(
    "TEMPLATES_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "templates"),
)


class TemplateError(Exception):
    pass


class TemplateManager:
    def __init__(self, templates_dir: Optional[str] = None) -> None:
        self.templates_dir = (
            Path(templates_dir or _DEFAULT_TEMPLATES_DIR).expanduser().resolve()
        )
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, str] = {}
        if _JINJA_AVAILABLE:
            # Only load filesystem loader from templates_dir
            self._env = Environment(
                loader=FileSystemLoader(str(self.templates_dir)),
                autoescape=select_autoescape(["html", "xml"]),
            )
        else:
            self._env = None
        logger.debug(
            "TemplateManager initialized dir=%s jinja=%s",
            self.templates_dir,
            _JINJA_AVAILABLE,
        )

    def list_templates(self) -> List[str]:
        """Return list of template filenames in the templates directory."""
        files = [p.name for p in self.templates_dir.glob("*.j2")] + [
            p.name for p in self.templates_dir.glob("*.tpl")
        ]
        # include raw .txt templates as well
        files += [p.name for p in self.templates_dir.glob("*.txt")]
        # unique, stable ordering
        seen = []
        for f in files:
            if f not in seen:
                seen.append(f)
        return seen

    def load_template(self, name: str) -> str:
        """Load template content from disk (cached). Name may include extension."""
        path = self.templates_dir / name
        if not path.exists():
            # try adding .j2 then .txt
            for ext in (".j2", ".tpl", ".txt"):
                p2 = self.templates_dir / f"{name}{ext}"
                if p2.exists():
                    path = p2
                    break
        if not path.exists():
            raise TemplateError(f"template not found: {name}")
        # use cache to avoid repeated IO
        key = str(path)
        if key in self._cache:
            return self._cache[key]
        content = path.read_text(encoding="utf-8")
        self._cache[key] = content
        return content

    def save_template(self, name: str, content: str, overwrite: bool = True) -> str:
        """Save template content to templates dir. Returns saved filename."""
        # ensure sane filename
        safe_name = (
            name
            if any(name.endswith(ext) for ext in (".j2", ".tpl", ".txt"))
            else f"{name}.j2"
        )
        path = self.templates_dir / safe_name
        if path.exists() and not overwrite:
            raise TemplateError(f"template exists and overwrite=False: {safe_name}")
        path.write_text(content, encoding="utf-8")
        # invalidate cache
        self._cache.pop(str(path), None)
        # if using jinja env, reload template by name is handled by loader next time
        return safe_name

    def render_template(
        self, name: str, context: Optional[Dict[str, object]] = None
    ) -> str:
        """
        Render a named template with provided context.
        Uses Jinja2 when available; otherwise falls back to safe python formatting.
        """
        ctx = context or {}
        if _JINJA_AVAILABLE and self._env is not None:
            try:
                # Environment loader expects filename only (not path)
                tmpl_name = name if (self.templates_dir / name).exists() else name
                tmpl = self._env.get_template(tmpl_name)
                return tmpl.render(**ctx)
            except Exception as e:
                logger.exception("jinja render failed for %s: %s", name, e)
                raise TemplateError(f"render failed: {e}") from e
        # fallback: load raw template and perform simple {key} replacements using str.format
        try:
            raw = self.load_template(name)
            # avoid raising on missing keys by converting all values to str and using format_map
            safe_ctx = {k: ("" if v is None else str(v)) for k, v in ctx.items()}
            return raw.format_map(DefaultDict(safe_ctx))
        except Exception as e:
            logger.exception("fallback render failed for %s: %s", name, e)
            raise TemplateError(f"render failed: {e}") from e


class DefaultDict(dict):
    """Helper that returns empty string for missing keys when used with format_map."""

    def __missing__(self, key):
        return ""


# module-level singleton for convenience
_default_manager: Optional[TemplateManager] = None


def _get_setting(name: str, default: Optional[str] = None) -> Optional[str]:
    try:
        from ..core import config as core_config  # type: ignore

        return getattr(core_config.settings, name, os.getenv(name, default))
    except Exception:
        return os.getenv(name, default)


def get_manager() -> TemplateManager:
    global _default_manager
    if _default_manager is None:
        dir_override = _get_setting("TEMPLATES_DIR")
        _default_manager = TemplateManager(
            templates_dir=dir_override or _DEFAULT_TEMPLATES_DIR
        )
    return _default_manager


# convenience module-level functions
def list_templates() -> List[str]:
    return get_manager().list_templates()


def load_template(name: str) -> str:
    return get_manager().load_template(name)


def save_template(name: str, content: str, overwrite: bool = True) -> str:
    return get_manager().save_template(name, content, overwrite=overwrite)


def render_template(name: str, context: Optional[Dict[str, object]] = None) -> str:
    return get_manager().render_template(name, context=context)
