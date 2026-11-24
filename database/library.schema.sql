-- Public compact multi-source library schema v2; no game/account/credential rows.
CREATE TABLE IF NOT EXISTS library_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS library_archives(url TEXT PRIMARY KEY,sha256 TEXT NOT NULL,scope TEXT NOT NULL,cursor INTEGER NOT NULL DEFAULT 0,accepted INTEGER NOT NULL DEFAULT 0,duplicates INTEGER NOT NULL DEFAULT 0,rejected INTEGER NOT NULL DEFAULT 0,skipped INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'pending',reasons_json TEXT NOT NULL DEFAULT '{}',source_id TEXT NOT NULL DEFAULT 'lichess-broadcasts');
  CREATE TABLE IF NOT EXISTS library_games(id TEXT PRIMARY KEY,white TEXT NOT NULL,black TEXT NOT NULL,white_title TEXT NOT NULL,black_title TEXT NOT NULL,date TEXT NOT NULL,year INTEGER NOT NULL,event TEXT NOT NULL,result TEXT NOT NULL,eco TEXT NOT NULL,opening TEXT NOT NULL,plies INTEGER NOT NULL,initial_fen TEXT NOT NULL,pgn_z BLOB NOT NULL,evals_z BLOB NOT NULL,source_url TEXT NOT NULL,archive_url TEXT NOT NULL REFERENCES library_archives(url),license TEXT NOT NULL,source_eval_count INTEGER NOT NULL);
  CREATE INDEX IF NOT EXISTS library_games_date ON library_games(date DESC,id);
  CREATE INDEX IF NOT EXISTS library_games_year ON library_games(year,date DESC,id);
  CREATE INDEX IF NOT EXISTS library_games_gm ON library_games(white_title,black_title,date DESC,id);
  CREATE INDEX IF NOT EXISTS library_games_eco ON library_games(eco,date DESC,id);
  CREATE TABLE IF NOT EXISTS library_provenance(game_id TEXT NOT NULL REFERENCES library_games(id) ON DELETE CASCADE,archive_url TEXT NOT NULL REFERENCES library_archives(url),ordinal INTEGER NOT NULL,PRIMARY KEY(game_id,archive_url));
  CREATE VIRTUAL TABLE IF NOT EXISTS library_search USING fts5(white,black,event,opening,eco,content='library_games',content_rowid='rowid',tokenize='unicode61 remove_diacritics 2');
  CREATE TRIGGER IF NOT EXISTS library_search_insert AFTER INSERT ON library_games BEGIN INSERT INTO library_search(rowid,white,black,event,opening,eco) VALUES(new.rowid,new.white,new.black,new.event,new.opening,new.eco); END;
CREATE TABLE IF NOT EXISTS library_sources(id TEXT PRIMARY KEY,name TEXT NOT NULL,page TEXT NOT NULL,license TEXT NOT NULL,license_url TEXT NOT NULL,attribution TEXT NOT NULL,evidence TEXT NOT NULL,category TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS library_merges(id TEXT PRIMARY KEY,source_sha256 TEXT NOT NULL,source_schema INTEGER NOT NULL,games_read INTEGER NOT NULL,games_added INTEGER NOT NULL,duplicates INTEGER NOT NULL,merged_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS library_archive_source ON library_archives(source_id);
CREATE INDEX IF NOT EXISTS library_game_archive ON library_games(archive_url,date DESC,id);
CREATE INDEX IF NOT EXISTS library_provenance_archive ON library_provenance(archive_url,game_id);
