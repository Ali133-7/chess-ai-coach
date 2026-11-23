# Third-party data and components

- **Lichess chess openings**: pinned TSV revision and SHA-256 values in `studio/knowledge/data/manifest.json`, CC0-1.0. Source: <https://github.com/lichess-org/chess-openings>.
- **Lichess puzzle and evaluation samples**: bounded samples, source details, checksums and licensing in the same manifest. Source: <https://database.lichess.org/>. The bundled sample is not the entire Lichess database.
- **1500 master games and derived annotations**: CC BY-SA 4.0; retain attribution and changes notice in `studio/knowledge/data/MASTER_GAMES_LICENSE.txt` and `master-games-manifest.json`. Original source links remain in each game. The compressed SQLite file contains public game data only.
- **Generated exercises**: selected public game positions with bounded Stockfish analysis and AI-authored bilingual notes; source links and provenance are retained in the bundled public JSON. No calibrated Elo is claimed.
- **Syzygy generated three-piece tables**: source URLs, checksums and redistribution terms in `manifest.json`; <https://github.com/syzygy1/tb#terms-of-use>.
- **Stockfish**: installed by the Dockerfile from the operating-system package repository; separately licensed GPLv3 software, <https://stockfishchess.org/>. No local Windows engine binary is committed here.
- **python-chess and Python/JavaScript dependencies**: retain their upstream licenses when redistributing dependencies. Runtime requirements and UI-test dependencies are declared in `requirements.txt` and `package.json`.

The responsive interface was written within this project's existing components. Reference projects and educational design sources are documented in `docs/interface-review-ar.txt`; their code was not imported as a new dependency.
