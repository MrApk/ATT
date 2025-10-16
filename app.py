from flask import Flask, render_template, request, redirect, url_for, session, make_response
import csv, os
from datetime import datetime, timedelta
import random, string
import qrcode
import hashlib, hmac, base64, time
import math

app = Flask(__name__)
app.secret_key = "supersecretkey"  # required for sessions

SECRET_KEY = b"super_secret_unlock_key"
STUDENT_FILE = "students.csv"
ATTEND_FILE = "attendance.csv"
CODE_FILE = "class_codes.csv"
TOKEN_FILE = "tokens.csv"
TEACHER_FILE = "teachers.csv"
LOCK_FILE = "lock.csv"

# --------- Helpers ----------
def load_students():
    students = {}
    if os.path.exists(STUDENT_FILE):
        with open(STUDENT_FILE, newline='', encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                students[row["id"]] = {"name": row["name"], "class": row["class"]}
    return students

def get_today_code(class_name, year, subject):
    today = datetime.now().strftime("%Y-%m-%d")
    if not os.path.exists(CODE_FILE):
        return None
    with open(CODE_FILE, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (
                row["date"] == today
                and row["class"] == class_name
                and row["year"] == year
                and row["subject"] == subject
            ):
                return row["code"]
    return None

def generate_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def generate_token(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def save_token(token, class_name, year, subject):
    today = datetime.now().strftime("%Y-%m-%d")
    tokens = []
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, newline='', encoding="utf-8") as f:
            tokens = list(csv.DictReader(f))

    tokens.append({
        "token": token,
        "class": class_name,
        "year": year,
        "subject": subject,
        "date": today,
        "used": "0",
        "student_id": ""
    })

    with open(TOKEN_FILE, "w", newline='', encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["token","class","year","subject","date","used","student_id"])
        writer.writeheader()
        writer.writerows(tokens)

def token_is_valid(token):
    if not os.path.exists(TOKEN_FILE):
        return False
    with open(TOKEN_FILE, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["token"] == token and row["used"] == "0":
                return True
    return False

def mark_token_used(token, student_id):
    if not os.path.exists(TOKEN_FILE):
        return
    with open(TOKEN_FILE, newline='', encoding="utf-8") as f:
        tokens = list(csv.DictReader(f))
    for row in tokens:
        if row["token"] == token:
            row["used"] = "1"
            row["student_id"] = student_id
    with open(TOKEN_FILE, "w", newline='', encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["token","class","year","subject","date","used","student_id"])
        writer.writeheader()
        writer.writerows(tokens)

def load_classes():
    classes = set()
    if os.path.exists(STUDENT_FILE):
        with open(STUDENT_FILE, newline='', encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                classes.add(row["class"])
    return sorted(list(classes))

def check_teacher(username, password):
    if os.path.exists(TEACHER_FILE):
        with open(TEACHER_FILE, newline='', encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["username"] == username and row["password"] == password:
                    return True
    return False

def is_student_locked(student_id):
    if not os.path.exists(LOCK_FILE):
        return False, None
    new_rows = []
    locked = False
    unlock_time = None
    now = datetime.now()
    with open(LOCK_FILE, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_unlock_time = datetime.strptime(row["unlock_time"], "%Y-%m-%d %H:%M:%S")
            if row["student_id"] == student_id:
                if now < row_unlock_time:
                    locked = True
                    unlock_time = row_unlock_time
                # skip expired lock (remove it)
            else:
                if now < row_unlock_time:
                    new_rows.append(row)

    # rewrite lock file with only valid locks
    with open(LOCK_FILE, "w", newline='', encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["student_id", "unlock_time"])
        writer.writeheader()
        writer.writerows(new_rows)

    return locked, unlock_time

def lock_student(student_id, minutes=40):
    unlock_time = datetime.now() + timedelta(minutes=minutes)
    rows = []
    if os.path.exists(LOCK_FILE):
        with open(LOCK_FILE, newline='', encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

    rows.append({"student_id": student_id, "unlock_time": unlock_time.strftime("%Y-%m-%d %H:%M:%S")})
    with open(LOCK_FILE, "w", newline='', encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["student_id", "unlock_time"])
        writer.writeheader()
        writer.writerows(rows)

def generate_unlock_token(student_id):
    expiry = int(time.time()) + 300  # token valid for 5 minutes
    data = f"{student_id}:{expiry}".encode()
    signature = hmac.new(SECRET_KEY, data, hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(data + b":" + signature).decode()
    return token

def verify_unlock_token(token):
    try:
        decoded = base64.urlsafe_b64decode(token.encode())
        parts = decoded.split(b":")
        if len(parts) != 3:
            return None  # invalid format
        student_id = parts[0].decode()
        expiry = int(parts[1].decode())
        signature = parts[2]
        # recompute
        data = f"{student_id}:{expiry}".encode()
        expected_sig = hmac.new(SECRET_KEY, data, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected_sig):
            return None
        if time.time() > expiry:
            return None
        return student_id
    except Exception:
        return None
    
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000  # meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

# --------- Routes ----------
@app.route("/")
def index():
    # check if locked
    lock_until = request.cookies.get("lock_until")
    if lock_until:
        lock_until_dt = datetime.strptime(lock_until, "%Y-%m-%d %H:%M:%S")
        if datetime.now() < lock_until_dt:
            return render_template("locked.html", unlock_time=lock_until_dt.strftime("%H:%M:%S"))

    # normal flow (QR scanning + token generation)
    class_name = request.args.get("class")
    year = request.args.get("year")
    subject = request.args.get("subject")
    class_code = request.args.get("code")
    token = None

    if class_name and year and subject and class_code:
        valid_code = get_today_code(class_name, year, subject)
        if valid_code and valid_code == class_code:
            token = generate_token()
            save_token(token, class_name, year, subject)

    classes = load_classes()
    return render_template("index.html",
                           classes=classes,
                           class_name=class_name,
                           year=year,
                           subject=subject,
                           class_code=class_code,
                           token=token)

@app.route("/mark", methods=["POST"])
def mark():
    
    student_id = request.form["student_id"].strip()
    input_code = request.form["class_code"].strip()
    class_name = request.form["class_name"]
    year = request.form["year"].strip()
    subject = request.form["subject"].strip()
    token = request.form.get("token", "")

    # ✅ NEW: get student location from form
    student_lat = request.form.get("student_lat")
    student_lng = request.form.get("student_lng")

    now = datetime.now()
    students = load_students()

    # ✅ Step 0: Check teacher location from CODE_FILE
    teacher_lat, teacher_lng = None, None
    if os.path.exists(CODE_FILE):
        with open(CODE_FILE, newline='', encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["class"] == class_name and row["year"] == year and row["subject"] == subject:
                    teacher_lat = row.get("lat")
                    teacher_lng = row.get("lng")
                    break

    # ✅ Step 0.1: If teacher location exists, verify student's location
    if teacher_lat and teacher_lng and student_lat and student_lng:
        try:
            distance = haversine(float(teacher_lat), float(teacher_lng),
                                 float(student_lat), float(student_lng))
            if distance > 100:
                return render_template("message.html",
                                       message=f"❌ You are too far from teacher. (Distance: {int(distance)}m)")
        except Exception as e:
            return render_template("message.html", message="⚠️ Location check failed. Try again.")

    # ✅ Step 1: Check cookie student_id (device lock)
    cookie_sid = request.cookies.get("sid")
    if cookie_sid and cookie_sid != student_id:
        return render_template("message.html", message=f"❌ This device is locked for Student ID {cookie_sid}. You cannot mark for another student.")

    # ✅ Step 2: Validate student
    if student_id not in students:
        return render_template("message.html", message="❌ Invalid Student ID")

    if students[student_id]["class"] != class_name:
        return render_template("message.html", message="❌ Wrong class for this Student ID")

    valid_code = get_today_code(class_name, year, subject)
    if not valid_code or input_code != valid_code:
        return render_template("message.html", message="❌ Invalid or expired class code")

    if not token or not token_is_valid(token):
        return render_template("message.html", message="❌ Invalid or used token. Refresh QR page and try again.")

    # ✅ Step 3: Prevent duplicate attendance
    if os.path.exists(ATTEND_FILE):
        with open(ATTEND_FILE, newline='', encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (
                    row["id"] == student_id
                    and row["class"] == class_name
                    and row["year"] == year
                    and row["subject"] == subject
                    and row["time"].startswith(datetime.now().strftime("%Y-%m-%d"))
                    and row["code"] == input_code
                ):
                    return render_template("message.html",
                                           message=f"⚠️ Attendance already marked for {students[student_id]['name']} today.")

    # ✅ Step 4: Save attendance
    with open(ATTEND_FILE, "a", newline='', encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([student_id, students[student_id]["name"], class_name, year, subject,
                         now.strftime("%Y-%m-%d %H:%M:%S"), input_code])

    mark_token_used(token, student_id)

    # ✅ Step 5: Set cookie with student ID + lock
    resp = make_response(render_template("message.html",
                           message=f"✅ Attendance marked for {students[student_id]['name']} at {now.strftime('%H:%M:%S')} (Location OK)."))
    resp.set_cookie("sid", student_id, max_age=60*60*24*365)  # 1-year device lock
    unlock_time = (now + timedelta(minutes=40)).strftime("%Y-%m-%d %H:%M:%S")
    resp.set_cookie("lock_until", unlock_time, max_age=60*40)
    return resp

# --- Teacher Authentication ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if check_teacher(username, password):
            session["teacher"] = username
            return redirect(url_for("teacher"))
        else:
            return "<h2>❌ Invalid Credentials</h2><a href='/login'>Try Again</a>"

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("teacher", None)
    return redirect(url_for("login"))

def login_required(func):
    def wrapper(*args, **kwargs):
        if "teacher" not in session:
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper

@app.route("/teacher")
@login_required
def teacher():
    # get filter values from query string (?class=...&year=...&subject=...&date=...)
    filter_class = request.args.get("class", "").strip()
    filter_year = request.args.get("year", "").strip()
    filter_subject = request.args.get("subject", "").strip()
    filter_date = request.args.get("date", "").strip()

    records = []
    if os.path.exists(ATTEND_FILE):
        with open(ATTEND_FILE, newline='', encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                match = True
                if filter_class and row["class"] != filter_class:
                    match = False
                if filter_year and row["year"] != filter_year:
                    match = False
                if filter_subject and row["subject"] != filter_subject:
                    match = False
                if filter_date and not row["time"].startswith(filter_date):
                    match = False
                if match:
                    records.append(row)

    # get dropdown values
    classes = load_classes()
    subjects = sorted({r["subject"] for r in records}) if records else []
    years = sorted({r["year"] for r in records}) if records else []

    return render_template(
        "teacher.html",
        attendance=records,
        teacher=session["teacher"],
        classes=classes,
        subjects=subjects,
        years=years,
        filter_class=filter_class,
        filter_year=filter_year,
        filter_subject=filter_subject,
        filter_date=filter_date,
    )

@app.route("/create_code", methods=["GET", "POST"])
@login_required
def create_code():
    classes = load_classes()
    if request.method == "POST":
        class_name = request.form["class_name"]
        year = request.form["year"].strip()
        subject = request.form["subject"].strip()
        lat = request.form.get("lat", "")
        lng = request.form.get("lng", "")
        code = generate_code()
        today = datetime.now().strftime("%Y-%m-%d")

        rows = []
        if os.path.exists(CODE_FILE):
            with open(CODE_FILE, newline='', encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

        # remove old entry for same day/class/year/subject
        rows = [r for r in rows if not (
            r["date"] == today and r["class"] == class_name and r["year"] == year and r["subject"] == subject
        )]

        rows.append({
            "date": today,
            "class": class_name,
            "year": year,
            "subject": subject,
            "code": code,
            "lat": lat,
            "lng": lng
        })

        # write with location support
        with open(CODE_FILE, "w", newline='', encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["date", "class", "year", "subject", "code", "lat", "lng"])
            writer.writeheader()
            writer.writerows(rows)

        url = f"http://localhost:5000/?class={class_name}&year={year}&subject={subject}&code={code}"
        qr_img = qrcode.make(url)
        qr_path = f"static/qrcodes/{class_name}_{year}_{subject}_{today}.png"
        os.makedirs("static/qrcodes", exist_ok=True)
        qr_img.save(qr_path)

        return render_template(
            "create_code_result.html",
            class_name=class_name,
            year=year,
            subject=subject,
            today=today,
            code=code,
            qr_path=qr_path,
            lat=lat,
            lng=lng
        )

    return render_template("create_code.html", classes=classes)



@app.route("/codes")
@login_required
def codes():
    records = []
    if os.path.exists(CODE_FILE):
        with open(CODE_FILE, newline='', encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append(row)
    return render_template("codes.html", codes=records, teacher=session["teacher"])

@app.route("/qr/<class_name>/<date>/<year>/<subject>")
@login_required
def qr_code(class_name, date, year, subject):
    with open(CODE_FILE, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["class"] == class_name and row["date"] == date and row["year"] == year and row["subject"] == subject:
                code = row["code"]
                url = f"http://localhost:5000/?class={class_name}&year={year}&subject={subject}&code={code}"
                qr_path = f"static/qrcodes/{class_name}_{year}_{subject}_{date}.png"

                # regenerate QR
                qr_img = qrcode.make(url)
                os.makedirs("static/qrcodes", exist_ok=True)
                qr_img.save(qr_path)

                return render_template("qr.html",
                                       class_name=class_name,
                                       date=date,
                                       year=year,
                                       subject=subject,
                                       code=code,
                                       url=url,
                                       qr_path=qr_path)
    return "<h2>❌ Code not found</h2><a href='/codes'>Back</a>"

@app.route("/unlock_device", methods=["GET", "POST"])
@login_required
def unlock_device():
    message = None
    link = None
    if request.method == "POST":
        student_id = request.form["student_id"].strip()
        if student_id:
            token = generate_unlock_token(student_id)
            link = url_for("clear_device_cookie_secure", token=token, _external=True)
            message = f"🔑 Secure unlock link generated for Student ID {student_id}"
        else:
            message = "❌ Please enter a Student ID."

    return render_template("unlock_device.html", teacher=session["teacher"], message=message, link=link)

@app.route("/clear_device_cookie_secure/<token>")
def clear_device_cookie_secure(token):
    student_id = verify_unlock_token(token)
    if not student_id:
        return render_template("message.html", message="❌ Invalid or expired unlock link.")
    
    cookie_sid = request.cookies.get("sid")
    resp = make_response(render_template("message.html", message=f"✅ Device unlocked for {student_id}. You can now mark attendance again."))
    resp.delete_cookie("sid")
    resp.delete_cookie("lock_until")
    return resp


if __name__ == "__main__":
    if not os.path.exists(ATTEND_FILE):
        with open(ATTEND_FILE, "w", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["id","name","class","year","subject","time","code"])

    if not os.path.exists(CODE_FILE):
        with open(CODE_FILE, "w", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["date","class","year","subject","code"])

    if not os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "w", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["token","class","year","subject","date","used","student_id"])

    app.run(debug=True)