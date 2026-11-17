from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from mvp.app import make_pipeline
from mvp.db import Database
from mvp.llm_client import build_client_or_none
from mvp.parser import MockParser
from mvp.pipeline import Pipeline


FIXED_INPUT = "今天背完单词了，论文开头也改了，跟朋友聊完没那么焦虑了。"


class FlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.pipeline = Pipeline(Database(self.db_path), MockParser())

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _rows(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.pipeline.db.session() as conn:
            return conn.execute(sql, args).fetchall()

    def _create_fixed_turn(self) -> dict:
        return self.pipeline.run_turn(
            user_id="U-DEMO-001",
            source="h5",
            source_message_id="h5-msg-001",
            content=FIXED_INPUT,
        )

    def test_tc_001_first_input_creates_two_tasks(self) -> None:
        result = self._create_fixed_turn()
        self.assertEqual(result["code"], "OK")
        self.assertEqual(result["data"]["status"], "recorded")
        self.assertEqual(len(result["data"]["tasks"]), 2)
        self.assertEqual(
            {task["kind"] for task in result["data"]["tasks"]},
            {"daily_task", "task_progress"},
        )
        statuses = {
            task["kind"]: task["status"] for task in result["data"]["tasks"]
        }
        self.assertEqual(statuses["daily_task"], "done")
        self.assertEqual(statuses["task_progress"], "active")
        self.assertEqual(len(self._rows("SELECT * FROM raw_events")), 1)
        self.assertEqual(len(self._rows("SELECT * FROM tasks")), 2)
        event = self._rows("SELECT * FROM raw_events")[0]
        self.assertEqual(event["content"], FIXED_INPUT)
        self.assertEqual(event["parse_status"], "parsed")
        self.assertIsNotNone(event["response_payload_json"])

    def test_tc_002_duplicate_message_is_idempotent(self) -> None:
        first = self._create_fixed_turn()
        second = self._create_fixed_turn()
        self.assertTrue(second["data"]["duplicate"])
        self.assertEqual(len(self._rows("SELECT * FROM raw_events")), 1)
        self.assertEqual(len(self._rows("SELECT * FROM tasks")), 2)
        self.assertEqual(
            first["data"]["event_id"], second["data"]["event_id"]
        )

    def test_tc_003_parse_failure_keeps_raw_event(self) -> None:
        class BrokenParser:
            def parse(self, content: str, session_id: str | None = None) -> dict:
                raise RuntimeError("empty parse result")

        pipeline = Pipeline(Database(self.db_path), BrokenParser())
        result = pipeline.run_turn(
            user_id="U-DEMO-001",
            source="h5",
            source_message_id="h5-msg-failed",
            content=FIXED_INPUT,
        )
        self.assertEqual(result["code"], "PARSE_REJECTED")
        self.assertEqual(result["data"]["status"], "clarification_required")
        self.assertEqual(result["data"]["tasks"], [])
        self.assertEqual(result["data"]["clarification"], result["data"]["reply_text"])
        raw = self._rows("SELECT * FROM raw_events")
        self.assertEqual(len(raw), 1)
        self.assertEqual(raw[0]["content"], FIXED_INPUT)
        self.assertEqual(raw[0]["parse_status"], "failed")
        self.assertEqual(len(self._rows("SELECT * FROM tasks")), 0)

    def test_tc_004_correction_appends_event_and_updates_task(self) -> None:
        created = self._create_fixed_turn()
        task = next(
            task
            for task in created["data"]["tasks"]
            if task["kind"] == "task_progress"
        )
        corrected = self.pipeline.correct(
            user_id="U-DEMO-001",
            source="h5",
            source_message_id="h5-correction-001",
            target_record_id=task["record_id"],
            content="论文开头改成写到第二部分",
            changes={"content": "论文开头改成写到第二部分"},
        )
        self.assertEqual(corrected["data"]["status"], "corrected")
        raw = self._rows("SELECT * FROM raw_events ORDER BY created_at")
        self.assertEqual(len(raw), 2)
        self.assertEqual(raw[1]["event_type"], "correction")
        self.assertEqual(raw[1]["related_event_id"], created["data"]["event_id"])
        self.assertEqual(raw[1]["target_record_id"], task["record_id"])
        tasks = self._rows(
            "SELECT * FROM tasks WHERE record_id = ?", (task["record_id"],)
        )
        self.assertEqual(tasks[0]["content"], "论文开头改成写到第二部分")
        self.assertEqual(raw[0]["content"], FIXED_INPUT)

    def test_tc_005_task_query_is_user_scoped(self) -> None:
        self._create_fixed_turn()
        today = date.today().isoformat()
        self.assertEqual(
            len(self.pipeline.tasks(user_id="U-DEMO-001", date=today)),
            2,
        )
        self.assertEqual(
            self.pipeline.tasks(user_id="U-OTHER", date=today),
            [],
        )

    def test_schema_has_exactly_two_tables(self) -> None:
        rows = self._rows(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        self.assertEqual({row["name"] for row in rows}, {"raw_events", "tasks"})

    def test_coach_failure_does_not_block_record(self) -> None:
        class BrokenCoach:
            def advise(self, *, user_id: str, context: dict) -> str | None:
                raise RuntimeError("coach timeout")

        pipeline = Pipeline(Database(self.db_path), MockParser(), coach=BrokenCoach())
        result = pipeline.run_turn(
            user_id="U-DEMO-001",
            source="h5",
            source_message_id="h5-coach-failure",
            content=FIXED_INPUT,
        )
        self.assertEqual(result["data"]["status"], "recorded")
        self.assertIsNone(result["data"]["coach_text"])
        self.assertEqual(len(result["data"]["tasks"]), 2)

    def test_mock_mode_wins_even_if_api_key_is_present(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_MODE": "mock",
                "OPENCODE_API_KEY": "intentionally-not-a-real-key",
            },
            clear=False,
        ):
            self.assertIsNone(build_client_or_none())

    def test_server_pipeline_keeps_existing_database_by_default(self) -> None:
        self._create_fixed_turn()
        with patch.dict(os.environ, {"LLM_MODE": "mock"}, clear=False):
            reopened = make_pipeline(self.db_path)
        self.assertEqual(
            len(
                reopened.tasks(
                    user_id="U-DEMO-001", date=date.today().isoformat()
                )
            ),
            2,
        )


if __name__ == "__main__":
    unittest.main()

