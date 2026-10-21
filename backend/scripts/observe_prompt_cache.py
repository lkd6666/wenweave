"""Read-only, token-weighted rollout report; separates synthetic acceptance traffic."""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: F401
from app.db.session import SessionLocal
from app.models.ai_model import AIModel
from app.models.model_call_record import ModelCallRecord, ModelCallSource

DIRECTORY = Path(__file__).resolve().parents[2] / "outputs/cache-optimization-20261012"


def aggregate(records):
    reported = [record for record in records if record.usage_reported]
    inputs = sum(record.input_tokens or 0 for record in reported)
    reads = sum(record.cache_read_tokens or 0 for record in reported)
    latencies = sorted((record.finished_at - record.started_at).total_seconds()
                       for record in records if record.finished_at)
    return {"calls": len(records), "reported_calls": len(reported), "input_tokens": inputs,
            "cache_read_tokens": reads, "cache_write_tokens": sum(record.cache_write_tokens or 0 for record in reported),
            "uncached_input_tokens": inputs - reads, "weighted_hit_rate": reads / inputs if inputs else None,
            "median_seconds": statistics.median(latencies) if latencies else None,
            "p95_seconds": latencies[min(len(latencies) - 1, int(len(latencies) * .95))] if latencies else None,
            "failed_calls": sum(str(record.status.value) in {"failed", "abandoned"} for record in records)}


def main():
    rollout = json.loads((DIRECTORY / "rollout.json").read_text(encoding="utf-8"))
    with SessionLocal() as db:
        after = db.query(ModelCallRecord).filter(ModelCallRecord.model_id == rollout["model_id"],
                                                 ModelCallRecord.id > rollout["last_call_id_before_enable"]).all()
        production = [record for record in after if not record.source_id.startswith("cache-acceptance-")]
        agents = [record for record in production if record.source == ModelCallSource.AGENT]
        compactions = [record for record in production if record.source in {
            ModelCallSource.AGENT_CONTEXT_COMPACTION, ModelCallSource.AGENT_RUNTIME_COMPACTION}]
        validation = [record for record in after if record.source_id.startswith("cache-acceptance-")]
        report = {"model_id": rollout["model_id"], "enabled": db.get(AIModel, rollout["model_id"]).prompt_cache_enabled,
                  "baseline_last_30_reported_agent_calls": rollout["baseline_last_30_reported_agent_calls"],
                  "production_agent": aggregate(agents), "production_compaction": aggregate(compactions),
                  "production_observation_complete": sum(record.usage_reported for record in agents) >= 30,
                  "isolated_validation": aggregate(validation)}
    (DIRECTORY / "production-observation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
