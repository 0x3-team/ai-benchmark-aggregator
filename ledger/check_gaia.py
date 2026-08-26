#!/usr/bin/env python3
"""Retired direct-network helper - governed offline stub.

This entrypoint historically performed an unbound outbound HTTP GET. It is
retired and replaced by the governed SafeFetch seam
(``ledger/app/ingestion/safe_fetch.py``), which defaults to a disabled network
transport. This file is kept as a tracked, runnable no-network stub so the
history of the retired helper is preserved through git without retaining a
runnable raw-network copy anywhere on disk. It exits immediately with a clear
message; it never opens a socket.
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "This helper is retired. Data access goes through the governed SafeFetch "
        "seam (ledger/app/ingestion/safe_fetch.py); this stub performs no network "
        "I/O by design.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
