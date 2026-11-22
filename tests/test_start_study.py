"""Offline Windows launcher regressions; all listeners are owned ephemeral fixtures."""
import base64
import ctypes
import hashlib
import http.server
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import unittest
import urllib.request
import uuid


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "start-study.ps1"
POWERSHELL = shutil.which("powershell.exe")
PID_PATTERN = re.compile(r"Study server process: (\d+)")


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def process_handle(pid, terminate=False):
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.restype = ctypes.c_void_p
    return kernel.OpenProcess(0x100000 | (1 if terminate else 0), False, pid)


def is_alive(pid):
    handle = process_handle(pid)
    if not handle:
        return False
    try:
        return ctypes.windll.kernel32.WaitForSingleObject(ctypes.c_void_p(handle), 0) == 258
    finally:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))


def terminate_owned_child(pid, code=23):
    handle = process_handle(pid, terminate=True)
    if not handle:
        return
    try:
        if ctypes.windll.kernel32.WaitForSingleObject(ctypes.c_void_p(handle), 0) == 258:
            if not ctypes.windll.kernel32.TerminateProcess(ctypes.c_void_p(handle), code):
                raise OSError("Could not stop the recorded test child")
            ctypes.windll.kernel32.WaitForSingleObject(ctypes.c_void_p(handle), 5000)
    finally:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))


@unittest.skipUnless(os.name == "nt" and POWERSHELL, "requires Windows PowerShell")
class StartStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = ROOT / ".cache" / ("start-study-tests-" + uuid.uuid4().hex[:12])
        cls.evidence.mkdir(parents=True)
        cls.published_hash = hashlib.sha256((ROOT / "data/study/index.json").read_bytes()).hexdigest()
        cls.results = []

    @classmethod
    def tearDownClass(cls):
        after_hash = hashlib.sha256((ROOT / "data/study/index.json").read_bytes()).hexdigest()
        (cls.evidence / "evidence.json").write_text(json.dumps({
            "publishedIndexSha256Before": cls.published_hash,
            "publishedIndexSha256After": after_hash,
            "publishedIndexUnchanged": after_hash == cls.published_hash,
            "python": sys.executable,
            "powershell": POWERSHELL,
            "launcherSha256": hashlib.sha256(LAUNCHER.read_bytes()).hexdigest(),
            "invocations": cls.results,
            "browser": "mocked; no browser process was launched",
            "cancellation": "PowerShell pipeline Stop(), no physical console Ctrl+C",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        if after_hash != cls.published_hash:
            raise AssertionError("Published study index changed during launcher tests")
        print("Launcher evidence:", cls.evidence)

    def setUp(self):
        self.case = self.evidence / self._testMethodName
        self.case.mkdir()
        self.project = self.case / "project with spaces-中文"
        (self.project / "data/study").mkdir(parents=True)
        (self.project / "web").mkdir()
        self.index = json.dumps({
            "schema": "codebrick-article-workspace",
            "summary": {"articles": 1, "curatedCandidates": 2},
            "contentApproved": False,
            "fixture": "临时索引，保留精确UTF-8字节",
        }, ensure_ascii=False).encode("utf-8")
        (self.project / "data/study/index.json").write_bytes(self.index)
        (self.project / "web/workbench.html").write_text("<title>launcher fixture</title>", encoding="utf-8")
        self.marker = self.case / "browser.json"
        self.port = self.free_port()
        self.sha = hashlib.sha256(self.index).hexdigest()

    def free_port(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.assertNotEqual(port, 8765)
        return port

    def script_prefix(self):
        return "$ErrorActionPreference = 'Stop'\n. " + ps_quote(LAUNCHER) + "\n"

    def server_call(self, extra="", expected=None, python=None):
        return ("Start-StudyServer -Python " + ps_quote(python or sys.executable)
                + " -Root " + ps_quote(self.project) + " -Port " + str(self.port)
                + " -ExpectedIndexHash " + ps_quote(expected or self.sha) + " -Verbose " + extra)

    def mock_browser(self, fail=False):
        if fail:
            return "function Open-StudyBrowser { param($Url); throw 'mock browser failed' }\n"
        return ("function Open-StudyBrowser { param($Url)\n"
                + " $seenHash = Get-StudyHttpIndexHash -Url "
                + ps_quote(f"http://127.0.0.1:{self.port}/data/study/index.json") + "\n"
                + " [pscustomobject]@{url=$Url; indexHash=$seenHash} | ConvertTo-Json -Compress | "
                + "Set-Content -LiteralPath " + ps_quote(self.marker) + " -Encoding UTF8\n}\n")

    def start_ps(self, script=None, args=None):
        number = len(self.results)
        log = self.case / f"powershell-{number}.log"
        if args is None:
            harness = self.case / f"harness-{number}.ps1"
            harness.write_text("[Console]::OutputEncoding = New-Object Text.UTF8Encoding $false\n" + script,
                               encoding="utf-8-sig")
            args = ["-File", str(harness)]
        command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", *args]
        with log.open("wb") as output:
            process = subprocess.Popen(command, cwd=ROOT.parent, stdout=output, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        record = {"test": self._testMethodName, "command": command,
                  "port": self.port, "log": str(log.relative_to(ROOT)), "launcherPid": process.pid}
        self.results.append(record)
        self.addCleanup(self.cleanup_process, process, log, record)
        return process, log, record

    def read_log(self, log):
        return log.read_bytes().decode("utf-8-sig", errors="replace")

    def cleanup_process(self, process, log, record):
        pids = sorted({int(pid) for pid in PID_PATTERN.findall(self.read_log(log))})
        record["serverPids"] = pids
        fallback = [pid for pid in pids if is_alive(pid)]
        for pid in fallback:
            terminate_owned_child(pid)
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        record["returnCode"] = process.returncode
        record["fallbackCleanupPids"] = fallback
        record["serverPidsAliveAfterCleanup"] = [pid for pid in pids if is_alive(pid)]

    def wait_for(self, process, log, predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            text = self.read_log(log)
            if predicate(text):
                return text
            if process.poll() is not None:
                self.fail(f"Launcher exited early ({process.returncode}):\n{text}")
            time.sleep(0.04)
        self.fail("Launcher wait timed out:\n" + self.read_log(log))

    def assert_no_listener(self):
        try:
            connection = socket.create_connection(("127.0.0.1", self.port), timeout=0.2)
        except OSError:
            return
        connection.close()
        self.fail("Test server still accepts connections")

    def assert_child_cleaned(self, log, require_pid=True):
        pids = sorted({int(pid) for pid in PID_PATTERN.findall(self.read_log(log))})
        if require_pid:
            self.assertTrue(pids, self.read_log(log))
        self.assertEqual([pid for pid in pids if is_alive(pid)], [], self.read_log(log))
        self.assert_no_listener()

    def run_expected_failure(self, script, message, require_pid=True):
        process, log, _ = self.start_ps(script)
        self.assertEqual(process.wait(timeout=20), 0, self.read_log(log))
        text = self.read_log(log)
        self.assertIn("EXPECTED_FAILURE:", text)
        self.assertIn(message, text)
        self.assertNotIn("CodeBrick Cards ready:", text)
        self.assertFalse(self.marker.exists())
        self.assert_child_cleaned(log, require_pid=require_pid)

    def catch_failure(self, call):
        return ("try { " + call + "; throw 'unexpected success' } catch { "
                + "Write-Output ('EXPECTED_FAILURE:' + $_.Exception.Message) }\n")

    def test_check_preserves_public_schema_and_never_starts_server(self):
        process, log, _ = self.start_ps(args=["-File", str(LAUNCHER), "-Check", "-NoBrowser", "-Port", str(self.port)])
        self.assertEqual(process.wait(timeout=20), 0, self.read_log(log))
        info = json.loads(self.read_log(log))
        self.assertFalse(info["serverStarted"])
        self.assertFalse(info["contentApproved"])
        self.assertEqual(info["url"], f"http://127.0.0.1:{self.port}/web/workbench.html")
        self.assertTrue(Path(info["python"]).is_file())
        self.assertEqual(info["project"], str(ROOT))
        self.assert_no_listener()

    def test_invalid_port_is_rejected_without_server(self):
        process, log, _ = self.start_ps(args=["-File", str(LAUNCHER), "-Check", "-Port", "1023"])
        self.assertNotEqual(process.wait(timeout=20), 0)
        self.assertNotIn("Study server process:", self.read_log(log))
        self.assert_no_listener()

    def test_missing_study_index_fails_before_start(self):
        copied = self.case / "start-study.ps1"
        shutil.copyfile(LAUNCHER, copied)
        process, log, _ = self.start_ps(args=["-File", str(copied), "-NoBrowser", "-Port", str(self.port)])
        self.assertNotEqual(process.wait(timeout=20), 0)
        self.assertIn("Study data is missing", self.read_log(log))
        self.assert_child_cleaned(log, require_pid=False)

    def test_cli_first_start_no_browser_and_child_exit_code(self):
        copied = self.project / "start-study.ps1"
        shutil.copyfile(LAUNCHER, copied)
        process, log, _ = self.start_ps(args=["-File", str(copied), "-NoBrowser", "-Port", str(self.port), "-Verbose"])
        text = self.wait_for(process, log, lambda text: "CodeBrick Cards ready:" in text)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{self.port}/data/study/index.json", timeout=2) as response:
            self.assertEqual(response.read(), self.index)
        with opener.open(f"http://127.0.0.1:{self.port}/web/workbench.html", timeout=2) as response:
            self.assertEqual(response.status, 200)
        self.assertIsNone(process.poll())
        pid = int(PID_PATTERN.search(text).group(1))
        terminate_owned_child(pid, code=23)
        self.assertEqual(process.wait(timeout=10), 23, self.read_log(log))
        self.assert_child_cleaned(log)

    def test_browser_mock_runs_only_after_live_verified_http(self):
        script = self.script_prefix() + self.mock_browser() + "$code = " + self.server_call() + "\nexit $code\n"
        process, log, _ = self.start_ps(script)
        text = self.wait_for(process, log, lambda text: self.marker.exists())
        browser = json.loads(self.marker.read_text(encoding="utf-8-sig"))
        self.assertEqual(browser["indexHash"], self.sha)
        self.assertEqual(browser["url"], f"http://127.0.0.1:{self.port}/web/workbench.html")
        self.assertIn("CodeBrick Cards ready:", text)
        self.assertIsNone(process.poll())
        terminate_owned_child(int(PID_PATTERN.search(text).group(1)), code=19)
        self.assertEqual(process.wait(timeout=10), 19, self.read_log(log))
        self.assert_child_cleaned(log)

    def test_no_browser_skips_mock(self):
        script = self.script_prefix() + self.mock_browser(fail=True) + "$code = " + self.server_call("-NoBrowser") + "\nexit $code\n"
        process, log, _ = self.start_ps(script)
        text = self.wait_for(process, log, lambda text: "CodeBrick Cards ready:" in text)
        self.assertIsNone(process.poll())
        self.assertNotIn("mock browser failed", text)
        terminate_owned_child(int(PID_PATTERN.search(text).group(1)), code=0)
        self.assertEqual(process.wait(timeout=10), 0, self.read_log(log))
        self.assert_child_cleaned(log)

    def test_browser_exception_reaps_server(self):
        script = self.script_prefix() + self.mock_browser(fail=True) + self.catch_failure(self.server_call())
        process, log, _ = self.start_ps(script)
        self.assertEqual(process.wait(timeout=20), 0, self.read_log(log))
        self.assertIn("EXPECTED_FAILURE:mock browser failed", self.read_log(log))
        self.assert_child_cleaned(log)

    def test_index_mismatch_fails_closed_and_reaps_server(self):
        script = self.script_prefix() + self.mock_browser() + self.catch_failure(self.server_call(expected="0" * 64))
        self.run_expected_failure(script, "does not match the local snapshot")

    def test_http_timeout_reaps_server_without_browser(self):
        script = (self.script_prefix() + self.mock_browser()
                  + "function Get-StudyHttpIndexHash { param($Url); throw [Net.WebException]::new('simulated stalled HTTP') }\n"
                  + self.catch_failure(self.server_call("-ReadyTimeoutMilliseconds 900")))
        self.run_expected_failure(script, "HTTP readiness timed out")

    def test_process_start_failure_does_not_open_browser(self):
        script = (self.script_prefix() + self.mock_browser()
                  + self.catch_failure(self.server_call(python=self.case / "missing-python.exe")))
        self.run_expected_failure(script, "EXPECTED_FAILURE:", require_pid=False)

    def test_occupied_exclusive_http_service_is_not_probed_or_opened(self):
        self.occupied_http_service(allow_reuse=False)

    def test_occupied_reusable_http_service_is_not_probed_or_opened(self):
        self.occupied_http_service(allow_reuse=True)

    def occupied_http_service(self, allow_reuse):
        fixture = self
        requests = []

        class OtherService(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(fixture.index)

            def log_message(self, *_):
                pass

        class ExclusiveServer(http.server.ThreadingHTTPServer):
            allow_reuse_address = allow_reuse

        with ExclusiveServer(("127.0.0.1", 0), OtherService) as other:
            self.port = other.server_port
            self.assertNotEqual(self.port, 8765)
            thread = threading.Thread(target=other.serve_forever, daemon=True)
            thread.start()
            try:
                script = self.script_prefix() + self.mock_browser() + self.catch_failure(self.server_call())
                process, log, _ = self.start_ps(script)
                self.assertEqual(process.wait(timeout=20), 0, self.read_log(log))
                text = self.read_log(log)
                self.assertIn("exited before becoming ready", text)
                self.assertIn("different free port", text)
                self.assertNotIn("CodeBrick Cards ready:", text)
                self.assertFalse(self.marker.exists())
                self.assertEqual(requests, [])
                pids = {int(pid) for pid in PID_PATTERN.findall(text)}
                self.assertTrue(pids)
                self.assertTrue(all(not is_alive(pid) for pid in pids))
                # The fixture listener remains ours and alive; the launcher must not stop it.
                with socket.create_connection(("127.0.0.1", self.port), timeout=1):
                    pass
            finally:
                other.shutdown()
                thread.join(timeout=5)
        self.assert_no_listener()

    def test_pipeline_cancellation_reaps_foreground_child(self):
        inner = self.script_prefix() + self.mock_browser() + self.server_call()
        encoded = base64.b64encode(inner.encode("utf-8")).decode("ascii")
        script = ("$ErrorActionPreference = 'Stop'\n$worker = [PowerShell]::Create()\n"
                  + "$null = $worker.AddScript([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + encoded + "')))\n"
                  + "$pending = $worker.BeginInvoke()\ntry {\n"
                  + " $deadline = [DateTime]::UtcNow.AddSeconds(15)\n"
                  + " while (-not (Test-Path -LiteralPath " + ps_quote(self.marker)
                  + ") -and -not $pending.IsCompleted -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 40 }\n"
                  + " if (-not (Test-Path -LiteralPath " + ps_quote(self.marker) + ")) { throw 'Pipeline never became ready' }\n"
                  + " $worker.Stop()\n Write-Output 'PIPELINE_STOPPED'\n"
                  + "} finally {\n if (-not $pending.IsCompleted) { $worker.Stop() }\n"
                  + " $worker.Streams.Verbose | ForEach-Object { Write-Output $_.Message }\n"
                  + " $worker.Dispose()\n}\n")
        process, log, _ = self.start_ps(script)
        self.assertEqual(process.wait(timeout=25), 0, self.read_log(log))
        self.assertIn("PIPELINE_STOPPED", self.read_log(log))
        self.assertTrue(self.marker.exists())
        self.assert_child_cleaned(log)


if __name__ == "__main__":
    unittest.main(verbosity=2)
