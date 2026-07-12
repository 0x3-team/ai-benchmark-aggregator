import httpx
import yaml

url = "https://raw.githubusercontent.com/Aider-AI/aider/main/aider/website/_data/polyglot_leaderboard.yml"
resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, timeout=10.0)
print(resp.status_code)
print(resp.text[:500])
data = yaml.safe_load(resp.text)
print("Type of data:", type(data))
if isinstance(data, list):
    print("List length:", len(data))
    print("First item:", data[0])
elif isinstance(data, dict):
    print("Keys:", list(data.keys()))
