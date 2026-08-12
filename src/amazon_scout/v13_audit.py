from __future__ import annotations

import argparse
import json
from pathlib import Path


def prepare(source: str | Path, output: str | Path) -> Path:
    source=Path(source); output=Path(output)
    bundle=json.loads(source.read_text(encoding="utf-8"))
    prior_id=bundle["research_run"].get("id")
    bundle["research_run"].update({
        "id":"resumed-diversified-v13-economics-20260812",
        "slug":"resumed-diversified-hunt-v1.3-economics-audit",
        "parent_run_id":prior_id,
        "resume_checkpoint":"completed-v1.2.4-persisted-evidence-offline-economics-recalculation",
    })
    bundle["v13_economics"]={
        "release":"V1.3",
        "source_bundle":str(source),
        "fee_rule_config":"config/amazon_uae_economics_v13.yaml",
        "additional_serpapi_calls":0,
        "scope":["long handle baseboard cleaning tool","washable ceiling fan blade sleeve duster","adjustable airplane foot hammock","wood crochet blocking board"],
        "physical_profile_warning":"Packaged dimensions and weights are ESTIMATE inputs, not observed ASIN data; economics remains PARTIAL.",
    }
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(bundle,indent=2),encoding="utf-8")
    return output


def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("source"); p.add_argument("output")
    a=p.parse_args(); print(prepare(a.source,a.output)); return 0


if __name__ == "__main__": raise SystemExit(main())
