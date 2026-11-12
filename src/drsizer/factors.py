"""site_replication_factor / site_search_factor parsing, validation and copy placement.

Rules follow the Splunk Enterprise documentation, "Configure the site replication
factor" and "Configure the site search factor"."""

import re


class Factor:
    def __init__(self, origin, total, sites):
        self.origin, self.total, self.sites = origin, total, dict(sites)

    def __str__(self):
        parts = ["origin:%d" % self.origin] + ["%s:%d" % kv for kv in self.sites.items()] + ["total:%d" % self.total]
        return ",".join(parts)


def parse(text):
    vals = {}
    for part in str(text).replace(" ", "").split(","):
        m = re.fullmatch(r"([a-z0-9_]+):(\d+)", part)
        if not m:
            raise ValueError("cannot parse %r in %r" % (part, text))
        if m.group(1) in vals:
            raise ValueError("%s given twice in %r" % (m.group(1), text))
        vals[m.group(1)] = int(m.group(2))
    if "origin" not in vals or "total" not in vals:
        raise ValueError("%r: origin and total are required" % text)
    if any(v < 1 for v in vals.values()):
        raise ValueError("%r: values must be positive integers" % text)
    origin, total = vals.pop("origin"), vals.pop("total")
    return Factor(origin, total, vals)


def minimum_total(f, all_sites):
    explicit = set(f.sites)
    if explicit >= set(all_sites):
        vals = sorted(f.sites.values())
        vals[0] = max(vals[0], f.origin)
        return sum(vals)
    return f.origin + sum(f.sites.values())


def validate(srf, ssf, peers):
    """peers: {site: number of indexers}. Returns (errors, warnings)."""
    errors, warnings = [], []
    sites = list(peers)
    for name, f in (("site_replication_factor", srf), ("site_search_factor", ssf)):
        for s in f.sites:
            if s not in peers:
                errors.append("%s names %s, which has no indexers in the design" % (name, s))
        need = minimum_total(f, sites)
        if f.total < need:
            errors.append("%s total:%d is below the required minimum %d" % (name, f.total, need))
    if srf.total < 3:
        warnings.append("site_replication_factor total:%d is below the default replication_factor of 3; "
                        "set replication_factor = %d explicitly or the manager will not start" % (srf.total, srf.total))
    if ssf.origin > srf.origin or ssf.total > srf.total:
        errors.append("site_search_factor origin/total must not exceed site_replication_factor")
    for s, v in ssf.sites.items():
        if s not in srf.sites:
            errors.append("%s is explicit in site_search_factor but not in site_replication_factor" % s)
        elif v > srf.sites[s]:
            errors.append("site_search_factor %s:%d exceeds site_replication_factor %s:%d" % (s, v, s, srf.sites[s]))
    if sum(peers.values()) < srf.total:
        errors.append("%d indexers in total but site_replication_factor total is %d" % (sum(peers.values()), srf.total))
    for s, n in peers.items():
        need = max(srf.origin, srf.sites.get(s, 0))
        if n < need:
            errors.append("%s has %d indexer(s); it needs at least %d (max of origin and its site value)" % (s, n, need))
    return errors, warnings


def placement(f, origin, peers):
    """Expected copies per site for a bucket that originates at `origin`."""
    sites = list(peers)
    copies = {s: 0 for s in sites}
    for s in sites:
        if s == origin:
            copies[s] = max(f.origin, f.sites.get(s, 0))
        else:
            copies[s] = f.sites.get(s, 0)
    remaining = f.total - sum(copies.values())
    while remaining > 0:
        room = [s for s in sites if copies[s] < peers[s]]
        if not room:
            break
        # extra copies go to non-explicit sites first, then to the site with the fewest copies
        s = min(room, key=lambda x: (x in f.sites, copies[x], sites.index(x)))
        copies[s] += 1
        remaining -= 1
    for s in sites:
        copies[s] = min(copies[s], peers[s])
    return copies
