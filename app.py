import json
import re
import math
import itertools
import threading
import time
import requests
from datetime import datetime, date
from flask import Flask, request, abort, render_template_string
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FlexSendMessage, BubbleContainer, BoxComponent, TextComponent,
    ImageComponent, URIAction, DatetimePickerAction, PostbackEvent,
    CarouselContainer, ButtonComponent
)

# 🛡️ ระบบป้องกัน Server Crash หากลืมลง Library
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSHEETS_READY = True
except ImportError:
    GSHEETS_READY = False
    print("⚠️ ยังไม่ได้ติดตั้ง gspread หรือ google-auth")

app = Flask(__name__)

# ==========================================
# 🟢 ตั้งค่า LINE & LIFF
# ==========================================
LINE_CHANNEL_ACCESS_TOKEN = "hJrtsmcBM9LT0m0jEC6h4dbp0ZWek8DwJ77PW7hypvMbGNPnld0vtFiuUpb5dXB0oiKgDAVO6C3duZARQMiLggsUmKew7SA2MoPECS9gDFebh/W0fk6ITXbzgVD3WX6iCdpdPZfaRA54aQXeEU5ezwdB04t89/1O/w1cDnyilFU="
LINE_CHANNEL_SECRET = "b178fc8ba767114ad57ac6ab93c312ab"

LIFF_ID_CALCULATOR = "2009026200-reXDdCkf"
LIFF_ID_INTERACTION = "2009155599-28RB35IY"

TABLE_IMAGE_URL = "https://i.postimg.cc/BnCsP0fK/ref-table.png"
TABLE_PDF_URL = "https://www.biogenetech.co.th/wp-content/uploads/2020/10/warfarin_Guideline.pdf" 

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

user_sessions = {}

# ==========================================
# 📊 ตั้งค่า Google Sheets (อัปเดตระบบเชื่อมต่อใหม่แบบ Dynamic)
# ==========================================
gc_client = None
sheet_logs = None
INTERACTION_DB = {}

if GSHEETS_READY:
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    try:
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        gc_client = gspread.authorize(creds)
        wb = gc_client.open("Warfy_Logs")
        sheet_logs = wb.sheet1
        print("✅ Google Sheets Connected Successfully!")
    except Exception as e:
        print(f"⚠️ Google Sheets Connection Failed: {e}")

# 🔄 ฟังก์ชันสำหรับโหลดข้อมูลยา (วิ่งไปหาชีต DI database ใหม่ทุกครั้งที่เรียกใช้)
def load_drug_db():
    global INTERACTION_DB
    if gc_client is None:
        print("⚠️ ยังไม่ได้เชื่อมต่อ Google Sheets API")
        return False
    try:
        wb = gc_client.open("Warfy_Logs")
        sheet_di = wb.worksheet("DI database") # ค้นหาชีตแบบ Real-time
        records = sheet_di.get_all_records()
        
        new_db = {}
        for row in records:
            keyword = str(row.get('Keyword', '')).strip().lower()
            if not keyword: continue # ข้ามแถวที่ว่าง
            new_db[keyword] = {
                "name": str(row.get('Name', '')),
                "risk": str(row.get('Risk', '')),
                "effect": str(row.get('Effect', '')),
                "detail": str(row.get('Detail', '')),
                "management": str(row.get('Management', '')),
                "reference": str(row.get('Reference', '')),
                "pdf_url": str(row.get('PDF_URL', ''))
            }
        INTERACTION_DB = new_db
        print(f"✅ โหลดข้อมูลยาสำเร็จ! พบ {len(INTERACTION_DB)} รายการ")
        return True
    except gspread.exceptions.WorksheetNotFound:
        print("⚠️ ไม่พบแผ่นงานชื่อ 'DI database' โปรดตรวจสอบชื่อให้ถูกต้อง")
        return False
    except Exception as e:
        print(f"⚠️ โหลดข้อมูลยาไม่สำเร็จ: {e}")
        return False

# โหลดข้อมูล 1 ครั้งตอนเซิร์ฟเวอร์ติด
load_drug_db()

def log_to_sheets(feature, details, location="No GPS"):
    if sheet_logs is None: return 
    try:
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        row_data = [timestamp, feature, details, location]
        sheet_logs.append_row(row_data)
    except Exception as e:
        print(f"⚠️ Error logging to sheets: {e}")

RISK_COLOR_MAP = {"X": "#D32F2F", "D": "#EF6C00", "C": "#FBC02D", "B": "#0288D1", "A": "#388E3C"}

# ==========================================
# 🌐 LIFF 1: Calculator HTML
# ==========================================
LIFF_CALC_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Warfy Calculator</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
    <style>
        body { font-family: sans-serif; padding: 20px; background-color: #f8f9fa; }
        .section { background: white; padding: 15px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
        .pill-btn { width: 48%; padding: 15px; margin: 1%; border: 1px solid #ddd; border-radius: 8px; background: #f0f0f0; font-size: 18px; }
        .pill-btn.active { background: #00C851; color: white; }
        input[type="text"] { width: 100%; padding: 12px; margin-top: 5px; border-radius: 5px; border: 1px solid #ccc; box-sizing: border-box; font-size: 18px; }
        .confirm-btn { width: 100%; padding: 15px; background: #007bff; color: white; border: none; border-radius: 50px; font-size: 18px; margin-top: 10px; cursor: pointer;}
    </style>
</head>
<body>
    <div class="section">
        <h3>1. ขนาดยาที่มี (mg)</h3>
        <div id="btnContainer"></div>
    </div>
    <div class="section">
        <h3>2. ขนาดยาเดิม (mg/wk)</h3>
        <input type="text" id="weeklyDose" placeholder="เช่น 21" inputmode="decimal" oninput="validateNumber(this)">
    </div>
    <div class="section">
        <h3>3. INR ล่าสุด</h3>
        <input type="text" id="inrValue" placeholder="เช่น 2.5" inputmode="decimal" oninput="validateNumber(this)">
        <label style="display:block; margin-top:10px;">
            <input type="checkbox" id="unknownInr" onchange="toggleInr()"> ไม่ทราบ/ไม่ได้ตรวจ
        </label>
    </div>
    <button class="confirm-btn" id="confirmBtn" onclick="sendData()">คำนวณ</button>

    <script>
        function validateNumber(input) {
            input.value = input.value.replace(/[^0-9.]/g, '');
            if ((input.value.match(/\\./g) || []).length > 1) { 
                input.value = input.value.replace(/\\.+$/, ""); 
            }
        }
        const pillSizes = [1, 2, 3, 5];
        let selected = new Set();
        pillSizes.forEach(s => {
            let b = document.createElement('button'); b.className='pill-btn'; b.innerText=s;
            b.onclick = () => { 
                if(selected.has(s)) { selected.delete(s); b.classList.remove('active'); } 
                else { selected.add(s); b.classList.add('active'); }
            };
            document.getElementById('btnContainer').appendChild(b);
        });
        function toggleInr() {
            document.getElementById('inrValue').disabled = document.getElementById('unknownInr').checked;
            if(document.getElementById('unknownInr').checked) { document.getElementById('inrValue').value = ''; }
        }
        async function sendData() {
            if (!liff.isInClient()) return alert("กรุณาเปิดในแอป LINE เท่านั้น");
            if (selected.size === 0) return alert("กรุณาเลือกขนาดยาที่มี");
            let dose = document.getElementById('weeklyDose').value;
            if (!dose) return alert("กรุณากรอกขนาดยาเดิม");
            let unk = document.getElementById('unknownInr').checked;
            let inr = document.getElementById('inrValue').value;
            if (!unk && !inr) return alert("กรุณากรอก INR");
            
            try {
                let msg = `📝 ข้อมูลจัดยา: ${Array.from(selected).sort().join(",")} | ${dose} | ${unk ? "Unknown" : inr}`;
                await liff.sendMessages([{type:'text', text:msg}]);
                liff.closeWindow();
            } catch (err) { 
                alert("Error: " + err); 
            }
        }
        liff.init({ liffId: "{{ liff_id }}" }).then(() => { if (!liff.isLoggedIn()) liff.login(); });
    </script>
</body>
</html>
"""

# ==========================================
# 🌐 LIFF 2: Interaction Checker HTML
# ==========================================
LIFF_INTERACT_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Check Interactions</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
    <style>
        body { font-family: -apple-system, sans-serif; padding: 20px; background-color: #f8f9fa; }
        .container { max-width: 500px; margin: 0 auto; }
        h3 { color: #333; margin-bottom: 5px; }
        .search-box { position: relative; width: 100%; margin-top: 15px; }
        input[type="text"] { width: 100%; padding: 15px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; box-sizing: border-box; outline: none; }
        .dropdown { position: absolute; top: 100%; left: 0; right: 0; background: white; border: 1px solid #ddd; border-radius: 0 0 8px 8px; max-height: 200px; overflow-y: auto; z-index: 1000; box-shadow: 0 4px 6px rgba(0,0,0,0.1); display: none; }
        .dropdown-item { padding: 12px; cursor: pointer; border-bottom: 1px solid #f0f0f0; }
        .dropdown-item:active { background-color: #e3f2fd; }
        .selected-area { margin-top: 20px; min-height: 50px; display: flex; flex-wrap: wrap; gap: 8px; }
        .drug-tag { background: #e3f2fd; color: #0277bd; padding: 8px 12px; border-radius: 20px; font-size: 14px; display: flex; align-items: center; border: 1px solid #b3e5fc; }
        .drug-tag span { margin-left: 8px; cursor: pointer; font-weight: bold; color: #d32f2f; }
        .check-btn { width: 100%; padding: 15px; background: #00C851; color: white; border: none; border-radius: 50px; font-size: 18px; margin-top: 30px; font-weight: bold; cursor: pointer; box-shadow: 0 4px 10px rgba(0, 200, 81, 0.3); transition: 0.3s; }
        .check-btn:disabled { background: #ccc; cursor: not-allowed; box-shadow: none; }
    </style>
</head>
<body>
    <div class="container">
        <h3>🔍 ตรวจสอบ Warfarin Drug interaction</h3>
        <small style="color:#666;">พิมพ์ชื่อยาแล้ว <b>กดเลือกจากรายการ</b></small>
        <div class="search-box">
            <input type="text" id="drugInput" placeholder="พิมพ์ชื่อยา (เช่น met...)" autocomplete="off">
            <div class="dropdown" id="suggestions"></div>
        </div>
        <div class="selected-area" id="selectedTags"></div>
        <button class="check-btn" id="checkBtn" onclick="submitData()" disabled>ตรวจสอบ (0)</button>
    </div>
    <script>
        const drugDB = {{ drug_list | tojson }}; 
        let selectedDrugs = new Set();
        const input = document.getElementById('drugInput');
        const dropdown = document.getElementById('suggestions');
        const tagsArea = document.getElementById('selectedTags');
        const checkBtn = document.getElementById('checkBtn');

        input.addEventListener('input', function() {
            const val = this.value.toLowerCase().trim();
            dropdown.innerHTML = '';
            if (!val) { dropdown.style.display = 'none'; return; }
            
            let matches = drugDB.filter(d => d.toLowerCase().includes(val) && !selectedDrugs.has(d));
            
            matches.sort((a, b) => {
                const aLower = a.toLowerCase();
                const bLower = b.toLowerCase();
                const aStarts = aLower.startsWith(val);
                const bStarts = bLower.startsWith(val);

                if (aStarts && !bStarts) return -1;
                if (!aStarts && bStarts) return 1;
                return aLower.localeCompare(bLower);
            });

            if (matches.length > 0) {
                dropdown.style.display = 'block';
                matches.forEach(drug => {
                    const item = document.createElement('div');
                    item.className = 'dropdown-item';
                    item.innerText = drug.charAt(0).toUpperCase() + drug.slice(1);
                    item.onmousedown = (e) => { e.preventDefault(); addDrug(drug); };
                    dropdown.appendChild(item);
                });
            } else { dropdown.style.display = 'none'; }
        });

        input.addEventListener('blur', () => { setTimeout(() => dropdown.style.display = 'none', 100); });

        function addDrug(drugKey) { selectedDrugs.add(drugKey); input.value = ''; dropdown.style.display = 'none'; renderTags(); }
        function removeDrug(drugKey) { selectedDrugs.delete(drugKey); renderTags(); }
        
        function renderTags() {
            tagsArea.innerHTML = '';
            selectedDrugs.forEach(drug => {
                const tag = document.createElement('div'); tag.className = 'drug-tag';
                tag.innerHTML = `${drug.charAt(0).toUpperCase() + drug.slice(1)} <span onclick="removeDrug('${drug}')">×</span>`;
                tagsArea.appendChild(tag);
            });
            checkBtn.innerText = `ตรวจสอบ (${selectedDrugs.size})`;
            checkBtn.disabled = selectedDrugs.size === 0;
            checkBtn.style.backgroundColor = selectedDrugs.size > 0 ? '#00C851' : '#ccc';
        }

        async function submitData() {
            if (!liff.isInClient()) return alert("กรุณาใช้งานในแอป LINE เท่านั้น");
            if (selectedDrugs.size === 0) return alert("กรุณาเลือกยาก่อนกดตรวจสอบ");
            
            try {
                const drugList = Array.from(selectedDrugs).join(", ");
                const msg = `🔍 ตรวจสอบยา: ${drugList}`; 
                
                await liff.sendMessages([{ type: 'text', text: msg }]); 
                liff.closeWindow(); 
            } catch (err) { 
                alert("เกิดข้อผิดพลาด: " + err); 
            }
        }
        liff.init({ liffId: "{{ liff_id }}" }).then(() => { if (!liff.isLoggedIn()) liff.login(); });
    </script>
</body>
</html>
"""

# ==========================================
# 🛤️ Routes & Logic Helpers
# ==========================================
@app.route("/")
def home(): 
    return "✅ Warfy Server is Running!"

@app.route("/liff/pill-selector")
def liff_pill_selector():
    return render_template_string(LIFF_CALC_HTML, liff_id=LIFF_ID_CALCULATOR)

@app.route("/liff/drug-interaction")
def liff_drug_interaction():
    drug_list = list(INTERACTION_DB.keys())
    return render_template_string(LIFF_INTERACT_HTML, liff_id=LIFF_ID_INTERACTION, drug_list=drug_list)

def analyze_drug_list(drug_names_str):
    input_list = [d.strip().lower() for d in drug_names_str.split(",")]
    results = []
    for user_drug in input_list:
        if user_drug in INTERACTION_DB:
            results.append(INTERACTION_DB[user_drug])
        else:
            for db_key, data in INTERACTION_DB.items():
                if user_drug in db_key:
                    results.append(data)
                    break 
    return results

def build_analysis_flex(results):
    if not results: return TextSendMessage(text="✅ ไม่พบปฏิกิริยาระหว่างยาในฐานข้อมูล (เบื้องต้นปลอดภัย หรืออาจสะกดผิด)\n\n*ผลลัพธ์นี้อ้างอิงจากฐานข้อมูลยาหลักเท่านั้น")
    bubbles = []
    risk_order = {'X':0, 'D':1, 'C':2, 'B':3, 'A':4}
    results.sort(key=lambda x: risk_order.get(x['risk'], 5))

    for item in results:
        risk = item['risk']
        color = RISK_COLOR_MAP.get(risk, "#999999")
        risk_text_map = {"X": "X - หลีกเลี่ยง (Avoid)", "D": "D - ปรับเปลี่ยน (Modify)", "C": "C - ติดตามผล (Monitor)", "B": "B - ไม่ต้องกังวล", "A": "A - ปลอดภัย"}
        
        body_contents = [
            BoxComponent(layout="horizontal", contents=[
                TextComponent(text=item['name'], weight="bold", size="lg", flex=1, color="#333333"),
                TextComponent(text=risk, weight="bold", color="#FFFFFF", align="center", gravity="center", backgroundColor=color, cornerRadius="20px", paddingAll="xs", width="30px")
            ]),
            TextComponent(text=risk_text_map.get(risk, risk), size="xs", weight="bold", color=color, margin="sm"),
            BoxComponent(layout="vertical", margin="md", backgroundColor="#f0f0f0", height="1px"),
            TextComponent(text="ผลกระทบ:", size="xs", color="#888888", margin="md"),
            TextComponent(text=item['effect'], size="sm", wrap=True, color="#333333"),
            TextComponent(text="รายละเอียด:", size="xs", color="#888888", margin="md"),
            TextComponent(text=item['detail'], size="sm", wrap=True, color="#333333")
        ]

        if 'management' in item and item['management']:
            body_contents.append(TextComponent(text="การจัดการ (Management):", size="xs", color="#D32F2F", margin="md", weight="bold"))
            body_contents.append(TextComponent(text=item['management'], size="sm", wrap=True, color="#333333"))
            
        if 'reference' in item and item['reference']:
            body_contents.append(BoxComponent(layout="vertical", margin="md", backgroundColor="#f0f0f0", height="1px"))
            body_contents.append(TextComponent(text="แหล่งข้อมูลอ้างอิง:", size="xxs", color="#888888", margin="sm"))
            body_contents.append(TextComponent(text=item['reference'], size="xxs", wrap=True, color="#aaaaaa"))
            
        if 'pdf_url' in item and item['pdf_url']:
            body_contents.append(ButtonComponent(style="secondary", height="sm", margin="md", color="#e3f2fd", action=URIAction(label="📄 เปิดอ่านเอกสารเต็ม", uri=item['pdf_url'])))

        bubbles.append(BubbleContainer(body=BoxComponent(layout="vertical", contents=body_contents)))
    
    bubbles.append(BubbleContainer(body=BoxComponent(layout="vertical", contents=[
        TextComponent(text="📚 ข้อมูลนี้ใช้เพื่อการศึกษาเท่านั้น", weight="bold", size="sm", color="#1E90FF", margin="md"),
        TextComponent(text="อ้างอิงข้อมูลจาก UpToDate® Lexidrug™ ตามที่แจ้งไว้ในระบบ", size="xs", color="#666666", wrap=True, margin="sm"),
        TextComponent(text="*โปรดปรึกษาแพทย์หรือเภสัชกรก่อนปรับเปลี่ยนขนาดยาทุกครั้ง", size="xxs", color="#aaaaaa", wrap=True, margin="md")
    ])))
    return FlexSendMessage(alt_text="ผลตรวจสอบยาตีกัน", contents=CarouselContainer(contents=bubbles))

def get_dose_adjustment_range(inr, current_dose):
    if inr is None: return current_dose, current_dose, "คงขนาดยาเดิม (ไม่ได้ระบุ INR / ไม่ได้ตรวจ)", 0
    if inr < 1.5: return current_dose*1.1, current_dose*1.2, "เพิ่มขนาดยา 10-20% (INR ต่ำกว่าเป้าหมาย)", 0
    elif 1.5 <= inr <= 1.9: return current_dose*1.05, current_dose*1.1, "เพิ่มขนาดยา 5-10% (INR ต่ำกว่าเป้าหมายเล็กน้อย)", 0
    elif 2.0 <= inr <= 3.0: return current_dose*0.98, current_dose*1.02, "คงขนาดยาเดิม (Target Achieved)", 0
    elif 3.1 <= inr <= 3.9: return current_dose*0.90, current_dose*0.95, "ลดขนาดยา 5-10% (INR สูงกว่าเป้าหมายเล็กน้อย)", 0
    elif 4.0 <= inr <= 4.9: return current_dose*0.895, current_dose*0.905, "⚠️ งดยา 1 วัน (Hold 1 day) แล้วลดขนาดยาลง 10%", 1
    elif 5.0 <= inr <= 8.9: return current_dose*0.84, current_dose*0.86, "⛔️ อันตราย: งดยา 1-2 วัน และควรทาน Vit K1", 2
    elif inr >= 9.0: return None, None, "🚨 EMERGENCY: หยุดยาและรีบพบแพทย์ทันที เพื่อรับ Vit K1", 7
    return current_dose, current_dose, "ปรึกษาแพทย์", 0

def get_single_drug_daily_options(available_tabs):
    options = {0: (0, 0)}
    for tab in available_tabs:
        for multiplier in [0.5, 1.0, 1.5, 2.0]:
            dose_val = tab * multiplier
            if dose_val not in options: options[dose_val] = (tab, multiplier)     
    return options

def find_best_schedule_in_range(min_weekly, max_weekly, available_tabs):
    daily_opts_map = get_single_drug_daily_options(available_tabs)
    possible_doses = sorted(list(daily_opts_map.keys()))
    candidates = []
    for dose_a, dose_b, dose_c in itertools.combinations_with_replacement(possible_doses, 3):
        active_doses = [d for d in [dose_a, dose_b, dose_c] if d > 0]
        if active_doses and (max(active_doses) - min(active_doses)) > 2.0: continue 
        for count_a in range(8):
            for count_b in range(8 - count_a):
                count_c = 7 - count_a - count_b
                weekly_sum = (dose_a * count_a) + (dose_b * count_b) + (dose_c * count_c)
                if min_weekly <= weekly_sum <= max_weekly:
                    active_days = 0
                    if dose_a > 0: active_days += count_a
                    if dose_b > 0: active_days += count_b
                    if dose_c > 0: active_days += count_c
                    if active_days >= 5:
                        schedule_list = [dose_a]*count_a + [dose_b]*count_b + [dose_c]*count_c
                        final_active_doses = [d for d in schedule_list if d > 0]
                        if final_active_doses and (max(final_active_doses) - min(final_active_doses)) > 2.0: continue
                        pill_summary = {}
                        for d in schedule_list:
                            if d > 0:
                                t_size, t_count = daily_opts_map.get(d, (0,0))
                                pill_summary[t_size] = pill_summary.get(t_size, 0) + t_count
                        candidates.append({"schedule": schedule_list, "sum": weekly_sum, "unique_count": len(set(schedule_list)), "pill_summary": pill_summary, "active_days": active_days})
    if not candidates: return None, 0, {}
    target_mid = (min_weekly + max_weekly) / 2
    candidates.sort(key=lambda x: (-x['active_days'], abs(x['sum'] - target_mid), x['unique_count']))
    best_candidate = candidates[0]
    return best_candidate['schedule'], best_candidate['sum'], best_candidate['pill_summary']

def build_strict_schedule_flex(final_dose, schedule_list, available_tabs, pill_summary, inr=None, previous_dose=None, adjustment_message=None):
    daily_opts_map = get_single_drug_daily_options(available_tabs)
    days = ['จ', 'อ', 'พ', 'พฤ', 'ศ', 'ส', 'อา']
    items = []
    header_color = "#FF3333" if "งด" in adjustment_message else "#00B900"
    
    info_box = [TextComponent(text=f"🔹 ขนาดยาเดิม: {previous_dose} mg/สัปดาห์", size="sm", color="#555555")]
    if inr is not None:
        info_box.insert(0, TextComponent(text=f"🔹 INR: {inr}", size="sm", color="#555555"))
        info_box.append(TextComponent(text=f"🔹 ใหม่: {final_dose:.1f} mg/สัปดาห์", size="sm", weight="bold", color="#1DB446"))
    else: info_box.insert(0, TextComponent(text=f"🔹 INR: ไม่ระบุ", size="sm", color="#aaaaaa"))
    
    info_box.append(TextComponent(text=f"📝 {adjustment_message}", size="sm", wrap=True, margin="sm", color="#FF0000" if "งด" in adjustment_message else "#aaaaaa"))
    items.extend(info_box)
    items.append(BoxComponent(layout="vertical", margin="md", backgroundColor="#e0e0e0", height="1px"))

    for i in range(7):
        dose = schedule_list[i]
        if dose == 0: text_detail, text_color, bg_color = "❌ งดยา", "#ff0000", "#ffeeee"
        else:
            tab_size, pill_count = daily_opts_map.get(dose, (0, 0))
            pill_str = "ครึ่ง" if pill_count == 0.5 else f"{pill_count:.1f}"
            if pill_count.is_integer(): pill_str = str(int(pill_count))
            text_detail, text_color, bg_color = f"{dose} mg ({tab_size}mg x {pill_str} เม็ด)", "#000000", "#ffffff"
        items.append(BoxComponent(layout="horizontal", backgroundColor=bg_color, contents=[TextComponent(text=days[i], weight="bold", flex=1, color="#333333"), TextComponent(text=text_detail, size="sm", flex=4, color=text_color)], paddingAll="xs", cornerRadius="sm", margin="xs"))

    summary_lines = [f"• ยา {k} mg: รวม {v} เม็ด/สัปดาห์" for k, v in sorted(pill_summary.items())]
    items.append(BoxComponent(layout="vertical", margin="md", backgroundColor="#e0e0e0", height="1px"))
    items.append(TextComponent(text="สรุปจำนวนยาต่อสัปดาห์", weight="bold", size="sm", margin="md"))
    items.append(TextComponent(text="\n".join(summary_lines) if summary_lines else "หยุดยาทั้งสัปดาห์", wrap=True, size="sm", color="#666666", margin="sm"))
    items.append(BoxComponent(layout="vertical", margin="md", backgroundColor="#e0e0e0", height="1px"))
    items.append(TextComponent(text="ต้องการคำนวณจำนวนเม็ดทั้งหมด?", size="xs", color="#aaaaaa", align="center", margin="sm"))
    items.append(BoxComponent(layout="horizontal", margin="sm", contents=[{"type": "button", "action": DatetimePickerAction(label="📅 เลือกวันนัดหมาย", data="action=select_date", mode="date"), "style": "primary", "color": "#1E90FF", "height": "sm"}]))
    
    if inr is not None:
        items.append(BoxComponent(layout="vertical", margin="md", backgroundColor="#e0e0e0", height="1px"))
        if TABLE_IMAGE_URL: items.append(ImageComponent(url=TABLE_IMAGE_URL, size="full", aspectRatio="1.6:1", aspectMode="cover", margin="md", action=URIAction(uri=TABLE_PDF_URL)))
        items.append(TextComponent(text="อ้างอิงจากสมาคมแพทย์โรคหัวใจแห่งประเทศไทย", wrap=True, size="xxs", color="#aaaaaa", margin="sm", align="center"))
    
    return FlexSendMessage(alt_text="ตารางยา Warfarin", contents=BubbleContainer(header=BoxComponent(layout="vertical", backgroundColor=header_color, contents=[TextComponent(text="ตารางรับประทานยา", weight="bold", size="lg", color="#FFFFFF", align="center")]), body=BoxComponent(layout="vertical", contents=items)))

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try: handler.handle(body, signature)
    except InvalidSignatureError: abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id

    # 🌟 ฟีเจอร์อัปเดตข้อมูลยาจาก Google Sheets ทันที
    if text == "อัปเดตยา":
        success = load_drug_db()
        if success:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✅ อัปเดตฐานข้อมูลยาจาก Google Sheets สำเร็จ!\nระบบค้นพบยาทั้งหมด: {len(INTERACTION_DB)} รายการ"))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ ไม่สามารถอัปเดตข้อมูลได้ โปรดตรวจสอบว่าตั้งชื่อชีตว่า 'DI database' ถูกต้องและไม่มีการเว้นวรรคส่วนเกินครับ"))
        return

    if text.lower() == "ping":
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"🏓 Pong! \nเวลา: {datetime.now().strftime('%H:%M:%S')}"))
        return

    if text in ["เช็กยาตีกัน", "เช็กยา"]:
        flex = FlexSendMessage(alt_text="ค้นหายา", contents=BubbleContainer(body=BoxComponent(layout="vertical", contents=[TextComponent(text="🔍 เช็กยาตีกัน", weight="bold", size="lg", color="#1E90FF", align="center"), TextComponent(text="พิมพ์ชื่อยาหลายตัวพร้อมกันได้", wrap=True, size="xs", color="#aaaaaa", align="center", margin="sm"), ButtonComponent(style="primary", color="#00C851", height="sm", margin="md", action=URIAction(label="เปิดระบบค้นหา", uri=f"https://liff.line.me/{LIFF_ID_INTERACTION}"))])))
        line_bot_api.reply_message(event.reply_token, flex)
        return
        
    if text == "ช่วยจัดยา warfarin":
        flex = FlexSendMessage(alt_text="เปิดหน้าจัดยา", contents=BubbleContainer(body=BoxComponent(layout="vertical", contents=[TextComponent(text="💊 ระบบช่วยจัดยา", weight="bold", size="lg", color="#1E90FF", align="center"), TextComponent(text="กดปุ่มด้านล่างเพื่อเลือกยาและกรอกข้อมูล", wrap=True, size="xs", color="#aaaaaa", align="center", margin="sm"), ButtonComponent(style="primary", color="#00C851", height="sm", margin="md", action=URIAction(label="กรอกข้อมูลจัดยา", uri=f"https://liff.line.me/{LIFF_ID_CALCULATOR}"))])))
        line_bot_api.reply_message(event.reply_token, flex)
        return

    if text.startswith("🔍 ตรวจสอบยา:"):
        drugs_str = text.replace("🔍 ตรวจสอบยา:", "").strip()
        log_to_sheets("เช็กยาตีกัน", f"ค้นหา: {drugs_str}", "No GPS")
        
        analysis_results = analyze_drug_list(drugs_str)
        line_bot_api.reply_message(event.reply_token, build_analysis_flex(analysis_results))
        return
    
    is_eng = re.match(r'^[a-zA-Z\s,]+$', text)
    if text.startswith("เช็กยา ") or is_eng:
        keyword = text.replace("เช็กยา ", "").strip()
        log_to_sheets("เช็กยาตีกัน (พิมพ์เอง)", f"ค้นหา: {keyword}", "No GPS")
        results = analyze_drug_list(keyword)
        line_bot_api.reply_message(event.reply_token, build_analysis_flex(results))
        return

    if text.startswith("📝 ข้อมูลจัดยา:"):
        try:
            parts = text.replace("📝 ข้อมูลจัดยา:", "").strip().split("|")
            pills_str = parts[0].strip()
            dose_str = parts[1].strip()
            inr_str = parts[2].strip()
            
            available_tabs = [float(x) for x in pills_str.split(",")]
            weekly_dose = float(dose_str)
            inr = None if (inr_str == "Unknown" or inr_str == "ไม่มี/ไม่ทราบ INR") else float(inr_str)

            min_t, max_t, msg, skip = get_dose_adjustment_range(inr, weekly_dose)
            log_to_sheets("คำนวณยา", f"Dose เดิม: {weekly_dose}mg | INR: {inr_str} | ยาที่มี: {pills_str}mg | แนะนำ: {msg}", "No GPS")

            if min_t is None and inr is not None:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
                return

            schedule, final, summary = find_best_schedule_in_range(min_t, max_t, available_tabs)
            if schedule:
                if skip: 
                    for i in range(min(skip, 7)): schedule[i] = 0
                non_zeros = sorted([x for x in schedule if x > 0], reverse=True)
                zeros = [x for x in schedule if x == 0]
                schedule = non_zeros + zeros

                user_sessions[user_id] = {'pill_summary': summary, 'timestamp': datetime.now()}
                line_bot_api.reply_message(event.reply_token, build_strict_schedule_flex(final, schedule, available_tabs, summary, inr, weekly_dose, msg))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"⚠️ คำนวณช่วง {min_t:.1f}-{max_t:.1f} mg แต่ไม่สามารถจัดยาที่มีให้ลงล็อกได้"))
        except Exception as e:
            print(f"Error logic: {e}")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ เกิดข้อผิดพลาดในการอ่านข้อมูล"))
        return

@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    data = event.postback.data
    if data == "action=select_date":
        if user_id not in user_sessions or 'pill_summary' not in user_sessions[user_id]:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ ข้อมูลหมดอายุ กรุณาเริ่มจัดยาใหม่"))
            return
        selected_date = datetime.strptime(event.postback.params['date'], '%Y-%m-%d').date()
        today = date.today()
        days_diff = (selected_date - today).days
        if days_diff <= 0:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ กรุณาเลือกวันในอนาคต"))
            return
        weeks_ceiling = math.ceil(days_diff / 7)
        pill_summary = user_sessions[user_id]['pill_summary']
        result_lines = []
        for strength, count_per_week in pill_summary.items():
            total_pills = count_per_week * weeks_ceiling
            result_lines.append(f"💊 ยา {strength} mg: {count_per_week:g}x{weeks_ceiling} = {total_pills:.0f} เม็ด")
        msg = (f"📅 **สรุปยอดเบิกยา**\nนัด: {selected_date.strftime('%d/%m/%Y')} ({days_diff} วัน)\nคิดเป็น: {weeks_ceiling} สัปดาห์ (ปัดขึ้น)\n-----------------\n{chr(10).join(result_lines)}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))

# ⏰ ระบบปลุกเซิร์ฟเวอร์อัตโนมัติ (Keep-alive) ป้องกันเซิร์ฟเวอร์หลับ
def keep_alive():
    url = "https://warfy-bot.onrender.com/"
    while True:
        try:
            requests.get(url)
            print("⏰ Ping! ปลุกเซิร์ฟเวอร์สำเร็จ")
        except Exception as e:
            print("⚠️ Ping Failed:", e)
        time.sleep(300) # ทำงานทุก 5 นาที (300 วินาที)

if __name__ == "__main__":
    # สั่งให้ระบบปลุกทำงานเบื้องหลังทันทีที่เปิดแอป
    threading.Thread(target=keep_alive, daemon=True).start()
    app.run(port=5000)
