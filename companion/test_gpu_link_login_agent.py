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

    def test_agent_lives_in_the_user_library(self):
        self.assertEqual(agent.agent_path(Path("/Users/me")),
                         Path("/Users/me/Library/LaunchAgents/os.opos.gpulink.companion.plist"))


if __name__ == "__main__":
    unittest.main()
