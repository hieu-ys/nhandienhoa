import os
import io
import json
import base64  # Thêm thư viện này
from datetime import timedelta
from flask import Flask, request, jsonify, send_from_directory, session
import google.generativeai as genai
from PIL import Image
import mysql.connector
from flask_bcrypt import Bcrypt
from flask_cors import CORS

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app, supports_credentials=True)
bcrypt = Bcrypt(app)

app.secret_key = 'super_secret_key_flower_recognition'
app.config.update(
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=False,
    PERMANENT_SESSION_LIFETIME=timedelta(days=1)
)

# --- CẤU HÌNH AI & DB ---
API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyBbr-Tp1aY9GatWayBl6x3X1aoTGdLtEVM")
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

DB_CONFIG = {
    'host': 'nhandienhoa-tnut-8a16.f.aivencloud.com',
    'port': 12281,
    'user': 'avnadmin',
    'password': 'AVNS_bQ5NL35Yjo4Xv8DmznL',
    'database': 'FlowerDB',
    'ssl_ca': 'ca.pem'
}

def get_db_connection():
    try: return mysql.connector.connect(**DB_CONFIG)
    except: return None

@app.route('/')
def serve_index(): return send_from_directory('.', 'index.html')

# --- API AUTH (Giữ nguyên) ---
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    hpw = bcrypt.generate_password_hash(data['matkhau']).decode('utf-8')
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO NguoiDung (tendangnhap, matkhau, hoten) VALUES (%s, %s, %s)", 
                       (data['tendangnhap'], hpw, data['hoten']))
        conn.commit()
        return jsonify({'message': 'OK'})
    except: return jsonify({'error': 'Lỗi'}), 400
    finally: conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM NguoiDung WHERE tendangnhap = %s", (data['tendangnhap'],))
    user = cursor.fetchone()
    if user and bcrypt.check_password_hash(user['matkhau'], data['matkhau']):
        session.permanent = True
        session['user_id'] = user['id']
        session['fullname'] = user['hoten']
        return jsonify({'user': user})
    return jsonify({'error': 'Sai tài khoản'}), 401

@app.route('/api/profile', methods=['GET'])
def get_profile():
    if 'user_id' not in session: return jsonify({'error': 'No'}), 401
    return jsonify({'id': session['user_id'], 'fullname': session['fullname']})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Out'})

# --- API HOA ---
@app.route('/api/flowers', methods=['GET'])
def get_flowers():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, tenhoa as name, ho as family, mota as description, chamsoc as care, hinh_url as image_url FROM Hoa")
    rows = cursor.fetchall()
    conn.close()
    return jsonify(rows)

@app.route('/api/recognize', methods=['POST'])
def recognize():
    uid = session.get('user_id')
    if not uid: return jsonify({'error': 'Login'}), 401
    
    # Hỗ trợ cả file upload và base64 string
    img_byte = None
    b64_str = None

    if 'image' in request.files:
        file = request.files['image']
        img_byte = file.read()
        b64_str = f"data:image/jpeg;base64,{base64.b64encode(img_byte).decode('utf-8')}"
    elif request.json and 'image_base64' in request.json:
        # Xử lý dữ liệu base64 từ camera trực tiếp
        b64_data = request.json['image_base64']
        # Loại bỏ tiền tố "data:image/jpeg;base64," nếu có
        if "," in b64_data:
            b64_str = b64_data
            b64_data = b64_data.split(",")[1]
        else:
            b64_str = f"data:image/jpeg;base64,{b64_data}"
        img_byte = base64.b64decode(b64_data)

    if img_byte is None:
        return jsonify({'error': 'Không tìm thấy ảnh'}), 400

    try:
        img = Image.open(io.BytesIO(img_byte))
        prompt = "Nhận diện hoa, trả về JSON {name, family, description, care}. Chỉ trả về JSON, không markdown. Nếu không phải hoa, trả về JSON với name là 'Không xác định'."
        res = model.generate_content(["Nhận diện hoa, trả về JSON {name, family, description, care}. Không markdown.", img])
        
        # Làm sạch kết quả trả về từ AI
        clean_text = res.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_text)

        # Chỉ lưu lịch sử nếu nhận diện được hoa cụ thể (name khác 'Không xác định')
        if data.get('name') and data['name'] != 'Không xác định':
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO LichSuNhanDien (id_nguoidung, hinh_base64, ketqua_json) VALUES (%s, %s, %s)", (uid, b64_str, clean_text))
                conn.commit()
                conn.close()

        return jsonify(data)
    except Exception as e:
        print(f"Lỗi nhận diện: {e}")
        return jsonify({'error': 'Lỗi xử lý ảnh hoặc AI'}), 500

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    prompt = f"Bạn là chuyên gia hoa. Người dùng hỏi: {data['message']}. Ngữ cảnh: {data.get('context','')}. Trả lời ngắn."
    try:
        res = model.generate_content(prompt)
        return jsonify({'reply': res.text})
    except:
        return jsonify({'reply': 'Lỗi kết nối AI'}), 500

if __name__ == '__main__':
    # Lấy cổng từ biến môi trường của Render, mặc định là 5000
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)