# Third-party data and components

- **Historical chess records (Figshare 4276523 v1)**: Ana Schaigorodsky (2016), *Chess Database*, DOI <https://doi.org/10.6084/m9.figshare.4276523.v1>, CC BY 4.0. Numerical records/mainlines are selected and validated; names/dates are retained, human commentary and variations removed. Source archive integrity and exact import policy are recorded in `studio/knowledge/data/historical-source.json`. Related study: Schaigorodsky, Perotti and Billoni, PLOS ONE 11(12):e0168213. The combined collection and application-generated board notes are CC BY-SA 4.0; individual source records/PGN retain their source license. See `docs/GAME_SOURCE_RESEARCH.md`.

- **Expanded local game library**: built from the official monthly Lichess broadcast archives, explicitly CC BY-SA 4.0 (the broadcast section has its own license). Every accepted game retains its source URL, archive SHA-256 and ordinal. The release manifest records exact coverage and filtering. See `docs/OPEN_GAME_LIBRARY.md`; this does not incorporate Chessgames.com archives or member annotations.

- **Lichess chess openings**: pinned TSV revision and SHA-256 values in `studio/knowledge/data/manifest.json`, CC0-1.0. Source: <https://github.com/lichess-org/chess-openings>.
- **Lichess puzzle and evaluation samples**: bounded samples, source details, checksums and licensing in the same manifest. Source: <https://database.lichess.org/>. The bundled sample is not the entire Lichess database.
- **1500 master games and derived annotations**: CC BY-SA 4.0; retain attribution and changes notice in `studio/knowledge/data/MASTER_GAMES_LICENSE.txt` and `master-games-manifest.json`. Original source links remain in each game. The compressed SQLite file contains public game data only.
- **Generated exercises**: selected public game positions with bounded Stockfish analysis and AI-authored bilingual notes; source links and provenance are retained in the bundled public JSON. No calibrated Elo is claimed.
- **Syzygy generated three-piece tables**: source URLs, checksums and redistribution terms in `manifest.json`; <https://github.com/syzygy1/tb#terms-of-use>.
- **Stockfish**: installed by the Dockerfile from the operating-system package repository; separately licensed GPLv3 software, <https://stockfishchess.org/>. No local Windows engine binary is committed here.
- **python-chess and Python/JavaScript dependencies**: retain their upstream licenses when redistributing dependencies. Runtime requirements and UI-test dependencies are declared in `requirements.txt` and `package.json`.

The responsive interface was written within this project's existing components. Reference projects and educational design sources are documented in `docs/interface-review-ar.txt`; their code was not imported as a new dependency.

- **Pillow 13.0.0**: bounded raster poster decoding and metadata-free re-encoding; MIT-CMU. Source and licence: <https://github.com/python-pillow/Pillow>. Preserve its bundled licence when redistributing dependencies.
