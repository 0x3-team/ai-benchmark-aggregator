from __future__ import annotations

from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.adapters.fake import FakeSourceAdapter
from app.ingestion.adapters.generic_csv import GenericCSVAdapter
from app.ingestion.adapters.generic_html_table import GenericHTMLTableAdapter
from app.ingestion.adapters.generic_json import GenericJSONAdapter
from app.ingestion.adapters.github_yaml import GitHubYAMLAdapter
from app.ingestion.adapters.hf_benchmark_api import HFBenchmarkAPIAdapter
from app.ingestion.adapters.hf_datasets_server import HFDatasetsServerAdapter
from app.ingestion.adapters.lmsys_arena_api import LMSYSArenaAPIAdapter
from app.ingestion.adapters.artificial_analysis_api import ArtificialAnalysisAPIAdapter
from app.ingestion.adapters.swe_bench_adapter import SWEBenchAdapter
from app.ingestion.adapters.livecodebench_adapter import LiveCodeBenchAdapter
from app.ingestion.adapters.livebench_adapter import LiveBenchAdapter
from app.ingestion.adapters.taubench_s3 import TauBenchS3Adapter

ADAPTERS: dict[str, type[SourceAdapter]] = {
    FakeSourceAdapter.source_type: FakeSourceAdapter,
    HFBenchmarkAPIAdapter.source_type: HFBenchmarkAPIAdapter,
    GenericJSONAdapter.source_type: GenericJSONAdapter,
    "github_json": GenericJSONAdapter,
    GenericCSVAdapter.source_type: GenericCSVAdapter,
    "github_csv": GenericCSVAdapter,
    GenericHTMLTableAdapter.source_type: GenericHTMLTableAdapter,
    "hf_datasets_server": HFDatasetsServerAdapter,
    "github_yaml": GitHubYAMLAdapter,
    "lmsys_arena_api": LMSYSArenaAPIAdapter,
    "artificial_analysis_api": ArtificialAnalysisAPIAdapter,
    "swe_bench_adapter": SWEBenchAdapter,
    "taubench_s3": TauBenchS3Adapter,
    "livecodebench_adapter": LiveCodeBenchAdapter,
    "livebench_adapter": LiveBenchAdapter,
}


def get_adapter(source_type: str, parser_name: str | None = None, **kwargs) -> SourceAdapter:
    cls = None
    if source_type == "api" and parser_name:
        cls = ADAPTERS.get(parser_name)
    
    if cls is None and parser_name:
        cls = ADAPTERS.get(parser_name)

    if cls is None:
        cls = ADAPTERS.get(source_type)

    if cls is None:
        raise KeyError(f"No adapter registered for source_type={source_type}, parser_name={parser_name}")
    return cls(**kwargs)
