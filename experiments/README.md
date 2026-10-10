# Experiments (October 2026)

Three controlled experiments, kept here as run. Full write-up (Chinese): `实验结论.docx`.

| Experiment | Finding | Decision in the main pipeline |
|---|---|---|
| `exp1_multilingual_retrieval` - A/B: retrieve on original text (A) vs translate to English first (B), BGE-M3, 50 synthetic articles, 30 queries | No significant difference (all 95% CIs cross 0). Translation changes legal meaning: "kuasa hukum" (defence counsel) -> "legal authority" 21 times; Indonesian names translated as words. | Retrieval, screening and quotes stay on the ORIGINAL text; translation is for people only. Already how `fairtrial/` works - nothing merged. |
| `exp2_bluesky` - keyword / hashtag / account probe | Too slow (newest relevant post 8-17 days old), 64% bot reposts, the most relevant terms return nothing. | Not used. Nothing merged. |
| `exp3_x_twitter` - X recent search, 4 rounds, ~71 requests, hand-labelled | X found 6 of 8 verified events the RSS layer missed, but 62-79% noise; the round-1 rules lost a real lead out of sample. | **Merged as a weak trigger**: `fairtrial/x_trigger.py` (rules fixed as the findings ask), `X=1 bash run_daily.sh`, "X signals" tab, digest section. Never creates cases or evidence. |

Not included, by the project's privacy rule: raw X / Bluesky posts and `.env` files.
Re-run instructions are in each folder's README / FINDINGS.
