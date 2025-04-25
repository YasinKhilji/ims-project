from flask import (
    Flask, render_template, request, redirect, url_for, flash, session, 
    jsonify)
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from psycopg2.extras import RealDictCursor
from functools import wraps
from flask_wtf.csrf import CSRFProtect
from database import (
    get_products, get_orders, create_order, process_order, user_login, 
    get_db_connection, get_suppliers, add_supplier_to_db, 
    get_user_notifications, get_unread_notification_count, mark_notification_as_read,create_notification
)

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Change this in production!
csrf = CSRFProtect(app)
# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Role requirements
def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_view(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            if current_user.role not in roles:
                flash('You do not have permission to access this page.', 'danger')
                return redirect(url_for('home'))
            return f(*args, **kwargs)
        return decorated_view
    return decorator

# User model
class User(UserMixin):
    def __init__(self, user_id, username, role):
        self.id = user_id
        self.username = username
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, role FROM users WHERE user_id = %s", (user_id,))
    user_data = cur.fetchone()
    cur.close()
    conn.close()
    if user_data:
        return User(user_data[0], user_data[1], user_data[2])
    return None

# Routes
@app.route('/')
@login_required
def index():
    if current_user.role == 'Admin':
        return redirect(url_for('admin_dashboard'))
    elif current_user.role == 'InventoryManager':
        return redirect(url_for('inventory_dashboard'))
    return redirect(url_for('products'))

@app.route('/admin/dashboard')
@login_required
@role_required('Admin')
def admin_dashboard():
    user_count = 0
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        user_count = cur.fetchone()[0]
        cur.close()
        conn.close()
    except Exception as e:
        flash(f'Error loading user count: {str(e)}', 'danger')
    return render_template('admin_dashboard.html', user_count=user_count)

@app.route('/inventory/dashboard')
@login_required
@role_required('InventoryManager')
def inventory_dashboard():
    return render_template('inventory_dashboard.html')

@app.route('/products')
@login_required
def products():
    try:
        products = get_products()
        if not products:
            flash('No products found in the database.', 'warning')
        return render_template('products.html', 
                             products=products,
                             can_edit=current_user.role in ['Admin', 'InventoryManager'])  # Explicit role check
    except Exception as e:
        flash(f'Error loading products: {str(e)}', 'danger')
        return redirect(url_for('admin_dashboard' if current_user.role == 'Admin' else 'inventory_dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user_data = user_login(username, password)
        if user_data:
            user = User(user_data['user_id'], user_data['username'], user_data['role'])
            login_user(user)
            flash('Logged in successfully!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully!', 'success')
    return redirect(url_for('login'))

@app.route('/products/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
@role_required('Admin', 'InventoryManager')
def edit_product(product_id):
    from database import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor()
    suppliers = []  # Initialize suppliers to avoid UnboundLocalError
    try:
        if request.method == 'POST':
            product_name = request.form.get('product_name')
            category = request.form.get('category')
            price = request.form.get('price')
            quantity = request.form.get('quantity')
            supplier_id = request.form.get('supplier_id')
            min_stocks = request.form.get('min_stocks')
            updated_by = current_user.id
            cur.execute("""
                CALL update_product(%s, %s, %s, %s, %s, %s, %s, %s)
            """, (product_id, product_name, category, price, quantity, supplier_id, min_stocks, updated_by))
            conn.commit()
            flash('Product updated successfully!', 'success')
            return redirect(url_for('products'))
        cur.execute("SELECT * FROM products WHERE product_id = %s AND is_deleted = FALSE", (product_id,))
        product = cur.fetchone()
        if not product:
            flash('Product not found!', 'danger')
            return redirect(url_for('products'))
        cur.execute("SELECT supplier_id, supplier_name FROM suppliers")
        suppliers = cur.fetchall()
    except Exception as e:
        conn.rollback()
        flash(f'Error updating product: {str(e)}', 'danger')
    finally:
        cur.close()
        conn.close()
    return render_template('edit_product.html', product=product, suppliers=suppliers)

# Order routes
@app.route('/orders')
@login_required
def orders():
    try:
        orders = get_orders()
        return render_template('orders.html', orders=orders, can_process=current_user.role in ['Admin', 'Sales'])
    except Exception as e:
        flash(f'Error loading orders: {str(e)}', 'danger')
        return redirect(url_for('admin_dashboard' if current_user.role == 'Admin' else 'inventory_dashboard'))

from database import get_db_connection

@app.route('/orders/create', methods=['GET', 'POST'])
@login_required
@role_required('Sales', 'Admin')
def create_new_order():
    if request.method == 'POST':
        product_id = request.form['product_id']
        try:
            quantity = int(request.form['quantity'])
            if quantity <= 0:
                flash('Quantity must be positive!', 'danger')
                return redirect(url_for('create_new_order'))
            
            added_by = current_user.id
            notes = request.form.get('notes')
            
            conn = get_db_connection()
            cur = conn.cursor()
            
            # Get product details
            cur.execute("SELECT product_name FROM products WHERE product_id = %s", (product_id,))
            product = cur.fetchone()
            if not product:
                flash('Product not found!', 'danger')
                return redirect(url_for('create_new_order'))
            
            product_name = product[0]
            
            # Create the order
            cur.execute("CALL create_order(%s, %s, %s, %s, %s, %s)", 
                       (product_id, quantity, added_by, notes, None, None))
            conn.commit()
            
            # Get the created order ID
            cur.execute("SELECT lastval()")  # More reliable way to get the last inserted ID
            order_id = cur.fetchone()[0]
            
            # Notify inventory managers
            cur.execute("SELECT user_id FROM users WHERE role = 'InventoryManager'")
            managers = cur.fetchall()
            for (manager_id,) in managers:
                create_notification(
                    user_id=manager_id,
                    message=f"New order #{order_id} for {product_name} (Qty: {quantity})",
                    notification_type="OrderCreated",
                    related_entity_type="order",
                    related_entity_id=order_id
                )
            
            conn.commit()  # Commit the notifications
            flash('Order created and notifications sent!', 'success')
            return redirect(url_for('orders'))
            
        except Exception as e:
            if 'conn' in locals():
                conn.rollback()
            flash(f'Error creating order: {str(e)}', 'danger')
            return redirect(url_for('create_new_order'))
        finally:
            if 'cur' in locals():
                cur.close()
            if 'conn' in locals():
                conn.close()
    
    products = get_products()
    return render_template('create_order.html', products=products)

@app.route('/audit_log')
@login_required
@role_required('Admin')
def audit_log():
    from database import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT al.log_id, al.table_name, al.action, al.created_at, u.role
            FROM audit_log al
            LEFT JOIN users u ON al.changed_by = u.user_id
            ORDER BY al.created_at DESC
        """)
        logs = cur.fetchall()
    except Exception as e:
        flash(f'Error fetching audit logs: {str(e)}', 'danger')
        logs = []
    finally:
        cur.close()
        conn.close()
    return render_template('audit_log.html', logs=logs)

@app.route('/orders/process/<int:order_id>', methods=['GET', 'POST'])
@login_required
@role_required('Admin', 'InventoryManager')
def process_order(order_id):
    from database import process_order
    if request.method == 'POST':
        status = request.form['status']
        processed_by = current_user.id
        notes = request.form.get('notes')
        try:
            process_order(order_id, status, processed_by, notes)
            flash('Order processed successfully!', 'success')
            return redirect(url_for('orders'))
        except Exception as e:
            flash(f'Error processing order: {str(e)}', 'danger')
            return redirect(url_for('process_order', order_id=order_id))
    return render_template('process_order.html', order_id=order_id)

# User management routes
@app.route('/users', methods=['GET', 'POST'])
@login_required
@role_required('Admin')
def users():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT user_id, username, role, email, is_active FROM users")
        users = cur.fetchall()
        cur.close()
        conn.close()
        print(f"Debug: Fetched users - {users}")
        if request.method == 'POST':
            username = request.form['username']
            password = request.form['password']
            role = request.form['role']
            email = request.form['email']
            is_active = 'on' in request.form.get('is_active', '')
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO users (username, password, role, email, full_name, is_active)
                VALUES (%s, crypt(%s, gen_salt('bf')), %s, %s, %s, %s)
            """, (username, password, role, email, username, is_active))
            conn.commit()
            cur.close()
            conn.close()
            flash('User created successfully!', 'success')
            return redirect(url_for('users'))
        if not users:
            flash('No users found in the database. Add a user using the form below.', 'warning')
        return render_template('users.html', users=users)
    except Exception as e:
        flash(f'Error loading users: {str(e)}', 'danger')
        print(f"Debug: Error in /users route - {str(e)}")
        return redirect(url_for('admin_dashboard'))

@app.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
@login_required
@role_required('Admin')
def edit_user(user_id):
    from database import get_db_connection
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT user_id, username, role, email, is_active FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        if not user:
            flash('User not found!', 'danger')
            return redirect(url_for('users'))
        print(f"Debug: Fetched user - {user}")  # Log the user data
        if request.method == 'POST':
            username = request.form.get('username', user['username'])
            role = request.form.get('role', user['role'])
            email = request.form.get('email', user['email'])
            is_active = 'on' in request.form.get('is_active', str(user['is_active']))
            password = request.form.get('password')
            conn = get_db_connection()
            cur = conn.cursor()
            if password:
                cur.execute("""
                    UPDATE users 
                    SET username = %s, role = %s, email = %s, is_active = %s, password = crypt(%s, gen_salt('bf'))
                    WHERE user_id = %s
                """, (username, role, email, is_active, password, user_id))
            else:
                cur.execute("""
                    UPDATE users 
                    SET username = %s, role = %s, email = %s, is_active = %s
                    WHERE user_id = %s
                """, (username, role, email, is_active, user_id))
            conn.commit()
            cur.close()
            conn.close()
            flash('User updated successfully!', 'success')
            return redirect(url_for('users'))
        return render_template('edit_user.html', user=user)
    except Exception as e:
        flash(f'Error editing user: {str(e)}', 'danger')
        print(f"Debug: Error in edit_user route - {str(e)}")  # Log the error
        return redirect(url_for('users'))
    
@app.route('/transactions')
@login_required
@role_required('Admin', 'InventoryManager')
def transactions():
    from database import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT t.transaction_id, t.product_id, p.product_name, t.transaction_type, t.quantity,
                   t.total_amount, u.username AS performed_by, t.transaction_date, t.notes
            FROM transactions t
            LEFT JOIN products p ON t.product_id = p.product_id
            LEFT JOIN users u ON t.performed_by = u.user_id
            ORDER BY t.transaction_date DESC
        """)
        transactions = cur.fetchall()
    except Exception as e:
        flash(f'Error fetching transactions: {str(e)}', 'danger')
        transactions = []
    finally:
        cur.close()
        conn.close()
    return render_template('transactions.html', transactions=transactions)
    
@app.route('/reports')
@login_required
@role_required('Admin')
def reports():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Total users
        cur.execute("SELECT COUNT(*) FROM users WHERE is_active = TRUE")
        total_active_users = cur.fetchone()[0]
        # Total products
        cur.execute("SELECT COUNT(*) FROM products WHERE is_deleted = FALSE")
        total_products = cur.fetchone()[0]
        cur.close()
        conn.close()
        return render_template('reports.html', total_active_users=total_active_users, total_products=total_products)
    except Exception as e:
        flash(f'Error loading reports: {str(e)}', 'danger')
        return redirect(url_for('admin_dashboard'))

# Add this with your other route imports
from database import get_suppliers, add_supplier_to_db

# --- Supplier Routes ---
@app.route('/suppliers')
@login_required
@role_required('Admin', 'InventoryManager')
def list_suppliers():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM suppliers")
        suppliers = cur.fetchall()
        return render_template('suppliers.html', suppliers=suppliers)
    except Exception as e:
        flash(str(e), 'danger')
        return redirect(url_for('index'))
    finally:
        cur.close()
        conn.close()


@app.route('/suppliers/add', methods=['GET', 'POST'])
@login_required
@role_required('Admin', 'InventoryManager')
def add_supplier():
    if request.method == 'POST':
        supplier_name = request.form['supplier_name']
        contact_info = request.form['contact_info']
        
        try:
            add_supplier_to_db(supplier_name, contact_info)
            flash('Supplier added successfully!', 'success')
            return redirect(url_for('list_suppliers'))
        except Exception as e:
            flash(f'Error adding supplier: {str(e)}', 'danger')
    
    return render_template('add_supplier.html')

@app.route('/suppliers/edit/<int:supplier_id>', methods=['GET', 'POST'])
@login_required
@role_required('Admin', 'InventoryManager')
def edit_supplier(supplier_id):
    if request.method == 'POST':
        try:
            from database import update_supplier  # Import the function
            update_supplier(
                supplier_id,
                request.form['supplier_name'],
                request.form['contact_info']
            )
            flash('Supplier updated successfully!', 'success')
            return redirect(url_for('list_suppliers'))
        except Exception as e:
            flash(f'Error updating supplier: {str(e)}', 'danger')
    
    # GET request handling
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM suppliers WHERE supplier_id = %s", (supplier_id,))
        supplier = cur.fetchone()
        if not supplier:
            flash('Supplier not found!', 'danger')
            return redirect(url_for('list_suppliers'))
        return render_template('edit_supplier.html', supplier=supplier)
    except Exception as e:
        flash(f'Error loading supplier: {str(e)}', 'danger')
        return redirect(url_for('list_suppliers'))
    finally:
        cur.close()
        conn.close()

# Add this with your other routes
@app.route('/suppliers/delete/<int:supplier_id>', methods=['POST'])
@login_required
@role_required('Admin')
def delete_supplier(supplier_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM suppliers WHERE supplier_id = %s", (supplier_id,))
        conn.commit()
        flash('Supplier deleted', 'success')
    except Exception as e:
        flash(str(e), 'danger')
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('list_suppliers'))

@app.route('/suppliers/<int:supplier_id>')
@login_required
@role_required('Admin', 'InventoryManager')
def supplier_details(supplier_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get supplier info
        cur.execute("SELECT * FROM suppliers WHERE supplier_id = %s", (supplier_id,))
        supplier = cur.fetchone()
        
        if not supplier:
            flash('Supplier not found!', 'danger')
            return redirect(url_for('list_suppliers'))
        
        # Get associated products
        cur.execute("""
            SELECT product_id, product_name, quantity 
            FROM products 
            WHERE supplier_id = %s AND is_deleted = FALSE
            ORDER BY product_name
        """, (supplier_id,))
        products = cur.fetchall()
        
        return render_template(
            'supplier_details.html',
            supplier=supplier,
            products=products
        )
        
    except Exception as e:
        flash(f'Error loading supplier details: {str(e)}', 'danger')
        return redirect(url_for('list_suppliers'))
    finally:
        cur.close()
        conn.close()

@app.route('/suppliers/reports')
@login_required
@role_required('Admin', 'InventoryManager')
def supplier_reports():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get supplier performance metrics
        cur.execute("""
            SELECT 
                s.supplier_id,
                s.supplier_name,
                COUNT(p.product_id) AS product_count,
                SUM(p.quantity) AS total_stock,
                AVG(p.price) AS avg_price
            FROM suppliers s
            LEFT JOIN products p ON s.supplier_id = p.supplier_id
            WHERE p.is_deleted = FALSE OR p.product_id IS NULL
            GROUP BY s.supplier_id
            ORDER BY product_count DESC
        """)
        supplier_stats = cur.fetchall()
        
        return render_template('supplier_reports.html', 
                            supplier_stats=supplier_stats)
        
    except Exception as e:
        flash(f'Error generating reports: {str(e)}', 'danger')
        return redirect(url_for('list_suppliers'))
    finally:
        cur.close()
        conn.close()

@app.route('/low_stock')
@login_required
@role_required('Admin', 'InventoryManager')
def low_stock():
    from database import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor()
    low_stock_data = []
    try:
        cur.execute("SELECT * FROM vw_low_stock")
        low_stock_data = cur.fetchall()
    except Exception as e:
        flash(f'Error fetching low stock data: {str(e)}', 'danger')
    finally:
        cur.close()
        conn.close()
    return render_template('low_stock.html', low_stock_data=low_stock_data)
from datetime import datetime

@app.context_processor
def utility_processor():
    def notifications_unread_count():
        if not current_user.is_authenticated:
            return 0
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM notifications WHERE user_id = %s AND is_read = FALSE", (current_user.id,))
        count = cur.fetchone()[0]
        conn.close()
        return count
    return dict(notifications_unread_count=notifications_unread_count)

# Time ago filter (add to Flask app)
@app.template_filter('time_ago')
def time_ago_filter(dt):
    now = datetime.now()
    diff = now - dt
    if diff.days > 0:
        return f"{diff.days}d ago"
    elif diff.seconds > 3600:
        return f"{diff.seconds // 3600}h ago"
    elif diff.seconds > 60:
        return f"{diff.seconds // 60}m ago"
    else:
        return "Just now"
# Add these new routes to app.py

@app.route('/notifications')
@login_required
def view_all_notifications():
    try:
        notifications = get_user_notifications(current_user.id, limit=20)
        return render_template('notifications.html', notifications=notifications)
    except Exception as e:
        flash(f'Error loading notifications: {str(e)}', 'danger')
        return redirect(url_for('index'))

@app.route('/api/notifications')
@login_required
def get_notifications_api():
    try:
        limit = request.args.get('limit', default=5, type=int)
        notifications = get_user_notifications(current_user.id, limit=limit)
        return jsonify(notifications)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/notifications/unread-count')
@login_required
def get_unread_count_api():
    try:
        count = get_unread_notification_count(current_user.id)
        return jsonify({'count': count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/notifications/mark-read/<int:notification_id>', methods=['GET', 'POST'])
@login_required
def mark_notification_read(notification_id):
    try:
        result = mark_notification_as_read(notification_id, current_user.id)
        redirect_url = url_for('view_all_notifications')  # Default redirect
        if result:
            entity_type, entity_id = result
            if entity_type == 'order':
                redirect_url = url_for('view_order', order_id=entity_id)
            elif entity_type == 'product':
                redirect_url = url_for('edit_product', product_id=entity_id)
            elif entity_type == 'user':
                redirect_url = url_for('view_user', user_id=entity_id)  # Add this
        return redirect(redirect_url)
    except Exception as e:
        flash(f'Error marking notification as read: {str(e)}', 'danger')
        return redirect(url_for('view_all_notifications'))

@app.route('/orders/<int:order_id>')
@login_required
@role_required('Admin', 'InventoryManager', 'Sales')
def view_order(order_id):
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT o.*, p.product_name, u.username AS added_by_username
            FROM orders o
            JOIN products p ON o.product_id = o.product_id
            JOIN users u ON o.added_by = u.user_id
            WHERE o.order_id = %s
        """, (order_id,))
        order = cur.fetchone()
        
        if not order:
            flash('Order not found!', 'danger')
            return redirect(url_for('orders'))
            
        cur.execute("""
            SELECT t.*, u.username AS performed_by_username
            FROM transactions t
            LEFT JOIN users u ON t.performed_by = u.user_id
            WHERE t.reference_id = %s
            ORDER BY t.created_at DESC
        """, (order_id,))
        transactions = cur.fetchall()
        
        return render_template('order_details.html', order=order, transactions=transactions)
    except Exception as e:
        flash(f'Error loading order details: {str(e)}', 'danger')
        return redirect(url_for('orders'))
    finally:
        cur.close()
        conn.close()

@app.route('/products/add', methods=['GET', 'POST'])
@login_required
@role_required('Admin', 'InventoryManager')
def add_product():
    if request.method == 'POST':
        try:
            # Get form data with proper validation
            product_name = request.form.get('product_name', '').strip()
            category = request.form.get('category', '').strip()
            
            # Validate required fields
            if not product_name or not category:
                flash('Product name and category are required', 'danger')
                return redirect(url_for('add_product'))
            
            # Convert with proper error handling
            try:
                price = float(request.form.get('price', 0))
                quantity = int(request.form.get('quantity', 0))
                supplier_id = int(request.form.get('supplier_id', 0))
                min_stocks = int(request.form.get('min_stocks', 5))
            except (ValueError, TypeError):
                flash('Invalid numeric values provided', 'danger')
                return redirect(url_for('add_product'))
            
            # Validate positive numbers
            if price <= 0 or quantity < 0 or supplier_id <= 0 or min_stocks < 0:
                flash('All numeric values must be positive', 'danger')
                return redirect(url_for('add_product'))
            
            conn = get_db_connection()
            cur = conn.cursor()
            
            # Check supplier exists
            cur.execute("SELECT 1 FROM suppliers WHERE supplier_id = %s", (supplier_id,))
            if not cur.fetchone():
                flash('Invalid supplier selected', 'danger')
                return redirect(url_for('add_product'))
            
            # Insert product
            cur.execute("""
                INSERT INTO products (product_name, category, price, quantity, 
                                    supplier_id, min_stocks, added_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING product_id
            """, (product_name, category, price, quantity, 
                 supplier_id, min_stocks, current_user.id))
            
            product_id = cur.fetchone()[0]
            conn.commit()
            
            flash('Product added successfully!', 'success')
            return redirect(url_for('products'))
            
        except Exception as e:
            if 'conn' in locals():
                conn.rollback()
            flash(f'Error adding product: {str(e)}', 'danger')
        finally:
            if 'cur' in locals():
                cur.close()
            if 'conn' in locals():
                conn.close()
    
    # GET request - show the form
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name")
        suppliers = cur.fetchall()
        
        if not suppliers:
            flash('No suppliers found. Please add suppliers first.', 'warning')
            return redirect(url_for('list_suppliers'))
            
        return render_template('add_product.html', suppliers=suppliers)
    except Exception as e:
        flash(f'Error loading form: {str(e)}', 'danger')
        return redirect(url_for('products'))
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

DEFAULT_ROLE='Sales'
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        email = request.form['email']
        full_name = request.form['full_name']
        role = request.form['role']
        
        if password != confirm_password:
            flash('Passwords do not match', 'danger')
            return redirect(url_for('register'))
            
        allowed_roles = ['Sales', 'InventoryManager']
        if role not in allowed_roles:
            flash('Invalid role selected', 'danger')
            return redirect(url_for('register'))
            
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            cur.execute("SELECT 1 FROM users WHERE username = %s OR email = %s", (username, email))
            if cur.fetchone():
                flash('Username or email already exists', 'danger')
                return redirect(url_for('register'))
            
            cur.execute("""
                INSERT INTO users (username, password, role, email, full_name, is_active)
                VALUES (%s, crypt(%s, gen_salt('bf')), %s, %s, %s, FALSE)
                RETURNING user_id
            """, (username, password, role, email, full_name))
            user_id = cur.fetchone()[0]
            
            # Find admin user dynamically
            cur.execute("SELECT user_id FROM users WHERE role = 'Admin' LIMIT 1")
            admin_row = cur.fetchone()
            admin_id = admin_row[0] if admin_row else 1  # Fallback to 1 if no admin found
            
            conn.commit()
            
            create_notification(
                user_id=admin_id,
                message=f"New {role} registration awaiting approval: {username}",
                notification_type="SystemAlert",
                related_entity_type="user",
                related_entity_id=user_id
            )
            
            flash('Registration successful! Your account is pending admin approval.', 'success')
            return redirect(url_for('login'))
            
        except Exception as e:
            conn.rollback()
            flash(f'Registration error: {str(e)}', 'danger')
        finally:
            cur.close()
            conn.close()
    
    return render_template('register.html')

@app.route('/admin/approve-users')
@login_required
@role_required('Admin')
def approve_users():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM users WHERE is_active = FALSE ORDER BY created_at")
        pending_users = cur.fetchall()
        return render_template('approve_users.html', users=pending_users)
    except Exception as e:
        flash(f'Error loading pending users: {str(e)}', 'danger')
        return redirect(url_for('admin_dashboard'))
    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()

@app.route('/admin/approve-user/<int:user_id>', methods=['POST'])
@login_required
@role_required('Admin')
def approve_user(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET is_active = TRUE WHERE user_id = %s", (user_id,))
        conn.commit()
        
        # Notify the user their account was approved
        create_notification(
            user_id=user_id,
            message="Your account has been approved! You can now login.",
            notification_type="SystemAlert"
        )
        
        flash('User approved successfully', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error approving user: {str(e)}', 'danger')
    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()
    return redirect(url_for('approve_users'))

@app.route('/admin/users/<int:user_id>')
@login_required
@role_required('Admin')
def view_user(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get user details
        cur.execute("""
            SELECT user_id, username, role, email, full_name, is_active, 
                   created_at, updated_at
            FROM users 
            WHERE user_id = %s
        """, (user_id,))
        user = cur.fetchone()
        print(f"DEBUG: Found user: {user}")
        if not user:
            flash('User not found', 'danger')
            return redirect(url_for('users'))
            
        return render_template('user_details.html', user=user)
        
    except Exception as e:
        flash(f'Error loading user: {str(e)}', 'danger')
        return redirect(url_for('users'))
    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()

@app.route('/debug-routes')
def debug_routes():
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            'route': str(rule),
            'methods': ', '.join(rule.methods),
            'endpoint': rule.endpoint
        })
    return jsonify(routes)
if __name__ == '__main__':
    app.run(debug=True)