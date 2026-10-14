"""Build a v1 support bundle from cached, explicitly selected metadata."""
import platform

try:
    from .version import VERSION
    from .operation_records import VERSION as OPERATION_VERSION, safe_number, next_step
except ImportError:
    from version import VERSION
    from operation_records import VERSION as OPERATION_VERSION, safe_number, next_step


CAPABILITIES = {"support_bundle_version": 1, "operation_record_version": OPERATION_VERSION}


def support_bundle(history, latest, writes_enabled):
    rows = history.selected(20) if history else []
    return {"schema_version": 1, "versions": {"manager": VERSION, "python": platform.python_version()},
            "capabilities": dict(CAPABILITIES, writes_enabled=bool(writes_enabled)),
            "metrics": {key: safe_number(latest.get(key)) for key in ("t", "mk", "ma", "mt", "rc", "rf", "rp")},
            "operations": rows, "history": history.summary() if history else {"history_available": False},
            "failures": [{"reason_code": row["reason_code"], "outcome": row["outcome"],
                          "operation_id": row["operation_id"], "correlation_id": row["correlation_id"],
                          "next_step": next_step("outcome_unknown" if row["outcome"] == "unknown" else row["reason_code"])}
                         for row in rows if row["outcome"] != "succeeded"]}
