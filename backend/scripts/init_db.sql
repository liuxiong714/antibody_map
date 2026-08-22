-- 扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

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
    extraction_status VARCHAR(20) DEFAULT 'pending' CHECK (extraction_status IN ('pending','processing','done','done_no_data','failed')),
    extracted_count INTEGER DEFAULT 0,
    approved_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE,
    deleted_by UUID
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
    review_comment TEXT,
    reviewer_id UUID REFERENCES "user"(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMP WITH TIME ZONE,
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