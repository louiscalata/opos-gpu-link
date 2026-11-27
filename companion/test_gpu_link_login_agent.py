import plistlib
import unittest
from pathlib import Path

import gpu_link_login_agent as agent


class LoginAgentTest(unittest.TestCase):
    def test_args_are_offline_strict_own_server(self):
        args = agent.companion_args("/usr/bin/python3", Path("/c"), serial="S1", adb="/a/adb",
                                    model_path="/m.gguf", log_dir="/logs")
        self.assertEqual(args[:4], ["/usr/bin/python3", "-u", "-B", "/c/gpu_link_autosetup.py"])
        for flag in ("--offline", "--strict-ports", "--own-server", "--no-pause"):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index("--port") + 1], "38400")
        self.assertEqual(args[args.index("--serial") + 1], "S1")
        self.assertEqual(args[args.index("--model-path") + 1], "/m.gguf")
        self.assertNotIn("--api-key", args)

    def test_optional_flags_are_left_out(self):
        args = agent.companion_args("py", Path("/c"))
        for flag in ("--serial", "--adb", "--model-path", "--log-dir"):
            self.assertNotIn(flag, args)

    def test_plist_starts_at_login_and_restarts_after_crash(self):
        plist = agent.build_plist(["py"], Path("/c"), Path("/logs"))
        self.assertEqual(plist["Label"], "os.opos.gpulink.companion")
        self.assertTrue(plist["RunAtLoad"])
        self.assertEqual(plist["KeepAlive"], {"SuccessfulExit": False})
        self.assertEqual(plist["WorkingDirectory"], "/c")
        self.assertIn("/opt/homebrew/bin", plist["EnvironmentVariables"]["PATH"])
        plistlib.loads(plistlib.dumps(plist))  # valid plist

    def test_plist_gives_time_for_a_clean_stop(self):
        plist = agent.build_plist(["py"], Path("/c"), Path("/logs"))
        self.assertGreaterEqual(plist["ExitTimeOut"], 20)

    def test_sigterm_unwinds_so_owned_servers_stop(self):
        import os
        import signal
        import gpu_link_autosetup as autosetup
        previous = signal.getsignal(signal.SIGTERM)
        try:
            self.assertTrue(autosetup.install_term_handler())
            stopped = []
            with self.assertRaises(autosetup.Terminated):
                try:
                    os.kill(os.getpid(), signal.SIGTERM)
                finally:
                    stopped.append(True)  # stands in for rt.stop() in run()'s finally
            self.assertEqual(stopped, [True])
        finally:
            signal.signal(signal.SIGTERM, previous)

    def test_servers_stay_in_the_launchd_job_group(self):
        import gpu_link_autosetup as autosetup
        plist = agent.build_plist(["py"], Path("/c"), Path("/logs"))
        self.assertEqual(plist["EnvironmentVariables"][autosetup.JOB_GROUP_ENV], "1")
        self.assertEqual(autosetup.server_session_options({autosetup.JOB_GROUP_ENV: "1"}), {})
        self.assertEqual(autosetup.server_session_options({}), {"start_new_session": True})

    def test_paths_are_absolute_for_launchd(self):
        import os
        self.assertEqual(agent.absolute("~/m.gguf"), os.path.expanduser("~/m.gguf"))
        self.assertTrue(os.path.isabs(agent.absolute("rel/m.gguf")))
        self.assertIsNone(agent.absolute(None))

    def test_waits_for_the_old_job_to_unload(self):
        states = iter([True, True, False])
        sleeps = []
        self.assertTrue(agent.wait_unloaded(lambda: next(states), sleeps.append))
        self.assertEqual(len(sleeps), 2)
        self.assertFalse(agent.wait_unloaded(lambda: True, lambda _s: None, timeout_s=1))

    def test_agent_lives_in_the_user_library(self):
        self.assertEqual(agent.agent_path(Path("/Users/me")),
                         Path("/Users/me/Library/LaunchAgents/os.opos.gpulink.companion.plist"))


if __name__ == "__main__":
    unittest.main()
