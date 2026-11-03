from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from media import Cancelled, MediaError, audio_streams, export, inspect, process_options, tool


class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        cls.source = cls.folder / "episode 日本語.mkv"
        (cls.folder / "subtitle.srt").write_text("1\n00:00:00,000 --> 00:00:00,900\nHello\n", encoding="utf-8")
        (cls.folder / "attachment.txt").write_text("An attachment", encoding="utf-8")
        (cls.folder / "chapters.txt").write_text(
            ";FFMETADATA1\ntitle=Test movie\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=1000\ntitle=Intro\n", encoding="utf-8")
        command = [tool("ffmpeg"), "-v", "error", "-y",
                   "-f", "lavfi", "-i", "color=size=64x64:rate=10:duration=1",
                   "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                   "-f", "lavfi", "-i", "sine=frequency=880:duration=1",
                   "-i", str(cls.folder / "subtitle.srt"),
                   "-f", "ffmetadata", "-i", str(cls.folder / "chapters.txt"),
                   "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:s",
                   "-map_metadata", "4", "-map_chapters", "4",
                   "-c:v", "ffv1", "-c:a", "pcm_s16le", "-c:s", "srt",
                   "-metadata:s:a:0", "language=jpn", "-metadata:s:a:0", "title=Japanese",
                   "-metadata:s:a:1", "language=eng", "-metadata:s:a:1", "title=English",
                   "-disposition:a:0", "default", "-disposition:a:1", "0",
                   "-attach", str(cls.folder / "attachment.txt"),
                   "-metadata:s:t:0", "mimetype=text/plain", str(cls.source)]
        subprocess.run(command, check=True, capture_output=True, **process_options())
        cls.info = inspect(cls.source)
        cls.original = cls.source.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def save(self, removed, default=None, cancel=None, overwrite=False):
        return export(self.source, self.info, removed, default,
                      cancel or threading.Event(), lambda _value: None, overwrite=overwrite)

    def test_remove_preserves_other_streams_and_source(self):
        first, second = audio_streams(self.info)
        output = self.save({first["index"]}, second["index"])
        result = inspect(output)
        audio = audio_streams(result)
        self.assertEqual(len(audio), 1)
        self.assertEqual(audio[0]["tags"]["language"], "eng")
        self.assertEqual(audio[0]["tags"]["title"], "English")
        self.assertEqual(audio[0]["disposition"]["default"], 1)
        self.assertEqual([s["codec_type"] for s in result["streams"]],
                         ["video", "audio", "subtitle", "attachment"])
        self.assertEqual(result["format"]["tags"]["title"], "Test movie")
        self.assertEqual(result["chapters"][0]["tags"]["title"], "Intro")
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(output.parent, self.source.parent)
        self.assertTrue(output.stem.startswith(self.source.stem + "-clear"))
        # Compare encoded packet hashes, proving kept streams were copied.
        def packets(path, selector):
            run = subprocess.run([tool("ffprobe"), "-v", "error", "-select_streams", selector,
                                  "-show_packets", "-show_data_hash", "sha256", "-show_entries",
                                  "packet=data_hash", "-of", "csv=p=0", str(path)],
                                 check=True, capture_output=True, **process_options())
            return run.stdout
        for source_stream, output_stream in [("v:0", "v:0"), ("a:1", "a:0"), ("s:0", "s:0")]:
            self.assertEqual(packets(self.source, source_stream), packets(output, output_stream))

    def test_change_default_without_removal(self):
        output = self.save(set(), audio_streams(self.info)[1]["index"])
        audio = audio_streams(inspect(output))
        self.assertEqual([s["disposition"]["default"] for s in audio], [0, 1])

    def test_remove_default_does_not_assign_another(self):
        output = self.save({audio_streams(self.info)[0]["index"]})
        self.assertEqual(audio_streams(inspect(output))[0]["disposition"]["default"], 0)

    def test_remove_all_audio(self):
        output = self.save({s["index"] for s in audio_streams(self.info)})
        self.assertEqual(audio_streams(inspect(output)), [])

    def test_collision_does_not_overwrite(self):
        removed = {audio_streams(self.info)[1]["index"]}
        first = self.save(removed)
        content = first.read_bytes()
        second = self.save(removed)
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), content)

    def test_cancel_before_start(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(Cancelled):
            self.save({audio_streams(self.info)[0]["index"]}, cancel=event, overwrite=True)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_cancel_during_export_cleans_temporary_file(self):
        event = threading.Event()
        before = set(self.folder.glob("*.mkv"))
        original_popen = subprocess.Popen

        def start_and_cancel(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            event.set()
            return process

        with patch("media.subprocess.Popen", side_effect=start_and_cancel):
            with self.assertRaises(Cancelled):
                self.save({audio_streams(self.info)[0]["index"]}, cancel=event, overwrite=True)
        self.assertEqual(set(self.folder.glob("*.mkv")), before)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_failed_export_cleans_temporary_file(self):
        broken = self.folder / "broken.mkv"
        broken.write_bytes(b"not an MKV")
        before = set(self.folder.glob("*.mkv"))
        with self.assertRaises(MediaError):
            export(broken, self.info, {audio_streams(self.info)[0]["index"]}, None,
                   threading.Event(), lambda _value: None)
        self.assertEqual(set(self.folder.glob("*.mkv")), before)
        self.assertEqual(broken.read_bytes(), b"not an MKV")

    def test_default_overwrites_source_after_verification(self):
        source = self.folder / "overwrite.mkv"
        source.write_bytes(self.original)
        output = export(source, self.info, {audio_streams(self.info)[0]["index"]}, None,
                        threading.Event(), lambda _value: None)
        self.assertEqual(output, source)
        self.assertEqual(len(audio_streams(inspect(source))), 1)
        self.assertNotEqual(source.read_bytes(), self.original)
        self.assertFalse(list(self.folder.glob(".processing-*.mkv")))

    def test_replacement_failure_keeps_original(self):
        source = self.folder / "locked.mkv"
        source.write_bytes(self.original)
        with patch("media.os.replace", side_effect=PermissionError("File is in use")):
            with self.assertRaises(PermissionError):
                export(source, self.info, {audio_streams(self.info)[0]["index"]}, None,
                       threading.Event(), lambda _value: None)
        self.assertEqual(source.read_bytes(), self.original)
        self.assertFalse(list(self.folder.glob(".processing-*.mkv")))

    def test_verification_failure_keeps_original(self):
        with patch("media.inspect", return_value={"streams": []}):
            with self.assertRaises(MediaError):
                self.save({audio_streams(self.info)[0]["index"]}, overwrite=True)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse(list(self.folder.glob(".processing-*.mkv")))

    def test_invalid_selection(self):
        with self.assertRaises(MediaError):
            self.save({0})  # video is never removable through the audio API
        with self.assertRaises(MediaError):
            first = audio_streams(self.info)[0]["index"]
            self.save({first}, first)
        with self.assertRaises(MediaError):
            self.save(set())


if __name__ == "__main__":
    unittest.main()
