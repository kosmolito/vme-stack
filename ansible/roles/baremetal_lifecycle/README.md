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

Uses `ansible.builtin.pause`, so it must run in a play with the linear strategy.
