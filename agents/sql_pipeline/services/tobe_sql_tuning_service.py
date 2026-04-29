from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from agents.sql_pipeline.core.logger import logger


# sql_pipeline/ 패키지 루트 (data/rag/ 위치 기준)
_AGENT_DIR = Path(__file__).resolve().parent.parent
# unified_agent/ 프로젝트 루트 (.env 위치 기준)
_PROJECT_ROOT = _AGENT_DIR.parent.parent
DEFAULT_CATALOG_PATH = _AGENT_DIR / "data" / "rag" / "tobe_rule_catalog.json"
load_dotenv(_PROJECT_ROOT / ".env")


class TobeSqlTuningService:
    def __init__(self) -> None:
        raw_path = os.getenv("TOBE_RULE_CATALOG_PATH", str(DEFAULT_CATALOG_PATH))
        self.catalog_path = self._resolve_path(raw_path)
        self.top_k = max(1, int(os.getenv("TOBE_SQL_TUNING_TOP_K", "3")))
        self.embed_base_url = os.getenv("RAG_EMBED_BASE_URL", "").strip()
        self.embed_api_key = os.getenv("RAG_EMBED_API_KEY", "").strip()
        self.embed_model = os.getenv("RAG_EMBED_MODEL", "BAAI/bge-m3").strip()
        self.embed_timeout_sec = int(os.getenv("RAG_EMBED_TIMEOUT_SEC", "30"))

    def retrieve_tuning_examples(self, sql_text: str) -> list[dict[str, Any]]:
        blocks = self._split_sql_into_blocks(sql_text)
        rules = self._load_catalog_rules()
        if not blocks or not rules:
            return []

        ordered_blocks = [block for block in blocks if block["block_type"] == "SUBQUERY"]
        ordered_blocks.extend(block for block in blocks if block["block_type"] != "SUBQUERY")

        try:
            return self._retrieve_by_vector_search(ordered_blocks, rules)
        except Exception as exc:
            logger.warning(
                "[TobeSqlTuningService] vector search fallback to token search "
                f"(reason={type(exc).__name__}: {exc})"
            )
            return [self._build_lexical_match_payload(block, rules) for block in ordered_blocks]

    def _retrieve_by_vector_search(
        self,
        blocks: list[dict[str, str]],
        rules: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not self.embed_base_url:
            raise RuntimeError("RAG_EMBED_BASE_URL is not set")

        try:
            import faiss
            import numpy as np
        except Exception as exc:
            raise RuntimeError("faiss-cpu and numpy are required for vector search") from exc

        rule_texts = [self._rule_embedding_text(rule) for rule in rules]
        block_texts = [block["normalized_sql"] for block in blocks]
        embeddings = self._embed_texts(rule_texts + block_texts)
        if len(embeddings) != len(rule_texts) + len(block_texts):
            raise RuntimeError("embedding response count does not match request count")

        rule_vectors = np.asarray(embeddings[: len(rule_texts)], dtype="float32")
        block_vectors = np.asarray(embeddings[len(rule_texts) :], dtype="float32")
        if rule_vectors.ndim != 2 or block_vectors.ndim != 2:
            raise RuntimeError("embedding vectors must be 2-dimensional")

        faiss.normalize_L2(rule_vectors)
        faiss.normalize_L2(block_vectors)
        index = faiss.IndexFlatIP(rule_vectors.shape[1])
        index.add(rule_vectors)

        safe_k = min(self.top_k, len(rules))
        scores, indices = index.search(block_vectors, safe_k)

        payloads: list[dict[str, Any]] = []
        for block_idx, block in enumerate(blocks):
            matches = []
            for score, rule_idx in zip(scores[block_idx], indices[block_idx]):
                if rule_idx < 0:
                    continue
                matches.append(self._format_rule_match(rules[int(rule_idx)], float(score)))
            payloads.append(
                {
                    "block_id": block["block_id"],
                    "block_type": block["block_type"],
                    "source_sql": block["sql"],
                    "search_method": "faiss_vector",
                    "embedding_model": self.embed_model,
                    "top_rule_matches": matches,
                }
            )
        return payloads

    def _build_lexical_match_payload(self, block: dict[str, str], rules: list[dict[str, Any]]) -> dict[str, Any]:
        scored: list[tuple[dict[str, Any], float]] = []
        for rule in rules:
            score = self._lexical_similarity(block["normalized_sql"], rule["normalized_bad_sql"])
            scored.append((rule, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return {
            "block_id": block["block_id"],
            "block_type": block["block_type"],
            "source_sql": block["sql"],
            "search_method": "token_fallback",
            "top_rule_matches": [
                self._format_rule_match(rule, score)
                for rule, score in scored[: self.top_k]
            ],
        }

    @staticmethod
    def _format_rule_match(rule: dict[str, Any], score: float) -> dict[str, Any]:
        return {
            "rule_id": rule["rule_id"],
            "score": round(score, 6),
            "guidance": rule["guidance"],
            "example_bad_sql": rule["example_bad_sql"],
            "example_tuned_sql": rule["example_tuned_sql"],
        }

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        endpoint = self._embedding_endpoint(self.embed_base_url)
        headers = {"Content-Type": "application/json"}
        if self.embed_api_key:
            headers["Authorization"] = f"Bearer {self.embed_api_key}"
        payload = {"model": self.embed_model, "input": texts}

        response = requests.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=self.embed_timeout_sec,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"embedding HTTP {response.status_code}: {response.text[:300]}")
        vectors = self._extract_embedding_vectors(response.json())
        if not vectors:
            raise RuntimeError("embedding response did not contain vectors")
        return vectors

    @staticmethod
    def _extract_embedding_vectors(body: Any) -> list[list[float]]:
        if isinstance(body, dict):
            data = body.get("data")
            if isinstance(data, list):
                vectors = []
                for item in data:
                    if isinstance(item, dict) and isinstance(item.get("embedding"), list):
                        vectors.append([float(value) for value in item["embedding"]])
                if vectors:
                    return vectors

            embeddings = body.get("embeddings")
            if isinstance(embeddings, list):
                vectors = []
                for item in embeddings:
                    if isinstance(item, list):
                        vectors.append([float(value) for value in item])
                if vectors:
                    return vectors

            embedding = body.get("embedding")
            if isinstance(embedding, list):
                return [[float(value) for value in embedding]]

        return []

    @staticmethod
    def _embedding_endpoint(base_url: str) -> str:
        normalized = base_url.strip().rstrip("/")
        if normalized.endswith("/embeddings"):
            return normalized
        if normalized.endswith("/v1"):
            return f"{normalized}/embeddings"
        return f"{normalized}/v1/embeddings"

    @staticmethod
    def _rule_embedding_text(rule: dict[str, Any]) -> str:
        guidance = " ".join(str(item) for item in rule.get("guidance", []))
        return "\n".join(
            [
                rule.get("normalized_bad_sql", ""),
                guidance,
                rule.get("example_bad_sql", ""),
            ]
        ).strip()

    def _load_catalog_rules(self) -> list[dict[str, Any]]:
        if not self.catalog_path.exists():
            logger.warning(f"[TobeSqlTuningService] rule catalog not found: {self.catalog_path}")
            return []

        raw = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        rows = raw.get("rules", raw if isinstance(raw, list) else [])
        result: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            rule_id = str(row.get("rule_id", "")).strip()
            example_bad_sql = str(row.get("example_bad_sql", "")).strip()
            if not rule_id or not example_bad_sql:
                continue
            guidance_raw = row.get("guidance", [])
            guidance = [str(item) for item in guidance_raw] if isinstance(guidance_raw, list) else [str(guidance_raw)]
            result.append(
                {
                    "rule_id": rule_id,
                    "guidance": guidance,
                    "example_bad_sql": example_bad_sql,
                    "example_tuned_sql": str(row.get("example_tuned_sql", "")).strip(),
                    "normalized_bad_sql": self._normalize_sql_shape(example_bad_sql),
                }
            )
        return result

    def _split_sql_into_blocks(self, sql_text: str) -> list[dict[str, str]]:
        source = (sql_text or "").strip().rstrip(";").strip()
        if not source:
            return []

        replacements: list[tuple[int, int, str, str]] = []
        stack: list[int] = []
        in_quote = False
        idx = 0
        while idx < len(source):
            ch = source[idx]
            if ch == "'":
                if in_quote and idx + 1 < len(source) and source[idx + 1] == "'":
                    idx += 2
                    continue
                in_quote = not in_quote
                idx += 1
                continue
            if in_quote:
                idx += 1
                continue
            if ch == "(":
                stack.append(idx)
            elif ch == ")" and stack:
                start = stack.pop()
                inner = source[start + 1 : idx].strip()
                if re.match(r"^SELECT\b", inner, flags=re.IGNORECASE):
                    placeholder = f"SUBQUERY_{len(replacements) + 1}"
                    replacements.append((start, idx + 1, placeholder, inner))
            idx += 1

        main_sql = source
        for start, end, placeholder, _inner in sorted(replacements, key=lambda item: item[0], reverse=True):
            main_sql = main_sql[:start] + f"({placeholder})" + main_sql[end:]

        blocks = [
            {
                "block_id": "MAIN_SQL",
                "block_type": "MAIN",
                "sql": main_sql,
                "normalized_sql": self._normalize_sql_shape(main_sql),
            }
        ]
        for _start, _end, placeholder, inner in replacements:
            blocks.append(
                {
                    "block_id": placeholder,
                    "block_type": "SUBQUERY",
                    "sql": inner,
                    "normalized_sql": self._normalize_sql_shape(inner),
                }
            )
        return blocks

    def _normalize_sql_shape(self, sql_text: str) -> str:
        text = re.sub(r"/\*.*?\*/", " ", sql_text or "", flags=re.DOTALL)
        text = re.sub(r"--[^\n]*", " ", text)
        text = re.sub(r"'(?:''|[^'])*'", " STR ", text)
        text = re.sub(r"\b\d+(?:\.\d+)?\b", " NUM ", text)
        text = re.sub(r"\bSUBQUERY_\d+\b", "SUBQUERY", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip()
        return text.upper()

    @staticmethod
    def _lexical_similarity(left: str, right: str) -> float:
        left_tokens = set(re.findall(r"[A-Z_]+|\d+", left.upper()))
        right_tokens = set(re.findall(r"[A-Z_]+|\d+", right.upper()))
        if not left_tokens or not right_tokens:
            return 0.0
        union = len(left_tokens.union(right_tokens))
        return len(left_tokens.intersection(right_tokens)) / union if union else 0.0

    @staticmethod
    def _resolve_path(raw_path: str) -> Path:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            project_path = (_PROJECT_ROOT / path).resolve()
            if project_path.exists():
                return project_path

            agent_path = (_AGENT_DIR / path).resolve()
            if agent_path.exists():
                return agent_path

            return project_path
        return path.resolve()


tobe_sql_tuning_service = TobeSqlTuningService()
