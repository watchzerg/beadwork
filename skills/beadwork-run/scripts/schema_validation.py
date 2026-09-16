"""受控 Draft 7 子集与严格 JSON 读取；不依赖任何工作流控制器。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

import evidence


def object_schema(properties: Dict[str, Any], optional: Tuple[str, ...] = ()) -> Dict[str, Any]:
    return {"type": "object", "properties": properties,
            "required": [key for key in properties if key not in optional],
            "additionalProperties": False}


TEXT = {"type": "string", "pattern": r"\S"}
SHA = {"type": "string", "pattern": r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"}
TEXTS = {"type": "array", "items": TEXT}
SEAMS = {**TEXTS, "uniqueItems": True}


def schema_errors(value: Any, schema: Dict[str, Any], path: str = "$") -> List[str]:
    errors: List[str] = []
    kind = schema.get("type")
    matches = {"object": isinstance(value, dict), "array": isinstance(value, list),
               "string": isinstance(value, str), "boolean": isinstance(value, bool),
               "integer": isinstance(value, (int, float)) and not isinstance(value, bool)
               and (isinstance(value, int) or value.is_integer()), "null": value is None}
    if kind is not None and not matches[kind]:
        return [path + ": expected " + kind]
    if "enum" in schema and not any(isinstance(value, bool) == isinstance(item, bool) and value == item
                                     for item in schema["enum"]):
        errors.append(path + ": enum")
    if "const" in schema and (isinstance(value, bool) != isinstance(schema["const"], bool)
                              or value != schema["const"]):
        errors.append(path + ": const")
    if isinstance(value, dict):
        errors.extend(path + "." + key + ": required" for key in schema.get("required", []) if key not in value)
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                errors.extend(schema_errors(item, properties[key], path + "." + key))
            elif schema.get("additionalProperties") is False:
                errors.append(path + "." + key + ": unexpected")
            elif isinstance(schema.get("additionalProperties"), dict):
                errors.extend(schema_errors(item, schema["additionalProperties"], path + "." + key))
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            errors.append(path + ": item count")
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value]
            if len(encoded) != len(set(encoded)):
                errors.append(path + ": duplicate items")
        if "items" in schema:
            for index, item in enumerate(value):
                errors.extend(schema_errors(item, schema["items"], f"{path}[{index}]"))
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(path + ": minLength")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(path + ": pattern")
    for name in ("anyOf", "oneOf"):
        if name in schema:
            matching = sum(not schema_errors(value, item, path) for item in schema[name])
            if matching == 0 or (name == "oneOf" and matching != 1):
                errors.append(path + ": " + name)
    for item in schema.get("allOf", []):
        errors.extend(schema_errors(value, item, path))
    if "not" in schema and not schema_errors(value, schema["not"], path):
        errors.append(path + ": not")
    if "if" in schema:
        branch = "else" if schema_errors(value, schema["if"], path) else "then"
        if branch in schema:
            errors.extend(schema_errors(value, schema[branch], path))
    return errors


def check_schema(schema: Any) -> None:
    allowed = {"$schema", "title", "description", "type", "properties", "required",
               "additionalProperties", "items", "minItems", "maxItems", "uniqueItems",
               "minLength", "pattern", "enum", "const", "anyOf", "oneOf", "allOf", "not",
               "if", "then", "else"}
    if not isinstance(schema, dict) or set(schema) - allowed:
        raise ValueError("schema 含不支持的规则")
    if "type" in schema and schema["type"] not in ("object", "array", "string", "boolean", "integer", "null"):
        raise ValueError("schema 含不支持的 type")
    for child in schema.get("properties", {}).values():
        check_schema(child)
    if isinstance(schema.get("additionalProperties"), dict):
        check_schema(schema["additionalProperties"])
    for key in ("items", "not", "if", "then", "else"):
        if key in schema:
            check_schema(schema[key])
    for key in ("anyOf", "oneOf", "allOf"):
        for child in schema.get(key, []):
            check_schema(child)


def read_json(path: str):
    return evidence.read_with_digest(path)
