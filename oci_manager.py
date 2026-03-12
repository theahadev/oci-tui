"""OCI Manager - synchronous Oracle Cloud Infrastructure SDK wrapper."""

from __future__ import annotations

from typing import Optional, Tuple

import oci
from oci.core.models import (
    AttachVnicDetails,
    CreatePublicIpDetails,
    CreateVnicDetails,
    EgressSecurityRule,
    GetPublicIpByPrivateIpIdDetails,
    IcmpOptions,
    IngressSecurityRule,
    LaunchInstanceDetails,
    LaunchInstanceShapeConfigDetails,
    PortRange,
    TcpOptions,
    UdpOptions,
    UpdatePublicIpDetails,
    UpdateSecurityListDetails,
    UpdateVnicDetails,
)


class OCIManager:
    """Wraps OCI SDK clients with simplified methods for TUI use."""

    def __init__(self, profile: str = "DEFAULT"):
        self.config = oci.config.from_file(profile_name=profile)
        oci.config.validate_config(self.config)
        self.compute = oci.core.ComputeClient(self.config)
        self.blockstorage = oci.core.BlockstorageClient(self.config)
        self.identity = oci.identity.IdentityClient(self.config)
        self.vnet = oci.core.VirtualNetworkClient(self.config)
        self.tenancy_id: str = self.config["tenancy"]

    # ── Tenancy / Compartments ──────────────────────────────────────────────

    def get_tenancy_name(self) -> str:
        try:
            return self.identity.get_tenancy(self.tenancy_id).data.name
        except Exception:
            return self.tenancy_id[:32] + "…"

    def list_compartments(self) -> list:
        """Return root compartment + all active child compartments."""
        root = self.identity.get_compartment(self.tenancy_id).data
        children = oci.pagination.list_call_get_all_results(
            self.identity.list_compartments,
            self.tenancy_id,
            compartment_id_in_subtree=True,
            lifecycle_state="ACTIVE",
        ).data
        return [root] + list(children)

    # ── Instances ───────────────────────────────────────────────────────────

    def list_instances(self, compartment_id: str) -> list:
        """Return all non-terminated instances in a compartment."""
        instances = oci.pagination.list_call_get_all_results(
            self.compute.list_instances,
            compartment_id,
        ).data
        return [i for i in instances if i.lifecycle_state != "TERMINATED"]

    def get_instance(self, instance_id: str):
        return self.compute.get_instance(instance_id).data

    def instance_action(self, instance_id: str, action: str):
        """action: START | STOP | SOFTSTOP | SOFTRESET | RESET"""
        return self.compute.instance_action(instance_id, action)

    def terminate_instance(self, instance_id: str, preserve_boot_volume: bool = False):
        return self.compute.terminate_instance(
            instance_id,
            preserve_boot_volume=preserve_boot_volume,
        )

    def launch_instance(self, details: dict):
        """Launch an instance from a dict of parameters."""
        ld = LaunchInstanceDetails(
            availability_domain=details["availability_domain"],
            compartment_id=details["compartment_id"],
            shape=details["shape"],
            display_name=details.get("display_name") or None,
            image_id=details["image_id"],
            subnet_id=details["subnet_id"],
            metadata=details.get("metadata", {}),
        )
        if details.get("shape_config"):
            ld.shape_config = LaunchInstanceShapeConfigDetails(
                ocpus=float(details["shape_config"].get("ocpus", 1)),
                memory_in_gbs=float(details["shape_config"].get("memory_in_gbs", 6)),
            )
        return self.compute.launch_instance(ld)

    # ── Networking ──────────────────────────────────────────────────────────

    def get_primary_ip(self, compartment_id: str, instance_id: str) -> Tuple[str, str]:
        """Return (public_ip, private_ip) for the primary VNIC, or ('—', '—')."""
        try:
            attachments = oci.pagination.list_call_get_all_results(
                self.compute.list_vnic_attachments,
                compartment_id,
                instance_id=instance_id,
            ).data
            # Find primary VNIC first; fall back to first available
            primary_vnic = None
            fallback_vnic = None
            for att in attachments:
                if att.lifecycle_state != "ATTACHED":
                    continue
                try:
                    vnic = self.vnet.get_vnic(att.vnic_id).data
                    if fallback_vnic is None:
                        fallback_vnic = vnic
                    if vnic.is_primary:
                        primary_vnic = vnic
                        break
                except Exception:
                    pass
            vnic = primary_vnic or fallback_vnic
            if vnic:
                return (vnic.public_ip or "—", vnic.private_ip or "—")
        except Exception:
            pass
        return ("—", "—")

    def list_vcns(self, compartment_id: str) -> list:
        return oci.pagination.list_call_get_all_results(
            self.vnet.list_vcns, compartment_id
        ).data

    def list_nsgs(self, compartment_id: str, vcn_id: Optional[str] = None) -> list:
        kwargs: dict = {"compartment_id": compartment_id}
        if vcn_id:
            kwargs["vcn_id"] = vcn_id
        return oci.pagination.list_call_get_all_results(
            self.vnet.list_network_security_groups, **kwargs
        ).data

    def get_vnic_full_details(self, vnic_id: str, compartment_id: str, attachment) -> dict:
        """Return a dict with vnic, subnet, vcn, route_table, private_ips (with public_ip each)."""
        vnic = self.vnet.get_vnic(vnic_id).data
        result: dict = {
            "vnic":        vnic,
            "attachment":  attachment,
            "subnet":      None,
            "vcn":         None,
            "route_table": None,
            "private_ips": [],
        }

        if vnic.subnet_id:
            try:
                subnet = self.vnet.get_subnet(vnic.subnet_id).data
                result["subnet"] = subnet
                try:
                    result["vcn"] = self.vnet.get_vcn(subnet.vcn_id).data
                except Exception:
                    pass
            except Exception:
                pass

        # Route table: prefer VNIC override, fall back to subnet
        rt_id = getattr(vnic, "route_table_id", None)
        if not rt_id and result["subnet"]:
            rt_id = result["subnet"].route_table_id
        if rt_id:
            try:
                result["route_table"] = self.vnet.get_route_table(rt_id).data
            except Exception:
                pass

        # Private IPs on this VNIC
        try:
            private_ips = oci.pagination.list_call_get_all_results(
                self.vnet.list_private_ips, vnic_id=vnic_id
            ).data
            for pip in private_ips:
                pub = None
                try:
                    pub = self.vnet.get_public_ip_by_private_ip_id(
                        GetPublicIpByPrivateIpIdDetails(private_ip_id=pip.id)
                    ).data
                except Exception:
                    pass
                rt = None
                if getattr(pip, "route_table_id", None):
                    try:
                        rt = self.vnet.get_route_table(pip.route_table_id).data
                    except Exception:
                        pass
                result["private_ips"].append({"private_ip": pip, "public_ip": pub, "route_table": rt})
        except Exception:
            pass

        return result

    def vnic_connect(self, instance_id: str, details: dict):
        """Attach a secondary VNIC to an instance.

        ``details`` keys (all optional unless noted):
          subnet_id*            – required
          display_name          – VNIC display name
          attachment_name       – attachment display name
          private_ip            – specific private IP; None = auto
          assign_public_ip      – True / False / None (None = subnet default)
          assign_private_dns    – bool (default True)
          hostname_label        – DNS label for the VNIC
          skip_source_dest_check – bool (default False)
          nsg_ids               – list[str]
          nic_index             – int (default 0)
        """
        cvd = CreateVnicDetails(
            subnet_id=details["subnet_id"],
            display_name=details.get("display_name") or None,
            hostname_label=details.get("hostname_label") or None,
            private_ip=details.get("private_ip") or None,
            assign_public_ip=details.get("assign_public_ip"),
            assign_private_dns_record=details.get("assign_private_dns"),
            skip_source_dest_check=bool(details.get("skip_source_dest_check", False)),
            nsg_ids=details.get("nsg_ids") or [],
        )
        avd = AttachVnicDetails(
            instance_id=instance_id,
            create_vnic_details=cvd,
            display_name=details.get("attachment_name") or None,
            nic_index=details.get("nic_index"),
        )
        return self.compute.attach_vnic(avd).data

    def update_vnic(self, vnic_id: str, details: dict):
        """Update an existing VNIC.

        ``details`` keys (all optional):
          display_name           – VNIC display name
          hostname_label         – DNS label
          skip_source_dest_check – bool
          nsg_ids                – list[str] (replaces existing NSGs)
          route_table_id         – override route table
        """
        uvd = UpdateVnicDetails(
            display_name=details.get("display_name") or None,
            hostname_label=details.get("hostname_label") or None,
            skip_source_dest_check=details.get("skip_source_dest_check"),
            nsg_ids=details.get("nsg_ids"),
            route_table_id=details.get("route_table_id") or None,
        )
        return self.vnet.update_vnic(vnic_id, uvd).data

    def detach_vnic(self, vnic_attachment_id: str):
        return self.compute.detach_vnic(vnic_attachment_id)



    def list_subnets(self, compartment_id: str, vcn_id: Optional[str] = None) -> list:
        kwargs = {"vcn_id": vcn_id} if vcn_id else {}
        return oci.pagination.list_call_get_all_results(
            self.vnet.list_subnets, compartment_id, **kwargs
        ).data

    # ── Compute metadata ────────────────────────────────────────────────────

    def list_availability_domains(self) -> list:
        return self.identity.list_availability_domains(self.tenancy_id).data

    def list_shapes(self, compartment_id: str) -> list:
        return oci.pagination.list_call_get_all_results(
            self.compute.list_shapes, compartment_id
        ).data

    def list_images(self, compartment_id: str) -> list:
        return oci.pagination.list_call_get_all_results(
            self.compute.list_images, compartment_id
        ).data

    def get_image(self, image_id: str):
        try:
            return self.compute.get_image(image_id).data
        except Exception:
            return None

    def get_instance_storage_details(self, compartment_id: str, instance_id: str, availability_domain: str) -> dict:
        """Return boot volume attachment + volume, and block volume attachments + volumes."""
        result: dict = {"boot_volumes": [], "block_volumes": []}

        # Boot volumes
        try:
            bv_atts = oci.pagination.list_call_get_all_results(
                self.compute.list_boot_volume_attachments,
                availability_domain,
                compartment_id,
                instance_id=instance_id,
            ).data
            for att in bv_atts:
                bv = None
                try:
                    bv = self.blockstorage.get_boot_volume(att.boot_volume_id).data
                except Exception:
                    pass
                result["boot_volumes"].append({"attachment": att, "volume": bv})
        except Exception:
            pass

        # Block volumes
        try:
            vol_atts = oci.pagination.list_call_get_all_results(
                self.compute.list_volume_attachments,
                compartment_id,
                instance_id=instance_id,
            ).data
            for att in vol_atts:
                vol = None
                try:
                    vol = self.blockstorage.get_volume(att.volume_id).data
                except Exception:
                    pass
                result["block_volumes"].append({"attachment": att, "volume": vol})
        except Exception:
            pass

        return result

    def list_console_connections(self, compartment_id: str, instance_id: str) -> list:
        """Return active console connections for the instance."""
        try:
            conns = oci.pagination.list_call_get_all_results(
                self.compute.list_instance_console_connections,
                compartment_id,
                instance_id=instance_id,
            ).data
            return [c for c in conns if c.lifecycle_state != "DELETED"]
        except Exception:
            return []

    def get_instance_network_details(self, compartment_id: str, instance_id: str) -> list:
        """Return a list of dicts, one per VNIC attachment, enriched with subnet/VCN/route-table."""
        attachments = oci.pagination.list_call_get_all_results(
            self.compute.list_vnic_attachments,
            compartment_id,
            instance_id=instance_id,
        ).data

        result = []
        for att in attachments:
            try:
                vnic = self.vnet.get_vnic(att.vnic_id).data
                info: dict = {
                    "attachment": att,
                    "vnic": vnic,
                    "subnet": None,
                    "vcn": None,
                    "route_table": None,
                }
                if vnic.subnet_id:
                    try:
                        subnet = self.vnet.get_subnet(vnic.subnet_id).data
                        info["subnet"] = subnet
                        try:
                            info["vcn"] = self.vnet.get_vcn(subnet.vcn_id).data
                        except Exception:
                            pass
                        if subnet.route_table_id:
                            try:
                                info["route_table"] = self.vnet.get_route_table(subnet.route_table_id).data
                            except Exception:
                                pass
                    except Exception:
                        pass
                result.append(info)
            except Exception:
                pass
        return result

    # ── Networking overview ─────────────────────────────────────────────────

    def list_all_vnics(self, compartment_id: str) -> list:
        """Return list of dicts {attachment, vnic, instance_name, subnet_name}."""
        attachments = oci.pagination.list_call_get_all_results(
            self.compute.list_vnic_attachments, compartment_id
        ).data
        result = []
        for att in attachments:
            try:
                vnic = self.vnet.get_vnic(att.vnic_id).data
                sn_name = "—"
                try:
                    sn_name = self.vnet.get_subnet(vnic.subnet_id).data.display_name
                except Exception:
                    pass
                result.append({
                    "attachment":     att,
                    "vnic":           vnic,
                    "subnet_name":    sn_name,
                })
            except Exception:
                pass
        return result

    def list_ip_mappings(self, compartment_id: str) -> list:
        """Return list of dicts {private_ip, public_ip, vnic, instance_name}."""
        # Build instance_id → name map from VNIC attachments
        attachments = oci.pagination.list_call_get_all_results(
            self.compute.list_vnic_attachments, compartment_id
        ).data
        att_by_vnic: dict = {a.vnic_id: a for a in attachments}

        # Build instance map
        instances = oci.pagination.list_call_get_all_results(
            self.compute.list_instances, compartment_id
        ).data
        inst_name: dict = {i.id: (i.display_name or i.id[-12:]) for i in instances}

        # List all subnets to iterate private IPs
        subnets = oci.pagination.list_call_get_all_results(
            self.vnet.list_subnets, compartment_id
        ).data

        result = []
        for sn in subnets:
            try:
                pips = oci.pagination.list_call_get_all_results(
                    self.vnet.list_private_ips, subnet_id=sn.id
                ).data
                for pip in pips:
                    if not pip.vnic_id:
                        continue
                    pub = None
                    try:
                        pub = self.vnet.get_public_ip_by_private_ip_id(
                            GetPublicIpByPrivateIpIdDetails(private_ip_id=pip.id)
                        ).data
                    except Exception:
                        pass
                    att = att_by_vnic.get(pip.vnic_id)
                    iname = inst_name.get(att.instance_id, "—") if att else "—"
                    result.append({
                        "private_ip":    pip,
                        "public_ip":     pub,
                        "instance_name": iname,
                        "subnet_name":   sn.display_name,
                    })
            except Exception:
                pass
        return result

    def list_reserved_public_ips(self, compartment_id: str) -> list:
        """Return list of dicts {public_ip, private_ip} for reserved public IPs."""
        public_ips = oci.pagination.list_call_get_all_results(
            self.vnet.list_public_ips,
            "REGION",
            compartment_id,
            lifetime="RESERVED",
        ).data
        result = []
        for public_ip in public_ips:
            if public_ip.lifecycle_state == "TERMINATED":
                continue
            private_ip = None
            if getattr(public_ip, "private_ip_id", None):
                try:
                    private_ip = self.vnet.get_private_ip(public_ip.private_ip_id).data
                except Exception:
                    pass
            result.append({"public_ip": public_ip, "private_ip": private_ip})
        return result

    def create_reserved_public_ip(self, compartment_id: str, display_name: Optional[str] = None):
        """Reserve a new public IP in the selected compartment."""
        details = CreatePublicIpDetails(
            compartment_id=compartment_id,
            lifetime="RESERVED",
            display_name=display_name or None,
        )
        return self.vnet.create_public_ip(details).data

    def update_public_ip_name(self, public_ip_id: str, display_name: str):
        """Update the display name for a reserved public IP."""
        details = UpdatePublicIpDetails(display_name=display_name)
        return self.vnet.update_public_ip(public_ip_id, details).data

    def delete_public_ip(self, public_ip_id: str):
        """Delete a public IP."""
        return self.vnet.delete_public_ip(public_ip_id)

    def list_security_lists(self, compartment_id: str) -> list:
        return oci.pagination.list_call_get_all_results(
            self.vnet.list_security_lists, compartment_id
        ).data

    def get_security_list(self, security_list_id: str):
        return self.vnet.get_security_list(security_list_id).data

    def update_security_list_rules(
        self, security_list_id: str,
        ingress_rules: list, egress_rules: list
    ):
        """Replace all ingress + egress rules on a security list."""
        return self.vnet.update_security_list(
            security_list_id,
            UpdateSecurityListDetails(
                ingress_security_rules=ingress_rules,
                egress_security_rules=egress_rules,
            ),
        ).data

    @staticmethod
    def build_ingress_rule(d: dict) -> IngressSecurityRule:
        """Build an IngressSecurityRule from a plain dict."""
        proto = d["protocol"]
        return IngressSecurityRule(
            protocol=proto,
            source=d["source"],
            source_type=d.get("source_type", "CIDR_BLOCK"),
            is_stateless=d.get("is_stateless", False),
            description=d.get("description") or None,
            tcp_options=OCIManager._tcp_opts(d) if proto in ("6", "all") else None,
            udp_options=OCIManager._udp_opts(d) if proto == "17" else None,
            icmp_options=OCIManager._icmp_opts(d) if proto in ("1", "58") else None,
        )

    @staticmethod
    def build_egress_rule(d: dict) -> EgressSecurityRule:
        """Build an EgressSecurityRule from a plain dict."""
        proto = d["protocol"]
        return EgressSecurityRule(
            protocol=proto,
            destination=d["destination"],
            destination_type=d.get("destination_type", "CIDR_BLOCK"),
            is_stateless=d.get("is_stateless", False),
            description=d.get("description") or None,
            tcp_options=OCIManager._tcp_opts(d) if proto in ("6", "all") else None,
            udp_options=OCIManager._udp_opts(d) if proto == "17" else None,
            icmp_options=OCIManager._icmp_opts(d) if proto in ("1", "58") else None,
        )

    @staticmethod
    def _port_range(lo, hi) -> Optional[PortRange]:
        if lo is None:
            return None
        lo_i = int(lo) if str(lo).strip() else None
        hi_i = int(hi) if str(hi).strip() else lo_i
        if lo_i is None:
            return None
        return PortRange(min=lo_i, max=hi_i)

    @staticmethod
    def _tcp_opts(d: dict) -> Optional[TcpOptions]:
        src = OCIManager._port_range(d.get("src_port_min"), d.get("src_port_max"))
        dst = OCIManager._port_range(d.get("dst_port_min"), d.get("dst_port_max"))
        if src is None and dst is None:
            return None
        return TcpOptions(source_port_range=src, destination_port_range=dst)

    @staticmethod
    def _udp_opts(d: dict) -> Optional[UdpOptions]:
        src = OCIManager._port_range(d.get("src_port_min"), d.get("src_port_max"))
        dst = OCIManager._port_range(d.get("dst_port_min"), d.get("dst_port_max"))
        if src is None and dst is None:
            return None
        return UdpOptions(source_port_range=src, destination_port_range=dst)

    @staticmethod
    def _icmp_opts(d: dict) -> Optional[IcmpOptions]:
        t = d.get("icmp_type")
        c = d.get("icmp_code")
        if t is None:
            return None
        return IcmpOptions(
            type=int(t),
            code=int(c) if c is not None and str(c).strip() else None,
        )
