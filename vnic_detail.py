from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static, TabbedContent, TabPane

from common import STATE_STYLE, _kv, _kv_long, _sec
from modals import CopyModal

# ── Screen: VNIC Detail ───────────────────────────────────────────────────────

class VnicDetailScreen(Screen):
    """Full-screen detail view for a single VNIC."""

    BINDINGS = [Binding("escape,q", "app.pop_screen", "Back")]

    def __init__(self, vnic_id: str, attachment, manager) -> None:
        super().__init__()
        self._vnic_id  = vnic_id
        self._att      = attachment
        self._mgr      = manager
        self._long_vals: dict = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="vnic-detail-header", markup=True)
        with TabbedContent(id="vnic-tabs"):
            with TabPane("VNIC Information", id="tab-vnic-info"):
                with ScrollableContainer(id="vnic-info-scroll"):
                    yield Static("[dim]  Loading…[/dim]", id="vnic-info-body", markup=True)
            with TabPane("IP Administration", id="tab-vnic-ips"):
                yield DataTable(id="vnic-ip-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def action_reveal(self, field_id: str) -> None:
        val = self._long_vals.get(field_id, "")
        self.app.push_screen(CopyModal(field_id.replace("_", " ").title(), val))

    def on_mount(self) -> None:
        tbl = self.query_one("#vnic-ip-table", DataTable)
        tbl.add_columns(
            "Private IP", "Public IP", "IP Lifetime",
            "FQDN", "Route Table", "Assigned",
        )
        self._load()

    @work(thread=True, name="load_vnic_detail")
    def _load(self) -> None:
        try:
            data = self._mgr.get_vnic_full_details(
                self._vnic_id,
                self._att.compartment_id,
                self._att,
            )
            self.app.call_from_thread(self._populate, data)
        except Exception as exc:
            self.app.call_from_thread(
                self.query_one("#vnic-info-body", Static).update,
                f"  [red]Error loading VNIC: {exc}[/red]",
            )

    def _populate(self, data: dict) -> None:
        def _fmt_dt(dt) -> str:
            return dt.strftime("%b %d, %Y, %H:%M UTC") if dt else "—"

        vnic = data["vnic"]
        att  = data["attachment"]
        sn   = data["subnet"]
        rt   = data["route_table"]

        # Header
        state = vnic.lifecycle_state
        col   = STATE_STYLE.get(state, "white").replace("bold ", "")
        self.query_one("#vnic-detail-header", Static).update(
            f" [b]{vnic.display_name or vnic.id[-12:]}[/b]   "
            f"[{col}]● {state}[/{col}]"
        )

        sn_name  = sn.display_name if sn else (vnic.subnet_id or "—")
        rt_name  = rt.display_name if rt else "—"
        nsg_text = ", ".join(vnic.nsg_ids) if vnic.nsg_ids else "None"
        ipv6_text = ", ".join(vnic.ipv6_addresses) if getattr(vnic, "ipv6_addresses", None) else "—"

        # Build FQDN
        fqdn = "—"
        if vnic.hostname_label and sn and data.get("vcn"):
            s_dns = getattr(sn, "dns_label", None)
            v_dns = getattr(data["vcn"], "dns_label", None)
            if s_dns and v_dns:
                fqdn = f"{vnic.hostname_label}.{s_dns}.{v_dns}.oraclevcn.com"

        # ── Tab 1: VNIC Information ────────────────────────────────────────
        lv    = self._long_vals
        text  = _sec("VNIC Information")
        text += _kv("Subnet",              sn_name)
        text += _kv("Skip Src/Dest Check", "Yes" if vnic.skip_source_dest_check else "No")
        text += _kv("MAC Address",         vnic.mac_address or "—")
        text += _kv("VLAN Tag",            str(att.vlan_tag) if att.vlan_tag is not None else "—")
        text += _kv_long("Compartment",    vnic.compartment_id, "vnic_comp",  lv)
        text += _kv_long("OCID",           vnic.id,             "vnic_ocid",  lv)
        text += _kv("Created",             _fmt_dt(vnic.time_created))
        text += _kv("Route Table",         rt_name)
        text += _kv("Network Sec. Groups", nsg_text)
        text += _kv("IPv6 Addresses",      ipv6_text)
        text += _kv("Hostname Label",      vnic.hostname_label or "—")
        text += _kv("FQDN",                fqdn)
        self.query_one("#vnic-info-body", Static).update(text)

        # ── Tab 2: IP Administration table ────────────────────────────────
        tbl = self.query_one("#vnic-ip-table", DataTable)
        tbl.clear()
        sorted_ips = sorted(
            data["private_ips"],
            key=lambda e: (not e["private_ip"].is_primary,),
        )
        for entry in sorted_ips:
            pip    = entry["private_ip"]
            pub    = entry["public_ip"]
            pip_rt = entry["route_table"]

            priv_label = pip.ip_address + (" (Primary IP)" if pip.is_primary else "")
            pub_label  = (pub.ip_address + (f" ({pub.lifetime})" if pub.lifetime else "")) if pub else "—"
            lifetime   = pub.lifetime if pub else "—"
            ip_fqdn    = fqdn if pip.is_primary else (pip.hostname_label or "—")
            rt_label   = pip_rt.display_name if pip_rt else rt_name

            tbl.add_row(
                priv_label, pub_label, lifetime,
                ip_fqdn, rt_label, _fmt_dt(pip.time_created),
                key=pip.id,
            )
