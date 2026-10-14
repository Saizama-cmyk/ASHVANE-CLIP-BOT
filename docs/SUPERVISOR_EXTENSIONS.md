# Supervisor extensions

`Extensions(settings, data / "supervisor")` provides async `install(spec)`,
`call(extension_id, tool_name, arguments)`, `close()`, and synchronous `inventory()`.
The master switch must await `close()` so active host children and UUID-named Docker
containers are cancelled and removed. Extension manifests persist in
`data/supervisor/extensions`; execution is always in a fresh container.

Supported acquisition requests:

```python
await extensions.install({
    "kind": "mcp", "ecosystem": "pip", "package": "mcp-server-time",
    "version": "2026.10.10", "executable": "mcp-server-time", "args": []
})
await extensions.install({"kind": "skill", "url": "https://example.org/SKILL.md"})
await extensions.install({"kind": "connector", "url": "https://example.org/connector"})
```

MCP acquisition confirms an exact version and a supported free-software license in
public PyPI metadata. The main distribution must have a non-yanked wheel and its
SHA256 is enforced during installation. Dependencies are restricted to wheels and
resolved during the build; their individual versions are **not** independently
verified against registry metadata. The resulting immutable image ID pins the
complete installed environment for subsequent calls. There are no new host Python
dependencies. npm, source distributions and user-provided Dockerfiles are unsupported.

The official Python base is resolved to a registry digest before generating a
Dockerfile. Only that Dockerfile and a generated hashed requirement file enter the
build context over stdin. The requested executable must be a console entrypoint of
the requested distribution. The Docker CLI receives a fresh empty configuration
path and only OS bootstrap environment variables, never account tokens, proxies,
Docker environment overrides or the application environment. The Linux CLI starts
at `/`, preventing WSL from retaining a Windows workspace directory handle.

Runtime has no network, host mounts, Docker socket, credentials or inherited files.
It runs as UID/GID 65534, with a read-only root, dropped capabilities, no new
privileges, bounded memory/CPU/process count, and temporary `/tmp` and `/workspace`
filesystems. These temporary files disappear after every call; there is no persistent
MCP filesystem session. Network-dependent packages cannot use their remote features
under this policy. The supervisor's separate public research fetcher supplies public
network evidence when needed.

`callable` becomes true only after actual MCP initialization and a nonempty validated
`tools/list`. Each call repeats that handshake and confirms the requested tool in the
current inventory, then performs real `tools/call`. JSON-RPC input/output, stderr,
metadata, execution time and inventory size are bounded by supervisor settings.
Client filesystem roots, sampling, elicitation and account login capabilities are
not granted. Model-supplied environment, mounts, shell commands, paths, unpinned
versions and credential-like launch flags are rejected.

SKILL.md content is stored with its URL, SHA256 and truncation flag as untrusted
knowledge. It grants no authority and is never executed. Connector requests record
`needs_connection`; this component does not log in or fabricate a token. Public
HTTPS acquisition uses the existing research fetcher, which validates and pins public
DNS answers, verifies TLS, disables ambient proxies and refuses redirects. The
controller must continue excluding private account data and secrets from tool input.

Verified on 2026-10-12 with WSL Debian Docker 29.6.1: actual public PyPI installation
of MIT-licensed `mcp-server-time==2026.10.10`, successful initialize/list exposing
`get_current_time` and `convert_time`, and an offline `get_current_time` call for
`America/Chicago` returning `2026-10-12T20:36:48-05:00`. The base digest was
`python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1`.
The test image was deleted and all owned runtime containers were removed. Mocked
containment/protocol/failure tests run without Docker; the Windows symlink negative
control skips when the current account lacks symlink privilege.
