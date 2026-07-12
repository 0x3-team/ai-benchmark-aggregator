import sys
import urllib.request
import json
from pathlib import Path
import yaml

def extract_base_model(model_raw: str) -> str | None:
    lower = model_raw.lower()
    
    # OpenAI o3/o4
    if "o4-mini" in lower or "o4 mini" in lower or "o4_mini" in lower:
        return "o4_mini"
    if "o3-mini" in lower or "o3 mini" in lower or "o3_mini" in lower or "o3" in lower:
        return "o3_mini"
    if "o1-mini" in lower or "o1 mini" in lower or "o1_mini" in lower:
        return "o1_mini"
    if "o1" in lower:
        return "o1"
        
    # OpenAI GPT-5
    if "gpt-5.6" in lower or "gpt 5.6" in lower or "gpt5.6" in lower:
        return "gpt_5_6"
    if "gpt-5.5" in lower or "gpt 5.5" in lower or "gpt5.5" in lower:
        return "gpt_5_5"
    if "gpt-5.4" in lower or "gpt 5.4" in lower or "gpt5.4" in lower:
        return "gpt_5_4"
    if "gpt-5.3" in lower or "gpt 5.3" in lower or "gpt5.3" in lower:
        return "gpt_5_3_codex"
    if "gpt-5.2" in lower or "gpt 5.2" in lower or "gpt5.2" in lower:
        return "gpt_5_2"
    if "gpt-5.1" in lower or "gpt 5.1" in lower or "gpt5.1" in lower:
        return "gpt_5_1"
    if "gpt-5" in lower or "gpt 5" in lower or "gpt5" in lower:
        if "nano" in lower:
            return "gpt_5_nano"
        if "mini" in lower:
            return "gpt_5_mini"
        return "gpt_5"
        
    # OpenAI GPT-4
    if "gpt-4.1" in lower or "gpt 4.1" in lower or "gpt4.1" in lower:
        if "mini" in lower:
            return "gpt_4_1_mini"
        return "gpt_4_1"
    if "gpt-4o-mini" in lower or "gpt 4o mini" in lower or "gpt4o-mini" in lower or "gpt4o mini" in lower:
        return "gpt_4o_mini"
    if "gpt-4o" in lower or "gpt 4o" in lower or "gpt4o" in lower:
        return "gpt_4o"
    if "gpt-4-turbo" in lower or "gpt 4 turbo" in lower or "gpt4-turbo" in lower or "gpt4 turbo" in lower:
        return "gpt_4_turbo"
    if "gpt-4" in lower or "gpt 4" in lower or "gpt4" in lower:
        return "gpt_4"
        
    # Anthropic Claude 5
    if "fable-5" in lower or "fable 5" in lower or "fable5" in lower:
        return "claude_fable_5"
    if "mythos-5" in lower or "mythos 5" in lower or "mythos5" in lower:
        return "claude_mythos_5"
        
    # Anthropic Claude 4
    if "opus-4.8" in lower or "opus 4.8" in lower or "opus4.8" in lower:
        return "claude_opus_4_8"
    if "opus-4.7" in lower or "opus 4.7" in lower or "opus4.7" in lower:
        return "claude_opus_4_7"
    if "sonnet-4.6" in lower or "sonnet 4.6" in lower or "sonnet4.6" in lower:
        return "claude_sonnet_4_6"
    if "opus-4.6" in lower or "opus 4.6" in lower or "opus4.6" in lower:
        return "claude_opus_4_6"
    if "haiku-4.5" in lower or "haiku 4.5" in lower or "haiku4.5" in lower:
        return "claude_haiku_4_5"
    if "claude 4.5 sonnet" in lower or "claude-4.5-sonnet" in lower:
        return "claude_4_5_sonnet"
    if "claude 4.5 opus" in lower or "claude-4.5-opus" in lower:
        return "claude_opus_4_8"
    if "claude 4.5 haiku" in lower or "claude-4.5-haiku" in lower:
        return "claude_4_5_haiku"
    if "claude 4 sonnet" in lower or "claude-4-sonnet" in lower:
        return "claude_sonnet_4_6"
    if "claude 4 opus" in lower or "claude-4-opus" in lower:
        return "claude_opus_4_7"
        
    # Anthropic Claude 3
    if "claude" in lower:
        if "3.7" in lower:
            return "claude_3_7_sonnet"
        if "3.5" in lower:
            if "haiku" in lower:
                return "claude_3_5_haiku"
            return "claude_3_5_sonnet"
        if "opus" in lower:
            return "claude_3_opus"
        if "haiku" in lower:
            return "claude_3_haiku"
            
    # Google Gemini
    if "gemini" in lower:
        if "3.5" in lower:
            if "pro" in lower:
                return "gemini_3_5_pro"
            return "gemini_3_5_flash"
        if "3.1" in lower:
            if "pro" in lower:
                return "gemini_3_pro"
            return "gemini_3_1_flash_lite"
        if "3" in lower:
            if "pro" in lower:
                return "gemini_3_pro"
            return "gemini_3"
        if "2.5" in lower:
            if "pro" in lower:
                return "gemini_2_5_pro"
            return "gemini_2_5_flash"
        if "2" in lower:
            if "pro" in lower:
                return "gemini_2_pro"
            return "gemini_2_0_flash"
        if "1.5" in lower:
            if "pro" in lower:
                return "gemini_1_5_pro"
            return "gemini_1_5_flash"

    # xAI Grok
    if "grok" in lower:
        if "4.5" in lower:
            return "grok_4_5"
        if "4.3" in lower:
            return "grok_4_3"
        if "4.20" in lower or "4.2" in lower:
            return "grok_4_20"
        if "3" in lower:
            return "grok_3"
        if "2" in lower:
            if "mini" in lower:
                return "grok_2_mini"
            return "grok_2"
            
    # DeepSeek
    if "deepseek" in lower:
        if "v4" in lower:
            return "deepseek_v4"
        if "v3.2" in lower or "3.2" in lower:
            if "reasoner" in lower:
                return "deepseek_v3_2_reasoner"
            return "deepseek_v3_2"
        if "v3" in lower:
            return "deepseek_v3"
        if "r1" in lower:
            return "deepseek_r1"
            
    # Meta Llama
    if "llama" in lower:
        if "4" in lower:
            if "405b" in lower:
                return "llama_4_405b"
            if "70b" in lower:
                return "llama_4_70b"
            if "scout" in lower:
                return "llama_4_scout"
            if "maverick" in lower:
                return "llama_4_maverick"
            return "llama_4_8b"
        if "3.3" in lower:
            return "llama_3_3_70b"
        if "3.1" in lower:
            if "405b" in lower:
                return "llama_3_1_405b"
            if "70b" in lower:
                return "llama_3_1_70b"
            return "llama_3_1_8b"

    # Alibaba Qwen
    if "qwen" in lower:
        if "3.7" in lower:
            return "qwen_3_7_max"
        if "3.6" in lower:
            return "qwen_3_6_plus"
        if "3.5" in lower:
            return "qwen_3_5"
        if "3" in lower:
            if "coder" in lower:
                return "qwen_3_coder"
        if "2.5" in lower:
            if "coder" in lower:
                return "qwen_2_5_coder_32b"
            if "72b" in lower:
                return "qwen_2_5_72b"
        
    # GLM
    if "glm" in lower:
        if "5" in lower:
            return "glm_5"
        if "4" in lower:
            return "glm_4"

    # Mistral
    if "mistral" in lower or "mixtral" in lower:
        if "medium" in lower:
            return "mistral_medium_3_5"
        if "large-2" in lower or "large 2" in lower:
            return "mistral_large_2"
        if "large" in lower:
            return "mistral_large"
        if "8x22b" in lower:
            return "mixtral_8x22b"
        if "devstral" in lower:
            if "small" in lower:
                return "devstral_small"
            return "devstral"

    # Gemma
    if "gemma" in lower:
        if "4" in lower:
            return "gemma_4"
        if "27b" in lower:
            return "gemma_2_27b"
        if "9b" in lower:
            return "gemma_2_9b"

    # Kimi
    if "kimi" in lower:
        if "2.6" in lower:
            return "kimi_k2_6"
        if "2.5" in lower:
            return "kimi_k2_5"
        if "thinking" in lower:
            return "kimi_k2_thinking"
        return "kimi_k2"

    # Phi
    if "phi" in lower:
        if "4" in lower:
            return "phi_4"
        if "3.5" in lower:
            return "phi_3_5"

    # MiniMax
    if "minimax" in lower:
        if "2.5" in lower:
            return "minimax_m2_5"
        return "minimax_m2"

    # ByteDance Doubao
    if "doubao" in lower:
        return "doubao_seed_code"

    # Atlassian
    if "atlassian" in lower or "rovo" in lower:
        return "atlassian_rovo_dev"

    return None

def fetch_hf_model(hf_id: str) -> dict | None:
    try:
        url = f"https://huggingface.co/api/models/{hf_id}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Antigravity/1.0 (Google DeepMind Agent)"}
        )
        with urllib.request.urlopen(req) as res:
            return json.loads(res.read().decode('utf-8'))
    except Exception:
        return None

def main():
    # 1. Fetch top 1000 models from Hugging Face
    url = "https://huggingface.co/api/models?sort=downloads&direction=-1&limit=1000&full=false"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Antigravity/1.0 (Google DeepMind Agent)"}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            models_data = json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"Error fetching from HF API: {e}")
        models_data = []

    good_models = {}
    
    # Process HF models returned from the downloads API
    for m in models_data:
        hf_id = m.get("id")
        if not hf_id:
            continue
        
        downloads = m.get("downloads", 0)
        likes = m.get("likes", 0)
        
        # Filter to "good"
        if downloads >= 50000 or likes >= 200:
            canonical_name = hf_id.split("/")[-1]
            if "/" in hf_id:
                provider = hf_id.split("/")[0]
            else:
                provider = m.get("author") or "unknown"
                
            display_name = canonical_name.replace("-", " ").replace("_", " ")
            display_name = " ".join(display_name.split())
            
            aliases = [hf_id]
            if display_name not in aliases:
                aliases.append(display_name)
            if canonical_name not in aliases:
                aliases.append(canonical_name)
                
            model_entry = {
                "id": hf_id,
                "canonical_name": canonical_name,
                "display_name": display_name,
                "entity_type": "chat_model",
                "provider": provider,
                "access_type": "open_weights",
                "status": "active",
                "downloads": downloads,
                "likes": likes,
                "pipeline_tag": m.get("pipeline_tag", ""),
                "createdAt": m.get("createdAt", ""),
                "aliases": aliases
            }
            good_models[hf_id] = model_entry

    # 2. Add root to path so we can query DB session
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    # Query DB for all unique model_raw values in the ResultClaim table
    print("Connecting to DB to find unique model_raw strings...")
    raw_claims_models = []
    try:
        import app.ingestion.runner # avoid circular import
        from app.db.engine import get_session
        from app.db.models import ResultClaim
        from sqlalchemy import select
        with get_session() as session:
            raw_claims_models = list(set(session.scalars(select(ResultClaim.model_raw)).all()))
    except Exception as e:
        print(f"Error querying DB for claims: {e}")

    print(f"Found {len(raw_claims_models)} unique model_raw strings in database.")

    # 3. Load frontier models so we can dynamically add aliases to them
    frontier_path = Path(__file__).parent.parent / "app" / "registry" / "models_frontier.yaml"
    frontier_data = {"models": []}
    if frontier_path.exists():
        with frontier_path.open("r", encoding="utf-8") as f:
            frontier_data = yaml.safe_load(f) or {"models": []}
            
    # Quick lookup map for frontier models
    frontier_by_id = {m["id"]: m for m in frontier_data.get("models") or []}

    # Track how many new HF models we discover and fetch
    new_hf_fetched = 0
    
    # 4. Map DB raw models
    for raw_name in raw_claims_models:
        if not raw_name:
            continue
        
        # Check if HF repo format
        if "/" in raw_name and "+" not in raw_name and " " not in raw_name:
            if raw_name not in good_models and raw_name not in frontier_by_id:
                # Let's fetch details from HF API
                m_info = fetch_hf_model(raw_name)
                if m_info:
                    canonical_name = raw_name.split("/")[-1]
                    provider = raw_name.split("/")[0]
                    display_name = canonical_name.replace("-", " ").replace("_", " ")
                    display_name = " ".join(display_name.split())
                    
                    aliases = [raw_name]
                    if display_name not in aliases:
                        aliases.append(display_name)
                    if canonical_name not in aliases:
                        aliases.append(canonical_name)
                        
                    model_entry = {
                        "id": raw_name,
                        "canonical_name": canonical_name,
                        "display_name": display_name,
                        "entity_type": "chat_model",
                        "provider": provider,
                        "access_type": "open_weights",
                        "status": "active",
                        "downloads": m_info.get("downloads", 0),
                        "likes": m_info.get("likes", 0),
                        "pipeline_tag": m_info.get("pipeline_tag", ""),
                        "createdAt": m_info.get("createdAt", ""),
                        "aliases": aliases
                    }
                    good_models[raw_name] = model_entry
                    new_hf_fetched += 1

        # Check if it maps to a frontier model
        base_id = extract_base_model(raw_name)
        if base_id and base_id in frontier_by_id:
            # Add raw_name as an alias of this frontier model
            f_model = frontier_by_id[base_id]
            if "aliases" not in f_model:
                f_model["aliases"] = []
            if raw_name not in f_model["aliases"]:
                f_model["aliases"].append(raw_name)

    # Write frontier models back
    with frontier_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(frontier_data, f, sort_keys=False, allow_unicode=True)

    # Save to ledger/app/registry/models_hf_seed.yaml
    output_path = Path(__file__).parent.parent / "app" / "registry" / "models_hf_seed.yaml"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    payload = {"models": list(good_models.values())}
    with output_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)
        
    print(f"seeded {len(good_models)} HF models")

if __name__ == "__main__":
    main()
