from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, abort
from flask_cors import CORS
import psycopg2
from psycopg2 import pool, extras
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, date
import os
import uuid
from functools import wraps
import logging

logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.secret_key = os.environ.get('SESSION_SECRET', 'fms-secret-key-2025')
CORS(app)

DATABASE_URL = os.environ.get('DATABASE_URL')
connection_pool = None

ROLES = ['owner', 'manager', 'field_worker', 'accountant']
MANAGE_ROLES = ['owner', 'manager']

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
ALLOWED_EXTENSIONS = {
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp',
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv',
    'txt', 'odt', 'ods', 'zip'
}
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16 MB
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_file_category(filename):
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    if ext in {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'}:
        return 'image'
    if ext == 'pdf':
        return 'pdf'
    if ext in {'doc', 'docx', 'odt', 'txt'}:
        return 'document'
    if ext in {'xls', 'xlsx', 'csv', 'ods'}:
        return 'spreadsheet'
    return 'other'


@app.context_processor
def inject_globals():
    from datetime import date, datetime
    return {
        'today': date.today(),
        'now': datetime.now().strftime('%A, %d %B %Y'),
    }


def init_pool():
    global connection_pool
    if DATABASE_URL and not connection_pool:
        try:
            connection_pool = pool.SimpleConnectionPool(1, 10, DATABASE_URL)
            print("Database connection pool created successfully!")
        except Exception as e:
            print(f"Error creating connection pool: {e}")


def get_db_connection():
    if connection_pool:
        return connection_pool.getconn()
    return None


def release_db_connection(conn):
    if connection_pool and conn:
        connection_pool.putconn(conn)


def init_db():
    conn = get_db_connection()
    if not conn:
        print("No DB connection for init_db")
        return
    try:
        cursor = conn.cursor()
        schema_path = os.path.join(os.path.dirname(__file__), 'database', 'schema_fms.sql')
        with open(schema_path, 'r') as f:
            cursor.execute(f.read())
        conn.commit()
        cursor.close()
        print("Database initialized successfully!")
    except Exception as e:
        print(f"Error initializing database: {e}")
        conn.rollback()
    finally:
        release_db_connection(conn)


# ─── Auth Decorators ──────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def manage_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login.', 'error')
            return redirect(url_for('login'))
        if session.get('role') not in MANAGE_ROLES:
            flash('Manager or Owner access required.', 'error')
            return redirect(request.referrer or url_for('index'))
        return f(*args, **kwargs)
    return decorated


def owner_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login.', 'error')
            return redirect(url_for('login'))
        if session.get('role') != 'owner':
            flash('Owner access required.', 'error')
            return redirect(request.referrer or url_for('index'))
        return f(*args, **kwargs)
    return decorated


# ─── Auth Routes ─────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        conn = get_db_connection()
        if not conn:
            flash('Database connection error.', 'error')
            return render_template('login.html')
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute("""
                SELECT u.*, f.name as farm_name, f.logo_path as farm_logo FROM users u
                LEFT JOIN farms f ON u.farm_id = f.id
                WHERE u.email = %s
            """, (email,))
            user = cursor.fetchone()
            cursor.close()
            if user and check_password_hash(user['password_hash'], password):
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['role'] = user['role']
                session['farm_id'] = user['farm_id']
                session['farm_name'] = user['farm_name'] or 'My Farm'
                session['avatar_path'] = user['avatar_path'] or ''
                session['farm_logo'] = user['farm_logo'] or ''
                flash(f"Welcome back, {user['username']}!", 'success')
                return redirect(url_for('index'))
            else:
                flash('Invalid email or password.', 'error')
        except Exception as e:
            logging.error(f"Login error: {e}")
            flash('An error occurred. Please try again.', 'error')
        finally:
            release_db_connection(conn)
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'field_worker')
        farm_name = request.form.get('farm_name', '').strip()
        farm_location = request.form.get('farm_location', '').strip()
        farm_area = request.form.get('farm_area', '')

        if not all([username, email, password, farm_name]):
            flash('Please fill in all required fields.', 'error')
            return render_template('register.html')

        conn = get_db_connection()
        if not conn:
            flash('Database connection error.', 'error')
            return render_template('register.html')
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute("SELECT id FROM users WHERE email = %s OR username = %s", (email, username))
            if cursor.fetchone():
                flash('Email or username already exists.', 'error')
                cursor.close()
                release_db_connection(conn)
                return render_template('register.html')

            farm_id = None
            if role == 'owner':
                area_val = float(farm_area) if farm_area else None
                cursor.execute("""
                    INSERT INTO farms (name, location, total_area) VALUES (%s, %s, %s) RETURNING id
                """, (farm_name, farm_location, area_val))
                farm_id = cursor.fetchone()['id']
            else:
                cursor.execute("SELECT id FROM farms WHERE name = %s", (farm_name,))
                farm = cursor.fetchone()
                if farm:
                    farm_id = farm['id']
                else:
                    flash(f'Farm "{farm_name}" not found. Ask the farm owner to register first.', 'error')
                    cursor.close()
                    release_db_connection(conn)
                    return render_template('register.html')

            pwd_hash = generate_password_hash(password)
            cursor.execute("""
                INSERT INTO users (username, email, password_hash, role, farm_id)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
            """, (username, email, pwd_hash, role, farm_id))
            user_id = cursor.fetchone()['id']
            conn.commit()
            cursor.close()

            session['user_id'] = user_id
            session['username'] = username
            session['role'] = role
            session['farm_id'] = farm_id
            session['farm_name'] = farm_name
            session['avatar_path'] = ''
            session['farm_logo'] = ''
            flash(f'Account created! Welcome to {farm_name}, {username}!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            logging.error(f"Register error: {e}")
            conn.rollback()
            flash('Registration failed. Please try again.', 'error')
        finally:
            release_db_connection(conn)
    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))


# ─── Dashboard ────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    farm_id = session.get('farm_id')
    stats = {}
    recent_activities = []
    pending_tasks = []
    low_stock = []
    upcoming_maintenance = []

    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)

            cursor.execute("SELECT COUNT(*) as cnt FROM fields WHERE farm_id = %s AND status = 'active'", (farm_id,))
            stats['fields'] = cursor.fetchone()['cnt']

            cursor.execute("SELECT COUNT(*) as cnt FROM livestock_groups WHERE farm_id = %s AND status = 'active'", (farm_id,))
            stats['livestock'] = cursor.fetchone()['cnt']

            cursor.execute("SELECT COUNT(*) as cnt FROM tasks WHERE farm_id = %s AND status != 'completed'", (farm_id,))
            stats['pending_tasks'] = cursor.fetchone()['cnt']

            cursor.execute("SELECT COUNT(*) as cnt FROM equipment WHERE farm_id = %s AND status = 'operational'", (farm_id,))
            stats['equipment'] = cursor.fetchone()['cnt']

            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) as total FROM income_records
                WHERE farm_id = %s AND EXTRACT(MONTH FROM income_date) = EXTRACT(MONTH FROM CURRENT_DATE)
                AND EXTRACT(YEAR FROM income_date) = EXTRACT(YEAR FROM CURRENT_DATE)
            """, (farm_id,))
            stats['monthly_income'] = float(cursor.fetchone()['total'])

            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) as total FROM expenses
                WHERE farm_id = %s AND EXTRACT(MONTH FROM expense_date) = EXTRACT(MONTH FROM CURRENT_DATE)
                AND EXTRACT(YEAR FROM expense_date) = EXTRACT(YEAR FROM CURRENT_DATE)
            """, (farm_id,))
            stats['monthly_expenses'] = float(cursor.fetchone()['total'])
            stats['monthly_profit'] = stats['monthly_income'] - stats['monthly_expenses']

            cursor.execute("""
                SELECT fa.*, f.name as field_name FROM field_activities fa
                JOIN fields f ON fa.field_id = f.id
                WHERE fa.farm_id = %s ORDER BY fa.activity_date DESC LIMIT 5
            """, (farm_id,))
            recent_activities = cursor.fetchall()

            cursor.execute("""
                SELECT t.*, u.username as assignee_name, f.name as field_name
                FROM tasks t
                LEFT JOIN users u ON t.assigned_to = u.id
                LEFT JOIN fields f ON t.field_id = f.id
                WHERE t.farm_id = %s AND t.status != 'completed'
                ORDER BY t.due_date ASC NULLS LAST LIMIT 5
            """, (farm_id,))
            pending_tasks = cursor.fetchall()

            cursor.execute("""
                SELECT * FROM inventory WHERE farm_id = %s AND quantity <= min_quantity ORDER BY (quantity - min_quantity) LIMIT 5
            """, (farm_id,))
            low_stock = cursor.fetchall()

            cursor.execute("""
                SELECT e.*, mr.next_due_date, mr.maintenance_type
                FROM equipment e
                LEFT JOIN maintenance_records mr ON mr.equipment_id = e.id
                WHERE e.farm_id = %s AND mr.next_due_date IS NOT NULL
                AND mr.next_due_date <= CURRENT_DATE + INTERVAL '30 days'
                ORDER BY mr.next_due_date ASC LIMIT 5
            """, (farm_id,))
            upcoming_maintenance = cursor.fetchall()

            cursor.close()
        except Exception as e:
            logging.error(f"Dashboard error: {e}")
        finally:
            release_db_connection(conn)

    return render_template('index.html',
        stats=stats,
        recent_activities=recent_activities,
        pending_tasks=pending_tasks,
        low_stock=low_stock,
        upcoming_maintenance=upcoming_maintenance
    )


# ─── Fields & Crop Activities ─────────────────────────────────────────────────

@app.route('/fields')
@login_required
def fields():
    farm_id = session.get('farm_id')
    field_list = []
    activities = []
    workers = []
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute("SELECT * FROM fields WHERE farm_id = %s ORDER BY name", (farm_id,))
            field_list = cursor.fetchall()
            cursor.execute("""
                SELECT fa.*, f.name as field_name, u.username as worker_name
                FROM field_activities fa
                JOIN fields f ON fa.field_id = f.id
                LEFT JOIN users u ON fa.worker_id = u.id
                WHERE fa.farm_id = %s ORDER BY fa.activity_date DESC LIMIT 50
            """, (farm_id,))
            activities = cursor.fetchall()
            cursor.execute("SELECT id, username FROM users WHERE farm_id = %s ORDER BY username", (farm_id,))
            workers = cursor.fetchall()
            cursor.close()
        except Exception as e:
            logging.error(f"Fields error: {e}")
        finally:
            release_db_connection(conn)
    attachments = get_attachments_for(farm_id, ['field', 'field_activity'])
    return render_template('fields.html', fields=field_list, activities=activities, workers=workers, attachments=attachments)


@app.route('/fields/add', methods=['POST'])
@login_required
@manage_required
def add_field():
    farm_id = session.get('farm_id')
    name = request.form.get('name', '').strip()
    area = request.form.get('area') or None
    area_unit = request.form.get('area_unit', 'acres')
    soil_type = request.form.get('soil_type', '').strip()
    gps_lat = request.form.get('gps_lat', '').strip()
    gps_lng = request.form.get('gps_lng', '').strip()
    current_crop = request.form.get('current_crop', '').strip()
    notes = request.form.get('notes', '').strip()
    if not name:
        flash('Field name is required.', 'error')
        return redirect(url_for('fields'))
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO fields (farm_id, name, area, area_unit, soil_type, gps_lat, gps_lng, current_crop, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (farm_id, name, area, area_unit, soil_type or None, gps_lat or None, gps_lng or None, current_crop or None, notes or None))
            conn.commit()
            cursor.close()
            flash(f'Field "{name}" added successfully!', 'success')
        except Exception as e:
            logging.error(f"Add field error: {e}")
            conn.rollback()
            flash('Error adding field.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('fields'))


@app.route('/fields/delete/<int:field_id>', methods=['POST'])
@login_required
@manage_required
def delete_field(field_id):
    farm_id = session.get('farm_id')
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM fields WHERE id = %s AND farm_id = %s", (field_id, farm_id))
            conn.commit()
            cursor.close()
            flash('Field deleted.', 'success')
        except Exception as e:
            logging.error(f"Delete field error: {e}")
            conn.rollback()
            flash('Error deleting field.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('fields'))


@app.route('/activities/add', methods=['POST'])
@login_required
def add_activity():
    farm_id = session.get('farm_id')
    field_id = request.form.get('field_id')
    activity_type = request.form.get('activity_type', '')
    activity_date = request.form.get('activity_date')
    crop_name = request.form.get('crop_name', '').strip()
    variety = request.form.get('variety', '').strip()
    quantity = request.form.get('quantity') or None
    unit = request.form.get('unit', '').strip()
    inputs_used = request.form.get('inputs_used', '').strip()
    notes = request.form.get('notes', '').strip()
    worker_id = request.form.get('worker_id') or session.get('user_id')

    if not all([field_id, activity_type, activity_date]):
        flash('Field, activity type, and date are required.', 'error')
        return redirect(url_for('fields'))
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO field_activities (field_id, farm_id, activity_type, activity_date, crop_name, variety, quantity, unit, inputs_used, notes, worker_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (field_id, farm_id, activity_type, activity_date, crop_name or None, variety or None, quantity, unit or None, inputs_used or None, notes or None, worker_id))
            conn.commit()
            cursor.close()
            flash('Activity logged successfully!', 'success')
        except Exception as e:
            logging.error(f"Add activity error: {e}")
            conn.rollback()
            flash('Error logging activity.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('fields'))


@app.route('/activities/delete/<int:activity_id>', methods=['POST'])
@login_required
@manage_required
def delete_activity(activity_id):
    farm_id = session.get('farm_id')
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM field_activities WHERE id = %s AND farm_id = %s", (activity_id, farm_id))
            conn.commit()
            cursor.close()
            flash('Activity deleted.', 'success')
        except Exception as e:
            logging.error(f"Delete activity error: {e}")
            conn.rollback()
            flash('Error deleting activity.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('fields'))


# ─── Livestock ────────────────────────────────────────────────────────────────

@app.route('/livestock')
@login_required
def livestock():
    farm_id = session.get('farm_id')
    groups = []
    records = []
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute("SELECT * FROM livestock_groups WHERE farm_id = %s ORDER BY species, name", (farm_id,))
            groups = cursor.fetchall()
            cursor.execute("""
                SELECT lr.*, lg.name as group_name, lg.species FROM livestock_records lr
                JOIN livestock_groups lg ON lr.livestock_group_id = lg.id
                WHERE lg.farm_id = %s ORDER BY lr.record_date DESC LIMIT 50
            """, (farm_id,))
            records = cursor.fetchall()
            cursor.close()
        except Exception as e:
            logging.error(f"Livestock error: {e}")
        finally:
            release_db_connection(conn)
    attachments = get_attachments_for(farm_id, ['livestock_group', 'livestock_record'])
    return render_template('livestock.html', groups=groups, records=records, attachments=attachments)


@app.route('/livestock/add', methods=['POST'])
@login_required
@manage_required
def add_livestock():
    farm_id = session.get('farm_id')
    name = request.form.get('name', '').strip()
    species = request.form.get('species', '').strip()
    breed = request.form.get('breed', '').strip()
    count = request.form.get('count', 0)
    location = request.form.get('location', '').strip()
    notes = request.form.get('notes', '').strip()
    if not all([name, species]):
        flash('Name and species are required.', 'error')
        return redirect(url_for('livestock'))
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO livestock_groups (farm_id, name, species, breed, count, location, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (farm_id, name, species, breed or None, count, location or None, notes or None))
            conn.commit()
            cursor.close()
            flash(f'Livestock group "{name}" added!', 'success')
        except Exception as e:
            logging.error(f"Add livestock error: {e}")
            conn.rollback()
            flash('Error adding livestock group.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('livestock'))


@app.route('/livestock/delete/<int:group_id>', methods=['POST'])
@login_required
@manage_required
def delete_livestock(group_id):
    farm_id = session.get('farm_id')
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM livestock_groups WHERE id = %s AND farm_id = %s", (group_id, farm_id))
            conn.commit()
            cursor.close()
            flash('Livestock group deleted.', 'success')
        except Exception as e:
            logging.error(f"Delete livestock error: {e}")
            conn.rollback()
            flash('Error deleting livestock group.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('livestock'))


@app.route('/livestock-record/add', methods=['POST'])
@login_required
def add_livestock_record():
    livestock_group_id = request.form.get('livestock_group_id')
    record_type = request.form.get('record_type', '')
    record_date = request.form.get('record_date')
    description = request.form.get('description', '').strip()
    quantity = request.form.get('quantity') or None
    cost = request.form.get('cost') or 0
    notes = request.form.get('notes', '').strip()
    if not all([livestock_group_id, record_type, record_date]):
        flash('Group, type, and date are required.', 'error')
        return redirect(url_for('livestock'))
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO livestock_records (livestock_group_id, record_type, record_date, description, quantity, cost, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (livestock_group_id, record_type, record_date, description or None, quantity, cost, notes or None))
            conn.commit()
            cursor.close()
            flash('Livestock record added!', 'success')
        except Exception as e:
            logging.error(f"Add livestock record error: {e}")
            conn.rollback()
            flash('Error adding record.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('livestock'))


@app.route('/livestock-record/delete/<int:record_id>', methods=['POST'])
@login_required
@manage_required
def delete_livestock_record(record_id):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM livestock_records WHERE id = %s", (record_id,))
            conn.commit()
            cursor.close()
            flash('Record deleted.', 'success')
        except Exception as e:
            logging.error(f"Delete livestock record error: {e}")
            conn.rollback()
            flash('Error deleting record.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('livestock'))


# ─── Tasks & Scheduling ───────────────────────────────────────────────────────

@app.route('/tasks')
@login_required
def tasks():
    farm_id = session.get('farm_id')
    task_list = []
    fields_list = []
    workers = []
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            status_filter = request.args.get('status', '')
            priority_filter = request.args.get('priority', '')
            base_query = """
                SELECT t.*, u.username as assignee_name, f.name as field_name,
                       cb.username as creator_name
                FROM tasks t
                LEFT JOIN users u ON t.assigned_to = u.id
                LEFT JOIN fields f ON t.field_id = f.id
                LEFT JOIN users cb ON t.created_by = cb.id
                WHERE t.farm_id = %s
            """
            params = [farm_id]
            if status_filter:
                base_query += " AND t.status = %s"
                params.append(status_filter)
            if priority_filter:
                base_query += " AND t.priority = %s"
                params.append(priority_filter)
            base_query += " ORDER BY t.due_date ASC NULLS LAST, t.priority DESC"
            cursor.execute(base_query, params)
            task_list = cursor.fetchall()
            cursor.execute("SELECT id, name FROM fields WHERE farm_id = %s ORDER BY name", (farm_id,))
            fields_list = cursor.fetchall()
            cursor.execute("SELECT id, username, role FROM users WHERE farm_id = %s ORDER BY username", (farm_id,))
            workers = cursor.fetchall()
            cursor.close()
        except Exception as e:
            logging.error(f"Tasks error: {e}")
        finally:
            release_db_connection(conn)
    return render_template('tasks.html', tasks=task_list, fields=fields_list, workers=workers,
                           status_filter=request.args.get('status', ''),
                           priority_filter=request.args.get('priority', ''))


@app.route('/tasks/add', methods=['POST'])
@login_required
@manage_required
def add_task():
    farm_id = session.get('farm_id')
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    task_type = request.form.get('task_type', '').strip()
    field_id = request.form.get('field_id') or None
    assigned_to = request.form.get('assigned_to') or None
    due_date = request.form.get('due_date') or None
    priority = request.form.get('priority', 'medium')
    estimated_hours = request.form.get('estimated_hours') or None
    if not title:
        flash('Task title is required.', 'error')
        return redirect(url_for('tasks'))
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tasks (farm_id, field_id, title, description, task_type, assigned_to, due_date, priority, estimated_hours, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (farm_id, field_id, title, description or None, task_type or None, assigned_to, due_date, priority, estimated_hours, session.get('user_id')))
            conn.commit()
            cursor.close()
            flash(f'Task "{title}" created!', 'success')
        except Exception as e:
            logging.error(f"Add task error: {e}")
            conn.rollback()
            flash('Error creating task.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('tasks'))


@app.route('/tasks/update/<int:task_id>', methods=['POST'])
@login_required
def update_task(task_id):
    farm_id = session.get('farm_id')
    status = request.form.get('status', 'pending')
    actual_hours = request.form.get('actual_hours') or None
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE tasks SET status = %s, actual_hours = %s WHERE id = %s AND farm_id = %s
            """, (status, actual_hours, task_id, farm_id))
            conn.commit()
            cursor.close()
            flash('Task updated!', 'success')
        except Exception as e:
            logging.error(f"Update task error: {e}")
            conn.rollback()
            flash('Error updating task.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('tasks'))


@app.route('/tasks/delete/<int:task_id>', methods=['POST'])
@login_required
@manage_required
def delete_task(task_id):
    farm_id = session.get('farm_id')
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tasks WHERE id = %s AND farm_id = %s", (task_id, farm_id))
            conn.commit()
            cursor.close()
            flash('Task deleted.', 'success')
        except Exception as e:
            logging.error(f"Delete task error: {e}")
            conn.rollback()
            flash('Error deleting task.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('tasks'))


# ─── Finance ──────────────────────────────────────────────────────────────────

@app.route('/finance')
@login_required
def finance():
    farm_id = session.get('farm_id')
    expenses_list = []
    income_list = []
    summary = {}
    fields_list = []
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute("""
                SELECT e.*, f.name as field_name FROM expenses e
                LEFT JOIN fields f ON e.field_id = f.id
                WHERE e.farm_id = %s ORDER BY e.expense_date DESC LIMIT 100
            """, (farm_id,))
            expenses_list = cursor.fetchall()

            cursor.execute("""
                SELECT * FROM income_records WHERE farm_id = %s ORDER BY income_date DESC LIMIT 100
            """, (farm_id,))
            income_list = cursor.fetchall()

            cursor.execute("SELECT COALESCE(SUM(amount), 0) as total FROM expenses WHERE farm_id = %s", (farm_id,))
            summary['total_expenses'] = float(cursor.fetchone()['total'])

            cursor.execute("SELECT COALESCE(SUM(amount), 0) as total FROM income_records WHERE farm_id = %s", (farm_id,))
            summary['total_income'] = float(cursor.fetchone()['total'])
            summary['net_profit'] = summary['total_income'] - summary['total_expenses']

            cursor.execute("""
                SELECT category, SUM(amount) as total FROM expenses WHERE farm_id = %s GROUP BY category ORDER BY total DESC
            """, (farm_id,))
            summary['expenses_by_category'] = cursor.fetchall()

            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) as total FROM expenses WHERE farm_id = %s
                AND EXTRACT(MONTH FROM expense_date) = EXTRACT(MONTH FROM CURRENT_DATE)
                AND EXTRACT(YEAR FROM expense_date) = EXTRACT(YEAR FROM CURRENT_DATE)
            """, (farm_id,))
            summary['month_expenses'] = float(cursor.fetchone()['total'])

            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) as total FROM income_records WHERE farm_id = %s
                AND EXTRACT(MONTH FROM income_date) = EXTRACT(MONTH FROM CURRENT_DATE)
                AND EXTRACT(YEAR FROM income_date) = EXTRACT(YEAR FROM CURRENT_DATE)
            """, (farm_id,))
            summary['month_income'] = float(cursor.fetchone()['total'])

            cursor.execute("SELECT id, name FROM fields WHERE farm_id = %s ORDER BY name", (farm_id,))
            fields_list = cursor.fetchall()
            cursor.close()
        except Exception as e:
            logging.error(f"Finance error: {e}")
        finally:
            release_db_connection(conn)
    attachments = get_attachments_for(farm_id, ['expense', 'income'])
    return render_template('finance.html', expenses=expenses_list, income=income_list, summary=summary, fields=fields_list, attachments=attachments)


@app.route('/finance/expense/add', methods=['POST'])
@login_required
def add_expense():
    farm_id = session.get('farm_id')
    if session.get('role') == 'field_worker':
        flash('Access denied.', 'error')
        return redirect(url_for('finance'))
    category = request.form.get('category', '')
    description = request.form.get('description', '').strip()
    amount = request.form.get('amount', 0)
    expense_date = request.form.get('expense_date')
    field_id = request.form.get('field_id') or None
    vendor = request.form.get('vendor', '').strip()
    receipt_ref = request.form.get('receipt_ref', '').strip()
    notes = request.form.get('notes', '').strip()
    if not all([category, description, amount, expense_date]):
        flash('Category, description, amount, and date are required.', 'error')
        return redirect(url_for('finance'))
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO expenses (farm_id, field_id, category, description, amount, expense_date, vendor, receipt_ref, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (farm_id, field_id, category, description, amount, expense_date, vendor or None, receipt_ref or None, notes or None))
            conn.commit()
            cursor.close()
            flash('Expense recorded!', 'success')
        except Exception as e:
            logging.error(f"Add expense error: {e}")
            conn.rollback()
            flash('Error recording expense.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('finance'))


@app.route('/finance/expense/delete/<int:expense_id>', methods=['POST'])
@login_required
@manage_required
def delete_expense(expense_id):
    farm_id = session.get('farm_id')
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM expenses WHERE id = %s AND farm_id = %s", (expense_id, farm_id))
            conn.commit()
            cursor.close()
            flash('Expense deleted.', 'success')
        except Exception as e:
            logging.error(f"Delete expense error: {e}")
            conn.rollback()
            flash('Error deleting expense.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('finance'))


@app.route('/finance/income/add', methods=['POST'])
@login_required
def add_income():
    farm_id = session.get('farm_id')
    if session.get('role') == 'field_worker':
        flash('Access denied.', 'error')
        return redirect(url_for('finance'))
    source = request.form.get('source', '').strip()
    product = request.form.get('product', '').strip()
    quantity = request.form.get('quantity') or None
    unit = request.form.get('unit', '').strip()
    unit_price = request.form.get('unit_price') or None
    amount = request.form.get('amount', 0)
    income_date = request.form.get('income_date')
    buyer = request.form.get('buyer', '').strip()
    notes = request.form.get('notes', '').strip()
    if not all([source, amount, income_date]):
        flash('Source, amount, and date are required.', 'error')
        return redirect(url_for('finance'))
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO income_records (farm_id, source, product, quantity, unit, unit_price, amount, income_date, buyer, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (farm_id, source, product or None, quantity, unit or None, unit_price, amount, income_date, buyer or None, notes or None))
            conn.commit()
            cursor.close()
            flash('Income recorded!', 'success')
        except Exception as e:
            logging.error(f"Add income error: {e}")
            conn.rollback()
            flash('Error recording income.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('finance'))


@app.route('/finance/income/delete/<int:income_id>', methods=['POST'])
@login_required
@manage_required
def delete_income(income_id):
    farm_id = session.get('farm_id')
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM income_records WHERE id = %s AND farm_id = %s", (income_id, farm_id))
            conn.commit()
            cursor.close()
            flash('Income record deleted.', 'success')
        except Exception as e:
            logging.error(f"Delete income error: {e}")
            conn.rollback()
            flash('Error deleting income.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('finance'))


# ─── Equipment ────────────────────────────────────────────────────────────────

@app.route('/equipment')
@login_required
def equipment():
    farm_id = session.get('farm_id')
    equip_list = []
    maintenance_list = []
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute("SELECT * FROM equipment WHERE farm_id = %s ORDER BY name", (farm_id,))
            equip_list = cursor.fetchall()
            cursor.execute("""
                SELECT mr.*, e.name as equipment_name FROM maintenance_records mr
                JOIN equipment e ON mr.equipment_id = e.id
                WHERE e.farm_id = %s ORDER BY mr.maintenance_date DESC LIMIT 50
            """, (farm_id,))
            maintenance_list = cursor.fetchall()
            cursor.close()
        except Exception as e:
            logging.error(f"Equipment error: {e}")
        finally:
            release_db_connection(conn)
    return render_template('equipment.html', equipment=equip_list, maintenance=maintenance_list)


@app.route('/equipment/add', methods=['POST'])
@login_required
@manage_required
def add_equipment():
    farm_id = session.get('farm_id')
    name = request.form.get('name', '').strip()
    equipment_type = request.form.get('equipment_type', '').strip()
    make = request.form.get('make', '').strip()
    model = request.form.get('model', '').strip()
    year = request.form.get('year') or None
    usage_hours = request.form.get('usage_hours') or 0
    fuel_type = request.form.get('fuel_type', '').strip()
    status = request.form.get('status', 'operational')
    last_service_date = request.form.get('last_service_date') or None
    next_service_date = request.form.get('next_service_date') or None
    notes = request.form.get('notes', '').strip()
    if not name:
        flash('Equipment name is required.', 'error')
        return redirect(url_for('equipment'))
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO equipment (farm_id, name, equipment_type, make, model, year, usage_hours, fuel_type, status, last_service_date, next_service_date, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (farm_id, name, equipment_type or None, make or None, model or None, year, usage_hours, fuel_type or None, status, last_service_date, next_service_date, notes or None))
            conn.commit()
            cursor.close()
            flash(f'Equipment "{name}" added!', 'success')
        except Exception as e:
            logging.error(f"Add equipment error: {e}")
            conn.rollback()
            flash('Error adding equipment.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('equipment'))


@app.route('/equipment/delete/<int:equip_id>', methods=['POST'])
@login_required
@manage_required
def delete_equipment(equip_id):
    farm_id = session.get('farm_id')
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM equipment WHERE id = %s AND farm_id = %s", (equip_id, farm_id))
            conn.commit()
            cursor.close()
            flash('Equipment deleted.', 'success')
        except Exception as e:
            logging.error(f"Delete equipment error: {e}")
            conn.rollback()
            flash('Error deleting equipment.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('equipment'))


@app.route('/equipment/maintenance/add', methods=['POST'])
@login_required
def add_maintenance():
    equipment_id = request.form.get('equipment_id')
    maintenance_type = request.form.get('maintenance_type', '').strip()
    maintenance_date = request.form.get('maintenance_date')
    description = request.form.get('description', '').strip()
    cost = request.form.get('cost') or 0
    performed_by = request.form.get('performed_by', '').strip()
    next_due_date = request.form.get('next_due_date') or None
    notes = request.form.get('notes', '').strip()
    if not all([equipment_id, maintenance_type, maintenance_date]):
        flash('Equipment, type, and date are required.', 'error')
        return redirect(url_for('equipment'))
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO maintenance_records (equipment_id, maintenance_type, maintenance_date, description, cost, performed_by, next_due_date, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (equipment_id, maintenance_type, maintenance_date, description or None, cost, performed_by or None, next_due_date, notes or None))
            if next_due_date:
                cursor.execute("UPDATE equipment SET last_service_date = %s, next_service_date = %s WHERE id = %s",
                               (maintenance_date, next_due_date, equipment_id))
            conn.commit()
            cursor.close()
            flash('Maintenance record added!', 'success')
        except Exception as e:
            logging.error(f"Add maintenance error: {e}")
            conn.rollback()
            flash('Error adding maintenance record.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('equipment'))


@app.route('/equipment/maintenance/delete/<int:record_id>', methods=['POST'])
@login_required
@manage_required
def delete_maintenance(record_id):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM maintenance_records WHERE id = %s", (record_id,))
            conn.commit()
            cursor.close()
            flash('Maintenance record deleted.', 'success')
        except Exception as e:
            logging.error(f"Delete maintenance error: {e}")
            conn.rollback()
            flash('Error deleting maintenance record.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('equipment'))


# ─── Inventory ────────────────────────────────────────────────────────────────

@app.route('/inventory')
@login_required
def inventory():
    farm_id = session.get('farm_id')
    items = []
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            category_filter = request.args.get('category', '')
            query = "SELECT * FROM inventory WHERE farm_id = %s"
            params = [farm_id]
            if category_filter:
                query += " AND category = %s"
                params.append(category_filter)
            query += " ORDER BY category, item_name"
            cursor.execute(query, params)
            items = cursor.fetchall()
            cursor.close()
        except Exception as e:
            logging.error(f"Inventory error: {e}")
        finally:
            release_db_connection(conn)
    return render_template('inventory.html', items=items, category_filter=request.args.get('category', ''))


@app.route('/inventory/add', methods=['POST'])
@login_required
@manage_required
def add_inventory():
    farm_id = session.get('farm_id')
    item_name = request.form.get('item_name', '').strip()
    category = request.form.get('category', '')
    quantity = request.form.get('quantity', 0)
    unit = request.form.get('unit', '').strip()
    min_quantity = request.form.get('min_quantity', 0)
    cost_per_unit = request.form.get('cost_per_unit') or 0
    location = request.form.get('location', '').strip()
    expiry_date = request.form.get('expiry_date') or None
    notes = request.form.get('notes', '').strip()
    if not all([item_name, category]):
        flash('Item name and category are required.', 'error')
        return redirect(url_for('inventory'))
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO inventory (farm_id, item_name, category, quantity, unit, min_quantity, cost_per_unit, location, expiry_date, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (farm_id, item_name, category, quantity, unit or None, min_quantity, cost_per_unit, location or None, expiry_date, notes or None))
            conn.commit()
            cursor.close()
            flash(f'"{item_name}" added to inventory!', 'success')
        except Exception as e:
            logging.error(f"Add inventory error: {e}")
            conn.rollback()
            flash('Error adding inventory item.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('inventory'))


@app.route('/inventory/update/<int:item_id>', methods=['POST'])
@login_required
def update_inventory(item_id):
    farm_id = session.get('farm_id')
    quantity = request.form.get('quantity', 0)
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE inventory SET quantity = %s WHERE id = %s AND farm_id = %s", (quantity, item_id, farm_id))
            conn.commit()
            cursor.close()
            flash('Quantity updated!', 'success')
        except Exception as e:
            logging.error(f"Update inventory error: {e}")
            conn.rollback()
            flash('Error updating quantity.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('inventory'))


@app.route('/inventory/delete/<int:item_id>', methods=['POST'])
@login_required
@manage_required
def delete_inventory(item_id):
    farm_id = session.get('farm_id')
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM inventory WHERE id = %s AND farm_id = %s", (item_id, farm_id))
            conn.commit()
            cursor.close()
            flash('Item deleted.', 'success')
        except Exception as e:
            logging.error(f"Delete inventory error: {e}")
            conn.rollback()
            flash('Error deleting item.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('inventory'))


# ─── Reports ─────────────────────────────────────────────────────────────────

@app.route('/reports')
@login_required
def reports():
    farm_id = session.get('farm_id')
    report = {}
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)

            cursor.execute("SELECT COALESCE(SUM(amount), 0) as total FROM income_records WHERE farm_id = %s", (farm_id,))
            report['total_income'] = float(cursor.fetchone()['total'])

            cursor.execute("SELECT COALESCE(SUM(amount), 0) as total FROM expenses WHERE farm_id = %s", (farm_id,))
            report['total_expenses'] = float(cursor.fetchone()['total'])
            report['net_profit'] = report['total_income'] - report['total_expenses']

            cursor.execute("""
                SELECT category, SUM(amount) as total, COUNT(*) as count
                FROM expenses WHERE farm_id = %s GROUP BY category ORDER BY total DESC
            """, (farm_id,))
            report['expenses_by_cat'] = cursor.fetchall()

            cursor.execute("""
                SELECT source, SUM(amount) as total, COUNT(*) as count
                FROM income_records WHERE farm_id = %s GROUP BY source ORDER BY total DESC
            """, (farm_id,))
            report['income_by_source'] = cursor.fetchall()

            cursor.execute("""
                SELECT activity_type, COUNT(*) as count FROM field_activities
                WHERE farm_id = %s GROUP BY activity_type ORDER BY count DESC
            """, (farm_id,))
            report['activities_by_type'] = cursor.fetchall()

            cursor.execute("""
                SELECT f.name, COUNT(fa.id) as activity_count FROM fields f
                LEFT JOIN field_activities fa ON fa.field_id = f.id
                WHERE f.farm_id = %s GROUP BY f.name ORDER BY activity_count DESC
            """, (farm_id,))
            report['field_activity'] = cursor.fetchall()

            cursor.execute("""
                SELECT status, COUNT(*) as count FROM tasks WHERE farm_id = %s GROUP BY status
            """, (farm_id,))
            report['tasks_by_status'] = cursor.fetchall()

            cursor.execute("""
                SELECT priority, COUNT(*) as count FROM tasks WHERE farm_id = %s GROUP BY priority
            """, (farm_id,))
            report['tasks_by_priority'] = cursor.fetchall()

            cursor.execute("""
                SELECT species, SUM(count) as total FROM livestock_groups WHERE farm_id = %s GROUP BY species
            """, (farm_id,))
            report['livestock_by_species'] = cursor.fetchall()

            cursor.execute("""
                SELECT category, COUNT(*) as count, SUM(quantity) as total_qty
                FROM inventory WHERE farm_id = %s GROUP BY category ORDER BY count DESC
            """, (farm_id,))
            report['inventory_by_cat'] = cursor.fetchall()

            cursor.execute("SELECT COUNT(*) as cnt FROM inventory WHERE farm_id = %s AND quantity <= min_quantity", (farm_id,))
            report['low_stock_count'] = cursor.fetchone()['cnt']

            cursor.execute("""
                SELECT status, COUNT(*) as count FROM equipment WHERE farm_id = %s GROUP BY status
            """, (farm_id,))
            report['equipment_by_status'] = cursor.fetchall()

            cursor.execute("""
                SELECT COALESCE(SUM(cost), 0) as total FROM maintenance_records mr
                JOIN equipment e ON mr.equipment_id = e.id WHERE e.farm_id = %s
            """, (farm_id,))
            report['total_maintenance_cost'] = float(cursor.fetchone()['total'])

            cursor.close()
        except Exception as e:
            logging.error(f"Reports error: {e}")
        finally:
            release_db_connection(conn)
    report_attachments = get_attachments_for(farm_id, ['report']).get(('report', farm_id), [])
    return render_template('reports.html', report=report, report_attachments=report_attachments, farm_id=farm_id)


# ─── Team / Users ─────────────────────────────────────────────────────────────

@app.route('/team')
@login_required
@manage_required
def team():
    farm_id = session.get('farm_id')
    members = []
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute("""
                SELECT u.id, u.username, u.email, u.role, u.created_at,
                       COUNT(t.id) as task_count
                FROM users u
                LEFT JOIN tasks t ON t.assigned_to = u.id AND t.status != 'completed'
                WHERE u.farm_id = %s
                GROUP BY u.id ORDER BY u.role, u.username
            """, (farm_id,))
            members = cursor.fetchall()
            cursor.close()
        except Exception as e:
            logging.error(f"Team error: {e}")
        finally:
            release_db_connection(conn)
    return render_template('team.html', members=members)


@app.route('/team/delete/<int:user_id>', methods=['POST'])
@login_required
@owner_required
def delete_team_member(user_id):
    farm_id = session.get('farm_id')
    if user_id == session.get('user_id'):
        flash('You cannot remove yourself.', 'error')
        return redirect(url_for('team'))
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE id = %s AND farm_id = %s", (user_id, farm_id))
            conn.commit()
            cursor.close()
            flash('Team member removed.', 'success')
        except Exception as e:
            logging.error(f"Delete team member error: {e}")
            conn.rollback()
            flash('Error removing team member.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('team'))


# ─── Profile & Settings ───────────────────────────────────────────────────────

IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def save_image(file, subfolder, old_path=None):
    """Save an uploaded image, remove old one, return relative static path."""
    if not file or file.filename == '':
        return None
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in IMAGE_EXTENSIONS:
        return None
    dest_dir = os.path.join(os.path.dirname(__file__), 'static', subfolder)
    os.makedirs(dest_dir, exist_ok=True)
    stored = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(dest_dir, stored))
    if old_path:
        old_full = os.path.join(os.path.dirname(__file__), 'static', old_path)
        if os.path.exists(old_full):
            os.remove(old_full)
    return f"{subfolder}/{stored}"


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user_id = session.get('user_id')
    farm_id = session.get('farm_id')
    conn = get_db_connection()
    if not conn:
        flash('Database connection error.', 'error')
        return redirect(url_for('index'))
    try:
        cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
        cursor.execute("SELECT u.*, f.name as farm_name, f.logo_path, f.location, f.total_area, f.area_unit, f.description FROM users u LEFT JOIN farms f ON u.farm_id = f.id WHERE u.id = %s", (user_id,))
        user = cursor.fetchone()
        cursor.close()
    except Exception as e:
        logging.error(f"Profile load error: {e}")
        user = None
    finally:
        release_db_connection(conn)
    return render_template('profile.html', user=user)


@app.route('/profile/avatar', methods=['POST'])
@login_required
def upload_avatar():
    user_id = session.get('user_id')
    file = request.files.get('avatar')
    if not file or file.filename == '':
        flash('No image selected.', 'error')
        return redirect(url_for('profile'))
    old_path = session.get('avatar_path', '')
    rel_path = save_image(file, 'avatars', old_path if old_path else None)
    if not rel_path:
        flash('Invalid image. Use JPG, PNG, GIF or WebP.', 'error')
        return redirect(url_for('profile'))
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET avatar_path = %s WHERE id = %s", (rel_path, user_id))
            conn.commit()
            cursor.close()
            session['avatar_path'] = rel_path
            flash('Profile picture updated!', 'success')
        except Exception as e:
            logging.error(f"Avatar upload error: {e}")
            conn.rollback()
            flash('Failed to save avatar.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('profile'))


@app.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    user_id = session.get('user_id')
    username = request.form.get('username', '').strip()
    email = request.form.get('email', '').strip()
    new_password = request.form.get('new_password', '').strip()
    confirm_password = request.form.get('confirm_password', '').strip()

    if not username or not email:
        flash('Username and email are required.', 'error')
        return redirect(url_for('profile'))

    if new_password and new_password != confirm_password:
        flash('Passwords do not match.', 'error')
        return redirect(url_for('profile'))

    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute("SELECT id FROM users WHERE (email = %s OR username = %s) AND id != %s", (email, username, user_id))
            if cursor.fetchone():
                flash('Username or email already taken by another account.', 'error')
                cursor.close()
                release_db_connection(conn)
                return redirect(url_for('profile'))
            if new_password:
                cursor.execute("UPDATE users SET username = %s, email = %s, password_hash = %s WHERE id = %s",
                               (username, email, generate_password_hash(new_password), user_id))
            else:
                cursor.execute("UPDATE users SET username = %s, email = %s WHERE id = %s",
                               (username, email, user_id))
            conn.commit()
            cursor.close()
            session['username'] = username
            flash('Profile updated successfully!', 'success')
        except Exception as e:
            logging.error(f"Update profile error: {e}")
            conn.rollback()
            flash('Failed to update profile.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('profile'))


@app.route('/farm/logo', methods=['POST'])
@login_required
@owner_required
def upload_farm_logo():
    farm_id = session.get('farm_id')
    file = request.files.get('logo')
    if not file or file.filename == '':
        flash('No image selected.', 'error')
        return redirect(url_for('profile'))
    old_path = session.get('farm_logo', '')
    rel_path = save_image(file, 'logos', old_path if old_path else None)
    if not rel_path:
        flash('Invalid image. Use JPG, PNG, GIF or WebP.', 'error')
        return redirect(url_for('profile'))
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE farms SET logo_path = %s WHERE id = %s", (rel_path, farm_id))
            conn.commit()
            cursor.close()
            session['farm_logo'] = rel_path
            flash('Farm logo updated!', 'success')
        except Exception as e:
            logging.error(f"Logo upload error: {e}")
            conn.rollback()
            flash('Failed to save logo.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('profile'))


@app.route('/farm/logo/remove', methods=['POST'])
@login_required
@owner_required
def remove_farm_logo():
    farm_id = session.get('farm_id')
    old_path = session.get('farm_logo', '')
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE farms SET logo_path = NULL WHERE id = %s", (farm_id,))
            conn.commit()
            cursor.close()
            if old_path:
                full = os.path.join(os.path.dirname(__file__), 'static', old_path)
                if os.path.exists(full):
                    os.remove(full)
            session['farm_logo'] = ''
            flash('Farm logo removed.', 'success')
        except Exception as e:
            logging.error(f"Remove logo error: {e}")
            conn.rollback()
        finally:
            release_db_connection(conn)
    return redirect(url_for('profile'))


@app.route('/profile/avatar/remove', methods=['POST'])
@login_required
def remove_avatar():
    user_id = session.get('user_id')
    old_path = session.get('avatar_path', '')
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET avatar_path = NULL WHERE id = %s", (user_id,))
            conn.commit()
            cursor.close()
            if old_path:
                full = os.path.join(os.path.dirname(__file__), 'static', old_path)
                if os.path.exists(full):
                    os.remove(full)
            session['avatar_path'] = ''
            flash('Profile picture removed.', 'success')
        except Exception as e:
            logging.error(f"Remove avatar error: {e}")
            conn.rollback()
        finally:
            release_db_connection(conn)
    return redirect(url_for('profile'))


# ─── Per-Record Attachment Helper & Routes ────────────────────────────────────

ATTACH_ENTITY_TYPES = {
    'livestock_group', 'livestock_record',
    'field', 'field_activity',
    'expense', 'income', 'report'
}

def get_attachments_for(farm_id, entity_types):
    """Return {(entity_type, entity_id): [upload_rows]}"""
    result = {}
    if not entity_types:
        return result
    conn = get_db_connection()
    if not conn:
        return result
    try:
        cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
        placeholders = ','.join(['%s'] * len(entity_types))
        cursor.execute(f"""
            SELECT up.*, u.username as uploader
            FROM uploads up
            LEFT JOIN users u ON up.uploaded_by = u.id
            WHERE up.farm_id = %s AND up.entity_type IN ({placeholders})
            ORDER BY up.uploaded_at ASC
        """, [farm_id] + list(entity_types))
        for row in cursor.fetchall():
            key = (row['entity_type'], row['entity_id'])
            result.setdefault(key, []).append(row)
        cursor.close()
    except Exception as e:
        logging.error(f"get_attachments_for error: {e}")
    finally:
        release_db_connection(conn)
    return result


@app.route('/attach/<entity_type>/<int:entity_id>', methods=['POST'])
@login_required
def attach_file(entity_type, entity_id):
    farm_id = session.get('farm_id')
    user_id = session.get('user_id')
    back = request.form.get('back_url') or request.referrer or url_for('index')
    if entity_type not in ATTACH_ENTITY_TYPES:
        flash('Invalid attachment type.', 'error')
        return redirect(back)
    file = request.files.get('file')
    description = request.form.get('description', '').strip()
    if not file or file.filename == '':
        flash('No file selected.', 'error')
        return redirect(back)
    if not allowed_file(file.filename):
        flash('File type not allowed. Use images, PDF, Word, Excel, CSV or TXT.', 'error')
        return redirect(back)
    original_name = secure_filename(file.filename)
    ext = original_name.rsplit('.', 1)[1].lower() if '.' in original_name else 'bin'
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    file_cat = get_file_category(original_name)
    farm_dir = os.path.join(UPLOAD_FOLDER, str(farm_id))
    os.makedirs(farm_dir, exist_ok=True)
    save_path = os.path.join(farm_dir, stored_name)
    file.save(save_path)
    file_size = os.path.getsize(save_path)
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO uploads (farm_id, original_filename, stored_filename, file_type,
                                     file_size, category, entity_type, entity_id, description, uploaded_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (farm_id, original_name, stored_name, ext, file_size,
                  file_cat, entity_type, entity_id, description or None, user_id))
            conn.commit()
            cursor.close()
            flash(f'"{original_name}" attached!', 'success')
        except Exception as e:
            logging.error(f"Attach file error: {e}")
            conn.rollback()
            os.remove(save_path)
            flash('Failed to attach file.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(back)


@app.route('/attach/delete/<int:file_id>', methods=['POST'])
@login_required
def delete_attachment(file_id):
    farm_id = session.get('farm_id')
    user_id = session.get('user_id')
    role = session.get('role')
    back = request.form.get('back_url') or request.referrer or url_for('index')
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute("SELECT * FROM uploads WHERE id = %s AND farm_id = %s", (file_id, farm_id))
            upload = cursor.fetchone()
            if not upload:
                flash('Attachment not found.', 'error')
            elif upload['uploaded_by'] != user_id and role not in MANAGE_ROLES:
                flash('You can only delete your own attachments.', 'error')
            else:
                cursor.execute("DELETE FROM uploads WHERE id = %s", (file_id,))
                conn.commit()
                fp = os.path.join(UPLOAD_FOLDER, str(farm_id), upload['stored_filename'])
                if os.path.exists(fp):
                    os.remove(fp)
                flash('Attachment deleted.', 'success')
            cursor.close()
        except Exception as e:
            logging.error(f"Delete attachment error: {e}")
            conn.rollback()
            flash('Error deleting attachment.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(back)


# ─── Files & Documents ────────────────────────────────────────────────────────

@app.route('/files')
@login_required
def files():
    farm_id = session.get('farm_id')
    uploads = []
    category_filter = request.args.get('category', '')
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            q = """
                SELECT up.*, u.username as uploader
                FROM uploads up
                LEFT JOIN users u ON up.uploaded_by = u.id
                WHERE up.farm_id = %s
            """
            params = [farm_id]
            if category_filter:
                q += " AND up.category = %s"
                params.append(category_filter)
            q += " ORDER BY up.uploaded_at DESC"
            cursor.execute(q, params)
            uploads = cursor.fetchall()
            cursor.close()
        except Exception as e:
            logging.error(f"Files list error: {e}")
        finally:
            release_db_connection(conn)
    return render_template('files.html', uploads=uploads, category_filter=category_filter)


@app.route('/files/upload', methods=['POST'])
@login_required
def upload_file():
    farm_id = session.get('farm_id')
    user_id = session.get('user_id')

    if 'file' not in request.files:
        flash('No file selected.', 'error')
        return redirect(url_for('files'))

    file = request.files['file']
    if file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('files'))

    if not allowed_file(file.filename):
        flash('File type not allowed. Allowed: images, PDF, Word, Excel, CSV, ZIP, TXT.', 'error')
        return redirect(url_for('files'))

    original_name = secure_filename(file.filename)
    ext = original_name.rsplit('.', 1)[1].lower() if '.' in original_name else 'bin'
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    file_category = get_file_category(original_name)
    description = request.form.get('description', '').strip()

    farm_upload_dir = os.path.join(UPLOAD_FOLDER, str(farm_id))
    os.makedirs(farm_upload_dir, exist_ok=True)
    save_path = os.path.join(farm_upload_dir, stored_name)
    file.save(save_path)
    file_size = os.path.getsize(save_path)

    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO uploads (farm_id, original_filename, stored_filename, file_type, file_size, category, description, uploaded_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (farm_id, original_name, stored_name, ext, file_size, file_category, description or None, user_id))
            conn.commit()
            cursor.close()
            flash(f'"{original_name}" uploaded successfully!', 'success')
        except Exception as e:
            logging.error(f"Upload DB error: {e}")
            conn.rollback()
            os.remove(save_path)
            flash('Upload failed. Please try again.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('files'))


@app.route('/files/view/<int:file_id>')
@login_required
def view_file(file_id):
    farm_id = session.get('farm_id')
    conn = get_db_connection()
    upload = None
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute("SELECT * FROM uploads WHERE id = %s AND farm_id = %s", (file_id, farm_id))
            upload = cursor.fetchone()
            cursor.close()
        except Exception as e:
            logging.error(f"View file error: {e}")
        finally:
            release_db_connection(conn)
    if not upload:
        abort(404)
    farm_upload_dir = os.path.join(UPLOAD_FOLDER, str(farm_id))
    ext = upload['stored_filename'].rsplit('.', 1)[-1].lower() if '.' in upload['stored_filename'] else ''
    inline_types = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'pdf', 'txt'}
    as_attach = ext not in inline_types
    return send_from_directory(farm_upload_dir, upload['stored_filename'],
                               download_name=upload['original_filename'],
                               as_attachment=as_attach)


@app.route('/files/download/<int:file_id>')
@login_required
def download_file(file_id):
    farm_id = session.get('farm_id')
    conn = get_db_connection()
    upload = None
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute("SELECT * FROM uploads WHERE id = %s AND farm_id = %s", (file_id, farm_id))
            upload = cursor.fetchone()
            cursor.close()
        except Exception as e:
            logging.error(f"Download file error: {e}")
        finally:
            release_db_connection(conn)
    if not upload:
        abort(404)
    farm_upload_dir = os.path.join(UPLOAD_FOLDER, str(farm_id))
    return send_from_directory(farm_upload_dir, upload['stored_filename'],
                               download_name=upload['original_filename'], as_attachment=True)


@app.route('/files/delete/<int:file_id>', methods=['POST'])
@login_required
def delete_file(file_id):
    farm_id = session.get('farm_id')
    user_id = session.get('user_id')
    role = session.get('role')
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute("SELECT * FROM uploads WHERE id = %s AND farm_id = %s", (file_id, farm_id))
            upload = cursor.fetchone()
            if not upload:
                flash('File not found.', 'error')
                cursor.close()
                release_db_connection(conn)
                return redirect(url_for('files'))
            if upload['uploaded_by'] != user_id and role not in MANAGE_ROLES:
                flash('You can only delete your own files.', 'error')
                cursor.close()
                release_db_connection(conn)
                return redirect(url_for('files'))
            cursor.execute("DELETE FROM uploads WHERE id = %s", (file_id,))
            conn.commit()
            cursor.close()
            file_path = os.path.join(UPLOAD_FOLDER, str(farm_id), upload['stored_filename'])
            if os.path.exists(file_path):
                os.remove(file_path)
            flash('File deleted.', 'success')
        except Exception as e:
            logging.error(f"Delete file error: {e}")
            conn.rollback()
            flash('Error deleting file.', 'error')
        finally:
            release_db_connection(conn)
    return redirect(url_for('files'))
