# OCI TUI

> *if a webui is too heavy, build your own tui*

A terminal UI for managing Oracle Cloud Infrastructure compute instances, built with [Textual](https://textual.textualize.io/) and the [OCI Python SDK](https://oracle-cloud-infrastructure-python-sdk.readthedocs.io/).

## Features

- **Browse** instances across compartments with live state colours
- **Details** panel shows shape, IPs, availability domain, and more
- **Power actions** — start, graceful stop, reboot (with confirmation)
- **Terminate** with confirmation guard
- **Launch** new instances via a guided form (supports flex shapes + SSH key)
- **Switch compartments** at any time
- Non-blocking UI — all API calls run in background threads

## Keyboard shortcuts

### Main screen

| Key | Action |
|-----|--------|
| `c` | Change compartment |
| `R` | Refresh instance list |
| `s` | Start selected instance |
| `S` | Stop selected instance |
| `b` | Reboot selected instance |
| `x` | Terminate selected instance |
| `l` | Launch new instance |
| `i` | Show full instance details |
| `q` | Quit |

### Networking tab (main screen)

| Key | Action |
|-----|--------|
| `v` | View VNIC detail |
| `I` | Add ingress rule |
| `E` | Add egress rule |
| `J` | Edit selected ingress rule |
| `K` | Edit selected egress rule |
| `D` | Delete selected ingress rule |
| `X` | Delete selected egress rule |

### Instance detail screen

| Key | Action |
|-----|--------|
| `1` | Details tab |
| `2` | Networking tab |
| `3` | Storage tab |
| `4` | Console tab |
| `a` | Add VNIC |
| `e` | Edit selected VNIC |
| `d` | Detach selected VNIC |
| `v` | View VNIC detail |
| `Escape` / `q` | Back |

## Setup

### 1. Configure OCI CLI credentials

If you haven't already, set up `~/.oci/config`:

```bash
oci setup config
```

Or create it manually:

```ini
[DEFAULT]
user=ocid1.user.oc1..aaaa...
fingerprint=xx:xx:xx:...
key_file=~/.oci/oci_api_key.pem
tenancy=ocid1.tenancy.oc1..aaaa...
region=us-ashburn-1
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run

```bash
python main.py
```

## Notes

- IPs are fetched lazily after the instance list loads (one API call per instance).
- The app uses your `DEFAULT` profile. To use a different profile, edit `main.py` and pass `profile="MY_PROFILE"` to `OCIManager`.
- Flex shapes (e.g. `VM.Standard.E4.Flex`, `VM.Standard.A1.Flex`) show OCPU/Memory fields in the launch form.
