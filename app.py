"""OCI TUI — Oracle Cloud Infrastructure terminal manager (Textual)."""

from __future__ import annotations

import time
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
    Static,
    TabbedContent,
    TabPane,
)

from common import STATE_STYLE, _short_ad, _expand_port_range
from modals import CompartmentModal, ConfirmModal, SecurityRuleModal
from launch_modal import LaunchModal
from instance_detail import InstanceDetailScreen
from vnic_detail import VnicDetailScreen


# ── Main App ──────────────────────────────────────────────────────────────────

class OCIApp(App):
    """OCI TUI — manage Oracle Cloud compute instances from your terminal."""

    TITLE = "OCI TUI"
    CSS_PATH = "oci_tui.tcss"

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

        # Security list tables
        st = self.query_one("#seclist-table", DataTable)
        st.add_columns("Name", "State", "VCN", "Ingress Rules", "Egress Rules")

        ig = self.query_one("#ingress-table", DataTable)
        ig.add_columns("Stateless", "Source", "Protocol", "Src Port", "Dst Port", "ICMP", "Description")

        eg = self.query_one("#egress-table", DataTable)
        eg.add_columns("Stateless", "Destination", "Protocol", "Src Port", "Dst Port", "ICMP", "Description")

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
