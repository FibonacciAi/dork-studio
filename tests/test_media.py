"""Provider regression tests: no credentials, no real network, temporary state only."""
import base64
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

_STATE = tempfile.TemporaryDirectory(prefix="dork-media-tests-")
_SOURCE = Path(__file__).resolve().parents[1] / "app" / "dashboard.py"
with patch.dict(os.environ, {"DORK_STATE_HOME": _STATE.name, "DORK_NO_ENV": "1"}, clear=True):
    spec = importlib.util.spec_from_file_location("dork_media_test_dashboard", _SOURCE)
    dashboard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dashboard)

# A synthetic one-pixel PNG. No private input media is used.
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l1sAAAAASUVORK5CYII="
URI = "data:image/png;base64," + PNG


class MediaTests(unittest.TestCase):
    def setUp(self):
        dashboard.app.config["TESTING"] = True
        self.client = dashboard.app.test_client()
        dashboard._VIDEO_JOB_RESULTS.clear()
        self.network = patch.object(dashboard.urllib.request, "urlopen", side_effect=AssertionError("Real network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.keys = patch.object(dashboard, "get_api_key", return_value="")
        self.keys.start()
        self.addCleanup(self.keys.stop)

    def post(self, path, body):
        return self.client.post(path, json=body)

    def test_video_estimate_rates_for_each_resolution(self):
        for model, rates in dashboard.VIDEO_RATES.items():
            for resolution, rate in rates.items():
                with self.subTest(model=model, resolution=resolution):
                    result = self.post("/api/media/estimate", {"kind": "video", "model": model, "resolution": resolution, "duration": 8, "input_images": 1})
                    self.assertEqual(result.status_code, 200)
                    data = result.get_json()
                    image_rate = 0.002 if model == "grok-imagine-video" else 0.01
                    self.assertAlmostEqual(data["estimate_usd"], 8 * rate + image_rate)
                    self.assertEqual(data["provider"], "xai")

    def test_image2_quality_and_edit_batch_input_estimates(self):
        for quality, expected in [("low", 0.06), ("medium", 0.08), ("auto", 0.08)]:
            result = self.post("/api/media/estimate", {"kind": "image", "quality": quality, "resolution": "2k", "n": 3, "input_images": 2, "operation": "edit"})
            self.assertEqual(result.status_code, 200)
            data = result.get_json()
            self.assertAlmostEqual(data["estimate_usd"], 3 * (expected + 0.02))
            self.assertTrue(data["input_cost_repeated_per_output"])
        generated = dashboard.estimate_media_cost({"kind": "image", "quality": "auto", "resolution": "1.5k"})
        self.assertEqual(generated["estimate_usd"], 0.05)
        self.assertEqual(generated["estimated_served_quality"], "low")

    def test_invalid_paid_parameters_never_submit(self):
        cases = [
            {"duration": 16}, {"duration": 0}, {"duration": 1.5}, {"duration": True},
            {"model": "xai/grok-imagine-video/v1.5/lite/text-to-video"},
            {"model": "grok-imagine-video", "resolution": "1080p"},
            {"generate_audio": "false"}, {"aspect_ratio": "5:2"},
        ]
        with patch.object(dashboard, "xai_request") as transport:
            for extra in cases:
                with self.subTest(extra=extra):
                    response = self.post("/api/video/generate", {"prompt": "synthetic test scene", **extra})
                    self.assertEqual(response.status_code, 400)
            transport.assert_not_called()

    def test_image_invalid_quality_never_submits(self):
        with patch.object(dashboard, "xai_request") as transport:
            response = self.post("/api/image/generate", {"prompt": "synthetic test scene", "quality": "high"})
            self.assertEqual(response.status_code, 400)
            response = self.post("/api/image/generate", {"prompt": "synthetic test scene", "n": 11})
            self.assertEqual(response.status_code, 400)
            transport.assert_not_called()

    def test_fast_image_to_video_payload_uses_xai_shape_and_preserves_framing(self):
        with patch.object(dashboard, "xai_request", return_value={"request_id": "job-123"}) as transport:
            response = self.post("/api/video/generate", {"prompt": "synthetic test scene", "model": "grok-imagine-video-1.5-lite", "image": URI, "aspect_ratio": "auto", "duration": 6, "resolution": "720p"})
            self.assertEqual(response.status_code, 200)
            endpoint, payload = transport.call_args.args
            self.assertEqual(endpoint, "videos/generations")
            self.assertEqual(payload["image"], {"url": URI})
            self.assertNotIn("aspect_ratio", payload)
            self.assertAlmostEqual(response.get_json()["estimate"]["estimate_usd"], 0.19)
            transport.assert_called_once()

    def test_text_to_video_aspect_and_audio(self):
        with patch.object(dashboard, "xai_request", return_value={"request_id": "job-456"}) as transport:
            response = self.post("/api/video/generate", {"prompt": "synthetic test scene", "aspect_ratio": "9:16", "generate_audio": False})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(transport.call_args.args[1]["aspect_ratio"], "9:16")
            self.assertIs(transport.call_args.args[1]["generate_audio"], False)

    def test_failed_paid_submission_has_no_retry(self):
        with patch.object(dashboard, "xai_request", side_effect=ValueError("422 rejected")) as transport:
            response = self.post("/api/video/generate", {"prompt": "synthetic test scene"})
            self.assertEqual(response.status_code, 502)
            transport.assert_called_once()
        with patch.object(dashboard, "xai_request", side_effect=ValueError("422 rejected")) as transport:
            response = self.post("/api/image/edit", {"prompt": "synthetic test scene", "image": PNG})
            self.assertEqual(response.status_code, 502)
            transport.assert_called_once()

    def test_image2_generation_forwards_quality(self):
        with patch.object(dashboard, "xai_request", return_value={"data": []}) as transport:
            with patch.object(dashboard, "_save_image_results", return_value=[]):
                response = self.post("/api/image/generate", {"prompt": "synthetic test scene", "quality": "medium", "resolution": "1.5k", "n": 2})
        self.assertEqual(response.status_code, 200)
        endpoint, payload = transport.call_args.args
        self.assertEqual(endpoint, "images/generations")
        self.assertEqual(payload["model"], "grok-imagine-image-2.0")
        self.assertEqual(payload["quality"], "medium")
        self.assertEqual(payload["resolution"], "1.5k")
        self.assertEqual(payload["n"], 2)
        self.assertAlmostEqual(response.get_json()["estimate"]["estimate_usd"], 0.14)

    def test_reference_generation_is_one_edit_without_vision_call(self):
        with patch.object(dashboard, "xai_request", return_value={"data": []}) as transport:
            with patch.object(dashboard, "_save_image_results", return_value=[]):
                response = self.post("/api/image/generate", {"prompt": "synthetic test scene", "reference": URI})
        self.assertEqual(response.status_code, 200)
        endpoint, payload = transport.call_args.args
        self.assertEqual(endpoint, "images/edits")
        self.assertEqual(payload["image"]["url"], URI)
        self.assertEqual(payload["quality"], "low")
        transport.assert_called_once()

    def test_multi_image_edit_and_legacy_quality_is_not_sent(self):
        with patch.object(dashboard, "xai_request", return_value={"data": []}) as transport:
            with patch.object(dashboard, "_save_image_results", return_value=[]):
                response = self.post("/api/image/edit", {"prompt": "synthetic test scene", "images": [PNG] * 5, "model": "grok-imagine-image-quality", "quality": "medium"})
        self.assertEqual(response.status_code, 200)
        payload = transport.call_args.args[1]
        self.assertEqual(len(payload["images"]), 5)
        self.assertNotIn("quality", payload)

    def test_video_pending_and_terminal_states(self):
        for state in ["pending", "failed", "expired", "cancelled"]:
            with self.subTest(state=state):
                with patch.object(dashboard, "xai_get", return_value={"status": state}):
                    response = self.client.get("/api/video/poll?id=test-job")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["status"], state)
                if state != "pending":
                    self.assertIn("error", response.get_json())

    def test_moderation_blocks_done_download(self):
        with patch.object(dashboard, "xai_get", return_value={"status": "done", "video": {"url": "https://vidgen.x.ai/test.mp4", "respect_moderation": False}}):
            response = self.client.get("/api/video/poll?id=test-moderation")
        self.assertEqual(response.get_json()["status"], "failed")
        self.assertIn("moderation", response.get_json()["error"])

    def test_completed_video_download_is_cached(self):
        result = {"status": "done", "video": {"url": "https://vidgen.x.ai/test.mp4", "respect_moderation": True}}
        with patch.object(dashboard, "xai_get", return_value=result) as get:
            with patch.object(dashboard.urllib.request, "urlopen", return_value=io.BytesIO(b"synthetic video")) as download:
                first = self.client.get("/api/video/poll?id=test-complete")
                second = self.client.get("/api/video/poll?id=test-complete")
        self.assertEqual(first.get_json(), second.get_json())
        self.assertEqual(first.get_json()["status"], "completed")
        self.assertTrue((dashboard.VIDEOS_DIR / first.get_json()["filename"]).is_file())
        get.assert_called_once()
        download.assert_called_once()

    def test_bad_json_and_poll_ids(self):
        self.assertEqual(self.post("/api/media/estimate", []).status_code, 400)
        self.assertEqual(self.post("/api/video/generate", []).status_code, 400)
        self.assertEqual(self.post("/api/image/generate", []).status_code, 400)
        self.assertEqual(self.client.get("/api/video/poll?id=../settings").status_code, 400)

    def test_capabilities_match_implemented_workflows(self):
        with patch.object(dashboard, "xai_get_optional", return_value=None):
            response = self.client.get("/api/models")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        cap = data["capabilities"]["video"]
        self.assertEqual(cap["fast_model"], "grok-imagine-video-1.5-lite")
        self.assertEqual(cap["pricing"]["grok-imagine-video-1.5"]["1080p"], 0.25)
        self.assertFalse(cap["supports_video_editing"])
        self.assertTrue(cap["supports_lastframe_continuation"])
        self.assertIn("grok-imagine-video", [model["id"] for model in data["video"]])
        self.assertEqual(data["capabilities"]["image"]["default_model"], "grok-imagine-image-2.0")


if __name__ == "__main__":
    unittest.main()
