# Contributing

Thank you for looking. OPOS GPU Link is an early public demo. Issues are welcome. Pull requests that fix docs, tests, or a clear bug are welcome too; please keep them small.

## Before you start

- Read [README.md](README.md) and, for running from source, [companion/SETUP.md](companion/SETUP.md).
- USB is the only link today. Wireless: coming later.
- Do not paste API keys, pairing codes, model-server keys, or private host-app code into issues or pull requests. Security reports go to [SECURITY.md](SECURITY.md).

## Tests

GitHub Actions on `ubuntu-latest` runs the public suites (no secrets, no self-hosted runners). Tests that need the private host app stay excluded, as [phone-service/README.md](phone-service/README.md) says.

From the checkout root:

```sh
python3 -B -m unittest discover -s companion -p 'test_*.py' -v
```

```sh
cd phone-service
PYTHONPATH=src python3 -B -m unittest tests.test_run_link tests.test_link_api tests.test_gpu_link_proto tests.test_gpu_link_server -v
```

```sh
# Needs JDK 17 and JAVA_HOME. Compiles a subset of the app sources; no Android SDK or device.
cd android
./scripts/run-host-tests.sh
```

The Android debug APK is built with `android/scripts/build-debug-apk.sh`. That script needs JDK 17 and an Android SDK with platform `android-37.0` and build-tools `37.0.0`. It is not part of the hosted CI workflow.

## Pull requests

Use the pull request template: What? / Why? / How? / Testing / Screenshots / Anything else?

- One change per pull request.
- Do not change app or companion behavior in a docs-only change.
- Wait for CI to go green, then merge with a merge commit. No force-push, no admin bypass.
- Do not merge Dependabot version bumps before 10 Dec 2026. The current Action pins are the ones the demo CI is green on.
