from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from coach_agent import PROJECT_ENDPOINT, ensure_azure_cli_on_path
from scripts.convert_leaf_draft_to_cards import load_inventory


ROOT = Path("/Users/xumuchi/Desktop/TeachAgent")
LEAF_CARD_GLOB = ROOT / "docs" / "rag_samples" / "*leaf_cards.jsonl"
DEFAULT_INDEX_DIR = ROOT / "docs" / "rag_index" / "leaf_embedding_index"
DEFAULT_RECORDS_PATH = DEFAULT_INDEX_DIR / "leaf_embeddings.jsonl"
DEFAULT_MANIFEST_PATH = DEFAULT_INDEX_DIR / "manifest.json"
DEFAULT_EMBEDDING_DEPLOYMENT = os.getenv(
    "AZURE_AI_EMBEDDING_DEPLOYMENT",
    "text-embedding-3-small",
)
DEFAULT_BATCH_SIZE = 16
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 6.0
EMBEDDING_SOURCE_FIELDS = [
    "title",
    "aliases",
    "keywords",
    "path",
    "texts",
    "support_snippets",
    "error_snippets",
]
PROJECT_ENDPOINT_SUFFIX_RE = re.compile(r"/api/projects/[^/]+/?$")


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_str_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            text = normalize_text(item)
            if text:
                values.append(text)
        return values
    text = normalize_text(value)
    if text is None:
        return []
    separators = [" | ", ";", "，", "\n"]
    parts = [text]
    for separator in separators:
        if len(parts) == 1:
            parts = [part.strip() for part in text.split(separator)]
    return [part for part in parts if part]


def unique_list(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        text = normalize_text(value)
        if text is None or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def vector_norm(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values))


def unit_normalize(values: list[float]) -> list[float]:
    norm = vector_norm(values)
    if norm <= 0:
        return values
    return [value / norm for value in values]


def dot_product(left: list[float], right: list[float]) -> float:
    limit = min(len(left), len(right))
    return sum(left[index] * right[index] for index in range(limit))


def safe_round(value: float, digits: int = 6) -> float:
    return round(value, digits)


def derive_resource_root(project_endpoint: str) -> str:
    endpoint = normalize_text(project_endpoint)
    if endpoint is None:
        raise ValueError("project endpoint must not be empty")
    return PROJECT_ENDPOINT_SUFFIX_RE.sub("", endpoint.rstrip("/"))


def derive_openai_base_url(project_endpoint: str) -> str:
    return derive_resource_root(project_endpoint).rstrip("/") + "/openai/v1"


DEFAULT_FOUNDRY_OPENAI_BASE_URL = os.getenv(
    "AZURE_AI_OPENAI_BASE_URL",
    derive_openai_base_url(PROJECT_ENDPOINT),
)


def load_leaf_card_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(ROOT.glob(str(LEAF_CARD_GLOB.relative_to(ROOT)))):
        with path.open(encoding="utf-8") as fp:
            for line in fp:
                text = line.strip()
                if not text:
                    continue
                rows.append(json.loads(text))
    return rows


def aggregate_leaf_rows(
    card_rows: list[dict[str, Any]],
    inventory: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for row in card_rows:
        node_id = row["node_id"]
        meta = inventory[node_id]
        bucket = grouped.setdefault(
            node_id,
            {
                "node_id": node_id,
                "title": row.get("title") or meta["name"],
                "node_kind": meta["node_kind"],
                "review_role": meta["review_role"],
                "binding_role": meta["binding_role"],
                "path": row.get("path") or meta["path"],
                "path_text": " > ".join(row.get("path") or meta["path"]),
                "aliases": [],
                "keywords": [],
                "texts": [],
                "support_snippets": [],
                "error_snippets": [],
                "source_cards": [],
            },
        )

        bucket["aliases"].extend(normalize_str_list(row.get("aliases")))
        bucket["keywords"].extend(normalize_str_list(row.get("keywords")))
        if text := normalize_text(row.get("text")):
            bucket["texts"].append(text)

        for field in [
            "definition",
            "core_idea",
            "boundary",
            "formula",
            "variable_notes",
            "derivation_hint",
            "method_goal",
            "review_cue",
        ]:
            if text := normalize_text(row.get(field)):
                bucket["support_snippets"].append(text)

        for field in [
            "recognition_signals",
            "applicable_conditions",
            "special_cases",
            "trigger_signals",
            "steps",
            "applicable_problem_types",
        ]:
            bucket["support_snippets"].extend(normalize_str_list(row.get(field)))

        for field in ["common_errors", "failure_modes"]:
            bucket["error_snippets"].extend(normalize_str_list(row.get(field)))

        bucket["source_cards"].append(row.get("chunk_id") or "")

    aggregated: list[dict[str, Any]] = []
    for row in grouped.values():
        row["aliases"] = unique_list(row["aliases"])
        row["keywords"] = unique_list(row["keywords"])
        row["texts"] = unique_list(row["texts"])
        row["support_snippets"] = unique_list(row["support_snippets"])
        row["error_snippets"] = unique_list(row["error_snippets"])
        row["source_cards"] = unique_list(row["source_cards"])
        row["embedding_text"] = build_embedding_text(row)
        aggregated.append(row)

    aggregated.sort(key=lambda item: item["node_id"])
    return aggregated


def build_embedding_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    parts.append(f"知识点：{row['title']}")
    parts.append(f"路径：{row['path_text']}")
    if row["aliases"]:
        parts.append("别名：" + "；".join(row["aliases"]))
    if row["keywords"]:
        parts.append("关键词：" + "；".join(row["keywords"]))
    if row["texts"]:
        parts.append("主卡内容：" + "\n".join(row["texts"]))
    if row["support_snippets"]:
        parts.append("辅助信号：" + "；".join(row["support_snippets"]))
    if row["error_snippets"]:
        parts.append("常见错误：" + "；".join(row["error_snippets"]))
    return "\n".join(parts)


def leaf_embedding_environment() -> dict[str, str | None]:
    ensure_azure_cli_on_path()
    return {
        "project_endpoint": PROJECT_ENDPOINT,
        "resource_root": derive_resource_root(PROJECT_ENDPOINT),
        "openai_base_url": DEFAULT_FOUNDRY_OPENAI_BASE_URL,
        "embedding_deployment": DEFAULT_EMBEDDING_DEPLOYMENT,
    }


@dataclass(frozen=True)
class LeafEmbeddingRecord:
    node_id: str
    title: str
    node_kind: str
    path: list[str]
    path_text: str
    aliases: list[str]
    keywords: list[str]
    embedding_text: str
    vector: list[float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "title": self.title,
            "node_kind": self.node_kind,
            "path": self.path,
            "path_text": self.path_text,
            "aliases": self.aliases,
            "keywords": self.keywords,
            "embedding_text": self.embedding_text,
            "vector": self.vector,
        }


class LeafEmbeddingIndex:
    def __init__(self, records: list[LeafEmbeddingRecord], manifest: dict[str, Any]) -> None:
        self.records = records
        self.manifest = manifest
        self._by_node_id = {record.node_id: record for record in records}

    @classmethod
    def load(
        cls,
        records_path: Path = DEFAULT_RECORDS_PATH,
        manifest_path: Path = DEFAULT_MANIFEST_PATH,
    ) -> "LeafEmbeddingIndex":
        records: list[LeafEmbeddingRecord] = []
        with records_path.open(encoding="utf-8") as fp:
            for line in fp:
                text = line.strip()
                if not text:
                    continue
                row = json.loads(text)
                records.append(
                    LeafEmbeddingRecord(
                        node_id=row["node_id"],
                        title=row["title"],
                        node_kind=row["node_kind"],
                        path=row["path"],
                        path_text=row["path_text"],
                        aliases=row.get("aliases", []),
                        keywords=row.get("keywords", []),
                        embedding_text=row["embedding_text"],
                        vector=row["vector"],
                    )
                )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return cls(records, manifest)

    def get(self, node_id: str) -> LeafEmbeddingRecord | None:
        return self._by_node_id.get(node_id)

    def search_by_vector(self, query_vector: list[float], *, top_k: int = 5) -> list[dict[str, Any]]:
        top_k = max(1, top_k)
        scored: list[tuple[float, LeafEmbeddingRecord]] = []
        for record in self.records:
            similarity = dot_product(query_vector, record.vector)
            scored.append((similarity, record))
        scored.sort(key=lambda item: (-item[0], item[1].path_text))
        return [
            {
                "node_id": record.node_id,
                "title": record.title,
                "node_kind": record.node_kind,
                "path": record.path,
                "path_text": record.path_text,
                "similarity": safe_round(score),
            }
            for score, record in scored[:top_k]
        ]


class FoundryLeafEmbeddingClient:
    def __init__(
        self,
        *,
        project_endpoint: str = PROJECT_ENDPOINT,
        openai_base_url: str = DEFAULT_FOUNDRY_OPENAI_BASE_URL,
        embedding_deployment: str = DEFAULT_EMBEDDING_DEPLOYMENT,
        api_key: str | None = None,
        use_default_credential: bool = False,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
    ) -> None:
        api_key = api_key or os.getenv("AZURE_AI_API_KEY") or os.getenv("AZURE_OPENAI_API_KEY")
        self.auth_mode = "token_credential"
        if api_key:
            from openai import OpenAI

            self.client = OpenAI(
                api_key=api_key,
                base_url=openai_base_url,
            )
            self.auth_mode = "api_key"
        else:
            ensure_azure_cli_on_path()
            try:
                from azure.ai.projects import AIProjectClient
                from azure.identity import AzureCliCredential, DefaultAzureCredential
            except ImportError as exc:
                raise ImportError(
                    "Missing Azure SDK packages. Install azure-ai-projects and azure-identity."
                ) from exc

            credential = (
                DefaultAzureCredential()
                if use_default_credential
                else AzureCliCredential()
            )
            project = AIProjectClient(endpoint=project_endpoint, credential=credential)
            self.client = project.get_openai_client()

        self.embedding_deployment = embedding_deployment
        self.project_endpoint = project_endpoint
        self.openai_base_url = openai_base_url
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        attempt = 0
        while True:
            try:
                response = self.client.embeddings.create(
                    input=texts,
                    model=self.embedding_deployment,
                    encoding_format="float",
                )
                return [item.embedding for item in response.data]
            except Exception:
                attempt += 1
                if attempt > self.max_retries:
                    raise
                time.sleep(self.retry_backoff_seconds * attempt)

    def embed_query(self, text: str) -> list[float]:
        vectors = self.embed_texts([text])
        if not vectors:
            raise ValueError("embedding service returned no vectors for query")
        return vectors[0]

    def probe(self, text: str = "数学 导数 单调性") -> dict[str, Any]:
        vector = self.embed_query(text)
        return {
            "embedding_deployment": self.embedding_deployment,
            "auth_mode": self.auth_mode,
            "vector_length": len(vector),
            "project_endpoint": self.project_endpoint,
            "openai_base_url": self.openai_base_url,
        }


class LeafEmbeddingIndexBuilder:
    def __init__(self) -> None:
        inventory = load_inventory()
        card_rows = load_leaf_card_rows()
        self.leaf_rows = aggregate_leaf_rows(card_rows, inventory)

    def build(
        self,
        *,
        embedding_client: FoundryLeafEmbeddingClient,
        out_dir: Path = DEFAULT_INDEX_DIR,
        batch_size: int = DEFAULT_BATCH_SIZE,
        normalize_vectors: bool = True,
        max_items: int | None = None,
    ) -> tuple[Path, Path]:
        rows = self.leaf_rows if max_items is None else self.leaf_rows[: max(0, max_items)]
        out_dir.mkdir(parents=True, exist_ok=True)

        record_rows: list[dict[str, Any]] = []
        batch_size = max(1, batch_size)
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            vectors = embedding_client.embed_texts(
                [row["embedding_text"] for row in batch]
            )
            for row, vector in zip(batch, vectors):
                normalized_vector = unit_normalize(vector) if normalize_vectors else vector
                record_rows.append(
                    {
                        "node_id": row["node_id"],
                        "title": row["title"],
                        "node_kind": row["node_kind"],
                        "review_role": row["review_role"],
                        "binding_role": row["binding_role"],
                        "path": row["path"],
                        "path_text": row["path_text"],
                        "aliases": row["aliases"],
                        "keywords": row["keywords"],
                        "embedding_text": row["embedding_text"],
                        "source_cards": row["source_cards"],
                        "vector_norm": safe_round(vector_norm(vector)),
                        "vector": [safe_round(value) for value in normalized_vector],
                    }
                )

        records_path = out_dir / DEFAULT_RECORDS_PATH.name
        manifest_path = out_dir / DEFAULT_MANIFEST_PATH.name

        with records_path.open("w", encoding="utf-8") as fp:
            for row in record_rows:
                fp.write(json.dumps(row, ensure_ascii=False) + "\n")

        manifest = {
            "version": "0.1",
            "artifact": "leaf_embedding_index",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "project_endpoint": PROJECT_ENDPOINT,
            "resource_root": derive_resource_root(PROJECT_ENDPOINT),
            "openai_base_url": embedding_client.openai_base_url,
            "embedding_deployment": embedding_client.embedding_deployment,
            "auth_mode": embedding_client.auth_mode,
            "record_count": len(record_rows),
            "vector_normalized": normalize_vectors,
            "records_path": str(records_path),
            "source_glob": str(LEAF_CARD_GLOB),
            "source_fields": EMBEDDING_SOURCE_FIELDS,
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return records_path, manifest_path


def parse_query_text(args: argparse.Namespace) -> str:
    query = normalize_text(args.query)
    if query:
        return query
    query_file = normalize_text(args.query_file)
    if query_file is None:
        raise ValueError("query mode requires --query or --query-file")
    return Path(query_file).read_text(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--out-dir", default=str(DEFAULT_INDEX_DIR))
    build_parser.add_argument(
        "--embedding-model",
        default=DEFAULT_EMBEDDING_DEPLOYMENT,
    )
    build_parser.add_argument("--api-key")
    build_parser.add_argument("--openai-base-url", default=DEFAULT_FOUNDRY_OPENAI_BASE_URL)
    build_parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    build_parser.add_argument("--max-items", type=int)
    build_parser.add_argument("--use-default-credential", action="store_true")
    build_parser.add_argument("--no-normalize", action="store_true")

    query_parser = subparsers.add_parser("query")
    query_parser.add_argument("--records-path", default=str(DEFAULT_RECORDS_PATH))
    query_parser.add_argument("--manifest-path", default=str(DEFAULT_MANIFEST_PATH))
    query_parser.add_argument(
        "--embedding-model",
        default=DEFAULT_EMBEDDING_DEPLOYMENT,
    )
    query_parser.add_argument("--api-key")
    query_parser.add_argument("--openai-base-url", default=DEFAULT_FOUNDRY_OPENAI_BASE_URL)
    query_parser.add_argument("--query")
    query_parser.add_argument("--query-file")
    query_parser.add_argument("--top-k", type=int, default=5)
    query_parser.add_argument("--use-default-credential", action="store_true")

    probe_parser = subparsers.add_parser("probe")
    probe_parser.add_argument(
        "--embedding-model",
        default=DEFAULT_EMBEDDING_DEPLOYMENT,
    )
    probe_parser.add_argument("--api-key")
    probe_parser.add_argument("--openai-base-url", default=DEFAULT_FOUNDRY_OPENAI_BASE_URL)
    probe_parser.add_argument("--text", default="数学 导数 单调性")
    probe_parser.add_argument("--use-default-credential", action="store_true")

    args = parser.parse_args()

    if args.command == "build":
        builder = LeafEmbeddingIndexBuilder()
        client = FoundryLeafEmbeddingClient(
            openai_base_url=args.openai_base_url,
            embedding_deployment=args.embedding_model,
            api_key=args.api_key,
            use_default_credential=args.use_default_credential,
        )
        records_path, manifest_path = builder.build(
            embedding_client=client,
            out_dir=Path(args.out_dir),
            batch_size=args.batch_size,
            normalize_vectors=not args.no_normalize,
            max_items=args.max_items,
        )
        print(
            json.dumps(
                {
                    "records_path": str(records_path),
                    "manifest_path": str(manifest_path),
                    "record_count": len(builder.leaf_rows)
                    if args.max_items is None
                    else min(len(builder.leaf_rows), args.max_items),
                    "embedding_deployment": args.embedding_model,
                    "auth_mode": client.auth_mode,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.command == "query":
        query_text = parse_query_text(args)
        index = LeafEmbeddingIndex.load(
            records_path=Path(args.records_path),
            manifest_path=Path(args.manifest_path),
        )
        client = FoundryLeafEmbeddingClient(
            openai_base_url=args.openai_base_url,
            embedding_deployment=args.embedding_model,
            api_key=args.api_key,
            use_default_credential=args.use_default_credential,
        )
        query_vector = unit_normalize(client.embed_query(query_text))
        result = index.search_by_vector(query_vector, top_k=args.top_k)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "probe":
        client = FoundryLeafEmbeddingClient(
            openai_base_url=args.openai_base_url,
            embedding_deployment=args.embedding_model,
            api_key=args.api_key,
            use_default_credential=args.use_default_credential,
        )
        print(json.dumps(client.probe(args.text), ensure_ascii=False, indent=2))
        return


if __name__ == "__main__":
    main()
