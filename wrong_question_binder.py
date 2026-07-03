from __future__ import annotations

import argparse
import math
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from leaf_embedding_index import (
    DEFAULT_EMBEDDING_DEPLOYMENT,
    DEFAULT_FOUNDRY_OPENAI_BASE_URL,
    DEFAULT_MANIFEST_PATH as DEFAULT_LEAF_EMBED_MANIFEST_PATH,
    DEFAULT_RECORDS_PATH as DEFAULT_LEAF_EMBED_RECORDS_PATH,
    FoundryLeafEmbeddingClient,
    LeafEmbeddingIndex,
    unit_normalize,
)
from scripts.convert_leaf_draft_to_cards import load_inventory


ROOT = Path("/Users/xumuchi/Desktop/TeachAgent")
TREE_PATH = ROOT / "docs" / "rag_inventory" / "knowledge_tree_typed_full.json"
LEAF_CARD_GLOB = ROOT / "docs" / "rag_samples" / "*leaf_cards.jsonl"

BINDER_VERSION = "wrong_question_binder_v4_focus_sparse_embedding_hybrid"
DEFAULT_TOP_K = 5
DEFAULT_MAX_SECONDARY = 2
DEFAULT_COARSE_K = 3
DEFAULT_GLOBAL_RECALL = 30
DEFAULT_SPARSE_RECALL = 24
DEFAULT_EMBEDDING_RECALL = 24
SUBTREE_LEVELS = {2, 3}
SPARSE_BM25_K1 = 1.5
SPARSE_BM25_B = 0.75

TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+")
QUESTION_PAYLOAD_FIELDS = [
    "stem",
    "question_type",
    "student_answer",
    "correct_answer",
    "solution_text",
    "teacher_comment",
    "source_name",
    "source_section",
    "source_created_at",
    "difficulty_guess",
    "tags",
]
OPTIONAL_LIST_FIELDS = {"tags"}
GENERIC_PATH_TERMS = {"数学"}
SURFACE_HINTS = [
    ("求导", "导数"),
    ("可导", "导数"),
    ("导函数", "导数"),
    ("导函数符号", "导数 单调性"),
    ("导数符号", "导数 单调性"),
    ("符号表", "符号变化 单调性"),
    ("增减区间", "单调性"),
    ("递增", "单调性"),
    ("递减", "单调性"),
    ("极大值", "极值"),
    ("极小值", "极值"),
    ("最大值", "最值"),
    ("最小值", "最值"),
    ("驻点", "极值"),
    ("切线", "几何意义 切线"),
    ("零点", "函数零点"),
    ("根的分布", "方程根"),
]


@dataclass(frozen=True)
class TextFeatures:
    tokens: frozenset[str]
    bigrams: frozenset[str]
    trigrams: frozenset[str]


@dataclass(frozen=True)
class WrongQuestionBindingResult:
    normalized_question: dict[str, Any]
    binding_record: dict[str, Any]
    coarse_subtree_candidates: list[dict[str, Any]]
    candidate_pool_size: int


EMPTY_FEATURES = TextFeatures(frozenset(), frozenset(), frozenset())


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_str_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        values = []
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
        if text is None:
            continue
        if text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"


def expand_math_surface_text(text: str) -> str:
    expanded_terms: list[str] = []
    for trigger, expansion in SURFACE_HINTS:
        if trigger in text:
            expanded_terms.append(expansion)
    if not expanded_terms:
        return text
    return text + "\n" + " ".join(unique_list(expanded_terms))


def normalize_fragment(text: str) -> str:
    return "".join(
        char.lower()
        for char in text
        if is_cjk(char) or char.isalnum()
    )


def build_ngrams(text: str, size: int) -> set[str]:
    if size <= 0:
        return set()
    compact = normalize_fragment(text)
    if len(compact) < size:
        return set()
    return {compact[index : index + size] for index in range(len(compact) - size + 1)}


def build_text_features(text: str | None) -> TextFeatures:
    if not text:
        return EMPTY_FEATURES

    text = expand_math_surface_text(text)

    tokens: set[str] = set()
    bigrams: set[str] = set()
    trigrams: set[str] = set()

    for raw_token in TOKEN_RE.findall(text):
        token = normalize_fragment(raw_token)
        if not token:
            continue
        tokens.add(token)
        bigrams.update(build_ngrams(token, 2))
        trigrams.update(build_ngrams(token, 3))

    return TextFeatures(
        tokens=frozenset(tokens),
        bigrams=frozenset(bigrams),
        trigrams=frozenset(trigrams),
    )


def build_focus_terms(text: str | None) -> frozenset[str]:
    if not text:
        return frozenset()

    terms: set[str] = set()
    expanded = expand_math_surface_text(text)
    for raw_token in TOKEN_RE.findall(expanded):
        normalized = normalize_fragment(raw_token)
        if not normalized or normalized.isdigit():
            continue

        if any(is_cjk(char) for char in raw_token):
            for size, prefix in ((2, "g2:"), (3, "g3:"), (4, "g4:")):
                if len(normalized) < size:
                    continue
                for index in range(len(normalized) - size + 1):
                    terms.add(prefix + normalized[index : index + size])
        elif normalized.isalpha() and len(normalized) >= 3:
            terms.add("tok:" + normalized)

    return frozenset(terms)


def focus_term_weight(term: str, doc_freqs: Counter[str], doc_count: int) -> float:
    if doc_count <= 0:
        return 0.0

    df = doc_freqs.get(term, 0)
    idf = math.log(1.0 + (doc_count + 1.0) / (df + 1.0))
    if term.startswith("g4:"):
        return idf * 1.35
    if term.startswith("g3:"):
        return idf * 1.18
    if term.startswith("g2:"):
        return idf * 0.88
    return idf


def build_focus_profile(
    text: str | None,
    doc_freqs: Counter[str],
    doc_count: int,
    *,
    max_terms: int = 24,
) -> dict[str, Any]:
    weighted_terms: list[tuple[float, str]] = []
    for term in build_focus_terms(text):
        doc_freq = doc_freqs.get(term, 0)
        if doc_freq <= 0:
            continue
        if doc_count > 0:
            coverage = doc_freq / doc_count
            if term.startswith("g2:") and coverage > 0.12:
                continue
            if term.startswith("g3:") and coverage > 0.22:
                continue
            if term.startswith("tok:") and coverage > 0.08:
                continue

        weight = focus_term_weight(term, doc_freqs, doc_count)
        if weight <= 0:
            continue
        weighted_terms.append((weight, term))

    weighted_terms.sort(key=lambda item: (-item[0], item[1]))
    selected = weighted_terms[: max(1, max_terms)]
    weights = {term: weight for weight, term in selected}
    labels = {term: term.split(":", 1)[1] for _, term in selected}
    return {
        "weights": weights,
        "labels": labels,
        "ordered_terms": [term for _, term in selected],
    }


def weighted_focus_overlap_score(
    candidate_terms: frozenset[str],
    focus_profile: dict[str, Any],
) -> float:
    weights = focus_profile.get("weights") or {}
    if not candidate_terms or not weights:
        return 0.0

    total_weight = sum(weights.values())
    if total_weight <= 0:
        return 0.0

    matched_weight = sum(weight for term, weight in weights.items() if term in candidate_terms)
    return clamp_score(matched_weight / total_weight)


def matched_focus_labels(
    candidate_terms: frozenset[str],
    focus_profile: dict[str, Any],
    *,
    limit: int = 4,
) -> list[str]:
    labels = focus_profile.get("labels") or {}
    ordered_terms = focus_profile.get("ordered_terms") or []
    matches = [labels[term] for term in ordered_terms if term in candidate_terms and term in labels]
    return unique_list(matches[:limit])


def overlap_score(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    if overlap == 0:
        return 0.0
    recall = overlap / len(left)
    precision = overlap / len(right)
    return min(1.0, 0.65 * recall + 0.35 * precision)


def feature_match_score(left: TextFeatures, right: TextFeatures) -> float:
    token_score = overlap_score(left.tokens, right.tokens)
    bigram_score = overlap_score(left.bigrams, right.bigrams)
    trigram_score = overlap_score(left.trigrams, right.trigrams)
    return min(1.0, 0.45 * token_score + 0.35 * bigram_score + 0.20 * trigram_score)


def safe_round(value: float, digits: int = 4) -> float:
    return round(max(0.0, min(1.0, value)), digits)


def clamp_score(value: float) -> float:
    return max(0.0, min(1.0, value))


def generate_question_id(question_payload: dict[str, Any]) -> str:
    digest = hashlib.sha1(
        json.dumps(question_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"wq_{digest[:12]}"


def normalize_question_input(raw_payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not isinstance(raw_payload, dict):
        raise ValueError("wrong question input must be a JSON object")

    question_payload = raw_payload.get("question_payload")
    if isinstance(question_payload, dict):
        base_payload = question_payload
    else:
        base_payload = raw_payload

    normalized_payload: dict[str, Any] = {}
    for field in QUESTION_PAYLOAD_FIELDS:
        value = base_payload.get(field)
        if field in OPTIONAL_LIST_FIELDS:
            normalized_payload[field] = normalize_str_list(value)
        elif field == "difficulty_guess":
            if value in (None, ""):
                continue
            normalized_payload[field] = value
        else:
            text = normalize_text(value)
            if text is not None:
                normalized_payload[field] = text

    stem = normalized_payload.get("stem")
    if stem is None:
        raise ValueError("wrong question input must contain stem")

    question_id = normalize_text(raw_payload.get("question_id"))
    if question_id is None:
        question_id = normalize_text(base_payload.get("question_id"))
    if question_id is None:
        question_id = generate_question_id(normalized_payload)

    return question_id, normalized_payload


def join_non_empty(parts: Iterable[str | None]) -> str:
    return "\n".join(part for part in parts if part)


def load_tree_nodes() -> list[dict[str, Any]]:
    payload = json.loads(TREE_PATH.read_text(encoding="utf-8"))
    return payload["nodes"]


def load_leaf_cards() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(ROOT.glob(str(LEAF_CARD_GLOB.relative_to(ROOT)))):
        with path.open(encoding="utf-8") as fp:
            for line in fp:
                text = line.strip()
                if not text:
                    continue
                rows.append(json.loads(text))
    return rows


def list_field(row: dict[str, Any], field_name: str) -> list[str]:
    return normalize_str_list(row.get(field_name))


def aggregate_leaf_rows(
    card_rows: list[dict[str, Any]],
    inventory: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for row in card_rows:
        node_id = row["node_id"]
        node_meta = inventory[node_id]
        bucket = grouped.setdefault(
            node_id,
            {
                "node_id": node_id,
                "node_kind": node_meta["node_kind"],
                "review_role": node_meta["review_role"],
                "binding_role": node_meta["binding_role"],
                "title": row.get("title") or node_meta["name"],
                "path": row.get("path") or node_meta["path"],
                "path_text": " > ".join(row.get("path") or node_meta["path"]),
                "level": node_meta["level"],
                "aliases": [],
                "keywords": [],
                "texts": [],
                "support_text_parts": [],
                "error_text_parts": [],
                "trigger_signals": [],
                "steps": [],
                "recognition_signals": [],
                "common_errors": [],
                "failure_modes": [],
                "applicable_conditions": [],
                "special_cases": [],
                "applicable_problem_types": [],
                "formula_parts": [],
                "definition_parts": [],
                "review_cues": [],
                "source_rows": [],
            },
        )

        bucket["aliases"].extend(list_field(row, "aliases"))
        bucket["keywords"].extend(list_field(row, "keywords"))
        if text := normalize_text(row.get("text")):
            bucket["texts"].append(text)

        support_fields = [
            "method_goal",
            "formula",
            "definition",
            "core_idea",
            "boundary",
            "review_cue",
            "variable_notes",
            "derivation_hint",
        ]
        for field in support_fields:
            if text := normalize_text(row.get(field)):
                bucket["support_text_parts"].append(text)
                if field == "formula":
                    bucket["formula_parts"].append(text)
                if field == "definition":
                    bucket["definition_parts"].append(text)
                if field == "review_cue":
                    bucket["review_cues"].append(text)

        list_support_fields = [
            "trigger_signals",
            "steps",
            "recognition_signals",
            "applicable_conditions",
            "special_cases",
            "applicable_problem_types",
        ]
        for field in list_support_fields:
            values = list_field(row, field)
            bucket["support_text_parts"].extend(values)
            bucket[field].extend(values)

        error_fields = ["common_errors", "failure_modes"]
        for field in error_fields:
            values = list_field(row, field)
            bucket["error_text_parts"].extend(values)
            bucket[field].extend(values)

        bucket["source_rows"].append(row)

    aggregated_rows: list[dict[str, Any]] = []
    for node_id, row in grouped.items():
        title = row["title"]
        aliases = unique_list(row["aliases"])
        keywords = unique_list(row["keywords"])
        support_text = unique_list(row["support_text_parts"])
        error_text = unique_list(row["error_text_parts"])
        full_text_parts = unique_list(
            [
                title,
                row["path_text"],
                *aliases,
                *keywords,
                *row["texts"],
                *support_text,
                *error_text,
            ]
        )
        search_text = "\n".join(full_text_parts)
        row["aliases"] = aliases
        row["keywords"] = keywords
        row["support_text"] = "\n".join(support_text)
        row["error_text"] = "\n".join(error_text)
        row["search_text"] = search_text
        row["identity_text"] = "\n".join(unique_list([title, row["path_text"], *aliases]))
        row["title_features"] = build_text_features(title)
        row["alias_features"] = build_text_features(" ".join(aliases))
        row["keyword_features"] = build_text_features(" ".join(keywords))
        row["path_features"] = build_text_features(row["path_text"])
        row["overall_features"] = build_text_features(search_text)
        row["support_features"] = build_text_features(row["support_text"])
        row["error_features"] = build_text_features(row["error_text"])
        row["focus_terms"] = build_focus_terms(search_text)
        row["identity_focus_terms"] = build_focus_terms(row["identity_text"])
        aggregated_rows.append(row)

    aggregated_rows.sort(key=lambda item: item["node_id"])
    return aggregated_rows


def is_descendant(leaf_node_id: str, subtree_node_id: str) -> bool:
    return leaf_node_id.startswith(subtree_node_id + ".")


def build_subtree_rows(
    tree_nodes: list[dict[str, Any]],
    leaf_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    subtrees: list[dict[str, Any]] = []
    for node in tree_nodes:
        if node.get("is_leaf"):
            continue
        if node.get("level") not in SUBTREE_LEVELS:
            continue

        descendants = [
            leaf for leaf in leaf_rows if is_descendant(leaf["node_id"], node["node_id"])
        ]
        if not descendants:
            continue

        titles = unique_list(leaf["title"] for leaf in descendants)
        aliases = unique_list(
            alias for leaf in descendants for alias in leaf.get("aliases", [])
        )
        keywords = unique_list(
            keyword for leaf in descendants for keyword in leaf.get("keywords", [])
        )
        text_parts = unique_list(
            [
                node["name"],
                node["path_text"],
                *titles[:60],
                *aliases[:80],
                *keywords[:120],
            ]
        )
        search_text = "\n".join(text_parts)
        subtrees.append(
            {
                "node_id": node["node_id"],
                "name": node["name"],
                "level": node["level"],
                "path": node["path"],
                "path_text": node["path_text"],
                "leaf_node_ids": [leaf["node_id"] for leaf in descendants],
                "child_leaf_count": len(descendants),
                "search_text": search_text,
                "overall_features": build_text_features(search_text),
                "title_features": build_text_features(node["name"]),
                "path_features": build_text_features(node["path_text"]),
                "focus_terms": build_focus_terms(search_text),
            }
        )
    subtrees.sort(key=lambda item: item["node_id"])
    return subtrees


def compact_text(value: str | None) -> str:
    return normalize_fragment(expand_math_surface_text(value or ""))


def phrase_in_text(phrase: str, texts: Iterable[str]) -> bool:
    normalized_phrase = compact_text(phrase)
    if not normalized_phrase:
        return False
    for text in texts:
        if normalized_phrase in compact_text(text):
            return True
    return False


def match_phrases(texts: Iterable[str], phrases: Iterable[str], *, limit: int = 6) -> list[str]:
    matched: list[str] = []
    for phrase in phrases:
        if len(matched) >= limit:
            break
        normalized = normalize_text(phrase)
        if normalized is None or len(normalized) < 2:
            continue
        if phrase_in_text(normalized, texts):
            matched.append(normalized)
    return unique_list(matched)


def extract_snippet(text: str, phrase: str, *, width: int = 18) -> str | None:
    normalized_text = text.strip()
    if not normalized_text:
        return None
    index = normalized_text.find(phrase)
    if index == -1:
        return None
    start = max(0, index - width)
    end = min(len(normalized_text), index + len(phrase) + width)
    snippet = normalized_text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(normalized_text):
        snippet = snippet + "..."
    return snippet


def quoted_fragments(question_payload: dict[str, Any], phrases: list[str]) -> list[str]:
    texts = [
        question_payload.get("stem") or "",
        question_payload.get("correct_answer") or "",
        question_payload.get("solution_text") or "",
        question_payload.get("student_answer") or "",
        question_payload.get("teacher_comment") or "",
    ]
    fragments: list[str] = []
    for phrase in phrases:
        for text in texts:
            snippet = extract_snippet(text, phrase)
            if snippet and snippet not in fragments:
                fragments.append(snippet)
            if len(fragments) >= 3:
                return fragments
    return fragments


def question_feature_map(question_payload: dict[str, Any]) -> dict[str, TextFeatures]:
    stem = question_payload.get("stem") or ""
    question_type = question_payload.get("question_type") or ""
    correct_answer = question_payload.get("correct_answer") or ""
    solution_text = question_payload.get("solution_text") or ""
    student_answer = question_payload.get("student_answer") or ""
    teacher_comment = question_payload.get("teacher_comment") or ""
    tags = " ".join(question_payload.get("tags", []))
    source_name = question_payload.get("source_name") or ""
    source_section = question_payload.get("source_section") or ""

    return {
        "stem": build_text_features(stem),
        "topic": build_text_features(
            join_non_empty([stem, question_type, tags, source_name, source_section])
        ),
        "correct_answer": build_text_features(correct_answer),
        "solution": build_text_features(join_non_empty([correct_answer, solution_text])),
        "error": build_text_features(join_non_empty([student_answer, teacher_comment])),
        "overall": build_text_features(
            join_non_empty(
                [
                    stem,
                    question_type,
                    correct_answer,
                    solution_text,
                    student_answer,
                    teacher_comment,
                    tags,
                    source_name,
                    source_section,
                ]
            )
        ),
    }


def build_embedding_query_text(question_payload: dict[str, Any]) -> str:
    parts: list[str] = []
    stem = normalize_text(question_payload.get("stem"))
    if stem:
        parts.append("题干：" + stem)
    question_type = normalize_text(question_payload.get("question_type"))
    if question_type:
        parts.append("题型：" + question_type)
    correct_answer = normalize_text(question_payload.get("correct_answer"))
    if correct_answer:
        parts.append("标准答案：" + correct_answer)
    solution_text = normalize_text(question_payload.get("solution_text"))
    if solution_text:
        parts.append("解析：" + solution_text)
    student_answer = normalize_text(question_payload.get("student_answer"))
    if student_answer:
        parts.append("学生答案：" + student_answer)
    teacher_comment = normalize_text(question_payload.get("teacher_comment"))
    if teacher_comment:
        parts.append("教师点评：" + teacher_comment)
    tags = normalize_str_list(question_payload.get("tags"))
    if tags:
        parts.append("标签：" + "；".join(tags))
    return "\n".join(parts)


def build_sparse_terms(text: str | None) -> list[str]:
    if not text:
        return []

    terms: list[str] = []
    expanded = expand_math_surface_text(text)
    for raw_token in TOKEN_RE.findall(expanded):
        token = normalize_fragment(raw_token)
        if not token:
            continue
        if len(token) <= 12:
            terms.append(f"tok:{token}")
        if len(token) >= 2:
            for index in range(len(token) - 1):
                terms.append(f"bg:{token[index:index + 2]}")
        if len(token) >= 3:
            for index in range(len(token) - 2):
                terms.append(f"tg:{token[index:index + 3]}")
    return terms


class LocalSparseLeafIndex:
    def __init__(self, leaf_rows: list[dict[str, Any]]) -> None:
        self.doc_count = 0
        self.avg_doc_length = 1.0
        self.doc_lengths: dict[str, int] = {}
        self.doc_freqs: Counter[str] = Counter()
        self.inverted_index: dict[str, list[tuple[str, int]]] = defaultdict(list)

        total_length = 0
        for leaf_row in leaf_rows:
            node_id = leaf_row["node_id"]
            term_counter = Counter(build_sparse_terms(leaf_row["search_text"]))
            if not term_counter:
                continue

            doc_length = sum(term_counter.values())
            self.doc_lengths[node_id] = doc_length
            total_length += doc_length
            self.doc_count += 1

            for term, tf in term_counter.items():
                self.inverted_index[term].append((node_id, tf))
                self.doc_freqs[term] += 1

        if self.doc_count > 0:
            self.avg_doc_length = total_length / self.doc_count

    def search(self, query_text: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        if self.doc_count <= 0:
            return []

        query_counter = Counter(build_sparse_terms(query_text))
        if not query_counter:
            return []

        scores: dict[str, float] = defaultdict(float)
        for term, qtf in query_counter.items():
            postings = self.inverted_index.get(term)
            if not postings:
                continue

            df = self.doc_freqs[term]
            idf = math.log(1.0 + (self.doc_count - df + 0.5) / (df + 0.5))
            query_weight = 1.0 + math.log(max(1, qtf))

            for node_id, tf in postings:
                doc_length = self.doc_lengths[node_id]
                denom = tf + SPARSE_BM25_K1 * (
                    1.0 - SPARSE_BM25_B + SPARSE_BM25_B * doc_length / self.avg_doc_length
                )
                bm25 = idf * ((tf * (SPARSE_BM25_K1 + 1.0)) / denom)
                scores[node_id] += bm25 * query_weight

        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return [
            {"node_id": node_id, "bm25_score": safe_round(score)}
            for node_id, score in ranked[: max(1, top_k)]
            if score > 0
        ]


def explicit_phrase_bonus(question_payload: dict[str, Any], phrases: Iterable[str]) -> float:
    texts = [
        question_payload.get("stem") or "",
        question_payload.get("correct_answer") or "",
        question_payload.get("solution_text") or "",
        question_payload.get("student_answer") or "",
        question_payload.get("teacher_comment") or "",
    ]
    hits = match_phrases(texts, phrases, limit=8)
    if not hits:
        return 0.0
    return min(1.0, 0.2 * len(hits))


def level_prior(level: int) -> float:
    if level <= 2:
        return 1.0
    if level == 3:
        return 0.92
    if level == 4:
        return 0.9
    if level >= 5:
        return 1.0
    return 0.85


def subtree_score(
    question_payload: dict[str, Any],
    question_features: dict[str, TextFeatures],
    subtree_row: dict[str, Any],
    focus_profile: dict[str, Any] | None = None,
) -> float:
    topic_score = feature_match_score(
        question_features["topic"], subtree_row["overall_features"]
    )
    solution_score = feature_match_score(
        question_features["solution"], subtree_row["overall_features"]
    )
    focus_score = weighted_focus_overlap_score(
        subtree_row.get("focus_terms", frozenset()),
        focus_profile or {},
    )
    rule_score = explicit_phrase_bonus(
        question_payload,
        [subtree_row["name"], *subtree_row["path"]],
    )
    compact_question = compact_text(
        join_non_empty(
            [
                question_payload.get("stem"),
                question_payload.get("correct_answer"),
                question_payload.get("solution_text"),
                question_payload.get("student_answer"),
                question_payload.get("teacher_comment"),
            ]
        )
    )
    anchor_bonus = 0.0
    subtree_name = subtree_row["name"]
    if subtree_name == "导数":
        has_explicit_derivative_signal = any(
            term in compact_question for term in ("导数", "求导", "导函数", "可导")
        )
        if has_explicit_derivative_signal:
            anchor_bonus += 0.45
        if has_explicit_derivative_signal and any(
            term in compact_question for term in ("单调性", "极值", "最值", "切线")
        ):
            anchor_bonus += 0.20
    if subtree_name == "函数":
        if "函数" in compact_question:
            anchor_bonus += 0.10
        if any(term in compact_question for term in ("定义域", "值域", "奇偶", "周期", "对称")):
            anchor_bonus += 0.20
    if subtree_name == "定积分":
        if any(term in compact_question for term in ("积分", "面积", "曲边梯形")):
            anchor_bonus += 0.45
    if subtree_name == "概率":
        if any(term in compact_question for term in ("概率", "事件", "互斥", "独立", "至少")):
            anchor_bonus += 0.45
    if subtree_name == "随机变量":
        if any(term in compact_question for term in ("期望", "方差", "分布列", "随机变量")):
            anchor_bonus += 0.45
    if subtree_name == "解析几何":
        if any(term in compact_question for term in ("直线", "圆", "椭圆", "双曲线", "抛物线")):
            anchor_bonus += 0.35
    raw_score = (
        0.43 * topic_score
        + 0.20 * solution_score
        + 0.15 * rule_score
        + 0.22 * focus_score
    )
    return clamp_score((raw_score + anchor_bonus) * level_prior(subtree_row["level"]))


def recall_score(
    question_payload: dict[str, Any],
    question_features: dict[str, TextFeatures],
    leaf_row: dict[str, Any],
) -> float:
    overall_score = feature_match_score(
        question_features["overall"], leaf_row["overall_features"]
    )
    keyword_score = feature_match_score(
        question_features["topic"],
        build_text_features(
            " ".join(
                [
                    leaf_row["title"],
                    " ".join(leaf_row.get("keywords", [])),
                    leaf_row["path_text"],
                ]
            )
        ),
    )
    solution_score = feature_match_score(
        question_features["solution"], leaf_row["support_features"]
    )
    exact_bonus = explicit_phrase_bonus(
        question_payload,
        [leaf_row["title"], *leaf_row.get("aliases", []), *leaf_row.get("keywords", [])],
    )
    return clamp_score(
        0.50 * overall_score
        + 0.25 * keyword_score
        + 0.15 * solution_score
        + 0.10 * exact_bonus
    )


def matched_path_terms(question_payload: dict[str, Any], leaf_row: dict[str, Any]) -> list[str]:
    texts = [
        question_payload.get("stem") or "",
        question_payload.get("correct_answer") or "",
        question_payload.get("solution_text") or "",
        question_payload.get("student_answer") or "",
        question_payload.get("teacher_comment") or "",
    ]
    path_terms = [
        term for term in leaf_row["path"] if term not in GENERIC_PATH_TERMS and len(term) >= 2
    ]
    return match_phrases(texts, path_terms, limit=5)


def infer_solution_pattern(question_payload: dict[str, Any], leaf_row: dict[str, Any]) -> str | None:
    texts = [
        question_payload.get("solution_text") or "",
        question_payload.get("correct_answer") or "",
        question_payload.get("stem") or "",
    ]
    candidate_phrases = unique_list(
        [
            *leaf_row.get("trigger_signals", []),
            *leaf_row.get("steps", []),
            *leaf_row.get("recognition_signals", []),
            *leaf_row.get("applicable_conditions", []),
            *leaf_row.get("special_cases", []),
            *leaf_row.get("keywords", []),
        ]
    )
    for phrase in candidate_phrases:
        if len(phrase) < 3:
            continue
        if phrase_in_text(phrase, texts):
            return phrase

    compact_solution = compact_text(join_non_empty(texts))
    if not compact_solution:
        return None

    if leaf_row["node_kind"] == "method":
        if "求导" in compact_solution and phrase_in_text("求导", [leaf_row["search_text"]]):
            return "解析中涉及先求导再推进后续判断"
        if "符号" in compact_solution and phrase_in_text("符号", [leaf_row["search_text"]]):
            return "解析中出现符号变化或符号表判断"
    if leaf_row["node_kind"] == "formula":
        if leaf_row.get("formula_parts"):
            return "标准答案与该公式卡的表达式或使用条件接近"
    return None


def infer_error_pattern(question_payload: dict[str, Any], leaf_row: dict[str, Any]) -> str | None:
    texts = [
        question_payload.get("student_answer") or "",
        question_payload.get("teacher_comment") or "",
    ]
    for phrase in unique_list(
        [*leaf_row.get("common_errors", []), *leaf_row.get("failure_modes", [])]
    ):
        if len(phrase) < 3:
            continue
        if phrase_in_text(phrase, texts):
            return phrase

    compact_error = compact_text(join_non_empty(texts))
    if not compact_error:
        return None

    if "变号" in compact_error and phrase_in_text("变号", [leaf_row["search_text"]]):
        return "学生错误与是否判断导函数变号有关"
    if "端点" in compact_error and phrase_in_text("端点", [leaf_row["search_text"]]):
        return "学生错误与端点检查有关"
    if "定义域" in compact_error and phrase_in_text("定义域", [leaf_row["search_text"]]):
        return "学生错误与定义域限制有关"
    return None


def leaf_score(
    question_payload: dict[str, Any],
    question_features: dict[str, TextFeatures],
    leaf_row: dict[str, Any],
    subtree_score_by_id: dict[str, float],
    sparse_score_by_id: dict[str, float] | None = None,
    embedding_score_by_id: dict[str, float] | None = None,
    focus_profile: dict[str, Any] | None = None,
    identity_focus_profile: dict[str, Any] | None = None,
) -> tuple[float, dict[str, float], dict[str, Any]]:
    semantic_match = clamp_score(
        0.35 * feature_match_score(question_features["overall"], leaf_row["overall_features"])
        + 0.35 * feature_match_score(question_features["topic"], leaf_row["overall_features"])
        + 0.20 * feature_match_score(question_features["solution"], leaf_row["overall_features"])
        + 0.10 * feature_match_score(question_features["error"], leaf_row["error_features"])
    )

    title_match = feature_match_score(question_features["topic"], leaf_row["title_features"])
    keyword_match = feature_match_score(
        question_features["overall"], leaf_row["keyword_features"]
    )
    alias_match = feature_match_score(
        question_features["overall"], leaf_row["alias_features"]
    )
    path_match = feature_match_score(question_features["topic"], leaf_row["path_features"])
    exact_bonus = explicit_phrase_bonus(
        question_payload,
        [leaf_row["title"], *leaf_row.get("aliases", []), *leaf_row.get("keywords", [])],
    )
    keyword_match_score = clamp_score(
        0.30 * title_match
        + 0.30 * keyword_match
        + 0.15 * alias_match
        + 0.15 * path_match
        + 0.10 * exact_bonus
    )

    solution_pattern = infer_solution_pattern(question_payload, leaf_row)
    solution_pattern_bonus = 0.30 if solution_pattern else 0.0
    solution_alignment = clamp_score(
        0.55 * feature_match_score(question_features["solution"], leaf_row["support_features"])
        + 0.20 * feature_match_score(question_features["correct_answer"], leaf_row["support_features"])
        + 0.25 * solution_pattern_bonus
    )
    focus_alignment = weighted_focus_overlap_score(
        leaf_row.get("focus_terms", frozenset()),
        focus_profile or {},
    )
    identity_alignment = weighted_focus_overlap_score(
        leaf_row.get("identity_focus_terms", frozenset()),
        identity_focus_profile or {},
    )
    focus_alignment = clamp_score(0.60 * focus_alignment + 0.40 * identity_alignment)

    granularity_fit = clamp_score(
        0.45 * level_prior(leaf_row["level"])
        + 0.55 * max(title_match, keyword_match, solution_alignment)
    )

    binding_role_score = 1.0 if leaf_row["binding_role"] == "primary_allowed" else 0.6

    matching_subtrees = [
        score
        for subtree_id, score in subtree_score_by_id.items()
        if is_descendant(leaf_row["node_id"], subtree_id)
    ]
    subtree_bias = max(matching_subtrees) if matching_subtrees else 0.0
    rule_score = clamp_score(0.55 * exact_bonus + 0.45 * subtree_bias)
    bm25_score = 0.0
    if sparse_score_by_id:
        bm25_score = clamp_score(sparse_score_by_id.get(leaf_row["node_id"], 0.0))
    embedding_score = 0.0
    if embedding_score_by_id:
        embedding_score = clamp_score(embedding_score_by_id.get(leaf_row["node_id"], 0.0))

    bind_score = clamp_score(
        0.19 * semantic_match
        + 0.12 * keyword_match_score
        + 0.18 * solution_alignment
        + 0.08 * granularity_fit
        + 0.05 * binding_role_score
        + 0.06 * rule_score
        + 0.12 * bm25_score
        + 0.10 * embedding_score
        + 0.10 * focus_alignment
    )

    matched_keywords = match_phrases(
        [
            question_payload.get("stem") or "",
            question_payload.get("correct_answer") or "",
            question_payload.get("solution_text") or "",
            question_payload.get("student_answer") or "",
            question_payload.get("teacher_comment") or "",
        ],
        leaf_row.get("keywords", []),
        limit=6,
    )
    matched_aliases = match_phrases(
        [
            question_payload.get("stem") or "",
            question_payload.get("correct_answer") or "",
            question_payload.get("solution_text") or "",
            question_payload.get("student_answer") or "",
            question_payload.get("teacher_comment") or "",
        ],
        leaf_row.get("aliases", []),
        limit=4,
    )
    path_terms = matched_path_terms(question_payload, leaf_row)
    error_pattern = infer_error_pattern(question_payload, leaf_row)

    evidence = {
        "matched_keywords": matched_keywords,
        "matched_aliases": matched_aliases,
        "matched_path_terms": path_terms,
        "matched_solution_pattern": solution_pattern,
        "matched_error_pattern": error_pattern,
        "quoted_fragments": quoted_fragments(
            question_payload,
            unique_list([*matched_keywords, *matched_aliases, *path_terms]),
        ),
    }
    breakdown = {
        "semantic_match_score": safe_round(semantic_match),
        "keyword_match_score": safe_round(keyword_match_score),
        "solution_alignment_score": safe_round(solution_alignment),
        "granularity_fit_score": safe_round(granularity_fit),
        "binding_role_score": safe_round(binding_role_score),
        "bm25_score": safe_round(bm25_score),
        "embedding_score": safe_round(embedding_score),
        "identity_alignment_score": safe_round(identity_alignment),
        "focus_alignment_score": safe_round(focus_alignment),
        "rule_score": safe_round(rule_score),
    }
    return bind_score, breakdown, evidence


def build_reason(
    leaf_row: dict[str, Any],
    evidence: dict[str, Any],
    *,
    primary: bool,
) -> str:
    parts: list[str] = []
    matched_keywords = evidence.get("matched_keywords") or []
    matched_aliases = evidence.get("matched_aliases") or []
    matched_path_terms = evidence.get("matched_path_terms") or []
    matched_solution_pattern = evidence.get("matched_solution_pattern")
    matched_error_pattern = evidence.get("matched_error_pattern")

    if matched_keywords:
        parts.append("命中关键词：" + "、".join(matched_keywords[:4]))
    if matched_aliases:
        parts.append("命中别名：" + "、".join(matched_aliases[:3]))
    if matched_path_terms:
        parts.append("路径语境贴近：" + "、".join(matched_path_terms[:3]))
    if matched_solution_pattern:
        parts.append("解析模式匹配：" + matched_solution_pattern)
    if matched_error_pattern:
        parts.append("错误信号相关：" + matched_error_pattern)
    if not parts:
        parts.append(f"题干与解析文本和叶子卡“{leaf_row['title']}”的检索文本最接近")
    if primary:
        parts.append("该叶子对题目核心求解动作的解释最完整")
    return "；".join(parts)


def build_secondary_reason(
    primary_entry: dict[str, Any],
    candidate_entry: dict[str, Any],
) -> str:
    primary_solution = primary_entry["score_breakdown"]["solution_alignment_score"]
    candidate_solution = candidate_entry["score_breakdown"]["solution_alignment_score"]
    if candidate_solution < primary_solution:
        return "与主叶子相关，但解析主步骤更贴近主叶子。"
    primary_path = primary_entry["path"]
    candidate_path = candidate_entry["path"]
    if primary_path[:-1] == candidate_path[:-1]:
        return "同属相近知识分支，但该候选更像辅助背景或前置步骤。"
    return "相关性较高，但不是题目最核心的主绑定对象。"


def compute_binding_confidence(primary_score: float, secondary_score: float | None) -> float:
    gap = primary_score if secondary_score is None else max(0.0, primary_score - secondary_score)
    gap_bonus = min(1.0, gap / 0.25)
    confidence = clamp_score(0.72 * primary_score + 0.28 * gap_bonus)
    return safe_round(confidence)


def summarize_result(result: WrongQuestionBindingResult) -> dict[str, Any]:
    record = result.binding_record
    return {
        "question_id": record["question_id"],
        "primary_node_id": record["primary_binding"]["node_id"],
        "secondary_node_ids": [
            entry["node_id"] for entry in record.get("secondary_bindings", [])
        ],
        "binding_confidence": record["binding_confidence"],
        "top_k_node_ids": [entry["node_id"] for entry in record["top_k_candidates"]],
        "coarse_subtrees": [
            entry["node_id"] for entry in result.coarse_subtree_candidates
        ],
        "candidate_pool_size": result.candidate_pool_size,
    }


class WrongQuestionBinder:
    def __init__(
        self,
        *,
        embedding_index: LeafEmbeddingIndex | None = None,
        embedding_client: FoundryLeafEmbeddingClient | None = None,
        enable_embeddings: bool = True,
    ) -> None:
        inventory = load_inventory()
        card_rows = load_leaf_cards()
        tree_nodes = load_tree_nodes()
        self.leaf_rows = aggregate_leaf_rows(card_rows, inventory)
        self.leaf_by_id = {row["node_id"]: row for row in self.leaf_rows}
        self.subtree_rows = build_subtree_rows(tree_nodes, self.leaf_rows)
        self.subtree_by_id = {row["node_id"]: row for row in self.subtree_rows}
        self.sparse_index = LocalSparseLeafIndex(self.leaf_rows)
        self.focus_doc_count = len(self.leaf_rows)
        self.focus_doc_freqs: Counter[str] = Counter()
        self.identity_doc_freqs: Counter[str] = Counter()
        for leaf_row in self.leaf_rows:
            for term in leaf_row.get("focus_terms", frozenset()):
                self.focus_doc_freqs[term] += 1
            for term in leaf_row.get("identity_focus_terms", frozenset()):
                self.identity_doc_freqs[term] += 1
        self.embedding_index = embedding_index
        self.embedding_client = embedding_client
        self.enable_embeddings = enable_embeddings

    @classmethod
    def from_environment(
        cls,
        *,
        enable_embeddings: bool = True,
        records_path: Path = DEFAULT_LEAF_EMBED_RECORDS_PATH,
        manifest_path: Path = DEFAULT_LEAF_EMBED_MANIFEST_PATH,
        embedding_model: str = DEFAULT_EMBEDDING_DEPLOYMENT,
        openai_base_url: str = DEFAULT_FOUNDRY_OPENAI_BASE_URL,
        api_key: str | None = None,
        use_default_credential: bool = False,
    ) -> "WrongQuestionBinder":
        embedding_index = None
        embedding_client = None
        if enable_embeddings and records_path.exists() and manifest_path.exists():
            embedding_index = LeafEmbeddingIndex.load(
                records_path=records_path,
                manifest_path=manifest_path,
            )
            if (
                api_key
                or os.getenv("AZURE_AI_API_KEY")
                or os.getenv("AZURE_OPENAI_API_KEY")
                or use_default_credential
            ):
                embedding_client = FoundryLeafEmbeddingClient(
                    embedding_deployment=embedding_model,
                    openai_base_url=openai_base_url,
                    api_key=api_key,
                    use_default_credential=use_default_credential,
                )
        return cls(
            embedding_index=embedding_index,
            embedding_client=embedding_client,
            enable_embeddings=enable_embeddings,
        )

    def bind(
        self,
        raw_payload: dict[str, Any],
        *,
        top_k: int = DEFAULT_TOP_K,
        max_secondary: int = DEFAULT_MAX_SECONDARY,
        coarse_k: int = DEFAULT_COARSE_K,
        global_recall: int = DEFAULT_GLOBAL_RECALL,
        sparse_recall: int = DEFAULT_SPARSE_RECALL,
        embedding_recall: int = DEFAULT_EMBEDDING_RECALL,
    ) -> WrongQuestionBindingResult:
        top_k = max(1, top_k)
        max_secondary = max(0, max_secondary)
        coarse_k = max(1, coarse_k)
        global_recall = max(top_k, global_recall)
        sparse_recall = max(top_k, sparse_recall)
        embedding_recall = max(top_k, embedding_recall)

        question_id, question_payload = normalize_question_input(raw_payload)
        question_features = question_feature_map(question_payload)
        retrieval_query_text = build_embedding_query_text(question_payload)
        focus_profile = build_focus_profile(
            retrieval_query_text,
            self.focus_doc_freqs,
            self.focus_doc_count,
        )
        identity_focus_profile = build_focus_profile(
            retrieval_query_text,
            self.identity_doc_freqs,
            self.focus_doc_count,
        )

        coarse_ranked: list[dict[str, Any]] = []
        for subtree_row in self.subtree_rows:
            score = subtree_score(
                question_payload,
                question_features,
                subtree_row,
                focus_profile,
            )
            if score <= 0:
                continue
            coarse_ranked.append(
                {
                    "node_id": subtree_row["node_id"],
                    "name": subtree_row["name"],
                    "path": subtree_row["path"],
                    "path_text": subtree_row["path_text"],
                    "score": score,
                    "child_leaf_count": subtree_row["child_leaf_count"],
                }
            )
        coarse_ranked.sort(key=lambda item: (-item["score"], item["path_text"]))
        coarse_candidates = coarse_ranked[:coarse_k]
        coarse_score_by_id = {item["node_id"]: item["score"] for item in coarse_candidates}

        sparse_candidates = self.sparse_index.search(
            retrieval_query_text,
            top_k=sparse_recall,
        )
        sparse_score_by_id: dict[str, float] = {}
        if sparse_candidates:
            max_sparse_score = max(
                float(candidate["bm25_score"]) for candidate in sparse_candidates
            )
            if max_sparse_score > 0:
                for candidate in sparse_candidates:
                    sparse_score_by_id[candidate["node_id"]] = clamp_score(
                        float(candidate["bm25_score"]) / max_sparse_score
                    )

        recall_ranked: list[tuple[float, str]] = []
        for leaf_row in self.leaf_rows:
            score = recall_score(question_payload, question_features, leaf_row)
            if score <= 0:
                continue
            recall_ranked.append((score, leaf_row["node_id"]))
        recall_ranked.sort(
            key=lambda item: (-item[0], self.leaf_by_id[item[1]]["path_text"])
        )

        embedding_candidates: list[dict[str, Any]] = []
        embedding_score_by_id: dict[str, float] = {}
        if (
            self.enable_embeddings
            and self.embedding_index is not None
            and self.embedding_client is not None
        ):
            query_vector = unit_normalize(
                self.embedding_client.embed_query(retrieval_query_text)
            )
            embedding_candidates = self.embedding_index.search_by_vector(
                query_vector,
                top_k=embedding_recall,
            )
            for entry in embedding_candidates:
                similarity = float(entry.get("similarity", 0.0))
                normalized_similarity = clamp_score((similarity + 1.0) / 2.0)
                embedding_score_by_id[entry["node_id"]] = normalized_similarity

        candidate_leaf_ids: set[str] = set()
        for coarse_candidate in coarse_candidates:
            subtree_id = coarse_candidate["node_id"]
            subtree_row = self.subtree_by_id[subtree_id]
            candidate_leaf_ids.update(subtree_row["leaf_node_ids"])
        for _, node_id in recall_ranked[:global_recall]:
            candidate_leaf_ids.add(node_id)
        for entry in sparse_candidates:
            candidate_leaf_ids.add(entry["node_id"])
        for entry in embedding_candidates:
            candidate_leaf_ids.add(entry["node_id"])
        if not candidate_leaf_ids:
            candidate_leaf_ids = {row["node_id"] for row in self.leaf_rows}

        scored_candidates: list[dict[str, Any]] = []
        for node_id in candidate_leaf_ids:
            leaf_row = self.leaf_by_id[node_id]
            bind_score, breakdown, evidence = leaf_score(
                question_payload,
                question_features,
                leaf_row,
                coarse_score_by_id,
                sparse_score_by_id,
                embedding_score_by_id,
                focus_profile,
                identity_focus_profile,
            )
            scored_candidates.append(
                {
                    "node_id": leaf_row["node_id"],
                    "title": leaf_row["title"],
                    "node_kind": leaf_row["node_kind"],
                    "review_role": leaf_row["review_role"],
                    "binding_role": leaf_row["binding_role"],
                    "path": leaf_row["path"],
                    "path_text": leaf_row["path_text"],
                    "bind_score": bind_score,
                    "score_breakdown": breakdown,
                    "evidence": evidence,
                    "_leaf_row": leaf_row,
                }
            )

        scored_candidates.sort(
            key=lambda item: (-item["bind_score"], item["path_text"])
        )
        top_candidates_raw = scored_candidates[:top_k]
        if not top_candidates_raw:
            raise ValueError("binder could not retrieve any candidate leaf nodes")

        top_candidates: list[dict[str, Any]] = []
        for rank, item in enumerate(top_candidates_raw, start=1):
            leaf_row = item.pop("_leaf_row")
            reason = build_reason(leaf_row, item["evidence"], primary=(rank == 1))
            candidate_entry = {
                "node_id": item["node_id"],
                "rank": rank,
                "bind_score": safe_round(item["bind_score"]),
                "title": item["title"],
                "node_kind": item["node_kind"],
                "review_role": item["review_role"],
                "binding_role": item["binding_role"],
                "path": item["path"],
                "score_breakdown": item["score_breakdown"],
                "evidence": item["evidence"],
                "reason": reason,
            }
            top_candidates.append(candidate_entry)

        primary_binding = dict(top_candidates[0])
        secondary_bindings: list[dict[str, Any]] = []
        primary_raw_score = top_candidates_raw[0]["bind_score"]
        for candidate in top_candidates[1:]:
            if len(secondary_bindings) >= max_secondary:
                break
            score_gap = primary_binding["bind_score"] - candidate["bind_score"]
            if candidate["bind_score"] < 0.45:
                continue
            if score_gap > 0.18:
                continue
            if (
                candidate["score_breakdown"]["solution_alignment_score"] < 0.20
                and candidate["score_breakdown"]["keyword_match_score"] < 0.20
            ):
                continue
            secondary_entry = dict(candidate)
            secondary_entry["why_not_primary"] = build_secondary_reason(
                primary_binding, candidate
            )
            secondary_bindings.append(secondary_entry)

        secondary_score = top_candidates[1]["bind_score"] if len(top_candidates) > 1 else None
        binding_confidence = compute_binding_confidence(
            primary_raw_score,
            secondary_score,
        )

        binding_record = {
            "question_id": question_id,
            "question_payload": question_payload,
            "primary_binding": primary_binding,
            "secondary_bindings": secondary_bindings,
            "top_k_candidates": top_candidates,
            "binding_confidence": binding_confidence,
            "binding_version": BINDER_VERSION,
            "binding_notes": [
                "scoring_policy=sparse_plus_embedding_plus_local_text_hybrid_v3",
                "coarse_routing=level_2_to_3_subtrees",
                "sparse_recall_enabled=true",
                "sparse_candidate_count=" + str(len(sparse_candidates)),
                "embedding_recall_enabled="
                + ("true" if bool(embedding_candidates) else "false"),
                "embedding_candidate_count=" + str(len(embedding_candidates)),
                "coarse_subtree_candidates="
                + ", ".join(candidate["node_id"] for candidate in coarse_candidates),
            ],
            "source": "wrong_question_binder.py",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }

        return WrongQuestionBindingResult(
            normalized_question={"question_id": question_id, **question_payload},
            binding_record=binding_record,
            coarse_subtree_candidates=[
                {
                    "node_id": entry["node_id"],
                    "name": entry["name"],
                    "path": entry["path"],
                    "score": safe_round(entry["score"]),
                    "child_leaf_count": entry["child_leaf_count"],
                }
                for entry in coarse_candidates
            ],
            candidate_pool_size=len(candidate_leaf_ids),
        )

    def write_output(
        self,
        result: WrongQuestionBindingResult,
        out_json: Path,
    ) -> None:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(
            json.dumps(result.binding_record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question-file", required=True)
    parser.add_argument("--out-json")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--max-secondary", type=int, default=DEFAULT_MAX_SECONDARY)
    parser.add_argument("--coarse-k", type=int, default=DEFAULT_COARSE_K)
    parser.add_argument("--global-recall", type=int, default=DEFAULT_GLOBAL_RECALL)
    parser.add_argument("--sparse-recall", type=int, default=DEFAULT_SPARSE_RECALL)
    parser.add_argument("--embedding-recall", type=int, default=DEFAULT_EMBEDDING_RECALL)
    parser.add_argument("--disable-embeddings", action="store_true")
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_DEPLOYMENT)
    parser.add_argument("--api-key")
    parser.add_argument("--openai-base-url", default=DEFAULT_FOUNDRY_OPENAI_BASE_URL)
    parser.add_argument("--embedding-records-path", default=str(DEFAULT_LEAF_EMBED_RECORDS_PATH))
    parser.add_argument("--embedding-manifest-path", default=str(DEFAULT_LEAF_EMBED_MANIFEST_PATH))
    parser.add_argument("--use-default-credential", action="store_true")
    args = parser.parse_args()

    question_path = Path(args.question_file)
    raw_payload = json.loads(question_path.read_text(encoding="utf-8"))

    binder = WrongQuestionBinder.from_environment(
        enable_embeddings=not args.disable_embeddings,
        records_path=Path(args.embedding_records_path),
        manifest_path=Path(args.embedding_manifest_path),
        embedding_model=args.embedding_model,
        openai_base_url=args.openai_base_url,
        api_key=args.api_key,
        use_default_credential=args.use_default_credential,
    )
    result = binder.bind(
        raw_payload,
        top_k=args.top_k,
        max_secondary=args.max_secondary,
        coarse_k=args.coarse_k,
        global_recall=args.global_recall,
        sparse_recall=args.sparse_recall,
        embedding_recall=args.embedding_recall,
    )

    if args.out_json:
        binder.write_output(result, Path(args.out_json))

    print(json.dumps(summarize_result(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
