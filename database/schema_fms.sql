-- Farm Management System - Complete Schema

CREATE TABLE IF NOT EXISTS farms (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    location VARCHAR(500),
    total_area DECIMAL(10,2),
    area_unit VARCHAR(20) DEFAULT 'acres',
    description TEXT,
    logo_path VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(200) UNIQUE NOT NULL,
    password_hash VARCHAR(500) NOT NULL,
    role VARCHAR(50) DEFAULT 'field_worker',
    farm_id INTEGER REFERENCES farms(id) ON DELETE SET NULL,
    avatar_path VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fields (
    id SERIAL PRIMARY KEY,
    farm_id INTEGER REFERENCES farms(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    area DECIMAL(10,2),
    area_unit VARCHAR(20) DEFAULT 'acres',
    soil_type VARCHAR(100),
    gps_lat VARCHAR(50),
    gps_lng VARCHAR(50),
    current_crop VARCHAR(200),
    status VARCHAR(50) DEFAULT 'active',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS field_activities (
    id SERIAL PRIMARY KEY,
    field_id INTEGER REFERENCES fields(id) ON DELETE CASCADE,
    farm_id INTEGER REFERENCES farms(id),
    activity_type VARCHAR(50) NOT NULL,
    activity_date DATE NOT NULL,
    crop_name VARCHAR(200),
    variety VARCHAR(200),
    quantity DECIMAL(10,2),
    unit VARCHAR(50),
    inputs_used TEXT,
    notes TEXT,
    worker_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS livestock_groups (
    id SERIAL PRIMARY KEY,
    farm_id INTEGER REFERENCES farms(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    species VARCHAR(100) NOT NULL,
    breed VARCHAR(200),
    count INTEGER DEFAULT 0,
    location VARCHAR(200),
    status VARCHAR(50) DEFAULT 'active',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS livestock_records (
    id SERIAL PRIMARY KEY,
    livestock_group_id INTEGER REFERENCES livestock_groups(id) ON DELETE CASCADE,
    record_type VARCHAR(50) NOT NULL,
    record_date DATE NOT NULL,
    description TEXT,
    quantity DECIMAL(10,2),
    cost DECIMAL(10,2) DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    farm_id INTEGER REFERENCES farms(id),
    field_id INTEGER REFERENCES fields(id) ON DELETE SET NULL,
    title VARCHAR(300) NOT NULL,
    description TEXT,
    task_type VARCHAR(100),
    assigned_to INTEGER REFERENCES users(id) ON DELETE SET NULL,
    due_date DATE,
    priority VARCHAR(20) DEFAULT 'medium',
    status VARCHAR(50) DEFAULT 'pending',
    estimated_hours DECIMAL(5,2),
    actual_hours DECIMAL(5,2),
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS expenses (
    id SERIAL PRIMARY KEY,
    farm_id INTEGER REFERENCES farms(id),
    field_id INTEGER REFERENCES fields(id) ON DELETE SET NULL,
    category VARCHAR(100) NOT NULL,
    description TEXT NOT NULL,
    amount DECIMAL(12,2) NOT NULL,
    expense_date DATE NOT NULL,
    vendor VARCHAR(200),
    receipt_ref VARCHAR(200),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS income_records (
    id SERIAL PRIMARY KEY,
    farm_id INTEGER REFERENCES farms(id),
    source VARCHAR(200) NOT NULL,
    product VARCHAR(200),
    quantity DECIMAL(10,2),
    unit VARCHAR(50),
    unit_price DECIMAL(10,2),
    amount DECIMAL(12,2) NOT NULL,
    income_date DATE NOT NULL,
    buyer VARCHAR(200),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS equipment (
    id SERIAL PRIMARY KEY,
    farm_id INTEGER REFERENCES farms(id),
    name VARCHAR(200) NOT NULL,
    equipment_type VARCHAR(100),
    make VARCHAR(100),
    model VARCHAR(100),
    year INTEGER,
    usage_hours DECIMAL(10,2) DEFAULT 0,
    fuel_type VARCHAR(50),
    status VARCHAR(50) DEFAULT 'operational',
    last_service_date DATE,
    next_service_date DATE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS maintenance_records (
    id SERIAL PRIMARY KEY,
    equipment_id INTEGER REFERENCES equipment(id) ON DELETE CASCADE,
    maintenance_type VARCHAR(100),
    maintenance_date DATE NOT NULL,
    description TEXT,
    cost DECIMAL(10,2) DEFAULT 0,
    performed_by VARCHAR(200),
    next_due_date DATE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inventory (
    id SERIAL PRIMARY KEY,
    farm_id INTEGER REFERENCES farms(id),
    item_name VARCHAR(200) NOT NULL,
    category VARCHAR(100) NOT NULL,
    quantity DECIMAL(10,2) DEFAULT 0,
    unit VARCHAR(50),
    min_quantity DECIMAL(10,2) DEFAULT 0,
    cost_per_unit DECIMAL(10,2) DEFAULT 0,
    location VARCHAR(200),
    expiry_date DATE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS uploads (
    id SERIAL PRIMARY KEY,
    farm_id INTEGER REFERENCES farms(id) ON DELETE CASCADE,
    original_filename VARCHAR(500) NOT NULL,
    stored_filename VARCHAR(500) NOT NULL,
    file_type VARCHAR(50),
    file_size INTEGER,
    category VARCHAR(100) DEFAULT 'general',
    entity_type VARCHAR(100),
    entity_id INTEGER,
    description TEXT,
    uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
