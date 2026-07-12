import httpx
from bs4 import BeautifulSoup
import sys

urls = {
    "olympiadbench": ("https://github.com/OpenBMB/OlympiadBench#readme", "Model", "avg", "Experiment with full benchmark"),
    "frontiercode": ("https://benchmarklist.com/benchmarks/frontiercode/", "Model", "Main Score", "FrontierCode"),
    "bfcl": ("https://gorilla.cs.berkeley.edu/leaderboard.html", "Model", "Overall Accuracy", None),
    "humaneval": ("https://evalplus.github.io/leaderboard.html", "model", "pass@1", None),
    "terminal_bench": ("https://www.tbench.ai/leaderboard/terminal-bench/2.1", "Model", "Accuracy", None),
    "browsecomp": ("https://llm-stats.com/benchmarks/browsecomp", "Model", "Score", None),
    "apex_agents": ("https://www.mercor.com/apex/apex-agents-leaderboard/", "Model", "Pass@1", None),
    "paperbench": ("https://github.com/openai/frontier-evals/tree/main/project/paperbench", "Model", "Score (%)", "PaperBench Results"),
    "toolbench": ("https://github.com/OpenBMB/ToolBench", "Model", "pass_rate", None),
    "mt_bench": ("https://lmsys.org/blog/2023-06-22-leaderboard/", "Model", "score", "MT-Bench"),
    "opencompass": ("https://rank.opencompass.org.cn/home", "Model", "Score", None),
    "hle_scale": ("https://labs.scale.com/leaderboard/humanitys_last_exam", "Model", "Accuracy", None),
}

for name, (url, m_col, s_col, hint) in urls.items():
    print(f"=== Checking {name} ===")
    try:
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, timeout=10.0)
        print(f"Status: {resp.status_code}")
        if resp.status_code != 200:
            print("Failed status code")
            continue
        soup = BeautifulSoup(resp.content, "lxml")
        tables = soup.find_all("table")
        print(f"Found {len(tables)} tables")
        
        # Look for headers
        found = False
        for i, table in enumerate(tables):
            tr = table.find("tr")
            if not tr:
                continue
            headers = [c.get_text().strip() for c in tr.find_all(["th", "td"])]
            headers_lower = [h.lower() for h in headers]
            
            # Check if columns match
            m_found = m_col.lower() in headers_lower
            s_found = s_col.lower() in headers_lower
            
            # Substring match also
            if not m_found:
                m_found = any(m_col.lower() in h for h in headers_lower)
            if not s_found:
                s_found = any(s_col.lower() in h for h in headers_lower)
                
            if m_found or s_found or (hint and hint.lower() in table.get_text().lower()):
                print(f"Table {i} has headers: {headers}")
                print(f"Match: model={m_found}, score={s_found}")
                found = True
        if not found:
            print("No matching table found!")
    except Exception as e:
        print(f"Error: {e}")
