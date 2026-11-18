"""Observe raw generation responses without taking over the pipeline's recovery."""
import json

from medtrace.note import ParseError, note_from_model


def _reject_constant(value):
    raise ValueError(f"{value} is not a JSON constant")


def observe_response(status, body):
    metrics = {"http_success": status == 200, "status": status, "strict_json": False,
               "json_object": False, "three_sections": False}
    try:
        obj = json.loads(body)
        if status != 200:
            error = obj.get("error") or obj
            metrics["provider_code"] = str(error.get("code", ""))[:80]
            return metrics
        choice = obj["choices"][0]
        metrics["finish_reason"] = choice.get("finish_reason")
        content = json.loads(choice["message"]["content"], parse_constant=_reject_constant)
        metrics["strict_json"] = True
        if isinstance(content, dict):
            metrics["json_object"] = True
            note_from_model(content, require_complete=True)
            metrics["three_sections"] = True
    except (ParseError, ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError):
        pass
    return metrics
