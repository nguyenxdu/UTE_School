# He Thong Quan Ly BCTT - KLTN

Ung dung quan ly de tai Bao cao thuc tap (BCTT) va Khoa luan tot nghiep (KLTN) cho Khoa FE.

Project gom:
- Backend Flask API + SQLite
- Frontend HTML/CSS/JS tai thu muc frontend
- Upload file tai thu muc uploads
- Script sinh bien ban docx bang Node.js

## 1. Tinh nang chinh

- Dang nhap theo vai tro: SV, GV, TBM
- Dang ky BCTT/KLTN, duyet de tai, phan cong vai tro
- Cham diem, tong hop ket qua, theo doi tien do
- Upload file ho so (PDF/DOC/DOCX)
- Xuat bien ban thu ky dinh dang DOCX
- He thong thong bao noi bo cho SV/GV

## 2. Cau truc thu muc

- app.py: Backend Flask API
- database.py: Khoi tao va ket noi SQLite
- import_real_data.py: Khoi tao DB va import du lieu that tu Google Sheet
- seed_data.py: Seed du lieu demo local
- frontend/index.html: Giao dien web
- gen_bien_ban.js: Tao file bien ban DOCX
- uploads/: Noi luu toan bo file upload

## 3. Yeu cau moi truong

- Python 3.10 tro len
- Node.js 18 tro len
- npm

## 4. Cai dat thu vien

Chay tai thu muc goc project.

### 4.1. Tao moi truong ao Python (khuyen nghi)

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 4.2. Cai thu vien Python

```powershell
pip install flask flask-cors
```

### 4.3. Cai thu vien Node.js

```powershell
npm install
```

Note:
- package.json hien tai su dung thu vien docx de xuat bien ban.

## 5. Khoi tao du lieu

Ban co 2 lua chon:

### Cach A: Import du lieu that (khuyen dung cho he thong hien tai)

```powershell
python import_real_data.py
```

### Cach B: Seed du lieu demo

```powershell
python seed_data.py
```

Sau khi chay 1 trong 2 script tren, file db.sqlite se duoc tao/cap nhat.

## 6. Chay he thong

### 6.1. Chay backend

```powershell
python app.py
```

Backend mac dinh:
- http://127.0.0.1:5000

### 6.2. Chay frontend

Ban co the mo truc tiep file frontend/index.html trong trinh duyet.

Khuyen nghi dung local server de on dinh hon:

```powershell
python -m http.server 5500 -d frontend
```

Mo:
- http://127.0.0.1:5500

Frontend dang cau hinh API base trong index.html la:
- http://127.0.0.1:5000

## 7. Dang nhap

- Mat khau mac dinh thuong la: 123456
- Co the dang nhap bang ma (MSSV/MAGV) hoac email tuy theo du lieu import
- Role he thong:
	- SV: Sinh vien
	- GV: Giang vien
	- TBM: Truong bo mon

## 8. Luong chay nhanh de test

1. Chay import du lieu: python import_real_data.py
2. Chay backend: python app.py
3. Mo frontend
4. Dang nhap GV de duyet de tai BCTT
5. Kiem tra quota GV thay doi sau duyet

## 9. Cac loi thuong gap

### Loi ModuleNotFoundError: flask/flask_cors

Nguyen nhan: chua cai thu vien Python.

Khac phuc:

```powershell
pip install flask flask-cors
```

### Frontend vao duoc nhung goi API loi

Nguyen nhan: backend chua chay hoac sai cong.

Khac phuc:
- Dam bao app.py dang chay port 5000
- Kiem tra API base trong frontend/index.html

### Loi xuat bien ban DOCX

Nguyen nhan: thieu package Node hoac loi runtime Node.

Khac phuc:

```powershell
npm install
```

## 10. Ghi chu phat trien

- Database la SQLite tai file db.sqlite
- Gioi han kich thuoc upload hien tai: 20MB
- Upload chap nhan: PDF, DOC, DOCX
- Session login su dung cookie cua Flask

## 11. Lenh tong hop (copy nhanh)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install flask flask-cors
npm install
python import_real_data.py
python app.py
```

