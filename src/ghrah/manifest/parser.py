# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from ghrah.manifest.ability import AbilityManifest
from ghrah.manifest.agent import AgentManifest
from ghrah.manifest.errors import ManifestValidationError, ManifestVersionError


def parse_ability_manifest(raw: str, format: str = "yaml") -> AbilityManifest:
    data = _load_raw(raw, format)
    try:
        return AbilityManifest.model_validate(data)
    except (PydanticValidationError, ManifestVersionError) as exc:
        raise ManifestValidationError(str(exc)) from exc


def parse_agent_manifest(raw: str, format: str = "yaml") -> AgentManifest:
    data = _load_raw(raw, format)
    try:
        return AgentManifest.model_validate(data)
    except (PydanticValidationError, ManifestVersionError) as exc:
        raise ManifestValidationError(str(exc)) from exc


def validate_manifest(raw: str, format: str = "yaml") -> tuple[bool, list[str]]:
    try:
        data = _load_raw(raw, format)
    except Exception as exc:
        return False, [f"Parse error: {exc}"]

    manifest_type = data.get("manifest", "")
    if manifest_type == "ability":
        return _validate_model(data, AbilityManifest)
    elif manifest_type == "agent":
        return _validate_model(data, AgentManifest)
    else:
        return False, [f"Unknown or missing manifest type: {manifest_type!r}"]


def _load_raw(raw: str, format: str) -> dict[str, Any]:
    if format == "yaml":
        result = yaml.safe_load(raw)
        if not isinstance(result, dict):
            raise ValueError("YAML content is not a mapping")
        return result
    elif format == "json":
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("JSON content is not a mapping")
        return data
    else:
        raise ValueError(f"Unsupported format: {format!r}")


def _validate_model(
    data: dict[str, Any], model_cls: type[BaseModel]
) -> tuple[bool, list[str]]:
    try:
        model_cls.model_validate(data)
        return True, []
    except PydanticValidationError as exc:
        errors = [
            f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
            for e in exc.errors()
        ]
        return False, errors
