import argparse
import json
import math
import os
import sys

from . import __version__, configs
from .design import Design


def _tb(gb):
    return "%.1f TB" % (gb / 1024.0) if gb >= 1024 else "%.0f GB" % gb


def report(d):
    errors, warnings = d.checks()
    st = d.storage()
    out = ["# %s" % d.name, "",
           "Ingest %.0f GB/day%s, retention %d days. `site_replication_factor = %s`, `site_search_factor = %s`." % (
               d.ingest, (", %.0f GB/day after %g years at %g%% growth" % (d.planned_ingest, d.years, 100 * d.growth))
               if d.years else "", d.retention, d.srf, d.ssf), ""]
    if errors:
        out += ["## Invalid configuration", ""] + ["- **%s**" % e for e in errors] + [""]
    out += ["## Copies per bucket", "", "| Data arrives at | " + " | ".join(d.peers) + " |",
            "|---|" + "---|" * len(d.peers)]
    for o, (rc, sc) in d.placements().items():
        out.append("| %s (%.0f%% of ingest) | %s |" % (o, 100 * d.share[o], " | ".join(
            "%d (%d searchable)" % (rc[s], sc[s]) for s in d.peers)))
    out += ["", "## Storage at full retention", "",
            "Using %.0f%% of ingest for compressed rawdata per copy and %.0f%% for index files per searchable copy, "
            "plus %.0f%% free space headroom." % (100 * d.raw_ratio, 100 * d.idx_ratio, 100 * d.headroom), "",
            "| Site | Indexers | Site total | Per indexer | Per indexer with headroom |", "|---|---|---|---|---|"]
    for s, gb in st.items():
        n = d.peers[s]
        per = gb / n if n else 0
        out.append("| %s | %d | %s | %s | %s |" % (s, n, _tb(gb), _tb(per), _tb(per / (1 - d.headroom)) if n else "-"))
    out.append("| **all** | %d | **%s** | | |" % (sum(d.peers.values()), _tb(sum(st.values()))))
    bw = d.bandwidth()
    out += ["", "## Inter-site replication", "",
            "Assumes peers stream compressed rawdata (%.0f%% of ingest) per remote copy and targets build their own index "
            "files. Link %g Mbps, planning limit %.0f%%." % (100 * d.payload, d.link_mbps, 100 * d.max_util), "",
            "| From | To | GB/day | Average Mbps | Peak Mbps (x%g) |" % d.peak, "|---|---|---|---|---|"]
    for (a, b), v in bw.items():
        out.append("| %s | %s | %.1f | %.1f | %.1f |" % (a, b, v["gb_per_day"], v["avg_mbps"], v["peak_mbps"]))
    hrs, backlog = d.catchup_hours()
    out += ["", "After a %g hour link or site outage, about %.0f GB must be re-replicated: %s." % (
        d.outage_h, backlog, ("roughly %.1f hours using the spare link capacity" % hrs) if hrs is not None else
        "**the link has no spare capacity to catch up**")]
    out += ["", "## Site failure scenarios", ""]
    for s in d.peers:
        r = d.site_loss(s)
        out.append("### Lose %s" % s)
        out.append("")
        for sev, msg in r["issues"]:
            out.append("- **%s**: %s" % (sev, msg))
        for msg in r["ok"]:
            out.append("- ok: %s" % msg)
        out.append("")
    if warnings:
        out += ["## Warnings", ""] + ["- %s" % w for w in warnings] + [""]
    return "\n".join(out) + "\n"


def compare(designs):
    out = ["# Design comparison", "",
           "| Design | SRF | SSF | Indexers | Total storage | Peak replication Mbps | Lose primary | Errors |",
           "|---|---|---|---|---|---|---|---|"]
    for d in designs:
        errors, _ = d.checks()
        prim = next((s["name"] for s in d.sites if s.get("role") == "primary"), next(iter(d.peers)))
        loss = d.site_loss(prim)
        worst = sorted({sev for sev, _ in loss["issues"]}, key=["critical", "high", "medium"].index)
        peak = max([b["peak_mbps"] for b in d.bandwidth().values()] or [0])
        out.append("| %s | %s | %s | %s | %s | %.0f | %s | %d |" % (
            d.name, d.srf, d.ssf, " + ".join(str(n) for n in d.peers.values()), _tb(sum(d.storage().values())), peak,
            ("%s (%d issues)" % (worst[0], len(loss["issues"]))) if worst else "ok", len(errors)))
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="drsizer", description="Size and validate multisite Splunk DR designs.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("report", help="report on one design, or compare several")
    p.add_argument("designs", nargs="+")
    p.add_argument("-o", "--output")
    p.add_argument("--fail-on-error", action="store_true")
    p = sub.add_parser("config", help="write starting-point .conf files for a design")
    p.add_argument("design")
    p.add_argument("-o", "--outdir", default="generated")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "report":
            designs = [Design.load(p) for p in args.designs]
            text = "".join(report(d) + "\n" for d in designs)
            if len(designs) > 1:
                text = compare(designs) + "\n" + text
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(text)
            else:
                sys.stdout.write(text)
            if args.fail_on_error and any(d.checks()[0] for d in designs):
                return 1
            return 0
        d = Design.load(args.design)
        for path, body in configs.render(d).items():
            full = os.path.join(args.outdir, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write(body)
            print(full)
        return 0
    except (OSError, ValueError, KeyError) as e:
        print("drsizer: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
