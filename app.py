import streamlit as st
import sqlite3
import json
import io
import os
import pandas as pd
from datetime import datetime, timedelta
import qrcode
from PIL import Image
from fpdf import FPDF

# -------------------------------------------------------------
# Configuration
# -------------------------------------------------------------
st.set_page_config(
    page_title="College Canteen",
    page_icon="🍽️️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

ADMIN_USER = "admin"
ADMIN_PASS = "admin123"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "restaurant.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# -------------------------------------------------------------
# Database Setup & Helpers
# -------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def init_db():
    conn = get_db()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS menu (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                price REAL NOT NULL,
                description TEXT,
                image_url TEXT,
                is_available INTEGER DEFAULT 1
            )
        """)

        c = conn.cursor()
        c.execute("PRAGMA table_info(menu)")
        cols = [col[1] for col in c.fetchall()]
        if "image_url" not in cols:
            conn.execute("ALTER TABLE menu ADD COLUMN image_url TEXT")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                table_no TEXT NOT NULL,
                items_json TEXT NOT NULL,
                total_amount REAL NOT NULL,
                status TEXT DEFAULT 'Pending',
                created_at TEXT NOT NULL
            )
        """)

        c.execute("SELECT COUNT(*) FROM menu")
        if c.fetchone()[0] == 0:
            sample_dishes = [
                ("Paneer Butter Masala", "Main Course", 260.0, "Cottage cheese cubes in rich tomato gravy.", "https://images.unsplash.com/photo-1631452180519-c014fe946bc7?w=500", 1),
                ("Veg Biryani", "Rice", 210.0, "Aromatic basmati rice cooked with garden spices.", "https://images.unsplash.com/photo-1563379091339-03b21ab4a4f8?w=500", 1),
                ("Butter Naan", "Breads", 45.0, "Clay oven flatbread glazed with fresh butter.", "https://images.unsplash.com/photo-1626074353765-517a681e40be?w=500", 1),
                ("Crispy Corn Chilli", "Starters", 180.0, "Fried sweet corn tossed with capsicum and spices.", "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=500", 1),
                ("Mango Lassi", "Beverages", 90.0, "Refreshing thick yogurt shake with mango pulp.", "https://images.unsplash.com/photo-1546173159-315724a31696?w=500", 1),
                ("Cold Coffee", "Beverages", 110.0, "Creamy blended chilled brew topped with cocoa.", "https://images.unsplash.com/photo-1517701550927-30cf4ba1dba5?w=500", 1),
            ]
            conn.executemany("INSERT INTO menu (name, category, price, description, image_url, is_available) VALUES (?, ?, ?, ?, ?, ?)", sample_dishes)
    conn.close()

init_db()

# -------------------------------------------------------------
# Thermal 80mm PDF Bill Generator
# -------------------------------------------------------------
def generate_thermal_receipt(order_id, table_no, items, total, date_str):
    pdf = FPDF(unit="mm", format=(72, 160))
    pdf.set_margins(3, 4, 3)
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=4)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 5, "College Canteen", ln=True, align="C")
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 4, f"Table: {table_no} | Order #{order_id}", ln=True, align="C")
    pdf.cell(0, 4, f"{date_str}", ln=True, align="C")
    pdf.cell(0, 3, "--------------------------------------------", ln=True, align="C")

    pdf.set_font("Helvetica", "B", 7)
    pdf.cell(32, 4, "Item", 0, 0, "L")
    pdf.cell(10, 4, "Qty", 0, 0, "C")
    pdf.cell(12, 4, "Rate", 0, 0, "R")
    pdf.cell(12, 4, "Total", 0, 1, "R")
    pdf.cell(0, 2, "--------------------------------------------", ln=True, align="C")

    pdf.set_font("Helvetica", "", 7)
    for it in items:
        name = it["name"][:18]
        qty = str(it["qty"])
        rate = f"{it['price']:.2f}"
        sub = f"{(it['qty'] * it['price']):.2f}"
        pdf.cell(32, 4, name, 0, 0, "L")
        pdf.cell(10, 4, qty, 0, 0, "C")
        pdf.cell(12, 4, rate, 0, 0, "R")
        pdf.cell(12, 4, sub, 0, 1, "R")

    tax = round(total * 0.05, 2)
    pdf.cell(0, 3, "--------------------------------------------", ln=True, align="C")
    pdf.cell(45, 4, "Sub Total:", 0, 0, "R")
    pdf.cell(21, 4, f"INR {total:.2f}", 0, 1, "R")
    pdf.cell(45, 4, "GST (5%):", 0, 0, "R")
    pdf.cell(21, 4, f"INR {tax:.2f}", 0, 1, "R")
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(45, 5, "Grand Total:", 0, 0, "R")
    pdf.cell(21, 5, f"INR {total+tax:.2f}", 0, 1, "R")

    return bytes(pdf.output())

# -------------------------------------------------------------
# Session States
# -------------------------------------------------------------
if "cart" not in st.session_state:
    st.session_state.cart = {}

if "admin_logged_in" not in st.session_state:
    st.session_state.admin_logged_in = False

# -------------------------------------------------------------
# Route & Mode Detection
# -------------------------------------------------------------
query_params = st.query_params
mode = query_params.get("mode", "").lower()
table_number = query_params.get("table", "T1")

# =============================================================
# 1. CUSTOMER ORDERING INTERFACE
# =============================================================
if mode != "admin":
    # Complete abstraction: hide sidebars, main menu, and footers from customers
    st.markdown("""
    <style>
        [data-testid="collapsedControl"] { display: none !important; }
        section[data-testid="stSidebar"] { display: none !important; }
        #MainMenu { visibility: hidden; }
        header { visibility: hidden; }
        footer { visibility: hidden; }
    </style>
    """, unsafe_allow_html=True)

    st.title("🍽️ Place Your Order")
    st.caption(f"Currently ordering for **Table: {table_number}**")

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name, category, price, description, image_url FROM menu WHERE is_available = 1 ORDER BY id ASC")
    menu_items = c.fetchall()
    conn.close()

    if not menu_items:
        st.info("The menu is currently being updated. Please check back shortly!")
    else:
        categories = ["All"] + sorted(list(set(row[2] for row in menu_items)))
        selected_cat = st.pills("Select Category", categories, default="All")

        filtered_items = [it for it in menu_items if selected_cat == "All" or it[2] == selected_cat]

        # 2-Column Menu Grid with Photos
        cols = st.columns(2, gap="medium")
        for idx, (item_id, name, cat, price, desc, img_url) in enumerate(filtered_items):
            with cols[idx % 2]:
                with st.container(border=True):
                    if img_url:
                        st.image(img_url, use_container_width=True)
                    else:
                        st.image("https://images.unsplash.com/photo-1495195129352-aeb325a55b65?w=500", use_container_width=True)

                    st.subheader(name)
                    st.caption(desc if desc else "Freshly prepared")
                    st.write(f"### ₹{price:.2f}")

                    current_qty = st.session_state.cart.get(item_id, 0)
                    btn_cols = st.columns([1, 1, 2])
                    with btn_cols[0]:
                        if st.button("➖", key=f"minus_{item_id}", use_container_width=True):
                            if current_qty > 0:
                                st.session_state.cart[item_id] -= 1
                                if st.session_state.cart[item_id] == 0:
                                    del st.session_state.cart[item_id]
                                st.rerun()
                    with btn_cols[1]:
                        if st.button("➕", key=f"plus_{item_id}", use_container_width=True):
                            st.session_state.cart[item_id] = current_qty + 1
                            st.rerun()
                    with btn_cols[2]:
                        st.write(f"Qty: **{current_qty}**")

        st.divider()

        # Cart Summary & Submission
        st.subheader("🛒 Current Cart")
        if not st.session_state.cart:
            st.write("Your cart is empty. Pick dishes using the buttons above.")
        else:
            total_bill = 0.0
            order_summary = []

            for (m_id, m_name, _, m_price, _, _) in menu_items:
                if m_id in st.session_state.cart:
                    qty = st.session_state.cart[m_id]
                    cost = qty * m_price
                    total_bill += cost
                    order_summary.append({
                        "id": m_id,
                        "name": m_name,
                        "qty": qty,
                        "price": m_price,
                        "subtotal": cost
                    })

            for line in order_summary:
                c1, c2, c3 = st.columns([4, 2, 2])
                c1.write(f"• **{line['name']}** (₹{line['price']:.2f})")
                c2.write(f"x {line['qty']}")
                c3.write(f"₹{line['subtotal']:.2f}")

            st.markdown(f"### Total Amount: **₹{total_bill:.2f}**")

            place_col, clear_col = st.columns([3, 1])
            with place_col:
                if st.button("🚀 Confirm & Send Order to Kitchen", type="primary", use_container_width=True):
                    conn = get_db()
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    items_json = json.dumps(order_summary)

                    with conn:
                        conn.execute("""
                            INSERT INTO orders (table_no, items_json, total_amount, status, created_at)
                            VALUES (?, ?, ?, 'Pending', ?)
                        """, (table_number, items_json, total_bill, now))
                    conn.close()

                    st.session_state.cart = {}
                    st.success(f"Order sent to the kitchen for Table {table_number}!")
                    st.balloons()

            with clear_col:
                if st.button("Clear Cart", use_container_width=True):
                    st.session_state.cart = {}
                    st.rerun()

# =============================================================
# 2. ADMIN & KITCHEN DASHBOARD
# =============================================================
else:
    if not st.session_state.admin_logged_in:
        st.title("🔒 Admin Authentication")
        col1, _ = st.columns([1, 1])
        with col1:
            with st.form("admin_login_form"):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                if st.form_submit_button("Log In", type="primary", use_container_width=True):
                    if u == ADMIN_USER and p == ADMIN_PASS:
                        st.session_state.admin_logged_in = True
                        st.rerun()
                    else:
                        st.error("Invalid username or password. Please try again.")
    else:
        st.sidebar.title("Admin Navigation")
        st.sidebar.success(f"Logged in as {ADMIN_USER}")
        if st.sidebar.button("Log Out", use_container_width=True):
            st.session_state.admin_logged_in = False
            st.rerun()

        st.title("⚙️ Restaurant Control & Management")
        tab_orders, tab_sales, tab_menu, tab_qr = st.tabs([
            "📋 Live Kitchen Orders (Auto-Sync)",
            "📊 Sales & Reports",
            "🍴 Menu Editor",
            "🖨️ Table QR Generator"
        ])

        # -----------------------------------------------------
        # Tab 1: Live Kitchen Orders (Auto-Refreshes every 3s)
        # -----------------------------------------------------
        with tab_orders:
            @st.fragment(run_every="3s")
            def render_live_kitchen_orders():
                h1, h2, h3 = st.columns([3, 1, 1])
                h1.subheader("Live Kitchen Tickets")
                h2.caption(f"🟢 Sync: {datetime.now().strftime('%H:%M:%S')}")
                with h3:
                    if st.button("🔄 Refresh", use_container_width=True):
                        st.rerun(scope="fragment")

                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT id, table_no, items_json, total_amount, status, created_at FROM orders ORDER BY id DESC")
                orders = c.fetchall()
                conn.close()

                if not orders:
                    st.info("No incoming orders found.")
                else:
                    for order in orders:
                        ord_id, t_no, items_raw, total, status, created_at = order
                        items_list = json.loads(items_raw)

                        with st.expander(f"Order #{ord_id} — Table {t_no} | Status: {status} | Total: ₹{total:.2f}"):
                            ic1, ic2 = st.columns([3, 1])
                            with ic1:
                                st.write(f"**Ordered At:** {created_at}")
                                for itm in items_list:
                                    st.write(f"- {itm['name']} x {itm['qty']} (₹{itm['price']} each)")
                            with ic2:
                                st.write(f"**Status:** `{status}`")
                                if status == "Pending":
                                    if st.button("Mark as Served", key=f"serve_{ord_id}", use_container_width=True):
                                        conn = get_db()
                                        with conn:
                                            conn.execute("UPDATE orders SET status = 'Served' WHERE id = ?", (ord_id,))
                                        conn.close()
                                        st.rerun(scope="fragment")

                                receipt_bytes = generate_thermal_receipt(ord_id, t_no, items_list, total, created_at)
                                st.download_button(
                                    label="🧾 Print 80mm Bill",
                                    data=receipt_bytes,
                                    file_name=f"receipt_order_{ord_id}_table_{t_no}.pdf",
                                    mime="application/pdf",
                                    key=f"bill_{ord_id}",
                                    use_container_width=True
                                )

            render_live_kitchen_orders()

        # -----------------------------------------------------
        # Tab 2: Sales Analytics & Daily/Monthly Breakdown
        # -----------------------------------------------------
        with tab_sales:
            st.subheader("Financial Analytics & Reports")
            conn = get_db()
            df_orders = pd.read_sql_query("SELECT id, table_no, items_json, total_amount, status, created_at FROM orders", conn)
            
            today_str = datetime.now().strftime("%Y-%m-%d")
            yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            month_str = datetime.now().strftime("%Y-%m")

            cur = conn.cursor()
            cur.execute("SELECT COUNT(*), COALESCE(SUM(total_amount), 0) FROM orders WHERE created_at LIKE ?", (f"{today_str}%",))
            today_orders, today_rev = cur.fetchone()

            cur.execute("SELECT COUNT(*), COALESCE(SUM(total_amount), 0) FROM orders WHERE created_at LIKE ?", (f"{yesterday_str}%",))
            yesterday_orders, yesterday_rev = cur.fetchone()

            cur.execute("SELECT COUNT(*), COALESCE(SUM(total_amount), 0) FROM orders WHERE created_at LIKE ?", (f"{month_str}%",))
            month_orders, month_rev = cur.fetchone()

            cur.execute("SELECT COUNT(*), COALESCE(SUM(total_amount), 0) FROM orders")
            total_orders, total_rev = cur.fetchone()
            conn.close()

            # KPI Highlights
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Today's Sales", f"₹{today_rev:,.2f}", f"{today_orders} orders")
            k2.metric("Yesterday", f"₹{yesterday_rev:,.2f}", f"{yesterday_orders} orders")
            k3.metric("This Month", f"₹{month_rev:,.2f}", f"{month_orders} orders")
            k4.metric("Lifetime Sales", f"₹{total_rev:,.2f}", f"{total_orders} orders")

            st.divider()

            if df_orders.empty:
                st.info("No sales data recorded yet.")
            else:
                df_orders["created_at"] = pd.to_datetime(df_orders["created_at"])
                df_orders["date"] = df_orders["created_at"].dt.date
                df_orders["month"] = df_orders["created_at"].dt.strftime("%Y-%m")

                view_option = st.radio("Group Breakdown", ["Daily Sales", "Monthly Sales", "Top Selling Dishes"], horizontal=True)

                if view_option == "Daily Sales":
                    daily_summary = df_orders.groupby("date").agg(Orders=("id", "count"), Revenue=("total_amount", "sum")).reset_index()
                    st.dataframe(
                        daily_summary,
                        column_config={"Revenue": st.column_config.ProgressColumn("Revenue (₹)", format="₹%.2f", min_value=0, max_value=float(daily_summary["Revenue"].max() or 1000))},
                        use_container_width=True
                    )

                elif view_option == "Monthly Sales":
                    monthly_summary = df_orders.groupby("month").agg(Orders=("id", "count"), Revenue=("total_amount", "sum")).reset_index()
                    st.dataframe(
                        monthly_summary,
                        column_config={"Revenue": st.column_config.ProgressColumn("Revenue (₹)", format="₹%.2f", min_value=0, max_value=float(monthly_summary["Revenue"].max() or 1000))},
                        use_container_width=True
                    )

                elif view_option == "Top Selling Dishes":
                    item_counts = {}
                    for raw in df_orders["items_json"]:
                        for it in json.loads(raw):
                            item_counts[it["name"]] = item_counts.get(it["name"], 0) + it["qty"]
                    df_dishes = pd.DataFrame(list(item_counts.items()), columns=["Dish", "Quantity Sold"]).sort_values(by="Quantity Sold", ascending=False)
                    st.dataframe(
                        df_dishes,
                        column_config={"Quantity Sold": st.column_config.ProgressColumn("Quantity Sold", min_value=0, max_value=int(df_dishes["Quantity Sold"].max() or 10))},
                        use_container_width=True
                    )

                st.divider()
                csv_data = df_orders.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Download Complete Sales Report (CSV)", data=csv_data, file_name=f"sales_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv")

        # -----------------------------------------------------
        # Tab 3: Menu Management
        # -----------------------------------------------------
        with tab_menu:
            st.subheader("Manage Menu Items")
            with st.expander("➕ Add New Dish"):
                with st.form("new_dish_form", clear_on_submit=True):
                    col_a, col_b = st.columns(2)
                    dish_name = col_a.text_input("Item Name")
                    dish_cat = col_b.selectbox("Category", ["Starters", "Main Course", "Breads", "Rice", "Beverages", "Dessert"])
                    dish_price = col_a.number_input("Price (INR)", min_value=0.0, step=10.0, format="%.2f")
                    dish_desc = col_b.text_area("Description", "Freshly prepared")
                    image_url_input = col_a.text_input("Image Web URL (Optional)")
                    uploaded_file = col_b.file_uploader("Or Upload Food Photo", type=["png", "jpg", "jpeg", "webp"])

                    if st.form_submit_button("Save Item to Menu") and dish_name:
                        final_img_path = image_url_input.strip() if image_url_input else ""
                        if uploaded_file is not None:
                            unique_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uploaded_file.name}"
                            save_path = os.path.join(UPLOAD_DIR, unique_filename)
                            with open(save_path, "wb") as f:
                                f.write(uploaded_file.getbuffer())
                            final_img_path = save_path

                        conn = get_db()
                        with conn:
                            conn.execute("INSERT INTO menu (name, category, price, description, image_url, is_available) VALUES (?, ?, ?, ?, ?, 1)",
                                         (dish_name, dish_cat, dish_price, dish_desc, final_img_path))
                        conn.close()
                        st.success(f"Added '{dish_name}' successfully!")
                        st.rerun()

            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT id, name, category, price, description, image_url, is_available FROM menu ORDER BY id DESC")
            all_dishes = c.fetchall()
            conn.close()

            for d_id, d_name, d_cat, d_price, d_desc, d_img, is_avail in all_dishes:
                d_col0, d_col1, d_col2, d_col3, d_col4 = st.columns([1.5, 3, 1.5, 1.5, 1.5])
                with d_col0:
                    if d_img:
                        st.image(d_img, width=80)
                    else:
                        st.caption("No image")
                with d_col1:
                    st.write(f"**{d_name}** ({d_cat})\n{d_desc}")
                with d_col2:
                    st.write(f"₹{d_price:.2f}")
                with d_col3:
                    avail = bool(is_avail)
                    new_status = st.toggle("In Stock", value=avail, key=f"avail_{d_id}")
                    if new_status != avail:
                        conn = get_db()
                        with conn:
                            conn.execute("UPDATE menu SET is_available = ? WHERE id = ?", (1 if new_status else 0, d_id))
                        conn.close()
                        st.rerun()
                with d_col4:
                    if st.button("🗑️ Delete", key=f"del_{d_id}"):
                        conn = get_db()
                        with conn:
                            conn.execute("DELETE FROM menu WHERE id = ?", (d_id,))
                        conn.close()
                        st.rerun()
                st.divider()

        # -----------------------------------------------------
        # Tab 4: QR Code Generator
        # -----------------------------------------------------
        with tab_qr:
            st.subheader("Generate Printable Table QR Code")
            qr_col1, qr_col2 = st.columns([1, 1])
            with qr_col1:
                base_url = st.text_input("Application Base URL", value="http://localhost:8501")
                target_table = st.text_input("Table Identifier", value="T1")

                final_qr_url = f"{base_url.rstrip('/')}/?table={target_table.strip()}"
                st.code(final_qr_url, language="text")

                qr = qrcode.QRCode(version=1, box_size=10, border=4)
                qr.add_data(final_qr_url)
                qr.make(fit=True)
                img = qr.make_image(fill_color="#000000", back_color="#FFFFFF")

                buf = io.BytesIO()
                img.save(buf, format="PNG")
                qr_bytes = buf.getvalue()

                st.download_button(f"💾 Download QR for {target_table}", data=qr_bytes, file_name=f"qr_{target_table}.png", mime="image/png")

            with qr_col2:
                st.image(qr_bytes, caption=f"QR Code for {target_table}", width=240)