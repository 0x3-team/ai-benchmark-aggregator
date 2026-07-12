import httpx
from bs4 import BeautifulSoup

url = "https://benchmarklist.com/benchmarks/frontiercode/"
resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, timeout=10.0)
soup = BeautifulSoup(resp.content, "lxml")
table = soup.find("table")
rows = table.find_all("tr")[1:5]
for r_i, r in enumerate(rows):
    cells = [c.get_text().strip() for c in r.find_all(["td", "th"])]
    print(f"Row {r_i}: {cells}")
