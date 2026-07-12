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
            tr = table.find("tr")
            if tr:
                headers = [c.get_text().strip() for c in tr.find_all(["th", "td"])]
                print(f"Table {i} headers: {headers}")
                # print first row to see data
                rows = table.find_all("tr")[1:3]
                for r_i, r in enumerate(rows):
                    cells = [c.get_text().strip() for c in r.find_all(["td", "th"])]
                    print(f"  Row {r_i} data: {cells}")
            else:
                print(f"Table {i} has no tr")
    except Exception as e:
        print(e)
