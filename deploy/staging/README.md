# Staging deployment templates

These sanitized templates describe the intended staging ingress after the operator prerequisites below are met. They contain no provider keys, authentication secrets, live Tailscale policy, or project data. They are not installed on `clawsrv` by this task.

## Intended request path

```text
authorized Tailscale user
  -> Tailscale Serve HTTPS on port 8767 (tailnet-only)
  -> Caddy on 127.0.0.1:8767 (validates Host/Origin and forwards identity)
  -> Workspace on 127.0.0.1:8766
```

Tailscale Serve supplies `Tailscale-User-Login` for user-identity devices and removes client-supplied identity headers. Configure the Workspace with `KDP_WORKSPACE_OPERATOR_HEADER=Tailscale-User-Login`. Tailscale does not populate that identity for tagged client devices, so those devices must not be used to authenticate operator actions. The app and Caddy listeners must remain on loopback; do not bind either to a LAN or Tailscale interface.

## Required operator gates

1. In Tailscale Access Controls, verify or set a least-privilege policy allowing only the named operator's user-identity devices to reach `clawsrv` TCP 8767. Remove broad member-wide grants for this port. Confirm the operator's client devices are not tagged. The current policy is not visible from the VPS and was not verified during G5.
2. Select and review an integrated, immutable application revision before deployment. The staging checkout currently has local modifications; do not overwrite them with `git pull`, branch checkout, or an unreviewed copy.
3. Take a paired SQLite and `projects/` backup, record its hash manifest, verify SQLite integrity and asset hashes, and verify a restore copy before changing routing or restarting the application.
4. Install these templates with owner-only permissions. Set `KDP_STAGING_FQDN` in `/home/clawusr/.config/kdp-workspace/proxy.env` to the machine's MagicDNS FQDN. Keep the provider key in its existing out-of-repository secret file; never place it in these templates or unit files.
5. Validate the Caddyfile and user units, including their effective systemd sandbox settings, before restart. The loopback app must be configured to trust only the Tailscale identity header.
6. Only after the ACL and backup gates pass, add a Tailscale Serve HTTPS route to the loopback Caddy port:

   ```bash
   tailscale serve --bg --https=8767 http://127.0.0.1:8767
   tailscale serve status
   ```

   Confirm port 8767 is shown as Serve-only and is not listed under Funnel. Preserve the unrelated existing Funnel route on port 443.
7. Test from the authorized user device: Workspace/health checks succeed, the authenticated identity is recorded instead of a submitted form name, an invalid Host or Origin is rejected, and a non-authorized tailnet device cannot connect. Do not invoke provider-backed actions during this smoke test.

## Rollback

- The additive Serve route can be removed with `tailscale serve --https=8767 off`; this must not alter existing Serve/Funnel ports.
- Restore the saved Caddyfile and systemd user unit files from the pre-change backup, then run `systemctl --user daemon-reload` and restart the relevant user service only after checking the restored files.
- If data recovery is needed, stop Workspace writes and restore the SQLite database and matching `projects/` archive together from one verified backup. Never restore only one half, and never overwrite newer staging work without an explicit recovery decision.

The G5 pre-change backup is documented in `docs/operations/ENVIRONMENTS.md`. It is owner-only (directory mode 0700, files mode 0600) but **not encrypted at file level**; host-disk encryption was not verified. Do not copy it off-host or change its permissions without an approved storage policy.

## References

- [Tailscale Serve and identity headers](https://tailscale.com/docs/features/tailscale-serve)
- [Tailscale Serve CLI](https://tailscale.com/docs/reference/tailscale-cli/serve)
- [Caddy `reverse_proxy`](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)
- [Caddy request matchers](https://caddyserver.com/docs/caddyfile/matchers)
