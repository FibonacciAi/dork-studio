"""Desktop launcher tests using only mocked sockets and browser commands."""
import contextlib
import errno
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_STATE = tempfile.TemporaryDirectory(prefix="dork-launcher-tests-")
_SOURCE = Path(__file__).resolve().parents[1] / "app" / "dashboard.py"
with patch.dict(os.environ, {"DORK_STATE_HOME": _STATE.name, "DORK_NO_ENV": "1"}, clear=True):
    spec = importlib.util.spec_from_file_location("dork_launcher_test_dashboard", _SOURCE)
    dashboard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dashboard)


class BoundServerFake:
    """Mirror the fd-backed Werkzeug server's port interface strictly."""
    __slots__ = ("port", "serve_calls", "closed")

    def __init__(self, port):
        self.port = port
        self.serve_calls = 0
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def serve_forever(self):
        self.serve_calls += 1


class LauncherTests(unittest.TestCase):
    def listener(self, port=5412, fd=42):
        listener = MagicMock()
        listener.getsockname.return_value = ("127.0.0.1", port)
        listener.fileno.return_value = fd
        return listener

    def test_preferred_port_is_stable_per_user_and_outside_old_range(self):
        for user in ("synthetic-user", "another-user", ""):
            expected = 5357 + int(hashlib.md5(user.encode()).hexdigest(), 16) % 100
            self.assertEqual(dashboard.preferred_dork_port(user), expected)
            self.assertGreaterEqual(expected, 5357)
            self.assertLessEqual(expected, 5456)
        with patch("getpass.getuser", return_value="synthetic-user"):
            self.assertEqual(dashboard.preferred_dork_port(), dashboard.preferred_dork_port("synthetic-user"))

    def test_loopback_listener_is_handed_to_threaded_server_without_rebind(self):
        listener = self.listener()
        with patch("socket.socket", return_value=listener) as socket_factory:
            with patch("werkzeug.serving.make_server") as make_server:
                self.assertIs(dashboard.create_local_server(5412), make_server.return_value)
        socket_factory.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind.assert_called_once_with(("127.0.0.1", 5412))
        listener.listen.assert_called_once_with(socket.SOMAXCONN)
        make_server.assert_called_once_with("127.0.0.1", 5412, dashboard.app, threaded=True, fd=42)
        listener.close.assert_called_once()

    def test_collision_with_opt_in_uses_one_ephemeral_fallback(self):
        busy, free = self.listener(), self.listener(42001, 43)
        busy.bind.side_effect = OSError(errno.EADDRINUSE, "Address already in use")
        with patch("socket.socket", side_effect=[busy, free]) as socket_factory:
            with patch("werkzeug.serving.make_server") as make_server:
                dashboard.create_local_server(5412, fallback_port=True)
        self.assertEqual(socket_factory.call_count, 2)
        busy.bind.assert_called_once_with(("127.0.0.1", 5412))
        free.bind.assert_called_once_with(("127.0.0.1", 0))
        busy.close.assert_called_once()
        free.close.assert_called_once()
        make_server.assert_called_once_with("127.0.0.1", 42001, dashboard.app, threaded=True, fd=43)

    def test_explicit_port_collision_without_fallback_fails(self):
        busy = self.listener()
        busy.bind.side_effect = OSError(errno.EADDRINUSE, "Address already in use")
        with patch("socket.socket", return_value=busy) as socket_factory:
            with patch("werkzeug.serving.make_server") as make_server:
                with self.assertRaises(OSError) as caught:
                    dashboard.create_local_server(5412)
        self.assertEqual(caught.exception.errno, errno.EADDRINUSE)
        socket_factory.assert_called_once()
        make_server.assert_not_called()
        busy.close.assert_called_once()

    def test_permission_and_other_bind_errors_never_fallback(self):
        for code in (errno.EPERM, errno.EACCES, errno.EADDRNOTAVAIL, errno.EINVAL):
            with self.subTest(code=code):
                listener = self.listener()
                listener.bind.side_effect = OSError(code, "synthetic denial")
                with patch("socket.socket", return_value=listener) as socket_factory:
                    with patch("werkzeug.serving.make_server") as make_server:
                        with self.assertRaises(OSError) as caught:
                            dashboard.create_local_server(5412, fallback_port=True)
                self.assertEqual(caught.exception.errno, code)
                socket_factory.assert_called_once()
                make_server.assert_not_called()
                listener.close.assert_called_once()

    def test_socket_creation_and_listen_errors_do_not_trigger_collision_fallback(self):
        with patch("socket.socket", side_effect=OSError(errno.EADDRINUSE, "synthetic constructor failure")) as factory:
            with self.assertRaises(OSError):
                dashboard.create_local_server(5412, fallback_port=True)
        factory.assert_called_once()
        listener = self.listener()
        listener.listen.side_effect = OSError(errno.EPERM, "synthetic listen denial")
        with patch("socket.socket", return_value=listener) as factory:
            with patch("werkzeug.serving.make_server") as make_server:
                with self.assertRaises(OSError):
                    dashboard.create_local_server(5412, fallback_port=True)
        factory.assert_called_once()
        make_server.assert_not_called()
        listener.close.assert_called_once()

    def test_fallback_failure_stops_without_third_attempt(self):
        busy, denied = self.listener(), self.listener()
        busy.bind.side_effect = OSError(errno.EADDRINUSE, "Address already in use")
        denied.bind.side_effect = OSError(errno.EPERM, "synthetic denial")
        with patch("socket.socket", side_effect=[busy, denied]) as factory:
            with self.assertRaises(OSError) as caught:
                dashboard.create_local_server(5412, fallback_port=True)
        self.assertEqual(caught.exception.errno, errno.EPERM)
        self.assertEqual(factory.call_count, 2)

    def test_explicit_port_zero_binds_once(self):
        listener = self.listener(42002)
        with patch("socket.socket", return_value=listener) as factory:
            with patch("werkzeug.serving.make_server"):
                dashboard.create_local_server(0, fallback_port=True)
        factory.assert_called_once()
        listener.bind.assert_called_once_with(("127.0.0.1", 0))

    def test_chrome_app_mode_payload_is_local_and_no_shell_is_used(self):
        url = "http://127.0.0.1:5412"
        with patch("sys.platform", "darwin"), patch.object(Path, "is_dir", return_value=True):
            with patch.object(dashboard.subprocess, "run", return_value=MagicMock(returncode=0)) as run:
                with patch("webbrowser.open") as default_browser:
                    self.assertTrue(dashboard.open_desktop_studio(url))
        run.assert_called_once_with(["open", "-na", "/Applications/Google Chrome.app", "--args", "--app=" + url, "--window-size=1500,930"], stdout=dashboard.subprocess.DEVNULL, stderr=dashboard.subprocess.DEVNULL, check=False)
        default_browser.assert_not_called()

    def test_edge_app_mode_when_chrome_is_unavailable(self):
        url = "http://127.0.0.1:5412"
        with patch("sys.platform", "darwin"), patch.object(Path, "is_dir", side_effect=[False, False, True]):
            with patch.object(dashboard.subprocess, "run", return_value=MagicMock(returncode=0)) as run:
                with patch("webbrowser.open") as default_browser:
                    self.assertTrue(dashboard.open_desktop_studio(url))
        self.assertEqual(run.call_args.args[0][2], "/Applications/Microsoft Edge.app")
        default_browser.assert_not_called()

    def test_default_browser_fallback_when_no_app_mode_browser_exists(self):
        url = "http://127.0.0.1:5412"
        with patch("sys.platform", "darwin"), patch.object(Path, "is_dir", return_value=False):
            with patch.object(dashboard.subprocess, "run") as run:
                with patch("webbrowser.open", return_value=True) as default_browser:
                    self.assertTrue(dashboard.open_desktop_studio(url))
        run.assert_not_called()
        default_browser.assert_called_once_with(url, new=1)

    def test_browser_permission_error_stops_opening_without_another_browser(self):
        with patch("sys.platform", "darwin"), patch.object(Path, "is_dir", return_value=True):
            with patch.object(dashboard.subprocess, "run", side_effect=PermissionError(errno.EPERM, "synthetic denial")) as run:
                with patch("webbrowser.open") as default_browser:
                    self.assertFalse(dashboard.open_desktop_studio("http://127.0.0.1:5412"))
        run.assert_called_once()
        default_browser.assert_not_called()

    def test_nonlocal_browser_url_is_rejected_before_opening(self):
        with patch.object(dashboard.subprocess, "run") as run, patch("webbrowser.open") as default_browser:
            with self.assertRaises(ValueError):
                dashboard.open_desktop_studio("https://external.example")
        run.assert_not_called()
        default_browser.assert_not_called()

    def test_cli_default_uses_per_user_port_and_opens_only_after_bind(self):
        server = BoundServerFake(5412)
        with patch.object(dashboard, "preferred_dork_port", return_value=5412):
            with patch.object(dashboard, "create_local_server", return_value=server) as create:
                with patch("threading.Timer") as timer, contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(dashboard.run_local_studio(["--open", "--fallback-port"]), 0)
        create.assert_called_once_with(5412, fallback_port=True)
        timer.assert_called_once_with(0.4, dashboard.open_desktop_studio, args=("http://127.0.0.1:5412",))
        self.assertTrue(timer.return_value.daemon)
        timer.return_value.start.assert_called_once()
        self.assertEqual(server.serve_calls, 1)
        self.assertTrue(server.closed)
        self.assertFalse(hasattr(server, "server_port"))

    def test_cli_port_zero_uses_actual_bound_port_in_url(self):
        server = BoundServerFake(42003)
        output = io.StringIO()
        with patch.object(dashboard, "create_local_server", return_value=server) as create:
            with patch("threading.Timer") as timer, contextlib.redirect_stdout(output):
                self.assertEqual(dashboard.run_local_studio(["--port", "0", "--open"]), 0)
        create.assert_called_once_with(0, fallback_port=False)
        timer.assert_called_once_with(0.4, dashboard.open_desktop_studio, args=("http://127.0.0.1:42003",))
        self.assertIn("http://127.0.0.1:42003", output.getvalue())
        self.assertEqual(server.serve_calls, 1)

    def test_cli_explicit_port_and_clear_collision_failure(self):
        error = OSError(errno.EADDRINUSE, "Address already in use")
        output = io.StringIO()
        with patch.object(dashboard, "create_local_server", side_effect=error) as create:
            with patch("threading.Timer") as timer, contextlib.redirect_stderr(output):
                self.assertEqual(dashboard.run_local_studio(["--open", "--port", "5413"]), 1)
        create.assert_called_once_with(5413, fallback_port=False)
        timer.assert_not_called()
        self.assertIn("5413 is occupied", output.getvalue())
        self.assertIn("Existing processes were left running", output.getvalue())

    def test_cli_permission_failure_stops_before_browser_open(self):
        output = io.StringIO()
        with patch.object(dashboard, "create_local_server", side_effect=OSError(errno.EPERM, "Operation not permitted")) as create:
            with patch("threading.Timer") as timer, contextlib.redirect_stderr(output):
                self.assertEqual(dashboard.run_local_studio(["--open", "--port", "5412", "--fallback-port"]), 1)
        create.assert_called_once()
        timer.assert_not_called()
        self.assertIn("Launch stopped", output.getvalue())


if __name__ == "__main__":
    unittest.main()
