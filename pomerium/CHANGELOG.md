# Changelog

All notable changes to this add-on will be documented in this file.

## [0.1.1] - 2026-10-27

### Changed
- Pomerium v0.33.1 -> v0.33.6. Security-relevant changes in between:
  - v0.33.4: fixes GHSA-pj2c-mjp8-p2m9 (upstream connections not reused
    across downstream clients; denial of service under many unique clients,
    e.g. internet-facing bot traffic) and updates the embedded Envoy from
    v1.38.2 to v1.38.5, which carries the Envoy security fixes from v1.38.3
    and v1.38.4 (among them CVE-2026-47778 TLS SAN truncation auth bypass,
    CVE-2026-73553 RBAC path-parameter auth bypass, CVE-2026-48743 HTTP/3
    request smuggling and a dozen crash/DoS fixes).
  - v0.33.5: hardens MCP request authorization (case-sensitive JSON member
    matching, rejects malformed/empty methods).
  - v0.33.6: refreshed CA bundle in the upstream distroless image to distrust
    the compromised eMudhra intermediates. This add-on only copies the
    `pomerium` binary out of that image; the trust store Envoy uses here is
    the HA Debian base's `ca-certificates`, installed fresh at build time
    (upstream requires `20250419~deb12u2` or newer for the same distrust).
  - v0.33.3: fixes for gRPC/MCP outbound connection reloads (no security
    impact). v0.33.2 was never published.
- No configuration changes: no new, renamed or removed options between
  v0.33.1 and v0.33.6, and the generated config is unchanged.

## [0.1.0] - 2026-08-19

### Added
- Initial release: Pomerium v0.33.1 (open source, all-in-one mode) as an
  identity-aware reverse proxy for Home Assistant and other add-ons
  (amd64, aarch64).
- Option-driven config generation: structured `routes` with per-route access
  rules (`allowed_users`, `allowed_domains`, `allow_any_authenticated_user`)
  compiled to Pomerium Policy Language. Routes without access rules deny all
  traffic by default.
- TLS via Let's Encrypt `autocert` (cache persisted in `/data`) or existing
  certificates from `/ssl` (`certfile`/`keyfile`).
- Hosted authenticate service by default (no IdP registration needed);
  optional self-hosted authenticate with `idp_*` options.
- `config_mode: file` escape hatch: a complete `pomerium.yaml` in the
  add-on config directory is used verbatim.
- Auto-generated, persisted `cookie_secret` so session cookies stay valid
  across restarts and updates; injected via environment in file mode when
  absent.
- Refuses to start while a route still uses the `example.com` placeholder.
- Design notes in `docs/DESIGN.md`.
