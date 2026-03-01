from __future__ import annotations

from typing import Optional

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Rule, Select

# ── Modal: Attach VNIC ───────────────────────────────────────────────────────

class AttachVnicModal(ModalScreen):
    """Form to attach a secondary VNIC to an instance."""

    BINDINGS = [Binding("escape", "dismiss_cancel", "Cancel")]

    def __init__(self, subnets: list, nsgs: list) -> None:
        super().__init__(classes="launch-modal")
        self._subnets = subnets
        self._nsgs    = nsgs

    def compose(self) -> ComposeResult:
        subnet_opts = [(s.display_name or s.id[:28], s.id) for s in self._subnets]
        nsg_opts    = [
            (f"{n.display_name or n.id[:20]}  [{n.vcn_id[-8:]}]", n.id)
            for n in self._nsgs
        ]

        with Container(id="modal-container"):
            yield Label("Attach VNIC", id="modal-title")
            yield Rule()
            with ScrollableContainer(classes="form-scroll"):
                yield Label("VNIC Display Name", classes="field-label")
                yield Input(placeholder="my-vnic  (optional)", id="in-vnic-name")

                yield Label("Attachment Display Name", classes="field-label")
                yield Input(placeholder="my-vnic-attachment  (optional)", id="in-att-name")

                yield Label("Subnet *", classes="field-label")
                yield Select(subnet_opts, id="sel-subnet", prompt="Select subnet…")

                yield Label("Private IP", classes="field-label")
                yield Input(placeholder="leave blank for auto-assign", id="in-priv-ip")

                yield Label("Assign Public IP", classes="field-label")
                yield Select(
                    [("Auto (subnet default)", "auto"), ("Yes", "yes"), ("No", "no")],
                    id="sel-pub-ip", value="auto",
                )

                yield Label("Assign Private DNS Record", classes="field-label")
                yield Select(
                    [("Yes", "yes"), ("No", "no")],
                    id="sel-dns-record", value="yes",
                )

                yield Label("Hostname Label", classes="field-label")
                yield Input(placeholder="optional DNS label", id="in-hostname")

                yield Label("Skip Source / Destination Check", classes="field-label")
                yield Select(
                    [("No", "no"), ("Yes", "yes")],
                    id="sel-skip-sdc", value="no",
                )

                if nsg_opts:
                    yield Label("Network Security Groups", classes="field-label")
                    yield Select(
                        nsg_opts, id="sel-nsg",
                        prompt="Select NSG (optional, one at a time)…",
                        allow_blank=True,
                    )
                else:
                    yield Label("NSG IDs  (comma-separated OCIDs)", classes="field-label")
                    yield Input(placeholder="ocid1.networksecuritygroup…, …", id="in-nsg-ids")

                yield Label("NIC Index", classes="field-label")
                yield Input(placeholder="0  (default; 1 for additional NIC)", id="in-nic-idx")

            with Horizontal(id="modal-buttons"):
                yield Button("Attach", variant="primary", id="btn-attach-ok")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def action_dismiss_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-attach-ok")
    def do_attach(self) -> None:
        subnet = self.query_one("#sel-subnet", Select).value
        if subnet is Select.BLANK:
            self.notify("Subnet is required", severity="warning")
            return

        pub_ip_val = self.query_one("#sel-pub-ip", Select).value
        assign_pub = None if pub_ip_val == "auto" else (pub_ip_val == "yes")

        dns_val = self.query_one("#sel-dns-record", Select).value
        assign_dns = (dns_val == "yes")

        skip_sdc = self.query_one("#sel-skip-sdc", Select).value == "yes"

        nic_idx_raw = self.query_one("#in-nic-idx", Input).value.strip()
        nic_idx = int(nic_idx_raw) if nic_idx_raw.isdigit() else None

        # NSG: either from Select widget or free-text Input
        nsg_ids: list = []
        try:
            nsg_sel = self.query_one("#sel-nsg", Select)
            if nsg_sel.value is not Select.BLANK:
                nsg_ids = [nsg_sel.value]
        except Exception:
            pass
        try:
            nsg_raw = self.query_one("#in-nsg-ids", Input).value.strip()
            if nsg_raw:
                nsg_ids = [x.strip() for x in nsg_raw.split(",") if x.strip()]
        except Exception:
            pass

        self.dismiss({
            "subnet_id":           subnet,
            "display_name":        self.query_one("#in-vnic-name", Input).value.strip(),
            "attachment_name":     self.query_one("#in-att-name",  Input).value.strip(),
            "private_ip":          self.query_one("#in-priv-ip",   Input).value.strip(),
            "assign_public_ip":    assign_pub,
            "assign_private_dns":  assign_dns,
            "hostname_label":      self.query_one("#in-hostname",  Input).value.strip(),
            "skip_source_dest_check": skip_sdc,
            "nsg_ids":             nsg_ids,
            "nic_index":           nic_idx,
        })

    @on(Button.Pressed, "#btn-cancel")
    def do_cancel(self) -> None:
        self.dismiss(None)


# ── Modal: Edit VNIC ─────────────────────────────────────────────────────────

class EditVnicModal(ModalScreen):
    """Pre-populated form to update an existing VNIC."""

    BINDINGS = [Binding("escape", "dismiss_cancel", "Cancel")]

    def __init__(self, vnic, nsgs: list) -> None:
        super().__init__(classes="launch-modal")
        self._vnic = vnic
        self._nsgs = nsgs

    def compose(self) -> ComposeResult:
        v = self._vnic
        cur_nsg_str = ", ".join(v.nsg_ids) if v.nsg_ids else ""

        nsg_opts = [
            (f"{n.display_name or n.id[:20]}  [{n.vcn_id[-8:]}]", n.id)
            for n in self._nsgs
        ]

        with Container(id="modal-container"):
            yield Label(f"Edit VNIC: {v.display_name or v.id[-8:]}", id="modal-title")
            yield Rule()
            with ScrollableContainer(classes="form-scroll"):
                yield Label("Display Name", classes="field-label")
                yield Input(v.display_name or "", id="in-vnic-name")

                yield Label("Hostname Label", classes="field-label")
                yield Input(v.hostname_label or "", id="in-hostname")

                yield Label("Skip Source / Destination Check", classes="field-label")
                skip_val = "yes" if v.skip_source_dest_check else "no"
                yield Select(
                    [("No", "no"), ("Yes", "yes")],
                    id="sel-skip-sdc", value=skip_val,
                )

                yield Label("NSG IDs  (comma-separated OCIDs)", classes="field-label")
                if nsg_opts:
                    yield Label(
                        f"  [dim]Current: {cur_nsg_str or 'none'}[/dim]",
                        classes="field-label", markup=True,
                    )
                    yield Select(
                        nsg_opts, id="sel-nsg",
                        prompt="Add / replace NSG (leave blank to keep current)…",
                        allow_blank=True,
                    )
                yield Input(cur_nsg_str, placeholder="ocid1.networksecuritygroup…, …", id="in-nsg-ids")

                yield Label("Route Table Override ID", classes="field-label")
                yield Input(
                    getattr(v, "route_table_id", "") or "",
                    placeholder="ocid1.routetable…  (blank = subnet default)",
                    id="in-rt-id",
                )

            with Horizontal(id="modal-buttons"):
                yield Button("Save", variant="primary", id="btn-edit-ok")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def action_dismiss_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-edit-ok")
    def do_save(self) -> None:
        # Resolve NSG IDs: free-text wins; if blank and NSG select has value, use that
        nsg_raw = self.query_one("#in-nsg-ids", Input).value.strip()
        nsg_ids: Optional[list] = None
        if nsg_raw:
            nsg_ids = [x.strip() for x in nsg_raw.split(",") if x.strip()]
        else:
            try:
                nsg_sel = self.query_one("#sel-nsg", Select)
                if nsg_sel.value is not Select.BLANK:
                    nsg_ids = [nsg_sel.value]
            except Exception:
                pass

        self.dismiss({
            "display_name":           self.query_one("#in-vnic-name", Input).value.strip() or None,
            "hostname_label":         self.query_one("#in-hostname",  Input).value.strip() or None,
            "skip_source_dest_check": self.query_one("#sel-skip-sdc", Select).value == "yes",
            "nsg_ids":                nsg_ids,
            "route_table_id":         self.query_one("#in-rt-id",     Input).value.strip() or None,
        })

    @on(Button.Pressed, "#btn-cancel")
    def do_cancel(self) -> None:
        self.dismiss(None)
