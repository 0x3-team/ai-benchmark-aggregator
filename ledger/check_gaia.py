import httpx

url = "https://datasets-server.huggingface.co/splits?dataset=gaia-benchmark/results_public"
resp = httpx.get(url, headers={"User-Agent": "benchmark-ledger/0.1"}, follow_redirects=True, timeout=10.0)
print("Splits status:", resp.status_code)
print(resp.text)
