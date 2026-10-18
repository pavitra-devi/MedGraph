import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.main import app


class ReportUploadTests(unittest.TestCase):
    def test_image_only_pdf_is_saved_unchanged_and_downloadable(self) -> None:
        output = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(output)
        pdf_bytes = output.getvalue()

        with tempfile.TemporaryDirectory() as storage_directory:
            saved_report: dict[str, str] = {}

            def create_report(
                patient_id: str,
                visit_id: str,
                title: str,
                report_type: str,
                content: str,
                uploaded_at: str,
                attachment_id: str,
                original_filename: str,
            ) -> dict[str, str]:
                self.assertEqual(content, "")
                saved_report.update(
                    attachment_id=attachment_id,
                    original_filename=original_filename,
                )
                return {
                    "report_id": "report-1",
                    "visit_id": visit_id,
                    "download_url": "/report/report-1/file",
                }

            storage_settings = SimpleNamespace(
                report_storage_dir=Path(storage_directory)
            )
            with (
                patch("app.main.repository.initialize_graph"),
                patch("app.main.repository.create_report", side_effect=create_report),
                patch(
                    "app.main.repository.fetch_report_attachment",
                    side_effect=lambda _: saved_report,
                ),
                patch("app.report_storage.settings", storage_settings),
                TestClient(app) as client,
            ):
                response = client.post(
                    "/report",
                    data={
                        "patient_id": "patient-1",
                        "visit_id": "visit-1",
                        "title": "Chest X-ray",
                        "report_type": "X-ray",
                    },
                    files={
                        "file": (
                            "chest-xray.pdf",
                            pdf_bytes,
                            "application/pdf",
                        )
                    },
                )
                self.assertEqual(response.status_code, 201, response.text)

                attachment_path = (
                    Path(storage_directory)
                    / f"{saved_report['attachment_id']}.pdf"
                )
                self.assertEqual(attachment_path.read_bytes(), pdf_bytes)

                download = client.get("/report/report-1/file")
                self.assertEqual(download.status_code, 200, download.text)
                self.assertEqual(download.content, pdf_bytes)

    def test_report_content_is_never_sent_to_gemini(self) -> None:
        patient_record = {
            "patient_id": "patient-1",
            "name": "Test Patient",
            "visits": [
                {
                    "visit_id": "visit-1",
                    "visit_date": "2026-10-18",
                    "condition": "Cough",
                    "notes": "Follow-up",
                    "medicines": [],
                }
            ],
            "reports": [
                {
                    "report_id": "report-1",
                    "title": "Chest X-ray",
                    "report_type": "X-ray",
                    "uploaded_at": "2026-10-18",
                    "content": "Private report text",
                }
            ],
        }

        def answer_with_gemini(message: str, context: dict[str, object]) -> str:
            self.assertNotIn("reports", context)
            self.assertNotIn("Private report text", str(context))
            return "The patient was seen for a cough."

        model_settings = SimpleNamespace(
            gemini_api_key="test-key",
            gemini_model="gemini-test",
        )
        with (
            patch("app.main.repository.initialize_graph"),
            patch("app.main.repository.fetch_patient", return_value=patient_record),
            patch("app.main.answer_with_gemini", side_effect=answer_with_gemini) as gemini,
            patch("app.main.settings", model_settings),
            TestClient(app) as client,
        ):
            history_response = client.post(
                "/chat",
                json={"message": "Summarize the last visit for Patient patient-1"},
            )
            self.assertEqual(history_response.status_code, 200, history_response.text)
            gemini.assert_called_once()

            gemini.reset_mock()
            report_response = client.post(
                "/chat",
                json={"message": "Show the X-ray report for Patient patient-1"},
            )
            self.assertEqual(report_response.status_code, 200, report_response.text)
            self.assertIn("Private report text", report_response.json()["answer"])
            gemini.assert_not_called()


if __name__ == "__main__":
    unittest.main()
