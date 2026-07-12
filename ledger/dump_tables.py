import httpx
from bs4 import BeautifulSoup

for name, url in [
    ("bfcl", "https://gorilla.cs.berkeley.edu/leaderboard.html"),
    ("humaneval", "https://evalplus.github.io/leaderboard.html"),
]:
    print(f"=== {name} ===")
    try:
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, timeout=10.0)
        soup = BeautifulSoup(resp.content, "lxml")
        tables = soup.find_all("table")
        print(f"Found {len(tables)} tables")
        for i, table in enumerate(tables):
            print(f"Table {i} HTML:")
            print(str(table)[:1000])
    except Exception as e:
        print(e)
