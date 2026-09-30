-- 扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 用户表 user（Alembic 迁移引用"user"表，须在创建外键前存在）
CREATE TABLE "user" (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(100),
    hashed_password VARCHAR(500) NOT NULL,
    display_name VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    is_admin BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX ix_user_username ON "user"(username);

-- 文献表 literature
CREATE TABLE literature (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title VARCHAR(500) NOT NULL,
    title_en VARCHAR(500),
    authors TEXT,
    journal VARCHAR(300),
    pub_year INTEGER,
    doi VARCHAR(200),
    pmid VARCHAR(20),
    abstract TEXT,
    keywords TEXT[],
    region VARCHAR(100),
    province VARCHAR(100),
    publication_types TEXT[],
    source_db VARCHAR(50),
    file_path VARCHAR(500),
    has_fulltext BOOLEAN DEFAULT FALSE,
    extraction_status VARCHAR(20) DEFAULT 'pending' CONSTRAINT lit_extraction_status_check CHECK (extraction_status IN ('pending','processing','queued','done','done_no_data','failed')),
    extracted_count INTEGER DEFAULT 0,
    approved_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 数据点表 data_point（核心数据表）
CREATE TABLE data_point (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    literature_id UUID REFERENCES literature(id) ON DELETE CASCADE,
    disease VARCHAR(100),
    region VARCHAR(100),
    province VARCHAR(100),
    city VARCHAR(100),
    latitude DECIMAL(10,7),
    longitude DECIMAL(10,7),
    age_group VARCHAR(50),
    age_min INTEGER,
    age_max INTEGER,
    sample_size INTEGER,
    data_type VARCHAR(20) CHECK (data_type IN ('seroprevalence','gmc')),
    value DECIMAL(10,4),
    unit VARCHAR(50),
    ci_lower DECIMAL(10,4),
    ci_upper DECIMAL(10,4),
    method VARCHAR(200),
    assay VARCHAR(200),
    population VARCHAR(200),
    collection_year INTEGER,
    confidence VARCHAR(10) DEFAULT 'medium' CHECK (confidence IN ('high','medium','low')),
    review_status VARCHAR(20) DEFAULT 'pending' CHECK (review_status IN ('pending','approved','rejected')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 疾病字典表 disease_dict
CREATE TABLE disease_dict (
    key VARCHAR(50) PRIMARY KEY,
    name_cn VARCHAR(100) NOT NULL,
    name_en VARCHAR(100),
    category VARCHAR(100),
    vaccine VARCHAR(200)
);

-- 报告表 report（Alembic init 迁移引用的表，须在迁移前存在）
CREATE TABLE report (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title VARCHAR(500) NOT NULL,
    content TEXT NOT NULL,
    report_type VARCHAR(30) DEFAULT 'antibody_analysis',
    disease VARCHAR(50),
    province VARCHAR(100),
    data_type VARCHAR(50),
    language VARCHAR(10) DEFAULT 'zh',
    literature_count INTEGER DEFAULT 0,
    data_point_count INTEGER DEFAULT 0,
    task_type VARCHAR(100),
    task_time VARCHAR(200),
    task_location VARCHAR(200),
    personnel_count INTEGER,
    personnel_gender VARCHAR(100),
    personnel_age VARCHAR(100),
    personnel_vaccination_history TEXT,
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT report_type_check CHECK (report_type IN ('antibody_analysis','vaccination_strategy'))
);

-- 插入 11 种疾病
INSERT INTO disease_dict VALUES
('measles','麻疹','Measles','疫苗可预防','麻腮风疫苗(MMR)'),
('mumps','腮腺炎','Mumps','疫苗可预防','麻腮风疫苗(MMR)'),
('rubella','风疹','Rubella','疫苗可预防','麻腮风疫苗(MMR)'),
('pertussis','百日咳','Pertussis','疫苗可预防','百白破疫苗(DTaP)'),
('diphtheria','白喉','Diphtheria','疫苗可预防','百白破疫苗(DTaP)'),
('tetanus','破伤风','Tetanus','疫苗可预防','百白破疫苗(DTaP)'),
('hepatitis_b','乙肝','Hepatitis B','疫苗可预防','乙肝疫苗(HepB)'),
('hepatitis_a','甲肝','Hepatitis A','疫苗可预防','甲肝疫苗(HepA)'),
('polio','脊灰','Polio','疫苗可预防','脊灰疫苗(OPV/IPV)'),
('influenza','流感','Influenza','呼吸道','流感疫苗'),
('covid19','新冠','COVID-19','呼吸道','新冠疫苗');

-- 创建索引
CREATE INDEX idx_dp_disease ON data_point(disease);
CREATE INDEX idx_dp_province ON data_point(province);
CREATE INDEX idx_dp_review_status ON data_point(review_status);
CREATE INDEX idx_dp_collection_year ON data_point(collection_year);
CREATE INDEX idx_lit_extraction_status ON literature(extraction_status);