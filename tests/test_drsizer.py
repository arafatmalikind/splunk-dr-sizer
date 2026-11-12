import os

import pytest

from drsizer import configs, factors
from drsizer.cli import main
from drsizer.design import Design

EX = os.path.join(os.path.dirname(__file__), "..", "examples")


def base(**kw):
    d = {"ingest_gb_per_day": 100, "retention_days": 1,
         "sites": [{"name": "site1", "role": "primary", "indexers": 3, "search_heads": 3, "cluster_manager": True},
                   {"name": "site2", "role": "dr", "indexers": 3, "search_heads": 1}],
         "site_replication_factor": "origin:2,total:3", "site_search_factor": "origin:1,total:2"}
    d.update(kw)
    return Design(d)


def test_parse_and_render():
    f = factors.parse("origin:2, site1:1, total:3")
    assert (f.origin, f.total, f.sites) == (2, 3, {"site1": 1}) and str(f) == "origin:2,site1:1,total:3"
    for bad in ("total:3", "origin:2", "origin:x,total:3", "origin:0,total:3", "origin:1,origin:2,total:3"):
        with pytest.raises(ValueError):
            factors.parse(bad)


def test_placement_matches_splunk_documentation_example():
    f = factors.parse("origin:2,site1:1,site2:2,site3:3,total:8")
    peers = {"site1": 9, "site2": 9, "site3": 9, "site4": 9}
    table = {o: list(factors.placement(f, o, peers).values()) for o in peers}
    assert table == {"site1": [2, 2, 3, 1], "site2": [1, 2, 3, 2], "site3": [1, 2, 3, 2], "site4": [1, 2, 3, 2]}


def test_minimum_total_rules():
    sites = ["site1", "site2", "site3"]
    assert factors.minimum_total(factors.parse("origin:3,site1:1,site2:2,site3:3,total:8"), sites) == 8
    assert factors.minimum_total(factors.parse("origin:2,site2:3,total:5"), sites) == 5


def test_validation_errors():
    srf, ssf = factors.parse("origin:2,site2:3,total:4"), factors.parse("origin:1,site1:1,total:2")
    errors, _ = factors.validate(srf, ssf, {"site1": 3, "site2": 2})
    text = " ".join(errors)
    assert "minimum 5" in text and "explicit in site_search_factor" in text and "site2 has 2" in text


def test_total_below_three_warns():
    _, w = factors.validate(factors.parse("origin:1,total:2"), factors.parse("origin:1,total:1"), {"a": 1, "b": 1})
    assert any("replication_factor = 2" in x for x in w)


def test_storage_matches_splunk_worked_example():
    # Splunk docs: 100 GB, RF 3, SF 2 needs 45 GB rawdata + 70 GB index files = 115 GB
    d = base()
    assert round(sum(d.storage().values()), 6) == 115.0


def test_bandwidth_counts_remote_copies():
    d = base(site_replication_factor="origin:2,site1:2,site2:2,total:4", site_search_factor="origin:1,site1:1,site2:1,total:2")
    (bw,) = d.bandwidth().values()
    assert bw["gb_per_day"] == pytest.approx(100 * 0.15 * 2)
    assert bw["avg_mbps"] == pytest.approx(30 * 8 * 1024 / 86400)


def test_site_loss_shc_and_copies():
    d = base()
    lose1 = d.site_loss("site1")
    assert any("static captain" in m for _, m in lose1["issues"])
    assert any("no cluster manager survives" in m for _, m in lose1["issues"])
    lose2 = d.site_loss("site2")
    assert not [i for i in lose2["issues"] if i[0] in ("critical", "high")]


def test_no_searchable_copy_survives():
    d = base(site_search_factor="origin:1,total:1")
    assert any(sev == "high" and "none is searchable" in m for sev, m in d.site_loss("site1")["issues"])


def test_no_copy_survives_is_critical():
    d = base(site_replication_factor="origin:3,total:3", site_search_factor="origin:1,total:1")
    assert d.site_loss("site1")["issues"][0][0] == "critical"


def test_standby_manager_logic():
    sites = [{"name": "site2", "role": "dr", "indexers": 3, "cluster_manager": True},
             {"name": "site1", "role": "primary", "indexers": 3, "search_heads": 3, "cluster_manager": True}]
    d = base(sites=sites, manager_switchover_mode="auto")
    assert d.cm_sites == ["site1", "site2"]
    assert any("takes over automatically" in m for m in d.site_loss("site1")["ok"])
    assert any("unaffected" in m for m in d.site_loss("site2")["ok"])


def test_even_shc_split_warns():
    d = base(sites=[{"name": "site1", "role": "primary", "indexers": 3, "search_heads": 2, "cluster_manager": True},
                    {"name": "site2", "indexers": 3, "search_heads": 2}])
    assert any("split evenly" in w for w in d.checks()[1])


def test_generated_configs():
    d = Design.load(os.path.join(EX, "active-passive-4x4.json"))
    files = configs.render(d)
    cm = files["site1/cluster-manager-server.conf"]
    assert "site_replication_factor = origin:2,site1:2,site2:2,total:4" in cm
    assert "manager_switchover_mode = manual" in cm and "[clustermanager:site2]" in cm
    assert "site = site0" in files["site2/search-head-server.conf"]
    assert "pass4SymmKey = <set from your secrets store>" in files["site1/indexer-server.conf"]


def test_cli(tmp_path):
    out = tmp_path / "r.md"
    assert main(["report", os.path.join(EX, "active-passive-4x2.json"), os.path.join(EX, "broken-3x2.json"),
                 "-o", str(out), "--fail-on-error"]) == 1
    assert out.read_text().startswith("# Design comparison")
    assert main(["config", os.path.join(EX, "active-passive-4x2.json"), "-o", str(tmp_path / "g")]) == 0
    assert (tmp_path / "g" / "site2" / "indexer-server.conf").exists()
