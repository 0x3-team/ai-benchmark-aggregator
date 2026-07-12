import httpx
from bs4 import BeautifulSoup

url = "https://github.com/openai/frontier-evals/tree/main/project/paperbench"
resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, timeout=10.0)
soup = BeautifulSoup(resp.content, "lxml")
tables = soup.find_all("table")
print(f"Found {len(tables)} tables")
for idx, table in enumerate(tables):
    tr = table.find("tr")
    if tr:
        headers = [c.get_text().strip() for c in tr.find_all(["th", "td"])]
        if any("score" in h.lower() for h in headers):
            print(f"Table {idx} headers: {headers}")
            rows = table.find_all("tr")[1:4]
            for r_i, r in enumerate(rows):
                cells = [c.get_text().strip() for c in r.find_all(["td", "th"])]
                print(f"  Row {r_i}: {cells}")
