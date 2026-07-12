#!/bin/bash
cd /srv/hermes/development/ai-benchmark-aggregator
git add ledger/app/ingestion/adapters/frontiermath_epoch.py ledger/app/ingestion/adapters/__init__.py ledger/tests/test_frontiermath_epoch.py
git commit -m "feat(ledger): add FrontierMath Epoch CSV ingestion adapter"
