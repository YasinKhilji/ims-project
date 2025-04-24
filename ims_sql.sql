-- 1. Cleanup existing objects
DROP TABLE IF EXISTS audit_log, transactions, orders, products, users, suppliers CASCADE;
DROP SEQUENCE IF EXISTS transactions_id_seq, orders_id_seq, audit_log_id_seq;
DROP EXTENSION IF EXISTS pgcrypto CASCADE;

-- 2. Enable extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 3. Create tables (corrected order to respect foreign key dependencies)
CREATE TABLE suppliers (
    supplier_id SERIAL PRIMARY KEY,
    supplier_name VARCHAR(100) NOT NULL,
    contact_info VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE users (
    user_id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    role VARCHAR(30) NOT NULL DEFAULT 'Employee' CHECK (role IN ('Admin', 'InventoryManager', 'Sales', 'Warehouse')),
    email VARCHAR(100) UNIQUE NOT NULL,
    full_name VARCHAR(100) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    product_name VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    price DECIMAL(10,2) NOT NULL CHECK (price >= 0),
    quantity INTEGER NOT NULL CHECK (quantity >= 0),
    supplier_id INTEGER REFERENCES suppliers(supplier_id),
    min_stocks INTEGER CHECK (min_stocks >= 0) DEFAULT 5,
    added_by INTEGER REFERENCES users(user_id),
    is_deleted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_product_name UNIQUE (product_name)
);

CREATE TABLE orders (
    order_id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(product_id),
    quantity_ordered INTEGER NOT NULL CHECK (quantity_ordered > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending', 'Approved', 'Cancelled', 'Fulfilled')),
    added_by INTEGER REFERENCES users(user_id),
    total_amount DECIMAL(10,2),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE transactions (
    transaction_id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(product_id),
    transaction_type VARCHAR(20) NOT NULL CHECK (transaction_type IN ('Sale', 'Purchase', 'Return', 'Adjustment')),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price DECIMAL(10,2),
    total_amount DECIMAL(10,2),
    performed_by INTEGER REFERENCES users(user_id),
    transaction_date DATE DEFAULT CURRENT_DATE,
    reference_id INTEGER,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE audit_log (
    log_id SERIAL PRIMARY KEY,
    table_name VARCHAR(50) NOT NULL,
    record_id INTEGER,
    action VARCHAR(10) NOT NULL CHECK (action IN ('INSERT', 'UPDATE', 'DELETE', 'ERROR', 'LOGIN', 'LOGOUT')),
    changed_by INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    old_values JSONB,
    new_values JSONB,
    error_message TEXT,
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. Timestamp function
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 5. Apply timestamp triggers
CREATE TRIGGER update_suppliers_timestamp BEFORE UPDATE ON suppliers FOR EACH ROW EXECUTE FUNCTION update_timestamp();
CREATE TRIGGER update_users_timestamp BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION update_timestamp();
CREATE TRIGGER update_products_timestamp BEFORE UPDATE ON products FOR EACH ROW EXECUTE FUNCTION update_timestamp();
CREATE TRIGGER update_orders_timestamp BEFORE UPDATE ON orders FOR EACH ROW EXECUTE FUNCTION update_timestamp();

-- 6. Stock management trigger
CREATE OR REPLACE PROCEDURE update_stock(
    p_product_id INTEGER,
    p_quantity_change INTEGER,
    p_transaction_type VARCHAR(20),
    p_performed_by INTEGER,
    p_notes TEXT DEFAULT NULL,
    INOUT p_transaction_id INTEGER DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_unit_price DECIMAL(10,2);
    v_current_stock INTEGER;
BEGIN
    -- Validate quantity is positive
    IF p_quantity_change <= 0 THEN
        RAISE EXCEPTION 'Quantity must be positive';
    END IF;
    
    -- Validate product exists
    IF NOT EXISTS (SELECT 1 FROM products WHERE product_id = p_product_id AND is_deleted = FALSE) THEN
        RAISE EXCEPTION 'Product not found or deleted';
    END IF;
    
    -- Validate transaction type
    IF p_transaction_type NOT IN ('Purchase', 'Sale', 'Return', 'Adjustment') THEN
        RAISE EXCEPTION 'Invalid transaction type: %', p_transaction_type;
    END IF;
    
    -- For sales, check stock availability
    IF p_transaction_type = 'Sale' THEN
        SELECT quantity INTO v_current_stock FROM products WHERE product_id = p_product_id;
        IF v_current_stock < p_quantity_change THEN
            RAISE EXCEPTION 'Insufficient stock. Available: %, Requested: %', v_current_stock, p_quantity_change;
        END IF;
    END IF;
    
    -- Get current price
    SELECT price INTO v_unit_price FROM products WHERE product_id = p_product_id;
    
    -- Create transaction (the trigger will handle stock update)
    INSERT INTO transactions(
        product_id, transaction_type, quantity,
        unit_price, total_amount, performed_by, notes
    ) VALUES (
        p_product_id, p_transaction_type, p_quantity_change,
        v_unit_price, v_unit_price * p_quantity_change, p_performed_by, p_notes
    ) RETURNING transaction_id INTO p_transaction_id;
    
EXCEPTION
    WHEN OTHERS THEN
        PERFORM log_audit_event(
            'transactions', 'ERROR', NULL, p_performed_by,
            NULL, NULL,
            SQLERRM, NULL, NULL
        );
        RAISE;
END;
$$;
DROP TRIGGER IF EXISTS stock_update_trigger ON transactions;
CREATE TRIGGER stock_update_trigger AFTER INSERT ON transactions FOR EACH ROW EXECUTE FUNCTION update_stock();

CREATE OR REPLACE FUNCTION handle_transaction_stock_update()
RETURNS TRIGGER AS $$
BEGIN
    -- Update product quantity based on transaction type
    IF NEW.transaction_type = 'Sale' THEN
        UPDATE products 
        SET quantity = quantity - NEW.quantity,
            updated_at = CURRENT_TIMESTAMP
        WHERE product_id = NEW.product_id;
    ELSIF NEW.transaction_type IN ('Purchase', 'Return', 'Adjustment') THEN
        UPDATE products 
        SET quantity = quantity + NEW.quantity,
            updated_at = CURRENT_TIMESTAMP
        WHERE product_id = NEW.product_id;
    END IF;
    
    -- Log the stock update
    PERFORM log_audit_event(
        'products', 
        'UPDATE', 
        NEW.product_id, 
        NEW.performed_by,
        jsonb_build_object('quantity', 
            CASE WHEN NEW.transaction_type = 'Sale' 
                 THEN (SELECT quantity FROM products WHERE product_id = NEW.product_id) + NEW.quantity
                 ELSE (SELECT quantity FROM products WHERE product_id = NEW.product_id) - NEW.quantity
            END),
        jsonb_build_object('quantity', (SELECT quantity FROM products WHERE product_id = NEW.product_id)),
        NULL, NULL, NULL
    );
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER stock_update_trigger 
AFTER INSERT ON transactions 
FOR EACH ROW 
EXECUTE FUNCTION handle_transaction_stock_update();
-- 7. Corrected add_product procedure (parameters in proper order)
-- =============================================
-- AUDIT LOGGING
-- =============================================

CREATE OR REPLACE FUNCTION log_audit_event(
    p_table_name VARCHAR,
    p_action VARCHAR,
    p_record_id INTEGER DEFAULT NULL,
    p_changed_by INTEGER DEFAULT NULL,
    p_old_values JSONB DEFAULT NULL,
    p_new_values JSONB DEFAULT NULL,
    p_error_message TEXT DEFAULT NULL,
    p_ip_address VARCHAR DEFAULT NULL,
    p_user_agent TEXT DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    RAISE NOTICE 'Attempting to log: table=%, action=%, record_id=%, changed_by=%', p_table_name, p_action, p_record_id, p_changed_by;
    INSERT INTO audit_log (
        table_name, record_id, action, changed_by,
        old_values, new_values, error_message,
        ip_address, user_agent
    ) VALUES (
        p_table_name, p_record_id, p_action, p_changed_by,
        p_old_values, p_new_values, p_error_message,
        p_ip_address, p_user_agent
    );
EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'Failed to log audit event: %', SQLERRM;
    -- Re-raise to see the error
    RAISE;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE PROCEDURE add_product(
    p_product_name VARCHAR,
    p_category VARCHAR,
    p_price DECIMAL(10,2),
    p_quantity INTEGER,
    p_supplier_id INTEGER,
    p_added_by INTEGER,
    p_min_stocks INTEGER DEFAULT 5,
    INOUT p_product_id INTEGER DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
BEGIN
    -- Validate
    IF p_product_name IS NULL OR p_product_name = '' THEN
        RAISE EXCEPTION 'Product name cannot be empty';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM suppliers WHERE supplier_id = p_supplier_id) THEN
        RAISE EXCEPTION 'Invalid supplier ID';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM users WHERE user_id = p_added_by) THEN
        RAISE EXCEPTION 'Invalid user ID';
    END IF;
    
    -- Insert product
    INSERT INTO products(
        product_name, category, price, quantity, 
        supplier_id, min_stocks, added_by
    ) VALUES (
        p_product_name, p_category, p_price, p_quantity,
        p_supplier_id, p_min_stocks, p_added_by
    ) RETURNING product_id INTO p_product_id;
    
    -- Log the action
    INSERT INTO audit_log(table_name, record_id, action, changed_by, new_values)
    VALUES ('products', p_product_id, 'INSERT', p_added_by, 
           jsonb_build_object(
               'name', p_product_name,
               'price', p_price,
               'quantity', p_quantity
           ));
END;
$$;

CREATE OR REPLACE PROCEDURE update_product(
    p_product_id INTEGER,
    p_product_name VARCHAR,
    p_category VARCHAR,
    p_price DECIMAL(10,2),
    p_quantity INTEGER,
    p_supplier_id INTEGER,
    p_min_stocks INTEGER,
    p_updated_by INTEGER
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_old_values JSONB;
    v_new_values JSONB;
BEGIN
    -- Fetch current values
    SELECT jsonb_build_object(
        'product_name', product_name,
        'category', category,
        'price', price,
        'quantity', quantity,
        'supplier_id', supplier_id,
        'min_stocks', min_stocks
    )
    INTO v_old_values
    FROM products
    WHERE product_id = p_product_id AND is_deleted = FALSE;

    IF v_old_values IS NULL THEN
        RAISE EXCEPTION 'Product not found or deleted';
    END IF;

    -- Update the product
    UPDATE products
    SET product_name = COALESCE(p_product_name, product_name),
        category = COALESCE(p_category, category),
        price = COALESCE(p_price, price),
        quantity = COALESCE(p_quantity, quantity),
        supplier_id = COALESCE(p_supplier_id, supplier_id),
        min_stocks = COALESCE(p_min_stocks, min_stocks),
        updated_at = CURRENT_TIMESTAMP,
        added_by = CASE WHEN p_product_name IS NOT NULL OR p_category IS NOT NULL OR p_price IS NOT NULL 
                       OR p_quantity IS NOT NULL OR p_supplier_id IS NOT NULL OR p_min_stocks IS NOT NULL 
                       THEN p_updated_by ELSE added_by END
    WHERE product_id = p_product_id;

    -- Build new values
    SELECT jsonb_build_object(
        'product_name', COALESCE(p_product_name, (SELECT product_name FROM products WHERE product_id = p_product_id)),
        'category', COALESCE(p_category, (SELECT category FROM products WHERE product_id = p_product_id)),
        'price', COALESCE(p_price, (SELECT price FROM products WHERE product_id = p_product_id)),
        'quantity', COALESCE(p_quantity, (SELECT quantity FROM products WHERE product_id = p_product_id)),
        'supplier_id', COALESCE(p_supplier_id, (SELECT supplier_id FROM products WHERE product_id = p_product_id)),
        'min_stocks', COALESCE(p_min_stocks, (SELECT min_stocks FROM products WHERE product_id = p_product_id))
    )
    INTO v_new_values;

    -- Log the update
    PERFORM log_audit_event(
        'products', 'UPDATE', p_product_id, p_updated_by,
        v_old_values, v_new_values
    );

EXCEPTION
    WHEN OTHERS THEN
        PERFORM log_audit_event(
            'products', 'ERROR', p_product_id, p_updated_by,
            NULL, NULL,
            SQLERRM, NULL, NULL
        );
        RAISE;
END;
$$;

-- =============================================
-- CORE PROCEDURES (User Management)
-- =============================================

CREATE OR REPLACE PROCEDURE user_login(
    p_username VARCHAR,
    p_password VARCHAR,
    p_ip_address VARCHAR DEFAULT NULL,
    p_user_agent TEXT DEFAULT NULL,
    INOUT p_user_id INTEGER DEFAULT NULL,
    INOUT p_role VARCHAR DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
BEGIN
    -- Check credentials
    SELECT u.user_id, u.role INTO p_user_id, p_role
    FROM users u
    WHERE u.username = p_username 
    AND u.password = crypt(p_password, u.password)
    AND u.is_active = TRUE;
    
    -- Log the attempt
    IF p_user_id IS NULL THEN
        PERFORM log_audit_event(
            'users', 'LOGIN_FAIL', NULL, NULL,
            NULL, NULL,
            'Invalid credentials for ' || p_username,
            p_ip_address, p_user_agent
        );
    ELSE
        PERFORM log_audit_event(
            'users', 'LOGIN', p_user_id, p_user_id,
            NULL, NULL,
            NULL, p_ip_address, p_user_agent
        );
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        PERFORM log_audit_event(
            'users', 'ERROR', NULL, NULL,
            NULL, NULL,
            SQLERRM, p_ip_address, p_user_agent
        );
        RAISE;
END;
$$;

-- =============================================
-- INVENTORY PROCEDURES
-- =============================================

CREATE OR REPLACE PROCEDURE update_stock(
    p_product_id INTEGER,
    p_quantity_change INTEGER,
    p_transaction_type VARCHAR(20),
    p_performed_by INTEGER,
    p_notes TEXT DEFAULT NULL,
    INOUT p_transaction_id INTEGER DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_unit_price DECIMAL(10,2);
BEGIN
    -- Validate
    IF NOT EXISTS (SELECT 1 FROM products WHERE product_id = p_product_id AND is_deleted = FALSE) THEN
        RAISE EXCEPTION 'Product not found or deleted';
    END IF;
    
    IF p_transaction_type NOT IN ('Purchase', 'Return', 'Adjustment') THEN
        RAISE EXCEPTION 'Invalid transaction type for stock update';
    END IF;
    
    -- Get current price
    SELECT price INTO v_unit_price FROM products WHERE product_id = p_product_id;
    
    -- Create transaction
    INSERT INTO transactions(
        product_id, transaction_type, quantity,
        unit_price, total_amount, performed_by, notes
    ) VALUES (
        p_product_id, p_transaction_type, p_quantity_change,
        v_unit_price, v_unit_price * p_quantity_change, p_performed_by, p_notes
    ) RETURNING transaction_id INTO p_transaction_id;
END;
$$;

-- =============================================
-- ORDER MANAGEMENT
-- =============================================

CREATE OR REPLACE PROCEDURE create_order(
    p_product_id INTEGER,
    p_quantity INTEGER,
    p_added_by INTEGER,
    p_notes TEXT DEFAULT NULL,
    INOUT p_order_id INTEGER DEFAULT NULL,
    INOUT p_status VARCHAR DEFAULT 'Pending'
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_current_stock INTEGER;
    v_price DECIMAL(10,2);
    v_total DECIMAL(10,2);
BEGIN
    -- Explicitly set status if NULL
    IF p_status IS NULL THEN
        p_status := 'Pending';
    END IF;
    -- Validate product
    SELECT quantity, price INTO v_current_stock, v_price
    FROM products 
    WHERE product_id = p_product_id AND is_deleted = FALSE;
    
    IF v_price IS NULL THEN
        RAISE EXCEPTION 'Product not found';
    END IF;
    
    -- Check stock
    IF v_current_stock < p_quantity THEN
        RAISE EXCEPTION 'Insufficient stock (Available: %)', v_current_stock;
    END IF;
    
    -- Calculate total
    v_total := v_price * p_quantity;
    
    -- Create order
    INSERT INTO orders(
        product_id, quantity_ordered, added_by,
        total_amount, notes, status
    ) VALUES (
        p_product_id, p_quantity, p_added_by,
        v_total, p_notes, p_status
    ) RETURNING order_id, status INTO p_order_id, p_status;
    
    -- Log the audit event
    PERFORM log_audit_event(
        'orders', 'INSERT', p_order_id, p_added_by,
        NULL, jsonb_build_object(
            'product_id', p_product_id,
            'quantity_ordered', p_quantity,
            'status', p_status,
            'total_amount', v_total,
            'notes', p_notes
        ),
        NULL, NULL, NULL
    );
EXCEPTION
    WHEN OTHERS THEN
        PERFORM log_audit_event(
            'orders', 'ERROR', NULL, p_added_by,
            NULL, NULL,
            SQLERRM, NULL, NULL
        );
        RAISE;
END;
$$;

CREATE OR REPLACE PROCEDURE process_order(
    p_order_id INTEGER,
    p_status VARCHAR(20),
    p_processed_by INTEGER,
    p_notes TEXT DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_product_id INTEGER;
    v_quantity INTEGER;
    v_price DECIMAL(10,2);
    v_current_status VARCHAR(20);
    v_has_sale_transaction BOOLEAN;
BEGIN
    -- Get order details
    SELECT product_id, quantity_ordered, total_amount/quantity_ordered, status
    INTO v_product_id, v_quantity, v_price, v_current_status
    FROM orders 
    WHERE order_id = p_order_id;
    
    IF v_product_id IS NULL THEN
        RAISE EXCEPTION 'Order not found';
    END IF;
    
    -- Validate status transition
    IF p_status NOT IN ('Pending', 'Approved', 'Cancelled', 'Fulfilled') THEN
        RAISE EXCEPTION 'Invalid status: %', p_status;
    END IF;
    
    -- Check if a sale transaction exists
    SELECT EXISTS (
        SELECT 1 FROM transactions 
        WHERE reference_id = p_order_id 
        AND transaction_type = 'Sale'
    ) INTO v_has_sale_transaction;
    
    -- Log the update before changing
    PERFORM log_audit_event(
        'orders', 'UPDATE', p_order_id, p_processed_by,
        jsonb_build_object('status', v_current_status),
        jsonb_build_object('status', p_status, 'notes', p_notes)
    );
    
    -- Update order
    UPDATE orders
    SET status = p_status,
        updated_at = CURRENT_TIMESTAMP
    WHERE order_id = p_order_id;
    
    -- If approved or fulfilled, create sale transaction
    IF p_status IN ('Approved', 'Fulfilled') AND NOT v_has_sale_transaction THEN
        INSERT INTO transactions(
            product_id, transaction_type, quantity,
            unit_price, total_amount, performed_by,
            reference_id, notes
        ) VALUES (
            v_product_id, 'Sale', v_quantity,
            v_price, v_price * v_quantity, p_processed_by,
            p_order_id, p_notes
        );
        PERFORM log_audit_event(
            'transactions', 'INSERT', NULL, p_processed_by,
            NULL, jsonb_build_object(
                'product_id', v_product_id,
                'transaction_type', 'Sale',
                'quantity', v_quantity,
                'total_amount', v_price * v_quantity
            )
        );
    END IF;
    
    -- If cancelled and a sale transaction exists, create return transaction
    IF p_status = 'Cancelled' AND v_has_sale_transaction THEN
        INSERT INTO transactions(
            product_id, transaction_type, quantity,
            unit_price, total_amount, performed_by,
            reference_id, notes
        ) VALUES (
            v_product_id, 'Return', v_quantity,
            v_price, v_price * v_quantity, p_processed_by,
            p_order_id, COALESCE(p_notes, 'Stock restored due to order cancellation')
        );
        PERFORM log_audit_event(
            'transactions', 'INSERT', NULL, p_processed_by,
            NULL, jsonb_build_object(
                'product_id', v_product_id,
                'transaction_type', 'Return',
                'quantity', v_quantity,
                'total_amount', v_price * v_quantity
            )
        );
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        PERFORM log_audit_event(
            'orders', 'ERROR', p_order_id, p_processed_by,
            NULL, NULL,
            SQLERRM, NULL, NULL
        );
        RAISE;
END;
$$;

-- =============================================
-- REPORTING FUNCTIONS
-- =============================================
CREATE OR REPLACE FUNCTION get_sales_report(
    p_start_date DATE DEFAULT CURRENT_DATE - INTERVAL '30 days',
    p_end_date DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    product_id INTEGER,
    product_name VARCHAR,
    category VARCHAR,
    total_sales DECIMAL(10,2),
    total_quantity BIGINT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        p.product_id,
        p.product_name,
        p.category,
        COALESCE(SUM(t.total_amount), 0) AS total_sales,
        COALESCE(SUM(t.quantity), 0) AS total_quantity
    FROM products p
    LEFT JOIN transactions t ON p.product_id = t.product_id
        AND t.transaction_type = 'Sale'
        AND t.transaction_date BETWEEN p_start_date AND p_end_date
    WHERE p.is_deleted = FALSE
    GROUP BY p.product_id, p.product_name, p.category
    ORDER BY total_sales DESC;
END;
$$;

CREATE OR REPLACE FUNCTION get_low_stock(
    p_threshold INTEGER DEFAULT 0
)
RETURNS TABLE (
    product_id INTEGER,
    product_name VARCHAR,
    current_stock INTEGER,
    min_stocks INTEGER,
    supplier_name VARCHAR
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        p.product_id,
        p.product_name,
        p.quantity AS current_stock,
        p.min_stocks,
        s.supplier_name
    FROM products p
    JOIN suppliers s ON p.supplier_id = s.supplier_id
    WHERE p.quantity <= p.min_stocks + p_threshold
    AND p.is_deleted = FALSE
    ORDER BY (p.quantity - p.min_stocks) ASC;
END;
$$;

-- 9. Views
CREATE OR REPLACE VIEW vw_low_stock AS
SELECT p.product_id, p.product_name, p.quantity, p.min_stocks, s.supplier_name
FROM products p
JOIN suppliers s ON p.supplier_id = s.supplier_id
WHERE p.quantity < p.min_stocks AND p.is_deleted = FALSE;

CREATE OR REPLACE VIEW vw_sales_report AS
SELECT 
    p.product_id,
    p.product_name,
    p.category,
    COUNT(o.order_id) AS total_orders,
    SUM(o.quantity_ordered) AS total_quantity,
    SUM(o.total_amount) AS total_sales
FROM products p
LEFT JOIN orders o ON p.product_id = o.product_id AND o.status = 'Approved'
GROUP BY p.product_id, p.product_name, p.category;

-- 10. Security setup
CREATE ROLE ims_admin NOLOGIN;
CREATE ROLE ims_manager NOLOGIN;
CREATE ROLE ims_sales NOLOGIN;
CREATE ROLE ims_anon NOLOGIN;

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ims_admin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO ims_admin;

GRANT SELECT, INSERT, UPDATE ON products, suppliers, orders TO ims_manager;
GRANT SELECT ON users TO ims_manager;

GRANT SELECT ON products, suppliers TO ims_sales;
GRANT SELECT, INSERT, UPDATE ON orders TO ims_sales;

GRANT SELECT ON users TO ims_anon;

CREATE ROLE ims_web LOGIN PASSWORD 'securepassword123';
GRANT ims_anon TO ims_web;

-- Sample data to fix total_sales for product_id = 1

-- 1. RESET ENTIRE DATABASE (Dangerous in production!)
TRUNCATE TABLE audit_log, transactions, orders, products, users, suppliers RESTART IDENTITY CASCADE;

-- 2. INSERT FRESH TEST DATA
INSERT INTO suppliers (supplier_name, contact_info) VALUES
('Tech Suppliers Inc.', 'contact@techsuppliers.com'),
('Office World', 'sales@officeworld.com');

INSERT INTO users (username, password, role, email, full_name) VALUES
('admin', crypt('admin123', gen_salt('bf')), 'Admin', 'admin@ims.com', 'System Admin'),
('manager1', crypt('manager123', gen_salt('bf')), 'InventoryManager', 'manager@ims.com', 'Inventory Manager'),
('sales1', crypt('sales123', gen_salt('bf')), 'Sales', 'sales@ims.com', 'Sales Staff');

INSERT INTO products (product_name, category, price, quantity, supplier_id, added_by) VALUES
('Laptop Pro', 'Electronics', 999.99, 10, 1, 1),
('Wireless Mouse', 'AccessoriFes', 19.99, 50, 1, 2),
('Desk Chair', 'Furniture', 149.99, 15, 2, 2);

GRANT INSERT ON audit_log to postgres
Select * from audit_log


-- Create notifications table
CREATE TABLE notifications (
    notification_id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(user_id) NOT NULL,
    message TEXT NOT NULL,
    notification_type VARCHAR(50) NOT NULL 
        CHECK (notification_type IN ('OrderCreated', 'OrderApproved', 'LowStock', 'SystemAlert')),
    is_read BOOLEAN DEFAULT FALSE,
    related_entity_type VARCHAR(20),  -- 'order', 'product', etc
    related_entity_id INTEGER,        -- ID of the related entity
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX idx_notifications_user ON notifications(user_id);
CREATE INDEX idx_notifications_unread ON notifications(user_id) WHERE is_read = FALSE;
