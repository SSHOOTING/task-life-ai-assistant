from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from mvp.db import Database
from mvp.parser import MockParser
from mvp.pipeline import Pipeline


USER_ID = "U-DEMO-001"
SOURCE = "h5"
SOURCE_MESSAGE_ID = "h5-msg-001"
FIXED_INPUT = "今天背完单词了，论文开头也改了，跟朋友聊完没那么焦虑了。"
EXPECTED_RECEIPT = (
    "已记下：每日任务：背单词；任务进展：毕业论文。原话已按原文保存。"
)


class TC001FixedInputAcceptanceTest(unittest.TestCase):
    """Independent acceptance evidence for the only frozen case, TC-001."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "acceptance.db"
        self.pipeline = Pipeline(Database(self.db_path), MockParser())

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _rows(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.pipeline.db.session() as conn:
            return conn.execute(sql, args).fetchall()

    def test_tc001_fixed_input_acceptance(self) -> None:
        result = self.pipeline.run_turn(
            user_id=USER_ID,
            source=SOURCE,
            source_message_id=SOURCE_MESSAGE_ID,
            content=FIXED_INPUT,
        )

        self.assertEqual(result["code"], "OK")
        data = result["data"]
        self.assertEqual(data["status"], "recorded")
        self.assertIsNone(data["clarification"])
        self.assertIsNone(data["coach_text"])
        self.assertEqual(data["reply_text"], EXPECTED_RECEIPT)

        tasks = data["tasks"]
        self.assertEqual(len(tasks), 2)
        tasks_by_kind = {task["kind"]: task for task in tasks}
        self.assertEqual(set(tasks_by_kind), {"daily_task", "task_progress"})

        daily_task = tasks_by_kind["daily_task"]
        self.assertEqual(daily_task["title"], "背单词")
        self.assertEqual(daily_task["status"], "done")
        self.assertEqual(daily_task["occurred_on"], date.today().isoformat())

        progress = tasks_by_kind["task_progress"]
        self.assertEqual(progress["title"], "毕业论文")
        self.assertEqual(progress["status"], "active")
        self.assertEqual(progress["occurred_on"], date.today().isoformat())

        event_id = data["event_id"]
        self.assertTrue(event_id)
        self.assertTrue(
            all(task["source_event_id"] == event_id for task in tasks)
        )

        event_rows = self._rows("SELECT * FROM raw_events")
        self.assertEqual(len(event_rows), 1)
        event = event_rows[0]
        self.assertEqual(event["event_id"], event_id)
        self.assertEqual(event["user_id"], USER_ID)
        self.assertEqual(event["source"], SOURCE)
        self.assertEqual(event["source_message_id"], SOURCE_MESSAGE_ID)
        self.assertEqual(event["event_type"], "utterance")
        self.assertEqual(event["content"], FIXED_INPUT)
        self.assertEqual(event["parse_status"], "parsed")
        self.assertIsNotNone(event["parse_result_json"])
        self.assertIsNotNone(event["response_payload_json"])

        task_rows = self._rows("SELECT * FROM tasks")
        self.assertEqual(len(task_rows), 2)
        self.assertTrue(
            all(row["source_event_id"] == event_id for row in task_rows)
        )
        self.assertEqual(
            {row["kind"] for row in task_rows},
            {"daily_task", "task_progress"},
        )
        self.assertFalse(any(row["kind"] == "reflection" for row in task_rows))
        self.assertFalse(
            any("焦虑" in (row["content"] or "") for row in task_rows)
        )

        cached = json.loads(event["response_payload_json"])
        self.assertEqual(cached["code"], "OK")
        self.assertEqual(cached["data"]["event_id"], event_id)
        self.assertEqual(cached["data"]["reply_text"], EXPECTED_RECEIPT)


if __name__ == "__main__":
    unittest.main()
