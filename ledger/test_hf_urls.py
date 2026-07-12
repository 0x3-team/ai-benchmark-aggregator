import httpx
import time

urls = [
    "https://datasets-server.huggingface.co/first-rows?dataset=gaia-benchmark/results_public&config=2023&split=train",
    "https://datasets-server.huggingface.co/first-rows?dataset=open-llm-leaderboard/results&config=default&split=train",
]

for url in urls:
    print(f"Fetching {url}")
    start = time.time()
    try:
        resp = httpx.get(url, headers={"User-Agent": "benchmark-ledger/0.1"}, follow_redirects=True, timeout=10.0)
        print(f"Status: {resp.status_code}, time: {time.time() - start:.2f}s")
        if resp.status_code == 200:
            print(f"Content length: {len(resp.content)}")
        else:
            print(f"Error content: {resp.text[:200]}")
    except Exception as e:
        print(f"Error: {e}, time: {time.time() - start:.2f}s")
