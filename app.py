import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify

# Initialize Flask app
app = Flask(__name__)

# Database setup
DB_PATH = os.path.join('data', 'pizzas.db')

# Create data directory if it doesn't exist
if not os.path.exists('data'):
    os.makedirs('data')

def get_db_connection():
    """Get a connection to the database"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create database tables if they don't exist"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Create Pizza table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS Pizza (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL
            )
        ''')
        
        # Create Order table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS "Order" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pizza_id INTEGER,
                quantity INTEGER NOT NULL,
                order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (pizza_id) REFERENCES Pizza (id)
            )
        ''')
        
        # Add customer_name column to Order table if it doesn't exist
        cursor.execute('PRAGMA table_info("Order")')
        columns = [column[1] for column in cursor.fetchall()]
        if 'customer_name' not in columns:
            cursor.execute('ALTER TABLE "Order" ADD COLUMN customer_name TEXT')
        
        # Add sample pizzas if table is empty
        cursor.execute('SELECT COUNT(*) FROM Pizza')
        if cursor.fetchone()[0] == 0:
            sample_pizzas = [
                ('Margherita', 14.99),
                ('Pepperoni', 1.99),
                ('Hawaiian', 99.99),
                ('Vegetarian', 12.99),
                ('Supreme', 14.99),
                ('BBQ Chicken', 13.99),
                ('Meat Lovers', 15.99),
                ('Buffalo', 16.99)
            ]
            cursor.executemany('INSERT INTO Pizza (name, price) VALUES (?, ?)', sample_pizzas)
            conn.commit()
    except Exception as e:
        print(f"Error initializing database: {e}")
        if 'conn' in locals():
            conn.rollback()
        raise
    finally:
        if 'conn' in locals():
            conn.close()

def get_all_pizzas():
    """Get all pizzas from the database"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT id, name, price FROM Pizza ORDER BY id')
        return cursor.fetchall()
    finally:
        conn.close()

def save_order(pizza_id, quantity, customer_name):
    """Save order to database and return order ID"""
    conn = get_db_connection()
    try:
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO "Order" (pizza_id, quantity, order_date, customer_name) VALUES (?, ?, ?, ?)',
            (pizza_id, quantity, current_time, customer_name)
        )
        order_id = cursor.lastrowid
        conn.commit()
        return order_id
    finally:
        conn.close()

def validate_promo_code(code):
    """Check if a promo code is valid and can be used"""
    if not code:
        return None, "No promo code provided"
        
    conn = get_db_connection()
    promo = conn.execute('''
        SELECT * FROM PromoCode 
        WHERE code = ? 
        AND is_active = 1
        AND (usage_limit IS NULL OR times_used < usage_limit)
    ''', (code.upper(),)).fetchone()
    conn.close()
    
    if not promo:
        return None, "Invalid or inactive promo code"
        
    return dict(promo), None

def apply_promo_code(order_id, promo_code_id, discount_percent):
    """Apply a promo code to an order and calculate discount"""
    conn = get_db_connection()
    try:
        # Get order total
        order = conn.execute('''
            SELECT o.quantity, p.price 
            FROM "Order" o
            JOIN Pizza p ON o.pizza_id = p.id
            WHERE o.id = ?
        ''', (order_id,)).fetchone()
        
        if not order:
            return False, "Order not found"
            
        total = order['quantity'] * order['price']
        discount_amount = (total * discount_percent) / 100
        
        # Update order with promo code and discount
        conn.execute('''
            UPDATE "Order" 
            SET promo_code_id = ?, 
                discount_amount = ?
            WHERE id = ?
        ''', (promo_code_id, discount_amount, order_id))
        
        # Increment promo code usage
        conn.execute('''
            UPDATE PromoCode 
            SET times_used = times_used + 1 
            WHERE id = ?
        ''', (promo_code_id,))
        
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def get_order_details(order_id):
    """Get order details from database"""
    conn = get_db_connection()
    try:
        order = conn.execute('''
            SELECT o.id, o.quantity, o.order_date, o.discount_amount,
                   p.id as pizza_id, p.name as pizza_name, p.price as pizza_price,
                   pc.id as promo_code_id, pc.code as promo_code, pc.discount_percent
            FROM "Order" o
            JOIN Pizza p ON o.pizza_id = p.id
            LEFT JOIN PromoCode pc ON o.promo_code_id = pc.id
            WHERE o.id = ?
        ''', (order_id,)).fetchone()
        return dict(order) if order else None
    finally:
        conn.close()

# Routes
@app.route('/')
def menu():
    """Show the pizza menu and order form"""
    pizzas = get_all_pizzas()
    return render_template('menu.html', pizzas=pizzas)

@app.route('/order', methods=['POST'])
def create_order():
    """Process the pizza order"""
    pizza_id = request.form.get('pizza_id')
    quantity = int(request.form.get('quantity', 1))
    customer_name = request.form.get('customer_name', '')
    promo_code = request.form.get('promo_code', '').strip().upper()
    
    if not all([pizza_id, quantity, customer_name]):
        return "Missing required fields", 400
    
    conn = get_db_connection()
    try:
        # Start transaction
        with conn:
            # Create the order
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO "Order" (pizza_id, quantity, customer_name)
                VALUES (?, ?, ?)
            ''', (pizza_id, quantity, customer_name))
            order_id = cursor.lastrowid
            
            # Apply promo code if provided
            if promo_code:
                promo, error = validate_promo_code(promo_code)
                if promo:
                    success, error = apply_promo_code(order_id, promo['id'], promo['discount_percent'])
                    if not success and error:
                        print(f"Failed to apply promo code: {error}")
                        # Continue without promo code
                
        return redirect(url_for('confirmation', order_id=order_id))
        
    except Exception as e:
        return f"Error creating order: {str(e)}", 500
    finally:
        conn.close()

@app.route('/confirmation/<int:order_id>')
def confirmation(order_id):
    """Show order confirmation"""
    order = get_order_details(order_id)
    if order is None:
        return "Order not found", 404
        
    # Calculate totals
    subtotal = order['pizza_price'] * order['quantity']
    total = subtotal - order.get('discount_amount', 0)
    
    return render_template('confirmation.html', 
                         order=order,
                         subtotal=subtotal,
                         total=total,
                         display_date=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=8000)
