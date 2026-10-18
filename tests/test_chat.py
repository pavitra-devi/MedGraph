import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.chat import (
    answer_with_gemini,
    deterministic_answer,
    find_patient_id,
    relevant_history,
)


class ChatParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.patient = {
            "patient_id": "123",
            "name": "Test Patient",
            "visits": [
                {
                    "visit_date": "2026-10-18",
                    "condition": "Headache",
                    "notes": "Follow-up",
                    "medicines": [{"name": "Medicine A", "dosage": "10 mg"}],
                },
                {
                    "visit_date": "2026-10-01",
                    "condition": "Fever",
                    "notes": None,
                    "medicines": [{"name": "Medicine B", "dosage": None}],
                },
            ],
            "reports": [
                {
                    "title": "Brain MRI",
                    "report_type": "MRI",
                    "uploaded_at": "2026-10-18",
                    "content": "No acute findings.",
                },
                {
                    "title": "CBC",
                    "report_type": "Blood test",
                    "uploaded_at": "2026-10-01",
                    "content": "Within range.",
                },
            ],
        }

    def test_extracts_patient_id_from_example_query(self) -> None:
        self.assertEqual(find_patient_id("Show last visit for Patient 123."), "123")
        self.assertEqual(find_patient_id("Patient ID: A-123?"), "A-123")
        self.assertIsNone(find_patient_id("Show recent history"))

    def test_limits_last_visits_and_filters_reports(self) -> None:
        context = relevant_history(
            "What medicines were prescribed in the last 1 visit? Show MRI report",
            self.patient,
        )
        self.assertEqual(len(context["visits"]), 1)
        self.assertEqual([report["report_type"] for report in context["reports"]], ["MRI"])

    def test_deterministic_answer_includes_visit_and_medicine(self) -> None:
        context = relevant_history("Show last visit for Patient 123", self.patient)
        answer = deterministic_answer("Show last visit for Patient 123", context)
        self.assertIn("2026-10-18", answer)
        self.assertIn("Medicine A (10 mg)", answer)

    @patch("app.chat.genai.Client")
    def test_gemini_uses_google_sdk_generate_content(self, client_class) -> None:
        client = client_class.return_value
        client.models.generate_content.return_value.text = "The latest visit was for headache."
        context = relevant_history("Show last visit for Patient 123", self.patient)

        with patch(
            "app.chat.settings",
            SimpleNamespace(gemini_api_key="test-key", gemini_model="gemini-3.5-flash"),
        ):
            answer = answer_with_gemini("Show last visit for Patient 123", context)

        self.assertEqual(answer, "The latest visit was for headache.")
        client_class.assert_called_once_with(api_key="test-key")
        self.assertEqual(
            client.models.generate_content.call_args.kwargs["model"],
            "gemini-3.5-flash",
        )


if __name__ == "__main__":
    unittest.main()
