CREATE TABLE kc_daily_runs(day TEXT PRIMARY KEY,target INTEGER NOT NULL,status TEXT NOT NULL,cursor INTEGER NOT NULL DEFAULT 0,scanned INTEGER NOT NULL DEFAULT 0,rejected INTEGER NOT NULL DEFAULT 0,error_code TEXT,lease TEXT,lease_until REAL NOT NULL DEFAULT 0,updated_at TEXT NOT NULL);

CREATE TABLE kc_edges(position_key TEXT NOT NULL,uci TEXT NOT NULL,after_key TEXT NOT NULL,san TEXT NOT NULL,PRIMARY KEY(position_key,uci));

CREATE TABLE kc_evaluations(position_key TEXT NOT NULL,source TEXT NOT NULL,depth INTEGER NOT NULL,cp_white INTEGER,mate_white INTEGER,pv_json TEXT NOT NULL,fen TEXT NOT NULL,engine TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(position_key,source));

CREATE TABLE kc_external_cache(kind TEXT NOT NULL,key TEXT NOT NULL,payload TEXT NOT NULL,updated_at REAL NOT NULL,PRIMARY KEY(kind,key));

CREATE TABLE kc_generated_exercises(puzzle_id TEXT PRIMARY KEY,position_key TEXT NOT NULL UNIQUE,day TEXT NOT NULL,source_game TEXT NOT NULL,source_ply INTEGER NOT NULL,fen_before TEXT NOT NULL,setup_uci TEXT NOT NULL,root_fen TEXT NOT NULL,proof_json TEXT NOT NULL,notes_json TEXT,provider TEXT,model TEXT,status TEXT NOT NULL,created_at TEXT NOT NULL,published_at TEXT);

CREATE TABLE kc_imports(key TEXT PRIMARY KEY,kind TEXT NOT NULL,filename TEXT NOT NULL,sha256 TEXT NOT NULL,cursor INTEGER NOT NULL DEFAULT 0,accepted INTEGER NOT NULL DEFAULT 0,rejected INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'pending',last_error TEXT,updated_at TEXT);

CREATE TABLE kc_master_evals(fen_key TEXT PRIMARY KEY,payload TEXT NOT NULL);

CREATE TABLE kc_master_games(id TEXT PRIMARY KEY,white TEXT NOT NULL,black TEXT NOT NULL,white_title TEXT NOT NULL,black_title TEXT NOT NULL,date TEXT NOT NULL,year INTEGER NOT NULL,event TEXT NOT NULL,result TEXT NOT NULL,eco TEXT NOT NULL,opening TEXT NOT NULL,plies INTEGER NOT NULL,initial_fen TEXT NOT NULL,pgn TEXT NOT NULL,source_url TEXT NOT NULL,archive_sha TEXT NOT NULL,license TEXT NOT NULL,content_hash TEXT NOT NULL UNIQUE);

CREATE TABLE kc_master_imports(sha TEXT PRIMARY KEY,cursor INTEGER NOT NULL DEFAULT 0,accepted INTEGER NOT NULL DEFAULT 0,rejected INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'pending');

CREATE TABLE kc_master_moves(game_id TEXT NOT NULL REFERENCES kc_master_games(id) ON DELETE CASCADE,ply INTEGER NOT NULL,uci TEXT NOT NULL,san TEXT NOT NULL,fen TEXT NOT NULL,note_json TEXT NOT NULL,material_white INTEGER NOT NULL,imported_eval TEXT,PRIMARY KEY(game_id,ply));

CREATE TABLE kc_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);

CREATE TABLE kc_network(name TEXT PRIMARY KEY,next_at REAL NOT NULL DEFAULT 0,last_status INTEGER,lock_until REAL NOT NULL DEFAULT 0,lock_token TEXT);

CREATE TABLE kc_openings(revision TEXT NOT NULL,id TEXT NOT NULL,eco TEXT NOT NULL,name TEXT NOT NULL,family TEXT NOT NULL,pgn TEXT NOT NULL,uci_json TEXT NOT NULL,terminal_key TEXT NOT NULL,plies INTEGER NOT NULL,PRIMARY KEY(revision,id));

CREATE TABLE kc_paths(revision TEXT NOT NULL,opening_id TEXT NOT NULL,ply INTEGER NOT NULL,before_key TEXT NOT NULL,position_key TEXT NOT NULL,fen TEXT NOT NULL,uci TEXT NOT NULL,san TEXT NOT NULL,PRIMARY KEY(revision,opening_id,ply),FOREIGN KEY(revision,opening_id) REFERENCES kc_openings(revision,id));

CREATE TABLE kc_positions(key TEXT PRIMARY KEY,fen TEXT NOT NULL);

CREATE TABLE kc_puzzles(id TEXT PRIMARY KEY,fen TEXT NOT NULL,setup_fen TEXT NOT NULL,moves_json TEXT NOT NULL,rating INTEGER NOT NULL,themes TEXT NOT NULL,opening_tags TEXT NOT NULL,game_url TEXT NOT NULL,source_sha TEXT NOT NULL);

CREATE TABLE kc_sources(key TEXT PRIMARY KEY,url TEXT NOT NULL,license TEXT NOT NULL,revision TEXT,scope TEXT,updated_at TEXT);

CREATE INDEX generated_day ON kc_generated_exercises(day,status);

CREATE INDEX kc_master_year ON kc_master_games(year DESC,date DESC,id);

CREATE INDEX kc_opening_name ON kc_openings(revision,name);

CREATE INDEX kc_opening_terminal ON kc_openings(revision,terminal_key);

CREATE INDEX kc_path_before ON kc_paths(revision,before_key);

CREATE INDEX kc_path_position ON kc_paths(revision,position_key);

CREATE INDEX kc_puzzle_rating ON kc_puzzles(rating);
