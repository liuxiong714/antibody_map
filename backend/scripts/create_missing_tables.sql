CREATE TABLE IF NOT EXISTS "user" (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100),
    hashed_password VARCHAR(500) NOT NULL,
    display_name VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    is_admin BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_user_username ON "user"(username);

CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES "user"(id),
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id VARCHAR(50),
    detail TEXT,
    ip_address VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_audit_log_user_id ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS ix_audit_log_created_at ON audit_log(created_at);

CREATE TABLE IF NOT EXISTS report (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title VARCHAR(500) NOT NULL,
    content TEXT NOT NULL,
    report_type VARCHAR(30) NOT NULL DEFAULT 'antibody_analysis',
    disease VARCHAR(50),
    province VARCHAR(100),
    data_type VARCHAR(50),
    language VARCHAR(10) NOT NULL DEFAULT 'zh',
    literature_count INTEGER NOT NULL DEFAULT 0,
    data_point_count INTEGER NOT NULL DEFAULT 0,
    task_type VARCHAR(100),
    task_time VARCHAR(200),
    task_location VARCHAR(200),
    personnel_count INTEGER,
    personnel_gender VARCHAR(100),
    personnel_age VARCHAR(100),
    personnel_vaccination_history TEXT,
    llm_model VARCHAR(100),
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT report_type_check CHECK (report_type IN ('antibody_analysis', 'vaccination_strategy'))
);

CREATE TABLE IF NOT EXISTS extraction_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    literature_id UUID NOT NULL REFERENCES literature(id) ON DELETE CASCADE,
    extracted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    model VARCHAR(100),
    status VARCHAR(20) NOT NULL DEFAULT 'success',
    data_point_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    llm_cost_usd NUMERIC(10,6) NOT NULL DEFAULT 0,
    llm_call_count INTEGER NOT NULL DEFAULT 0,
    llm_usage_detail JSONB,
    CONSTRAINT extraction_history_status_check CHECK (status IN ('success', 'no_data', 'failed'))
);

CREATE TABLE IF NOT EXISTS titer_table (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    literature_id UUID NOT NULL REFERENCES literature(id) ON DELETE CASCADE,
    assay_type VARCHAR(20) NOT NULL,
    ref_antisera JSONB,
    antigens JSONB,
    titers JSONB,
    unit VARCHAR(50),
    quality_score INTEGER,
    source_page INTEGER,
    source_context VARCHAR(500),
    confidence VARCHAR(10) NOT NULL DEFAULT 'medium',
    review_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT titer_table_assay_type_check CHECK (assay_type IN ('hi', 'vnt', 'elisa')),
    CONSTRAINT titer_table_review_status_check CHECK (review_status IN ('pending', 'approved', 'rejected')),
    CONSTRAINT titer_table_quality_score_check CHECK (quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 100))
);

CREATE TABLE IF NOT EXISTS tag (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(50) NOT NULL,
    color VARCHAR(7) DEFAULT '#1677ff',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_tag_name UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS literature_tag (
    literature_id UUID NOT NULL REFERENCES literature(id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    PRIMARY KEY (literature_id, tag_id)
);

CREATE TABLE IF NOT EXISTS local_model_config (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_local_model_config_model_name UNIQUE (model_name)
);

CREATE TABLE IF NOT EXISTS api_model_config (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    api_key VARCHAR(500) NOT NULL,
    base_url VARCHAR(500) NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS analysis_snapshot (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    module VARCHAR(50) NOT NULL,
    params JSONB,
    data_hash VARCHAR(32) NOT NULL,
    response_json JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS monitored_folder (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(200) NOT NULL,
    folder_path VARCHAR(500) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    scan_interval_seconds INTEGER NOT NULL DEFAULT 300,
    file_extensions TEXT,
    auto_extract BOOLEAN NOT NULL DEFAULT TRUE,
    extraction_model VARCHAR(100),
    extraction_api_key VARCHAR(200),
    extraction_base_url VARCHAR(300),
    last_scan_at TIMESTAMP WITH TIME ZONE,
    last_scan_new_count INTEGER NOT NULL DEFAULT 0,
    total_imported_count INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'idle',
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT mf_status_check CHECK (status IN ('idle', 'scanning', 'error'))
);

CREATE TABLE IF NOT EXISTS monitored_file (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    folder_id UUID NOT NULL REFERENCES monitored_folder(id) ON DELETE CASCADE,
    file_path VARCHAR(500) NOT NULL,
    file_name VARCHAR(300) NOT NULL,
    file_hash VARCHAR(64),
    file_size INTEGER,
    file_mtime TIMESTAMP WITH TIME ZONE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    literature_id UUID,
    error_message TEXT,
    imported_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT mf_file_status_check CHECK (status IN ('pending', 'imported', 'skipped_duplicate', 'failed'))
);
CREATE INDEX IF NOT EXISTS ix_monitored_file_folder_id ON monitored_file(folder_id);
CREATE INDEX IF NOT EXISTS ix_monitored_file_file_hash ON monitored_file(file_hash);
CREATE INDEX IF NOT EXISTS ix_monitored_file_literature_id ON monitored_file(literature_id);