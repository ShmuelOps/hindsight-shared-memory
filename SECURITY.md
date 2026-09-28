# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue. Report privately via
[GitHub Security Advisories](https://github.com/ShmuelOps/hindsight-shared-memory/security/advisories/new).

## Threat model

- The Hindsight API (`:8888`), its MCP endpoint, and the optional UI (`:9999`) have **no authentication**. This
  project binds them to `127.0.0.1`, and CI checks that the server can't be reached on a non-loopback address.
  Any local process can still read and write memories.
- The embedded Postgres listens on `127.0.0.1:5488`.
- Memories are stored in plaintext. Don't retain secrets.
- With the `claude-code` provider, the server runs the Claude Agent SDK using your local Claude login.
- Vulnerabilities in Hindsight itself should be reported upstream to
  [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight/security).
