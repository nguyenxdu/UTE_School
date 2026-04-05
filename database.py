import sqlite3

DB_PATH = "db.sqlite"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # trả về dict thay vì tuple
    return conn


def _table_columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def migrate_db(conn):
    """Thêm cột mới cho DB cũ (SQLite)."""
    cur = conn.cursor()
    ucols = _table_columns(conn, "users")
    if "he_dao_tao" not in ucols:
        cur.execute("ALTER TABLE users ADD COLUMN he_dao_tao TEXT DEFAULT ''")
    dcols = _table_columns(conn, "dot")
    if "he_dao_tao" not in dcols:
        cur.execute("ALTER TABLE dot ADD COLUMN he_dao_tao TEXT DEFAULT ''")
    if "nganh" not in dcols:
        cur.execute("ALTER TABLE dot ADD COLUMN nganh TEXT DEFAULT ''")
    gcols = _table_columns(conn, "gv_slot")
    if "he_dao_tao" not in gcols:
        cur.execute("ALTER TABLE gv_slot ADD COLUMN he_dao_tao TEXT DEFAULT 'DaiTra'")
    conn.commit()


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ma TEXT UNIQUE NOT NULL,        -- MSSV hoặc MAGV
            ho_ten TEXT NOT NULL,
            mat_khau TEXT NOT NULL,
            role TEXT NOT NULL,             -- SV / GV / TBM
            linh_vuc TEXT,                  -- major / chuyên môn (chuỗi phân tách bởi dấu phẩy)
            he_dao_tao TEXT DEFAULT ''      -- DaiTra / CLC (SV & có thể dùng cho GV)
        );

        CREATE TABLE IF NOT EXISTS dot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ten_dot TEXT NOT NULL,
            loai TEXT NOT NULL,             -- BCTT / KLTN
            han_dang_ky TEXT,
            han_nop TEXT,
            trang_thai TEXT DEFAULT 'mo',    -- mo / dong
            he_dao_tao TEXT DEFAULT '',     -- để trống nếu đợt chung (không tách Đại trà/CLC)
            nganh TEXT DEFAULT ''           -- QLCN, TMĐT, ... (khớp linh_vuc SV)
        );

        CREATE TABLE IF NOT EXISTS gv_slot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gv_id INTEGER,
            dot_id INTEGER,
            quota INTEGER DEFAULT 5,
            slot_con_lai INTEGER DEFAULT 5,
            duyet_tbm INTEGER DEFAULT 0,    -- 0/1
            he_dao_tao TEXT DEFAULT 'DaiTra', -- DaiTra / CLC — pool slot theo hệ SV
            FOREIGN KEY(gv_id) REFERENCES users(id),
            FOREIGN KEY(dot_id) REFERENCES dot(id)
        );

        CREATE TABLE IF NOT EXISTS dang_ky (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sv_id INTEGER,
            gv_id INTEGER,
            dot_id INTEGER,
            loai TEXT NOT NULL,             -- BCTT / KLTN
            ten_de_tai TEXT,
            linh_vuc TEXT,
            trang_thai TEXT DEFAULT 'cho_duyet',  -- cho_duyet/dong_y/tu_choi/pass/fail
            FOREIGN KEY(sv_id) REFERENCES users(id),
            FOREIGN KEY(gv_id) REFERENCES users(id),
            FOREIGN KEY(dot_id) REFERENCES dot(id)
        );

        CREATE TABLE IF NOT EXISTS nop_bai (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dang_ky_id INTEGER,
            loai_file TEXT,   -- bai_lam/phieu_xn/turnitin/bai_chinh_sua/bien_ban_giai_trinh
            file_path TEXT,
            uploaded_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(dang_ky_id) REFERENCES dang_ky(id)
        );

        CREATE TABLE IF NOT EXISTS cham_diem (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dang_ky_id INTEGER,
            gv_id INTEGER,
            vai_tro TEXT,     -- HD / PB / CT / TV
            diem REAL,
            nhan_xet TEXT,
            cau_hoi TEXT,
            FOREIGN KEY(dang_ky_id) REFERENCES dang_ky(id),
            FOREIGN KEY(gv_id) REFERENCES users(id)
        );
                         
        CREATE TABLE IF NOT EXISTS thong_bao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nguoi_nhan_id INTEGER NOT NULL,
            nguoi_gui_id INTEGER,
            dang_ky_id INTEGER,
            loai TEXT,          -- 'tu_choi_gvhd' / 'tu_choi_cthd'
            noi_dung TEXT,      -- lý do từ chối GV ghi
            da_doc INTEGER DEFAULT 0,
            tao_luc TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(nguoi_nhan_id) REFERENCES users(id),
            FOREIGN KEY(nguoi_gui_id) REFERENCES users(id),
            FOREIGN KEY(dang_ky_id) REFERENCES dang_ky(id)
        );
    """)

    migrate_db(conn)
    conn.commit()
    conn.close()
    print("✅ Database initialized!")