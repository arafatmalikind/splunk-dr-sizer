"""Starting-point .conf files for a design. Secrets are left as placeholders."""

SECRET = "<set from your secrets store>"


def manager(d, cm_name, all_cms):
    site = next(s["name"] for s in d.sites if s["name"] == cm_name)
    lines = ["# server.conf on cluster manager at %s" % site, "[general]", "site = %s" % site, "",
             "[clustering]", "mode = manager", "multisite = true",
             "available_sites = %s" % ",".join(d.peers),
             "site_replication_factor = %s" % d.srf, "site_search_factor = %s" % d.ssf,
             "cluster_label = %s" % d.label, "pass4SymmKey = %s" % SECRET]
    if d.srf.total < 3:
        lines.append("replication_factor = %d" % d.srf.total)
    others = [s for s in d.peers if d.share.get(s)]
    if len(d.peers) > 1 and others:
        pairs = ["%s:%s" % (s, next(x for x in d.peers if x != s)) for s in d.peers]
        lines.append("forwarder_site_failover = %s" % ",".join(pairs))
    if len(all_cms) > 1:
        lines += ["manager_switchover_mode = %s" % (d.cm_mode if d.cm_mode != "disabled" else "manual"),
                  "manager_uri = %s" % ",".join("clustermanager:%s" % c for c in all_cms)]
        for c in all_cms:
            lines += ["", "[clustermanager:%s]" % c, "manager_uri = https://cm-%s.example.internal:8089" % c]
    lines += ["", "[indexer_discovery]", "pass4SymmKey = %s" % SECRET, "indexerWeightByDiskCapacity = true"]
    return "\n".join(lines) + "\n"


def _manager_uri(d):
    if len(d.cm_sites) > 1:
        return "https://cluster-manager.example.internal:8089   # load balancer or DNS name in front of the managers"
    return "https://cm-%s.example.internal:8089" % (d.cm_sites[0] if d.cm_sites else "site1")


def peer(d, site):
    return "\n".join(["# server.conf on every indexer at %s" % site, "[general]", "site = %s" % site, "",
                      "[clustering]", "mode = peer", "manager_uri = %s" % _manager_uri(d), "pass4SymmKey = %s" % SECRET, "",
                      "[replication_port://9887]", ""])


def search_head(d, site):
    return "\n".join([
        "# server.conf on search head cluster members at %s" % site,
        "[general]", "# site0 disables search affinity so every member uses the same primary copies,",
        "# as recommended for search head clusters that span sites", "site = site0", "",
        "[clustering]", "mode = searchhead", "multisite = true", "manager_uri = %s" % _manager_uri(d),
        "pass4SymmKey = %s" % SECRET, ""])


def forwarder(d, site):
    return "\n".join([
        "# outputs.conf on forwarders at %s (set [general] site = %s in their server.conf)" % (site, site),
        "[indexer_discovery:idxc]", "manager_uri = %s" % _manager_uri(d).split()[0], "pass4SymmKey = %s" % SECRET, "",
        "[tcpout:idxc]", "indexerDiscovery = idxc", "useACK = true", "",
        "[tcpout]", "defaultGroup = idxc", ""])


def render(d):
    files = {}
    for c in d.cm_sites:
        files["%s/cluster-manager-server.conf" % c] = manager(d, c, d.cm_sites)
    for s in d.peers:
        files["%s/indexer-server.conf" % s] = peer(d, s)
        files["%s/forwarder-outputs.conf" % s] = forwarder(d, s)
        if any(x["name"] == s and x.get("search_heads") for x in d.sites):
            files["%s/search-head-server.conf" % s] = search_head(d, s)
    return files
