from __future__ import annotations

from typing import Dict

# ── Helpers ──────────────────────────────────────────────────────────────────

STATE_STYLE: Dict[str, str] = {
    "RUNNING":      "bold green",
    "STOPPED":      "bold red",
    "PROVISIONING": "bold yellow",
    "STARTING":     "bold yellow",
    "STOPPING":     "bold yellow",
    "REBOOTING":    "bold yellow",
    "TERMINATING":  "bold red",
    "TERMINATED":   "dim",
}

STATE_ACTIONS: Dict[str, list[str]] = {
    "RUNNING": ["SOFTSTOP", "SOFTRESET", "RESET"],
    "STOPPED": ["START"],
}

# ── Rich-markup helpers ───────────────────────────────────────────────────────

_KW = 28  # key column width for detail views
_TRUNC_LEN = 46  # max display length for long strings

# Full IANA IP protocol list (common ones first, then numerically)
_IANA_PROTOCOLS: list[tuple[str, str]] = [
    ("All Protocols", "all"),
    ("1  - ICMP",                            "1"),
    ("6  - TCP",                             "6"),
    ("17 - UDP",                             "17"),
    ("58 - IPv6-ICMP",                       "58"),
    ("0  - HOPOPT (IPv6 Hop-by-Hop)",        "0"),
    ("2  - IGMP",                            "2"),
    ("3  - GGP",                             "3"),
    ("4  - IPv4 encapsulation",              "4"),
    ("5  - ST (Stream)",                     "5"),
    ("7  - CBT",                             "7"),
    ("8  - EGP",                             "8"),
    ("9  - IGP",                             "9"),
    ("10 - BBN-RCC-MON",                     "10"),
    ("11 - NVP-II",                          "11"),
    ("12 - PUP",                             "12"),
    ("14 - EMCON",                           "14"),
    ("15 - XNET",                            "15"),
    ("16 - CHAOS",                           "16"),
    ("18 - MUX",                             "18"),
    ("19 - DCN-MEAS",                        "19"),
    ("20 - HMP",                             "20"),
    ("21 - PRM",                             "21"),
    ("22 - XNS-IDP",                         "22"),
    ("27 - RDP",                             "27"),
    ("28 - IRTP",                            "28"),
    ("29 - ISO-TP4",                         "29"),
    ("30 - NETBLT",                          "30"),
    ("33 - DCCP",                            "33"),
    ("36 - XTP",                             "36"),
    ("37 - DDP",                             "37"),
    ("41 - IPv6 encapsulation",              "41"),
    ("43 - IPv6-Route",                      "43"),
    ("44 - IPv6-Frag",                       "44"),
    ("45 - IDRP",                            "45"),
    ("46 - RSVP",                            "46"),
    ("47 - GRE",                             "47"),
    ("48 - DSR",                             "48"),
    ("50 - ESP (Encap Security Payload)",    "50"),
    ("51 - AH (Authentication Header)",      "51"),
    ("54 - NARP",                            "54"),
    ("57 - SKIP",                            "57"),
    ("59 - IPv6-NoNxt",                      "59"),
    ("60 - IPv6-Opts",                       "60"),
    ("80 - ISO-IP",                          "80"),
    ("88 - EIGRP",                           "88"),
    ("89 - OSPFIGP",                         "89"),
    ("94 - IPIP",                            "94"),
    ("97 - ETHERIP",                         "97"),
    ("103 - PIM",                            "103"),
    ("108 - IPComp",                         "108"),
    ("112 - VRRP",                           "112"),
    ("115 - L2TP",                           "115"),
    ("132 - SCTP",                           "132"),
    ("133 - FC",                             "133"),
    ("136 - UDPLite",                        "136"),
    ("137 - MPLS-in-IP",                     "137"),
    ("139 - HIP",                            "139"),
    ("143 - Ethernet",                       "143"),
]


def _expand_port_range(d: dict) -> dict:
    """Convert 'sport'/'dport' range strings into min/max keys for the manager."""
    def _split(s):
        if not s or not s.strip():
            return None, None
        s = s.strip()
        if "-" in s:
            parts = s.split("-", 1)
            return parts[0].strip(), parts[1].strip()
        return s, s

    lo, hi = _split(d.pop("sport", ""))
    d["src_port_min"], d["src_port_max"] = lo, hi
    lo, hi = _split(d.pop("dport", ""))
    d["dst_port_min"], d["dst_port_max"] = lo, hi

    icmp_type = d.pop("icmp_type", "")
    icmp_code = d.pop("icmp_code", "")
    if icmp_type:
        d["icmp_type"] = icmp_type
    if icmp_code:
        d["icmp_code"] = icmp_code
    return d


def _trunc(s: str) -> str:
    """Shorten a long string, keeping start and tail for recognisability."""
    if not s or len(s) <= _TRUNC_LEN:
        return s
    keep = (_TRUNC_LEN - 1) // 2
    return s[:keep] + "…" + s[-((_TRUNC_LEN - 1) - keep):]


def _kv(key: str, val: str) -> str:
    """Format a single key-value row for detail sections."""
    return f"  [dim]{key:<{_KW}}[/dim]  {val or '—'}\n"


def _kv_long(key: str, val: str, field_id: str, store: dict) -> str:
    """Like _kv but truncates long values and adds a clickable reveal link.

    ``store`` is the screen's ``_long_vals`` dict; the full value is saved there
    under ``field_id`` so ``action_reveal`` can look it up.
    """
    store[field_id] = val or ""
    display = _trunc(val) if val else "—"
    link = f"[@click=reveal('{field_id}')]{display}[/]"
    return f"  [dim]{key:<{_KW}}[/dim]  {link}\n"


def _sec(title: str) -> str:
    """Format a section header."""
    return f"\n[b]{title}[/b]\n[dim]{'─' * 60}[/dim]\n"


def _short_ad(availability_domain: str) -> str:
    return availability_domain.split(":")[-1] if availability_domain else "—"
