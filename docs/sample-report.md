# Design comparison

| Design | SRF | SSF | Indexers | Total storage | Peak replication Mbps | Lose primary | Errors |
|---|---|---|---|---|---|---|---|
| Active/passive, 4 indexers primary, 2 DR | origin:2,total:3 | origin:1,total:2 | 4 + 2 | 59.6 TB | 6 | high (4 issues) | 0 |
| Active/passive, 4 + 4 indexers, searchable copy in DR | origin:2,site1:2,site2:2,total:4 | origin:1,site1:1,site2:1,total:2 | 4 + 4 | 67.4 TB | 12 | high (3 issues) | 0 |
| Invalid: 3 + 2, searchable copies the DR site cannot hold | origin:2,site2:3,total:4 | origin:1,site1:1,total:2 | 3 + 2 | 25.1 TB | 9 | high (4 issues) | 3 |

# Active/passive, 4 indexers primary, 2 DR

Ingest 110 GB/day, 145 GB/day after 2 years at 15% growth, retention 365 days. `site_replication_factor = origin:2,total:3`, `site_search_factor = origin:1,total:2`.

## Copies per bucket

| Data arrives at | site1 | site2 |
|---|---|---|
| site1 (100% of ingest) | 2 (1 searchable) | 1 (1 searchable) |

## Storage at full retention

Using 15% of ingest for compressed rawdata per copy and 35% for index files per searchable copy, plus 25% free space headroom.

| Site | Indexers | Site total | Per indexer | Per indexer with headroom |
|---|---|---|---|---|
| site1 | 4 | 33.7 TB | 8.4 TB | 11.2 TB |
| site2 | 2 | 25.9 TB | 13.0 TB | 17.3 TB |
| **all** | 6 | **59.6 TB** | | |

## Inter-site replication

Assumes peers stream compressed rawdata (15% of ingest) per remote copy and targets build their own index files. Link 1000 Mbps, planning limit 50%.

| From | To | GB/day | Average Mbps | Peak Mbps (x3) |
|---|---|---|---|---|
| site1 | site2 | 21.8 | 2.1 | 6.2 |

After a 24 hour link or site outage, about 22 GB must be re-replicated: roughly 0.1 hours using the spare link capacity.

## Site failure scenarios

### Lose site1

- **medium**: 100% of ingest normally lands at site1; forwarders must fail over (indexer discovery with forwarder_site_failover, or a second output group)
- **high**: search head cluster keeps 1 of 4 members; 3 are needed to elect a captain. Run the static captain procedure on site2
- **medium**: standby cluster manager at site2 must be activated manually and DNS or the load balancer switched
- **medium**: 2 surviving indexers cannot hold total:3 copies; the cluster stays below its replication factor until site1 returns
- ok: data that arrives at site1: 1 copy(ies), 1 searchable, survive

### Lose site2

- ok: data that arrives at site1: 2 copy(ies), 1 searchable, survive
- ok: search head cluster keeps 3 of 4 members, majority 3
- ok: active cluster manager at site1 is unaffected


# Active/passive, 4 + 4 indexers, searchable copy in DR

Ingest 110 GB/day, 145 GB/day after 2 years at 15% growth, retention 365 days. `site_replication_factor = origin:2,site1:2,site2:2,total:4`, `site_search_factor = origin:1,site1:1,site2:1,total:2`.

## Copies per bucket

| Data arrives at | site1 | site2 |
|---|---|---|
| site1 (100% of ingest) | 2 (1 searchable) | 2 (1 searchable) |

## Storage at full retention

Using 15% of ingest for compressed rawdata per copy and 35% for index files per searchable copy, plus 25% free space headroom.

| Site | Indexers | Site total | Per indexer | Per indexer with headroom |
|---|---|---|---|---|
| site1 | 4 | 33.7 TB | 8.4 TB | 11.2 TB |
| site2 | 4 | 33.7 TB | 8.4 TB | 11.2 TB |
| **all** | 8 | **67.4 TB** | | |

## Inter-site replication

Assumes peers stream compressed rawdata (15% of ingest) per remote copy and targets build their own index files. Link 1000 Mbps, planning limit 50%.

| From | To | GB/day | Average Mbps | Peak Mbps (x3) |
|---|---|---|---|---|
| site1 | site2 | 43.6 | 4.1 | 12.4 |

After a 24 hour link or site outage, about 44 GB must be re-replicated: roughly 0.2 hours using the spare link capacity.

## Site failure scenarios

### Lose site1

- **medium**: 100% of ingest normally lands at site1; forwarders must fail over (indexer discovery with forwarder_site_failover, or a second output group)
- **high**: search head cluster keeps 2 of 5 members; 3 are needed to elect a captain. Run the static captain procedure on site2
- **medium**: standby cluster manager at site2 must be activated manually and DNS or the load balancer switched
- ok: data that arrives at site1: 2 copy(ies), 1 searchable, survive

### Lose site2

- ok: data that arrives at site1: 2 copy(ies), 1 searchable, survive
- ok: search head cluster keeps 3 of 5 members, majority 3
- ok: active cluster manager at site1 is unaffected


# Invalid: 3 + 2, searchable copies the DR site cannot hold

Ingest 110 GB/day, retention 180 days. `site_replication_factor = origin:2,site2:3,total:4`, `site_search_factor = origin:1,site1:1,total:2`.

## Invalid configuration

- **site_replication_factor total:4 is below the required minimum 5**
- **site1 is explicit in site_search_factor but not in site_replication_factor**
- **site2 has 2 indexer(s); it needs at least 3 (max of origin and its site value)**

## Copies per bucket

| Data arrives at | site1 | site2 |
|---|---|---|
| site1 (100% of ingest) | 2 (1 searchable) | 2 (1 searchable) |

## Storage at full retention

Using 15% of ingest for compressed rawdata per copy and 35% for index files per searchable copy, plus 25% free space headroom.

| Site | Indexers | Site total | Per indexer | Per indexer with headroom |
|---|---|---|---|---|
| site1 | 3 | 12.6 TB | 4.2 TB | 5.6 TB |
| site2 | 2 | 12.6 TB | 6.3 TB | 8.4 TB |
| **all** | 5 | **25.1 TB** | | |

## Inter-site replication

Assumes peers stream compressed rawdata (15% of ingest) per remote copy and targets build their own index files. Link 100 Mbps, planning limit 50%.

| From | To | GB/day | Average Mbps | Peak Mbps (x3) |
|---|---|---|---|---|
| site1 | site2 | 33.0 | 3.1 | 9.4 |

After a 24 hour link or site outage, about 33 GB must be re-replicated: roughly 1.6 hours using the spare link capacity.

## Site failure scenarios

### Lose site1

- **medium**: 100% of ingest normally lands at site1; forwarders must fail over (indexer discovery with forwarder_site_failover, or a second output group)
- **high**: search head cluster keeps 2 of 4 members; 3 are needed to elect a captain. Run the static captain procedure on site2
- **high**: no cluster manager survives; peers keep running but no bucket fixup or peer changes happen until a manager is restored
- **medium**: 2 surviving indexers cannot hold total:4 copies; the cluster stays below its replication factor until site1 returns
- ok: data that arrives at site1: 2 copy(ies), 1 searchable, survive

### Lose site2

- **high**: search head cluster keeps 2 of 4 members; 3 are needed to elect a captain. Run the static captain procedure on site1
- **medium**: 3 surviving indexers cannot hold total:4 copies; the cluster stays below its replication factor until site2 returns
- ok: data that arrives at site1: 2 copy(ies), 1 searchable, survive
- ok: active cluster manager at site1 is unaffected

## Warnings

- search heads are split evenly; losing either site loses the captain majority. Put the majority on the primary site
- single cluster manager at site1; consider cluster manager redundancy (manager_switchover_mode) with a standby at another site


