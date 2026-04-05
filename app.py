# -*- coding: utf-8 -*-
import os
import subprocess
import json
import tempfile
from functools import wraps
from datetime import datetime
from flask import Flask, request, jsonify, session, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
from database import get_db, init_db
import google.generativeai as genai
from pypdf import PdfReader
from docx import Document

app = Flask(__name__)
app.secret_key = "secret_key_123"
CORS(app, supports_credentials=True)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyBXKIdqFfH3OBbfhGUuiF2V0BxfkcgK4IM").strip()
GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL", "").strip()
_GEMINI_CONFIGURED = False

UPLOAD_FOLDER = "uploads"
UPLOAD_FOLDER = os.path.join(app.root_path, UPLOAD_FOLDER)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def _resolve_upload_path(stored_path):
    if not stored_path:
        return ""
    normalized = str(stored_path).replace("\\", "/")
    if os.path.isabs(normalized):
        return normalized
    return os.path.join(app.root_path, normalized)

init_db()

@app.route("/", methods=["GET"])
def home():
    # Sử dụng luôn hàm ok() bạn đã viết trong app.py
    return ok("UTE School API is running mượt mà 🚀")


def ok(message="Thành công", data=None, status=200):
    return jsonify({"success": True, "message": message, "data": data or {}}), status


def fail(message="Có lỗi xảy ra", status=400):
    return jsonify({"success": False, "message": message, "data": {}}), status


def _configure_gemini():
    global _GEMINI_CONFIGURED
    if _GEMINI_CONFIGURED:
        return True
    try:
        if GEMINI_API_KEY:
            genai.configure(api_key=GEMINI_API_KEY)
        _GEMINI_CONFIGURED = True
        return True
    except Exception as e:
        print(f"[ERROR] Failed to configure Gemini: {str(e)}")
        return False


def _candidate_gemini_models():
    candidates = []
    if GEMINI_MODEL_NAME:
        for name in GEMINI_MODEL_NAME.split(","):
            model_name = name.strip()
            if model_name and model_name not in candidates:
                candidates.append(model_name)

    # Ưu tiên model mới trước, giữ model cũ làm fallback tương thích.
    # Lưu ý: gemini-1.5-flash đã bị deprecated, chỉ dùng gemini-2.0 trở lên
    defaults = [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-pro",
        "gemini-pro",
    ]
    for model_name in defaults:
        if model_name not in candidates:
            candidates.append(model_name)
    return candidates


def _read_pdf_text(file_path):
    reader = PdfReader(file_path)
    chunks = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            chunks.append(text)
    return "\n".join(chunks)


def _read_docx_text(file_path):
    doc = Document(file_path)
    chunks = [para.text for para in doc.paragraphs if para.text and para.text.strip()]
    return "\n".join(chunks)


def _read_text_from_file(file_path):
    file_path = _resolve_upload_path(file_path)
    if not file_path or not os.path.exists(file_path):
        return ""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return _read_pdf_text(file_path)
    if ext == ".docx":
        return _read_docx_text(file_path)
    if ext == ".txt":
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    return ""


def _pick_latest_upload_paths(conn, dang_ky_id, loai_file_list):
    placeholders = ",".join(["?"] * len(loai_file_list))
    rows = conn.execute(
        f"""
        SELECT loai_file, file_path
        FROM nop_bai
        WHERE dang_ky_id = ? AND loai_file IN ({placeholders})
        ORDER BY id DESC
        """,
        [dang_ky_id, *loai_file_list],
    ).fetchall()
    seen = set()
    paths = []
    for row in rows:
        path = row["file_path"]
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def _collect_summary_content(conn, dang_ky_id):
    paths = _pick_latest_upload_paths(conn, dang_ky_id, ["kltn_bai_pdf", "kltn_bai_word", "kltn_bai"])
    if not paths:
        return "", []
    texts = []
    used_paths = []
    for path in paths:
        text = _read_text_from_file(path)
        if text.strip():
            texts.append(text)
            used_paths.append(path)
    return "\n\n".join(texts).strip(), used_paths


def _build_gemini_summary_prompt(content):
    return f"""
Bạn là một trợ lý học thuật cao cấp. Hãy tóm tắt nội dung báo cáo thực tập/đồ án sau đây để giảng viên phản biện có cái nhìn nhanh nhất.

Yêu cầu tóm tắt theo các mục:
1. Tên đề tài & Mục tiêu chính.
2. Các công nghệ/phương pháp sử dụng.
3. Kết quả đạt được (Sản phẩm/Số liệu).
4. Nhận định nhanh: Ưu điểm và những điểm cần chất vấn thêm (nếu có).

Nội dung báo cáo:
---
{content}
---
""".strip()


def map_role(role):
    if role == "SV":
        return "sv"
    if role == "GV":
        return "gv"
    if role == "TBM":
        return "bm"
    return role.lower()


def build_email(ma):
    if not ma:
        return None
    return f"{ma.lower()}@hcmute.edu.vn"


def parse_linh_vuc(value):
    if not value:
        return {"mangDeTai": "", "tenCongTy": ""}
    if "||" not in value:
        return {"mangDeTai": value, "tenCongTy": ""}
    parts = value.split("||", 1)
    return {"mangDeTai": parts[0], "tenCongTy": parts[1]}


def _sv_majors_from_row(sv_row):
    lv = sv_row["linh_vuc"] or ""
    return [x.strip() for x in lv.split(",") if x.strip()]


def kltn_major_from_dang_ky(linh_vuc_raw):
    """Mảng/lĩnh vực đề tài KLTN lưu trong dang_ky.linh_vuc (phần trước || nếu có)."""
    meta = parse_linh_vuc(linh_vuc_raw or "")
    return (meta.get("mangDeTai") or "").strip()


def user_covers_kltn_major(user_row, major):
    if not major:
        return True
    parts = [x.strip() for x in (user_row["linh_vuc"] or "").split(",") if x.strip()]
    return major in parts


def assert_kltn_assignees_match_major(conn, major, user_ids):
    """TBM: mọi GV phân công phải có lĩnh vực trùng mảng đề tài."""
    if not major:
        return True, None
    seen = set()
    for mid in user_ids:
        if mid is None:
            continue
        try:
            uid = int(mid)
        except (TypeError, ValueError):
            return False, "ID thành viên không hợp lệ"
        if uid in seen:
            continue
        seen.add(uid)
        row = conn.execute(
            "SELECT id, ho_ten, linh_vuc FROM users WHERE id = ?",
            (uid,),
        ).fetchone()
        if not row:
            return False, "Không tìm thấy người dùng id=%s" % uid
        if not user_covers_kltn_major(row, major):
            return False, (
                "GV %s không cùng lĩnh vực với đề tài (%s). "
                "Chỉ được phân công giảng viên có chuyên môn trùng mảng đăng ký."
                % (row["ho_ten"], major)
            )
    return True, None


def normalize_sv_slot_he(sv_row):
    """Hệ SV dùng để chọn pool gv_slot: CLC hoặc DaiTra (mặc định Đại trà nếu trống)."""
    if not sv_row:
        return "DaiTra"
    h = (sv_row["he_dao_tao"] or "").strip()
    return "CLC" if h == "CLC" else "DaiTra"


def dot_matches_student(conn, dot_id, sv_row):
    """SV chỉ đăng ký đợt đúng ngành (dot.nganh); đợt không phân theo Đại trà/CLC."""
    try:
        did = int(dot_id)
    except (TypeError, ValueError):
        return False, "dot_id không hợp lệ"
    dot = conn.execute("SELECT * FROM dot WHERE id = ?", (did,)).fetchone()
    if not dot:
        return False, "Không có đợt đăng ký này"
    dot_nganh = (dot["nganh"] or "").strip()
    if dot_nganh:
        majors = _sv_majors_from_row(sv_row)
        if majors and dot_nganh not in majors:
            return False, "Đợt không khớp ngành/chuyên ngành của bạn"
    return True, None


def map_status_for_ui(loai, trang_thai):
    if loai == "BCTT":
        if trang_thai == "dong_y":
            return "gv_xac_nhan"
    if loai == "KLTN":
        if trang_thai == "dong_y":
            return "thuc_hien"
    return trang_thai


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user_id = session.get("user_id") or request.headers.get("X-User-Id")
        if not user_id:
            return fail("Chưa đăng nhập", 401)
        return fn(*args, **kwargs)
    return wrapper


def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = session.get("role") or request.headers.get("X-User-Role")
            if not role:
                return fail("Chưa đăng nhập", 401)
            role = str(role).upper()
            if role not in roles:
                return fail("Không có quyền truy cập", 403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def get_current_user(conn):
    uid = session.get("user_id") or request.headers.get("X-User-Id")
    return conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def _hoi_dong_ids(conn, dang_ky_id):
    row = conn.execute(
        """
        SELECT file_path FROM nop_bai
        WHERE dang_ky_id = ? AND loai_file = 'hoi_dong'
        ORDER BY id DESC LIMIT 1
        """,
        (dang_ky_id,),
    ).fetchone()
    if not row or not row["file_path"]:
        return None
    ids = [int(x) for x in row["file_path"].split("|") if x.strip().isdigit()]
    if len(ids) < 3:
        return None
    return {"ct": ids[0], "tk": ids[1], "tv": ids[2:]}


def _can_score_kltn(conn, dang_ky_id, gv_id, vai_tro):
    reg = conn.execute("SELECT gv_id, loai FROM dang_ky WHERE id = ?", (dang_ky_id,)).fetchone()
    if not reg or reg["loai"] != "KLTN":
        return False
    if vai_tro == "HD":
        return reg["gv_id"] == gv_id
    if vai_tro == "PB":
        row = conn.execute(
            """
            SELECT file_path FROM nop_bai
            WHERE dang_ky_id = ? AND loai_file = 'phanbien_gv'
            ORDER BY id DESC LIMIT 1
            """,
            (dang_ky_id,),
        ).fetchone()
        if not row:
            return False
        pb_ids = [int(x) for x in str(row["file_path"]).split("|") if x.strip().isdigit()]
        return gv_id in pb_ids
    hd = _hoi_dong_ids(conn, dang_ky_id)
    if not hd:
        return False
    if vai_tro == "CT":
        return hd["ct"] == gv_id
    if vai_tro == "TV":
        return gv_id in hd["tv"]
    return False


def serialize_user(row):
    return {
        "id": row["id"],
        "ma": row["ma"],
        "email": build_email(row["ma"]),
        "ho_ten": row["ho_ten"],
        "name": row["ho_ten"],
        "role_raw": row["role"],
        "role": map_role(row["role"]),
        "linh_vuc": row["linh_vuc"] or "",
        "heDaoTao": (row["he_dao_tao"] or "").strip(),
    }


def fetch_bootstrap(conn):
    users = conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall()
    dots = conn.execute("SELECT * FROM dot ORDER BY id ASC").fetchall()
    slots = conn.execute("SELECT * FROM gv_slot ORDER BY id ASC").fetchall()
    regs = conn.execute(
        """
        SELECT dk.*, sv.ma AS sv_ma, gv.ma AS gv_ma, d.ten_dot AS ten_dot
        FROM dang_ky dk
        JOIN users sv ON sv.id = dk.sv_id
        JOIN users gv ON gv.id = dk.gv_id
        JOIN dot d ON d.id = dk.dot_id
        ORDER BY dk.id DESC
        """
    ).fetchall()
    scores = conn.execute("SELECT * FROM cham_diem ORDER BY id ASC").fetchall()
    uploads = conn.execute("SELECT * FROM nop_bai ORDER BY uploaded_at DESC").fetchall()

    user_map = {u["id"]: serialize_user(u) for u in users}
    gv_slots_payload = []
    for s in slots:
        hek = (s["he_dao_tao"] or "").strip() or "DaiTra"
        gv_slots_payload.append(
            {
                "id": s["id"],
                "gvId": s["gv_id"],
                "dotId": str(s["dot_id"]),
                "heDaoTao": hek,
                "slotConLai": s["slot_con_lai"],
                "quota": s["quota"],
                "duyetTbm": bool(s["duyet_tbm"]),
            }
        )

    dot_data = []
    for d in dots:
        dot_data.append(
            {
                "id": str(d["id"]),
                "ten": d["ten_dot"],
                "loai": d["loai"],
                "trangThai": "dang_mo" if d["trang_thai"] == "mo" else "dong",
                "batDau": d["han_dang_ky"],
                "ketThuc": d["han_nop"],
                "heDaoTao": (d["he_dao_tao"] or "").strip(),
                "nganh": (d["nganh"] or "").strip(),
            }
        )

    score_map = {}
    tv_scores_by_dk = {}
    for s in scores:
        score_map.setdefault(s["dang_ky_id"], {})[s["vai_tro"]] = s
        if s["vai_tro"] == "TV":
            tv_scores_by_dk.setdefault(s["dang_ky_id"], []).append(s)

    upload_map = {}
    for u in uploads:
        dk = u["dang_ky_id"]
        lf = u["loai_file"]
        upload_map.setdefault(dk, {})
        if lf not in upload_map[dk]:
            upload_map[dk][lf] = u["file_path"]

    bctt_list = []
    kltn_list = []
    for r in regs:
        meta = parse_linh_vuc(r["linh_vuc"])
        record = {
            "id": f"{r['loai'].lower()}{r['id']}",
            "dangKyId": r["id"],
            "svEmail": build_email(r["sv_ma"]),
            "tenDot": r["ten_dot"] if "ten_dot" in r.keys() else "",
            "tenDeTai": r["ten_de_tai"],
            "mangDeTai": meta["mangDeTai"],
            "gvEmail": build_email(r["gv_ma"]),
            "gvHDEmail": build_email(r["gv_ma"]),
            "dotId": str(r["dot_id"]),
            "trangThai": map_status_for_ui(r["loai"], r["trang_thai"]),
            "ngayDangKy": datetime.now().strftime("%Y-%m-%d"),
        }
        if r["loai"] == "BCTT":
            sc_bctt = score_map.get(r["id"], {}).get("BCTT")
            record["tenCongTy"] = meta["tenCongTy"]
            record["fileBC"] = upload_map.get(r["id"], {}).get("bctt_baocao")
            record["fileXacNhan"] = upload_map.get(r["id"], {}).get("bctt_xacnhan")
            record["fileTurnitinBCTT"] = upload_map.get(r["id"], {}).get("turnitin_bctt")
            record["diemBCTT"] = sc_bctt["diem"] if sc_bctt else None
            record["nhanXetBCTT"] = sc_bctt["nhan_xet"] if sc_bctt else ""
            bctt_list.append(record)
        else:
            sc = score_map.get(r["id"], {})
            pb_raw = upload_map.get(r["id"], {}).get("phanbien_gv")
            gv_pb_email = None
            if pb_raw:
                try:
                    pb_user = user_map.get(int(pb_raw))
                    gv_pb_email = pb_user["email"] if pb_user else None
                except ValueError:
                    gv_pb_email = None
            hoi_dong_raw = upload_map.get(r["id"], {}).get("hoi_dong")
            hoi_dong = None
            if hoi_dong_raw:
                ids = [int(id_str) for id_str in hoi_dong_raw.split('|') if id_str.isdigit()]
                if len(ids) >= 3:
                    ct_user = user_map.get(ids[0])
                    tk_user = user_map.get(ids[1])
                    tv_users = [user_map.get(uid) for uid in ids[2:]]
                    if ct_user and tk_user and all(tv_users):
                        hoi_dong = {
                            "ct": ct_user["email"],
                            "tk": tk_user["email"],
                            "tv": [u["email"] for u in tv_users],
                        }
            record["gvPBEmail"] = gv_pb_email
            record["pbAccepted"] = bool(upload_map.get(r["id"], {}).get("pb_accepted"))
            record["hoiDong"] = hoi_dong
            # KLTN files: hỗ trợ cả bài Word + PDF
            file_map = upload_map.get(r["id"], {})
            record["fileBai"] = file_map.get("kltn_bai_pdf") or file_map.get("kltn_bai")
            record["fileBaiWord"] = file_map.get("kltn_bai_word")
            record["fileTurnitin"] = upload_map.get(r["id"], {}).get("turnitin")
            record["fileBaiChinhSua"] = upload_map.get(r["id"], {}).get("kltn_chinhsua")
            record["fileGiaiTrinh"] = upload_map.get(r["id"], {}).get("bien_ban_giai_trinh")
            record["diemHD"] = sc["HD"]["diem"] if sc.get("HD") else None
            record["diemPB"] = sc["PB"]["diem"] if sc.get("PB") else None
            record["diemBB"] = sc["CT"]["diem"] if sc.get("CT") else None
            pb_row = sc.get("PB")
            record["pbNote"] = (pb_row["nhan_xet"] or "") if pb_row else ""
            record["pbCauHoi"] = (pb_row["cau_hoi"] or "") if pb_row else ""
            ct_row = sc.get("CT")
            record["ctNote"] = (ct_row["nhan_xet"] or "") if ct_row else ""
            record["ctCauHoi"] = (ct_row["cau_hoi"] or "") if ct_row else ""
            record["bbNote"] = record["ctNote"]
            record["tkBienBan"] = upload_map.get(r["id"], {}).get("bien_ban_tk") or ""
            # Ghi nhận nhận xét của GVHD để GV phản biện có thể xem
            record["hdNote"] = sc["HD"]["nhan_xet"] if sc.get("HD") else ""
            record["xacNhanGVHD"] = bool(upload_map.get(r["id"], {}).get("xac_nhan_gvhd"))
            record["xacNhanCTHD"] = bool(upload_map.get(r["id"], {}).get("xac_nhan_cthd"))
            record["tuChoiGVHD"] = upload_map.get(r["id"], {}).get("tu_choi_gvhd")
            record["tuChoiCTHD"] = upload_map.get(r["id"], {}).get("tu_choi_cthd")
            # Nhiều dòng chấm vai trò TV (mỗi thành viên một bản ghi)
            record["tvScores"] = []
            for s in tv_scores_by_dk.get(r["id"], []):
                gu = user_map.get(s["gv_id"])
                if gu:
                    record["tvScores"].append(
                        {
                            "email": gu["email"],
                            "diem": s["diem"],
                            "nhanXet": s["nhan_xet"] or "",
                        }
                    )
            kltn_list.append(record)

    bctt_dots = [d for d in dots if d["loai"] == "BCTT"]
    open_bctt_dot_ids = [d["id"] for d in bctt_dots if d["trang_thai"] == "mo"]

    def gv_bctt_open_slots_aggregate(gv_uid):
        """Tổng slot BCTT đang mở (mọi hệ) — chỉ để dashboard GV/TBM; chọn GV theo đợt dùng gvSlots + hệ SV."""
        user_slots = [s for s in slots if s["gv_id"] == gv_uid]
        bctt_open = [s for s in user_slots if s["dot_id"] in open_bctt_dot_ids]
        if not bctt_open:
            return None
        return {
            "slot_con_lai": sum(s["slot_con_lai"] for s in bctt_open),
            "quota": sum(s["quota"] for s in bctt_open),
            "duyet_tbm": all(bool(s["duyet_tbm"]) for s in bctt_open),
        }

    mapped_users = []
    for u in users:
        role = map_role(u["role"])
        user_data = {
            "id": u["id"],
            "ma": u["ma"],
            "email": build_email(u["ma"]),
            "password": u["mat_khau"],
            "name": u["ho_ten"],
            "role": role,
            "mssv": u["ma"] if role == "sv" else None,
            "msgv": u["ma"] if role in ("gv", "bm") else None,
            "khoa": "",
            "chuyenMon": [x.strip() for x in (u["linh_vuc"] or "").split(",") if x.strip()],
            "heDaoTao": (u["he_dao_tao"] or "").strip(),
        }
        if role in ("gv", "bm"):
            agg = gv_bctt_open_slots_aggregate(u["id"])
            user_data["quota"] = agg["slot_con_lai"] if agg else 0
            user_data["quota_max"] = agg["quota"] if agg else 0
            user_data["slot_con_lai"] = agg["slot_con_lai"] if agg else 0
            user_data["slotOpen"] = agg["duyet_tbm"] if agg else True
        else:
            user_data["quota"] = 0
            user_data["quota_max"] = 0
            user_data["slot_con_lai"] = 0
            user_data["slotOpen"] = True
        mapped_users.append(user_data)

    return {
        "users": mapped_users,
        "dotDangKy": dot_data,
        "bcttList": bctt_list,
        "kltnList": kltn_list,
        "gvSlots": gv_slots_payload,
    }


@app.errorhandler(413)
def file_too_large(_):
    return fail("File vượt quá 20MB", 400)


@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    ma = (data.get("ma") or "").strip()
    mat_khau = data.get("mat_khau")
    if not ma or not mat_khau:
        return fail("Thiếu mã đăng nhập hoặc mật khẩu", 400)

    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE ma = ? AND mat_khau = ?",
        (ma.upper(), mat_khau),
    ).fetchone()
    conn.close()
    if not user:
        return fail("Sai tên đăng nhập hoặc mật khẩu", 401)

    session["user_id"] = user["id"]
    session["role"] = user["role"]
    return ok("Đăng nhập thành công", {"user": serialize_user(user)})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return ok("Đăng xuất thành công")


@app.route("/api/me", methods=["GET"])
@login_required
def me():
    conn = get_db()
    user = get_current_user(conn)
    conn.close()
    return ok("Lấy thông tin phiên đăng nhập", {"user": serialize_user(user)})


@app.route("/api/me/password", methods=["POST"])
@login_required
def change_my_password():
    data = request.json or {}
    old_password = data.get("old_password") or data.get("mat_khau_cu")
    new_password = data.get("new_password") or data.get("mat_khau_moi")
    confirm_password = data.get("confirm_password") or data.get("xac_nhan_mat_khau")

    if old_password is None or new_password is None:
        return fail("Thiếu mật khẩu hiện tại hoặc mật khẩu mới", 400)

    old_password = str(old_password)
    new_password = str(new_password)
    confirm_password = str(confirm_password) if confirm_password is not None else None

    if confirm_password is not None and new_password != confirm_password:
        return fail("Mật khẩu xác nhận không khớp", 400)
    if len(new_password) < 6:
        return fail("Mật khẩu tối thiểu 6 ký tự", 400)

    conn = get_db()
    user = get_current_user(conn)
    if not user:
        conn.close()
        return fail("Không tìm thấy người dùng", 401)
    if str(user["mat_khau"]) != old_password:
        conn.close()
        return fail("Mật khẩu hiện tại không đúng", 400)
    if old_password == new_password:
        conn.close()
        return fail("Mật khẩu mới phải khác mật khẩu hiện tại", 400)

    conn.execute(
        "UPDATE users SET mat_khau = ? WHERE id = ?",
        (new_password, user["id"]),
    )
    conn.commit()
    conn.close()
    return ok("Cập nhật mật khẩu thành công")


@app.route("/api/bootstrap", methods=["GET"])
@login_required
def bootstrap():
    conn = get_db()
    data = fetch_bootstrap(conn)

    # Lọc theo bộ môn nếu là TBM
    role = session.get("role") or request.headers.get("X-User-Role", "")
    if str(role).upper() == "TBM":
        uid = session.get("user_id") or request.headers.get("X-User-Id")
        tbm = conn.execute("SELECT linh_vuc FROM users WHERE id = ?", (uid,)).fetchone()
        if tbm and tbm["linh_vuc"]:
            nganh_list = [x.strip() for x in tbm["linh_vuc"].split(",") if x.strip()]
            def thuoc_nganh(ten_dot):
                return any(n in (ten_dot or "") for n in nganh_list)
            data["bcttList"] = [b for b in data["bcttList"] if thuoc_nganh(b.get("tenDot", ""))]
            data["kltnList"] = [k for k in data["kltnList"] if thuoc_nganh(k.get("tenDot", ""))]

    conn.close()
    return ok("Lấy dữ liệu giao diện", data)


@app.route("/api/bctt/register", methods=["POST"])
@role_required("SV")
def register_bctt():
    data = request.json or {}
    ten = (data.get("ten_de_tai") or "").strip()
    linh_vuc = (data.get("linh_vuc") or "").strip()
    cong_ty = (data.get("ten_cong_ty") or "").strip()
    gv_id = data.get("gv_id")
    dot_id = data.get("dot_id")
    if not all([ten, linh_vuc, cong_ty, gv_id, dot_id]):
        return fail("Thiếu thông tin đăng ký BCTT", 400)

    conn = get_db()
    sv = get_current_user(conn)
    exists = conn.execute(
        "SELECT id FROM dang_ky WHERE sv_id = ? AND loai = 'BCTT'",
        (sv["id"],),
    ).fetchone()
    if exists:
        conn.close()
        return fail("Bạn đã đăng ký BCTT", 400)

    ok_dot, dot_err = dot_matches_student(conn, dot_id, sv)
    if not ok_dot:
        conn.close()
        return fail(dot_err, 400)

    sv_he = normalize_sv_slot_he(sv)
    slot = conn.execute(
        "SELECT * FROM gv_slot WHERE gv_id = ? AND dot_id = ? AND he_dao_tao = ?",
        (gv_id, dot_id, sv_he),
    ).fetchone()
    if not slot:
        conn.close()
        return fail("Không có slot GV cho hệ (%s) của bạn trong đợt này" % sv_he, 400)
    if slot["duyet_tbm"] == 1 and slot["slot_con_lai"] <= 0:
        conn.close()
        return fail("GV đã hết slot hướng dẫn (%s) trong đợt này" % sv_he, 400)

    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO dang_ky (sv_id, gv_id, dot_id, loai, ten_de_tai, linh_vuc, trang_thai)
        VALUES (?, ?, ?, 'BCTT', ?, ?, 'cho_duyet')
        """,
        (sv["id"], gv_id, dot_id, ten, f"{linh_vuc}||{cong_ty}"),
    )
    # SV luôn đăng ký thành công và vào trạng thái chờ duyệt.
    # Chỉ trừ slot khi slot đã được TBM mở chính thức.
    conn.commit()
    conn.close()
    return ok("Đăng ký BCTT thành công")


@app.route("/api/kltn/register", methods=["POST"])
@role_required("SV")
def register_kltn():
    data = request.json or {}
    ten = (data.get("ten_de_tai") or "").strip()
    linh_vuc = (data.get("linh_vuc") or "").strip()
    gv_id = data.get("gv_id")
    dot_id = data.get("dot_id")
    if not all([ten, linh_vuc, gv_id, dot_id]):
        return fail("Thiếu thông tin đăng ký KLTN", 400)

    conn = get_db()
    sv = get_current_user(conn)
    passed = conn.execute(
        "SELECT id FROM dang_ky WHERE sv_id = ? AND loai = 'BCTT' AND trang_thai = 'pass'",
        (sv["id"],),
    ).fetchone()
    if not passed:
        conn.close()
        return fail("Bạn chỉ được đăng ký KLTN khi BCTT = pass", 400)

    existed = conn.execute(
        "SELECT id FROM dang_ky WHERE sv_id = ? AND loai = 'KLTN'",
        (sv["id"],),
    ).fetchone()
    if existed:
        conn.close()
        return fail("Bạn đã đăng ký KLTN", 400)

    ok_dot, dot_err = dot_matches_student(conn, dot_id, sv)
    if not ok_dot:
        conn.close()
        return fail(dot_err, 400)

    conn.execute(
        """
        INSERT INTO dang_ky (sv_id, gv_id, dot_id, loai, ten_de_tai, linh_vuc, trang_thai)
        VALUES (?, ?, ?, 'KLTN', ?, ?, 'thuc_hien')
        """,
        (sv["id"], gv_id, dot_id, ten, linh_vuc),
    )
    conn.commit()
    conn.close()
    return ok("Đăng ký KLTN thành công")


@app.route("/api/bctt/submit", methods=["POST"])
@role_required("SV")
def submit_bctt():
    data = request.json or {}
    dang_ky_id = data.get("dang_ky_id")
    if not dang_ky_id:
        return fail("Thiếu dang_ky_id", 400)
    conn = get_db()
    sv = get_current_user(conn)
    reg = conn.execute(
        "SELECT * FROM dang_ky WHERE id = ? AND sv_id = ? AND loai = 'BCTT'",
        (dang_ky_id, sv["id"]),
    ).fetchone()
    if not reg:
        conn.close()
        return fail("Không tìm thấy đăng ký BCTT", 404)
    if reg["trang_thai"] not in ("gv_xac_nhan", "cho_cham"):
        conn.close()
        return fail("BCTT chưa ở trạng thái được nộp hồ sơ", 400)
    files = conn.execute(
        "SELECT loai_file FROM nop_bai WHERE dang_ky_id = ? AND loai_file IN ('bctt_baocao','bctt_xacnhan')",
        (dang_ky_id,),
    ).fetchall()
    types = {f["loai_file"] for f in files}
    if "bctt_baocao" not in types or "bctt_xacnhan" not in types:
        conn.close()
        return fail("Cần nộp đủ báo cáo BCTT và giấy xác nhận", 400)
    conn.execute("UPDATE dang_ky SET trang_thai = 'cho_cham' WHERE id = ?", (dang_ky_id,))
    conn.commit()
    conn.close()
    return ok("Đã nộp hồ sơ BCTT, chờ GV chấm")


@app.route("/api/bctt/grade", methods=["POST"])
@role_required("GV")
def grade_bctt():
    data = request.json or {}
    dang_ky_id = data.get("dang_ky_id")
    diem = data.get("diem")
    nhan_xet = (data.get("nhan_xet") or "").strip()
    if diem is None:
        return fail("Thiếu điểm BCTT", 400)
    try:
        diem = float(diem)
    except ValueError:
        return fail("Điểm không hợp lệ", 400)
    if diem < 0 or diem > 10:
        return fail("Điểm phải từ 0 đến 10", 400)
    conn = get_db()
    gv = get_current_user(conn)
    reg = conn.execute(
        "SELECT * FROM dang_ky WHERE id = ? AND gv_id = ? AND loai = 'BCTT'",
        (dang_ky_id, gv["id"]),
    ).fetchone()
    if not reg:
        conn.close()
        return fail("Không tìm thấy BCTT cần chấm", 404)
    if reg["trang_thai"] != "cho_cham":
        conn.close()
        return fail("BCTT chưa ở trạng thái chờ chấm", 400)
    has_turnitin = conn.execute(
        "SELECT id FROM nop_bai WHERE dang_ky_id = ? AND loai_file = 'turnitin_bctt' LIMIT 1",
        (dang_ky_id,),
    ).fetchone()
    if not has_turnitin:
        conn.close()
        return fail("Cần upload file Turnitin BCTT trước khi chấm", 400)
    old = conn.execute(
        "SELECT id FROM cham_diem WHERE dang_ky_id = ? AND gv_id = ? AND vai_tro = 'BCTT'",
        (dang_ky_id, gv["id"]),
    ).fetchone()
    if old:
        conn.execute(
            "UPDATE cham_diem SET diem = ?, nhan_xet = ? WHERE id = ?",
            (diem, nhan_xet, old["id"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO cham_diem (dang_ky_id, gv_id, vai_tro, diem, nhan_xet, cau_hoi)
            VALUES (?, ?, 'BCTT', ?, ?, '')
            """,
            (dang_ky_id, gv["id"], diem, nhan_xet),
        )
    result = "pass" if diem >= 4 else "fail"
    conn.execute("UPDATE dang_ky SET trang_thai = ? WHERE id = ?", (result, dang_ky_id))
    conn.commit()
    conn.close()
    return ok("Chấm BCTT thành công")


@app.route("/api/kltn/submit", methods=["POST"])
@role_required("SV")
def submit_kltn():
    data = request.json or {}
    dang_ky_id = data.get("dang_ky_id")
    if not dang_ky_id:
        return fail("Thiếu dang_ky_id", 400)
    conn = get_db()
    sv = get_current_user(conn)
    reg = conn.execute(
        "SELECT * FROM dang_ky WHERE id = ? AND sv_id = ? AND loai = 'KLTN'",
        (dang_ky_id, sv["id"]),
    ).fetchone()
    if not reg:
        conn.close()
        return fail("Không tìm thấy đăng ký KLTN", 404)
    if reg["trang_thai"] != "thuc_hien":
        conn.close()
        return fail("KLTN chưa ở trạng thái thực hiện", 400)
    # Yêu cầu SV nộp đủ 2 file: Word và PDF
    files = conn.execute(
        """
        SELECT loai_file FROM nop_bai
        WHERE dang_ky_id = ? AND loai_file IN ('kltn_bai_pdf','kltn_bai_word')
        """,
        (dang_ky_id,),
    ).fetchall()
    types = {f["loai_file"] for f in files}
    if "kltn_bai_pdf" not in types or "kltn_bai_word" not in types:
        conn.close()
        return fail("Cần upload đủ file Word và PDF của bài KLTN trước khi nộp", 400)
    conn.execute("UPDATE dang_ky SET trang_thai = 'cham_diem' WHERE id = ?", (dang_ky_id,))
    conn.commit()
    conn.close()
    return ok("Đã nộp KLTN, chờ chấm điểm")


@app.route("/api/kltn/revision-approve", methods=["POST"])
@role_required("GV")
def approve_kltn_revision():
    data = request.json or {}
    dang_ky_id = data.get("dang_ky_id")
    step = data.get("step")
    dong_y = data.get("dong_y", True)
    if step not in ("gvhd", "cthd"):
        return fail("Step không hợp lệ", 400)
    conn = get_db()
    gv = get_current_user(conn)
    reg = conn.execute("SELECT * FROM dang_ky WHERE id = ? AND loai = 'KLTN'", (dang_ky_id,)).fetchone()
    if not reg:
        conn.close()
        return fail("Không tìm thấy KLTN", 404)
    uploads = conn.execute(
        "SELECT loai_file FROM nop_bai WHERE dang_ky_id = ? AND loai_file IN ('kltn_chinhsua','bien_ban_giai_trinh')",
        (dang_ky_id,),
    ).fetchall()
    up_types = {u["loai_file"] for u in uploads}
    if "kltn_chinhsua" not in up_types or "bien_ban_giai_trinh" not in up_types:
        conn.close()
        return fail("SV chưa nộp đủ bài chỉnh sửa và biên bản giải trình", 400)
    if step == "gvhd":
        if gv["id"] != reg["gv_id"]:
            conn.close()
            return fail("Chỉ GVHD mới được duyệt bước này", 403)
        conn.execute(
            "DELETE FROM nop_bai WHERE dang_ky_id = ? AND loai_file IN ('xac_nhan_gvhd','xac_nhan_cthd')",
            (dang_ky_id,),
        )
        if not dong_y:
            # Xóa file cũ để SV phải nộp lại bản mới
            conn.execute(
                "DELETE FROM nop_bai WHERE dang_ky_id = ? AND loai_file IN ('kltn_chinhsua','bien_ban_giai_trinh','xac_nhan_gvhd','xac_nhan_cthd')",
                (dang_ky_id,),
            )
            # Lưu lý do từ chối để SV xem
            ly_do = data.get("ly_do", "").strip()
            conn.execute(
                "INSERT INTO nop_bai (dang_ky_id, loai_file, file_path) VALUES (?, 'tu_choi_gvhd', ?)",
                (dang_ky_id, ly_do),
            )

            conn.execute(
                """
                INSERT INTO thong_bao (nguoi_nhan_id, nguoi_gui_id, dang_ky_id, loai, noi_dung)
                VALUES (?, ?, ?, 'tu_choi_gvhd', ?)
                """,
                (reg["sv_id"], gv["id"], dang_ky_id,
                 ly_do if ly_do else "GVHD yêu cầu bạn chỉnh sửa và nộp lại bài KLTN")
            )
            conn.commit()
            conn.close()
            return ok("GVHD đã từ chối; sinh viên cần chỉnh sửa và nộp lại")
        conn.execute(
            "INSERT INTO nop_bai (dang_ky_id, loai_file, file_path) VALUES (?, 'xac_nhan_gvhd', ?)",
            (dang_ky_id, str(gv["id"])),
        )
    else:
        hd = _hoi_dong_ids(conn, dang_ky_id)
        if not hd or hd["ct"] != gv["id"]:
            conn.close()
            return fail("Chỉ Chủ tịch hội đồng mới được duyệt bước này", 403)
        has_gvhd = conn.execute(
            "SELECT id FROM nop_bai WHERE dang_ky_id = ? AND loai_file = 'xac_nhan_gvhd' LIMIT 1",
            (dang_ky_id,),
        ).fetchone()
        if not has_gvhd:
            conn.close()
            return fail("GVHD chưa duyệt chỉnh sửa — Chủ tịch HĐ chưa được thao tác", 400)
        conn.execute(
            "DELETE FROM nop_bai WHERE dang_ky_id = ? AND loai_file = 'xac_nhan_cthd'",
            (dang_ky_id,),
        )
        if not dong_y:
            conn.execute(
                "DELETE FROM nop_bai WHERE dang_ky_id = ? AND loai_file IN ('kltn_chinhsua','bien_ban_giai_trinh','xac_nhan_gvhd','xac_nhan_cthd')",
                (dang_ky_id,),
            )
            ly_do = data.get("ly_do", "").strip()
            conn.execute(
                "INSERT INTO nop_bai (dang_ky_id, loai_file, file_path) VALUES (?, 'tu_choi_cthd', ?)",
                (dang_ky_id, ly_do),
            )

            conn.execute(
                """
                INSERT INTO thong_bao (nguoi_nhan_id, nguoi_gui_id, dang_ky_id, loai, noi_dung)
                VALUES (?, ?, ?, 'tu_choi_cthd', ?)
                """,
                (reg["sv_id"], gv["id"], dang_ky_id,
                 ly_do if ly_do else "Chủ tịch HĐ yêu cầu bạn chỉnh sửa và nộp lại bài KLTN")
            )
            conn.commit()
            conn.close()
            return ok("Chủ tịch HĐ đã từ chối; sinh viên cần chỉnh sửa và nộp lại")
        conn.execute(
            "INSERT INTO nop_bai (dang_ky_id, loai_file, file_path) VALUES (?, 'xac_nhan_cthd', ?)",
            (dang_ky_id, str(gv["id"])),
        )
        conn.execute("UPDATE dang_ky SET trang_thai = 'hoan_thanh' WHERE id = ?", (dang_ky_id,))
    conn.commit()
    conn.close()
    return ok("Duyệt chỉnh sửa thành công")


@app.route("/api/kltn/bien-ban-tk", methods=["POST"])
@role_required("GV")
def save_bien_ban_tk():
    data = request.json or {}
    dang_ky_id = data.get("dang_ky_id")
    noi_dung = data.get("noi_dung")
    if noi_dung is None:
        noi_dung = ""
    else:
        noi_dung = str(noi_dung)
    if not dang_ky_id:
        return fail("Thiếu dang_ky_id", 400)
    conn = get_db()
    gv = get_current_user(conn)
    hd = _hoi_dong_ids(conn, dang_ky_id)
    if not hd or hd["tk"] != gv["id"]:
        conn.close()
        return fail("Chỉ Thư ký hội đồng được lưu biên bản này", 403)
    conn.execute("DELETE FROM nop_bai WHERE dang_ky_id = ? AND loai_file = 'bien_ban_tk'", (dang_ky_id,))
    conn.execute(
        "INSERT INTO nop_bai (dang_ky_id, loai_file, file_path) VALUES (?, 'bien_ban_tk', ?)",
        (dang_ky_id, noi_dung),
    )
    conn.commit()
    conn.close()
    return ok("Đã lưu nội dung biên bản (Thư ký)")


@app.route("/api/bctt/approve", methods=["POST"])
@role_required("GV")
def approve_bctt():
    data = request.json or {}
    ids = data.get("dang_ky_ids") or []
    action = data.get("action")
    
    if action not in ("dong_y", "tu_choi"):
        return fail("Action không hợp lệ", 400)
    if not ids:
        return fail("Danh sách đăng ký trống", 400)

    conn = get_db()
    gv = get_current_user(conn)
    cursor = conn.cursor()

    # TRƯỜNG HỢP 1: TỪ CHỐI (Không ảnh hưởng Quota, có thể update hàng loạt)
    if action == "tu_choi":
        placeholders = ",".join(["?"] * len(ids))
        cursor.execute(
            f"""
            UPDATE dang_ky SET trang_thai = 'tu_choi'
            WHERE id IN ({placeholders}) AND gv_id = ? AND loai = 'BCTT'
            """,
            [*ids, gv["id"]],
        )
        success_count = cursor.rowcount

    # TRƯỜNG HỢP 2: ĐỒNG Ý (Phải check Quota TỪNG NGƯỜI một)
    else:
        success_count = 0
        for dk_id in ids:
            # 1. Lấy thông tin đăng ký (Bảo mật: Chỉ lấy đúng đề tài của GV này và đang chờ duyệt)
            dk = cursor.execute(
                """
                SELECT dk.dot_id, dk.trang_thai, sv.he_dao_tao
                FROM dang_ky dk
                JOIN users sv ON sv.id = dk.sv_id
                WHERE dk.id = ? AND dk.gv_id = ? AND dk.loai = 'BCTT'
                """,
                (dk_id, gv["id"]),
            ).fetchone()

            if not dk or dk["trang_thai"] != "cho_duyet":
                continue # Bỏ qua nếu ID không hợp lệ hoặc đã duyệt rồi

            sv_he = normalize_sv_slot_he(dk)
            slot = cursor.execute(
                "SELECT id, slot_con_lai FROM gv_slot WHERE gv_id = ? AND dot_id = ? AND he_dao_tao = ?",
                (gv["id"], dk["dot_id"], sv_he),
            ).fetchone()

            # 3. NẾU CÒN SLOT -> Mới duyệt và trừ Quota
            if slot and slot["slot_con_lai"] > 0:
                cursor.execute("UPDATE dang_ky SET trang_thai = 'gv_xac_nhan' WHERE id = ?", (dk_id,))
                cursor.execute("UPDATE gv_slot SET slot_con_lai = slot_con_lai - 1 WHERE id = ?", (slot["id"],))
                success_count += 1

    conn.commit()
    conn.close()

    # Báo lỗi nếu bấm duyệt nhưng không thành công do hết Quota
    if action == "dong_y" and success_count == 0 and len(ids) > 0:
        return fail("Không thể duyệt! Quota hướng dẫn của bạn đã hết.", 400)

    return ok(f"Đã xử lý thành công {success_count} đề tài BCTT.")


@app.route("/api/bctt/rename", methods=["POST"])
@role_required("GV")
def rename_bctt():
    data = request.json or {}
    dang_ky_id = data.get("dang_ky_id")
    new_name = (data.get("ten_de_tai") or "").strip()
    if not dang_ky_id or not new_name:
        return fail("Thiếu dữ liệu đổi tên đề tài", 400)

    conn = get_db()
    gv = get_current_user(conn)
    reg = conn.execute(
        "SELECT * FROM dang_ky WHERE id = ? AND gv_id = ? AND loai = 'BCTT'",
        (dang_ky_id, gv["id"]),
    ).fetchone()
    if not reg:
        conn.close()
        return fail("Không tìm thấy đề tài BCTT cần đổi tên", 404)

    conn.execute(
        "UPDATE dang_ky SET ten_de_tai = ?, trang_thai = 'gv_xac_nhan' WHERE id = ?",
        (new_name, dang_ky_id),
    )
    conn.commit()
    conn.close()
    return ok("Đã đổi tên và xác nhận đề tài BCTT")


@app.route("/api/gv-slot/duyet", methods=["POST"])
@role_required("TBM")
def duyet_slot():
    data = request.json or {}
    slot_id = data.get("slot_id")
    gv_id = data.get("gv_id")
    dot_id = data.get("dot_id")
    duyet = 1 if data.get("duyet", True) else 0
    conn = get_db()
    if slot_id:
        conn.execute("UPDATE gv_slot SET duyet_tbm = ? WHERE id = ?", (duyet, slot_id))
    elif gv_id and dot_id:
        conn.execute(
            "UPDATE gv_slot SET duyet_tbm = ? WHERE gv_id = ? AND dot_id = ?",
            (duyet, gv_id, dot_id),
        )
    else:
        conn.close()
        return fail("Thiếu slot_id hoặc (gv_id, dot_id)", 400)
    conn.commit()
    conn.close()
    return ok("Cập nhật trạng thái slot thành công")


@app.route("/api/phan-cong", methods=["POST"])
@role_required("TBM")
def assign_roles():
    data = request.json or {}
    dang_ky_id = data.get("dang_ky_id")
    gv_hd_id = data.get("gv_hd_id")
    gv_pb_id = data.get("gv_pb_id")
    
    if not dang_ky_id:
        return fail("Thiếu ID đăng ký", 400)

    conn = get_db()
    reg = conn.execute(
        "SELECT id, loai, linh_vuc, gv_id FROM dang_ky WHERE id = ?",
        (dang_ky_id,),
    ).fetchone()
    if not reg:
        conn.close()
        return fail("Không tìm thấy đăng ký", 404)

    major = kltn_major_from_dang_ky(reg["linh_vuc"])
    if major:
        check_ids = []
        if gv_hd_id is not None:
            check_ids.append(int(gv_hd_id))
        elif reg["gv_id"] is not None:
            check_ids.append(reg["gv_id"])
        if gv_pb_id is not None:
            check_ids.append(int(gv_pb_id))
        if check_ids:
            ok_m, err_m = assert_kltn_assignees_match_major(conn, major, check_ids)
            if not ok_m:
                conn.close()
                return fail(err_m, 400)

    if gv_hd_id is not None:
        conn.execute("UPDATE dang_ky SET gv_id = ? WHERE id = ?", (gv_hd_id, dang_ky_id))

    if gv_pb_id is not None:
        if reg["loai"] != "KLTN":
            conn.close()
            return fail("Chỉ phân công phản biện cho KLTN", 400)

        # Xóa phân công cũ nếu có
        conn.execute("DELETE FROM nop_bai WHERE dang_ky_id = ? AND loai_file = 'phanbien_gv'", (dang_ky_id,))
        # Thêm phân công mới
        conn.execute(
            "INSERT INTO nop_bai (dang_ky_id, loai_file, file_path) VALUES (?, 'phanbien_gv', ?)",
            (dang_ky_id, str(gv_pb_id)),
        )

    conn.commit()
    conn.close()
    return ok("Phân công thành công")


@app.route("/api/kltn/pb-accept", methods=["POST"])
@role_required("GV")
def pb_accept():
    data = request.json or {}
    dang_ky_id = data.get("dang_ky_id")
    conn = get_db()
    gv = get_current_user(conn)
    assigned = conn.execute(
        "SELECT id FROM nop_bai WHERE dang_ky_id = ? AND loai_file = 'phanbien_gv' AND file_path = ? LIMIT 1",
        (dang_ky_id, str(gv["id"])),
    ).fetchone()
    if not assigned:
        conn.close()
        return fail("Bạn chưa được phân công phản biện đề tài này", 403)
    
    # Thay đổi trang thái KLTN để cho phép chấm điểm
    conn.execute("UPDATE dang_ky SET trang_thai = 'cham_diem' WHERE id = ?", (dang_ky_id,))
    
    conn.execute(
        "INSERT INTO nop_bai (dang_ky_id, loai_file, file_path) VALUES (?, 'pb_accepted', ?)",
        (dang_ky_id, str(gv["id"])),
    )
    conn.commit()
    conn.close()
    return ok("Đã xác nhận phản biện KLTN, bạn có thể bắt đầu chấm điểm.")


@app.route("/api/phan-cong/hoi-dong", methods=["POST"])
@role_required("TBM")
def assign_council():
    data = request.json or {}
    dang_ky_id = data.get("dang_ky_id")
    ct_id = data.get("ct_id")
    tk_id = data.get("tk_id")
    # Hỗ trợ cả tham số cũ (tv_id) lẫn mới (tv_ids)
    tv_ids = data.get("tv_ids")
    single_tv = data.get("tv_id")
    if tv_ids is None:
        tv_ids = [single_tv] if single_tv else []
    if not all([dang_ky_id, ct_id, tk_id]) or not tv_ids:
        return fail("Thiếu thông tin hội đồng (cần CT, TK và ít nhất 1 TV)", 400)

    conn = get_db()
    reg_hd = conn.execute(
        "SELECT loai, linh_vuc FROM dang_ky WHERE id = ?",
        (dang_ky_id,),
    ).fetchone()
    if not reg_hd or reg_hd["loai"] != "KLTN":
        conn.close()
        return fail("Chỉ lập hội đồng cho đăng ký KLTN", 400)
    major = kltn_major_from_dang_ky(reg_hd["linh_vuc"])
    council_ids = [ct_id, tk_id, *tv_ids]
    ok_m, err_m = assert_kltn_assignees_match_major(conn, major, council_ids)
    if not ok_m:
        conn.close()
        return fail(err_m, 400)

    all_member_ids = [str(ct_id), str(tk_id), *[str(tv_id) for tv_id in tv_ids]]
    hoi_dong_path = "|".join(all_member_ids)

    # Remove old council assignment if exists
    conn.execute(
        "DELETE FROM nop_bai WHERE dang_ky_id = ? AND loai_file = 'hoi_dong'",
        (dang_ky_id,)
    )
    # Insert new council assignment
    conn.execute(
        "INSERT INTO nop_bai (dang_ky_id, loai_file, file_path) VALUES (?, 'hoi_dong', ?)",
        (dang_ky_id, hoi_dong_path),
    )
    conn.commit()
    conn.close()
    return ok("Lập hội đồng thành công")


@app.route("/api/cham-diem", methods=["POST"])
@role_required("GV", "TBM")
def score():
    data = request.json or {}
    dang_ky_id = data.get("dang_ky_id")
    vai_tro = data.get("vai_tro")
    diem = data.get("diem")
    nhan_xet = data.get("nhan_xet", "")
    cau_hoi = data.get("cau_hoi", "")
    if not all([dang_ky_id, vai_tro]) or diem is None:
        return fail("Thiếu dữ liệu chấm điểm", 400)
    try:
        diem = float(diem)
    except ValueError:
        return fail("Điểm không hợp lệ", 400)
    if diem < 0 or diem > 10:
        return fail("Điểm phải từ 0 đến 10", 400)

    conn = get_db()
    gv = get_current_user(conn)
    reg_chk = conn.execute("SELECT loai FROM dang_ky WHERE id = ?", (dang_ky_id,)).fetchone()
    role_hdr = str(request.headers.get("X-User-Role") or session.get("role") or "").upper()
    if reg_chk and reg_chk["loai"] == "KLTN" and role_hdr != "TBM":
        if not _can_score_kltn(conn, dang_ky_id, gv["id"], vai_tro):
            conn.close()
            return fail("Bạn không được phân công chấm điểm với vai trò này", 403)
    old = conn.execute(
        "SELECT id FROM cham_diem WHERE dang_ky_id = ? AND gv_id = ? AND vai_tro = ?",
        (dang_ky_id, gv["id"], vai_tro),
    ).fetchone()
    if old:
        conn.execute(
            """
            UPDATE cham_diem
            SET diem = ?, nhan_xet = ?, cau_hoi = ?
            WHERE id = ?
            """,
            (diem, nhan_xet, cau_hoi, old["id"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO cham_diem (dang_ky_id, gv_id, vai_tro, diem, nhan_xet, cau_hoi)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (dang_ky_id, gv["id"], vai_tro, diem, nhan_xet, cau_hoi),
        )
    reg = conn.execute("SELECT loai FROM dang_ky WHERE id = ?", (dang_ky_id,)).fetchone()
    if reg and reg["loai"] == "KLTN":
        if vai_tro == "PB":
            if not str(nhan_xet or "").strip() or not str(cau_hoi or "").strip():
                conn.close()
                return fail("GV phản biện: bắt buộc nhập nhận xét và câu hỏi (Thư ký đưa vào biên bản)", 400)
        cnt = conn.execute(
            "SELECT COUNT(DISTINCT vai_tro) AS c FROM cham_diem WHERE dang_ky_id = ? AND vai_tro IN ('HD','PB','CT') AND diem IS NOT NULL",
            (dang_ky_id,),
        ).fetchone()
        if cnt and cnt["c"] == 3:
            conn.execute("UPDATE dang_ky SET trang_thai = 'bao_ve' WHERE id = ?", (dang_ky_id,))
    conn.commit()
    conn.close()
    return ok("Lưu điểm thành công")


@app.route("/api/kltn/finalize", methods=["POST"])
@role_required("TBM", "GV")
def finalize_kltn():
    data = request.json or {}
    dang_ky_id = data.get("dang_ky_id")
    if not dang_ky_id:
        return fail("Thiếu dang_ky_id", 400)
    conn = get_db()
    gv = get_current_user(conn)
    role_hdr = str(request.headers.get("X-User-Role") or session.get("role") or "").upper()
    ct_id = _hoi_dong_ids(conn, dang_ky_id)
    ct_id = ct_id["ct"] if ct_id else None
    if role_hdr == "TBM":
        pass
    elif role_hdr == "GV" and ct_id is not None and gv["id"] == ct_id:
        pass
    else:
        conn.close()
        return fail("Chỉ Chủ tịch hội đồng hoặc TBM được kết thúc (pass/fail) KLTN", 403)
    rows = conn.execute(
        "SELECT vai_tro, diem FROM cham_diem WHERE dang_ky_id = ?",
        (dang_ky_id,),
    ).fetchall()
    
    diem_hd = next((r["diem"] for r in rows if r["vai_tro"] == "HD"), None)
    diem_pb = next((r["diem"] for r in rows if r["vai_tro"] == "PB"), None)
    
    diem_tv_list = [r["diem"] for r in rows if r["vai_tro"] == "TV"]
    diem_ct = next((r["diem"] for r in rows if r["vai_tro"] == "CT"), None)
    
    hoi_dong_scores = diem_tv_list
    if diem_ct is not None:
        hoi_dong_scores.append(diem_ct)

    if diem_hd is None or diem_pb is None or not hoi_dong_scores:
        conn.close()
        return fail("Chưa đủ điểm HD/PB/HĐ để kết thúc KLTN", 400)

    avg_hd = sum(hoi_dong_scores) / len(hoi_dong_scores)
    
    # Công thức mới: GVHD 20%, PB 20% và HĐ 60%
    final_avg = (diem_hd * 0.2) + (diem_pb * 0.2) + (avg_hd * 0.6)
    
    result = "pass" if final_avg >= 4 else "fail"
    conn.execute("UPDATE dang_ky SET trang_thai = ? WHERE id = ? AND loai = 'KLTN'", (result, dang_ky_id))
    conn.commit()
    conn.close()
    return ok("Kết thúc KLTN thành công", {"average": round(final_avg, 2), "result": result})


@app.route("/api/dot-list", methods=["GET"])
@role_required("TBM")
def get_dot_list():
    """TBM lấy danh sách đợt của lĩnh vực mình quản lý."""
    conn = get_db()
    gv = get_current_user(conn)
    if not gv:
        conn.close()
        return fail("Không tìm thấy người dùng", 401)
    
    # Lấy các lĩnh vực TBM quản lý
    nganh_list = [x.strip() for x in (gv["linh_vuc"] or "").split(",") if x.strip()]
    if not nganh_list:
        conn.close()
        return ok("Lấy danh sách đợt", {"dotList": []})
    
    # Lấy đợt có mã ngành trùng với của TBM
    dots = conn.execute(
        "SELECT id, ten_dot, loai, han_dang_ky, han_nop, trang_thai, nganh FROM dot WHERE nganh IN ({})".format(
            ",".join(["?"] * len(nganh_list))
        ),
        nganh_list
    ).fetchall()
    
    dot_list = [dict(row) for row in dots]
    conn.close()
    return ok("Lấy danh sách đợt", {"dotList": dot_list})


@app.route("/api/dot/update-status", methods=["POST"])
@role_required("TBM")
def update_dot_status():
    """TBM khóa/mở đợt của lĩnh vực mình quản lý."""
    data = request.json or {}
    dot_id = data.get("dot_id")
    trang_thai = data.get("trang_thai")  # 'mo' hoặc 'dong'
    
    if not dot_id or trang_thai not in ["mo", "dong"]:
        return fail("Thiếu dot_id hoặc trang_thai không hợp lệ", 400)
    
    conn = get_db()
    gv = get_current_user(conn)
    if not gv:
        conn.close()
        return fail("Không tìm thấy người dùng", 401)
    
    # Lấy đợt cần cập nhật
    try:
        dot_id = int(dot_id)
    except (TypeError, ValueError):
        conn.close()
        return fail("dot_id không hợp lệ", 400)
    
    dot = conn.execute("SELECT id, nganh FROM dot WHERE id = ?", (dot_id,)).fetchone()
    if not dot:
        conn.close()
        return fail("Không tìm thấy đợt", 404)
    
    # Kiểm tra TBM có quản lý ngành này không
    nganh_list = [x.strip() for x in (gv["linh_vuc"] or "").split(",") if x.strip()]
    dot_nganh = (dot["nganh"] or "").strip()
    
    if dot_nganh not in nganh_list:
        conn.close()
        return fail("Bạn không được phép quản lý đợt này (ngoài lĩnh vực quản lý)", 403)
    
    # Cập nhật trạng thái
    conn.execute("UPDATE dot SET trang_thai = ? WHERE id = ?", (trang_thai, dot_id))
    conn.commit()
    conn.close()
    
    status_text = "Mở" if trang_thai == "mo" else "Khóa"
    return ok(f"{status_text} đợt thành công")


@app.route("/api/upload", methods=["POST"])
@login_required
def upload():
    dang_ky_id = request.form.get("dang_ky_id")
    loai = request.form.get("loai_file")
    ma_sv = request.form.get("ma_sv")
    if not all([dang_ky_id, loai, ma_sv]):
        return fail("Thiếu dữ liệu upload", 400)
    if "file" not in request.files:
        return fail("Không có file upload", 400)

    f = request.files["file"]
    if not f.filename:
        return fail("Tên file rỗng", 400)
    if not f.filename.lower().endswith(('.pdf', '.doc', '.docx')):
        return fail("Chỉ chấp nhận file PDF, DOC, hoặc DOCX", 400)

    safe_name = secure_filename(f.filename)
    target_dir = os.path.join(UPLOAD_FOLDER, loai, ma_sv)
    os.makedirs(target_dir, exist_ok=True)
    save_path = os.path.join(target_dir, f"{int(datetime.now().timestamp())}_{safe_name}")
    f.save(save_path)

    stored_path = os.path.relpath(save_path, app.root_path).replace("\\", "/")

    conn = get_db()
    conn.execute(
        "INSERT INTO nop_bai (dang_ky_id, loai_file, file_path) VALUES (?, ?, ?)",
        (dang_ky_id, loai, stored_path),
    )
    conn.commit()
    conn.close()
    return ok("Upload file thành công", {"file_path": stored_path})


@app.route("/api/gv/summarize", methods=["POST"])
@role_required("GV", "TBM")
def summarize_report():
    data = request.json or {}
    dang_ky_id = data.get("dang_ky_id")
    content = (data.get("content") or "").strip()

    if not dang_ky_id and not content:
        return fail("Thiếu dang_ky_id hoặc nội dung để tóm tắt", 400)

    if not content and dang_ky_id:
        conn = get_db()
        try:
            reg = conn.execute(
                "SELECT id, gv_id, loai FROM dang_ky WHERE id = ?",
                (dang_ky_id,),
            ).fetchone()
            if not reg or reg["loai"] != "KLTN":
                return fail("Chỉ hỗ trợ tóm tắt hồ sơ KLTN", 400)

            role_hdr = str(request.headers.get("X-User-Role") or session.get("role") or "").upper()
            if role_hdr == "GV":
                current_user = get_current_user(conn)
                if not current_user:
                    return fail("Không tìm thấy người dùng", 401)

                can_access = reg["gv_id"] == current_user["id"]
                if not can_access:
                    pb_row = conn.execute(
                        "SELECT file_path FROM nop_bai WHERE dang_ky_id = ? AND loai_file = 'phanbien_gv' ORDER BY id DESC LIMIT 1",
                        (dang_ky_id,),
                    ).fetchone()
                    if pb_row:
                        pb_ids = [int(x) for x in str(pb_row["file_path"]).split("|") if x.strip().isdigit()]
                        if current_user["id"] in pb_ids:
                            can_access = True
                    else:
                        hd = _hoi_dong_ids(conn, dang_ky_id)
                        if hd and (current_user["id"] == hd["ct"] or current_user["id"] == hd["tk"] or current_user["id"] in hd["tv"]):
                            can_access = True

                if not can_access:
                    return fail("Bạn không có quyền tóm tắt hồ sơ này", 403)

            content, used_paths = _collect_summary_content(conn, dang_ky_id)
        finally:
            conn.close()
        if not content:
            return fail("Không tìm thấy nội dung văn bản từ file đã nộp", 400)
    else:
        used_paths = []

    if not _configure_gemini():
        return fail("Lỗi cấu hình Gemini API - Kiểm tra lại GEMINI_API_KEY hoặc kết nối mạng", 500)

    prompt = _build_gemini_summary_prompt(content)
    last_error = None
    for model_name in _candidate_gemini_models():
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            summary_text = (getattr(response, "text", "") or "").strip()
            if not summary_text:
                raise RuntimeError("Model trả về nội dung rỗng")
            return ok("Tóm tắt thành công", {
                "summary": summary_text,
                "used_files": used_paths,
                "model": model_name,
            })
        except Exception as e:
            last_error = e

    return fail(
        "Lỗi kết nối Gemini: không tìm thấy model phù hợp hoặc model không hỗ trợ generateContent. "
        f"Lỗi cuối: {str(last_error)}",
        500,
    )


@app.route("/api/thong-ke", methods=["GET"])
@role_required("TBM")
def thong_ke():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT d.ten_dot, COUNT(dk.id) AS tong,
               SUM(CASE WHEN dk.trang_thai = 'pass' THEN 1 ELSE 0 END) AS pass_count
        FROM dang_ky dk
        JOIN dot d ON d.id = dk.dot_id
        WHERE dk.loai = 'KLTN'
        GROUP BY d.id
        ORDER BY d.id ASC
        """
    ).fetchall()
    conn.close()
    data = [{"ten_dot": r["ten_dot"], "tong": r["tong"], "pass": r["pass_count"] or 0} for r in rows]
    return ok("Thống kê thành công", {"rows": data})


from flask import Flask, request, jsonify, session, send_from_directory

@app.route('/api/bien-ban/luu', methods=['POST'])
@login_required
def luu_bien_ban():
    """Nhận file docx base64 từ frontend, lưu vào uploads/bien_ban_tk/<ma_sv>/"""
    import base64
    data = request.json or {}
    ma_sv = data.get('maSV', 'unknown')
    dang_ky_id = data.get('dangKyId')
    file_b64 = data.get('fileBase64')
    filename = data.get('filename', 'bien_ban.docx')
    if not file_b64 or not dang_ky_id:
        return fail("Thiếu dữ liệu", 400)
    target_dir = os.path.join(app.root_path, 'uploads', 'bien_ban_tk', str(ma_sv))
    os.makedirs(target_dir, exist_ok=True)
    save_path = os.path.join(target_dir, f"{int(datetime.now().timestamp())}_{secure_filename(filename)}")
    with open(save_path, 'wb') as f:
        f.write(base64.b64decode(file_b64))
    stored_path = os.path.relpath(save_path, app.root_path).replace("\\", "/")
    conn = get_db()
    conn.execute("DELETE FROM nop_bai WHERE dang_ky_id = ? AND loai_file = 'bien_ban_tk'", (dang_ky_id,))
    conn.execute("INSERT INTO nop_bai (dang_ky_id, loai_file, file_path) VALUES (?, 'bien_ban_tk', ?)",
                 (dang_ky_id, stored_path))
    conn.commit()
    conn.close()
    return ok("Lưu biên bản thành công", {"file_path": stored_path})

@app.route('/uploads/<path:filename>')
def download_file(filename):
    # filename sẽ có dạng: loai_file/ma_sv/ten_file
    # Cần phải tách đường dẫn để lấy thư mục và tên file
    directory = os.path.join(app.root_path, 'uploads', os.path.dirname(filename))
    file = os.path.basename(filename)
    return send_from_directory(directory, file, as_attachment=True)


@app.route('/api/bien-ban/xuat-docx', methods=['POST'])
@login_required
def xuat_bien_ban_docx():
    data = request.json or {}
    tmp = tempfile.NamedTemporaryFile(suffix='.docx', delete=False)
    tmp.close()
    out_path = tmp.name
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gen_bien_ban.js')
    try:
        result = subprocess.run(
            ['node', script_path, json.dumps(data, ensure_ascii=False), out_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0 or not os.path.exists(out_path):
            return fail(f"Lỗi tạo file: {result.stderr or result.stdout}", 500)
        ma_sv = data.get('maSV', 'SV')
        ten = data.get('tenDeTai', 'bien_ban')[:30].replace(' ', '_')
        return send_file(out_path, as_attachment=True,
            download_name=f"BienBan_{ma_sv}_{ten}.docx",
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    except subprocess.TimeoutExpired:
        return fail("Timeout", 500)
    except Exception as e:
        return fail(str(e), 500)
    finally:
        try: os.unlink(out_path)
        except: pass

@app.route("/api/thong-bao", methods=["GET"])
@login_required
def get_thong_bao():
    conn = get_db()
    user = get_current_user(conn)
    rows = conn.execute(
        """
        SELECT tb.*, u.ho_ten AS ten_nguoi_gui
        FROM thong_bao tb
        LEFT JOIN users u ON u.id = tb.nguoi_gui_id
        WHERE tb.nguoi_nhan_id = ?
        ORDER BY tb.tao_luc DESC
        """,
        (user["id"],)
    ).fetchall()
    conn.close()
    data = [dict(r) for r in rows]
    return ok("Lấy thông báo thành công", {"thong_bao": data})


@app.route("/api/thong-bao/doc", methods=["POST"])
@login_required
def mark_read():
    """Đánh dấu đã đọc một hoặc tất cả thông báo"""
    data = request.json or {}
    tb_id = data.get("id")  # None = đánh dấu tất cả
    conn = get_db()
    user = get_current_user(conn)
    if tb_id:
        conn.execute(
            "UPDATE thong_bao SET da_doc = 1 WHERE id = ? AND nguoi_nhan_id = ?",
            (tb_id, user["id"])
        )
    else:
        conn.execute(
            "UPDATE thong_bao SET da_doc = 1 WHERE nguoi_nhan_id = ?",
            (user["id"],)
        )
    conn.commit()
    conn.close()
    return ok("Đã cập nhật trạng thái đọc")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
