import psycopg2
from psycopg2.extras import RealDictCursor

def get_db_connection():
    conn = psycopg2.connect(
        dbname="inventory_management",
        user="postgres",
        password="lab@123",
        host="localhost",
        port="5432"
    )
    return conn

def get_products():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM products WHERE is_deleted = FALSE")
    products = cur.fetchall()
    cur.close()
    conn.close()
    return products

def get_orders():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT o.*, p.product_name 
        FROM orders o
        JOIN products p ON o.product_id = p.product_id
    """)
    orders = cur.fetchall()
    cur.close()
    conn.close()
    return orders

def get_sales_report(start_date, end_date):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM get_sales_report(%s, %s)", (start_date, end_date))
    report = cur.fetchall()
    cur.close()
    conn.close()
    return report

def get_low_stock():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM get_low_stock()")
    low_stock = cur.fetchall()
    cur.close()
    conn.close()
    return low_stock

def add_product(product_name, category, price, quantity, supplier_id, added_by, min_stocks=5):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "CALL add_product(%s, %s, %s, %s, %s, %s, %s, NULL)",
            (product_name, category, price, quantity, supplier_id, added_by, min_stocks)
        )
        conn.commit()
    except psycopg2.Error as e:
        print(f"Error adding product: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

def create_order(product_id, quantity, added_by, notes=None):
    conn = get_db_connection()
    cur = conn.cursor()
    order_id = None
    status = None
    try:
        cur.execute("CALL create_order(%s, %s, %s, %s, %s, %s)", (product_id, quantity, added_by, notes, order_id, status))
        conn.commit()
        cur.execute("SELECT %s, %s", (order_id, status))
        order_id, status = cur.fetchone()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()
    return order_id, status

def process_order(order_id, status, processed_by, notes=None):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("CALL process_order(%s, %s, %s, %s)", (order_id, status, processed_by, notes))
    conn.commit()
    cur.close()
    conn.close()

def user_login(username, password, ip_address=None, user_agent=None):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT user_id, username, role 
        FROM users 
        WHERE username = %s AND password = crypt(%s, password) AND is_active = TRUE
    """, (username, password))
    user_data = cur.fetchone()
    cur.close()
    conn.close()
    return user_data  # Returns None if not found

def user_logout(user_id, ip_address=None, user_agent=None):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("CALL user_logout(%s, %s, %s)", (user_id, ip_address, user_agent))
    conn.commit()
    cur.close()
    conn.close()

def update_stock(product_id, quantity_change, transaction_type, performed_by, notes=None):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "CALL update_stock(%s, %s, %s, %s, %s, NULL)",
        (product_id, quantity_change, transaction_type, performed_by, notes)
    )
    conn.commit()
    cur.close()
    conn.close()

def get_suppliers():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM suppliers ORDER BY supplier_name")
    suppliers = cur.fetchall()
    cur.close()
    conn.close()
    return suppliers

def add_supplier_to_db(supplier_name, contact_info):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO suppliers (supplier_name, contact_info) VALUES (%s, %s)",
        (supplier_name, contact_info)
    )
    conn.commit()
    cur.close()
    conn.close()

def update_supplier(supplier_id, supplier_name, contact_info):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE suppliers SET supplier_name = %s, contact_info = %s WHERE supplier_id = %s",
            (supplier_name, contact_info, supplier_id)
        )
        conn.commit()
    except Exception as e:
        raise e  # Re-raise the exception to handle it in the route
    finally:
        cur.close()
        conn.close()

def delete_supplier(supplier_id):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        # First check if any products reference this supplier
        cur.execute("SELECT COUNT(*) FROM products WHERE supplier_id = %s", (supplier_id,))
        if cur.fetchone()[0] > 0:
            raise Exception("Cannot delete supplier - products are associated with it")
        
        cur.execute("DELETE FROM suppliers WHERE supplier_id = %s", (supplier_id,))
        conn.commit()
    except Exception as e:
        raise e
    finally:
        cur.close()
        conn.close()
# Add these new functions to database.py

def create_notification(user_id, message, notification_type, related_entity_type=None, related_entity_id=None):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO notifications 
            (user_id, message, notification_type, related_entity_type, related_entity_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING notification_id
        """, (user_id, message, notification_type, related_entity_type, related_entity_id))
        notification_id = cur.fetchone()[0]
        conn.commit()
        return notification_id
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()

def get_user_notifications(user_id, limit=5):
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT notification_id, message, is_read, created_at,
                   related_entity_type, related_entity_id
            FROM notifications
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (user_id, limit))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()

def get_unread_notification_count(user_id):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM notifications
            WHERE user_id = %s AND is_read = FALSE
        """, (user_id,))
        return cur.fetchone()[0]
    finally:
        cur.close()
        conn.close()

def mark_notification_as_read(notification_id, user_id):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE notifications
            SET is_read = TRUE
            WHERE notification_id = %s AND user_id = %s
            RETURNING related_entity_type, related_entity_id
        """, (notification_id, user_id))
        result = cur.fetchone()
        conn.commit()
        return result
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()