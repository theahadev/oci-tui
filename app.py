"""OCI TUI — Oracle Cloud Infrastructure terminal manager (Textual)."""

from __future__ import annotations

import time
from ipaddress import ip_address
from typing import Dict, Optional, Tuple

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Label,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from common import STATE_STYLE, _short_ad, _expand_port_range
from modals import CompartmentModal, ConfirmModal, PublicIpNameModal, SecurityRuleModal
from launch_modal import LaunchModal
from instance_detail import InstanceDetailScreen
from vnic_detail import VnicDetailScreen


# ── Main App ──────────────────────────────────────────────────────────────────

class OCIApp(App):
    """OCI TUI — manage Oracle Cloud compute instances from your terminal."""

    TITLE = "OCI TUI"
    CSS_PATH = "oci_tui.tcss"
    RESERVED_PUBLIC_IP_REFRESH_SECONDS = 10
    RESERVED_PUBLIC_IP_SORT_OPTIONS = [
        ("Created ↓", "created_desc"),
        ("Created ↑", "created_asc"),
        ("IP Address ↑", "ip_asc"),
        ("IP Address ↓", "ip_desc"),
        ("Name ↑", "name_asc"),
        ("Name ↓", "name_desc"),
    ]

    BINDINGS = [
        Binding("c",     "change_compartment",    "Compartment"),
        Binding("R",     "refresh",               "Refresh"),
        Binding("s",     "start",                 "Start"),
        Binding("S",     "stop",                  "Stop"),
        Binding("b",     "reboot",                "Reboot"),
        Binding("x",     "terminate",             "Terminate"),
        Binding("l",     "launch",                "Launch"),
        Binding("i",     "details",               "Details"),
        Binding("v",     "net_vnic_view",          "VNIC Detail",      show=False),
        Binding("q",     "quit",                  "Quit"),
        Binding("I",     "seclist_add_ingress",    "Add Ingress Rule",  show=False),
        Binding("E",     "seclist_add_egress",     "Add Egress Rule",   show=False),
        Binding("J",     "seclist_edit_ingress",   "Edit Ingress Rule", show=False),
        Binding("K",     "seclist_edit_egress",    "Edit Egress Rule",  show=False),
        Binding("D",     "seclist_del_ingress",    "Del Ingress Rule",  show=False),
        Binding("X",     "seclist_del_egress",     "Del Egress Rule",   show=False),
        Binding("n",     "reserve_public_ip",      "Reserve Public IP", show=False),
        Binding("e",     "edit_reserved_public_ip","Edit Reserved IP",  show=False),
        Binding("delete","delete_reserved_public_ip","Delete Reserved IP", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._manager = None
        self._instances: list      = []
        self._instance_map: dict   = {}
        self._ip_cache: Dict[str, Tuple[str, str]] = {}
        self._compartment_id: Optional[str] = None
        self._compartment_name: str = "—"
        self._col_ip      = None
        self._col_priv_ip = None
        # Networking tab state
        self._net_vnics_cache: list = []  # cached {vnic, attachment, subnet_name} dicts
        self._reserved_public_ips: list = []
        self._reserved_public_ip_selected_id: Optional[str] = None
        self._reserved_public_ip_sort: str = "created_desc"
        self._sec_lists: list = []        # cached security list objects
        self._sec_list_map: dict = {}     # id → security list
        self._cur_sec_list = None         # currently selected security list

    # ── Compose ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="toolbar"):
            yield Label("Compartment: ", classes="toolbar-label")
            yield Label("—", id="comp-name")
            yield Label("", id="status-label")
        with TabbedContent(id="main-tabs"):
            with TabPane("Instances", id="tab-instances"):
                with Container(id="main"):
                    yield DataTable(id="instance-table", cursor_type="row", zebra_stripes=True)
                    with Container(id="detail-panel"):
                        yield Static(
                            "[dim]No instance selected — use ↑↓ to navigate, [b]i[/b] for full details[/dim]",
                            id="detail-content",
                            markup=True,
                        )
            with TabPane("Networking", id="tab-networking-main"):
                with TabbedContent(id="net-tabs"):
                    with TabPane("VNICs", id="tab-net-vnics"):
                        yield DataTable(id="net-vnic-table", cursor_type="row", zebra_stripes=True)
                    with TabPane("IP Administration", id="tab-net-ips"):
                        yield DataTable(id="net-ip-table", cursor_type="row", zebra_stripes=True)
                    with TabPane("Reserved Public IPs", id="tab-net-reserved-ips"):
                        with Vertical(id="reserved-public-ip-layout"):
                            with Horizontal(id="reserved-public-ip-toolbar"):
                                yield Label("Order By", id="reserved-public-ip-sort-label")
                                yield Select(
                                    self.RESERVED_PUBLIC_IP_SORT_OPTIONS,
                                    value=self._reserved_public_ip_sort,
                                    id="reserved-public-ip-sort",
                                )
                                yield Static(
                                    f"Auto-refreshes every {self.RESERVED_PUBLIC_IP_REFRESH_SECONDS}s · Keys: n / e / Delete",
                                    id="reserved-public-ip-hint",
                                )
                            yield DataTable(
                                id="net-reserved-public-ip-table",
                                cursor_type="row",
                                zebra_stripes=True,
                            )
                    with TabPane("Security Lists", id="tab-net-seclist"):
                        with Vertical(id="seclist-layout"):
                            yield DataTable(id="seclist-table", cursor_type="row", zebra_stripes=True)
                            with TabbedContent(id="seclist-rules-tabs"):
                                with TabPane("Ingress Rules", id="tab-ingress"):
                                    yield DataTable(id="ingress-table", cursor_type="row", zebra_stripes=True)
                                with TabPane("Egress Rules", id="tab-egress"):
                                    yield DataTable(id="egress-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        # Instances tab
        table = self.query_one("#instance-table", DataTable)
        keys = table.add_columns("Name", "State", "Shape", "AD", "Public IP", "Private IP", "Created")
        self._col_ip      = keys[4]
        self._col_priv_ip = keys[5]

        # VNICs table
        vt = self.query_one("#net-vnic-table", DataTable)
        vt.add_columns("Name", "State", "Primary", "Subnet", "Private IP", "Public IP", "MAC", "Instance")

        # IP Admin table
        it = self.query_one("#net-ip-table", DataTable)
        it.add_columns("Private IP", "Public IP", "Lifetime", "Instance", "Subnet", "Assigned")

        # Reserved public IPs table
        rpt = self.query_one("#net-reserved-public-ip-table", DataTable)
        rpt.add_columns("Name", "IP Address", "Attachment Status", "Reservation Date")

        # Security list tables
        st = self.query_one("#seclist-table", DataTable)
        st.add_columns("Name", "State", "VCN", "Ingress Rules", "Egress Rules")

        ig = self.query_one("#ingress-table", DataTable)
        ig.add_columns("Stateless", "Source", "Protocol", "Src Port", "Dst Port", "ICMP", "Description")

        eg = self.query_one("#egress-table", DataTable)
        eg.add_columns("Stateless", "Destination", "Protocol", "Src Port", "Dst Port", "ICMP", "Description")

        self.set_interval(self.RESERVED_PUBLIC_IP_REFRESH_SECONDS, self._load_reserved_public_ips)
        self._init_oci()

    # ── OCI init / loading ────────────────────────────────────────────────────

    @work(thread=True, name="init_oci")
    def _init_oci(self) -> None:
        try:
            from oci_manager import OCIManager
            self._manager = OCIManager()
            tenancy_name  = self._manager.get_tenancy_name()
            self.call_from_thread(
                self._set_compartment,
                self._manager.tenancy_id,
                f"(root) {tenancy_name}",
            )
        except Exception as exc:
            self.call_from_thread(
                self.notify,
                f"OCI init failed: {exc}",
                severity="error",
                timeout=20,
            )

    def _set_compartment(self, cid: str, name: str) -> None:
        self._compartment_id   = cid
        self._compartment_name = name
        self.query_one("#comp-name", Label).update(name)
        self._load_instances()
        self._load_net_vnics()
        self._load_net_ips()
        self._load_reserved_public_ips()
        self._load_sec_lists()

    @work(thread=True, name="load_instances")
    def _load_instances(self) -> None:
        if not self._manager or not self._compartment_id:
            return
        self.call_from_thread(self._set_status, "⟳  Loading…")
        try:
            instances = self._manager.list_instances(self._compartment_id)
            self.call_from_thread(self._populate_table, instances)
            # Fetch IPs in same thread, update cells as they arrive
            for inst in instances:
                try:
                    pub, priv = self._manager.get_primary_ip(inst.compartment_id, inst.id)
                    self._ip_cache[inst.id] = (pub, priv)
                    self.call_from_thread(self._update_ip_cell, inst.id, pub, priv)
                except Exception:
                    self._ip_cache[inst.id] = ("—", "—")
        except Exception as exc:
            self.call_from_thread(self.notify, f"Load error: {exc}", severity="error")
        finally:
            self.call_from_thread(self._set_status, "")

    def _populate_table(self, instances: list) -> None:
        self._instances    = instances
        self._instance_map = {i.id: i for i in instances}

        table = self.query_one("#instance-table", DataTable)
        table.clear()

        for inst in instances:
            state      = inst.lifecycle_state
            state_text = Text(state, style=STATE_STYLE.get(state, "white"))
            ad         = _short_ad(inst.availability_domain)
            created    = inst.time_created.strftime("%Y-%m-%d") if inst.time_created else "—"
            cached     = self._ip_cache.get(inst.id, ("…", "…"))
            pub_ip     = cached[0]
            priv_ip    = cached[1] if len(cached) > 1 else "…"

            table.add_row(
                inst.display_name or "—",
                state_text,
                inst.shape or "—",
                ad,
                pub_ip,
                priv_ip,
                created,
                key=inst.id,
            )

        msg = f"Loaded {len(instances)} instance(s)" if instances else "No instances in compartment"
        self.notify(msg, timeout=3)

    def _update_ip_cell(self, instance_id: str, pub: str, priv: str = "—") -> None:
        if self._col_ip is None:
            return
        try:
            table = self.query_one("#instance-table", DataTable)
            table.update_cell(instance_id, self._col_ip,      pub,  update_width=True)
            table.update_cell(instance_id, self._col_priv_ip, priv, update_width=True)
        except Exception:
            pass  # row may not exist (compartment changed)

    def _set_status(self, msg: str) -> None:
        self.query_one("#status-label", Label).update(msg)

    # ── Row selection → detail panel ─────────────────────────────────────────

    @on(DataTable.RowHighlighted)
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key and event.row_key.value:
            inst = self._instance_map.get(event.row_key.value)
            if inst:
                self._refresh_detail_panel(inst)

    def _refresh_detail_panel(self, inst) -> None:
        state  = inst.lifecycle_state
        color  = STATE_STYLE.get(state, "white").replace("bold ", "")
        pub, priv = self._ip_cache.get(inst.id, ("…", "…"))
        ad     = _short_ad(inst.availability_domain)

        sc_info = ""
        if inst.shape_config and inst.shape_config.ocpus:
            cfg = inst.shape_config
            sc_info = f"  •  {cfg.ocpus:.0f} OCPU(s)  •  {cfg.memory_in_gbs:.0f} GB RAM"

        text = (
            f"[b]{inst.display_name}[/b]   "
            f"[{color}]{state}[/{color}]\n"
            f"[dim]{inst.id}[/dim]\n"
            f"{inst.shape}{sc_info}   {ad}   "
            f"pub [b]{pub}[/b]   priv [b]{priv}[/b]"
        )
        self.query_one("#detail-content", Static).update(text)

    # ── Key actions ───────────────────────────────────────────────────────────

    def _selected(self, require_state: Optional[str] = None):
        """Return the selected instance, or None with a warning."""
        if not self._instances:
            self.notify("No instances loaded", severity="warning")
            return None
        try:
            table    = self.query_one("#instance-table", DataTable)
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
            inst     = self._instance_map.get(cell_key.row_key.value)
        except Exception:
            inst = None

        if not inst:
            self.notify("No instance selected", severity="warning")
            return None
        if require_state and inst.lifecycle_state != require_state:
            self.notify(
                f"Instance must be {require_state} (currently {inst.lifecycle_state})",
                severity="warning",
            )
            return None
        return inst

    def action_refresh(self) -> None:
        self._load_instances()
        self._load_net_vnics()
        self._load_net_ips()
        self._load_reserved_public_ips()
        self._load_sec_lists()

    def action_details(self) -> None:
        inst = self._selected()
        if not inst:
            return
        self.push_screen(InstanceDetailScreen(inst, self._manager, self._ip_cache))

    def action_net_vnic_view(self) -> None:
        """Open VnicDetailScreen for the highlighted row in the Networking > VNICs table."""
        try:
            tbl     = self.query_one("#net-vnic-table", DataTable)
            vnic_id = tbl.coordinate_to_cell_key(tbl.cursor_coordinate).row_key.value
        except Exception:
            self.notify("Select a VNIC from the table first", severity="warning")
            return
        entry = next((e for e in self._net_vnics_cache if e["vnic"].id == vnic_id), None)
        if not entry:
            self.notify("VNIC not found in cache — try refreshing", severity="warning")
            return
        self.push_screen(VnicDetailScreen(entry["vnic"].id, entry["attachment"], self._manager))

    def action_change_compartment(self) -> None:
        if not self._manager:
            self.notify("OCI not initialized yet", severity="warning")
            return
        self._fetch_and_show_compartments()

    @work(thread=True, name="fetch_compartments")
    def _fetch_and_show_compartments(self) -> None:
        self.call_from_thread(self._set_status, "⟳  Loading compartments…")
        try:
            compartments = self._manager.list_compartments()
            self.call_from_thread(self._show_compartment_modal, compartments)
        except Exception as exc:
            self.call_from_thread(self.notify, f"Error: {exc}", severity="error")
        finally:
            self.call_from_thread(self._set_status, "")

    def _show_compartment_modal(self, compartments: list) -> None:
        def on_dismiss(result) -> None:
            if result:
                cid, name = result
                self._set_compartment(cid, name)

        self.push_screen(CompartmentModal(compartments), on_dismiss)

    # ── Power actions ─────────────────────────────────────────────────────────

    def action_start(self) -> None:
        inst = self._selected(require_state="STOPPED")
        if inst:
            self._power_action(inst, "START", "Starting")

    def action_stop(self) -> None:
        inst = self._selected(require_state="RUNNING")
        if not inst:
            return

        def on_confirm(ok: bool) -> None:
            if ok:
                self._power_action(inst, "SOFTSTOP", "Stopping")

        self.push_screen(
            ConfirmModal("Stop Instance", f"Gracefully stop [b]{inst.display_name}[/b]?", "Stop"),
            on_confirm,
        )

    def action_reboot(self) -> None:
        inst = self._selected(require_state="RUNNING")
        if not inst:
            return

        def on_confirm(ok: bool) -> None:
            if ok:
                self._power_action(inst, "SOFTRESET", "Rebooting")

        self.push_screen(
            ConfirmModal("Reboot Instance", f"Reboot [b]{inst.display_name}[/b]?", "Reboot"),
            on_confirm,
        )

    def action_terminate(self) -> None:
        inst = self._selected()
        if not inst:
            return

        def on_confirm(ok: bool) -> None:
            if ok:
                self._do_terminate(inst)

        self.push_screen(
            ConfirmModal(
                "⚠  Terminate Instance",
                f"Permanently delete [b]{inst.display_name}[/b]?\n\n"
                "[bold red]This cannot be undone.[/bold red]",
                "Terminate",
            ),
            on_confirm,
        )

    @work(thread=True)
    def _power_action(self, inst, action: str, verb: str) -> None:
        self.call_from_thread(self.notify, f"{verb} {inst.display_name}…", timeout=4)
        try:
            self._manager.instance_action(inst.id, action)
            self.call_from_thread(self.notify, f"{verb} initiated ✓", severity="information")
            time.sleep(3)
            self._refresh_after_action()
        except Exception as exc:
            self.call_from_thread(self.notify, f"Error: {exc}", severity="error")

    @work(thread=True)
    def _do_terminate(self, inst) -> None:
        self.call_from_thread(self.notify, f"Terminating {inst.display_name}…", timeout=4)
        try:
            self._manager.terminate_instance(inst.id)
            self.call_from_thread(self.notify, "Termination initiated ✓", severity="information")
            time.sleep(3)
            self._refresh_after_action()
        except Exception as exc:
            self.call_from_thread(self.notify, f"Error: {exc}", severity="error")

    def _refresh_after_action(self) -> None:
        """Reload instances from current thread (already a worker)."""
        try:
            instances = self._manager.list_instances(self._compartment_id)
            self.call_from_thread(self._populate_table, instances)
        except Exception as exc:
            self.call_from_thread(self.notify, f"Refresh error: {exc}", severity="error")

    # ── Launch ────────────────────────────────────────────────────────────────

    def action_launch(self) -> None:
        if not self._manager or not self._compartment_id:
            self.notify("OCI not initialized yet", severity="warning")
            return
        self._fetch_launch_data()

    @work(thread=True, name="fetch_launch_data")
    def _fetch_launch_data(self) -> None:
        self.call_from_thread(self._set_status, "⟳  Loading launch data…")
        try:
            shapes  = self._manager.list_shapes(self._compartment_id)
            images  = self._manager.list_images(self._compartment_id)
            ads     = self._manager.list_availability_domains()
            subnets = self._manager.list_subnets(self._compartment_id)
            self.call_from_thread(self._show_launch_modal, shapes, images, ads, subnets)
        except Exception as exc:
            self.call_from_thread(self.notify, f"Error loading launch data: {exc}", severity="error")
        finally:
            self.call_from_thread(self._set_status, "")

    def _show_launch_modal(self, shapes, images, ads, subnets) -> None:
        def on_dismiss(details) -> None:
            if details:
                self._do_launch(details)

        self.push_screen(
            LaunchModal(self._compartment_id, shapes, images, ads, subnets),
            on_dismiss,
        )

    @work(thread=True)
    def _do_launch(self, details: dict) -> None:
        name = details.get("display_name", "new instance")
        self.call_from_thread(self.notify, f"Launching {name}…", timeout=6)
        try:
            self._manager.launch_instance(details)
            self.call_from_thread(self.notify, "Instance launched ✓", severity="information")
            time.sleep(4)
            self._refresh_after_action()
        except Exception as exc:
            self.call_from_thread(self.notify, f"Launch error: {exc}", severity="error")

    # ── Networking tab ────────────────────────────────────────────────────────

    @work(thread=True, name="load_net_vnics")
    def _load_net_vnics(self) -> None:
        if not self._manager or not self._compartment_id:
            return
        try:
            vnics = self._manager.list_all_vnics(self._compartment_id)
            self.call_from_thread(self._populate_net_vnics, vnics)
        except Exception as exc:
            self.call_from_thread(self.notify, f"VNIC load error: {exc}", severity="error")

    def _populate_net_vnics(self, vnics: list) -> None:
        self._net_vnics_cache = vnics          # cache for open-detail action
        tbl = self.query_one("#net-vnic-table", DataTable)
        tbl.clear()
        for entry in vnics:
            v   = entry["vnic"]
            att = entry["attachment"]
            st  = Text(v.lifecycle_state, style=STATE_STYLE.get(v.lifecycle_state, "white"))
            tbl.add_row(
                v.display_name or "—",
                st,
                "Yes" if v.is_primary else "No",
                entry["subnet_name"],
                v.private_ip or "—",
                v.public_ip  or "—",
                v.mac_address or "—",
                att.instance_id[-12:],
                key=v.id,
            )

    @work(thread=True, name="load_net_ips")
    def _load_net_ips(self) -> None:
        if not self._manager or not self._compartment_id:
            return
        try:
            mappings = self._manager.list_ip_mappings(self._compartment_id)
            self.call_from_thread(self._populate_net_ips, mappings)
        except Exception as exc:
            self.call_from_thread(self.notify, f"IP load error: {exc}", severity="error")

    def _populate_net_ips(self, mappings: list) -> None:
        def _fmt_dt(dt) -> str:
            return dt.strftime("%Y-%m-%d %H:%M") if dt else "—"

        tbl = self.query_one("#net-ip-table", DataTable)
        tbl.clear()
        for m in mappings:
            pip = m["private_ip"]
            pub = m["public_ip"]
            priv_label = pip.ip_address + (" (Primary)" if pip.is_primary else "")
            pub_label  = pub.ip_address if pub else "—"
            lifetime   = pub.lifetime if pub else "—"
            tbl.add_row(
                priv_label,
                pub_label,
                lifetime,
                m["instance_name"],
                m["subnet_name"],
                _fmt_dt(pip.time_created),
                key=pip.id,
            )

    @work(thread=True, name="load_reserved_public_ips")
    def _load_reserved_public_ips(self) -> None:
        if not self._manager or not self._compartment_id:
            return
        try:
            reserved_ips = self._manager.list_reserved_public_ips(self._compartment_id)
            self.call_from_thread(self._populate_reserved_public_ips, reserved_ips)
        except Exception as exc:
            self.call_from_thread(self.notify, f"Reserved public IP load error: {exc}", severity="error")

    def _reserved_ip_attachment_status(self, entry: dict) -> str:
        public_ip = entry["public_ip"]
        private_ip = entry["private_ip"]
        if public_ip.assigned_entity_type == "PRIVATE_IP":
            if private_ip and getattr(private_ip, "ip_address", None):
                return f"Assigned to {private_ip.ip_address}"
            return "Assigned to private IP"
        if public_ip.assigned_entity_type == "NAT_GATEWAY":
            return "Assigned to NAT gateway"
        if public_ip.lifecycle_state in ("ASSIGNING", "UNASSIGNING"):
            return "Updating assignment…"
        return "Unassigned"

    def _sort_reserved_public_ips(self, reserved_ips: list) -> list:
        reverse = self._reserved_public_ip_sort.endswith("_desc")
        field = self._reserved_public_ip_sort.rsplit("_", 1)[0]

        def _name(entry: dict) -> str:
            return (entry["public_ip"].display_name or "").casefold()

        def _created(entry: dict):
            return entry["public_ip"].time_created or 0

        def _ip(entry: dict):
            addr = entry["public_ip"].ip_address
            if not addr:
                return (1, "")
            try:
                return (0, ip_address(addr))
            except ValueError:
                return (0, addr)

        key_map = {
            "created": _created,
            "ip": _ip,
            "name": _name,
        }
        return sorted(reserved_ips, key=key_map[field], reverse=reverse)

    def _populate_reserved_public_ips(self, reserved_ips: list) -> None:
        def _fmt_dt(dt) -> str:
            return dt.strftime("%Y-%m-%d %H:%M") if dt else "—"

        tbl = self.query_one("#net-reserved-public-ip-table", DataTable)
        selected_id = self._reserved_public_ip_selected_id
        try:
            row_key = tbl.coordinate_to_cell_key(tbl.cursor_coordinate).row_key
            if row_key and row_key.value:
                selected_id = row_key.value
        except Exception:
            pass

        self._reserved_public_ips = self._sort_reserved_public_ips(reserved_ips)
        tbl.clear()
        for entry in self._reserved_public_ips:
            public_ip = entry["public_ip"]
            tbl.add_row(
                public_ip.display_name or "—",
                public_ip.ip_address or "—",
                self._reserved_ip_attachment_status(entry),
                _fmt_dt(public_ip.time_created),
                key=public_ip.id,
            )
        self._restore_reserved_public_ip_selection(selected_id)

    def _restore_reserved_public_ip_selection(self, public_ip_id: Optional[str]) -> None:
        if not self._reserved_public_ips:
            self._reserved_public_ip_selected_id = None
            return

        row_index = 0
        selected_id = public_ip_id
        if selected_id:
            for idx, entry in enumerate(self._reserved_public_ips):
                if entry["public_ip"].id == selected_id:
                    row_index = idx
                    break
            else:
                selected_id = None

        if selected_id is None:
            selected_id = self._reserved_public_ips[0]["public_ip"].id

        self._reserved_public_ip_selected_id = selected_id
        try:
            self.query_one("#net-reserved-public-ip-table", DataTable).move_cursor(row=row_index, column=0)
        except Exception:
            pass

    def _reserved_public_ip_tab_active(self) -> bool:
        try:
            return self.query_one("#net-tabs", TabbedContent).active == "tab-net-reserved-ips"
        except Exception:
            return False

    def _selected_reserved_public_ip(self):
        try:
            tbl = self.query_one("#net-reserved-public-ip-table", DataTable)
            public_ip_id = tbl.coordinate_to_cell_key(tbl.cursor_coordinate).row_key.value
        except Exception:
            self.notify("Select a reserved public IP first", severity="warning")
            return None
        entry = next(
            (item for item in self._reserved_public_ips if item["public_ip"].id == public_ip_id),
            None,
        )
        if not entry:
            self.notify("Reserved public IP not found in cache — try again", severity="warning")
            return None
        self._reserved_public_ip_selected_id = public_ip_id
        return entry

    def action_reserve_public_ip(self) -> None:
        if not self._reserved_public_ip_tab_active():
            self.notify("Open Networking > Reserved Public IPs first", severity="warning")
            return
        if not self._manager or not self._compartment_id:
            self.notify("OCI not initialized yet", severity="warning")
            return

        def on_dismiss(name: Optional[str]) -> None:
            if name is not None:
                self._do_create_reserved_public_ip(name)

        self.push_screen(
            PublicIpNameModal("Reserve New Public IP", "Reserve"),
            on_dismiss,
        )

    @work(thread=True, name="create_reserved_public_ip")
    def _do_create_reserved_public_ip(self, display_name: str) -> None:
        self.call_from_thread(self.notify, "Reserving public IP…", timeout=4)
        try:
            created = self._manager.create_reserved_public_ip(self._compartment_id, display_name)
            self._reserved_public_ip_selected_id = created.id
            self.call_from_thread(self.notify, "Reserved public IP created ✓", severity="information")
            time.sleep(2)
            self._load_reserved_public_ips()
        except Exception as exc:
            self.call_from_thread(self.notify, f"Reserve public IP error: {exc}", severity="error")

    def action_edit_reserved_public_ip(self) -> None:
        if not self._reserved_public_ip_tab_active():
            self.notify("Open Networking > Reserved Public IPs first", severity="warning")
            return
        entry = self._selected_reserved_public_ip()
        if not entry:
            return
        public_ip = entry["public_ip"]

        def on_dismiss(name: Optional[str]) -> None:
            if name is not None:
                self._do_rename_reserved_public_ip(public_ip.id, name)

        self.push_screen(
            PublicIpNameModal(
                "Edit Public IP Name",
                "Save",
                initial_value=public_ip.display_name or "",
            ),
            on_dismiss,
        )

    @work(thread=True, name="rename_reserved_public_ip")
    def _do_rename_reserved_public_ip(self, public_ip_id: str, display_name: str) -> None:
        self.call_from_thread(self.notify, "Updating public IP name…", timeout=4)
        try:
            self._manager.update_public_ip_name(public_ip_id, display_name)
            self._reserved_public_ip_selected_id = public_ip_id
            self.call_from_thread(self.notify, "Reserved public IP updated ✓", severity="information")
            time.sleep(1)
            self._load_reserved_public_ips()
        except Exception as exc:
            self.call_from_thread(self.notify, f"Update public IP error: {exc}", severity="error")

    def action_delete_reserved_public_ip(self) -> None:
        if not self._reserved_public_ip_tab_active():
            self.notify("Open Networking > Reserved Public IPs first", severity="warning")
            return
        entry = self._selected_reserved_public_ip()
        if not entry:
            return
        public_ip = entry["public_ip"]
        label = public_ip.display_name or public_ip.ip_address or public_ip.id[-12:]

        def on_confirm(ok: bool) -> None:
            if ok:
                self._do_delete_reserved_public_ip(public_ip.id, label)

        self.push_screen(
            ConfirmModal(
                "Delete Reserved Public IP",
                f"Delete [b]{label}[/b] ({public_ip.ip_address or 'pending address'})?",
                "Delete",
            ),
            on_confirm,
        )

    @work(thread=True, name="delete_reserved_public_ip")
    def _do_delete_reserved_public_ip(self, public_ip_id: str, label: str) -> None:
        self.call_from_thread(self.notify, f"Deleting {label}…", timeout=4)
        try:
            remaining_ids = [
                entry["public_ip"].id
                for entry in self._reserved_public_ips
                if entry["public_ip"].id != public_ip_id
            ]
            self._reserved_public_ip_selected_id = remaining_ids[0] if remaining_ids else None
            self._manager.delete_public_ip(public_ip_id)
            self.call_from_thread(self.notify, "Reserved public IP deleted ✓", severity="information")
            time.sleep(2)
            self._load_reserved_public_ips()
        except Exception as exc:
            self.call_from_thread(self.notify, f"Delete public IP error: {exc}", severity="error")

    @on(Select.Changed, "#reserved-public-ip-sort")
    def on_reserved_public_ip_sort_changed(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return
        self._reserved_public_ip_sort = str(event.value)
        self._load_reserved_public_ips()

    @on(DataTable.RowHighlighted, "#net-reserved-public-ip-table")
    def on_reserved_public_ip_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key and event.row_key.value:
            self._reserved_public_ip_selected_id = event.row_key.value

    # ── Security Lists ────────────────────────────────────────────────────────

    @work(thread=True, name="load_sec_lists")
    def _load_sec_lists(self) -> None:
        if not self._manager or not self._compartment_id:
            return
        try:
            sl_list = self._manager.list_security_lists(self._compartment_id)
            self.call_from_thread(self._populate_sec_lists, sl_list)
        except Exception as exc:
            self.call_from_thread(self.notify, f"Security list load error: {exc}", severity="error")

    def _populate_sec_lists(self, sl_list: list) -> None:
        self._sec_lists   = sl_list
        self._sec_list_map = {sl.id: sl for sl in sl_list}

        tbl = self.query_one("#seclist-table", DataTable)
        tbl.clear()
        for sl in sl_list:
            # Each SL has ingress_security_rules / egress_security_rules lists
            n_in  = len(sl.ingress_security_rules or [])
            n_eg  = len(sl.egress_security_rules  or [])
            vcn_id_short = sl.vcn_id[-12:] if sl.vcn_id else "—"
            st = Text(sl.lifecycle_state, style=STATE_STYLE.get(sl.lifecycle_state, "white"))
            tbl.add_row(sl.display_name or "—", st, vcn_id_short, str(n_in), str(n_eg), key=sl.id)

    @on(DataTable.RowHighlighted, "#seclist-table")
    def on_seclist_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key and event.row_key.value:
            sl = self._sec_list_map.get(event.row_key.value)
            if sl:
                self._cur_sec_list = sl
                self._show_sec_rules(sl)

    def _show_sec_rules(self, sl) -> None:
        def _proto(p) -> str:
            return {"6": "TCP", "17": "UDP", "1": "ICMP", "all": "All Protocols"}.get(str(p), str(p))

        def _port(opts) -> tuple:
            if not opts:
                return ("All", "All")
            src = opts.source_port_range
            dst = opts.destination_port_range if hasattr(opts, "destination_port_range") else None
            def _fmt(r):
                if r is None:
                    return "All"
                return str(r.min) if r.min == r.max else f"{r.min}-{r.max}"
            return (_fmt(src), _fmt(dst))

        def _icmp(r) -> str:
            io = r.icmp_options
            if not io:
                return "—"
            return f"{io.type}, {io.code}" if io.code is not None else str(io.type)

        ig = self.query_one("#ingress-table", DataTable)
        ig.clear()
        for r in (sl.ingress_security_rules or []):
            proto = _proto(r.protocol)
            tcp_o = r.tcp_options if proto in ("TCP", "All Protocols") else (r.udp_options if proto == "UDP" else None)
            src_p, dst_p = _port(tcp_o)
            ig.add_row(
                "Yes" if r.is_stateless else "No",
                r.source,
                proto,
                src_p, dst_p,
                _icmp(r),
                r.description or "—",
            )

        eg = self.query_one("#egress-table", DataTable)
        eg.clear()
        for r in (sl.egress_security_rules or []):
            proto = _proto(r.protocol)
            tcp_o = r.tcp_options if proto in ("TCP", "All Protocols") else (r.udp_options if proto == "UDP" else None)
            src_p, dst_p = _port(tcp_o)
            eg.add_row(
                "Yes" if r.is_stateless else "No",
                r.destination,
                proto,
                src_p, dst_p,
                _icmp(r),
                r.description or "—",
            )

    def action_seclist_add_ingress(self) -> None:
        if not self._cur_sec_list:
            self.notify("Select a security list first", severity="warning")
            return
        self.push_screen(SecurityRuleModal(direction="ingress"), self._on_ingress_rule)

    def action_seclist_edit_ingress(self) -> None:
        if not self._cur_sec_list:
            self.notify("Select a security list first", severity="warning")
            return
        try:
            tbl = self.query_one("#ingress-table", DataTable)
            idx = tbl.cursor_row
            rule = (self._cur_sec_list.ingress_security_rules or [])[idx]
        except (Exception, IndexError):
            self.notify("Select an ingress rule row first", severity="warning")
            return
        self.push_screen(
            SecurityRuleModal(direction="ingress", existing_rule=rule, rule_index=idx),
            self._on_ingress_rule,
        )

    def _on_ingress_rule(self, rule_dict) -> None:
        if not rule_dict or not self._cur_sec_list:
            return
        sl   = self._cur_sec_list
        rule_dict = _expand_port_range(rule_dict)
        rule_dict["source"] = rule_dict.pop("cidr", "")
        rule = self._manager.build_ingress_rule(rule_dict)
        rules = list(sl.ingress_security_rules or [])
        idx   = rule_dict.get("rule_index", -1)
        if idx >= 0 and idx < len(rules):
            rules[idx] = rule          # edit in place
        else:
            rules.append(rule)         # new rule
        self._save_sec_rules(sl.id, rules, sl.egress_security_rules or [])

    def action_seclist_add_egress(self) -> None:
        if not self._cur_sec_list:
            self.notify("Select a security list first", severity="warning")
            return
        self.push_screen(SecurityRuleModal(direction="egress"), self._on_egress_rule)

    def action_seclist_edit_egress(self) -> None:
        if not self._cur_sec_list:
            self.notify("Select a security list first", severity="warning")
            return
        try:
            tbl = self.query_one("#egress-table", DataTable)
            idx = tbl.cursor_row
            rule = (self._cur_sec_list.egress_security_rules or [])[idx]
        except (Exception, IndexError):
            self.notify("Select an egress rule row first", severity="warning")
            return
        self.push_screen(
            SecurityRuleModal(direction="egress", existing_rule=rule, rule_index=idx),
            self._on_egress_rule,
        )

    def _on_egress_rule(self, rule_dict) -> None:
        if not rule_dict or not self._cur_sec_list:
            return
        sl   = self._cur_sec_list
        rule_dict = _expand_port_range(rule_dict)
        rule_dict["destination"] = rule_dict.pop("cidr", "")
        rule = self._manager.build_egress_rule(rule_dict)
        rules = list(sl.egress_security_rules or [])
        idx   = rule_dict.get("rule_index", -1)
        if idx >= 0 and idx < len(rules):
            rules[idx] = rule
        else:
            rules.append(rule)
        self._save_sec_rules(sl.id, sl.ingress_security_rules or [], rules)


    def action_seclist_del_ingress(self) -> None:
        self._delete_sec_rule("ingress")

    def action_seclist_del_egress(self) -> None:
        self._delete_sec_rule("egress")

    def _delete_sec_rule(self, direction: str) -> None:
        if not self._cur_sec_list:
            self.notify("Select a security list first", severity="warning")
            return
        table_id = "#ingress-table" if direction == "ingress" else "#egress-table"
        try:
            tbl = self.query_one(table_id, DataTable)
            idx = tbl.cursor_row
        except Exception:
            self.notify("Select a rule row first", severity="warning")
            return

        sl = self._cur_sec_list
        if direction == "ingress":
            rules = list(sl.ingress_security_rules or [])
            if idx >= len(rules):
                return
            rules.pop(idx)
            self._save_sec_rules(sl.id, rules, sl.egress_security_rules or [])
        else:
            rules = list(sl.egress_security_rules or [])
            if idx >= len(rules):
                return
            rules.pop(idx)
            self._save_sec_rules(sl.id, sl.ingress_security_rules or [], rules)

    @work(thread=True, name="save_sec_rules")
    def _save_sec_rules(self, sl_id: str, ingress: list, egress: list) -> None:
        self.call_from_thread(self._set_status, "⟳  Saving rules…")
        try:
            updated = self._manager.update_security_list_rules(sl_id, ingress, egress)
            self._sec_list_map[sl_id] = updated
            self._cur_sec_list        = updated
            # patch in-place in list
            for i, sl in enumerate(self._sec_lists):
                if sl.id == sl_id:
                    self._sec_lists[i] = updated
                    break
            self.call_from_thread(self._populate_sec_lists, self._sec_lists)
            self.call_from_thread(self._show_sec_rules, updated)
            self.call_from_thread(self.notify, "Security rules saved ✓", severity="information")
        except Exception as exc:
            self.call_from_thread(self.notify, f"Save error: {exc}", severity="error")
        finally:
            self.call_from_thread(self._set_status, "")
