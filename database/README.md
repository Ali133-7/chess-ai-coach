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
