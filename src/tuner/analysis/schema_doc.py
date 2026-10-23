"""The analysis document template shown by `tuner analyze schema`."""

TEMPLATE = {
    "cache_key": "<copy from evidence bundle>",
    "tasks": [{
        "task_id": "<id from evidence>",
        "objective": "what the user was trying to accomplish",
        "summary": "1-3 sentences on how the work went",
        "what_happened": [
            {"claim": "factual observation", "evidence": ["S1", "T4"]}],
        "classification": {
            "productive_complexity": [
                {"claim": "work that was genuinely needed",
                 "evidence": ["P1"]}],
            "avoidable_overhead": [
                {"claim": "waste a better workflow could avoid",
                 "evidence": ["S2"]}],
            "insufficient_evidence": ["what cannot be judged from the data"],
        }}],
    "recommendations": [{
        "title": "short imperative title",
        "kind": "skill | rule | workflow | prompt | tooling | "
                "model-choice | none",
        "scope": "global | project | none",
        "confidence": "low | medium | high",
        "description": "what to change",
        "expected_impact": "qualitative, no dollar amounts",
        "why_it_helps": "link to the cited evidence",
        "proposed_action": "concrete next step",
        "evidence": [{"task_id": "<id>", "claim": "what this shows",
                      "refs": ["S1", "T4"]}],
        "skill_change": {
            "name": "kebab-case-name",
            "content": "full SKILL.md text incl. YAML frontmatter "
                       "(optional; only for kind=skill)"},
    }],
    "limitations": ["anything the analysis could not determine"],
}
