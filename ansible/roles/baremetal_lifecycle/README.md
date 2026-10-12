# baremetal_lifecycle (vendored)

Copied on 2026-10-10 from the private repo `kosmolito/ansible-baremetal-lifecycle`
(`roles/baremetal_lifecycle`), so vme-stack and its EE need no access to that repo.
Raw Redfish (`uri`) for HPE iLO and Dell iDRAC: eject and insert virtual media,
optional BIOS setup, one-time boot override, power on or reset.

vme-stack calls it from `boot_redfish` (platform `redfish`). Sync changes between the
two copies by hand.

Local changes against the origin:
- `tasks/{hpe,dell}/02_insert_virtual_media.yml`: the ISO URL check uses `HEAD`
  instead of `GET` (GET downloaded the whole ~4.6 GB ISO through the controller).
- Basic auth fallback and `Accept` header (2026-10-12, Dell iDRAC with Redfish 1.4.0):
  `tasks/00_collect_information.yml` accepts a 401 on the session login, then checks
  the same credentials with basic auth (`GET /redfish/v1/Systems`) and fails only
  if that is refused too. Every Redfish request sends the headers in `srv_headers`:
  the session token or basic auth, `Accept: application/json` (that iDRAC answers
  406 without it) and `Content-Type: application/json`; the session logout sends
  `Accept` too. `srv_auth` (default `session`; vme-stack: `bmc_auth`): `basic` skips
  the session login altogether. Diff for the origin: given to the maintainer to apply
  there.

Uses `ansible.builtin.pause`, so it must run in a play with the linear strategy.
