#!/usr/bin/env python3
"""Build a self-contained interactive playground from an evolution run."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from urllib.parse import quote
from typing import Any


ROUND_FILE = re.compile(r"^round-(\d{4})\.json$")
BOT_FIELDS = (
    "bot_id", "family", "parents", "params", "rank", "played", "won", "lost",
    "capped", "win_rate", "wilson_95", "mean_points", "mean_finish",
    "mean_final_stack", "status", "offspring_ids", "invalid_actions",
    "decisions", "latency_mean_ms", "latency_p95_ms", "latency_max_ms",
    "over_1ms",
)
AGGREGATE_FIELDS = (
    "bot_id", "played", "won", "lost", "capped", "win_rate", "wilson_95",
    "mean_points", "mean_finish", "mean_final_stack", "invalid_actions",
    "decisions", "invalid_rate", "latency_mean_ms", "latency_p95_ms",
    "latency_max_ms", "over_1ms", "attempt", "gate_passed",
    "wilson_lower_bound", "exact_lower_bound", "alpha", "gate_lower_bound",
    "gate_alpha", "alpha_spent", "attempts",
)
FRESH_FIELDS = (
    "played", "won", "lost", "capped", "win_rate", "wilson_95",
    "mean_points", "mean_finish", "mean_final_stack", "invalid_actions",
    "decisions", "invalid_rate", "latency_mean_ms", "latency_p95_ms",
    "latency_max_ms", "over_1ms", "exact_lower_bound", "alpha",
)
SUMMARY_FIELDS = (
    "schema", "status", "completed_generations", "target_win_rate",
    "champion", "last_generation", "config", "statistical_method",
)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid non-finite JSON number: {value}")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream, parse_constant=_reject_json_constant)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"could not read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _project_list(value: Any, fields: tuple[str, ...], label: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a JSON list")
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ValueError(f"{label}[{index}] must be a JSON object")
        rows.append({field: raw.get(field) for field in fields})
    return rows


def _project_confirmation(value: Any, label: str) -> list[dict[str, Any]]:
    rows = _project_list(value, AGGREGATE_FIELDS, label)
    if not isinstance(value, list):
        return rows
    for output, raw in zip(rows, value):
        fresh = raw.get("attempt_result")
        output["attempt_result"] = (
            {field: fresh.get(field) for field in FRESH_FIELDS}
            if isinstance(fresh, dict) else None
        )
    return rows


def _rounds(run_dir: Path, output_parent: Path) -> list[dict[str, Any]]:
    found: list[tuple[int, Path]] = []
    for path in run_dir.iterdir():
        match = ROUND_FILE.match(path.name)
        if match and path.is_file():
            found.append((int(match.group(1)), path))
    found.sort(key=lambda item: item[0])

    result: list[dict[str, Any]] = []
    for file_generation, path in found:
        raw = _read_json(path)
        bots_raw = raw.get("bots", [])
        bots = _project_list(bots_raw, BOT_FIELDS, f"{path.name}.bots")
        json_url = quote(os.path.relpath(path, output_parent).replace(os.sep, "/"), safe="/")
        csv_path = run_dir / f"round-{file_generation:04d}.csv"
        csv_url = (
            quote(os.path.relpath(csv_path, output_parent).replace(os.sep, "/"), safe="/")
            if csv_path.is_file() else None
        )
        result.append({
            "generation": raw.get("generation", file_generation),
            "file_generation": file_generation,
            "created_at_utc": raw.get("created_at_utc"),
            "status": raw.get("status"),
            "target_win_rate": raw.get("target_win_rate"),
            "bots": bots,
            "validation": _project_list(
                raw.get("validation", []), AGGREGATE_FIELDS, f"{path.name}.validation"
            ),
            "confirmation": _project_confirmation(
                raw.get("confirmation", []), f"{path.name}.confirmation"
            ),
            "generation_summary": raw.get("generation_summary") or {},
            "json_url": json_url,
            "csv_url": csv_url,
            "json_name": path.name,
            "csv_name": csv_path.name,
        })
    return result


def _script_json(value: Any) -> str:
    """Serialize JSON safely inside a script element in a standalone HTML file."""
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _report_data(run_dir: Path, output_parent: Path) -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    summary_exists = summary_path.is_file()
    summary_raw = _read_json(summary_path) if summary_exists else {}
    summary = {field: summary_raw.get(field) for field in SUMMARY_FIELDS}
    rounds = _rounds(run_dir, output_parent)
    latest = rounds[-1] if rounds else None
    target = summary.get("target_win_rate")
    if target is None and latest is not None:
        target = latest.get("target_win_rate")

    completed = summary.get("completed_generations")
    file_generations = [item["file_generation"] for item in rounds]
    expected_end = completed if isinstance(completed, int) and completed >= 0 else None
    if expected_end is not None:
        missing = [number for number in range(1, expected_end + 1) if number not in file_generations]
    elif file_generations:
        missing = [
            number for number in range(min(file_generations), max(file_generations) + 1)
            if number not in file_generations
        ]
    else:
        missing = []
    warnings: list[str] = []
    if not summary_exists:
        warnings.append("No summary.json was found; run status and confirmation are unknown.")
    if missing:
        warnings.append("Missing round report file numbers: " + ", ".join(str(number) for number in missing) + ".")
    if not rounds:
        warnings.append("No round-NNNN.json reports were found in this run directory.")

    # Keep report objects compact and focused. Each raw JSON report remains
    # available through its download link.
    latest_bots = latest["bots"] if latest else []
    latest_validation = latest["validation"] if latest else []
    latest_confirmation = latest["confirmation"] if latest else []
    latest_generation_summary = latest["generation_summary"] if latest else {}
    summary_url = None
    if summary_exists:
        summary_url = quote(
            os.path.relpath(summary_path, output_parent).replace(os.sep, "/"), safe="/"
        )
    return {
        "schema": "pokerbot-evolution-playground-v1",
        "run_name": run_dir.name or str(run_dir),
        "summary_available": summary_exists,
        "summary_url": summary_url,
        "summary": summary,
        "target_win_rate": target,
        "completed_generations": completed,
        "rounds": rounds,
        "rounds_loaded": len(rounds),
        "missing_round_numbers": missing,
        "warnings": warnings,
        # The latest report mirrors the familiar per-generation report shape.
        "bots": latest_bots,
        "validation": latest_validation,
        "confirmation": latest_confirmation,
        "generation_summary": latest_generation_summary,
    }


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Evolution playground</title>
<style>
:root {
  color: var(--foreground, #202938);
  font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif);
  font-size: 14px;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; width: 100%; color: var(--foreground, #202938); }
body { line-height: 1.45; }
#evolution-report { width: min(100%, 728px); margin: 0 auto; padding: 0; }
h1, h2, h3, p { margin-top: 0; }
h1 { margin-bottom: 4px; font-size: 1.55rem; line-height: 1.2; }
h2 { margin-bottom: 8px; font-size: 1.12rem; }
h3 { margin-bottom: 6px; font-size: 1rem; }
p:last-child { margin-bottom: 0; }
a { color: var(--chart-1, #315bd6); }
button, select { color: var(--foreground, #202938); font: inherit; }
button, select, .download-link {
  border: 1px solid var(--border, #d7dce5);
  border-radius: var(--radius, 10px);
  background: var(--card, #fff);
  padding: 7px 10px;
}
button { cursor: pointer; }
button:hover, .download-link:hover { border-color: var(--chart-1, #315bd6); }
button:focus-visible, select:focus-visible, a:focus-visible, summary:focus-visible {
  outline: 2px solid var(--chart-1, #315bd6);
  outline-offset: 2px;
}
.page-heading { padding: 14px 0 8px; }
.eyebrow, .muted, .small { color: var(--muted-foreground, #687386); }
.eyebrow { margin: 0 0 3px; font-size: .76rem; letter-spacing: .08em; text-transform: uppercase; }
.muted { font-size: .88rem; }
.small { font-size: .82rem; }
.cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.card {
  min-width: 0;
  padding: 16px;
  border: 1px solid var(--border, #d7dce5);
  border-radius: var(--radius, 14px);
  background: var(--card, #fff);
}
.stack { display: grid; gap: 12px; }
.metric-label { margin: 0 0 3px; color: var(--muted-foreground, #687386); font-size: .78rem; }
.metric-value { overflow-wrap: anywhere; margin: 0; font-size: 1.02rem; font-weight: 650; }
.status-line { display: flex; align-items: baseline; gap: 7px; flex-wrap: wrap; }
.badge { display: inline-block; border: 1px solid var(--border, #d7dce5); border-radius: 999px; padding: 2px 8px; font-size: .76rem; }
.warning { margin-top: 10px; padding: 9px 11px; border-left: 3px solid var(--chart-5, #d97706); }
.controls { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 10px 0 0; }
.controls label { font-weight: 600; }
select { min-width: min(100%, 260px); max-width: 100%; }
.mode-tabs { display: inline-flex; gap: 6px; flex-wrap: wrap; }
.mode-tabs button[aria-pressed="true"] { border-color: var(--chart-1, #315bd6); box-shadow: inset 0 0 0 1px var(--chart-1, #315bd6); }
.chart-scroll, .table-scroll { width: 100%; overflow: auto; }
.chart-scroll { margin-top: 8px; }
.chart-svg { display: block; width: 100%; min-width: 660px; height: 380px; }
.trend-svg { display: block; width: 100%; min-width: 460px; height: 170px; }
.table-scroll { max-height: 390px; border: 1px solid var(--border, #d7dce5); border-radius: var(--radius, 10px); }
table { border-collapse: collapse; width: 100%; }
.wide-table { min-width: 1700px; }
th, td { border-bottom: 1px solid var(--border, #d7dce5); padding: 7px 9px; text-align: left; vertical-align: top; }
th { position: sticky; top: 0; z-index: 1; background: var(--card, #fff); white-space: nowrap; font-size: .78rem; }
th button { border: 0; background: transparent; padding: 0; font-weight: 650; text-align: left; }
td { font-variant-numeric: tabular-nums; }
tbody tr:last-child td { border-bottom: 0; }
td.bot-id { min-width: 160px; overflow-wrap: anywhere; font-weight: 600; }
td.params { min-width: 100px; }
details summary { color: var(--chart-1, #315bd6); cursor: pointer; }
details pre { max-width: 300px; max-height: 240px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font-size: .75rem; }
.empty { padding: 16px; color: var(--muted-foreground, #687386); text-align: center; }
.downloads { display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0 0; }
.download-link { display: inline-block; text-decoration: none; font-size: .82rem; }
.legend { display: flex; flex-wrap: wrap; gap: 12px; color: var(--muted-foreground, #687386); font-size: .8rem; }
.legend-mark { display: inline-block; width: 20px; margin-right: 5px; border-top: 3px solid var(--chart-1, #315bd6); vertical-align: middle; }
.field-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px 14px; margin: 8px 0 0; }
.field-list div { min-width: 0; }
.field-list dt { color: var(--muted-foreground, #687386); font-size: .75rem; }
.field-list dd { margin: 0; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.footer-note { padding: 4px 0 18px; }
@media (max-width: 520px) {
  .cards { grid-template-columns: 1fr; gap: 8px; }
  .page-heading { padding-top: 10px; }
  .card { padding: 16px; }
  .field-list { grid-template-columns: 1fr; }
  .controls { align-items: stretch; }
  select { width: 100%; }
}
</style>
</head>
<body>
<main id="evolution-report" aria-labelledby="page-title">
  <header class="page-heading">
    <p class="eyebrow">Pokerbot · Evolution run</p>
    <h1 id="page-title">Evolution playground</h1>
    <p id="run-name" class="muted"></p>
  </header>
  <div class="stack">
    <section class="cards" aria-label="Run overview">
      <article class="card">
        <p class="metric-label">Target outright win rate</p>
        <p id="target-value" class="metric-value">—</p>
        <p id="target-sample" class="small"></p>
      </article>
      <article class="card">
        <p class="metric-label">Progress</p>
        <p id="progress-value" class="metric-value">—</p>
        <p id="progress-detail" class="small"></p>
      </article>
      <article class="card">
        <p class="metric-label">Latest candidate</p>
        <p id="champion-value" class="metric-value">—</p>
        <p id="champion-detail" class="small"></p>
      </article>
    </section>

    <section id="warnings" class="card" hidden aria-label="Report completeness"></section>

    <section class="card" aria-labelledby="round-heading">
      <h2 id="round-heading">Round report</h2>
      <p id="round-summary" class="muted"></p>
      <div class="controls">
        <label for="round-select">Select round</label>
        <select id="round-select"></select>
      </div>
      <div class="controls mode-tabs" role="group" aria-label="Evaluation split">
        <button id="training-tab" type="button" aria-pressed="true">Training</button>
        <button id="validation-tab" type="button" aria-pressed="false">Held-out validation</button>
      </div>
      <p id="mode-note" class="small"></p>
      <div class="downloads" aria-label="Raw report downloads">
        <a id="json-download" class="download-link" href="#" download>Download raw round JSON</a>
        <a id="csv-download" class="download-link" href="#" download>Download bot CSV</a>
        <a id="summary-download" class="download-link" href="#" download hidden>Download summary JSON</a>
      </div>
    </section>

    <section class="card" aria-labelledby="chart-heading">
      <h2 id="chart-heading">Win rate with 95% Wilson intervals</h2>
      <p id="chart-note" class="muted"></p>
      <div class="legend" aria-hidden="true">
        <span><i class="legend-mark"></i>Observed outright win rate</span>
        <span>Line: reported two-sided 95% Wilson interval</span>
      </div>
      <div class="chart-scroll" tabindex="0" aria-label="Scrollable win rate chart">
        <svg id="win-chart" class="chart-svg" viewBox="0 0 780 380" role="img" aria-labelledby="win-title win-desc">
          <title id="win-title">Bot win rates and Wilson confidence intervals</title>
          <desc id="win-desc">Each evaluated bot is shown with its reported win rate, sample size, interval, and mean points.</desc>
        </svg>
      </div>
      <p class="small">Chart labels show observed rate, wins / actual matches played, and mean points. Bots with zero matches remain in the training table and are not plotted.</p>
    </section>

    <section class="card" aria-labelledby="leaderboard-heading">
      <h2 id="leaderboard-heading">Leaderboard and lineage</h2>
      <p id="table-note" class="muted"></p>
      <div class="table-scroll" tabindex="0" aria-label="Scrollable sortable leaderboard">
        <table id="leaderboard" class="wide-table">
          <thead></thead><tbody></tbody>
        </table>
      </div>
      <p class="small">Latency p95 is the maximum of per-match policy-call p95 values, as recorded by the run; it is not a pooled p95. Values are not recalculated here.</p>
    </section>

    <section class="card" aria-labelledby="generation-heading">
      <h2 id="generation-heading">Generation training summary</h2>
      <p id="generation-note" class="muted"></p>
      <dl id="generation-fields" class="field-list"></dl>
    </section>

    <section class="card" aria-labelledby="trend-heading">
      <h2 id="trend-heading">Training mean-points trend</h2>
      <p class="muted">Best-ranked training bot's mean points per match by generation. Bots and opponent mix can change each round, so this descriptive trend is not proof of improvement.</p>
      <div class="chart-scroll" tabindex="0" aria-label="Scrollable training mean-points trend">
        <svg id="trend-chart" class="trend-svg" viewBox="0 0 720 170" role="img" aria-labelledby="trend-title trend-desc">
          <title id="trend-title">Best-ranked training bot mean points by generation</title>
          <desc id="trend-desc">Training means across generations. The top-ranked bot and opponent mix change across rounds.</desc>
        </svg>
      </div>
      <p id="trend-values" class="small"></p>
    </section>

    <section class="card" aria-labelledby="confirmation-heading">
      <h2 id="confirmation-heading">Confirmation</h2>
      <p class="muted">Confirmation is shown separately from training and held-out validation. A gate result is not used to relabel the latest candidate; the run summary determines whether the champion is confirmed.</p>
      <div id="confirmation-results"></div>
    </section>

    <p class="footer-note small">Capped tables remain non-wins according to the source reports. Confidence bands and counts are read from each round report; no cap outcomes or intervals are reassigned.</p>
  </div>
</main>
<script id="report-data" type="application/json">__REPORT_JSON__</script>
<script>
"use strict";
const REPORT = JSON.parse(document.getElementById("report-data").textContent);
const BOT_FIELDS = __BOT_FIELDS__;
const numberOrNull = value => (typeof value === "number" && Number.isFinite(value) ? value : null);
const fmtNumber = (value, digits=2) => numberOrNull(value) === null ? "—" : value.toFixed(digits);
const fmtRate = value => numberOrNull(value) === null ? "—" : (value * 100).toFixed(1) + "%";
const fmtInterval = value => Array.isArray(value) && value.length >= 2 &&
  numberOrNull(value[0]) !== null && numberOrNull(value[1]) !== null
  ? (value[0] * 100).toFixed(1) + "–" + (value[1] * 100).toFixed(1) + "%"
  : "—";
const text = (node, value) => { node.textContent = value == null ? "—" : String(value); };
const element = (name, className) => {
  const node = document.createElement(name);
  if (className) node.className = className;
  return node;
};
const numericSort = value => numberOrNull(value);

function setSummary() {
  text(document.getElementById("run-name"), "Run: " + REPORT.run_name);
  const target = numberOrNull(REPORT.target_win_rate);
  text(document.getElementById("target-value"), target === null ? "Unavailable" : ">" + fmtRate(target));
  const loaded = REPORT.rounds_loaded;
  const completed = numberOrNull(REPORT.completed_generations);
  text(document.getElementById("progress-value"),
    completed === null ? loaded + " round reports loaded" : loaded + " / " + completed + " round reports");
  text(document.getElementById("progress-detail"),
    REPORT.missing_round_numbers.length
      ? "Missing report numbers: " + REPORT.missing_round_numbers.join(", ")
      : (completed === null ? "Run summary progress unavailable." : "Summary-reported completed generations: " + completed + "."));
  document.getElementById("target-sample").textContent =
    "Observed sample size is shown for each bot and split below.";

  const summary = REPORT.summary || {};
  const champion = summary.champion && typeof summary.champion === "object" ? summary.champion : {};
  const summaryConfirms = summary.status === "confirmed_target_reached" && champion.status === "confirmed";
  let latestCandidate = champion.bot_id;
  if (!latestCandidate && REPORT.rounds.length) {
    const latest = REPORT.rounds[REPORT.rounds.length - 1];
    const ranked = latest.bots.filter(row => numericSort(row.rank) !== null).sort((a,b) => a.rank - b.rank);
    latestCandidate = ranked.length ? ranked[0].bot_id : null;
  }
  text(document.getElementById("champion-value"), latestCandidate || "No candidate reported");
  text(document.getElementById("champion-detail"), summaryConfirms
    ? "Confirmed by summary.json."
    : (REPORT.summary_available
      ? "Provisional candidate; summary.json does not confirm a champion."
      : "Confirmation status unknown because summary.json is missing."));

  const warnings = document.getElementById("warnings");
  if (REPORT.warnings.length) {
    warnings.hidden = false;
    const heading = element("h2");
    text(heading, "Report completeness");
    warnings.appendChild(heading);
    for (const message of REPORT.warnings) {
      const paragraph = element("p", "warning");
      text(paragraph, message);
      warnings.appendChild(paragraph);
    }
  } else {
    warnings.hidden = true;
  }
  const summaryLink = document.getElementById("summary-download");
  if (REPORT.summary_url) {
    summaryLink.hidden = false;
    summaryLink.href = REPORT.summary_url;
  }
}

const roundSelect = document.getElementById("round-select");
let selectedIndex = 0;
let mode = "training";
let sort = { key: "rank", direction: 1 };
let csvObjectUrl = null;

function fillRoundSelector() {
  if (!REPORT.rounds.length) {
    const option = element("option");
    option.value = "0";
    option.textContent = "No round reports found";
    roundSelect.appendChild(option);
    roundSelect.disabled = true;
    return;
  }
  REPORT.rounds.forEach((round, index) => {
    const option = element("option");
    option.value = String(index);
    const evaluated = round.bots.filter(row => numericSort(row.played) > 0).length;
    const zero = round.bots.filter(row => numericSort(row.played) === 0).length;
    option.textContent = "Round " + round.generation + " · " + evaluated + " evaluated · " + zero + " offspring not played";
    roundSelect.appendChild(option);
  });
  selectedIndex = REPORT.rounds.length - 1;
  roundSelect.value = String(selectedIndex);
}

function roundNow() {
  return REPORT.rounds[selectedIndex] || null;
}

function linkedTrainingRow(round, row) {
  return round.bots.find(bot => bot.bot_id === row.bot_id) || {};
}

function currentRows(round) {
  if (!round) return [];
  if (mode === "training") return round.bots.slice();
  return round.validation.map(row => Object.assign({}, row, {
    _training: linkedTrainingRow(round, row),
    _sort_rank: linkedTrainingRow(round, row).rank
  }));
}

function displayValue(value, field) {
  if (value === null || value === undefined) return "—";
  if (field === "win_rate" || field === "best_training_win_rate") return fmtRate(value);
  if (field === "wilson_95") return fmtInterval(value);
  if (field === "mean_points" || field === "mean_finish" || field === "mean_final_stack" ||
      field === "latency_mean_ms" || field === "latency_p95_ms" || field === "latency_max_ms") {
    return fmtNumber(value, 3);
  }
  if (field === "gate_passed") return value ? "Passed" : "Not passed";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

const TRAINING_COLUMNS = [
  ["bot_id", "Bot"], ["family", "Family"], ["parents", "Parents"], ["params", "Parameters"],
  ["rank", "Rank"], ["played", "Played n"], ["won", "Won"], ["lost", "Lost"],
  ["capped", "Capped"], ["win_rate", "Win rate"], ["wilson_95", "Wilson 95%"],
  ["mean_points", "Mean points"], ["mean_finish", "Mean finish"],
  ["mean_final_stack", "Mean final stack"], ["status", "Status"],
  ["offspring_ids", "Offspring IDs"], ["invalid_actions", "Invalid actions"],
  ["decisions", "Decisions"], ["latency_mean_ms", "Latency mean ms"],
  ["latency_p95_ms", "Latency p95 ms"], ["latency_max_ms", "Latency max ms"],
  ["over_1ms", "Over 1 ms"]
];
const VALIDATION_COLUMNS = [
  ["bot_id", "Bot"], ["_family", "Family"], ["_sort_rank", "Training rank"],
  ["played", "Held-out n"], ["won", "Won"], ["lost", "Lost"], ["capped", "Capped"],
  ["win_rate", "Win rate"], ["wilson_95", "Wilson 95%"],
  ["mean_points", "Mean points"], ["mean_finish", "Mean finish"],
  ["mean_final_stack", "Mean final stack"], ["gate_passed", "Validation gate"]
];

function cellValue(row, key) {
  if (key === "_family") return row._training && row._training.family;
  if (key === "_sort_rank") return row._sort_rank;
  return row[key];
}

function cellNode(row, key) {
  const td = element("td", key === "bot_id" ? "bot-id" : (key === "params" ? "params" : ""));
  const value = cellValue(row, key);
  if (key === "params" && value != null) {
    const details = element("details");
    const summary = element("summary");
    text(summary, "View parameters");
    const pre = element("pre");
    text(pre, JSON.stringify(value, null, 2));
    details.append(summary, pre);
    td.appendChild(details);
    return td;
  }
  if (key === "parents" || key === "offspring_ids") {
    const details = element("details");
    const summary = element("summary");
    const values = Array.isArray(value) ? value : [];
    text(summary, values.length ? values.length + (key === "parents" ? " parent(s)" : " offspring") : "—");
    if (values.length) {
      const list = element("ul");
      for (const item of values) {
        const li = element("li");
        text(li, item);
        list.appendChild(li);
      }
      details.append(summary, list);
      td.appendChild(details);
    } else {
      text(td, "—");
    }
    return td;
  }
  text(td, displayValue(value, key));
  return td;
}

function renderTable(round) {
  const table = document.getElementById("leaderboard");
  const head = table.querySelector("thead");
  const body = table.querySelector("tbody");
  head.replaceChildren();
  body.replaceChildren();
  const columns = mode === "training" ? TRAINING_COLUMNS : VALIDATION_COLUMNS;
  const headerRow = element("tr");
  columns.forEach(([key, label]) => {
    const th = element("th");
    const button = element("button");
    button.type = "button";
    button.dataset.sort = key;
    button.setAttribute("aria-label", "Sort by " + label);
    button.textContent = label + (sort.key === key ? (sort.direction === 1 ? " ▲" : " ▼") : "");
    th.appendChild(button);
    headerRow.appendChild(th);
  });
  head.appendChild(headerRow);
  const rows = currentRows(round);
  rows.sort((a, b) => {
    let left = cellValue(a, sort.key);
    let right = cellValue(b, sort.key);
    if (left === null || left === undefined) return right === null || right === undefined ? 0 : 1;
    if (right === null || right === undefined) return -1;
    const leftNumber = numericSort(left);
    const rightNumber = numericSort(right);
    let compared;
    if (leftNumber !== null && rightNumber !== null) compared = leftNumber - rightNumber;
    else compared = String(Array.isArray(left) ? left.join(",") : left)
      .localeCompare(String(Array.isArray(right) ? right.join(",") : right));
    return compared * sort.direction;
  });
  if (!rows.length) {
    const tr = element("tr");
    const td = element("td", "empty");
    td.colSpan = columns.length;
    text(td, mode === "training" ? "No training bot rows in this round." : "No held-out validation leaders were tested in this round.");
    tr.appendChild(td);
    body.appendChild(tr);
  } else {
    rows.forEach(row => {
      const tr = element("tr");
      columns.forEach(([key]) => tr.appendChild(cellNode(row, key)));
      body.appendChild(tr);
    });
  }
}

function svgElement(name, attrs={}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
}

function chartText(svg, x, y, value, attrs={}) {
  const node = svgElement("text", Object.assign({x, y}, attrs));
  node.textContent = value;
  svg.appendChild(node);
  return node;
}

function chartRows(round) {
  if (!round) return [];
  if (mode === "training") return round.bots.slice();
  return round.validation.map(row => Object.assign({}, row, {
    _training: linkedTrainingRow(round, row)
  }));
}

function truncateLabel(value, max=30) {
  const label = value == null ? "Unknown bot" : String(value);
  return label.length > max ? label.slice(0, max - 1) + "…" : label;
}

function renderWinChart(round) {
  const svg = document.getElementById("win-chart");
  svg.replaceChildren();
  const title = svgElement("title", {id: "win-title"});
  title.textContent = mode === "training" ? "Training bot win rates" : "Held-out validation leader win rates";
  const desc = svgElement("desc", {id: "win-desc"});
  desc.textContent = "Every evaluated bot is shown with its reported rate, sample size, 95 percent Wilson interval when available, and mean points.";
  svg.append(title, desc);
  const rows = chartRows(round).filter(row => numericSort(row.played) !== null && row.played > 0);
  const left = 244, right = 605, top = 44, bottom = 332;
  for (let tick = 0; tick <= 4; tick += 1) {
    const rate = tick / 4;
    const x = left + (right - left) * rate;
    svg.appendChild(svgElement("line", {x1:x, y1:top-12, x2:x, y2:bottom, stroke:"var(--border, #d7dce5)", "stroke-width":1}));
    chartText(svg, x, 356, Math.round(rate * 100) + "%", {fill:"var(--muted-foreground, #687386)", "font-size":12, "text-anchor":"middle"});
  }
  chartText(svg, 625, 27, "Rate · wins/n · mean pts", {fill:"var(--muted-foreground, #687386)", "font-size":11});
  if (!rows.length) {
    chartText(svg, 244, 190, "No evaluated matches in this split for this round.", {fill:"var(--muted-foreground, #687386)", "font-size":14});
    return;
  }
  const spacing = (bottom - top) / rows.length;
  rows.forEach((row, index) => {
    const y = top + spacing * (index + 0.5);
    const rate = numericSort(row.win_rate);
    const wins = row.won == null ? "—" : String(row.won);
    const played = row.played == null ? "—" : String(row.played);
    const points = numberOrNull(row.mean_points);
    const rateLabel = rate === null ? "n/a" : fmtRate(rate);
    const label = truncateLabel(row.bot_id, 29);
    const family = mode === "validation" && row._training ? row._training.family : row.family;
    const fullDescription = String(row.bot_id || "Unknown bot") + ", " + String(family || "family unavailable") +
      "; " + rateLabel + "; " + wins + " wins from " + played + " matches; Wilson 95% " +
      fmtInterval(row.wilson_95) + "; mean points " + fmtNumber(points, 3);
    chartText(svg, 8, y + 4, label, {fill:"var(--foreground, #202938)", "font-size":12});
    if (rate !== null && rate >= 0 && rate <= 1) {
      const x = left + (right - left) * rate;
      const band = row.wilson_95;
      if (Array.isArray(band) && band.length >= 2 &&
          numberOrNull(band[0]) !== null && numberOrNull(band[1]) !== null &&
          band[0] >= 0 && band[1] <= 1) {
        const x1 = left + (right - left) * band[0];
        const x2 = left + (right - left) * band[1];
        const colorNumber = (index % 6) + 1;
        svg.appendChild(svgElement("line", {
          x1, y1:y, x2, y2:y, stroke:"var(--chart-" + colorNumber + ", #315bd6)",
          "stroke-width":3, "stroke-linecap":"round"
        }));
        svg.appendChild(svgElement("line", {
          x1, y1:y-5, x2:x1, y2:y+5, stroke:"var(--chart-" + colorNumber + ", #315bd6)", "stroke-width":1.5
        }));
        svg.appendChild(svgElement("line", {
          x1:x2, y1:y-5, x2:x2, y2:y+5, stroke:"var(--chart-" + colorNumber + ", #315bd6)", "stroke-width":1.5
        }));
      }
      const circle = svgElement("circle", {
        cx:x, cy:y, r:5, fill:"var(--chart-" + ((index % 6) + 1) + ", #315bd6)",
        stroke:"var(--card, #fff)", "stroke-width":1.5
      });
      const tip = svgElement("title");
      tip.textContent = fullDescription;
      circle.appendChild(tip);
      svg.appendChild(circle);
    }
    chartText(svg, 625, y + 4, rateLabel + " · " + wins + "/" + played + " · " +
      (points === null ? "—" : points.toFixed(3)) + " pts", {fill:"var(--foreground, #202938)", "font-size":11});
  });
}

function renderDownloads(round) {
  const jsonLink = document.getElementById("json-download");
  const csvLink = document.getElementById("csv-download");
  if (!round) {
    jsonLink.hidden = true;
    csvLink.hidden = true;
    return;
  }
  jsonLink.hidden = false;
  jsonLink.href = round.json_url;
  jsonLink.download = round.json_name;
  if (csvObjectUrl) {
    URL.revokeObjectURL(csvObjectUrl);
    csvObjectUrl = null;
  }
  if (round.csv_url) {
    csvLink.href = round.csv_url;
    csvLink.download = round.csv_name;
    csvLink.textContent = "Download source CSV";
  } else {
    const header = BOT_FIELDS;
    const lines = [header.map(csvCell).join(",")];
    for (const row of round.bots) lines.push(header.map(field => csvCell(row[field])).join(","));
    csvObjectUrl = URL.createObjectURL(new Blob([lines.join("\\r\\n") + "\\r\\n"], {type:"text/csv;charset=utf-8"}));
    csvLink.href = csvObjectUrl;
    csvLink.download = round.csv_name.replace(".csv", "-bots.csv");
    csvLink.textContent = "Download CSV from bot rows";
  }
  csvLink.hidden = false;
}

function csvCell(value) {
  const raw = value == null ? "" : (typeof value === "object" ? JSON.stringify(value) : String(value));
  return '"' + raw.replace(/"/g, '""') + '"';
}

function renderGeneration(round) {
  const summary = round ? round.generation_summary || {} : {};
  const note = document.getElementById("generation-note");
  const fields = document.getElementById("generation-fields");
  fields.replaceChildren();
  if (!round) {
    text(note, "No generation summary is available.");
    return;
  }
  const evaluated = round.bots.filter(row => numericSort(row.played) > 0).length;
  const unplayed = round.bots.filter(row => numericSort(row.played) === 0).length;
  text(note, "Round " + round.generation + ": " + round.bots.length + " training rows, " + evaluated +
    " evaluated bots, and " + unplayed + " offspring rows with zero matches.");
  const values = [
    ["Training matches", summary.training_match_count],
    ["Best training bot", summary.best_training_bot_id],
    ["Best training win rate", summary.best_training_win_rate == null ? null : fmtRate(summary.best_training_win_rate)],
    ["Best training mean points", summary.best_training_mean_points == null ? null : fmtNumber(summary.best_training_mean_points, 3)],
    ["Validation gate passes", summary.validation_gate_passes],
    ["Confirmation attempts", summary.confirmation_attempts],
    ["Confirmed target reached in round", summary.confirmed_target_reached]
  ];
  for (const [label, value] of values) {
    const wrapper = element("div");
    const dt = element("dt");
    const dd = element("dd");
    text(dt, label);
    text(dd, typeof value === "boolean" ? (value ? "Yes" : "No") : (value == null ? "—" : value));
    wrapper.append(dt, dd);
    fields.appendChild(wrapper);
  }
}

function renderConfirmation(round) {
  const container = document.getElementById("confirmation-results");
  container.replaceChildren();
  if (!round || !round.confirmation.length) {
    const empty = element("p", "empty");
    text(empty, round ? "No confirmation sample was run in this round." : "No round is selected.");
    container.appendChild(empty);
    return;
  }
  for (const row of round.confirmation) {
    const article = element("article");
    const heading = element("h3");
    text(heading, row.bot_id || "Candidate");
    const paragraph = element("p");
    const result = row.attempt_result || {};
    const freshPlayed = result.played == null ? "—" : result.played;
    const freshWon = result.won == null ? "—" : result.won;
    text(paragraph, "Cumulative descriptive sample: " + (row.won == null ? "—" : row.won) + "/" +
      (row.played == null ? "—" : row.played) + " wins (n=" + (row.played == null ? "—" : row.played) +
      "). Fresh gate sample: " + freshWon + "/" + freshPlayed + " (n=" + freshPlayed + ").");
    const detail = element("p", "small");
    const gate = row.gate_passed === true ? "Passed" : (row.gate_passed === false ? "Not passed" : "Not reported");
    text(detail, "Gate result: " + gate + " · fresh-sample exact lower bound " +
      fmtNumber(row.gate_lower_bound, 4) + " · alpha " + fmtNumber(row.gate_alpha, 6) +
      " · cumulative Wilson 95% " + fmtInterval(row.wilson_95) +
      ". This is a round-level result; champion status follows summary.json.");
    article.append(heading, paragraph, detail);
    container.appendChild(article);
  }
}

function renderRound() {
  const round = roundNow();
  if (!round) {
    text(document.getElementById("round-summary"), "No round reports are available.");
    text(document.getElementById("mode-note"), "No source data is available.");
    text(document.getElementById("chart-note"), "No source data is available.");
    text(document.getElementById("table-note"), "No source data is available.");
    renderDownloads(null);
    renderTable(null);
    renderWinChart(null);
    renderGeneration(null);
    renderConfirmation(null);
    return;
  }
  const evaluatedTraining = round.bots.filter(row => numericSort(row.played) > 0);
  const zeroPlayed = round.bots.filter(row => numericSort(row.played) === 0);
  text(document.getElementById("round-summary"),
    "Round " + round.generation + " · " + evaluatedTraining.length + " evaluated training bots · " +
    zeroPlayed.length + " offspring with 0 played · " + round.validation.length + " validation leaders · " +
    round.confirmation.length + " confirmation entries" +
    (round.created_at_utc ? " · " + round.created_at_utc : ""));
  const modeNote = mode === "training"
    ? "Training outcomes rank and select the population. Every training bot row is shown, including offspring that have not played."
    : "Held-out validation results use the separate validation pool and are shown as a promotion gate, not as training ranks.";
  text(document.getElementById("mode-note"), modeNote);
  text(document.getElementById("chart-note"), mode === "training"
    ? "Training results · all evaluated bots in the selected round. Confidence intervals are read directly from the report."
    : "Held-out validation · all validation leaders with match data. These results are separate from training.");
  text(document.getElementById("table-note"), mode === "training"
    ? "Training leaderboard, including played=0 offspring. Click a header to sort."
    : "Separate held-out leader results. Training rank is shown only as lineage context. Click a header to sort.");
  renderDownloads(round);
  renderTable(round);
  renderWinChart(round);
  renderGeneration(round);
  renderConfirmation(round);
}

function renderTrend() {
  const svg = document.getElementById("trend-chart");
  svg.replaceChildren();
  const title = svgElement("title", {id:"trend-title"});
  title.textContent = "Best-ranked training bot mean points by generation";
  const desc = svgElement("desc", {id:"trend-desc"});
  desc.textContent = "Descriptive training means; the leading bot and opponent mix can change in each generation.";
  svg.append(title, desc);
  const points = REPORT.rounds.map(round => ({
    generation: round.generation,
    value: numberOrNull(round.generation_summary && round.generation_summary.best_training_mean_points)
  }));
  const valid = points.filter(point => point.value !== null);
  const valuesText = document.getElementById("trend-values");
  if (!valid.length) {
    chartText(svg, 54, 88, "No training mean-points values are available.", {fill:"var(--muted-foreground, #687386)", "font-size":13});
    text(valuesText, "No values are present in the loaded generation summaries.");
    return;
  }
  let min = Math.min(...valid.map(point => point.value));
  let max = Math.max(...valid.map(point => point.value));
  if (min === max) { min -= 0.5; max += 0.5; }
  else { const pad = (max - min) * 0.12; min -= pad; max += pad; }
  const left = 55, right = 690, top = 22, bottom = 126;
  for (let tick=0; tick<=2; tick+=1) {
    const fraction = tick/2;
    const y = bottom - (bottom-top)*fraction;
    const value = min + (max-min)*fraction;
    svg.appendChild(svgElement("line", {x1:left, y1:y, x2:right, y2:y, stroke:"var(--border, #d7dce5)", "stroke-width":1}));
    chartText(svg, left-7, y+4, value.toFixed(2), {fill:"var(--muted-foreground, #687386)", "font-size":10, "text-anchor":"end"});
  }
  const positionX = index => points.length <= 1 ? (left+right)/2 : left + (right-left)*index/(points.length-1);
  const positionY = value => bottom - (value-min)/(max-min)*(bottom-top);
  const pathPoints = [];
  points.forEach((point,index) => {
    if (point.value === null) return;
    pathPoints.push([positionX(index),positionY(point.value)]);
  });
  if (pathPoints.length > 1) {
    const path = svgElement("polyline", {
      points:pathPoints.map(pair => pair[0]+","+pair[1]).join(" "),
      fill:"none", stroke:"var(--chart-2, #0f8b6d)", "stroke-width":2
    });
    svg.appendChild(path);
  }
  points.forEach((point,index) => {
    const x = positionX(index);
    if (point.value !== null) {
      const circle = svgElement("circle", {cx:x, cy:positionY(point.value), r:4, fill:"var(--chart-2, #0f8b6d)"});
      const tip = svgElement("title");
      tip.textContent = "Round " + point.generation + ": " + point.value.toFixed(4) + " mean points";
      circle.appendChild(tip);
      svg.appendChild(circle);
      if (points.length <= 12) chartText(svg, x, positionY(point.value)-7, point.value.toFixed(2), {
        fill:"var(--foreground, #202938)", "font-size":10, "text-anchor":"middle"
      });
    }
    if (points.length <= 12 || index === 0 || index === points.length-1 || index % Math.ceil(points.length/6) === 0) {
      chartText(svg, x, 151, "R" + point.generation, {fill:"var(--muted-foreground, #687386)", "font-size":10, "text-anchor":"middle"});
    }
  });
  text(valuesText, valid.map(point => "R" + point.generation + " " + point.value.toFixed(3)).join(" · "));
}

function setMode(nextMode) {
  mode = nextMode;
  sort = {key: nextMode === "training" ? "rank" : "_sort_rank", direction:1};
  document.getElementById("training-tab").setAttribute("aria-pressed", String(mode === "training"));
  document.getElementById("validation-tab").setAttribute("aria-pressed", String(mode === "validation"));
  renderRound();
}

document.getElementById("training-tab").addEventListener("click", () => setMode("training"));
document.getElementById("validation-tab").addEventListener("click", () => setMode("validation"));
roundSelect.addEventListener("change", () => {
  selectedIndex = Number(roundSelect.value) || 0;
  sort = {key: mode === "training" ? "rank" : "_sort_rank", direction:1};
  renderRound();
});
document.getElementById("leaderboard").querySelector("thead").addEventListener("click", event => {
  const button = event.target.closest("button[data-sort]");
  if (!button) return;
  const key = button.dataset.sort;
  sort = {key, direction: sort.key === key ? -sort.direction : 1};
  renderTable(roundNow());
});

setSummary();
fillRoundSelector();
renderRound();
renderTrend();
</script>
</body>
</html>
"""


def generate(run_dir: Path, output: Path, *, recent: int | None = None) -> dict[str, Any]:
    run_dir = run_dir.expanduser().resolve()
    if not run_dir.exists():
        raise ValueError(f"run directory does not exist: {run_dir}")
    if not run_dir.is_dir():
        raise ValueError(f"run path is not a directory: {run_dir}")
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    data = _report_data(run_dir, output.parent)
    if recent is not None:
        if recent < 1:
            raise ValueError("recent must be positive")
        if len(data["rounds"]) > recent:
            data["rounds"] = data["rounds"][-recent:]
            data["rounds_loaded"] = len(data["rounds"])
            data["warnings"].append(f"Showing the latest {recent} rounds; all source reports remain available in the run directory.")
    json_data = _script_json(data)
    fields_json = json.dumps(list(BOT_FIELDS), separators=(",", ":"))
    replacements = {"__REPORT_JSON__": json_data, "__BOT_FIELDS__": fields_json}
    page = re.sub(
        r"__REPORT_JSON__|__BOT_FIELDS__",
        lambda match: replacements[match.group(0)],
        HTML_TEMPLATE,
    )
    output.write_text(page, encoding="utf-8")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a dependency-free interactive HTML report for a pokerbot evolution run."
    )
    parser.add_argument("--run-dir", required=True, type=Path, help="directory containing round-NNNN.json and summary.json")
    parser.add_argument("--output", type=Path, help="output HTML path (default: playground.html within the run directory)")
    parser.add_argument("--recent", type=int, help="include only the latest N rounds in this HTML view")
    args = parser.parse_args(argv)
    run_dir = args.run_dir.expanduser().resolve()
    output = args.output if args.output is not None else run_dir / "playground.html"
    try:
        data = generate(run_dir, output, recent=args.recent)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(
        f"Wrote {output.expanduser().resolve()} "
        f"({data['rounds_loaded']} round reports; {len(data['bots'])} bot rows in latest round)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
