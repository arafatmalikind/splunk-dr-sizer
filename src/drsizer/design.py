"""Storage, bandwidth and failure analysis for a two or more site Splunk design."""

import json
import math

from . import factors

GB = 1.0


class Design:
    def __init__(self, d, name=None):
        self.name = d.get("name") or name or "design"
        self.ingest = float(d["ingest_gb_per_day"])
        self.growth = float(d.get("growth_pct_per_year", 0)) / 100.0
        self.years = float(d.get("plan_years", 0))
        self.retention = int(d.get("retention_days", 90))
        comp = d.get("compression", {})
        self.raw_ratio = float(comp.get("rawdata", 0.15))
        self.idx_ratio = float(comp.get("index_files", 0.35))
        self.headroom = float(d.get("free_space_headroom_pct", 25)) / 100.0
        self.sites = d["sites"]
        self.peers = {s["name"]: int(s.get("indexers", 0)) for s in self.sites}
        self.srf = factors.parse(d.get("site_replication_factor", "origin:2,total:3"))
        self.ssf = factors.parse(d.get("site_search_factor", "origin:1,total:2"))
        share = d.get("ingest_share")
        if not share:
            prim = [s["name"] for s in self.sites if s.get("role") == "primary"] or [self.sites[0]["name"]]
            share = {prim[0]: 1.0}
        tot = sum(share.values())
        self.share = {k: v / tot for k, v in share.items()}
        net = d.get("network", {})
        self.link_mbps = float(net.get("inter_site_mbps", 1000))
        self.max_util = float(net.get("max_utilisation_pct", 50)) / 100.0
        self.peak = float(net.get("peak_to_average", 3))
        self.payload = float(net.get("replication_payload_ratio", self.raw_ratio))
        self.outage_h = float(d.get("outage_hours_to_recover", 24))
        self.cm_mode = d.get("manager_switchover_mode", "disabled")
        cms = [s for s in self.sites if s.get("cluster_manager")]
        cms.sort(key=lambda s: s.get("role") != "primary")      # the active manager runs at the primary site
        self.cm_sites = [s["name"] for s in cms]
        self.label = d.get("cluster_label", "idxc1")

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f), name=path.rsplit("/", 1)[-1].rsplit(".", 1)[0])

    @property
    def planned_ingest(self):
        return self.ingest * (1 + self.growth) ** self.years

    def placements(self):
        return {o: (factors.placement(self.srf, o, self.peers), factors.placement(self.ssf, o, self.peers))
                for o in self.share}

    def storage(self):
        """GB per site at steady state (full retention), before headroom."""
        daily = {s: 0.0 for s in self.peers}
        for o, (rc, sc) in self.placements().items():
            vol = self.planned_ingest * self.share[o]
            for s in self.peers:
                daily[s] += vol * (self.raw_ratio * rc[s] + self.idx_ratio * sc[s])
        return {s: daily[s] * self.retention for s in daily}

    def bandwidth(self):
        """Average and peak Mbps per direction between sites for replication."""
        flows = {}
        for o, (rc, _) in self.placements().items():
            vol = self.planned_ingest * self.share[o]
            for s, n in rc.items():
                if s != o and n:
                    flows[(o, s)] = flows.get((o, s), 0.0) + vol * self.payload * n
        out = {}
        for k, gb in flows.items():
            avg = gb * 8 * 1024 / 86400.0
            out[k] = {"gb_per_day": gb, "avg_mbps": avg, "peak_mbps": avg * self.peak}
        return out

    def catchup_hours(self):
        """Time to re-replicate copies missed during an outage of outage_hours, using the spare link capacity."""
        backlog_gb = sum(b["gb_per_day"] for b in self.bandwidth().values()) * self.outage_h / 24.0
        spare = self.link_mbps * self.max_util - sum(b["avg_mbps"] for b in self.bandwidth().values())
        if spare <= 0:
            return None, backlog_gb
        return backlog_gb * 8 * 1024 / spare / 3600.0, backlog_gb

    def shc(self):
        members = {s["name"]: int(s.get("search_heads", 0)) for s in self.sites}
        return members, sum(members.values())

    def site_loss(self, lost):
        """What happens when one site is lost."""
        res = {"site": lost, "issues": [], "ok": []}
        survivors = [s for s in self.peers if s != lost]
        for o, (rc, sc) in self.placements().items():
            raw_left = sum(rc[s] for s in survivors)
            srch_left = sum(sc[s] for s in survivors)
            label = "data that arrives at %s" % o
            if raw_left == 0:
                res["issues"].append(("critical", "%s: no copy outside %s; buckets are lost until the site returns" % (label, lost)))
            elif srch_left == 0:
                res["issues"].append(("high", "%s: %d copy(ies) survive but none is searchable; searches return partial "
                                              "results until fixup builds index files" % (label, raw_left)))
            else:
                res["ok"].append("%s: %d copy(ies), %d searchable, survive" % (label, raw_left, srch_left))
        if self.share.get(lost):
            res["issues"].append(("medium", "%.0f%% of ingest normally lands at %s; forwarders must fail over (indexer discovery "
                                            "with forwarder_site_failover, or a second output group)" % (100 * self.share[lost], lost)))
        members, n = self.shc()
        if n:
            maj = n // 2 + 1
            left = n - members.get(lost, 0)
            if left == 0:
                res["issues"].append(("high", "no search head survives"))
            elif left < maj:
                res["issues"].append(("high", "search head cluster keeps %d of %d members; %d are needed to elect a captain. "
                                              "Run the static captain procedure on %s" % (left, n, maj, ", ".join(survivors))))
            else:
                res["ok"].append("search head cluster keeps %d of %d members, majority %d" % (left, n, maj))
        cms = [s for s in self.cm_sites if s != lost]
        active_lost = bool(self.cm_sites) and self.cm_sites[0] == lost
        if not cms:
            res["issues"].append(("high", "no cluster manager survives; peers keep running but no bucket fixup or peer "
                                          "changes happen until a manager is restored"))
        elif active_lost and self.cm_mode != "auto":
            res["issues"].append(("medium", "standby cluster manager at %s must be activated manually and DNS or the load "
                                            "balancer switched" % ", ".join(cms)))
        elif active_lost:
            res["ok"].append("standby cluster manager at %s takes over automatically" % cms[0])
        else:
            res["ok"].append("active cluster manager at %s is unaffected" % self.cm_sites[0])
        surv_peers = sum(self.peers[s] for s in survivors)
        if surv_peers < self.srf.total:
            res["issues"].append(("medium", "%d surviving indexers cannot hold total:%d copies; the cluster stays below "
                                            "its replication factor until %s returns" % (surv_peers, self.srf.total, lost)))
        return res

    def checks(self):
        errors, warnings = factors.validate(self.srf, self.ssf, self.peers)
        members, n = self.shc()
        if 0 < n < 3:
            warnings.append("a search head cluster needs at least 3 members")
        if n and max(members.values()) * 2 == n:
            warnings.append("search heads are split evenly; losing either site loses the captain majority. "
                            "Put the majority on the primary site")
        if not self.cm_sites:
            warnings.append("no site hosts a cluster manager")
        elif len(self.cm_sites) == 1:
            warnings.append("single cluster manager at %s; consider cluster manager redundancy "
                            "(manager_switchover_mode) with a standby at another site" % self.cm_sites[0])
        for k, b in self.bandwidth().items():
            if b["peak_mbps"] > self.link_mbps * self.max_util:
                warnings.append("replication %s -> %s peaks at %.0f Mbps, above %.0f%% of the %g Mbps link" % (
                    k[0], k[1], b["peak_mbps"], 100 * self.max_util, self.link_mbps))
        for o, (_, sc) in self.placements().items():
            for s, n in sc.items():
                if n == 0:
                    warnings.append("data that arrives at %s has no searchable copy at %s; search affinity there "
                                    "will reach across sites" % (o, s))
        return errors, warnings
