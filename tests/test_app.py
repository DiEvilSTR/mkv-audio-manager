from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from app import App
from media import audio_streams, inspect, process_options, tool


class AppWorkflowTests(unittest.TestCase):
    def test_compact_layout_keeps_actions_visible(self):
        build = App._build
        for scaling in (1.333, 2.0):
            def scaled_build(app):
                app.tk.call("tk", "scaling", scaling)
                build(app)

            with patch.object(App, "_build", scaled_build):
                app = App()
            app.attributes("-topmost", True)
            try:
                app.folder_text.set("C:/" + "A long folder name/" * 25)
                app.summary.set("A very long episode filename " * 20)
                app.status.set("Saved: " + "A long output filename " * 20)
                app.default.set("Track 2 · English · " + "A long track title " * 20)
                for size in ("940x540", "820x460"):
                    with self.subTest(scaling=scaling, size=size):
                        app.geometry(size + "+40+40")
                        app.update()
                        for widget in (app.save_button, app.cancel_button, app.output_button,
                                       app.default_box, app.filter_entry, app.progress, app.overwrite_box):
                            self.assertTrue(widget.winfo_viewable(), str(widget))
                            self.assertGreaterEqual(widget.winfo_x(), 0)
                            self.assertGreaterEqual(widget.winfo_rootx(), app.winfo_rootx())
                            self.assertGreaterEqual(widget.winfo_rooty(), app.winfo_rooty())
                            self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                                 app.winfo_rootx() + app.winfo_width())
                            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                                 app.winfo_rooty() + app.winfo_height())
                            self.assertEqual(app.winfo_containing(
                                widget.winfo_rootx() + widget.winfo_width() // 2,
                                widget.winfo_rooty() + widget.winfo_height() // 2), widget)
                        for button in (app.save_button, app.cancel_button, app.output_button):
                            self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth())
                            self.assertGreaterEqual(button.winfo_height(), button.winfo_reqheight())
                        self.assertGreater(app.tracks.winfo_height(), 80)
                        self.assertGreater(app.file_tree.winfo_height(), 80)
            finally:
                app.destroy()

    def test_file_and_audio_rows_are_visible_and_clickable(self):
        app = App()
        app.geometry("940x540+40+40")
        app.attributes("-topmost", True)
        try:
            for tree in (app.file_tree, app.tracks):
                tree.insert("", "end", iid="example", values=("example.mkv",))
            app.update()
            for tree in (app.file_tree, app.tracks):
                with self.subTest(tree=str(tree)):
                    bounds = tree.bbox("example")
                    self.assertTrue(bounds, "Row should be displayed")
                    x, y, width, height = bounds
                    screen_x = tree.winfo_rootx() + x + min(width // 2, 30)
                    screen_y = tree.winfo_rooty() + y + height // 2
                    self.assertEqual(app.winfo_containing(screen_x, screen_y), tree,
                                     "Another widget is covering the row")
        finally:
            app.destroy()

    def test_browse_select_remove_and_save(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "episode.mkv"
            subprocess.run([
                tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "sine=duration=1",
                "-map", "0:a", "-map", "0:a", "-c", "copy", str(source)],
                capture_output=True, check=True, **process_options())
            app = App()
            app.withdraw()

            def wait_for(predicate):
                deadline = time.monotonic() + 15
                while not predicate() and time.monotonic() < deadline:
                    app.update()
                    time.sleep(0.02)
                self.assertTrue(predicate(), "GUI operation timed out")

            try:
                self.assertTrue(app.overwrite.get())
                app.folder = Path(temporary)
                app.refresh()
                self.assertEqual(len(app.file_tree.get_children()), 1)
                app.file_tree.selection_set("0")
                app.select_file()
                wait_for(lambda: app.info is not None)
                self.assertEqual(len(app.tracks.get_children()), 2)
                app.toggle(app.tracks.get_children()[0])
                choice = next(key for key, value in app.default_choices.items() if value is not None)
                app.default.set(choice)
                with patch("app.messagebox.showinfo") as success, patch("app.messagebox.showerror") as error:
                    app.save()
                    wait_for(lambda: not app.busy)
                    error.assert_not_called()
                    success.assert_called_once()
                self.assertTrue(app.last_output.is_file())
                self.assertEqual(app.last_output, source)
                wait_for(lambda: app.info is not None)
                self.assertEqual(len(app.tracks.get_children()), 1)
                self.assertFalse(app.removed)
                self.assertEqual(len(audio_streams(inspect(app.last_output))), 1)
                self.assertEqual(len(audio_streams(inspect(source))), 1)
                # Save again after replacement: the UI must use refreshed stream indexes.
                app.overwrite.set(False)
                app.default.set(next(key for key, value in app.default_choices.items() if value is not None))
                with patch("app.messagebox.showinfo"), patch("app.messagebox.showerror") as error:
                    app.save()
                    wait_for(lambda: not app.busy)
                    error.assert_not_called()
                self.assertEqual(app.last_output, source.with_name("episode-clear.mkv"))
                self.assertEqual(len(audio_streams(inspect(source))), 1)
                self.assertEqual(len(app.file_tree.get_children()), 2)
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()
