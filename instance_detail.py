from __future__ import annotations

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static, TabbedContent, TabPane

from common import STATE_STYLE, _kv, _kv_long, _sec, _short_ad
from modals import CopyModal, ConfirmModal
from vnic_modals import AttachVnicModal, EditVnicModal
from vnic_detail import VnicDetailScreen

class InstanceDetailScreen(Screen):
    """Full-screen tabbed instance details (Details, Networking)."""

    BINDINGS = [
        Binding("escape,q", "app.pop_screen", "Back"),
        Binding("1", "show_tab('tab-details')",    "Details",    show=False),
        Binding("2", "show_tab('tab-networking')", "Networking", show=False),
        Binding("3", "show_tab('tab-storage')",    "Storage",    show=False),
        Binding("4", "show_tab('tab-console')",    "Console",    show=False),
        Binding("a", "vnic_add",    "Add VNIC",    show=False),
        Binding("e", "vnic_edit",   "Edit VNIC",   show=False),
        Binding("d", "vnic_detach", "Detach VNIC", show=False),
        Binding("v", "vnic_view",   "View VNIC",   show=False),
    ]

    def __init__(self, instance, manager, ip_cache: dict) -> None:
        super().__init__()
        self._inst       = instance
        self._mgr        = manager
        self._ip_cache   = ip_cache
        self._net_details: list = []  # cached VNIC detail dicts
        self._long_vals:  dict  = {}  # field_id → full string for CopyModal

    # ── Layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        inst  = self._inst
        state = inst.lifecycle_state
        col   = STATE_STYLE.get(state, "white").replace("bold ", "")
        pub   = self._ip_cache.get(inst.id, ("—",))[0]

        yield Header()
        yield Static(
            f" [b]{inst.display_name}[/b]   "
            f"[{col}]● {state}[/{col}]   "
            f"[dim]{inst.region}  ·  {_short_ad(inst.availability_domain)}  ·  {pub}[/dim]",
            id="inst-header",
            markup=True,
        )
        with TabbedContent(id="detail-tabs"):
            with TabPane("Details", id="tab-details"):
                with ScrollableContainer(id="details-scroll"):
                    yield Static("", id="sec-general",  markup=True)
                    yield Static("", id="sec-shape",    markup=True)
                    yield Static("[dim]  Loading image details…[/dim]", id="sec-image",   markup=True)
                    yield Static("", id="sec-options",  markup=True)

            with TabPane("Networking", id="tab-networking"):
                with ScrollableContainer(id="net-scroll"):
                    yield Static("[dim]  Loading networking…[/dim]", id="sec-primary-vnic", markup=True)
                    yield Static(_sec("Attached VNICs"), id="sec-vnic-title", markup=True)
                    yield DataTable(id="vnic-table", cursor_type="row", zebra_stripes=True)

            with TabPane("Storage", id="tab-storage"):
                with ScrollableContainer(id="storage-scroll"):
                    yield Static("[dim]  Loading storage…[/dim]", id="sec-boot-vol-hdr", markup=True)
                    yield DataTable(id="boot-vol-table", cursor_type="row", zebra_stripes=True)
                    yield Static(_sec("Attached Block Volumes"), id="sec-block-vol-hdr", markup=True)
                    yield DataTable(id="block-vol-table", cursor_type="row", zebra_stripes=True)

            with TabPane("Console", id="tab-console"):
                with ScrollableContainer(id="console-scroll"):
                    yield Static("[dim]  Loading console connections…[/dim]", id="sec-console", markup=True)

        yield Footer()

    def on_mount(self) -> None:
        tbl = self.query_one("#vnic-table", DataTable)
        tbl.add_columns("Name", "Subnet", "VCN", "State", "Route Table", "VLAN Tag", "MAC Address")

        bvt = self.query_one("#boot-vol-table", DataTable)
        bvt.add_columns("Name", "State", "Size", "In-transit Enc.", "Created", "Attached", "Image")

        blkt = self.query_one("#block-vol-table", DataTable)
        blkt.add_columns("Name", "State", "Type", "Device", "Access", "Size", "VPU", "Multipath")

        self._populate_static_sections()
        self._load_image()
        self._load_networking()
        self._load_storage()
        self._load_console()

    # ── Details tab ───────────────────────────────────────────────────────────

    def _populate_static_sections(self) -> None:
        inst      = self._inst
        pub, priv = self._ip_cache.get(inst.id, ("—", "—"))
        state     = inst.lifecycle_state
        col       = STATE_STYLE.get(state, "white").replace("bold ", "")
        created   = inst.time_created.strftime("%b %d, %Y, %H:%M:%S UTC") if inst.time_created else "—"

        # ── General Information
        lv = self._long_vals
        self.query_one("#sec-general", Static).update(
            _sec("General Information")
            + _kv("Availability Domain", inst.availability_domain)
            + _kv("Fault Domain",        inst.fault_domain or "—")
            + _kv("Region",              inst.region)
            + _kv_long("OCID",           inst.id,               "inst_ocid",    lv)
            + _kv("Launched",            created)
            + _kv_long("Compartment",    inst.compartment_id,   "inst_comp",    lv)
            + _kv("Capacity Type",       "On-demand")
            + _kv("State",              f"[{col}]● {state}[/{col}]")
            + _kv("Public IP",           pub)
            + _kv("Private IP",          priv)
        )

        # ── Shape Configuration
        cfg        = inst.shape_config
        shape_text = _sec("Shape Configuration") + _kv("Shape", inst.shape)
        if cfg:
            if cfg.ocpus:
                shape_text += _kv("OCPU Count",               f"{cfg.ocpus:.0f}")
            if cfg.memory_in_gbs:
                shape_text += _kv("Memory (GB)",              f"{cfg.memory_in_gbs:.0f}")
            if cfg.networking_bandwidth_in_gbps:
                shape_text += _kv("Network Bandwidth (Gbps)", f"{cfg.networking_bandwidth_in_gbps:.1f}")
            if cfg.gpus:
                shape_text += _kv("GPUs",                     f"{cfg.gpus}")
            shape_text += _kv("Local Disk", "Block storage only")
        self.query_one("#sec-shape", Static).update(shape_text)

        # ── Instance Options
        meta_keys = list((inst.metadata or {}).keys())
        self.query_one("#sec-options", Static).update(
            _sec("Instance Options")
            + _kv("Launch Mode",    inst.launch_mode or "—")
            + _kv("IMDS Versions",  "v1 and v2")
            + (_kv("Metadata Keys", ", ".join(meta_keys)) if meta_keys else "")
        )

    @work(thread=True, name="load_image")
    def _load_image(self) -> None:
        if not self._inst.image_id:
            self.app.call_from_thread(
                self.query_one("#sec-image", Static).update,
                _sec("Image Details") + "  [dim]No image attached[/dim]\n",
            )
            return
        try:
            image = self._mgr.get_image(self._inst.image_id)
            self.app.call_from_thread(self._populate_image_section, image)
        except Exception as exc:
            self.app.call_from_thread(
                self.query_one("#sec-image", Static).update,
                _sec("Image Details") + f"  [red]Error: {exc}[/red]\n",
            )

    def _populate_image_section(self, image) -> None:
        if not image:
            self.query_one("#sec-image", Static).update(
                _sec("Image Details") + "  [dim]Image not found[/dim]\n"
            )
            return

        lv   = self._long_vals
        text = (
            _sec("Image Details")
            + _kv("Operating System", image.operating_system)
            + _kv("Version",          image.operating_system_version)
            + _kv("Image",            image.display_name)
            + _kv_long("Image OCID",  image.id, "image_ocid", lv)
        )

        lo = image.launch_options
        if lo:
            enc = getattr(lo, "is_pv_encryption_in_transit_enabled", None)
            sb  = getattr(lo, "is_secure_boot_enabled", None)
            text += (
                _sec("Launch Options")
                + _kv("NIC Attachment Type",   lo.network_type              or "—")
                + _kv("Remote Data Volume",    lo.remote_data_volume_type   or "—")
                + _kv("Firmware",              lo.firmware                  or "—")
                + _kv("Boot Volume Type",      lo.boot_volume_type          or "—")
                + _kv("In-transit Encryption", "Enabled" if enc  else "Disabled")
                + _kv("Secure Boot",           "Enabled" if sb   else "Disabled")
            )

        self.query_one("#sec-image", Static).update(text)

    # ── Networking tab ────────────────────────────────────────────────────────

    @work(thread=True, name="load_networking")
    def _load_networking(self) -> None:
        try:
            details = self._mgr.get_instance_network_details(
                self._inst.compartment_id, self._inst.id
            )
            self.app.call_from_thread(self._populate_networking, details)
        except Exception as exc:
            self.app.call_from_thread(
                self.query_one("#sec-primary-vnic", Static).update,
                _sec("Primary VNIC") + f"  [red]Error: {exc}[/red]\n",
            )

    def _populate_networking(self, details: list) -> None:
        self._net_details = details
        if not details:
            self.query_one("#sec-primary-vnic", Static).update(
                _sec("Primary VNIC") + "  [dim]No VNICs attached[/dim]\n"
            )
            return

        primary = next((d for d in details if d["vnic"].is_primary), details[0])
        v   = primary["vnic"]
        att = primary["attachment"]
        sn  = primary["subnet"]
        vc  = primary["vcn"]
        rt  = primary["route_table"]

        sn_name = sn.display_name if sn else (v.subnet_id or "—")
        vc_name = vc.display_name if vc else "—"
        rt_name = rt.display_name if rt else "—"

        # Build internal FQDN
        fqdn = "—"
        if v.hostname_label and sn and vc:
            s_dns = getattr(sn, "dns_label", None)
            v_dns = getattr(vc, "dns_label", None)
            if s_dns and v_dns:
                fqdn = f"{v.hostname_label}.{s_dns}.{v_dns}.oraclevcn.com"

        nsg_text = (", ".join(v.nsg_ids) if v.nsg_ids else "None")
        priv_dns = "Disabled" if getattr(sn, "prohibit_internet_ingress", False) else "Enabled"

        lv = self._long_vals
        self.query_one("#sec-primary-vnic", Static).update(
            _sec("Primary VNIC")
            + _kv("Public IPv4",           v.public_ip   or "—")
            + _kv("Private IPv4",          v.private_ip  or "—")
            + _kv("VCN",                   vc_name)
            + _kv("Subnet",                sn_name)
            + _kv("Route Table",           rt_name)
            + _kv("Private DNS",           priv_dns)
            + _kv("Hostname",              v.hostname_label or "—")
            + _kv("Internal FQDN",         fqdn)
            + _kv("MAC Address",           v.mac_address or "—")
            + _kv("VLAN Tag",              str(att.vlan_tag) if att.vlan_tag is not None else "—")
            + _kv_long("VNIC OCID",        v.id,            "primary_vnic_ocid", lv)
            + _kv("Network Sec. Groups",   nsg_text)
        )

        # Populate attached VNICs table
        tbl = self.query_one("#vnic-table", DataTable)
        tbl.clear()
        for d in details:
            vnic = d["vnic"]
            att  = d["attachment"]
            name = (vnic.display_name or "—") + (" (Primary)" if vnic.is_primary else "")
            sn_n = d["subnet"].display_name if d["subnet"] else "—"
            vc_n = d["vcn"].display_name    if d["vcn"]    else "—"
            rt_n = d["route_table"].display_name if d["route_table"] else "—"
            st   = Text(att.lifecycle_state, style=STATE_STYLE.get(att.lifecycle_state, "white"))
            tbl.add_row(
                name, sn_n, vc_n, st, rt_n,
                str(att.vlan_tag) if att.vlan_tag is not None else "—",
                vnic.mac_address or "—",
                key=vnic.id,
            )

    def action_reveal(self, field_id: str) -> None:
        val = self._long_vals.get(field_id, "")
        self.app.push_screen(CopyModal(field_id.replace("_", " ").title(), val))

    def action_show_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    # ── VNIC actions (Networking tab) ─────────────────────────────────────────

    def _selected_vnic_entry(self):
        """Return the net_details dict for the highlighted VNIC row, or None."""
        try:
            tbl      = self.query_one("#vnic-table", DataTable)
            cell_key = tbl.coordinate_to_cell_key(tbl.cursor_coordinate)
            vnic_id  = cell_key.row_key.value
            return next((d for d in self._net_details if d["vnic"].id == vnic_id), None)
        except Exception:
            return None

    def action_vnic_view(self) -> None:
        entry = self._selected_vnic_entry()
        if not entry:
            self.notify("Select a VNIC from the table first", severity="warning")
            return
        self.app.push_screen(
            VnicDetailScreen(entry["vnic"].id, entry["attachment"], self._mgr)
        )

    def action_vnic_add(self) -> None:
        self._fetch_vnic_add_data()

    @work(thread=True, name="fetch_vnic_add_data")
    def _fetch_vnic_add_data(self) -> None:
        self.app.call_from_thread(self.notify, "Loading subnets…", timeout=3)
        try:
            subnets = self._mgr.list_subnets(self._inst.compartment_id)
            nsgs    = self._mgr.list_nsgs(self._inst.compartment_id)
            self.app.call_from_thread(self._show_attach_modal, subnets, nsgs)
        except Exception as exc:
            self.app.call_from_thread(self.notify, f"Error: {exc}", severity="error")

    def _show_attach_modal(self, subnets: list, nsgs: list) -> None:
        def on_dismiss(details) -> None:
            if details:
                self._do_vnic_connect(details)

        self.app.push_screen(AttachVnicModal(subnets, nsgs), on_dismiss)

    @work(thread=True, name="vnic_connect")
    def _do_vnic_connect(self, details: dict) -> None:
        self.app.call_from_thread(self.notify, "Attaching VNIC…", timeout=6)
        try:
            self._mgr.vnic_connect(self._inst.id, details)
            self.app.call_from_thread(self.notify, "VNIC attached ✓", severity="information")
            self._load_networking()
        except Exception as exc:
            self.app.call_from_thread(self.notify, f"Error: {exc}", severity="error")

    def action_vnic_edit(self) -> None:
        entry = self._selected_vnic_entry()
        if not entry:
            self.notify("Select a VNIC from the table first", severity="warning")
            return
        self._fetch_vnic_edit_data(entry["vnic"])

    @work(thread=True, name="fetch_vnic_edit_data")
    def _fetch_vnic_edit_data(self, vnic) -> None:
        try:
            nsgs = self._mgr.list_nsgs(self._inst.compartment_id)
            self.app.call_from_thread(self._show_edit_modal, vnic, nsgs)
        except Exception as exc:
            self.app.call_from_thread(self.notify, f"Error: {exc}", severity="error")

    def _show_edit_modal(self, vnic, nsgs: list) -> None:
        def on_dismiss(details) -> None:
            if details:
                self._do_vnic_update(vnic.id, details)

        self.app.push_screen(EditVnicModal(vnic, nsgs), on_dismiss)

    @work(thread=True, name="vnic_update")
    def _do_vnic_update(self, vnic_id: str, details: dict) -> None:
        self.app.call_from_thread(self.notify, "Updating VNIC…", timeout=6)
        try:
            self._mgr.update_vnic(vnic_id, details)
            self.app.call_from_thread(self.notify, "VNIC updated ✓", severity="information")
            self._load_networking()
        except Exception as exc:
            self.app.call_from_thread(self.notify, f"Error: {exc}", severity="error")

    def action_vnic_detach(self) -> None:
        entry = self._selected_vnic_entry()
        if not entry:
            self.notify("Select a VNIC from the table first", severity="warning")
            return
        vnic = entry["vnic"]
        att  = entry["attachment"]
        if vnic.is_primary:
            self.notify("Cannot detach the primary VNIC", severity="warning")
            return

        def on_confirm(ok: bool) -> None:
            if ok:
                self._do_vnic_detach(att.id)

        self.app.push_screen(
            ConfirmModal(
                "Detach VNIC",
                f"Detach [b]{vnic.display_name or vnic.id[-12:]}[/b] from this instance?",
                "Detach",
            ),
            on_confirm,
        )

    @work(thread=True, name="vnic_detach")
    def _do_vnic_detach(self, att_id: str) -> None:
        self.app.call_from_thread(self.notify, "Detaching VNIC…", timeout=6)
        try:
            self._mgr.detach_vnic(att_id)
            self.app.call_from_thread(self.notify, "VNIC detached ✓", severity="information")
            self._load_networking()
        except Exception as exc:
            self.app.call_from_thread(self.notify, f"Error: {exc}", severity="error")



    @work(thread=True, name="load_storage")
    def _load_storage(self) -> None:
        try:
            data = self._mgr.get_instance_storage_details(
                self._inst.compartment_id,
                self._inst.id,
                self._inst.availability_domain,
            )
            self.app.call_from_thread(self._populate_storage, data)
        except Exception as exc:
            self.app.call_from_thread(
                self.query_one("#sec-boot-vol-hdr", Static).update,
                _sec("Boot Volume") + f"  [red]Error: {exc}[/red]\n",
            )

    def _populate_storage(self, data: dict) -> None:
        def _fmt_dt(dt) -> str:
            if dt is None:
                return "—"
            return dt.strftime("%b %d, %Y, %H:%M UTC")

        # Boot volumes
        self.query_one("#sec-boot-vol-hdr", Static).update(_sec("Boot Volume"))
        bvt = self.query_one("#boot-vol-table", DataTable)
        bvt.clear()
        for item in data["boot_volumes"]:
            att = item["attachment"]
            bv  = item["volume"]
            name  = (bv.display_name  if bv  else att.display_name) or "—"
            state = Text(att.lifecycle_state, style=STATE_STYLE.get(att.lifecycle_state, "white"))
            size  = f"{bv.size_in_gbs} GB" if bv and bv.size_in_gbs else "—"
            enc   = "Enabled" if att.is_pv_encryption_in_transit_enabled else "Disabled"
            img   = bv.image_id or "—" if bv else "—"
            bvt.add_row(
                name, state, size, enc,
                _fmt_dt(bv.time_created if bv else None),
                _fmt_dt(att.time_created),
                img,
            )

        # Block volumes
        blkt = self.query_one("#block-vol-table", DataTable)
        blkt.clear()
        if not data["block_volumes"]:
            self.query_one("#sec-block-vol-hdr", Static).update(
                _sec("Attached Block Volumes") + "  [dim]No block volumes attached[/dim]\n"
            )
        else:
            self.query_one("#sec-block-vol-hdr", Static).update(_sec("Attached Block Volumes"))
            for item in data["block_volumes"]:
                att = item["attachment"]
                vol = item["volume"]
                name     = (vol.display_name if vol else att.display_name) or "—"
                state    = Text(att.lifecycle_state, style=STATE_STYLE.get(att.lifecycle_state, "white"))
                att_type = getattr(att, "attachment_type", "—") or "—"
                device   = getattr(att, "device", None) or "—"
                access   = "Read-only" if getattr(att, "is_read_only", False) else "Read/Write"
                size     = f"{vol.size_in_gbs} GB" if vol and vol.size_in_gbs else "—"
                vpu      = str(vol.vpus_per_gb) if vol and vol.vpus_per_gb is not None else "—"
                multi    = "Yes" if getattr(att, "is_multipath", False) else "No"
                blkt.add_row(name, state, att_type, device, access, size, vpu, multi)

    # ── Console tab ───────────────────────────────────────────────────────────

    @work(thread=True, name="load_console")
    def _load_console(self) -> None:
        try:
            conns = self._mgr.list_console_connections(
                self._inst.compartment_id, self._inst.id
            )
            self.app.call_from_thread(self._populate_console, conns)
        except Exception as exc:
            self.app.call_from_thread(
                self.query_one("#sec-console", Static).update,
                _sec("Console Connection") + f"  [red]Error: {exc}[/red]\n",
            )

    def _populate_console(self, conns: list) -> None:
        if not conns:
            self.query_one("#sec-console", Static).update(
                _sec("Console Connection")
                + "  [dim]No active console connections.[/dim]\n\n"
                + "  To connect, create a console connection from the OCI Console\n"
                + "  and use the provided SSH or VNC connection string.\n"
            )
            return

        text = _sec("Console Connection")
        for c in conns:
            st_col = STATE_STYLE.get(c.lifecycle_state, "white")
            text += _kv("ID",              c.id)
            text += _kv("State",           f"[{st_col}]{c.lifecycle_state}[/{st_col}]")
            text += _kv("Fingerprint",     c.fingerprint      or "—")
            text += _kv("SSH Connection",  c.connection_string     or "—")
            text += _kv("VNC Connection",  c.vnc_connection_string or "—")
            text += "\n"
        self.query_one("#sec-console", Static).update(text)
