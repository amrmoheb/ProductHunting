import sqlite3
import tempfile
import unittest
from pathlib import Path

from amazon_scout.research_ingest import ingest
from amazon_scout.database import ScoutDatabase
from amazon_scout.research_pipeline import historical_changes


class ResearchIngestTests(unittest.TestCase):
    def test_persists_historical_evidence_and_derived_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "test.db"
            md, js, run_id = ingest("tests/fixtures/research_evidence.json", db)
            try:
                with sqlite3.connect(db) as connection:
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0], 6)
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM derived_metrics").fetchone()[0], 6)
                    self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            finally:
                md.unlink(missing_ok=True); js.unlink(missing_ok=True)

    def test_historical_observations_need_two_points(self):
        with tempfile.TemporaryDirectory() as directory:
            db = ScoutDatabase(Path(directory) / "history.db"); db.initialize()
            self.assertIsNone(historical_changes(db, "B0HISTORY1", None, "2026-08-12T00:00:00Z")["price_change_7d"])
            with db.connect() as connection:
                run_id = connection.execute("INSERT INTO research_runs(started_at,marketplace_id,mode,filters_json) VALUES(?,?,?,?)", ("2026-08-01T00:00:00Z","A2VIGQ35RCS4UG","research","{}")).lastrowid
                for i, (value, observed) in enumerate(((50,"2026-08-01T00:00:00Z"),(55,"2026-08-08T00:00:00Z"))):
                    connection.execute("INSERT INTO evidence_records(id,run_id,external_run_id,metric_name,metric_value_json,asin,marketplace,source_provider,source_type,observed_at,retrieved_at,confidence,is_estimate) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (f"hist-{i}",run_id,"history-run","current_price_aed",str(value),"B0HISTORY1","amazon.ae","codex_web","web_search",observed,observed,"MEDIUM",0))
            self.assertEqual(historical_changes(db, "B0HISTORY1", None, "2026-08-12T00:00:00Z")["price_change_7d"], 5)
