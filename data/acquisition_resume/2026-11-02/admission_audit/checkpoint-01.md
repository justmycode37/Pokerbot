# Admission audit checkpoint 1

Independent review in progress; no rows admitted or modified. Counts below are parsed file lengths only and are not yet eligibility findings.

- `data/corpus_splits/development-after-prospective-v1.json`: 45 rows; SHA-256 `d172e7310677b051b8dea0163fb14b06b81ad9b5847c73d735f1e2ec66c1a483`; declared counts `{'development': {'decisions': 45, 'groups': 8}, 'evaluation': {'decisions': 0, 'groups': 0}, 'train': {'decisions': 0, 'groups': 0}}`
- `data/acquisition_resume/2026-11-01/admissions/batch-001.json`: 30 rows; SHA-256 `3d2e387b997fab022c9a4a1a75d84e8dfe6d1c8606644cb353c217288dc5e0ac`; declared counts `{'baseline_decisions': 45, 'combined_groups': 10, 'combined_unique_hands': 41, 'combined_usable_decisions': 75, 'held_for_ante_eligibility_correction': 21, 'new_admitted_decisions': 30, 'new_unique_hands': 29}`
- `data/acquisition_resume/2026-11-01/admissions/batch-002.json`: 5 rows; SHA-256 `0bcc76745a35e0f8bb846abff97cdcb750f47aefef3c07d9cceb7587b9171efe`; declared counts `{'combined_groups': 12, 'combined_unique_hands': 43, 'combined_usable_decisions': 80, 'held_duplicate_report_decisions': 4, 'new_admitted_decisions': 5, 'new_unique_hands': 2}`

Next: independently reconcile source hand/action identity, raw source hashes/prefixes, state and hero legality, ante contestability, report replay facts, and duplicate keys.
