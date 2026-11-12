# splunk-dr-sizer

Size, validate and stress-test a multisite Splunk Enterprise design for disaster recovery before you build it.

Describe the sites, indexers, search heads, cluster managers, `site_replication_factor` and `site_search_factor` in a small JSON file. The tool tells you:

- whether the factors are valid for that design, using the documented rules (the manager refuses to start on an invalid factor, so it is better to find out on paper)
- how many copies, and how many searchable copies, each site holds for data arriving at each site
- storage per site and per indexer at full retention, with growth and headroom
- inter-site replication bandwidth, average and peak, and how long catch-up takes after an outage
- what happens when each site is lost: surviving copies, searchability, search head captain majority, cluster manager failover, forwarder failover
- starting-point `server.conf` and `outputs.conf` for every role

```
drsizer report examples/active-passive-4x2.json examples/active-passive-4x4.json examples/broken-3x2.json
```

| Design | SRF | SSF | Indexers | Total storage | Peak replication Mbps | Lose primary | Errors |
|---|---|---|---|---|---|---|---|
| Active/passive, 4 indexers primary, 2 DR | origin:2,total:3 | origin:1,total:2 | 4 + 2 | 59.6 TB | 6 | high (4 issues) | 0 |
| Active/passive, 4 + 4 indexers, searchable copy in DR | origin:2,site1:2,site2:2,total:4 | origin:1,site1:1,site2:1,total:2 | 4 + 4 | 67.4 TB | 12 | high (3 issues) | 0 |
| Invalid: 3 + 2, searchable copies the DR site cannot hold | origin:2,site2:3,total:4 | origin:1,site1:1,total:2 | 3 + 2 | 25.1 TB | 9 | high (4 issues) | 3 |

Excerpt for the 4 + 2 design, losing the primary site:

> - **medium**: 100% of ingest normally lands at site1; forwarders must fail over (indexer discovery with forwarder_site_failover, or a second output group)
> - **high**: search head cluster keeps 1 of 4 members; 3 are needed to elect a captain. Run the static captain procedure on site2
> - **medium**: standby cluster manager at site2 must be activated manually and DNS or the load balancer switched
> - **medium**: 2 surviving indexers cannot hold total:3 copies; the cluster stays below its replication factor until site1 returns
> - ok: data that arrives at site1: 1 copy(ies), 1 searchable, survive

Full output: [docs/sample-report.md](docs/sample-report.md). Generated configs for the 4 + 4 design: [docs/generated/](docs/generated/).

## Design file

```json
{
  "name": "Active/passive, 4 + 4 indexers",
  "ingest_gb_per_day": 110,
  "growth_pct_per_year": 15,
  "plan_years": 2,
  "retention_days": 365,
  "sites": [
    {"name": "site1", "role": "primary", "indexers": 4, "search_heads": 3, "cluster_manager": true},
    {"name": "site2", "role": "dr", "indexers": 4, "search_heads": 2, "cluster_manager": true}
  ],
  "site_replication_factor": "origin:2,site1:2,site2:2,total:4",
  "site_search_factor": "origin:1,site1:1,site2:1,total:2",
  "manager_switchover_mode": "manual",
  "network": {"inter_site_mbps": 1000, "max_utilisation_pct": 50, "peak_to_average": 3},
  "outage_hours_to_recover": 24
}
```

Optional keys: `ingest_share` (for example `{"site1": 0.7, "site2": 0.3}` for active/active ingestion; default is all ingest at the primary), `compression` (`rawdata`, `index_files`), `free_space_headroom_pct`, `cluster_label`, and `network.replication_payload_ratio`.

## How the numbers are calculated

**Factor validation**, from the Splunk documentation pages "Configure the site replication factor" and "Configure the site search factor":

- `origin` and `total` are required; values are positive integers
- with non-explicit sites, `total` must be at least `origin` plus all explicit site values; when every site is explicit, `origin` replaces the smallest site value in that sum
- every site needs at least max(`origin`, its site value) indexers, and the cluster needs at least `total`
- `site_search_factor` values may not exceed their `site_replication_factor` counterparts, and a site explicit in the search factor must be explicit in the replication factor
- a `total` below 3 needs `replication_factor` set explicitly

**Copy placement** follows the documented algorithm: the origin site gets max(`origin`, its site value), explicit sites get their value, and remaining copies go to non-explicit sites first, then to the site with the fewest copies. The test suite checks this against the four-site example table in the Splunk documentation.

**Storage** uses Splunk's documented rule of thumb: compressed rawdata is about 15% of ingest per copy, and index files are about 35% per searchable copy. The test suite checks the documented worked example (100 GB, replication factor 3, search factor 2, 115 GB in total). Real ratios vary by data type; measure yours with `| dbinspect` and override `compression`.

**Bandwidth** assumes a peer streams the compressed rawdata to each remote copy, and a target holding a searchable copy builds its own index files. Set `replication_payload_ratio` to 0.5 for a conservative upper bound. Forwarder traffic and search traffic between sites are not included.

**Site loss** checks, for each site: whether at least one copy and one searchable copy of every origin's data survive, whether the search head cluster keeps a majority (captain election needs a majority of all members; otherwise the static captain procedure applies), whether a cluster manager survives and how it takes over, and whether the surviving indexers can still hold `total` copies.

## Generated configuration

```
drsizer config examples/active-passive-4x4.json -o generated/
```

The output is one folder per site, with configs for the cluster manager, indexer peer, search head cluster member and forwarder. It includes `multisite`, `available_sites`, both factors, `forwarder_site_failover`, cluster manager redundancy stanzas when more than one manager is defined, `site0` for search heads (recommended when a search head cluster spans sites), and indexer discovery for forwarders. Secrets are placeholders. Review everything against your Splunk version's `server.conf.spec` before deploying, and push peer configuration through the manager as usual.

## What this tool does not decide for you

- Whether active/active or active/passive fits your recovery objectives. Compare the designs side by side and weigh storage cost against what survives a site loss.
- Hardware sizing for search load. Storage and replication are here; CPU and IOPS for your search concurrency are not.
- SmartStore. Remote storage changes both the storage and the DR model, and is out of scope.

## Development

```
pip install -e .[test]
pytest
```

No third-party runtime dependencies. Example designs are fictional.

## License

MIT. See [LICENSE](LICENSE).
