from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kdp_pipeline.core.hashing import sha256_text
from kdp_pipeline.providers.contracts import RenderedPrompt


_VERSIONED_NAME = re.compile(r"^(?P<stem>.+)-v(?P<version>\d+(?:\.\d+)+)\.md$")
_VARIABLE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*}}")


class PromptRegistryError(ValueError):
    pass


class PromptNotFoundError(PromptRegistryError):
    pass


class MissingPromptVariableError(PromptRegistryError):
    pass


@dataclass(frozen=True)
class PromptTemplate:
    template_id: str
    template_version: str
    path: Path
    source_text: str


class PromptRegistry:
    """Deterministic registry for prompts named ``{id}-v{dotted-version}.md``."""

    def __init__(self, prompts_root: Path):
        self.prompts_root = prompts_root.resolve()
        self._templates = self._discover()

    def _discover(self) -> dict[tuple[str, str], PromptTemplate]:
        if not self.prompts_root.is_dir():
            raise PromptRegistryError(f"Prompt directory does not exist: {self.prompts_root}")

        templates: dict[tuple[str, str], PromptTemplate] = {}
        for path in sorted(self.prompts_root.rglob("*.md")):
            match = _VERSIONED_NAME.match(path.name)
            if not match:
                raise PromptRegistryError(
                    "Prompt filename must match {template-id}-v{dotted-version}.md: "
                    f"{path.relative_to(self.prompts_root)}"
                )
            relative = path.relative_to(self.prompts_root).with_suffix("")
            template_id = (relative.parent / match.group("stem")).as_posix()
            template_version = match.group("version")
            key = (template_id, template_version)
            if key in templates:
                raise PromptRegistryError(f"Duplicate prompt template: {template_id} v{template_version}")
            templates[key] = PromptTemplate(
                template_id=template_id,
                template_version=template_version,
                path=path,
                source_text=path.read_text(encoding="utf-8"),
            )
        return templates

    def load(self, template_id: str, template_version: str | None = None) -> PromptTemplate:
        matches = [
            template for (candidate_id, _), template in self._templates.items()
            if candidate_id == template_id
        ]
        if not matches:
            raise PromptNotFoundError(f"Unknown prompt template: {template_id}")
        if template_version is None:
            if len(matches) != 1:
                versions = ", ".join(sorted(t.template_version for t in matches))
                raise PromptRegistryError(
                    f"Prompt version is required for {template_id}; available versions: {versions}"
                )
            return matches[0]
        try:
            return self._templates[(template_id, template_version)]
        except KeyError as exc:
            raise PromptNotFoundError(
                f"Unknown prompt template version: {template_id} v{template_version}"
            ) from exc

    def render(
        self,
        template_id: str,
        variables: dict[str, Any],
        template_version: str | None = None,
    ) -> RenderedPrompt:
        template = self.load(template_id, template_version)
        names = list(dict.fromkeys(_VARIABLE.findall(template.source_text)))
        missing = [name for name in names if name not in variables]
        if missing:
            raise MissingPromptVariableError(
                f"Missing variables for {template_id} v{template.template_version}: "
                + ", ".join(missing)
            )

        rendered = _VARIABLE.sub(lambda match: str(variables[match.group(1)]), template.source_text)
        return RenderedPrompt(
            template_id=template.template_id,
            template_version=template.template_version,
            rendered_text=rendered,
            rendered_sha256=sha256_text(rendered),
        )
