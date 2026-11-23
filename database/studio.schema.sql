CREATE TABLE analysis_preferences(user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
       preset TEXT NOT NULL DEFAULT 'fast' CHECK(preset IN ('turbo','fast','balanced','detailed','deep')));

CREATE TABLE app_config(key TEXT PRIMARY KEY,value TEXT NOT NULL);

CREATE TABLE archive_months(user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
       path TEXT, checked_at TEXT, PRIMARY KEY(user_id,path));

CREATE TABLE auth_attempts(key TEXT PRIMARY KEY, n INTEGER, expires_at INTEGER);

CREATE TABLE control_ad_deliveries(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),campaign_id TEXT NOT NULL REFERENCES control_ads(id),created_at REAL NOT NULL,clicked_at REAL, shown_at REAL);

CREATE TABLE control_ad_events(user_id INTEGER NOT NULL REFERENCES users(id),event TEXT NOT NULL,resource TEXT NOT NULL,created_at REAL NOT NULL,PRIMARY KEY(user_id,event,resource));

CREATE TABLE control_ads(id TEXT PRIMARY KEY,title_ar TEXT NOT NULL,title_en TEXT NOT NULL,body_ar TEXT NOT NULL,body_en TEXT NOT NULL,image_path TEXT NOT NULL,link_url TEXT NOT NULL,button_ar TEXT NOT NULL,button_en TEXT NOT NULL,placement TEXT NOT NULL,event TEXT NOT NULL,after_n INTEGER NOT NULL,daily_cap INTEGER NOT NULL,cooldown_minutes INTEGER NOT NULL,plan_id TEXT,enabled INTEGER NOT NULL,starts_at REAL NOT NULL,ends_at REAL NOT NULL,priority INTEGER NOT NULL,version INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL);

CREATE TABLE control_audit(id INTEGER PRIMARY KEY,actor_id INTEGER,action TEXT NOT NULL,target TEXT NOT NULL,details_json TEXT NOT NULL,created_at TEXT NOT NULL);

CREATE TABLE control_discounts(code TEXT PRIMARY KEY,kind TEXT NOT NULL,value INTEGER NOT NULL CHECK(value>0),enabled INTEGER NOT NULL,starts_at REAL NOT NULL,ends_at REAL NOT NULL,max_uses INTEGER NOT NULL CHECK(max_uses>0),per_user INTEGER NOT NULL CHECK(per_user>0),plan_id TEXT,version INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL);

CREATE TABLE control_gateway_versions(id TEXT PRIMARY KEY,name TEXT NOT NULL,environment TEXT NOT NULL,public_json TEXT NOT NULL,secrets_json TEXT NOT NULL,created_at TEXT NOT NULL);

CREATE TABLE control_gateways(name TEXT PRIMARY KEY,enabled INTEGER NOT NULL DEFAULT 0,environment TEXT NOT NULL DEFAULT 'sandbox',version_id TEXT,updated_at TEXT NOT NULL);

CREATE TABLE control_memberships(user_id INTEGER PRIMARY KEY REFERENCES users(id),plan_id TEXT NOT NULL REFERENCES control_plans(id),starts_at REAL NOT NULL,expires_at REAL NOT NULL,source TEXT NOT NULL,reference TEXT NOT NULL,updated_at TEXT NOT NULL);

CREATE TABLE control_orders(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),plan_id TEXT NOT NULL REFERENCES control_plans(id),plan_title TEXT NOT NULL,days INTEGER NOT NULL,original_amount INTEGER NOT NULL,amount INTEGER NOT NULL,currency TEXT NOT NULL DEFAULT 'IQD',discount_code TEXT,gateway TEXT NOT NULL,gateway_version TEXT,status TEXT NOT NULL,provider_id TEXT,checkout_json TEXT,callback_hash TEXT NOT NULL,request_key TEXT NOT NULL,created_at REAL NOT NULL,expires_at REAL NOT NULL,paid_at REAL,last_check REAL NOT NULL DEFAULT 0,UNIQUE(user_id,request_key),UNIQUE(gateway,provider_id));

CREATE TABLE control_plans(id TEXT PRIMARY KEY,title_ar TEXT NOT NULL,title_en TEXT NOT NULL,description_ar TEXT NOT NULL,description_en TEXT NOT NULL,price_iqd INTEGER NOT NULL CHECK(price_iqd>=0),days INTEGER NOT NULL CHECK(days>0),enabled INTEGER NOT NULL,features_json TEXT NOT NULL,limits_json TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL);

CREATE TABLE control_play_purchases(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),gateway_version TEXT NOT NULL,product_id TEXT NOT NULL,plan_id TEXT NOT NULL REFERENCES control_plans(id),order_id TEXT NOT NULL,expires_at REAL NOT NULL,state TEXT NOT NULL,token_ref TEXT NOT NULL,last_check REAL NOT NULL,UNIQUE(order_id));

CREATE TABLE control_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);

CREATE TABLE control_usage(user_id INTEGER NOT NULL REFERENCES users(id),day TEXT NOT NULL,feature TEXT NOT NULL,n INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user_id,day,feature));

CREATE TABLE games(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
       external_id TEXT NOT NULL,url TEXT NOT NULL,pgn TEXT NOT NULL,finished_at INTEGER NOT NULL,
       white TEXT NOT NULL, black TEXT NOT NULL, result TEXT NOT NULL, time_class TEXT,
       stage TEXT NOT NULL DEFAULT 'pending', completed_positions INTEGER DEFAULT 0,total_positions INTEGER DEFAULT 0,
       error TEXT,created_at TEXT NOT NULL, updated_at TEXT,
       UNIQUE(user_id,external_id));

CREATE TABLE groq_training_games (
          id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          player_color TEXT NOT NULL, moves_json TEXT NOT NULL DEFAULT '[]',
          version INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active',
          busy_token TEXT, busy_until REAL NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, level TEXT NOT NULL DEFAULT 'strong');

CREATE TABLE groq_training_usage (
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          day TEXT NOT NULL, requests INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id,day));

CREATE TABLE knowledge_game_reports(game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,fingerprint TEXT NOT NULL,report_json TEXT NOT NULL,updated_at TEXT NOT NULL);

CREATE TABLE knowledge_puzzle_history(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,puzzle_id TEXT NOT NULL,status TEXT NOT NULL,first_seen_at TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(user_id,puzzle_id));

CREATE TABLE knowledge_puzzle_sessions(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,puzzle_id TEXT NOT NULL,cursor INTEGER NOT NULL DEFAULT 1,version INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'active',mistakes INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,played_json TEXT);

CREATE TABLE knowledge_usage(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,day TEXT NOT NULL,engine_calls INTEGER NOT NULL DEFAULT 0,external_calls INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user_id,day));

CREATE TABLE learning_ai_plans(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,fingerprint TEXT NOT NULL,status TEXT NOT NULL,payload TEXT,provider TEXT,model TEXT,error_code TEXT,done_json TEXT NOT NULL DEFAULT '[]',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);

CREATE TABLE learning_placement_results(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,revision TEXT NOT NULL,result_json TEXT NOT NULL,created_at TEXT NOT NULL);

CREATE TABLE learning_placement_sessions(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,revision TEXT NOT NULL,version INTEGER NOT NULL,state_json TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);

CREATE TABLE learning_progress(
   user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
   revision TEXT NOT NULL,lesson_id TEXT NOT NULL,completed_at TEXT NOT NULL,
   independent INTEGER NOT NULL DEFAULT 0,review_count INTEGER NOT NULL DEFAULT 0,
   due_at TEXT NOT NULL,last_session TEXT NOT NULL,
   PRIMARY KEY(user_id,revision,lesson_id));

CREATE TABLE learning_rating_snapshots(user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,username TEXT NOT NULL,payload TEXT NOT NULL,fetched_at REAL NOT NULL);

CREATE TABLE learning_sessions(
   id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
   revision TEXT NOT NULL,lesson_id TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 0,
   state_json TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);

CREATE TABLE lesson_attempts(user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
       lesson_id TEXT, passed INTEGER DEFAULT 0, attempts INTEGER DEFAULT 0,passed_at TEXT,
       PRIMARY KEY(user_id,lesson_id));

CREATE TABLE lesson_solves(user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
       lesson_id TEXT,game_id INTEGER REFERENCES games(id) ON DELETE CASCADE,
       ply INTEGER, solved_at TEXT,PRIMARY KEY(user_id,lesson_id,game_id,ply));

CREATE TABLE moves(game_id INTEGER REFERENCES games(id) ON DELETE CASCADE,ply INTEGER,
       san TEXT NOT NULL,uci TEXT NOT NULL,fen_before TEXT NOT NULL,fen_after TEXT NOT NULL,
       grade TEXT NOT NULL, loss_cp INTEGER, eval_cp_white INTEGER, best_uci TEXT,best_san TEXT,
       book_name TEXT, lines_json TEXT, phase TEXT, PRIMARY KEY(game_id,ply));

CREATE TABLE position_scans(game_id INTEGER REFERENCES games(id) ON DELETE CASCADE,ply INTEGER,
       fen TEXT NOT NULL, scan_json TEXT NOT NULL, PRIMARY KEY(game_id,ply));

CREATE TABLE ratings(user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
       format TEXT, rating INTEGER, best INTEGER, wins INTEGER,losses INTEGER,draws INTEGER,updated_at TEXT,
       PRIMARY KEY(user_id,format));

CREATE TABLE sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
       csrf TEXT NOT NULL,expires_at INTEGER NOT NULL);

CREATE TABLE teacher_cache (
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          key TEXT NOT NULL,reply_json TEXT NOT NULL,created_at TEXT NOT NULL,
          PRIMARY KEY(user_id,key));

CREATE TABLE teacher_messages (
          id INTEGER PRIMARY KEY,thread_id INTEGER NOT NULL REFERENCES teacher_threads(id) ON DELETE CASCADE,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          ply INTEGER NOT NULL,role TEXT NOT NULL CHECK(role IN ('user','assistant')),
          content TEXT NOT NULL,created_at TEXT NOT NULL);

CREATE TABLE teacher_threads (
          id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
          title TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);

CREATE TABLE teacher_usage (
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          day TEXT NOT NULL,requests INTEGER NOT NULL DEFAULT 0,
          input_tokens INTEGER NOT NULL DEFAULT 0,output_tokens INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(user_id,day));

CREATE TABLE training_coach_usage (
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          day TEXT NOT NULL, analyses INTEGER NOT NULL DEFAULT 0, explanations INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(user_id,day));

CREATE TABLE training_move_coaching (
          game_id TEXT NOT NULL REFERENCES groq_training_games(id) ON DELETE CASCADE,
          ply INTEGER NOT NULL, analysis_json TEXT, reply_json TEXT,
          lock_token TEXT, lock_until REAL NOT NULL DEFAULT 0, PRIMARY KEY(game_id,ply));

CREATE TABLE users(id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, pass_hash TEXT NOT NULL,
       chess_username TEXT, theme TEXT NOT NULL DEFAULT 'dark', board_theme TEXT DEFAULT 'classic', target_rating INTEGER DEFAULT 1000,
       rating_format TEXT DEFAULT 'rapid', role TEXT NOT NULL DEFAULT 'user', created_at TEXT NOT NULL,
       disabled INTEGER NOT NULL DEFAULT 0);

CREATE TABLE worker_state(key TEXT PRIMARY KEY,value TEXT NOT NULL);

CREATE INDEX control_ad_user ON control_ad_deliveries(user_id,campaign_id,created_at);

CREATE INDEX control_order_status ON control_orders(status,created_at);

CREATE UNIQUE INDEX idx_groq_one_active ON groq_training_games(user_id) WHERE status='active';

CREATE INDEX idx_groq_training_owner ON groq_training_games(user_id,updated_at DESC);

CREATE INDEX idx_knowledge_moves_fen ON moves(fen_before,game_id);

CREATE INDEX idx_studio_games ON games(user_id,finished_at DESC);

CREATE INDEX idx_studio_move_grade ON moves(game_id,grade);

CREATE INDEX idx_studio_queue ON games(stage,finished_at DESC);

CREATE INDEX idx_teacher_messages ON teacher_messages(thread_id,id);

CREATE INDEX idx_teacher_threads ON teacher_threads(user_id,updated_at DESC);

CREATE INDEX knowledge_reports_owner ON knowledge_game_reports(user_id,game_id);

CREATE INDEX learning_due ON learning_progress(user_id,revision,due_at);

CREATE INDEX learning_plan_context ON learning_ai_plans(user_id,fingerprint,status);

CREATE INDEX learning_plan_owner ON learning_ai_plans(user_id,created_at);

CREATE INDEX learning_session_owner ON learning_sessions(user_id,revision,lesson_id,updated_at);

CREATE INDEX placement_result_owner ON learning_placement_results(user_id,created_at);

CREATE INDEX placement_session_owner ON learning_placement_sessions(user_id,updated_at);

CREATE INDEX puzzle_session_owner ON knowledge_puzzle_sessions(user_id,puzzle_id,status);
