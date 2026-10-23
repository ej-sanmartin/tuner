"""Read Cursor's ai-tracking DB (model per conversation, summaries).

Read-only and best effort; absence or schema drift just returns empty.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path


def load_tracking(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return ({conversation_id: dominant model}, {conversation_id: title})."""
    models: dict[str, str] = {}
    titles: dict[str, str] = {}
    if not path.exists():
        return models, titles
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1",
                               uri=True, timeout=2)
    except sqlite3.Error:
        return models, titles
    try:
        counts: dict[str, dict[str, int]] = defaultdict(dict)
        for cid, model, n in conn.execute(
                "SELECT conversationId, model, COUNT(*) FROM ai_code_hashes "
                "WHERE conversationId IS NOT NULL AND model IS NOT NULL "
                "AND model != '' GROUP BY 1, 2"):
            counts[cid][model] = n
        for cid, by_model in counts.items():
            models[cid] = max(by_model, key=lambda m: by_model[m])
        for cid, title in conn.execute(
                "SELECT conversationId, title FROM conversation_summaries "
                "WHERE title IS NOT NULL AND title != ''"):
            titles[cid] = title
    except sqlite3.Error:
        pass  # schema drift: treat as no enrichment
    finally:
        conn.close()
    return models, titles
