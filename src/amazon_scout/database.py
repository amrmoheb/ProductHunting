from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS research_runs (id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT, marketplace_id TEXT NOT NULL CHECK(marketplace_id='A2VIGQ35RCS4UG'), mode TEXT NOT NULL, filters_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS search_queries (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES research_runs(id), query TEXT NOT NULL, number_of_results INTEGER, observed_at TEXT NOT NULL, raw_path TEXT);
CREATE TABLE IF NOT EXISTS products (asin TEXT PRIMARY KEY, title TEXT NOT NULL, brand TEXT, product_type TEXT, first_seen_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS product_observations (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES research_runs(id), asin TEXT NOT NULL REFERENCES products(asin), marketplace_id TEXT NOT NULL, source TEXT NOT NULL, observation_kind TEXT NOT NULL, payload_json TEXT NOT NULL, observed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS prices (id INTEGER PRIMARY KEY, asin TEXT NOT NULL REFERENCES products(asin), marketplace_id TEXT NOT NULL, price REAL, currency TEXT NOT NULL CHECK(currency='AED'), price_type TEXT NOT NULL, source TEXT NOT NULL, observed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sales_ranks (id INTEGER PRIMARY KEY, asin TEXT NOT NULL REFERENCES products(asin), marketplace_id TEXT NOT NULL, rank INTEGER, classification TEXT, source TEXT NOT NULL, observed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS offers (id INTEGER PRIMARY KEY, asin TEXT NOT NULL REFERENCES products(asin), marketplace_id TEXT NOT NULL, offer_count INTEGER, featured_price REAL, lowest_price REAL, amazon_retail_present INTEGER, source TEXT NOT NULL, observed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fee_estimates (id INTEGER PRIMARY KEY, asin TEXT NOT NULL REFERENCES products(asin), marketplace_id TEXT NOT NULL, selling_price REAL NOT NULL, referral_fee REAL, fulfillment_fees REAL, other_fees REAL, total_fees REAL, currency TEXT NOT NULL CHECK(currency='AED'), source TEXT NOT NULL, observed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS niche_metrics (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES research_runs(id), niche TEXT NOT NULL, metrics_json TEXT NOT NULL, observed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS opportunity_scores (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES research_runs(id), niche TEXT NOT NULL, score REAL NOT NULL, confidence_score REAL NOT NULL, factors_json TEXT NOT NULL, scoring_version TEXT NOT NULL, calculated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES research_runs(id), markdown_path TEXT NOT NULL, json_path TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evidence_records (id TEXT PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES research_runs(id), external_run_id TEXT NOT NULL, metric_name TEXT NOT NULL, metric_value_json TEXT, metric_unit TEXT, asin TEXT, keyword TEXT, niche TEXT, marketplace TEXT NOT NULL CHECK(marketplace IN ('amazon.ae','A2VIGQ35RCS4UG')), source_provider TEXT NOT NULL, source_type TEXT NOT NULL, source_url TEXT, source_title TEXT, observed_at TEXT NOT NULL, retrieved_at TEXT NOT NULL, confidence TEXT NOT NULL, is_estimate INTEGER NOT NULL, notes TEXT, UNIQUE(external_run_id,id));
CREATE TABLE IF NOT EXISTS derived_metrics (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES research_runs(id), niche TEXT, asin TEXT, metric_name TEXT NOT NULL, metric_value_json TEXT, metric_unit TEXT, evidence_ids_json TEXT NOT NULL, calculated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_run_evidence (run_id INTEGER NOT NULL REFERENCES research_runs(id), evidence_id TEXT NOT NULL REFERENCES evidence_records(id), PRIMARY KEY(run_id,evidence_id));
CREATE TABLE IF NOT EXISTS research_candidates (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES research_runs(id), niche TEXT NOT NULL, candidate_type TEXT NOT NULL, observed_market_price_aed REAL, observed_price_min_aed REAL, observed_price_max_aed REAL, proposed_selling_price_aed REAL, bundle_hypothesis_price_aed REAL, fee_calculation_price_aed REAL, preliminary_score REAL, validated_score REAL, data_confidence_score REAL NOT NULL, recommendation_tier TEXT NOT NULL, gates_json TEXT NOT NULL, components_json TEXT NOT NULL, freshness TEXT NOT NULL, calculated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS serpapi_usage (run_id INTEGER PRIMARY KEY REFERENCES research_runs(id), configured INTEGER NOT NULL, enabled INTEGER NOT NULL, configured_max_calls INTEGER NOT NULL, calls_attempted INTEGER NOT NULL, calls_succeeded INTEGER NOT NULL, calls_failed INTEGER NOT NULL, calls_saved_by_cache INTEGER NOT NULL, calls_remaining INTEGER NOT NULL, estimated_cost_usd REAL, keywords_json TEXT NOT NULL, asins_json TEXT NOT NULL, purposes_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS provider_errors (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES research_runs(id), provider TEXT NOT NULL, purpose TEXT, error_type TEXT NOT NULL, message TEXT NOT NULL, occurred_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS serpapi_cache_metadata (request_fingerprint TEXT PRIMARY KEY, engine TEXT NOT NULL, amazon_domain TEXT NOT NULL CHECK(amazon_domain='amazon.ae'), keyword TEXT, asin TEXT, retrieved_at TEXT NOT NULL, cache_path TEXT NOT NULL, normalized_evidence_ids_json TEXT NOT NULL DEFAULT '[]');
CREATE INDEX IF NOT EXISTS idx_observations_asin_time ON product_observations(asin, observed_at);
CREATE INDEX IF NOT EXISTS idx_prices_asin_time ON prices(asin, observed_at);
CREATE INDEX IF NOT EXISTS idx_ranks_asin_time ON sales_ranks(asin, observed_at);
CREATE INDEX IF NOT EXISTS idx_evidence_metric_time ON evidence_records(metric_name, niche, asin, observed_at);
CREATE INDEX IF NOT EXISTS idx_evidence_asin_time ON evidence_records(asin, observed_at);
"""


class ScoutDatabase:
    def __init__(self, path: str | Path = "data/scout.db") -> None:
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate(connection)

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        """Add nullable V1.1/V1.2 fields without rebuilding or deleting history."""
        additions = {
            "research_runs": {"generated_at": "TEXT", "evidence_cutoff": "TEXT", "candidate_funnel_json": "TEXT"},
            "evidence_records": {"market_relevance": "TEXT", "source_timezone": "TEXT", "evidence_freshness": "TEXT"},
            "fee_estimates": {"fee_calculation_price_aed": "REAL", "category_assumption": "TEXT", "known_components_json": "TEXT", "unknown_components_json": "TEXT"},
            "opportunity_scores": {"preliminary_score": "REAL", "validated_score": "REAL", "recommendation_tier": "TEXT"},
        }
        for table, columns in additions.items():
            existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            for name, sql_type in columns.items():
                if name not in existing:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")

    def start_run(self, started_at: str, mode: str, filters: dict | None = None) -> int:
        with self.connect() as connection:
            cursor = connection.execute("INSERT INTO research_runs(started_at, marketplace_id, mode, filters_json) VALUES(?,?,?,?)", (started_at, "A2VIGQ35RCS4UG", mode, json.dumps(filters or {})))
            return int(cursor.lastrowid)
