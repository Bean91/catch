CREATE TABLE daily_wellness (
	date DATE NOT NULL, 
	source VARCHAR NOT NULL, 
	resting_hr INTEGER, 
	hrv_rmssd FLOAT, 
	sleep_seconds INTEGER, 
	deep_sleep_seconds INTEGER, 
	light_sleep_seconds INTEGER, 
	rem_sleep_seconds INTEGER, 
	awake_sleep_seconds INTEGER, 
	sleep_score INTEGER, 
	stress INTEGER, 
	body_battery INTEGER, 
	spo2 FLOAT, 
	respiration FLOAT, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (date)
);
CREATE TABLE activities (
	id INTEGER NOT NULL, 
	source VARCHAR NOT NULL, 
	external_id VARCHAR NOT NULL, 
	type VARCHAR, 
	start DATETIME, 
	duration FLOAT, 
	distance FLOAT, 
	avg_hr FLOAT, 
	max_hr FLOAT, 
	avg_power FLOAT, 
	calories FLOAT, 
	raw_json VARCHAR, 
	fit_path VARCHAR, 
	updated_at DATETIME NOT NULL, workout_type TEXT, drag_factor INTEGER, stroke_rate REAL, intervals_json TEXT, linked_activity_id INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_activity_source_external_id UNIQUE (source, external_id)
);
CREATE TABLE body_comp (
	id INTEGER NOT NULL, 
	source VARCHAR NOT NULL, 
	external_id VARCHAR NOT NULL, 
	ts DATETIME NOT NULL, 
	weight_kg FLOAT, 
	fat_pct FLOAT, 
	fat_kg FLOAT, 
	muscle_kg FLOAT, 
	bone_kg FLOAT, 
	hydration_kg FLOAT, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_bodycomp_source_external_id UNIQUE (source, external_id)
);
CREATE TABLE sync_state (
	source VARCHAR NOT NULL, 
	cursor VARCHAR, 
	last_attempt_at DATETIME, 
	last_success_at DATETIME, 
	last_error VARCHAR, 
	PRIMARY KEY (source)
);
CREATE TABLE oauth_tokens (
	source VARCHAR NOT NULL, 
	access_token_enc VARCHAR NOT NULL, 
	refresh_token_enc VARCHAR, 
	expires_at DATETIME, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (source)
);
CREATE TABLE notes (
	id INTEGER NOT NULL, 
	date DATE NOT NULL, 
	text VARCHAR NOT NULL, 
	rpe INTEGER, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE strokes (
	id INTEGER NOT NULL, 
	activity_id INTEGER NOT NULL, 
	t FLOAT NOT NULL, 
	distance FLOAT, 
	pace_500m FLOAT, 
	watts FLOAT, 
	stroke_rate FLOAT, 
	hr FLOAT, seq INTEGER NOT NULL DEFAULT 0, interval_index INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(activity_id) REFERENCES activities (id)
);
CREATE TABLE settings (
	id INTEGER NOT NULL, 
	data_json VARCHAR NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE daily_scores (
	date DATE NOT NULL, 
	recovery_json VARCHAR, 
	strain_json VARCHAR, 
	load_json VARCHAR, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (date)
);
CREATE INDEX ix_strokes_activity_id ON strokes(activity_id);
