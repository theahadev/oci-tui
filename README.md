# OCI TUI

> *if a webui is too heavy, build your own tui*

A terminal UI for managing Oracle Cloud Infrastructure compute instances, built with [Textual](https://textual.textualize.io/) and the [OCI Python SDK](https://oracle-cloud-infrastructure-python-sdk.readthedocs.io/).

## Features

- **Compartment-aware instance browser** with live lifecycle colours and lazy IP loading
- **Quick detail panel** for the selected instance, including shape, AD, public IP, and private IP
- **Power operations** for instances: start, graceful stop, reboot, and terminate with confirmation prompts
- **Instance launch workflow** with availability domain, shape, image, subnet, optional display name, SSH key, and flex OCPU/memory inputs
- **Networking overview tab** with:
  - all VNICs in the compartment
  - private/public IP administration mapping
  - reserved public IP management
  - security list inspection and editing
- **Reserved public IP management** with continuous auto-refresh, sorting, reserve, rename, and delete actions
- **Security list rule management** for ingress and egress rules, including add, edit, and delete flows
- **Full instance detail screen** with separate Details, Networking, Storage, and Console tabs
- **Deep networking drill-down** for primary VNIC information, attached VNICs, route tables, NSGs, DNS/FQDN details, and per-IP administration
- **VNIC lifecycle actions** from instance detail: attach a secondary VNIC, edit VNIC settings, detach non-primary VNICs, and open a dedicated VNIC detail view
- **Storage visibility** for boot volume attachments and block volume attachments
- **Console visibility** for active instance console connections and connection strings
- **Copy/reveal support** for long OCIDs and identifiers in detail screens
- **Non-blocking UI** — OCI API calls run in background workers so the interface stays responsive

## Keyboard shortcuts

### Main screen

| Key | Action |
|-----|--------|
| `c` | Change compartment |
| `R` | Refresh instances and networking data |
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
| `v` | View the selected VNIC in the Networking > VNICs table |
| `n` | Reserve a new public IP in Networking > Reserved Public IPs |
| `e` | Edit the selected reserved public IP name |
| `Delete` | Delete the selected reserved public IP |
| `I` | Add an ingress rule to the selected security list |
| `E` | Add an egress rule to the selected security list |
| `J` | Edit the selected ingress rule |
| `K` | Edit the selected egress rule |
| `D` | Delete the selected ingress rule |
| `X` | Delete the selected egress rule |

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

## What you can manage

### Instances

- Browse non-terminated instances in the current compartment
- Refresh instance and networking data
- Start, stop, reboot, and terminate instances
- Launch a new compute instance from the TUI
- Open a full-screen detail view for the selected instance

### Networking

- Review all VNIC attachments in the current compartment
- Inspect private/public IP mappings
- View reserved public IPs with deterministic sorting by creation date, IP address, or name
- Reserve, rename, and delete reserved public IPs
- Inspect security lists and modify ingress/egress rules

### Instance details

- Review general metadata, shape configuration, image details, and launch options
- Inspect primary VNIC networking data and all attached VNICs
- Attach, edit, detach, and inspect VNICs
- Review boot volume and block volume attachments
- View active console connection details

### VNIC details

- Inspect subnet, route table, MAC, VLAN tag, NSGs, hostname label, FQDN, and IPv6 data
- Review all private IPs on the VNIC together with public IP lifetime and route-table information

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
- Reserved public IPs auto-refresh and preserve the selected row when possible.
- The app uses your `DEFAULT` profile. To use a different profile, edit `main.py` and pass `profile="MY_PROFILE"` to `OCIManager`.
- Flex shapes (e.g. `VM.Standard.E4.Flex`, `VM.Standard.A1.Flex`) show OCPU/Memory fields in the launch form.
