import yaml
from pathlib import Path

curated_path = Path("/srv/hermes/development/ai-benchmark-aggregator/ledger/app/registry/benchmarks_curated.yaml")
with curated_path.open() as f:
    data = yaml.safe_load(f)

ids = {b["id"] for b in data.get("benchmarks", [])}
print("Curated benchmark IDs:")
for i in sorted(ids):
    print(f"  {i}")
