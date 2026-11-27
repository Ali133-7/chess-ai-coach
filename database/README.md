# Database release snapshot

`public-knowledge.sqlite3.gz` is a newly constructed, allowlisted export of the server's public chess reference data. It is **not the production user database**. See `manifest.json` for the export timestamp, exact table counts, SHA-256 hashes and licence scope.

Snapshot: **23 November 2026, 19:36 UTC / 22:36 Baghdad**. Includes 3,865 openings, 37,700 opening-path entries, 1,500 master games with 131,696 recorded plies, and 5,048 puzzles including 48 published generated exercises. Compressed size: 13,421,300 bytes.

- `studio.schema.sql`: current application schema, including administration, memberships, payments and promotions; **no rows**.
- `knowledge.schema.sql`: current knowledge schema; **no rows**.
- `public-knowledge.sqlite3.gz`: public opening graph, CC0 puzzle corpus, CC BY-SA master games and their published generated exercises.
- `manifest.json`: reproducibility and integrity metadata.

User accounts and password hashes, sessions, personal games/progress, payment orders/purchase tokens, merchant settings/credentials, audit records and runtime caches are excluded. A separate private backup remains on the server; Git is not a backup of those records. The exporter builds a new SQLite database by inserting allowed records, so deleted/free pages from a private source database cannot leak into the artifact.

Licences, original source URLs and change notices remain in the database and [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). Generated exercises are derived from public master games, include Stockfish evidence and AI notes, and do not carry a calibrated Elo rating. Unpublished exercises and private-game derivatives are excluded.

To inspect safely, decompress into a **new directory**, verify `sqlite_sha256` from the manifest and run `PRAGMA integrity_check` and `PRAGMA foreign_key_check`. Do not overwrite a running `studio.sqlite3` or `knowledge.sqlite3`. Use the normal [installation/bootstrap guide](../README.md) for a new deployment; its setup functions create missing runtime tables safely.

From the repository root, validate hashes, table counts, both empty schemas, every puzzle's legal move sequence and the published exercises' master-game provenance:

```bash
python -m scripts.verify_public_database database
```

To regenerate an export from consistent private backup files:

```bash
python scripts/export_public_database.py \
  --studio /private-backup/studio.sqlite3 \
  --knowledge /private-backup/knowledge.sqlite3 \
  --output /review/public-database
```

Review the manifest and tests before copying only the output directory into Git. Never copy the private input files, key directories or backup folder.

## Expanded local game library — 25 November 2026

The separate [multi-source game-library release](https://github.com/Ali133-7/chess-ai-coach/releases/tag/multi-source-games-2026-11-25) contains **1,051,601 unique accepted records**, **90,580,594 recorded plies** and **74,860,494 numerical source annotations**. It combines **1,025,382** games from all 82 pinned Lichess broadcast archives with **26,219** historical records from Ana Schaigorodsky's Figshare v1 deposit. Only **52,809** explicitly identify both players as GM. Source-provided years span 1749–2026; this is not independent historical authentication. Exact scopes, archive checkpoints, counters, source licenses and merge receipts are in [game-library-manifest.json](game-library-manifest.json). Source engine settings are unknown; missing scores remain unscored.

Download the gzip and manifest together from the release assets. The **1,515,941,183-byte gzip** (2,927,587,328 bytes unpacked) is not duplicated in Git history. [library.schema.sql](library.schema.sql) contains only the optional v2 catalogue schema; [GAME_LIBRARY_LICENSE.txt](GAME_LIBRARY_LICENSE.txt) records attribution and changes. Update application code before installing v2, as described in [safe installation and analysis limits](../docs/OPEN_GAME_LIBRARY.md). Install it as **master-library.sqlite3**, separately from account and knowledge databases. All mainlines were checked during import; the manifest explicitly reports that this large release was not subjected to another complete mainline pass during packaging. No account, secret, payment or private player-history rows enter the artifact.

The adapted combined collection is CC BY-SA 4.0, while original Figshare records retain CC BY 4.0 and Ana Schaigorodsky's attribution, including individual PGN export. The historical source is partially selected in this snapshot; a separate finite full import on the project server does not change this immutable release. The older GM-only release remains available with its [original v1 manifest](game-library-manifest-gm-2026-11-25.json). See [source research and reproduction](../docs/GAME_SOURCE_RESEARCH.md).

## Tal supplement — 27 November 2026

The [additive Tal release](https://github.com/Ali133-7/chess-ai-coach/releases/tag/tal-games-2026-11-27) contains **1,999 games / 138,197 recorded plies**, source-provided years 1949–1992, CC BY 4.0 with Ana Schaigorodsky's attribution. See [tal-supplement-manifest.json](tal-supplement-manifest.json), [tal-selection.json](tal-selection.json), and [name matching, evidence and safe additive installation](../docs/TAL_SEARCH.md). Use `scripts/apply_game_library_supplement.py` to merge it into an existing catalogue. On the project server it added 1,942 IDs, retained the 57 already present, and preserved all existing records; the combined study view then contained 1,053,903 games. The base million-game release above remains immutable.
