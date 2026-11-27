# Security

Please report vulnerabilities privately through [GitHub security advisories](https://github.com/louiscalata/opos-gpu-link/security/advisories/new). Do not open a public issue, pull request, or discussion with exploit details.

This is an early demo. It has not been independently audited, and nothing here is a security certification.

## Scope

OPOS GPU Link is a local, offline-first setup: an Android app, a loopback phone service, and a computer companion that talks to a local model server. The phone reaches the computer only through a USB-C `adb` forward. Pairing uses a six-digit compare-and-allow step, and later requests are signed.

In scope: the code in this repository, the pairing and signed-request path, the loopback services, and the published debug APK and companion builds.

Out of scope: third-party model servers and model files, `adb` itself, and the private host app that is not in this repository.

## Please include

- The commit or release you tested
- What you expected, and what happened
- A minimal way to reproduce it, without keys, pairing codes, or model-server credentials

There is no bounty program.
