-- TeachAgent PostgreSQL MVP schema
--
-- Scope:
-- 1. Student master data
-- 2. Knowledge nodes, including student-created custom nodes
-- 3. Student question bank / wrongbook
-- 4. Review state for nodes and questions
-- 5. Memory event log and current memory profile
-- 6. Diagnosis / coach interaction records
--
-- Notes:
-- - This schema is designed to replace the current local JSON / JSONL runtime files.
-- - The existing knowledge tree can be seeded into knowledge_nodes from
--   docs/rag_inventory/knowledge_tree_typed_full.json.
-- - review_scheduler.py and coach/diagnosis logic can continue to consume
--   Python dict payloads after the service layer reads these tables.

BEGIN;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TABLE IF NOT EXISTS students (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  student_uid TEXT NOT NULL,
  display_name TEXT,
  grade_level TEXT,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'inactive')),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(metadata) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (student_uid)
);

CREATE TABLE IF NOT EXISTS learning_sessions (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  session_uid TEXT NOT NULL,
  session_type TEXT NOT NULL DEFAULT 'study'
    CHECK (session_type IN ('study', 'diagnosis', 'coach', 'review', 'mixed')),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at TIMESTAMPTZ,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(metadata) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (student_id, session_uid)
);

CREATE INDEX IF NOT EXISTS learning_sessions_student_idx
  ON learning_sessions (student_id);

CREATE INDEX IF NOT EXISTS learning_sessions_started_at_idx
  ON learning_sessions (started_at);

CREATE TABLE IF NOT EXISTS knowledge_nodes (
  node_id TEXT PRIMARY KEY,
  owner_student_id BIGINT REFERENCES students(id) ON DELETE CASCADE,
  parent_node_id TEXT REFERENCES knowledge_nodes(node_id) ON DELETE RESTRICT,
  name TEXT NOT NULL,
  level BIGINT NOT NULL DEFAULT 0 CHECK (level >= 0),
  is_leaf BOOLEAN NOT NULL DEFAULT TRUE,
  node_kind TEXT NOT NULL DEFAULT 'leaf',
  review_role TEXT,
  binding_role TEXT,
  path TEXT[] NOT NULL DEFAULT '{}',
  path_text TEXT,
  aliases TEXT[] NOT NULL DEFAULT '{}',
  common_errors TEXT[] NOT NULL DEFAULT '{}',
  typing_source TEXT NOT NULL,
  source_scope TEXT NOT NULL DEFAULT 'system'
    CHECK (source_scope IN ('system', 'student_custom')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (
    (source_scope = 'system' AND owner_student_id IS NULL)
    OR
    (source_scope = 'student_custom' AND owner_student_id IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS knowledge_nodes_parent_idx
  ON knowledge_nodes (parent_node_id);

CREATE INDEX IF NOT EXISTS knowledge_nodes_owner_student_idx
  ON knowledge_nodes (owner_student_id);

CREATE INDEX IF NOT EXISTS knowledge_nodes_scope_idx
  ON knowledge_nodes (source_scope);

CREATE TABLE IF NOT EXISTS student_questions (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  question_uid TEXT NOT NULL,
  question_kind TEXT NOT NULL DEFAULT 'wrong_question'
    CHECK (question_kind IN ('seed_example', 'wrong_question', 'practice_question')),
  source_type TEXT NOT NULL DEFAULT 'manual_entry',
  source_batch_id TEXT,
  source_name TEXT,
  source_section TEXT,
  source_chapter TEXT,
  question_type TEXT,
  stem TEXT NOT NULL,
  student_answer TEXT,
  correct_answer TEXT,
  solution_text TEXT,
  priority_note TEXT,
  note TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(payload) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (student_id, question_uid)
);

CREATE INDEX IF NOT EXISTS student_questions_student_idx
  ON student_questions (student_id);

CREATE INDEX IF NOT EXISTS student_questions_kind_idx
  ON student_questions (student_id, question_kind);

CREATE INDEX IF NOT EXISTS student_questions_source_batch_idx
  ON student_questions (student_id, source_batch_id);

CREATE TABLE IF NOT EXISTS student_question_node_links (
  question_id BIGINT NOT NULL REFERENCES student_questions(id) ON DELETE CASCADE,
  node_id TEXT NOT NULL REFERENCES knowledge_nodes(node_id) ON DELETE RESTRICT,
  link_role TEXT NOT NULL DEFAULT 'secondary'
    CHECK (link_role IN ('primary', 'secondary')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (question_id, node_id)
);

CREATE INDEX IF NOT EXISTS student_question_node_links_node_idx
  ON student_question_node_links (node_id);

CREATE INDEX IF NOT EXISTS student_question_node_links_role_idx
  ON student_question_node_links (question_id, link_role);

CREATE TABLE IF NOT EXISTS student_review_states (
  student_id BIGINT PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE,
  record_uid TEXT NOT NULL,
  generated_at TIMESTAMPTZ NOT NULL,
  review_plan JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(review_plan) = 'object'),
  notes JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(notes) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS student_node_states (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  node_id TEXT NOT NULL REFERENCES knowledge_nodes(node_id) ON DELETE RESTRICT,
  state TEXT NOT NULL
    CHECK (state IN ('new', 'learning', 'review', 'stable')),
  mastery DOUBLE PRECISION NOT NULL DEFAULT 0.0
    CHECK (mastery >= 0.0 AND mastery <= 1.0),
  stability DOUBLE PRECISION NOT NULL DEFAULT 0.0
    CHECK (stability >= 0.0),
  first_seen_at TIMESTAMPTZ,
  last_reviewed_at TIMESTAMPTZ,
  next_review_at TIMESTAMPTZ,
  correct_count BIGINT NOT NULL DEFAULT 0 CHECK (correct_count >= 0),
  wrong_count BIGINT NOT NULL DEFAULT 0 CHECK (wrong_count >= 0),
  source_batch_ids TEXT[] NOT NULL DEFAULT '{}',
  priority_note TEXT,
  manual_priority_bias DOUBLE PRECISION NOT NULL DEFAULT 0.0
    CHECK (manual_priority_bias >= -0.5 AND manual_priority_bias <= 0.5),
  manual_skip_until TIMESTAMPTZ,
  session_priority_boost DOUBLE PRECISION NOT NULL DEFAULT 0.0
    CHECK (session_priority_boost >= -0.8 AND session_priority_boost <= 0.8),
  session_priority_until TIMESTAMPTZ,
  session_priority_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (student_id, node_id)
);

CREATE INDEX IF NOT EXISTS student_node_states_student_idx
  ON student_node_states (student_id);

CREATE INDEX IF NOT EXISTS student_node_states_next_review_idx
  ON student_node_states (student_id, next_review_at);

CREATE TABLE IF NOT EXISTS student_question_states (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  question_id BIGINT NOT NULL REFERENCES student_questions(id) ON DELETE CASCADE,
  state TEXT NOT NULL
    CHECK (state IN ('new', 'learning', 'review', 'stable')),
  source_batch_id TEXT,
  last_result TEXT NOT NULL DEFAULT 'unseen'
    CHECK (last_result IN ('unseen', 'correct', 'wrong', 'partial')),
  review_count BIGINT NOT NULL DEFAULT 0 CHECK (review_count >= 0),
  first_seen_at TIMESTAMPTZ,
  last_reviewed_at TIMESTAMPTZ,
  next_review_at TIMESTAMPTZ,
  difficulty_estimate DOUBLE PRECISION,
  priority_note TEXT,
  mastery DOUBLE PRECISION
    CHECK (mastery IS NULL OR (mastery >= 0.0 AND mastery <= 1.0)),
  stability DOUBLE PRECISION
    CHECK (stability IS NULL OR stability >= 0.0),
  manual_priority_bias DOUBLE PRECISION NOT NULL DEFAULT 0.0
    CHECK (manual_priority_bias >= -0.5 AND manual_priority_bias <= 0.5),
  manual_skip_until TIMESTAMPTZ,
  session_priority_boost DOUBLE PRECISION NOT NULL DEFAULT 0.0
    CHECK (session_priority_boost >= -0.8 AND session_priority_boost <= 0.8),
  session_priority_until TIMESTAMPTZ,
  session_priority_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (student_id, question_id)
);

CREATE INDEX IF NOT EXISTS student_question_states_student_idx
  ON student_question_states (student_id);

CREATE INDEX IF NOT EXISTS student_question_states_next_review_idx
  ON student_question_states (student_id, next_review_at);

CREATE TABLE IF NOT EXISTS student_memory_events (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  learning_session_id BIGINT REFERENCES learning_sessions(id) ON DELETE SET NULL,
  event_uid TEXT,
  event_type TEXT NOT NULL
    CHECK (event_type IN ('diagnosis', 'coach', 'review', 'binding', 'student_choice')),
  occurred_at TIMESTAMPTZ NOT NULL,
  student_question_id BIGINT REFERENCES student_questions(id) ON DELETE SET NULL,
  question_uid TEXT,
  primary_node_id TEXT,
  secondary_node_ids TEXT[] NOT NULL DEFAULT '{}',
  source_name TEXT,
  source_section TEXT,
  error_type TEXT
    CHECK (
      error_type IS NULL
      OR error_type IN ('concept_gap', 'missing_strategy', 'misreading', 'calculation', 'careless')
    ),
  result_label TEXT,
  action_type TEXT,
  confidence DOUBLE PRECISION,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(payload) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (student_id, event_uid)
);

CREATE INDEX IF NOT EXISTS student_memory_events_student_time_idx
  ON student_memory_events (student_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS student_memory_events_type_time_idx
  ON student_memory_events (student_id, event_type, occurred_at DESC);

CREATE INDEX IF NOT EXISTS student_memory_events_question_idx
  ON student_memory_events (student_id, question_uid);

CREATE INDEX IF NOT EXISTS student_memory_events_primary_node_idx
  ON student_memory_events (student_id, primary_node_id);

CREATE INDEX IF NOT EXISTS student_memory_events_payload_gin
  ON student_memory_events USING GIN (payload);

CREATE TABLE IF NOT EXISTS student_memory_profiles (
  student_id BIGINT PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE,
  record_uid TEXT NOT NULL,
  profile_version TEXT NOT NULL,
  generated_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  dominant_error_type TEXT,
  dominant_error_signal_strength TEXT,
  dominant_error_share DOUBLE PRECISION
    CHECK (
      dominant_error_share IS NULL
      OR (dominant_error_share >= 0.0 AND dominant_error_share <= 1.0)
    ),
  memory_stage TEXT,
  recommended_teaching_mode TEXT,
  recommended_review_mode TEXT,
  error_type_counts JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(error_type_counts) = 'object'),
  teaching_preferences JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(teaching_preferences) = 'object'),
  practice_preferences JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(practice_preferences) = 'object'),
  personalization_summary JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(personalization_summary) = 'object'),
  memory_graph JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(memory_graph) = 'object'),
  agent_memory_text TEXT,
  notes JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(notes) = 'object'),
  raw_profile JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(raw_profile) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS student_memory_profiles_review_mode_idx
  ON student_memory_profiles (recommended_review_mode);

CREATE TABLE IF NOT EXISTS student_node_memories (
  student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  node_id TEXT NOT NULL REFERENCES knowledge_nodes(node_id) ON DELETE RESTRICT,
  error_type_counts JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(error_type_counts) = 'object'),
  observed_wrong_count BIGINT NOT NULL DEFAULT 0 CHECK (observed_wrong_count >= 0),
  review_wrong_count BIGINT NOT NULL DEFAULT 0 CHECK (review_wrong_count >= 0),
  mastery_hint TEXT NOT NULL,
  stability_hint TEXT NOT NULL,
  linked_question_uids TEXT[] NOT NULL DEFAULT '{}',
  diagnosis_count BIGINT NOT NULL DEFAULT 0 CHECK (diagnosis_count >= 0),
  review_correct_count BIGINT NOT NULL DEFAULT 0 CHECK (review_correct_count >= 0),
  review_partial_count BIGINT NOT NULL DEFAULT 0 CHECK (review_partial_count >= 0),
  practice_request_count BIGINT NOT NULL DEFAULT 0 CHECK (practice_request_count >= 0),
  consecutive_wrong_count BIGINT NOT NULL DEFAULT 0 CHECK (consecutive_wrong_count >= 0),
  last_seen_at TIMESTAMPTZ,
  last_wrong_at TIMESTAMPTZ,
  last_event_at TIMESTAMPTZ,
  dominant_error_type TEXT,
  recommended_intervention TEXT,
  signal_strength TEXT,
  observation_stage TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(metadata) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (student_id, node_id)
);

CREATE INDEX IF NOT EXISTS student_node_memories_signal_idx
  ON student_node_memories (student_id, signal_strength);

CREATE TABLE IF NOT EXISTS student_question_memories (
  student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  question_id BIGINT NOT NULL REFERENCES student_questions(id) ON DELETE CASCADE,
  linked_node_ids TEXT[] NOT NULL DEFAULT '{}',
  wrong_count BIGINT NOT NULL DEFAULT 0 CHECK (wrong_count >= 0),
  review_count BIGINT NOT NULL DEFAULT 0 CHECK (review_count >= 0),
  last_result TEXT NOT NULL DEFAULT 'unseen'
    CHECK (last_result IN ('unseen', 'correct', 'wrong', 'partial')),
  error_type_counts JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(error_type_counts) = 'object'),
  diagnosis_count BIGINT NOT NULL DEFAULT 0 CHECK (diagnosis_count >= 0),
  correct_count BIGINT NOT NULL DEFAULT 0 CHECK (correct_count >= 0),
  partial_count BIGINT NOT NULL DEFAULT 0 CHECK (partial_count >= 0),
  last_error_type TEXT,
  source_name TEXT,
  source_section TEXT,
  last_seen_at TIMESTAMPTZ,
  last_wrong_at TIMESTAMPTZ,
  last_event_at TIMESTAMPTZ,
  signal_strength TEXT,
  observation_stage TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(metadata) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (student_id, question_id)
);

CREATE INDEX IF NOT EXISTS student_question_memories_signal_idx
  ON student_question_memories (student_id, signal_strength);

CREATE TABLE IF NOT EXISTS diagnosis_sessions (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  learning_session_id BIGINT REFERENCES learning_sessions(id) ON DELETE SET NULL,
  question_id BIGINT REFERENCES student_questions(id) ON DELETE SET NULL,
  diagnosis_uid TEXT,
  problem_text TEXT NOT NULL,
  reference_answer TEXT,
  student_answer TEXT,
  student_profile_input TEXT,
  max_coach_turns BIGINT CHECK (max_coach_turns IS NULL OR max_coach_turns >= 1),
  error_type TEXT
    CHECK (
      error_type IS NULL
      OR error_type IN ('concept_gap', 'missing_strategy', 'misreading', 'calculation', 'careless')
    ),
  reason TEXT,
  evidence TEXT,
  confidence DOUBLE PRECISION,
  can_continue BOOLEAN NOT NULL DEFAULT FALSE,
  can_enter_coach BOOLEAN NOT NULL DEFAULT FALSE,
  result_payload JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(result_payload) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (student_id, diagnosis_uid)
);

CREATE INDEX IF NOT EXISTS diagnosis_sessions_student_idx
  ON diagnosis_sessions (student_id, created_at DESC);

CREATE TABLE IF NOT EXISTS diagnosis_messages (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  diagnosis_session_id BIGINT NOT NULL REFERENCES diagnosis_sessions(id) ON DELETE CASCADE,
  message_index BIGINT NOT NULL CHECK (message_index >= 0),
  speaker TEXT NOT NULL CHECK (speaker IN ('assistant', 'student', 'system')),
  content TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(payload) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (diagnosis_session_id, message_index)
);

CREATE INDEX IF NOT EXISTS diagnosis_messages_session_idx
  ON diagnosis_messages (diagnosis_session_id, message_index);

CREATE TABLE IF NOT EXISTS coach_sessions (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  learning_session_id BIGINT REFERENCES learning_sessions(id) ON DELETE SET NULL,
  question_id BIGINT REFERENCES student_questions(id) ON DELETE SET NULL,
  coach_uid TEXT,
  error_type TEXT
    CHECK (
      error_type IS NULL
      OR error_type IN ('concept_gap', 'missing_strategy', 'misreading', 'calculation', 'careless')
    ),
  coach_mode TEXT,
  max_turns BIGINT NOT NULL CHECK (max_turns >= 1),
  turn_index BIGINT NOT NULL DEFAULT 0 CHECK (turn_index >= 0),
  done BOOLEAN NOT NULL DEFAULT FALSE,
  stop_reason TEXT,
  student_profile_input TEXT,
  result_payload JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(result_payload) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (student_id, coach_uid)
);

CREATE INDEX IF NOT EXISTS coach_sessions_student_idx
  ON coach_sessions (student_id, created_at DESC);

CREATE TABLE IF NOT EXISTS coach_messages (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  coach_session_id BIGINT NOT NULL REFERENCES coach_sessions(id) ON DELETE CASCADE,
  message_index BIGINT NOT NULL CHECK (message_index >= 0),
  speaker TEXT NOT NULL CHECK (speaker IN ('assistant', 'student', 'system')),
  content TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(payload) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (coach_session_id, message_index)
);

CREATE INDEX IF NOT EXISTS coach_messages_session_idx
  ON coach_messages (coach_session_id, message_index);

CREATE TRIGGER students_set_updated_at
BEFORE UPDATE ON students
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER learning_sessions_set_updated_at
BEFORE UPDATE ON learning_sessions
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER knowledge_nodes_set_updated_at
BEFORE UPDATE ON knowledge_nodes
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER student_questions_set_updated_at
BEFORE UPDATE ON student_questions
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER student_review_states_set_updated_at
BEFORE UPDATE ON student_review_states
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER student_node_states_set_updated_at
BEFORE UPDATE ON student_node_states
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER student_question_states_set_updated_at
BEFORE UPDATE ON student_question_states
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER student_node_memories_set_updated_at
BEFORE UPDATE ON student_node_memories
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER student_question_memories_set_updated_at
BEFORE UPDATE ON student_question_memories
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER diagnosis_sessions_set_updated_at
BEFORE UPDATE ON diagnosis_sessions
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER coach_sessions_set_updated_at
BEFORE UPDATE ON coach_sessions
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

COMMIT;
