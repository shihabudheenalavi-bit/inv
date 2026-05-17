
import streamlit as st
import pandas as pd
import plotly.express as px
import hashlib
import os
import shutil
from pathlib import Path

try:
    from streamlit_barcodescanner import barcode_scanner
except Exception:
    barcode_scanner = None

try:
    import cv2
    import numpy as np
except Exception:
    cv2 = None
    np = None

try:
    import zxingcpp
except Exception:
    zxingcpp = None
from datetime import datetime, date, timedelta
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime,
    ForeignKey, Text, Boolean, Date, func
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# ============================================================
# JUMAN PEARLS DENTAL CLINIC
# Inventory + Clinical Costing System for DOH-style costing prep
# Streamlit + SQLite
# ============================================================

Base = declarative_base()

# -------------------------
# DATABASE MODELS
# -------------------------

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="Viewer")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)


class Doctor(Base):
    __tablename__ = "doctors"
    id = Column(Integer, primary_key=True)
    doctor_name = Column(String, unique=True, nullable=False)
    department = Column(String, nullable=False)
    specialty = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)


class Item(Base):
    __tablename__ = "inventory_items"
    id = Column(Integer, primary_key=True)
    barcode = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    brand = Column(String, nullable=True)
    unit = Column(String, nullable=False)  # Consumption / stock tracking unit
    purchase_uom = Column(String, default="Same")
    consumption_uom = Column(String, default="Same")
    conversion_factor = Column(Float, default=1.0)  # 1 purchase UOM = X consumption UOM
    min_stock = Column(Float, default=0.0)
    current_qty = Column(Float, default=0.0)
    weighted_avg_cost = Column(Float, default=0.0)
    default_expense_account = Column(String, nullable=True)
    clinical_or_admin = Column(String, default="Clinical")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)




class SupplierBarcodeMapping(Base):
    __tablename__ = "supplier_barcode_mappings"
    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=False)
    supplier_name = Column(String, nullable=False)
    supplier_barcode = Column(String, unique=True, nullable=False)
    supplier_item_name = Column(String, nullable=True)
    pack_size = Column(Float, default=1.0)
    remarks = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    item = relationship("Item")


class PurchaseInvoice(Base):
    __tablename__ = "purchase_invoices"
    id = Column(Integer, primary_key=True)
    supplier_name = Column(String, nullable=False)
    invoice_no = Column(String, nullable=False)
    invoice_date = Column(Date, nullable=False)
    gross_amount = Column(Float, default=0.0)
    vat_amount = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    freight_amount = Column(Float, default=0.0)
    quickbooks_ref = Column(String, nullable=True)
    remarks = Column(Text, nullable=True)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.now)


class Batch(Base):
    __tablename__ = "item_batches"
    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("inventory_items.id"))
    purchase_invoice_id = Column(Integer, ForeignKey("purchase_invoices.id"), nullable=True)
    batch_no = Column(String, nullable=True)
    expiry_date = Column(Date, nullable=True)
    received_qty = Column(Float, default=0.0)
    remaining_qty = Column(Float, default=0.0)
    unit_cost = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.now)

    item = relationship("Item")
    invoice = relationship("PurchaseInvoice")


class StockTransaction(Base):
    __tablename__ = "stock_transactions"
    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("inventory_items.id"))
    batch_id = Column(Integer, ForeignKey("item_batches.id"), nullable=True)
    txn_type = Column(String, nullable=False)  # PURCHASE, CONSUMPTION, ADJUSTMENT, OPENING
    quantity = Column(Float, nullable=False)
    unit_cost = Column(Float, default=0.0)
    total_cost = Column(Float, default=0.0)

    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    patient_mrn = Column(String, nullable=True)
    procedure_code = Column(String, nullable=True)
    procedure_name = Column(String, nullable=True)
    payment_type = Column(String, nullable=True)  # Cash / Insurance / Corporate / N/A
    cost_center = Column(String, nullable=True)

    txn_date = Column(Date, default=date.today)
    user_name = Column(String, nullable=False)
    remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    item = relationship("Item")
    batch = relationship("Batch")
    doctor = relationship("Doctor")


class MonthlyClosing(Base):
    __tablename__ = "monthly_closings"
    id = Column(Integer, primary_key=True)
    period = Column(String, nullable=False)  # YYYY-MM
    item_id = Column(Integer, ForeignKey("inventory_items.id"))
    system_qty = Column(Float, default=0.0)
    physical_qty = Column(Float, default=0.0)
    adjustment_qty = Column(Float, default=0.0)
    closing_value = Column(Float, default=0.0)
    prepared_by = Column(String, nullable=False)
    approved_by = Column(String, nullable=True)
    locked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

    item = relationship("Item")


class Reconciliation(Base):
    __tablename__ = "reconciliations"
    id = Column(Integer, primary_key=True)
    period = Column(String, nullable=False)
    qb_purchase_total = Column(Float, default=0.0)
    system_purchase_total = Column(Float, default=0.0)
    qb_material_expense = Column(Float, default=0.0)
    system_consumption_cost = Column(Float, default=0.0)
    qb_inventory_balance = Column(Float, default=0.0)
    system_inventory_value = Column(Float, default=0.0)
    variance_purchase = Column(Float, default=0.0)
    variance_consumption = Column(Float, default=0.0)
    variance_inventory = Column(Float, default=0.0)
    prepared_by = Column(String, nullable=False)
    approved_by = Column(String, nullable=True)
    signoff_status = Column(String, default="Draft")
    remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    module = Column(String, nullable=False)
    action = Column(String, nullable=False)
    record_id = Column(String, nullable=True)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    user_name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.now)


class TemporaryConsumption(Base):
    __tablename__ = "temporary_consumptions"
    id = Column(Integer, primary_key=True)
    temp_item_name = Column(String, nullable=False)
    temp_barcode = Column(String, nullable=True)
    quantity = Column(Float, nullable=False)
    estimated_unit_cost = Column(Float, default=0.0)
    estimated_total_cost = Column(Float, default=0.0)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    patient_mrn = Column(String, nullable=True)
    procedure_code = Column(String, nullable=True)
    procedure_name = Column(String, nullable=True)
    cost_center = Column(String, nullable=True)
    txn_date = Column(Date, default=date.today)
    status = Column(String, default="Pending")  # Pending, Mapped, Rejected
    mapped_item_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=True)
    mapped_transaction_id = Column(Integer, ForeignKey("stock_transactions.id"), nullable=True)
    entered_by = Column(String, nullable=False)
    reviewed_by = Column(String, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    remarks = Column(Text, nullable=True)
    admin_remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    doctor = relationship("Doctor")
    mapped_item = relationship("Item")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    id = Column(Integer, primary_key=True)
    role = Column(String, nullable=False)
    module = Column(String, nullable=False)
    can_access = Column(Boolean, default=False)
    updated_by = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.now)


class BackupConfig(Base):
    __tablename__ = "backup_config"
    id = Column(Integer, primary_key=True)
    backup_folder = Column(String, default="backups")
    frequency = Column(String, default="Manual")  # Manual, Daily, Weekly
    enabled = Column(Boolean, default=False)
    last_backup_at = Column(DateTime, nullable=True)
    updated_by = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.now)


class BackupLog(Base):
    __tablename__ = "backup_logs"
    id = Column(Integer, primary_key=True)
    backup_file = Column(String, nullable=False)
    backup_type = Column(String, nullable=False)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.now)


# -------------------------
# DATABASE INIT
# -------------------------

engine = create_engine("sqlite:///jpdc_clinical_costing_inventory.db", connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)
DB_FILE = "jpdc_clinical_costing_inventory.db"


def ensure_schema_updates():
    """Adds newly introduced columns to existing SQLite databases without deleting data."""
    with engine.connect() as conn:
        existing_cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(inventory_items)").fetchall()]
        if "purchase_uom" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE inventory_items ADD COLUMN purchase_uom VARCHAR DEFAULT 'Same'")
        if "consumption_uom" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE inventory_items ADD COLUMN consumption_uom VARCHAR DEFAULT 'Same'")
        if "conversion_factor" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE inventory_items ADD COLUMN conversion_factor FLOAT DEFAULT 1.0")
        conn.commit()


ensure_schema_updates()

ALL_MODULES = [
    "Dashboard",
    "Inventory Master",
    "Supplier Barcode Mapping",
    "Doctor & Cost Centers",
    "Purchase Invoice / Stock Inward",
    "Consumption Entry",
    "Temporary Consumption",
    "Adjustments",
    "Monthly Closing",
    "Clinical Costing Reports",
    "QuickBooks Reconciliation",
    "Audit Log",
    "Admin Edit Center",
    "Backup",
    "Role Settings",
    "User Management"
]
DEFAULT_ROLES = ["Super Admin", "Inventory Manager", "Store Keeper", "Nurse", "Doctor", "Viewer"]


def get_db():
    return SessionLocal()


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hash_password(password) == password_hash


def log_audit(db, module, action, record_id, old_value, new_value, reason, user_name):
    log = AuditLog(
        module=module,
        action=action,
        record_id=str(record_id) if record_id else None,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        user_name=user_name
    )
    db.add(log)
    db.commit()


def seed_admin():
    db = get_db()
    if not db.query(User).filter(User.username == "admin").first():
        db.add(User(username="admin", password_hash=hash_password("123"), role="Super Admin"))
        db.commit()

    # Create default backup configuration
    if not db.query(BackupConfig).first():
        db.add(BackupConfig(backup_folder="backups", frequency="Manual", enabled=False, updated_by="system"))
        db.commit()

    # Seed practical module permissions for default roles. Super Admin can access all modules.
    default_permissions = {
        "Super Admin": ALL_MODULES,
        "Inventory Manager": [
            "Dashboard", "Inventory Master", "Supplier Barcode Mapping", "Doctor & Cost Centers", "Purchase Invoice / Stock Inward",
            "Consumption Entry", "Temporary Consumption", "Adjustments", "Monthly Closing",
            "Clinical Costing Reports", "QuickBooks Reconciliation", "Audit Log", "Backup"
        ],
        "Store Keeper": [
            "Dashboard", "Inventory Master", "Supplier Barcode Mapping", "Purchase Invoice / Stock Inward",
            "Consumption Entry", "Temporary Consumption", "Clinical Costing Reports", "Backup"
        ],
        "Nurse": ["Dashboard", "Consumption Entry", "Temporary Consumption"],
        "Doctor": ["Dashboard", "Consumption Entry", "Temporary Consumption", "Clinical Costing Reports"],
        "Viewer": ["Dashboard", "Clinical Costing Reports"]
    }
    for role, modules in default_permissions.items():
        for module in ALL_MODULES:
            existing = db.query(RolePermission).filter(RolePermission.role == role, RolePermission.module == module).first()
            if not existing:
                db.add(RolePermission(role=role, module=module, can_access=(module in modules), updated_by="system"))
    db.commit()
    db.close()


seed_admin()

# -------------------------
# STREAMLIT CONFIG
# -------------------------

st.set_page_config(
    page_title="JPDC Inventory & Clinical Costing",
    layout="wide",
    page_icon="🦷"
)

st.title("🦷 JPDC Inventory & Clinical Costing System")
st.caption("Inventory, material consumption, doctor-wise costing, monthly closing, and DOH-style reconciliation support")

# -------------------------
# UI THEME - MAROON / WHITE
# -------------------------
st.markdown("""
<style>
    .stApp { background: #fffaf8; }
    [data-testid="stSidebar"] { background: linear-gradient(180deg, #5b0f1b 0%, #7a1b2c 100%); }
    [data-testid="stSidebar"] * { color: #ffffff !important; }
    h1, h2, h3 { color: #5b0f1b !important; }
    div.stButton > button, div.stDownloadButton > button {
        background-color: #6f1424;
        color: white;
        border-radius: 10px;
        border: 1px solid #6f1424;
        font-weight: 600;
    }
    div.stButton > button:hover, div.stDownloadButton > button:hover {
        background-color: #8b1e34;
        color: white;
        border: 1px solid #8b1e34;
    }
    .metric-card {
        background: #ffffff;
        border: 1px solid #ead6d9;
        border-left: 8px solid #6f1424;
        border-radius: 16px;
        padding: 16px 18px;
        box-shadow: 0 4px 16px rgba(111, 20, 36, 0.08);
        min-height: 110px;
    }
    .metric-label {
        color: #6f1424;
        font-size: 14px;
        font-weight: 700;
        margin-bottom: 8px;
    }
    .metric-value {
        color: #2f1117;
        font-size: 25px;
        font-weight: 800;
    }
    .soft-box {
        background: #ffffff;
        border: 1px solid #ead6d9;
        border-radius: 14px;
        padding: 16px;
        box-shadow: 0 3px 12px rgba(111, 20, 36, 0.06);
    }
</style>
""", unsafe_allow_html=True)



# -------------------------
# AUTH
# -------------------------

if "auth" not in st.session_state:
    st.session_state.auth = False
if "user" not in st.session_state:
    st.session_state.user = None
if "role" not in st.session_state:
    st.session_state.role = None


def login_screen():
    st.subheader("Login")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")
        if submitted:
            db = get_db()
            user = db.query(User).filter(User.username == username, User.is_active == True).first()
            if user and verify_password(password, user.password_hash):
                st.session_state.auth = True
                st.session_state.user = user.username
                st.session_state.role = user.role
                db.close()
                st.rerun()
            else:
                db.close()
                st.error("Invalid username or password")


if not st.session_state.auth:
    login_screen()
    st.stop()


# -------------------------
# HELPERS
# -------------------------

def require_roles(allowed_roles):
    # Existing role checks are preserved, but admin module permissions can also allow access.
    if st.session_state.role == "Super Admin":
        return
    if st.session_state.role in allowed_roles:
        return
    try:
        if has_module_access(st.session_state.role, choice):
            return
    except Exception:
        pass
    st.warning("Access denied for your role.")
    st.stop()


def get_item_by_barcode(db, barcode):
    return db.query(Item).filter(Item.barcode == barcode, Item.is_active == True).first()


def get_item_by_any_barcode(db, barcode):
    """
    First checks the clinic internal barcode/SKU from Item Master.
    If not found, checks supplier barcode aliases and returns the mapped internal item.
    Returns: (item, barcode_source_text)
    """
    if not barcode:
        return None, "No barcode entered"

    item = db.query(Item).filter(Item.barcode == barcode, Item.is_active == True).first()
    if item:
        return item, "Internal Barcode"

    mapping = db.query(SupplierBarcodeMapping).filter(
        SupplierBarcodeMapping.supplier_barcode == barcode,
        SupplierBarcodeMapping.is_active == True
    ).first()

    if mapping and mapping.item and mapping.item.is_active:
        return mapping.item, f"Supplier Barcode mapped from {mapping.supplier_name}"

    return None, "Not Found"


def decode_barcode_or_qr_from_camera(camera_image):
    """Decode QR code/barcode from Streamlit camera image without changing app workflow."""
    if camera_image is None:
        return None, "No camera image captured."
    if cv2 is None or np is None:
        return None, "Camera decoding requires opencv-python-headless and numpy in requirements.txt."

    try:
        file_bytes = np.asarray(bytearray(camera_image.getvalue()), dtype=np.uint8)
        image = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
        if image is None:
            return None, "Could not read the camera image."

        # Try ZXing first. It reads common 1D barcodes and QR codes more reliably on mobile camera images.
        if zxingcpp is not None:
            candidate_images = [image]
            try:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                candidate_images.append(gray)
                candidate_images.append(cv2.resize(gray, None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC))
                candidate_images.append(cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1])
            except Exception:
                pass

            for candidate in candidate_images:
                try:
                    results = zxingcpp.read_barcodes(candidate)
                    for result in results:
                        value = getattr(result, "text", "")
                        fmt = getattr(result, "format", "Barcode/QR")
                        if value:
                            return str(value).strip(), str(fmt)
                except Exception:
                    continue

        # QR code fallback using OpenCV
        qr_detector = cv2.QRCodeDetector()
        qr_value, _, _ = qr_detector.detectAndDecode(image)
        if qr_value:
            return qr_value.strip(), "QR Code"

        # Barcode fallback if the installed OpenCV build supports it
        if hasattr(cv2, "barcode_BarcodeDetector"):
            barcode_detector = cv2.barcode_BarcodeDetector()
            ok, decoded_info, decoded_type, _ = barcode_detector.detectAndDecode(image)
            if ok and decoded_info:
                for value in decoded_info:
                    if value:
                        return str(value).strip(), "Barcode"

        return None, "No barcode/QR detected. Hold the code flat, fill the camera box, avoid glare, and try again."
    except Exception as e:
        return None, f"Camera scan failed: {e}"


def get_purchase_conversion_factor(db, barcode, item):
    """For stock inward: converts purchase quantity into stock/consumption quantity.
    If a supplier barcode mapping has pack_size, it is used first.
    Otherwise the item master conversion_factor is used.
    Example: 1 carton = 10 boxes, purchase qty 2 cartons => stock qty 20 boxes.
    """
    mapping = None
    if barcode:
        mapping = db.query(SupplierBarcodeMapping).filter(
            SupplierBarcodeMapping.supplier_barcode == barcode,
            SupplierBarcodeMapping.is_active == True
        ).first()
    if mapping and mapping.pack_size and mapping.pack_size > 0:
        return float(mapping.pack_size), f"Supplier pack size: 1 scanned purchase unit = {mapping.pack_size} {item.consumption_uom or item.unit}"
    factor = item.conversion_factor or 1.0
    return float(factor), f"Item master conversion: 1 {item.purchase_uom or 'purchase unit'} = {factor} {item.consumption_uom or item.unit}"


def recalc_weighted_average_cost(old_qty, old_avg_cost, added_qty, added_unit_cost):
    total_qty = (old_qty or 0) + (added_qty or 0)
    if total_qty <= 0:
        return 0.0
    old_value = (old_qty or 0) * (old_avg_cost or 0)
    added_value = (added_qty or 0) * (added_unit_cost or 0)
    return (old_value + added_value) / total_qty


def period_filter_expr(period):
    start = datetime.strptime(period + "-01", "%Y-%m-%d").date()
    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)
    return start, end


def metric_card(label, value):
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True
    )


def money(value):
    return f"AED {float(value or 0):,.2f}"


def has_module_access(role, module):
    if role == "Super Admin":
        return True
    db = get_db()
    perm = db.query(RolePermission).filter(RolePermission.role == role, RolePermission.module == module).first()
    allowed = bool(perm and perm.can_access)
    db.close()
    return allowed


def require_module_access(module_name):
    if not has_module_access(st.session_state.role, module_name):
        st.warning("Access denied for this module. Please contact admin.")
        st.stop()


def verify_admin_password(password):
    db = get_db()
    admin = db.query(User).filter(User.role == "Super Admin", User.is_active == True).first()
    ok = bool(admin and verify_password(password, admin.password_hash))
    db.close()
    return ok


def make_backup(backup_type="Manual", created_by="system"):
    db_path = Path(DB_FILE)
    if not db_path.exists():
        return False, "Database file not found. Run the app and save at least one record first.", None

    db = get_db()
    config = db.query(BackupConfig).first()
    backup_folder = Path(config.backup_folder if config else "backups")
    backup_folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_folder / f"jpdc_inventory_backup_{stamp}.db"
    shutil.copy2(db_path, backup_file)

    if config:
        config.last_backup_at = datetime.now()
    db.add(BackupLog(backup_file=str(backup_file), backup_type=backup_type, created_by=created_by))
    db.commit()
    db.close()
    return True, f"Backup created: {backup_file}", str(backup_file)


def run_scheduled_backup_if_due():
    db = get_db()
    config = db.query(BackupConfig).first()
    if not config or not config.enabled or config.frequency == "Manual":
        db.close()
        return
    now = datetime.now()
    due = False
    if not config.last_backup_at:
        due = True
    elif config.frequency == "Daily" and now - config.last_backup_at >= timedelta(days=1):
        due = True
    elif config.frequency == "Weekly" and now - config.last_backup_at >= timedelta(days=7):
        due = True
    db.close()
    if due:
        make_backup("Scheduled", "system")


run_scheduled_backup_if_due()


# -------------------------
# SIDEBAR
# -------------------------

menu = [m for m in ALL_MODULES if has_module_access(st.session_state.role, m)]
if not menu:
    st.error("No module access is assigned for your role. Please contact admin.")
    st.stop()

SETTINGS_MODULES = ["Role Settings", "User Management", "Admin Edit Center", "Backup", "Audit Log"]
main_menu = [m for m in menu if m not in SETTINGS_MODULES]
settings_menu = [m for m in SETTINGS_MODULES if m in menu]

st.sidebar.markdown("### Important Modules")
main_choice = st.sidebar.selectbox("Open module", main_menu if main_menu else menu)

choice = main_choice
if settings_menu:
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⚙️ Settings")
    settings_choice = st.sidebar.selectbox("Admin/settings area", ["-- Select settings --"] + settings_menu)
    if settings_choice != "-- Select settings --":
        choice = settings_choice

require_module_access(choice)
st.sidebar.markdown("---")
st.sidebar.write(f"Logged in: **{st.session_state.user}**")
st.sidebar.write(f"Role: **{st.session_state.role}**")
if st.sidebar.button("Logout"):
    st.session_state.auth = False
    st.session_state.user = None
    st.session_state.role = None
    st.rerun()


# -------------------------
# DASHBOARD
# -------------------------

if choice == "Dashboard":
    db = get_db()
    items = db.query(Item).filter(Item.is_active == True).all()

    total_value = sum((i.current_qty or 0) * (i.weighted_avg_cost or 0) for i in items)
    low_stock = sum(1 for i in items if (i.current_qty or 0) <= (i.min_stock or 0))
    today = date.today()
    expiry_soon = db.query(Batch).filter(
        Batch.expiry_date != None,
        Batch.expiry_date <= date(today.year, today.month, today.day)
    ).count()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Inventory Value", f"AED {total_value:,.2f}")
    c2.metric("Active Items", len(items))
    c3.metric("Low Stock Items", low_stock)
    c4.metric("Expired / Due Batches", expiry_soon)

    df_items = pd.read_sql(db.query(Item).statement, engine)
    if not df_items.empty:
        fig = px.bar(df_items, x="name", y="current_qty", color="category", title="Current Stock by Item")
        st.plotly_chart(fig, use_container_width=True)

    st.info("For DOH costing, focus on monthly consumption cost, department-wise allocation, reconciliation, and sign-off.")
    db.close()


# -------------------------
# INVENTORY MASTER
# -------------------------

elif choice == "Inventory Master":
    require_roles(["Super Admin", "Inventory Manager", "Store Keeper"])
    db = get_db()
    st.subheader("Inventory Item Master")

    with st.expander("Add New Item", expanded=False):
        with st.form("add_item_form"):
            col1, col2, col3 = st.columns(3)
            barcode = col1.text_input("Barcode / SKU *")
            name = col2.text_input("Item Name *")
            brand = col3.text_input("Brand")
            category = col1.selectbox("Category", ["Implants", "Ortho", "Consumables", "Surgical", "PPE", "Lab", "Medicine", "Other"])
            consumption_uom = col2.selectbox("Consumption / Stock UOM", ["Pcs", "Box", "Set", "Packet", "Bottle", "Tube", "Syringe", "Cartridge", "Carton", "Roll", "Pair"] )
            purchase_uom = col3.selectbox("Purchase UOM", ["Same", "Carton", "Box", "Packet", "Set", "Bottle", "Tube", "Pcs", "Roll", "Pair"] )
            conversion_factor = col1.number_input("Conversion: 1 Purchase UOM = how many Consumption UOM?", min_value=0.0001, value=1.0, help="Example: tissue 1 carton = 10 boxes, enter 10")
            min_stock = col2.number_input("Minimum Stock", min_value=0.0)
            default_expense_account = col3.text_input("QuickBooks Account")
            clinical_or_admin = col1.selectbox("Clinical/Admin", ["Clinical", "Admin", "Shared"])
            unit = consumption_uom
            submitted = st.form_submit_button("Save Item")

            if submitted:
                if not barcode or not name:
                    st.error("Barcode and item name are required.")
                elif db.query(Item).filter(Item.barcode == barcode).first():
                    st.error("Barcode already exists.")
                else:
                    item = Item(
                        barcode=barcode, name=name, brand=brand, category=category, unit=unit,
                        purchase_uom=purchase_uom, consumption_uom=consumption_uom, conversion_factor=conversion_factor,
                        min_stock=min_stock, default_expense_account=default_expense_account,
                        clinical_or_admin=clinical_or_admin
                    )
                    db.add(item)
                    db.commit()
                    log_audit(db, "Inventory Master", "CREATE", item.id, None, f"{name} - {barcode}", "New item", st.session_state.user)
                    st.success("Item saved.")

    df = pd.read_sql(db.query(Item).statement, engine)
    st.dataframe(df, use_container_width=True)
    db.close()


# -------------------------
# SUPPLIER BARCODE MAPPING
# -------------------------

elif choice == "Supplier Barcode Mapping":
    require_roles(["Super Admin", "Inventory Manager", "Store Keeper"])
    db = get_db()
    st.subheader("Supplier Barcode Mapping")
    st.info("Use this when the same item has different barcodes from different suppliers. Scan any supplier barcode and the system will use the one internal item from Item Master.")

    items = db.query(Item).filter(Item.is_active == True).order_by(Item.name.asc()).all()
    item_options = {f"{i.name} | Internal SKU: {i.barcode} | Unit: {i.unit}": i for i in items}

    with st.expander("Add Supplier Barcode Alias", expanded=True):
        with st.form("supplier_barcode_form"):
            if not items:
                st.warning("Please create item master first.")
            selected_item_label = st.selectbox("Map to Internal Item *", list(item_options.keys()) if item_options else ["No item available"])
            c1, c2, c3 = st.columns(3)
            supplier_name = c1.text_input("Supplier Name *")
            supplier_barcode = c2.text_input("Supplier Barcode *")
            pack_size = c3.number_input("Supplier Pack Size", min_value=0.0, value=1.0, help="For purchase scanning. Example: supplier carton barcode = 10 boxes, enter 10. For inner box barcode, keep 1.")
            supplier_item_name = st.text_input("Supplier Item Name / Description")
            remarks = st.text_area("Remarks")
            submitted = st.form_submit_button("Save Mapping")

            if submitted:
                if not items:
                    st.error("No item master found.")
                elif not supplier_name or not supplier_barcode:
                    st.error("Supplier name and supplier barcode are required.")
                elif db.query(Item).filter(Item.barcode == supplier_barcode).first():
                    st.error("This barcode is already used as an internal item barcode. Use a different supplier barcode.")
                elif db.query(SupplierBarcodeMapping).filter(SupplierBarcodeMapping.supplier_barcode == supplier_barcode).first():
                    st.error("This supplier barcode is already mapped.")
                else:
                    selected_item = item_options[selected_item_label]
                    mapping = SupplierBarcodeMapping(
                        item_id=selected_item.id,
                        supplier_name=supplier_name,
                        supplier_barcode=supplier_barcode,
                        supplier_item_name=supplier_item_name,
                        pack_size=pack_size,
                        remarks=remarks,
                        created_by=st.session_state.user
                    )
                    db.add(mapping)
                    db.commit()
                    log_audit(db, "Supplier Barcode Mapping", "CREATE", mapping.id, None, f"{supplier_barcode} -> {selected_item.name}", "Supplier barcode alias", st.session_state.user)
                    st.success(f"Mapping saved: supplier barcode {supplier_barcode} will use internal item {selected_item.name}.")

    st.markdown("### Existing Supplier Barcode Mappings")
    mappings = db.query(SupplierBarcodeMapping).all()
    rows = []
    for m in mappings:
        rows.append({
            "id": m.id,
            "supplier_name": m.supplier_name,
            "supplier_barcode": m.supplier_barcode,
            "internal_barcode": m.item.barcode if m.item else "",
            "internal_item": m.item.name if m.item else "",
            "supplier_item_name": m.supplier_item_name,
            "pack_size": m.pack_size,
            "is_active": m.is_active,
            "created_by": m.created_by,
            "created_at": m.created_at
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True)

    st.markdown("### Test Barcode Lookup")
    test_code = st.text_input("Scan or type any internal/supplier barcode to test")
    if test_code:
        item, source = get_item_by_any_barcode(db, test_code)
        if item:
            st.success(f"Found: {item.name} | Internal SKU: {item.barcode} | Source: {source}")
        else:
            st.error("Barcode not found in item master or supplier mapping.")

    db.close()


# -------------------------
# DOCTOR & COST CENTERS
# -------------------------

elif choice == "Doctor & Cost Centers":
    require_roles(["Super Admin", "Inventory Manager"])
    db = get_db()
    st.subheader("Doctor and Cost Center Mapping")

    with st.form("doctor_form"):
        col1, col2, col3 = st.columns(3)
        doctor_name = col1.text_input("Doctor Name")
        department = col2.selectbox("Department / Cost Center", ["GP Dentistry", "Orthodontics", "Implantology", "Surgery", "Periodontics", "Pedodontics", "General"])
        specialty = col3.text_input("Specialty")
        submitted = st.form_submit_button("Save Doctor")
        if submitted:
            if not doctor_name:
                st.error("Doctor name required.")
            elif db.query(Doctor).filter(Doctor.doctor_name == doctor_name).first():
                st.error("Doctor already exists.")
            else:
                d = Doctor(doctor_name=doctor_name, department=department, specialty=specialty)
                db.add(d)
                db.commit()
                log_audit(db, "Doctor Master", "CREATE", d.id, None, doctor_name, "New doctor mapping", st.session_state.user)
                st.success("Doctor saved.")

    df = pd.read_sql(db.query(Doctor).statement, engine)
    st.dataframe(df, use_container_width=True)
    db.close()


# -------------------------
# PURCHASE / STOCK INWARD
# -------------------------

elif choice == "Purchase Invoice / Stock Inward":
    require_roles(["Super Admin", "Inventory Manager", "Store Keeper"])
    db = get_db()
    st.subheader("Purchase Invoice and Batch-wise Stock Inward")

    with st.form("purchase_form"):
        st.markdown("### Invoice Header")
        c1, c2, c3 = st.columns(3)
        supplier_name = c1.text_input("Supplier Name *")
        invoice_no = c2.text_input("Invoice Number *")
        invoice_date = c3.date_input("Invoice Date", value=date.today())

        c4, c5, c6, c7 = st.columns(4)
        gross_amount = c4.number_input("Gross Amount", min_value=0.0)
        vat_amount = c5.number_input("VAT Amount", min_value=0.0)
        discount_amount = c6.number_input("Discount", min_value=0.0)
        freight_amount = c7.number_input("Freight / Other Cost", min_value=0.0)
        quickbooks_ref = st.text_input("QuickBooks Reference / Bill No.")
        remarks = st.text_area("Invoice Remarks")

        st.markdown("### Item Received")
        i1, i2, i3, i4 = st.columns(4)
        barcode = i1.text_input("Item Barcode / SKU *")
        purchase_qty = i2.number_input("Purchase Quantity", min_value=0.0, help="Enter quantity in purchase UOM, e.g., cartons")
        purchase_unit_cost = i3.number_input("Purchase Unit Cost", min_value=0.0, help="Cost per purchase UOM, e.g., cost per carton")
        batch_no = i4.text_input("Batch Number")
        expiry_date = st.date_input("Expiry Date", value=date.today())

        submitted = st.form_submit_button("Save Purchase and Add Stock")

        if submitted:
            item, barcode_source = get_item_by_any_barcode(db, barcode)
            if not supplier_name or not invoice_no or not item or purchase_qty <= 0:
                st.error("Supplier, invoice number, valid barcode, and quantity are required.")
            else:
                conversion_factor, conversion_note = get_purchase_conversion_factor(db, barcode, item)
                stock_qty = purchase_qty * conversion_factor
                unit_cost = purchase_unit_cost / conversion_factor if conversion_factor else purchase_unit_cost
                qty = stock_qty
                invoice = PurchaseInvoice(
                    supplier_name=supplier_name, invoice_no=invoice_no, invoice_date=invoice_date,
                    gross_amount=gross_amount, vat_amount=vat_amount, discount_amount=discount_amount,
                    freight_amount=freight_amount, quickbooks_ref=quickbooks_ref, remarks=remarks,
                    created_by=st.session_state.user
                )
                db.add(invoice)
                db.commit()

                old_qty = item.current_qty
                old_avg = item.weighted_avg_cost
                item.weighted_avg_cost = recalc_weighted_average_cost(old_qty, old_avg, qty, unit_cost)
                item.current_qty = (item.current_qty or 0) + qty

                batch = Batch(
                    item_id=item.id, purchase_invoice_id=invoice.id, batch_no=batch_no,
                    expiry_date=expiry_date, received_qty=qty, remaining_qty=qty, unit_cost=unit_cost
                )
                db.add(batch)
                db.commit()

                txn = StockTransaction(
                    item_id=item.id, batch_id=batch.id, txn_type="PURCHASE",
                    quantity=qty, unit_cost=unit_cost, total_cost=qty * unit_cost,
                    txn_date=invoice_date, user_name=st.session_state.user,
                    remarks=f"Invoice: {invoice_no}, Supplier: {supplier_name}, Barcode Source: {barcode_source}, Purchase Qty: {purchase_qty} {item.purchase_uom or 'purchase unit'}, Conversion: {conversion_factor}, Stock Qty: {stock_qty} {item.consumption_uom or item.unit}"
                )
                db.add(txn)
                db.commit()

                log_audit(db, "Purchase", "CREATE", txn.id, None, f"{item.name}, purchase qty {purchase_qty}, stock qty {stock_qty}, unit cost {unit_cost}", "Stock inward with UOM conversion", st.session_state.user)
                st.success(f"Stock added using {barcode_source}. {conversion_note}. Added {stock_qty:g} {item.consumption_uom or item.unit}. Internal item: {item.name}. New quantity: {item.current_qty:g}. New weighted average cost: AED {item.weighted_avg_cost:,.2f} per {item.consumption_uom or item.unit}")

    st.markdown("### Recent Purchases")
    df = pd.read_sql(db.query(StockTransaction).filter(StockTransaction.txn_type == "PURCHASE").statement, engine)
    st.dataframe(df, use_container_width=True)
    db.close()


# -------------------------
# CONSUMPTION
# -------------------------

elif choice == "Consumption Entry":
    require_roles(["Super Admin", "Inventory Manager", "Store Keeper", "Doctor"])
    db = get_db()
    st.subheader("Material Consumption Entry")

    doctors = db.query(Doctor).filter(Doctor.is_active == True).all()
    doctor_options = {f"{d.doctor_name} - {d.department}": d for d in doctors}

    with st.form("consumption_form"):
        c1, c2, c3 = st.columns(3)

        with c1.expander("📷 Scan from Camera", expanded=False):
            if barcode_scanner is not None:
                st.caption("Use this from mobile browser. Allow camera permission, then point to QR/barcode.")
                scanned_code = barcode_scanner(key="consumption_live_barcode_scanner")
                if scanned_code:
                    st.session_state["consumption_barcode_input"] = str(scanned_code).strip()
                    st.success(f"Scanned: {st.session_state['consumption_barcode_input']}")
                    st.caption("The scanned code is placed into the barcode field below automatically.")
            else:
                st.warning("Live scanner package is not installed. Add streamlit-barcodescanner to requirements.txt and reboot the app.")

        barcode = c1.text_input("Scan / Enter Barcode *", key="consumption_barcode_input")
        qty = c2.number_input("Quantity Used in Consumption UOM", min_value=0.0, help="Example: if stock UOM is Box, enter number of boxes used")
        txn_date = c3.date_input("Consumption Date", value=date.today())

        doctor_label = st.selectbox("Doctor / Cost Center", list(doctor_options.keys()) if doctor_options else ["No doctor created"])
        p1, p2, p3 = st.columns(3)
        patient_mrn = p1.text_input("Patient MRN")
        procedure_code = p2.text_input("Procedure Code")
        procedure_name = p3.text_input("Procedure / Treatment Name")
        payment_type = st.selectbox("Payment Type", ["N/A", "Cash", "Insurance", "Corporate"])
        remarks = st.text_area("Remarks")
        submitted = st.form_submit_button("Record Consumption")

        if submitted:
            item, barcode_source = get_item_by_any_barcode(db, barcode)
            if not item:
                st.error("Item not found in internal barcode or supplier barcode mapping.")
            elif qty <= 0:
                st.error("Quantity must be greater than zero.")
            elif item.current_qty < qty:
                st.error("Insufficient stock.")
            elif not doctors:
                st.error("Please create doctor/cost center first.")
            else:
                doctor = doctor_options[doctor_label]
                unit_cost = item.weighted_avg_cost or 0
                total_cost = qty * unit_cost

                # Deduct from earliest expiry batch first
                remaining_to_deduct = qty
                batches = db.query(Batch).filter(Batch.item_id == item.id, Batch.remaining_qty > 0).order_by(Batch.expiry_date.asc()).all()
                selected_batch_id = None
                for batch in batches:
                    deduct = min(batch.remaining_qty, remaining_to_deduct)
                    if deduct > 0:
                        batch.remaining_qty -= deduct
                        remaining_to_deduct -= deduct
                        selected_batch_id = batch.id
                    if remaining_to_deduct <= 0:
                        break

                item.current_qty -= qty

                txn = StockTransaction(
                    item_id=item.id, batch_id=selected_batch_id, txn_type="CONSUMPTION",
                    quantity=qty, unit_cost=unit_cost, total_cost=total_cost,
                    doctor_id=doctor.id, patient_mrn=patient_mrn, procedure_code=procedure_code,
                    procedure_name=procedure_name, payment_type=payment_type,
                    cost_center=doctor.department, txn_date=txn_date,
                    user_name=st.session_state.user, remarks=(remarks or "") + f" | Barcode Source: {barcode_source}"
                )
                db.add(txn)
                db.commit()

                log_audit(db, "Consumption", "CREATE", txn.id, None, f"{item.name}, qty {qty}, cost {total_cost}", "Material consumption", st.session_state.user)
                st.success(f"Consumption recorded using {barcode_source}. Internal item: {item.name}. Used {qty:g} {item.consumption_uom or item.unit}. Cost: AED {total_cost:,.2f}. Remaining stock: {item.current_qty:g} {item.consumption_uom or item.unit}")

    db.close()


# -------------------------
# ADJUSTMENTS
# -------------------------

elif choice == "Adjustments":
    require_roles(["Super Admin", "Inventory Manager"])
    db = get_db()
    st.subheader("Stock Adjustment")

    with st.form("adjust_form"):
        barcode = st.text_input("Barcode / SKU")
        adjustment_qty = st.number_input("Adjustment Quantity (+ increase / - decrease)", value=0.0)
        reason = st.text_area("Reason for Adjustment *")
        submitted = st.form_submit_button("Post Adjustment")

        if submitted:
            item, barcode_source = get_item_by_any_barcode(db, barcode)
            if not item:
                st.error("Item not found in internal barcode or supplier barcode mapping.")
            elif not reason:
                st.error("Reason required for audit trail.")
            else:
                old_qty = item.current_qty
                item.current_qty += adjustment_qty
                txn = StockTransaction(
                    item_id=item.id, txn_type="ADJUSTMENT", quantity=adjustment_qty,
                    unit_cost=item.weighted_avg_cost or 0,
                    total_cost=adjustment_qty * (item.weighted_avg_cost or 0),
                    txn_date=date.today(), user_name=st.session_state.user, remarks=reason
                )
                db.add(txn)
                db.commit()
                log_audit(db, "Adjustment", "CREATE", txn.id, f"Old qty: {old_qty}", f"New qty: {item.current_qty}", reason, st.session_state.user)
                st.success("Adjustment posted.")

    db.close()


# -------------------------
# MONTHLY CLOSING
# -------------------------

elif choice == "Monthly Closing":
    require_roles(["Super Admin", "Inventory Manager"])
    db = get_db()
    st.subheader("Monthly Physical Stock Closing")

    period = st.text_input("Period YYYY-MM", value=date.today().strftime("%Y-%m"))
    items = db.query(Item).filter(Item.is_active == True).all()

    st.warning("Enter physical stock count. System will calculate variance. Lock after management approval.")

    rows = []
    for item in items:
        rows.append({
            "item_id": item.id,
            "barcode": item.barcode,
            "name": item.name,
            "system_qty": item.current_qty,
            "physical_qty": item.current_qty,
            "weighted_avg_cost": item.weighted_avg_cost
        })

    df = pd.DataFrame(rows)
    edited = st.data_editor(df, use_container_width=True, num_rows="fixed")

    approved_by = st.text_input("Approved By / Sign-off Authority")
    lock_month = st.checkbox("Lock Month After Save")
    if st.button("Save Monthly Closing"):
        for _, row in edited.iterrows():
            item = db.query(Item).filter(Item.id == int(row["item_id"])).first()
            physical_qty = float(row["physical_qty"])
            system_qty = float(row["system_qty"])
            adjustment_qty = physical_qty - system_qty
            closing_value = physical_qty * (item.weighted_avg_cost or 0)

            closing = MonthlyClosing(
                period=period, item_id=item.id, system_qty=system_qty,
                physical_qty=physical_qty, adjustment_qty=adjustment_qty,
                closing_value=closing_value, prepared_by=st.session_state.user,
                approved_by=approved_by, locked=lock_month
            )
            db.add(closing)

            if adjustment_qty != 0:
                item.current_qty = physical_qty
                txn = StockTransaction(
                    item_id=item.id, txn_type="ADJUSTMENT", quantity=adjustment_qty,
                    unit_cost=item.weighted_avg_cost or 0,
                    total_cost=adjustment_qty * (item.weighted_avg_cost or 0),
                    txn_date=date.today(), user_name=st.session_state.user,
                    remarks=f"Monthly closing adjustment for {period}"
                )
                db.add(txn)

        db.commit()
        log_audit(db, "Monthly Closing", "CREATE", period, None, f"Closing saved for {period}", "Monthly physical count", st.session_state.user)
        st.success("Monthly closing saved.")

    closings = pd.read_sql(db.query(MonthlyClosing).statement, engine)
    st.dataframe(closings, use_container_width=True)
    db.close()


# -------------------------
# CLINICAL COSTING + INVENTORY REPORTS
# -------------------------

elif choice == "Clinical Costing Reports":
    db = get_db()
    st.subheader("Reports - Inventory Movement & Clinical Costing")
    st.caption("Use this section to check how much inventory came in, how much went out, item-wise balance, last purchase price, and DOH costing support reports.")

    report_tab1, report_tab2, report_tab3, report_tab4, report_tab5 = st.tabs([
        "📦 Inventory Summary",
        "🔍 Item Report",
        "⬇️ Inward / ⬆️ Outward",
        "🏷️ Last Purchase Price",
        "🦷 Clinical Costing"
    ])

    # -------------------------
    # TAB 1 - INVENTORY SUMMARY
    # -------------------------
    with report_tab1:
        st.markdown("### Inventory Summary")
        items_df = pd.read_sql(db.query(Item).filter(Item.is_active == True).statement, engine)

        if items_df.empty:
            st.info("No inventory items found.")
        else:
            items_df["inventory_value"] = items_df["current_qty"].fillna(0) * items_df["weighted_avg_cost"].fillna(0)
            low_stock_df = items_df[items_df["current_qty"].fillna(0) <= items_df["min_stock"].fillna(0)]

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                metric_card("Total Inventory Value", money(items_df["inventory_value"].sum()))
            with c2:
                metric_card("Total Items", f"{len(items_df):,}")
            with c3:
                metric_card("Low Stock Items", f"{len(low_stock_df):,}")
            with c4:
                metric_card("Current Quantity", f"{items_df['current_qty'].sum():,.2f}")

            st.markdown("### Category-wise Summary")
            cat_summary = items_df.groupby("category", dropna=False).agg(
                item_count=("id", "count"),
                total_qty=("current_qty", "sum"),
                inventory_value=("inventory_value", "sum")
            ).reset_index().sort_values("inventory_value", ascending=False)
            st.dataframe(cat_summary, use_container_width=True, hide_index=True)

            fig = px.bar(cat_summary, x="category", y="inventory_value", title="Inventory Value by Category")
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("### Low Stock Alert")
            st.dataframe(low_stock_df[["barcode", "name", "category", "unit", "current_qty", "min_stock", "weighted_avg_cost", "inventory_value"]], use_container_width=True, hide_index=True)

            st.download_button(
                "Download Inventory Summary CSV",
                items_df.to_csv(index=False).encode("utf-8"),
                "inventory_summary.csv",
                "text/csv"
            )

    # -------------------------
    # TAB 2 - ITEM REPORT
    # -------------------------
    with report_tab2:
        st.markdown("### Item Report - Search by Date, Item, Category, and Transaction Type")
        f1, f2, f3, f4 = st.columns(4)
        from_date = f1.date_input("From Date", value=date(date.today().year, date.today().month, 1), key="item_from_date")
        to_date = f2.date_input("To Date", value=date.today(), key="item_to_date")

        item_list = db.query(Item).filter(Item.is_active == True).order_by(Item.name).all()
        item_options = ["All Items"] + [f"{i.barcode} - {i.name}" for i in item_list]
        selected_item = f3.selectbox("Item", item_options)
        selected_txn_type = f4.selectbox("Transaction Type", ["All", "PURCHASE", "CONSUMPTION", "ADJUSTMENT", "OPENING"])

        category_options = ["All Categories"] + sorted([x[0] for x in db.query(Item.category).distinct().all() if x[0]])
        selected_category = st.selectbox("Category", category_options)

        if st.button("Search Item Report", key="search_item_report"):
            query = db.query(StockTransaction, Item).join(Item, StockTransaction.item_id == Item.id).filter(
                StockTransaction.txn_date >= from_date,
                StockTransaction.txn_date <= to_date
            )
            if selected_txn_type != "All":
                query = query.filter(StockTransaction.txn_type == selected_txn_type)
            if selected_item != "All Items":
                selected_barcode = selected_item.split(" - ")[0]
                query = query.filter(Item.barcode == selected_barcode)
            if selected_category != "All Categories":
                query = query.filter(Item.category == selected_category)

            rows = []
            for txn, item in query.order_by(StockTransaction.txn_date.desc(), StockTransaction.id.desc()).all():
                rows.append({
                    "date": txn.txn_date,
                    "barcode": item.barcode,
                    "item_name": item.name,
                    "category": item.category,
                    "transaction_type": txn.txn_type,
                    "quantity": txn.quantity,
                    "unit_cost": txn.unit_cost,
                    "total_cost": txn.total_cost,
                    "cost_center": txn.cost_center,
                    "patient_mrn": txn.patient_mrn,
                    "procedure_name": txn.procedure_name,
                    "user": txn.user_name,
                    "remarks": txn.remarks
                })

            result_df = pd.DataFrame(rows)
            if result_df.empty:
                st.info("No item movement found for the selected filters.")
            else:
                c1, c2, c3 = st.columns(3)
                with c1:
                    metric_card("Total Quantity Movement", f"{result_df['quantity'].sum():,.2f}")
                with c2:
                    metric_card("Total Value", money(result_df["total_cost"].sum()))
                with c3:
                    metric_card("Transactions", f"{len(result_df):,}")

                st.dataframe(result_df, use_container_width=True, hide_index=True)
                st.download_button(
                    "Download Item Report CSV",
                    result_df.to_csv(index=False).encode("utf-8"),
                    f"item_report_{from_date}_to_{to_date}.csv",
                    "text/csv"
                )

    # -------------------------
    # TAB 3 - INWARD / OUTWARD MOVEMENT
    # -------------------------
    with report_tab3:
        st.markdown("### Inventory Came In and Went Out")
        m1, m2 = st.columns(2)
        movement_from = m1.date_input("From Date", value=date(date.today().year, date.today().month, 1), key="movement_from")
        movement_to = m2.date_input("To Date", value=date.today(), key="movement_to")

        if st.button("Search Movement Report", key="search_movement_report"):
            query = db.query(StockTransaction, Item).join(Item, StockTransaction.item_id == Item.id).filter(
                StockTransaction.txn_date >= movement_from,
                StockTransaction.txn_date <= movement_to
            )

            rows = []
            for txn, item in query.all():
                inward_qty = txn.quantity if txn.txn_type == "PURCHASE" else 0
                inward_value = txn.total_cost if txn.txn_type == "PURCHASE" else 0
                outward_qty = txn.quantity if txn.txn_type == "CONSUMPTION" else 0
                outward_value = txn.total_cost if txn.txn_type == "CONSUMPTION" else 0
                adjustment_qty = txn.quantity if txn.txn_type == "ADJUSTMENT" else 0
                adjustment_value = txn.total_cost if txn.txn_type == "ADJUSTMENT" else 0
                rows.append({
                    "barcode": item.barcode,
                    "item_name": item.name,
                    "category": item.category,
                    "inward_qty": inward_qty,
                    "inward_value": inward_value,
                    "outward_qty": outward_qty,
                    "outward_value": outward_value,
                    "adjustment_qty": adjustment_qty,
                    "adjustment_value": adjustment_value,
                    "current_qty": item.current_qty,
                    "current_value": (item.current_qty or 0) * (item.weighted_avg_cost or 0)
                })

            movement_df = pd.DataFrame(rows)
            if movement_df.empty:
                st.info("No stock movement found for selected dates.")
            else:
                movement_summary = movement_df.groupby(["barcode", "item_name", "category"], dropna=False).agg(
                    inward_qty=("inward_qty", "sum"),
                    inward_value=("inward_value", "sum"),
                    outward_qty=("outward_qty", "sum"),
                    outward_value=("outward_value", "sum"),
                    adjustment_qty=("adjustment_qty", "sum"),
                    adjustment_value=("adjustment_value", "sum"),
                    current_qty=("current_qty", "max"),
                    current_value=("current_value", "max")
                ).reset_index()

                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    metric_card("Inventory Came In", money(movement_summary["inward_value"].sum()))
                with c2:
                    metric_card("Inventory Went Out", money(movement_summary["outward_value"].sum()))
                with c3:
                    metric_card("Net Qty Movement", f"{(movement_summary['inward_qty'].sum() - movement_summary['outward_qty'].sum() + movement_summary['adjustment_qty'].sum()):,.2f}")
                with c4:
                    metric_card("Current Value", money(movement_summary["current_value"].sum()))

                st.dataframe(movement_summary, use_container_width=True, hide_index=True)

                chart_df = pd.DataFrame({
                    "Movement": ["Inward", "Outward", "Adjustment"],
                    "Value": [movement_summary["inward_value"].sum(), movement_summary["outward_value"].sum(), movement_summary["adjustment_value"].sum()]
                })
                fig = px.bar(chart_df, x="Movement", y="Value", title="Inventory Movement Value")
                st.plotly_chart(fig, use_container_width=True)

                st.download_button(
                    "Download Movement Report CSV",
                    movement_summary.to_csv(index=False).encode("utf-8"),
                    f"inventory_movement_{movement_from}_to_{movement_to}.csv",
                    "text/csv"
                )

    # -------------------------
    # TAB 4 - LAST PURCHASE PRICE
    # -------------------------
    with report_tab4:
        st.markdown("### Item Last Purchase Price Report")
        last_rows = []
        items = db.query(Item).filter(Item.is_active == True).order_by(Item.name).all()
        for item in items:
            last_purchase = db.query(StockTransaction).filter(
                StockTransaction.item_id == item.id,
                StockTransaction.txn_type == "PURCHASE"
            ).order_by(StockTransaction.txn_date.desc(), StockTransaction.id.desc()).first()

            last_batch = db.query(Batch).filter(Batch.item_id == item.id).order_by(Batch.created_at.desc()).first()

            last_rows.append({
                "barcode": item.barcode,
                "item_name": item.name,
                "category": item.category,
                "unit": item.unit,
                "current_qty": item.current_qty,
                "weighted_avg_cost": item.weighted_avg_cost,
                "current_value": (item.current_qty or 0) * (item.weighted_avg_cost or 0),
                "last_purchase_date": last_purchase.txn_date if last_purchase else None,
                "last_purchase_qty": last_purchase.quantity if last_purchase else 0,
                "last_purchase_unit_price": last_purchase.unit_cost if last_purchase else 0,
                "last_purchase_total": last_purchase.total_cost if last_purchase else 0,
                "last_batch_no": last_batch.batch_no if last_batch else None,
                "last_expiry_date": last_batch.expiry_date if last_batch else None
            })

        last_df = pd.DataFrame(last_rows)
        search_text = st.text_input("Search item name / barcode", key="last_price_search")
        if search_text:
            mask = last_df["item_name"].str.contains(search_text, case=False, na=False) | last_df["barcode"].str.contains(search_text, case=False, na=False)
            last_df = last_df[mask]

        st.dataframe(last_df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Last Purchase Price CSV",
            last_df.to_csv(index=False).encode("utf-8"),
            "last_purchase_price_report.csv",
            "text/csv"
        )

    # -------------------------
    # TAB 5 - EXISTING CLINICAL COSTING REPORTS
    # -------------------------
    with report_tab5:
        st.markdown("### Clinical Costing Report")
        period = st.text_input("Report Period YYYY-MM", value=date.today().strftime("%Y-%m"))
        start, end = period_filter_expr(period)

        txns_query = db.query(StockTransaction).filter(
            StockTransaction.txn_date >= start,
            StockTransaction.txn_date < end
        )

        df_txn = pd.read_sql(txns_query.statement, engine)

        if df_txn.empty:
            st.info("No transactions found for selected period.")
        else:
            consumption = df_txn[df_txn["txn_type"] == "CONSUMPTION"]

            c1, c2, c3 = st.columns(3)
            with c1:
                metric_card("Total Consumption Cost", money(consumption["total_cost"].sum()))
            with c2:
                metric_card("Total Purchase Cost", money(df_txn[df_txn["txn_type"] == "PURCHASE"]["total_cost"].sum()))
            with c3:
                metric_card("Consumption Entries", f"{len(consumption):,}")

            st.markdown("### Doctor / Cost Center Consumption")
            if not consumption.empty:
                report_cc = consumption.groupby("cost_center", dropna=False)["total_cost"].sum().reset_index()
                st.dataframe(report_cc, use_container_width=True, hide_index=True)
                fig = px.pie(report_cc, names="cost_center", values="total_cost", title="Consumption Cost by Cost Center")
                st.plotly_chart(fig, use_container_width=True)

                st.markdown("### Procedure-wise Material Cost")
                report_proc = consumption.groupby(["procedure_code", "procedure_name"], dropna=False)["total_cost"].sum().reset_index()
                st.dataframe(report_proc, use_container_width=True, hide_index=True)

                st.markdown("### Patient / MRN Material Usage")
                report_patient = consumption.groupby(["patient_mrn", "procedure_name"], dropna=False)["total_cost"].sum().reset_index()
                st.dataframe(report_patient, use_container_width=True, hide_index=True)

            st.download_button(
                "Download Clinical Costing Transaction CSV",
                df_txn.to_csv(index=False).encode("utf-8"),
                f"clinical_costing_transactions_{period}.csv",
                "text/csv"
            )

    db.close()


# -------------------------
# QUICKBOOKS RECONCILIATION
# -------------------------

elif choice == "QuickBooks Reconciliation":
    require_roles(["Super Admin", "Inventory Manager"])
    db = get_db()
    st.subheader("QuickBooks / Trial Balance Reconciliation")

    period = st.text_input("Period YYYY-MM", value=date.today().strftime("%Y-%m"))
    start, end = period_filter_expr(period)

    system_purchase_total = db.query(func.sum(StockTransaction.total_cost)).filter(
        StockTransaction.txn_type == "PURCHASE",
        StockTransaction.txn_date >= start,
        StockTransaction.txn_date < end
    ).scalar() or 0.0

    system_consumption_cost = db.query(func.sum(StockTransaction.total_cost)).filter(
        StockTransaction.txn_type == "CONSUMPTION",
        StockTransaction.txn_date >= start,
        StockTransaction.txn_date < end
    ).scalar() or 0.0

    system_inventory_value = db.query(func.sum(Item.current_qty * Item.weighted_avg_cost)).scalar() or 0.0

    c1, c2, c3 = st.columns(3)
    c1.metric("System Purchases", f"AED {system_purchase_total:,.2f}")
    c2.metric("System Consumption", f"AED {system_consumption_cost:,.2f}")
    c3.metric("System Inventory Value", f"AED {system_inventory_value:,.2f}")

    with st.form("recon_form"):
        qb_purchase_total = st.number_input("QuickBooks Purchase Total", min_value=0.0)
        qb_material_expense = st.number_input("QuickBooks Material Expense / Consumption", min_value=0.0)
        qb_inventory_balance = st.number_input("QuickBooks Inventory Balance", min_value=0.0)
        approved_by = st.text_input("Approved By / CFO / CEO")
        signoff_status = st.selectbox("Status", ["Draft", "Prepared", "Approved", "Rejected"])
        remarks = st.text_area("Remarks / Variance Explanation")
        submitted = st.form_submit_button("Save Reconciliation")

        if submitted:
            recon = Reconciliation(
                period=period,
                qb_purchase_total=qb_purchase_total,
                system_purchase_total=system_purchase_total,
                qb_material_expense=qb_material_expense,
                system_consumption_cost=system_consumption_cost,
                qb_inventory_balance=qb_inventory_balance,
                system_inventory_value=system_inventory_value,
                variance_purchase=qb_purchase_total - system_purchase_total,
                variance_consumption=qb_material_expense - system_consumption_cost,
                variance_inventory=qb_inventory_balance - system_inventory_value,
                prepared_by=st.session_state.user,
                approved_by=approved_by,
                signoff_status=signoff_status,
                remarks=remarks
            )
            db.add(recon)
            db.commit()
            log_audit(db, "Reconciliation", "CREATE", recon.id, None, f"Recon {period}", remarks, st.session_state.user)
            st.success("Reconciliation saved.")

    df = pd.read_sql(db.query(Reconciliation).statement, engine)
    st.dataframe(df, use_container_width=True)
    db.close()


# -------------------------
# AUDIT LOG
# -------------------------

elif choice == "Audit Log":
    require_roles(["Super Admin", "Inventory Manager"])
    db = get_db()
    st.subheader("Audit Log")
    df = pd.read_sql(db.query(AuditLog).order_by(AuditLog.created_at.desc()).statement, engine)
    st.dataframe(df, use_container_width=True)
    db.close()



# -------------------------
# TEMPORARY CONSUMPTION
# -------------------------

elif choice == "Temporary Consumption":
    require_module_access("Temporary Consumption")
    db = get_db()
    st.subheader("Temporary Consumption - Item Not Yet Added")
    st.caption("Use this only when treatment cannot wait and the item is not yet available in the item master. Admin/store must clear pending entries later.")

    temp_tab1, temp_tab2 = st.tabs(["➕ Enter Temporary Usage", "✅ Review / Map Pending Items"])

    with temp_tab1:
        doctors = db.query(Doctor).filter(Doctor.is_active == True).all()
        doctor_options = {f"{d.doctor_name} - {d.department}": d for d in doctors}
        with st.form("temporary_consumption_form"):
            c1, c2, c3 = st.columns(3)
            temp_item_name = c1.text_input("Temporary Item Name *")
            temp_barcode = c2.text_input("Barcode if available")
            qty = c3.number_input("Quantity Used *", min_value=0.0)
            estimated_unit_cost = c1.number_input("Estimated Unit Cost", min_value=0.0)
            txn_date = c2.date_input("Usage Date", value=date.today())
            doctor_label = c3.selectbox("Doctor / Cost Center", list(doctor_options.keys()) if doctor_options else ["No doctor created"])
            p1, p2, p3 = st.columns(3)
            patient_mrn = p1.text_input("Patient MRN")
            procedure_code = p2.text_input("Procedure Code")
            procedure_name = p3.text_input("Procedure Name")
            remarks = st.text_area("Reason / Remarks")
            submitted = st.form_submit_button("Save Temporary Consumption")

            if submitted:
                if not temp_item_name or qty <= 0:
                    st.error("Temporary item name and quantity are required.")
                elif not doctors:
                    st.error("Please create doctor/cost center first.")
                else:
                    doctor = doctor_options[doctor_label]
                    temp = TemporaryConsumption(
                        temp_item_name=temp_item_name,
                        temp_barcode=temp_barcode,
                        quantity=qty,
                        estimated_unit_cost=estimated_unit_cost,
                        estimated_total_cost=qty * estimated_unit_cost,
                        doctor_id=doctor.id,
                        patient_mrn=patient_mrn,
                        procedure_code=procedure_code,
                        procedure_name=procedure_name,
                        cost_center=doctor.department,
                        txn_date=txn_date,
                        entered_by=st.session_state.user,
                        remarks=remarks
                    )
                    db.add(temp)
                    db.commit()
                    log_audit(db, "Temporary Consumption", "CREATE", temp.id, None, f"{temp_item_name}, qty {qty}", "Temporary usage", st.session_state.user)
                    st.success("Temporary consumption saved. Store/Admin must map it to an actual item later.")

    with temp_tab2:
        st.markdown("### Pending Temporary Entries")
        pending = db.query(TemporaryConsumption).filter(TemporaryConsumption.status == "Pending").order_by(TemporaryConsumption.created_at.desc()).all()
        if not pending:
            st.info("No pending temporary consumption entries.")
        else:
            rows = []
            for t in pending:
                rows.append({
                    "id": t.id,
                    "date": t.txn_date,
                    "item": t.temp_item_name,
                    "barcode": t.temp_barcode,
                    "qty": t.quantity,
                    "estimated_cost": t.estimated_total_cost,
                    "cost_center": t.cost_center,
                    "patient_mrn": t.patient_mrn,
                    "procedure": t.procedure_name,
                    "entered_by": t.entered_by,
                    "remarks": t.remarks
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            if st.session_state.role in ["Super Admin", "Inventory Manager", "Store Keeper"]:
                st.markdown("### Map Temporary Usage to Actual Inventory Item")
                with st.form("map_temp_form"):
                    temp_id = st.number_input("Temporary Entry ID", min_value=1, step=1)
                    actual_barcode = st.text_input("Actual Item Barcode / SKU")
                    admin_password = st.text_input("Admin Password Required", type="password")
                    admin_remarks = st.text_area("Admin Remarks")
                    map_btn = st.form_submit_button("Map and Create Actual Consumption")

                    if map_btn:
                        if not verify_admin_password(admin_password):
                            st.error("Admin password is incorrect.")
                        else:
                            temp = db.query(TemporaryConsumption).filter(TemporaryConsumption.id == int(temp_id), TemporaryConsumption.status == "Pending").first()
                            item = get_item_by_barcode(db, actual_barcode)
                            if not temp:
                                st.error("Pending temporary entry not found.")
                            elif not item:
                                st.error("Actual inventory item not found. Create it in Inventory Master first.")
                            elif item.current_qty < temp.quantity:
                                st.error("Actual item has insufficient stock. Add purchase/stock inward first.")
                            else:
                                unit_cost = item.weighted_avg_cost or temp.estimated_unit_cost or 0
                                total_cost = temp.quantity * unit_cost
                                item.current_qty -= temp.quantity
                                txn = StockTransaction(
                                    item_id=item.id,
                                    txn_type="CONSUMPTION",
                                    quantity=temp.quantity,
                                    unit_cost=unit_cost,
                                    total_cost=total_cost,
                                    doctor_id=temp.doctor_id,
                                    patient_mrn=temp.patient_mrn,
                                    procedure_code=temp.procedure_code,
                                    procedure_name=temp.procedure_name,
                                    payment_type="N/A",
                                    cost_center=temp.cost_center,
                                    txn_date=temp.txn_date,
                                    user_name=temp.entered_by,
                                    remarks=f"Mapped from temporary consumption ID {temp.id}. {admin_remarks or ''}"
                                )
                                db.add(txn)
                                db.commit()
                                temp.status = "Mapped"
                                temp.mapped_item_id = item.id
                                temp.mapped_transaction_id = txn.id
                                temp.reviewed_by = st.session_state.user
                                temp.reviewed_at = datetime.now()
                                temp.admin_remarks = admin_remarks
                                db.commit()
                                log_audit(db, "Temporary Consumption", "MAP", temp.id, temp.temp_item_name, item.name, admin_remarks, st.session_state.user)
                                st.success("Temporary entry mapped and actual consumption posted.")
            else:
                st.info("Only Super Admin, Inventory Manager, or Store Keeper can map temporary entries.")

        st.markdown("### All Temporary Consumption Records")
        all_temp = pd.read_sql(db.query(TemporaryConsumption).order_by(TemporaryConsumption.created_at.desc()).statement, engine)
        st.dataframe(all_temp, use_container_width=True)
    db.close()


# -------------------------
# ADMIN EDIT CENTER
# -------------------------

elif choice == "Admin Edit Center":
    require_roles(["Super Admin"])
    db = get_db()
    st.subheader("Admin Edit Center")
    st.caption("Admin password is required before editing important saved records.")

    admin_password = st.text_input("Enter Admin Password to Unlock Editing", type="password")
    unlocked = verify_admin_password(admin_password) if admin_password else False

    if not unlocked:
        st.info("Enter the Super Admin password to edit records.")
    else:
        edit_tab1, edit_tab2, edit_tab3 = st.tabs(["Inventory Items", "Doctors", "Transactions"])

        with edit_tab1:
            items_df = pd.read_sql(db.query(Item).statement, engine)
            st.dataframe(items_df, use_container_width=True)
            with st.form("edit_item_form"):
                item_id = st.number_input("Item ID", min_value=1, step=1)
                new_name = st.text_input("New Item Name")
                new_min_stock = st.number_input("New Minimum Stock", min_value=0.0)
                new_account = st.text_input("New QuickBooks Account")
                reason = st.text_area("Reason for Edit", key="item_edit_reason")
                if st.form_submit_button("Update Item"):
                    item = db.query(Item).filter(Item.id == int(item_id)).first()
                    if not item:
                        st.error("Item not found.")
                    elif not reason:
                        st.error("Reason is required.")
                    else:
                        old = f"name={item.name}, min_stock={item.min_stock}, account={item.default_expense_account}"
                        if new_name:
                            item.name = new_name
                        item.min_stock = new_min_stock
                        item.default_expense_account = new_account
                        db.commit()
                        newv = f"name={item.name}, min_stock={item.min_stock}, account={item.default_expense_account}"
                        log_audit(db, "Admin Edit - Item", "UPDATE", item.id, old, newv, reason, st.session_state.user)
                        st.success("Item updated.")

        with edit_tab2:
            doctors_df = pd.read_sql(db.query(Doctor).statement, engine)
            st.dataframe(doctors_df, use_container_width=True)
            with st.form("edit_doctor_form"):
                doctor_id = st.number_input("Doctor ID", min_value=1, step=1)
                new_department = st.selectbox("New Department", ["GP Dentistry", "Orthodontics", "Implantology", "Surgery", "Periodontics", "Pedodontics", "General"])
                active_status = st.checkbox("Active", value=True)
                reason = st.text_area("Reason for Edit", key="doctor_edit_reason")
                if st.form_submit_button("Update Doctor"):
                    doctor = db.query(Doctor).filter(Doctor.id == int(doctor_id)).first()
                    if not doctor:
                        st.error("Doctor not found.")
                    elif not reason:
                        st.error("Reason is required.")
                    else:
                        old = f"department={doctor.department}, active={doctor.is_active}"
                        doctor.department = new_department
                        doctor.is_active = active_status
                        db.commit()
                        newv = f"department={doctor.department}, active={doctor.is_active}"
                        log_audit(db, "Admin Edit - Doctor", "UPDATE", doctor.id, old, newv, reason, st.session_state.user)
                        st.success("Doctor updated.")

        with edit_tab3:
            st.warning("For safety, this section allows editing remarks/date only. Quantity/cost corrections should be posted through Adjustments.")
            txns_df = pd.read_sql(db.query(StockTransaction).order_by(StockTransaction.id.desc()).limit(200).statement, engine)
            st.dataframe(txns_df, use_container_width=True)
            with st.form("edit_txn_form"):
                txn_id = st.number_input("Transaction ID", min_value=1, step=1)
                new_date = st.date_input("Correct Transaction Date", value=date.today())
                new_remarks = st.text_area("Corrected Remarks")
                reason = st.text_area("Reason for Edit", key="txn_edit_reason")
                if st.form_submit_button("Update Transaction Date / Remarks"):
                    txn = db.query(StockTransaction).filter(StockTransaction.id == int(txn_id)).first()
                    if not txn:
                        st.error("Transaction not found.")
                    elif not reason:
                        st.error("Reason is required.")
                    else:
                        old = f"date={txn.txn_date}, remarks={txn.remarks}"
                        txn.txn_date = new_date
                        txn.remarks = new_remarks
                        db.commit()
                        newv = f"date={txn.txn_date}, remarks={txn.remarks}"
                        log_audit(db, "Admin Edit - Transaction", "UPDATE", txn.id, old, newv, reason, st.session_state.user)
                        st.success("Transaction updated.")
    db.close()


# -------------------------
# BACKUP
# -------------------------

elif choice == "Backup":
    require_module_access("Backup")
    db = get_db()
    st.subheader("Database Backup")
    st.caption("Create manual backups and enable simple daily/weekly scheduled backup when the app is opened.")

    config = db.query(BackupConfig).first()
    if not config:
        config = BackupConfig(backup_folder="backups", frequency="Manual", enabled=False, updated_by=st.session_state.user)
        db.add(config)
        db.commit()

    b1, b2, b3 = st.columns(3)
    b1.metric("Backup Folder", config.backup_folder)
    b2.metric("Schedule", config.frequency)
    b3.metric("Last Backup", config.last_backup_at.strftime("%Y-%m-%d %H:%M") if config.last_backup_at else "Not yet")

    if st.button("Create Manual Backup Now"):
        ok, msg, backup_file = make_backup("Manual", st.session_state.user)
        if ok:
            st.success(msg)
            with open(backup_file, "rb") as f:
                st.download_button("Download Backup DB", f.read(), Path(backup_file).name, "application/octet-stream")
        else:
            st.error(msg)

    with st.form("backup_settings_form"):
        backup_folder = st.text_input("Backup Folder", value=config.backup_folder)
        frequency = st.selectbox("Scheduled Backup Frequency", ["Manual", "Daily", "Weekly"], index=["Manual", "Daily", "Weekly"].index(config.frequency))
        enabled = st.checkbox("Enable Scheduled Backup", value=config.enabled)
        admin_password = st.text_input("Admin Password Required", type="password")
        if st.form_submit_button("Save Backup Settings"):
            if not verify_admin_password(admin_password):
                st.error("Admin password is incorrect.")
            else:
                old = f"folder={config.backup_folder}, frequency={config.frequency}, enabled={config.enabled}"
                config.backup_folder = backup_folder
                config.frequency = frequency
                config.enabled = enabled
                config.updated_by = st.session_state.user
                config.updated_at = datetime.now()
                db.commit()
                log_audit(db, "Backup", "UPDATE SETTINGS", config.id, old, f"folder={backup_folder}, frequency={frequency}, enabled={enabled}", "Backup settings", st.session_state.user)
                st.success("Backup settings saved.")

    logs = pd.read_sql(db.query(BackupLog).order_by(BackupLog.created_at.desc()).statement, engine)
    st.markdown("### Backup History")
    st.dataframe(logs, use_container_width=True)
    db.close()


# -------------------------
# ROLE SETTINGS
# -------------------------

elif choice == "Role Settings":
    require_roles(["Super Admin"])
    db = get_db()
    st.subheader("Role Settings - Module Access")
    st.caption("Tick the modules each role can access. Super Admin always has full access.")

    selected_role = st.selectbox("Select Role", DEFAULT_ROLES)
    st.markdown(f"### Access for: {selected_role}")
    admin_password = st.text_input("Admin Password Required to Save", type="password")

    current = {p.module: p.can_access for p in db.query(RolePermission).filter(RolePermission.role == selected_role).all()}
    new_permissions = {}
    cols = st.columns(3)
    for idx, module in enumerate(ALL_MODULES):
        disabled = selected_role == "Super Admin"
        default_value = True if selected_role == "Super Admin" else current.get(module, False)
        with cols[idx % 3]:
            new_permissions[module] = st.checkbox(module, value=default_value, disabled=disabled, key=f"perm_{selected_role}_{module}")

    if st.button("Save Role Permissions"):
        if not verify_admin_password(admin_password):
            st.error("Admin password is incorrect.")
        else:
            for module, allowed in new_permissions.items():
                perm = db.query(RolePermission).filter(RolePermission.role == selected_role, RolePermission.module == module).first()
                if not perm:
                    perm = RolePermission(role=selected_role, module=module)
                    db.add(perm)
                perm.can_access = True if selected_role == "Super Admin" else allowed
                perm.updated_by = st.session_state.user
                perm.updated_at = datetime.now()
            db.commit()
            log_audit(db, "Role Settings", "UPDATE", selected_role, None, str(new_permissions), "Module permission update", st.session_state.user)
            st.success("Role permissions saved. Users may need to logout/login to refresh menu.")

    st.markdown("### Current Permission Table")
    perm_df = pd.read_sql(db.query(RolePermission).statement, engine)
    st.dataframe(perm_df, use_container_width=True)
    db.close()


# -------------------------
# USER MANAGEMENT
# -------------------------

elif choice == "User Management":
    require_roles(["Super Admin"])
    db = get_db()
    st.subheader("User Management")

    with st.form("user_form"):
        c1, c2, c3 = st.columns(3)
        username = c1.text_input("Username")
        password = c2.text_input("Password", type="password")
        role = c3.selectbox("Role", DEFAULT_ROLES)
        submitted = st.form_submit_button("Create User")

        if submitted:
            if not username or not password:
                st.error("Username and password required.")
            elif db.query(User).filter(User.username == username).first():
                st.error("Username already exists.")
            else:
                user = User(username=username, password_hash=hash_password(password), role=role)
                db.add(user)
                db.commit()
                log_audit(db, "User Management", "CREATE", user.id, None, username, "New user", st.session_state.user)
                st.success("User created.")

    st.markdown("---")
    st.subheader("Reset User Password")
    users = db.query(User).order_by(User.username.asc()).all()
    user_options = {f"{u.username} | {u.role}": u for u in users}
    with st.form("reset_password_form"):
        selected_user_label = st.selectbox("Select User", list(user_options.keys()) if user_options else ["No users found"])
        new_password = st.text_input("New Password", type="password")
        admin_password = st.text_input("Admin Password Confirmation", type="password")
        reset_submitted = st.form_submit_button("Reset Password")
        if reset_submitted:
            admin_user = db.query(User).filter(User.username == st.session_state.user).first()
            if not admin_user or not verify_password(admin_password, admin_user.password_hash):
                st.error("Admin password is incorrect.")
            elif not new_password:
                st.error("New password is required.")
            else:
                selected_user = user_options[selected_user_label]
                selected_user.password_hash = hash_password(new_password)
                db.commit()
                log_audit(db, "User Management", "PASSWORD_RESET", selected_user.id, None, selected_user.username, "Password reset by admin", st.session_state.user)
                st.success(f"Password reset completed for {selected_user.username}.")

    df = pd.read_sql(db.query(User).statement, engine)
    st.dataframe(df[["username", "role", "is_active", "created_at"]], use_container_width=True)
    db.close()
