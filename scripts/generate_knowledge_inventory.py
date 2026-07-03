from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path


ROOT = Path("/Users/xumuchi/Desktop/TeachAgent")
SOURCE_PATH = ROOT / "docs" / "math_knowledge_tree.md"
OUTPUT_DIR = ROOT / "docs" / "rag_inventory"
TREE_OUTPUT = OUTPUT_DIR / "knowledge_tree_typed_full.json"
LEAF_OUTPUT = OUTPUT_DIR / "leaf_nodes_full.jsonl"
OVERRIDES_PATH = OUTPUT_DIR / "node_overrides.json"


HEADING_L2_RE = re.compile(r"^##\s+\d+\.\s+(.*)$")
HEADING_L3_RE = re.compile(r"^###\s+\d+(?:\.\d+)+\s+(.*)$")
BULLET_RE = re.compile(r"^(?P<indent>\s*)-\s+(?P<name>.+)$")
PARENT_MARKER = "（父节点）"
LEAF_MARKER = "（叶子）"

APPLICATION_PATTERNS = (
    "实际应用",
    "生活优化问题",
    "综合应用",
    "建立函数模型",
)

FORMULA_PATTERNS = (
    "公式",
    "定理",
    "方程",
    "系数",
    "离心率",
    "斜率",
    "标准方程",
    "一般方程",
    "点斜式",
    "斜截式",
    "两点式",
    "截距式",
    "一般式",
    "通项",
    "期望与方差",
)

CONCEPT_PATTERNS = (
    "概念",
    "性质",
    "关系",
    "定义",
    "特征",
    "意义",
    "分类",
    "值域",
    "定义域",
    "零点",
    "单调性",
    "奇偶性",
    "周期性",
    "对称性",
    "最值",
    "结构",
)

METHOD_PATTERNS = (
    "法",
    "变换",
    "转化",
    "判定",
    "作图",
    "绘制",
    "框图",
    "算法",
    "换元",
    "求和",
    "解读",
    "识别",
    "分析",
    "讨论",
    "求解",
    "判断",
    "求值",
)

FORMULA_SPECIAL_CASES = {
    "古典概型计算",
    "几何概型计算",
    "条件概率计算",
    "二项分布概念与计算",
}

METHOD_SECTION_MARKERS = {
    "位置关系转化",
    "递推数列转化方法",
    "数列求和方法",
    "图象变换",
    "证明方法",
    "算法",
}


def strip_markers(text: str) -> str:
    return (
        text.replace(PARENT_MARKER, "")
        .replace(LEAF_MARKER, "")
        .strip()
    )


def clean_heading_name(text: str) -> str:
    name = re.sub(r"^\d+(?:\.\d+)*\s*", "", text).strip()
    return strip_markers(name)


def slugify_part(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", strip_markers(text))
    replacements = {
        "×": "x",
        "ω": "omega",
        "φ": "phi",
        "∞": "infinity",
    }
    for src, dest in replacements.items():
        normalized = normalized.replace(src, dest)
    normalized = normalized.replace("/", "_")
    normalized = normalized.replace("-", "_")
    normalized = normalized.replace("—", "_")
    normalized = normalized.replace("–", "_")
    normalized = normalized.replace("+", "_")
    normalized = normalized.replace("=", "_")
    normalized = re.sub(r"[（）()]+", "", normalized)
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "_", normalized)
    normalized = normalized.strip("_").lower()
    return normalized or "node"


def load_overrides() -> dict[str, dict]:
    if not OVERRIDES_PATH.exists():
        return {}
    return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))


def infer_leaf_kind(name: str, path: list[str]) -> str:
    if any(part in METHOD_SECTION_MARKERS for part in path):
        return "method"
    if any(pattern in name for pattern in APPLICATION_PATTERNS):
        return "application"
    if name in FORMULA_SPECIAL_CASES:
        return "formula"
    if any(pattern in name for pattern in FORMULA_PATTERNS):
        return "formula"
    if any(pattern in name for pattern in METHOD_PATTERNS):
        return "method"
    if any(pattern in name for pattern in CONCEPT_PATTERNS):
        return "concept"
    return "concept"


def build_node(
    *,
    name: str,
    parent: dict | None,
    level: int,
    is_leaf: bool,
    seen_ids: set[str],
    overrides: dict[str, dict],
) -> dict:
    path = (parent["path"] if parent else []) + [name]
    path_text = " > ".join(path)
    override = overrides.get(path_text, {})

    node_kind = "category"
    if is_leaf:
        node_kind = override.get("node_kind") or infer_leaf_kind(name, path)

    review_role = None
    binding_role = None
    if is_leaf:
        review_role = override.get("review_role", "core")
        binding_role = override.get("binding_role", "primary_allowed")

    parent_id = parent["node_id"] if parent else None
    if parent_id is None:
        node_id = "math"
    else:
        candidate = f"{parent_id}.{slugify_part(name)}"
        node_id = candidate
        suffix = 2
        while node_id in seen_ids:
            node_id = f"{candidate}_{suffix}"
            suffix += 1

    seen_ids.add(node_id)
    prerequisites = []
    if parent_id:
        prerequisites = [parent_id]

    return {
        "node_id": node_id,
        "name": name,
        "parent_id": parent_id,
        "level": level,
        "is_leaf": is_leaf,
        "node_kind": node_kind,
        "review_role": review_role,
        "binding_role": binding_role,
        "path": path,
        "path_text": path_text,
        "aliases": [],
        "prerequisites": prerequisites,
        "common_errors": [],
        "typing_source": (
            "override"
            if is_leaf and override
            else "heuristic"
            if is_leaf
            else "structural"
        ),
    }


def parse_tree() -> list[dict]:
    lines = SOURCE_PATH.read_text(encoding="utf-8").splitlines()
    nodes: list[dict] = []
    seen_ids: set[str] = set()
    overrides = load_overrides()

    root = build_node(
        name="数学",
        parent=None,
        level=0,
        is_leaf=False,
        seen_ids=seen_ids,
        overrides=overrides,
    )
    nodes.append(root)

    current_l2 = root
    current_l3 = None
    bullet_stack: list[tuple[int, dict]] = []

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line:
            continue

        match_l2 = HEADING_L2_RE.match(line)
        if match_l2:
            current_l2 = build_node(
                name=clean_heading_name(match_l2.group(1)),
                parent=root,
                level=1,
                is_leaf=False,
                seen_ids=seen_ids,
                overrides=overrides,
            )
            nodes.append(current_l2)
            current_l3 = None
            bullet_stack = []
            continue

        match_l3 = HEADING_L3_RE.match(line)
        if match_l3:
            current_l3 = build_node(
                name=clean_heading_name(match_l3.group(1)),
                parent=current_l2,
                level=2,
                is_leaf=False,
                seen_ids=seen_ids,
                overrides=overrides,
            )
            nodes.append(current_l3)
            bullet_stack = []
            continue

        match_bullet = BULLET_RE.match(line)
        if not match_bullet or current_l3 is None:
            continue

        indent = len(match_bullet.group("indent"))
        depth = indent // 2
        raw_name = match_bullet.group("name").strip()
        is_leaf = LEAF_MARKER in raw_name or PARENT_MARKER not in raw_name
        name = strip_markers(raw_name)

        while bullet_stack and bullet_stack[-1][0] >= depth:
            bullet_stack.pop()

        parent = current_l3 if depth == 0 else bullet_stack[-1][1]
        node = build_node(
            name=name,
            parent=parent,
            level=3 + depth,
            is_leaf=is_leaf,
            seen_ids=seen_ids,
            overrides=overrides,
        )
        nodes.append(node)
        if not is_leaf:
            bullet_stack.append((depth, node))

    return nodes


def write_outputs(nodes: list[dict]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    tree_payload = {
        "version": "0.1",
        "project": "TeachAgent",
        "derived_from": "docs/math_knowledge_tree.md",
        "chunk_unit": "leaf_node",
        "binding_rule": "one_wrong_question_bind_1_core_leaf_plus_0_to_1_supporting_leaf",
        "node_id_strategy": "path_based_unicode_slug",
        "nodes": nodes,
    }
    TREE_OUTPUT.write_text(
        json.dumps(tree_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    leaf_nodes = [node for node in nodes if node["is_leaf"]]
    with LEAF_OUTPUT.open("w", encoding="utf-8") as fp:
        for node in leaf_nodes:
            fp.write(json.dumps(node, ensure_ascii=False) + "\n")


def main() -> None:
    nodes = parse_tree()
    write_outputs(nodes)

    leaf_nodes = [node for node in nodes if node["is_leaf"]]
    kind_counts = Counter(node["node_kind"] for node in leaf_nodes)
    print(f"wrote {len(nodes)} nodes")
    print(f"wrote {len(leaf_nodes)} leaf nodes")
    print("leaf kinds:", dict(kind_counts))
    print(f"tree output: {TREE_OUTPUT}")
    print(f"leaf output: {LEAF_OUTPUT}")


if __name__ == "__main__":
    main()
