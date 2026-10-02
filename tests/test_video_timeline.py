"""Real ffmpeg checks with synthetic media, isolated state, and no provider I/O."""
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

_STATE = tempfile.TemporaryDirectory(prefix="dork-timeline-tests-")
_SOURCE = Path(__file__).resolve().parents[1] / "app/dashboard.py"
with patch.dict(os.environ, {"DORK_STATE_HOME": _STATE.name, "DORK_NO_ENV": "1"}, clear=True):
    spec = importlib.util.spec_from_file_location("dork_timeline_dashboard", _SOURCE)
    dashboard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dashboard)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg and ffprobe are required")
class VideoTimelineTests(unittest.TestCase):
    def setUp(self):
        self.client = dashboard.app.test_client()
        self.network = patch.object(dashboard.urllib.request, "urlopen", side_effect=AssertionError("No network allowed"))
        self.network.start(); self.addCleanup(self.network.stop)

    def clip(self, name, fps=24, frames=8, size=(192, 108), start=16, audio=False, offset=0):
        width, height = size
        pixels = []
        for frame in range(frames):
            image = Image.new("RGB", size)
            x = start + frame * 2
            for column in range(x, min(x + 4, width)):
                for row in range(height): image.putpixel((column, row), (255, 255, 255))
            pixels.append(image.tobytes())
        path = dashboard.VIDEOS_DIR / name
        command = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                   "-s", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0"]
        if audio:
            command += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={frames/fps}"]
        command += ["-c:v", "libx264", "-crf", "0", "-pix_fmt", "yuv420p"]
        if audio: command += ["-c:a", "aac"]
        if offset: command += ["-output_ts_offset", str(offset)]
        command += [str(path)]
        subprocess.run(command, input=b"".join(pixels), capture_output=True, check=True, timeout=30)
        return path

    def probe(self, path):
        result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                                 "-show_frames", "-of", "json", str(path)], capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def decoded(self, path):
        metadata = self.probe(path)
        video = next(s for s in metadata["streams"] if s["codec_type"] == "video")
        width, height = video["width"], video["height"]
        result = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0",
                                 "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"], capture_output=True, check=True)
        stride = width * height * 3
        return [result.stdout[i:i+stride] for i in range(0, len(result.stdout), stride)], width, height

    def stitch(self, paths):
        response = self.client.post("/api/video/stitch", json={"videos": [p.name for p in paths]})
        self.assertEqual(response.status_code, 200, response.get_json())
        return dashboard.VIDEOS_DIR / response.get_json()["filename"], response.get_json()

    def test_last_frame_matches_actual_final_decoded_pixels(self):
        path = self.clip("last-frame.mp4", fps=30, frames=9)
        frames, width, height = self.decoded(path)
        response = self.client.post("/api/video/lastframe", json={"filename": path.name})
        self.assertEqual(response.status_code, 200, response.get_json())
        result = response.get_json()
        extracted = Image.open(io.BytesIO(base64.b64decode(result["base64"]))).convert("RGB")
        self.assertEqual(result["decoded_frame_index"], 8)
        self.assertEqual(extracted.tobytes(), frames[-1])
        self.assertNotEqual(extracted.tobytes(), frames[-3])

    def test_same_rate_motion_has_no_extra_duplicate_or_skipped_boundary_frame(self):
        first = self.clip("motion-a.mp4", frames=8, start=16, audio=True)
        second = self.clip("motion-b.mp4", frames=8, start=32)
        joined, receipt = self.stitch([first, second])
        frames, width, height = self.decoded(joined)
        self.assertEqual(len(frames), 16); self.assertEqual(receipt["frames"], 16)
        centers = []
        for raw in frames[6:10]:
            image = Image.frombytes("RGB", (width, height), raw)
            columns = [x for x in range(width) if image.getpixel((x, height//2))[0] > 127]
            centers.append(sum(columns)/len(columns))
        self.assertEqual(centers, [29.5, 31.5, 33.5, 35.5])
        metadata = self.probe(joined)
        timestamps = [float(f["best_effort_timestamp_time"]) for f in metadata["frames"] if f["media_type"] == "video"]
        for a, b in zip(timestamps, timestamps[1:]): self.assertAlmostEqual(b-a, 1/24, places=5)
        audio = next(s for s in metadata["streams"] if s["codec_type"] == "audio")
        self.assertEqual(audio["sample_rate"], "48000"); self.assertEqual(audio["channels"], 2)
        self.assertLess(abs(float(audio["duration"])-16/24), .025)

    def test_mixed_rate_size_offset_and_missing_audio_normalize_to_one_timeline(self):
        first = self.clip("mixed-a.mp4", frames=24, fps=24, audio=True, offset=2)
        second = self.clip("mixed-b.mp4", frames=30, fps=30, size=(128, 72), offset=4)
        joined, receipt = self.stitch([first, second])
        metadata = self.probe(joined)
        video = next(s for s in metadata["streams"] if s["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"]), (192, 108))
        self.assertEqual(video["avg_frame_rate"], "24/1"); self.assertEqual(int(video["nb_frames"]), 48)
        self.assertAlmostEqual(float(video["duration"]), 2, places=5)
        timestamps = [float(f["best_effort_timestamp_time"]) for f in metadata["frames"] if f["media_type"] == "video"]
        self.assertEqual(timestamps[0], 0)
        for a,b in zip(timestamps,timestamps[1:]): self.assertAlmostEqual(b-a, 1/24, places=5)
        audio = next(s for s in metadata["streams"] if s["codec_type"] == "audio")
        self.assertAlmostEqual(float(audio["duration"]), 2, places=2)
        self.assertEqual(receipt["transition"], "normalized cut")
        pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(joined), "-map", "0:a:0",
                              "-ac", "1", "-f", "f32le", "pipe:1"], capture_output=True, check=True).stdout
        samples = struct.unpack(f"<{len(pcm)//4}f", pcm)
        def rms(start, end):
            values = samples[round(start*48000):round(end*48000)]
            return (sum(v*v for v in values)/len(values))**.5
        self.assertGreater(rms(.1, .7), .03, "Timestamp reset must retain the actual first-clip audio")
        self.assertLess(rms(1.2, 1.8), .001, "The clip without audio must receive aligned silence")

    def test_invalid_list_and_paths_are_rejected_before_processing(self):
        for videos in ["bad", ["one.mp4"], ["../escape.mp4", "other.mp4"], [12, "other.mp4"]]:
            self.assertEqual(self.client.post("/api/video/stitch", json={"videos": videos}).status_code, 400)


if __name__ == "__main__": unittest.main()
