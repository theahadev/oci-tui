from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Rule, Select, Static

from common import _IANA_PROTOCOLS, _expand_port_range  # noqa: F401 (_expand_port_range re-exported)

# ── Modal: Select Compartment ─────────────────────────────────────────────────

class CompartmentModal(ModalScreen):
    """Pick a compartment from a list."""

    BINDINGS = [Binding("escape", "dismiss_none", "Cancel")]

    def __init__(self, compartments: list) -> None:
        super().__init__()
        self._compartments = compartments

    def compose(self) -> ComposeResult:
        options = [(c.name, c.id) for c in self._compartments]
        with Container(id="modal-container"):
            yield Label("Select Compartment", id="modal-title")
            yield Rule()
            yield Select(options, id="comp-select", prompt="Choose compartment…")
            with Horizontal(id="modal-buttons"):
                yield Button("Select", variant="primary", id="btn-select")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def action_dismiss_none(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-select")
    def do_select(self) -> None:
        sel = self.query_one("#comp-select", Select)
        if sel.value is Select.BLANK:
            self.notify("Please choose a compartment", severity="warning")
            return
        name = next((c.name for c in self._compartments if c.id == sel.value), str(sel.value))
        self.dismiss((sel.value, name))

    @on(Button.Pressed, "#btn-cancel")
    def do_cancel(self) -> None:
        self.dismiss(None)


# ── Modal: Confirm ────────────────────────────────────────────────────────────

class ConfirmModal(ModalScreen):
    """Generic yes/no confirmation dialog."""

    BINDINGS = [Binding("escape", "dismiss_no", "Cancel")]

    def __init__(self, title: str, message: str, confirm_label: str = "Confirm") -> None:
        super().__init__()
        self._title = title
        self._message = message
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Container(id="modal-container"):
            yield Label(self._title, id="modal-title")
            yield Rule()
            yield Static(self._message, id="modal-message", markup=True)
            with Horizontal(id="modal-buttons"):
                yield Button(self._confirm_label, variant="error", id="btn-confirm")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def action_dismiss_no(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#btn-confirm")
    def do_confirm(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#btn-cancel")
    def do_cancel(self) -> None:
        self.dismiss(False)


# ── Modal: Copy full value ────────────────────────────────────────────────────

class CopyModal(ModalScreen):
    """Shows the full value of a truncated field in a selectable Input."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def __init__(self, label: str, value: str) -> None:
        super().__init__()
        self._label = label
        self._value = value

    def compose(self) -> ComposeResult:
        with Container(id="modal-container"):
            yield Label(self._label, id="modal-title")
            yield Rule()
            yield Input(self._value, id="copy-input")
            with Horizontal(id="modal-buttons"):
                yield Button("Close", variant="default", id="btn-close")

    def on_mount(self) -> None:
        inp = self.query_one("#copy-input", Input)
        inp.cursor_position = 0

    @on(Button.Pressed, "#btn-close")
    def do_close(self) -> None:
        self.dismiss()


# ── Security Rule Modal ───────────────────────────────────────────────────────

class SecurityRuleModal(ModalScreen):
    """Add or edit an ingress or egress security rule."""

    def __init__(
        self,
        direction: str = "ingress",
        existing_rule=None,
        rule_index: int = -1,
    ) -> None:
        super().__init__()
        self._direction  = direction
        self._existing   = existing_rule
        self._rule_index = rule_index

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _pr_str(pr) -> str:
        """PortRange object → 'min-max' or 'min' string."""
        if not pr:
            return ""
        return str(pr.min) if pr.min == pr.max else f"{pr.min}-{pr.max}"

    def _pre(self) -> dict:
        """Extract pre-fill values from an existing OCI rule object."""
        r = self._existing
        if r is None:
            return {}
        proto = str(r.protocol) if r.protocol != "all" else "all"
        cidr  = getattr(r, "source", None) or getattr(r, "destination", None) or ""
        sport = dport = icmp_type = icmp_code = ""
        tcp_o = getattr(r, "tcp_options", None)
        udp_o = getattr(r, "udp_options", None)
        icmp_o = getattr(r, "icmp_options", None)
        opts = tcp_o or udp_o
        if opts:
            sport = self._pr_str(getattr(opts, "source_port_range", None))
            dport = self._pr_str(getattr(opts, "destination_port_range", None))
        if icmp_o:
            icmp_type = str(icmp_o.type) if icmp_o.type is not None else ""
            icmp_code = str(icmp_o.code) if icmp_o.code is not None else ""
        return {
            "cidr":      cidr,
            "protocol":  proto,
            "sport":     sport,
            "dport":     dport,
            "icmp_type": icmp_type,
            "icmp_code": icmp_code,
            "desc":      getattr(r, "description", "") or "",
            "stateless": bool(getattr(r, "is_stateless", False)),
        }

    def compose(self) -> ComposeResult:
        editing  = self._existing is not None
        verb     = "Edit" if editing else "Add"
        lbl      = "Ingress Rule" if self._direction == "ingress" else "Egress Rule"
        src_dst  = "Source CIDR" if self._direction == "ingress" else "Destination CIDR"
        pre      = self._pre()

        with Container(classes="modal-box"):
            yield Label(f"{verb} {lbl}", classes="modal-title")
            yield Label(src_dst)
            yield Input(
                value=pre.get("cidr", ""),
                placeholder="0.0.0.0/0",
                id="sec-cidr",
            )
            yield Label("Protocol")
            yield Select(
                _IANA_PROTOCOLS,
                id="sec-proto",
                value=pre.get("protocol", "6"),
            )
            yield Label("Source Port Range  (blank = All)")
            yield Input(
                value=pre.get("sport", ""),
                placeholder="e.g. 1024-65535",
                id="sec-sport",
            )
            yield Label("Destination Port Range  (blank = All)")
            yield Input(
                value=pre.get("dport", ""),
                placeholder="e.g. 22  or  80-443",
                id="sec-dport",
            )
            yield Label("ICMP Type  (ICMP/ICMPv6 only)")
            yield Input(
                value=pre.get("icmp_type", ""),
                placeholder="e.g. 3",
                id="sec-icmp-type",
            )
            yield Label("ICMP Code  (blank = any)")
            yield Input(
                value=pre.get("icmp_code", ""),
                placeholder="e.g. 4",
                id="sec-icmp-code",
            )
            yield Label("Description")
            yield Input(
                value=pre.get("desc", ""),
                placeholder="optional",
                id="sec-desc",
            )
            with Horizontal(classes="button-row"):
                yield Button(verb, variant="primary", id="btn-ok")
                yield Button("Cancel", id="btn-cancel")

    @on(Button.Pressed, "#btn-ok")
    def do_ok(self) -> None:
        def _qv(wid):
            try:
                return self.query_one(wid, Input).value.strip()
            except Exception:
                return ""

        cidr = _qv("#sec-cidr")
        if not cidr:
            self.notify("CIDR / address is required", severity="error")
            return

        proto = self.query_one("#sec-proto", Select).value
        self.dismiss({
            "direction":   self._direction,
            "cidr":        cidr,
            "protocol":    proto,
            "sport":       _qv("#sec-sport"),
            "dport":       _qv("#sec-dport"),
            "icmp_type":   _qv("#sec-icmp-type"),
            "icmp_code":   _qv("#sec-icmp-code"),
            "description": _qv("#sec-desc"),
            "stateless":   False,
            "rule_index":  self._rule_index,
        })

    @on(Button.Pressed, "#btn-cancel")
    def do_cancel(self) -> None:
        self.dismiss(None)
