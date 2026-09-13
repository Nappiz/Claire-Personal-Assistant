"""Regression tests for per-request temporal grounding."""

from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import patch

from schemas.chat_sch import MemoryContext
from services import llm_service


class TemporalAwarenessTests(TestCase):
    def test_jakarta_clock_is_derived_from_utc_instant(self):
        context = llm_service._current_temporal_context(
            datetime(2026, 9, 11, 2, 15, 30, tzinfo=timezone.utc),
            "Asia/Jakarta",
        )

        self.assertEqual("2026-09-11T09:15:30+07:00", context["local_datetime_iso"])
        self.assertEqual("Jumat", context["weekday"])
        self.assertEqual(2026, context["current_year"])
        self.assertEqual("Asia/Jakarta", context["timezone"])
        self.assertEqual("UTC+07:00", context["utc_offset"])

    def test_chat_system_prompt_receives_authoritative_current_time(self):
        clock = {
            "local_datetime_iso": "2026-09-11T09:15:30+07:00",
            "date_iso": "2026-09-11",
            "time_24h": "09:15:30",
            "weekday": "Jumat",
            "current_year": 2026,
            "timezone": "Asia/Jakarta",
            "timezone_abbreviation": "WIB",
            "utc_offset": "UTC+07:00",
        }
        with patch.object(llm_service, "_current_temporal_context", return_value=clock):
            messages = llm_service._build_chat_messages("Doomsday tayang 2026", MemoryContext())

        system_prompt = messages[0]["content"]
        self.assertIn("2026-09-11T09:15:30+07:00", system_prompt)
        self.assertIn("Tahun yang sama dengan current_year berarti tahun ini", system_prompt)
        self.assertEqual("Doomsday tayang 2026", messages[-1]["content"])

    def test_invalid_timezone_falls_back_to_utc(self):
        context = llm_service._current_temporal_context(
            datetime(2026, 9, 11, 2, 15, 30, tzinfo=timezone.utc),
            "Invalid/Timezone",
        )

        self.assertEqual("UTC", context["timezone"])
        self.assertEqual("UTC+00:00", context["utc_offset"])
