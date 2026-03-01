from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Rule, Select

from common import _short_ad

# ── Modal: Launch Instance ────────────────────────────────────────────────────

class LaunchModal(ModalScreen):
    """Form to provision a new compute instance."""

    BINDINGS = [Binding("escape", "dismiss_cancel", "Cancel")]

    def __init__(
        self,
        compartment_id: str,
        shapes: list,
        images: list,
        ads: list,
        subnets: list,
    ) -> None:
        super().__init__(classes="launch-modal")
        self._compartment_id = compartment_id
        self._shapes = shapes
        self._images = images
        self._ads = ads
        self._subnets = subnets

    def compose(self) -> ComposeResult:
        ad_opts      = [(_short_ad(ad.name), ad.name) for ad in self._ads]
        shape_opts   = [(s.shape, s.shape) for s in self._shapes[:60]]
        image_opts   = [
            (f"{img.display_name[:40]}  ({img.operating_system})", img.id)
            for img in self._images[:40]
        ]
        subnet_opts  = [(s.display_name or s.id[:28], s.id) for s in self._subnets]

        with Container(id="modal-container"):
            yield Label("Launch Instance", id="modal-title")
            yield Rule()
            with ScrollableContainer(classes="form-scroll"):
                yield Label("Display Name", classes="field-label")
                yield Input(placeholder="my-instance", id="in-name")

                yield Label("Availability Domain *", classes="field-label")
                yield Select(ad_opts, id="sel-ad", prompt="Select AD…")

                yield Label("Shape *", classes="field-label")
                yield Select(shape_opts, id="sel-shape", prompt="Select shape…")

                with Horizontal(classes="shape-config"):
                    with Vertical(classes="half"):
                        yield Label("OCPUs  (flex)", classes="field-label")
                        yield Input("1", id="in-ocpu")
                    with Vertical(classes="half"):
                        yield Label("Memory GB  (flex)", classes="field-label")
                        yield Input("6", id="in-mem")

                yield Label("Image *", classes="field-label")
                yield Select(image_opts, id="sel-image", prompt="Select image…")

                yield Label("Subnet *", classes="field-label")
                yield Select(subnet_opts, id="sel-subnet", prompt="Select subnet…")

                yield Label("SSH Public Key  (optional)", classes="field-label")
                yield Input(placeholder="ssh-rsa AAAA…", id="in-ssh")

            with Horizontal(id="modal-buttons"):
                yield Button("Launch", variant="primary", id="btn-launch")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def action_dismiss_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-launch")
    def do_launch(self) -> None:
        ad     = self.query_one("#sel-ad",     Select).value
        shape  = self.query_one("#sel-shape",  Select).value
        image  = self.query_one("#sel-image",  Select).value
        subnet = self.query_one("#sel-subnet", Select).value

        if Select.BLANK in (ad, shape, image, subnet):
            self.notify("Please fill all required fields (*)", severity="warning")
            return

        name    = self.query_one("#in-name",  Input).value.strip()
        ocpu    = self.query_one("#in-ocpu",  Input).value.strip()
        mem     = self.query_one("#in-mem",   Input).value.strip()
        ssh_key = self.query_one("#in-ssh",   Input).value.strip()

        details: dict = {
            "compartment_id":      self._compartment_id,
            "availability_domain": ad,
            "shape":               shape,
            "image_id":            image,
            "subnet_id":           subnet,
        }
        if name:
            details["display_name"] = name
        if "Flex" in str(shape) or "flex" in str(shape):
            details["shape_config"] = {
                "ocpus":         float(ocpu) if ocpu else 1.0,
                "memory_in_gbs": float(mem)  if mem  else 6.0,
            }
        if ssh_key:
            details["metadata"] = {"ssh_authorized_keys": ssh_key}

        self.dismiss(details)

    @on(Button.Pressed, "#btn-cancel")
    def do_cancel(self) -> None:
        self.dismiss(None)
