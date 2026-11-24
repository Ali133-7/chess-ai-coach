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

The separate [game-library release](https://github.com/Ali133-7/chess-ai-coach/releases/tag/local-games-2026-11-25) contains **52,809 completed GM-vs-GM game records**, **4,661,211 recorded plies** and **4,070,105 numerical source annotations** (2019–2026). All 82 monthly files in the pinned Lichess broadcast list were processed: 1,299,343 source records, with acceptance, duplicate, rejection and skip counts in [game-library-manifest.json](game-library-manifest.json). Source annotations have unknown engine settings; missing scores remain unscored.

Download the gzip and manifest together from the release assets. The 71,985,972-byte gzip is not duplicated in Git history. [library.schema.sql](library.schema.sql) contains only the optional catalogue schema; [GAME_LIBRARY_LICENSE.txt](GAME_LIBRARY_LICENSE.txt) records attribution and changes. Install it as **master-library.sqlite3**, separately from account and knowledge databases. See [installation and analysis limits](../docs/OPEN_GAME_LIBRARY.md). All recorded mainlines were checked on import and rechecked during packaging. No account, secret, payment or private player-history rows enter this artifact.
