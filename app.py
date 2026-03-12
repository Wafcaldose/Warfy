import json
import gspread
from google.oauth2.service_account import Credentials
from flask import Flask, request, abort, render_template_string
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FlexSendMessage, BubbleContainer, BoxComponent, TextComponent,
    ImageComponent, URIAction, DatetimePickerAction, PostbackEvent,
    CarouselContainer, ButtonComponent, PostbackAction
)
import itertools
import re
import math
from datetime import datetime, date

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
# 📊 ตั้งค่า Google Sheets
# ==========================================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

try:
    creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    gc = gspread.authorize(creds)
    sheet = gc.open("Warfy_Logs").sheet1
    print("✅ Google Sheets Connected Successfully!")
except Exception as e:
    print(f"⚠️ Google Sheets Connection Failed: {e}")
    sheet = None

def log_to_sheets(feature, details, location):
    if sheet is None: return 
    try:
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        maps_link = location
        if location and "," in location and "Denied" not in location and "No GPS" not in location:
            maps_link = f"https://www.google.com/maps?q={location}"
        row_data = [timestamp, feature, details, maps_link]
        sheet.append_row(row_data)
        print("📝 Logged to Google Sheets!")
    except Exception as e:
        print(f"⚠️ Error logging to sheets: {e}")

# ==========================================
# 💊 ฐานข้อมูลยา (อัปเดต Rating X พร้อมลิงก์ PDF)
# ==========================================
INTERACTION_DB = {
    # --- Category X (Avoid - สีแดง) พร้อมลิงก์ PDF ---
    "abciximab": {
        "name": "Abciximab", "risk": "X", "effect": "Bleeding Risk", 
        "detail": "เพิ่มความเสี่ยงในการเกิดภาวะเลือดออกอย่างรุนแรง", 
        "management": "หลีกเลี่ยงการใช้ร่วมกัน (Avoid combination) เนื่องจากเสี่ยงเลือดออกสูงมาก", 
        "reference": "UpToDate Lexidrug: Abciximab", 
        "pdf_url": "https://drive.google.com/file/d/15V88vAokwnIgx9qYnUNYVBgWsXz-mbaP/view?usp=drive_link"
    },
    "alteplase": {
        "name": "Alteplase", "risk": "X", "effect": "Bleeding Risk", 
        "detail": "ยาละลายลิ่มเลือด เพิ่มความเสี่ยงเลือดออกรุนแรง ห้ามใช้ร่วมกัน", 
        "management": "ห้ามใช้ร่วมกันเด็ดขาด ยกเว้นกรณีฉุกเฉินช่วยชีวิตที่แพทย์สั่งให้ระงับ Warfarin", 
        "reference": "UpToDate Lexidrug: Alteplase", 
        "pdf_url": "https://drive.google.com/file/d/1j_1wTVE-sbTiMg3ZbZgRoUmlP0SXAjRj/view?usp=drive_link"
    },
    "defibrotide": {
        "name": "Defibrotide", "risk": "X", "effect": "Bleeding Risk", 
        "detail": "เพิ่มความเสี่ยงในการเกิดภาวะเลือดออก", 
        "management": "หลีกเลี่ยงการใช้ร่วมกันอย่างเด็ดขาด", 
        "reference": "UpToDate Lexidrug: Defibrotide", 
        "pdf_url": "https://drive.google.com/file/d/1L-FCZvz2mzhJU3zRzfZOLroBfWrDJVzd/view?usp=drive_link"
    },
    "hemin": {
        "name": "Hemin", "risk": "X", "effect": "Altered Anticoagulant Effect", 
        "detail": "อาจรบกวนประสิทธิภาพของยาต้านการแข็งตัวของเลือด", 
        "management": "หลีกเลี่ยงการใช้ร่วมกัน", 
        "reference": "UpToDate Lexidrug: Hemin", 
        "pdf_url": "https://drive.google.com/file/d/1kh69ua1CxyM4TrTNPKySL2Ud4R9o0iOq/view?usp=drive_link"
    },
    "mifepristone": {
        "name": "Mifepristone", "risk": "X", "effect": "Bleeding Risk", 
        "detail": "เพิ่มความเสี่ยงเลือดออกรุนแรงทางช่องคลอด", 
        "management": "หลีกเลี่ยงการใช้ร่วมกับ Warfarin โดยเฉพาะเมื่อใช้ในข้อบ่งชี้บางประการ", 
        "reference": "UpToDate Lexidrug: Mifepristone", 
        "pdf_url": "https://drive.google.com/file/d/1z-eGMjZapQ54Kd7Q_Xb7gBrDuXNNDk-r/view?usp=drive_link"
    },
    "omacetaxine": {
        "name": "Omacetaxine", "risk": "X", "effect": "Bleeding Risk", 
        "detail": "รบกวนการแข็งตัวของเลือดและเพิ่มความเสี่ยงเลือดออก", 
        "management": "หลีกเลี่ยงการใช้ร่วมกัน", 
        "reference": "UpToDate Lexidrug: Omacetaxine", 
        "pdf_url": "https://drive.google.com/file/d/1K56QeEQzJQB3VU3obQaDrDLwc0nPcd3w/view?usp=drive_link"
    },
    "oxatomide": {
        "name": "Oxatomide", "risk": "X", "effect": "Increased Risk of Adverse Effects", 
        "detail": "อาจเกิดปฏิกิริยาระหว่างยาที่รุนแรง", 
        "management": "หลีกเลี่ยงการใช้ร่วมกัน", 
        "reference": "UpToDate Lexidrug: Oxatomide", 
        "pdf_url": "https://drive.google.com/file/d/1ujGEx2gLE_r2R0nOC5uWg4IGlfnZWG9_/view?usp=drive_link"
    },
    "streptokinase": {
        "name": "Streptokinase", "risk": "X", "effect": "Bleeding Risk", 
        "detail": "ยาละลายลิ่มเลือด เพิ่มความเสี่ยงเลือดออกรุนแรง ห้ามใช้ร่วมกัน", 
        "management": "ห้ามใช้ร่วมกันเด็ดขาด", 
        "reference": "UpToDate Lexidrug: Streptokinase", 
        "pdf_url": "https://drive.google.com/file/d/1TPEFDyOcZ4wDOfRMgz9zhKt3Du47PVZ2/view?usp=drive_link"
    },
    "tenecteplase": {
        "name": "Tenecteplase", "risk": "X", "effect": "Bleeding Risk", 
        "detail": "ยาละลายลิ่มเลือด เพิ่มความเสี่ยงเลือดออกอย่างรุนแรง", 
        "management": "หลีกเลี่ยงการใช้ร่วมกัน (ขึ้นอยู่กับข้อบ่งชี้ทางคลินิก)", 
        "reference": "UpToDate Lexidrug: Tenecteplase", 
        "pdf_url": "https://drive.google.com/file/d/1hl535UMybwMHyJ44E5M7sS9BebCPcm9Q/view?usp=drive_link"
    },
    "vorapaxar": {
        "name": "Vorapaxar", "risk": "X", "effect": "Bleeding Risk", 
        "detail": "ยาต้านเกล็ดเลือดรุนแรง ห้ามใช้ร่วมกัน", 
        "management": "ห้ามใช้ร่วมกันเด็ดขาด เนื่องจากความเสี่ยงตกเลือดในสมอง", 
        "reference": "UpToDate Lexidrug: Vorapaxar", 
        "pdf_url": "https://drive.google.com/file/d/1rKNzzEMjL-010dv18a77vAksd3edLIC8/view?usp=drive_link"
    },

    # --- Category D (Modify - สีส้ม) ---
    "amiodarone": {"name": "Amiodarone", "risk": "D", "effect": "Incr. INR (Significant)", "detail": "ยับยั้งการทำลาย Warfarin อย่างมาก ทำให้ INR พุ่งสูง พิจารณาลดขนาด Warfarin 30-50%"},
    "carbamazepine": {"name": "Carbamazepine", "risk": "D", "effect": "Decr. INR", "detail": "เร่งการทำลาย Warfarin ทำให้ INR ต่ำลง ต้องติดตามและอาจต้องเพิ่มขนาดยา"},
    "fluconazole": {"name": "Fluconazole", "risk": "D", "effect": "Incr. INR", "detail": "เพิ่มระดับ Warfarin อย่างมีนัยสำคัญ พิจารณาลดขนาด Warfarin"},
    "metronidazole": {"name": "Metronidazole", "risk": "D", "effect": "Incr. INR (Significant)", "detail": "เพิ่มระดับ Warfarin อย่างมาก พิจารณาลดขนาด Warfarin 30% หรือมากกว่า"},
    "rifampin": {"name": "Rifampin", "risk": "D", "effect": "Decr. INR (Significant)", "detail": "ลดระดับ Warfarin อย่างมากและรวดเร็ว อาจต้องเพิ่มขนาดยา 100-200% (ปรึกษาแพทย์)"},
    "bactrim": {"name": "Co-trimoxazole (Bactrim)", "risk": "D", "effect": "Incr. INR (Significant)", "detail": "เสี่ยง INR พุ่งสูงมาก พิจารณาลดขนาด Warfarin และติดตามใกล้ชิด"},
    "sulfamethoxazole": {"name": "Sulfamethoxazole", "risk": "D", "effect": "Incr. INR", "detail": "ส่วนประกอบหลักใน Bactrim เพิ่ม INR สูง"},
    
    # --- Category C (Monitor - สีเหลือง) ---
    "amoxicillin": {"name": "Amoxicillin", "risk": "C", "effect": "Poss. Incr. INR", "detail": "อาจเพิ่ม INR ในบางราย (ลด Vit K จากแบคทีเรียในลำไส้) ควรติดตามผล"},
    "aspirin": {"name": "Aspirin", "risk": "C", "effect": "Bleeding Risk", "detail": "เพิ่มความเสี่ยงเลือดออก (Antiplatelet) โดยอาจไม่เปลี่ยนค่า INR"},
    "azithromycin": {"name": "Azithromycin", "risk": "C", "effect": "Poss. Incr. INR", "detail": "อาจเพิ่ม INR ได้ ควรติดตามผล"},
    "celecoxib": {"name": "Celecoxib", "risk": "C", "effect": "Bleeding Risk", "detail": "NSAIDs เพิ่มความเสี่ยงเลือดออก"},
    "ciprofloxacin": {"name": "Ciprofloxacin", "risk": "C", "effect": "Poss. Incr. INR", "detail": "อาจยับยั้งการทำลาย Warfarin ควรติดตาม INR"},
    "clopidogrel": {"name": "Clopidogrel", "risk": "C", "effect": "Bleeding Risk", "detail": "เพิ่มความเสี่ยงเลือดออก (Antiplatelet) ระวังการใช้ร่วมกัน"},
    "diclofenac": {"name": "Diclofenac", "risk": "C", "effect": "Bleeding Risk", "detail": "NSAIDs เพิ่มความเสี่ยงเลือดออกและระคายเคืองกระเพาะ"},
    "ibuprofen": {"name": "Ibuprofen", "risk": "C", "effect": "Bleeding Risk", "detail": "NSAIDs เพิ่มความเสี่ยงเลือดออก"},
    "levofloxacin": {"name": "Levofloxacin", "risk": "C", "effect": "Poss. Incr. INR", "detail": "อาจเพิ่มฤทธิ์ Warfarin ควรติดตาม INR"},
    "naproxen": {"name": "Naproxen", "risk": "C", "effect": "Bleeding Risk", "detail": "NSAIDs เพิ่มความเสี่ยงเลือดออก"},
    "omeprazole": {"name": "Omeprazole", "risk": "C", "effect": "Variable", "detail": "ผลต่อ INR ไม่แน่นอน (อาจเพิ่มในบางราย) ควรติดตามผล"},
    "paracetamol": {"name": "Paracetamol", "risk": "C", "effect": "Poss. Incr. INR", "detail": "หากทาน >2g/วัน (4 เม็ด) ต่อเนื่องหลายวัน อาจเพิ่ม INR ได้"},
    "simvastatin": {"name": "Simvastatin", "risk": "C", "effect": "Poss. Incr. INR", "detail": "อาจเพิ่ม INR เล็กน้อย ควรติดตามผล"},
    "tramadol": {"name": "Tramadol", "risk": "C", "effect": "Poss. Incr. INR", "detail": "มีรายงานการเพิ่ม INR ในผู้ป่วยบางราย"},

    # --- Category B (No Action Needed - สีฟ้า) ---
    "amlodipine": {"name": "Amlodipine", "risk": "B", "effect": "No Action", "detail": "ไม่พบปฏิกิริยาที่มีนัยสำคัญทางคลินิก (ปลอดภัย)"},
    "digoxin": {"name": "Digoxin", "risk": "B", "effect": "No Action", "detail": "ปลอดภัยเมื่อใช้ร่วมกัน"},
    "furosemide": {"name": "Furosemide", "risk": "B", "effect": "No Action", "detail": "ยาขับปัสสาวะ ปลอดภัยเมื่อใช้ร่วมกัน"},
    "hydrochlorothiazide": {"name": "Hydrochlorothiazide", "risk": "B", "effect": "No Action", "detail": "ยาขับปัสสาวะ ปลอดภัย"},
    "pantoprazole": {"name": "Pantoprazole", "risk": "B", "effect": "No Action", "detail": "ยาลดกรดที่ปลอดภัยกว่า Omeprazole เล็กน้อย"},
    "propranolol": {"name": "Propranolol", "risk": "B", "effect": "No Action", "detail": "ปลอดภัยเมื่อใช้ร่วมกัน"},
    "spironolactone": {"name": "Spironolactone", "risk": "B", "effect": "No Action", "detail": "ปลอดภัยเมื่อใช้ร่วมกัน"},
    "oseltamivir": {"name": "Oseltamivir", "risk": "B", "effect": "No Action", "detail": "ยาต้านไวรัสไข้หวัดใหญ่ ปลอดภัย"},

    # --- Category A (No Known Interaction - สีเขียว) ---
    "atorvastatin": {"name": "Atorvastatin", "risk": "A", "effect": "Safe", "detail": "ไม่พบปฏิกิริยาระหว่างยา (ปลอดภัยที่สุดในกลุ่ม Statin)"}
}

RISK_COLOR_MAP = {
    "X": "#D32F2F", "D": "#EF6C00", "C": "#FBC02D", "B": "#0288D1", "A": "#388E3C"
}

# ==========================================
# 🌐 LIFF HTML
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
            if ((input.value.match(/\./g) || []).length > 1) { input.value = input.value.replace(/\.+$/, ""); }
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
            if(document.getElementById('unknownInr').checked) document.getElementById('inrValue').value = '';
        }

        function getLocation() {
            return new Promise((resolve) => {
                if (!navigator.geolocation) {
                    resolve("No GPS"); 
                } else {
                    navigator.geolocation.getCurrentPosition(
                        (position) => { resolve(`${position.coords.latitude},${position.coords.longitude}`); },
                        (error) => { resolve("Location Denied"); },
                        { enableHighAccuracy: true, timeout: 5000 }
                    );
                }
            });
        }

        async function sendData() {
            if (!liff.isInClient()) return alert("กรุณาเปิดในแอป LINE เท่านั้น");
            if (selected.size === 0) return alert("กรุณาเลือกขนาดยาที่มี");
            let dose = document.getElementById('weeklyDose').value;
            if (!dose) return alert("กรุณากรอกขนาดยาเดิม");
            let unk = document.getElementById('unknownInr').checked;
            let inr = document.getElementById('inrValue').value;
            if (!unk && !inr) return alert("กรุณากรอก INR");
            
            const btn = document.getElementById('confirmBtn');
            const originalText = btn.innerText;
            btn.innerText = "กำลังหาพิกัด📍...";

            let location = await getLocation(); 
            let msg = `📝 ข้อมูลจัดยา: ${Array.from(selected).sort().join(",")} | ${dose} | ${unk ? "Unknown" : inr} | ${location}`;
            
            try {
                await liff.sendMessages([{type:'text', text:msg}]);
                liff.closeWindow();
            } catch (err) { 
                alert("Error: " + err); 
                btn.innerText = originalText;
            }
        }
        liff.init({ liffId: "{{ liff_id }}" }).then(() => { if (!liff.isLoggedIn()) liff.login(); });
    </script>
</body>
</html>
"""

# ✅ ปรับข้อความหัวข้อ H3 แล้ว
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
            <input type="text" id="drugInput" placeholder="พิมพ์ชื่อยา (เช่น Para...)" autocomplete="off">
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
            const matches = drugDB.filter(d => d.toLowerCase().includes(val) && !selectedDrugs.has(d));
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

        function addDrug(drugKey) {
            selectedDrugs.add(drugKey);
            input.value = ''; dropdown.style.display = 'none'; renderTags();
        }
        function removeDrug(drugKey) {
            selectedDrugs.delete(drugKey); renderTags();
        }
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

        function getLocation() {
            return new Promise((resolve) => {
                if (!navigator.geolocation) {
                    resolve("No GPS");
                } else {
                    navigator.geolocation.getCurrentPosition(
                        (position) => { resolve(`${position.coords.latitude},${position.coords.longitude}`); },
                        (error) => { resolve("Location Denied"); },
                        { enableHighAccuracy: true, timeout: 5000 }
                    );
                }
            });
        }

        async function submitData() {
            if (!liff.isInClient()) return alert("กรุณาใช้งานในแอป LINE เท่านั้น");
            if (selectedDrugs.size === 0) return alert("กรุณาเลือกยาก่อนกดตรวจสอบ");
            
            const originalText = checkBtn.innerText;
            checkBtn.innerText = "กำลังดึงพิกัด📍..."; 

            let location = await getLocation(); 
            const drugList = Array.from(selectedDrugs).join(", ");
            const msg = `🔍 ตรวจสอบยา: ${drugList} | ${location}`; 
            
            try {
                await liff.sendMessages([{ type: 'text', text: msg }]);
                liff.closeWindow();
            } catch (err) {
                alert("เกิดข้อผิดพลาดในการส่งข้อมูล: " + err);
                checkBtn.innerText = originalText;
            }
        }
        liff.init({ liffId: "{{ liff_id }}" })
            .then(() => { if (!liff.isLoggedIn()) liff.login(); })
            .catch(err => { alert("LIFF Init Error: " + err); });
    </script>
</body>
</html>
"""

# ==========================================
# 🛤️ Routes & Logic Helpers
# ==========================================
@app.route("/")
def home(): return "✅ Warfy Server is Running!"

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
    if not results: return TextSendMessage(text="✅ ไม่พบปฏิกิริยาระหว่างยาในฐานข้อมูล Lexicomp (เบื้องต้นปลอดภัย หรือสะกดผิด)\n\n*ผลลัพธ์นี้อ้างอิงจากฐานข้อมูลยาหลักเท่านั้น")
    bubbles = []
    risk_order = {'X':0, 'D':1, 'C':2, 'B':3, 'A':4}
    results.sort(key=lambda x: risk_order.get(x['risk'], 5))

    for item in results:
        risk = item['risk']
        color = RISK_COLOR_MAP.get(risk, "#999999")
        risk_text_map = {
            "X": "X - หลีกเลี่ยง (Avoid)", "D": "D - ปรับเปลี่ยน (Modify)",
            "C": "C - ติดตามผล (Monitor)", "B": "B - ไม่ต้องกังวล", "A": "A - ปลอดภัย"
        }
        
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

        if risk in ['X', 'D']:
            if 'management' in item and item['management']:
                body_contents.append(TextComponent(text="การจัดการ (Management):", size="xs", color="#D32F2F", margin="md", weight="bold"))
                body_contents.append(TextComponent(text=item['management'], size="sm", wrap=True, color="#333333"))
            
            if 'reference' in item and item['reference']:
                body_contents.append(BoxComponent(layout="vertical", margin="md", backgroundColor="#f0f0f0", height="1px"))
                body_contents.append(TextComponent(text="อ้างอิง (Reference):", size="xxs", color="#888888", margin="sm"))
                body_contents.append(TextComponent(text=item['reference'], size="xxs", wrap=True, color="#aaaaaa"))

            if 'pdf_url' in item and item['pdf_url']:
                body_contents.append(ButtonComponent(
                    style="secondary", 
                    height="sm", 
                    margin="md", 
                    color="#e3f2fd",
                    action=URIAction(label="📄 เปิดอ่านเอกสารเต็ม", uri=item['pdf_url'])
                ))

        bubble = BubbleContainer(
            body=BoxComponent(layout="vertical", contents=body_contents)
        )
        bubbles.append(bubble)
    
    bubbles.append(BubbleContainer(body=BoxComponent(layout="vertical", contents=[
        TextComponent(text="📚 แหล่งอ้างอิงหลัก:", weight="bold", size="sm", color="#1E90FF"),
        TextComponent(text="UpToDate® Lexidrug™ (Warfarin Interactions)", size="xs", color="#666666", wrap=True, margin="sm"),
        TextComponent(text="*ข้อมูลเพื่อการศึกษา โปรดปรึกษาแพทย์ก่อนปรับยา", size="xxs", color="#aaaaaa", wrap=True, margin="md")
    ])))
    return FlexSendMessage(alt_text="ผลตรวจสอบยาตีกัน", contents=CarouselContainer(contents=bubbles))

def get_dose_adjustment_range(inr, current_dose):
    if inr is None: return current_dose, current_dose, "คงขนาดยาเดิม (ไม่ได้ระบุ INR / ไม่ได้ตรวจ)", 0
    if inr < 1.5: return current_dose*1.1, current_dose*1.2, "เพิ่มขนาดยา 10-20% (INR ต่ำกว่าเป้าหมาย)", 0
    elif 1.5 <= inr <= 1.9: return current_dose*1.05, current_dose*1.1, "เพิ่มขนาดยา 5-10% (INR ต่ำกว่าเป้าหมายเล็กน้อย)", 0
    elif 2.0 <= inr <= 3.0: return current_dose*0.98, current_dose*1.02, "คงขนาดยาเดิม (Target Achieved)", 0
    elif 3.1 <= inr <= 3.9: return current_dose*0.90, current_dose*0.95, "ลดขนาดยา 5-10% (INR สูงกว่าเป้าหมายเล็กน้อย)", 0
    elif 4.0 <= inr <= 4.9: return current_dose*0.895, current_dose*0.905, "⚠️ งดยา 1 วัน (Hold 1 day) แล้วลดขนาดยาลง 10%", 1
    elif 5.0 <= inr <= 8.9: return current_dose*0.84, current_dose*0.86, "⛔️ อันตราย: งดยา 1-2 วัน และควรทาน Vit K1 (ระบบคำนวณลดขนาดลง ~15%)", 2
    elif inr >= 9.0: return None, None, "🚨 EMERGENCY: หยุดยาและรีบพบแพทย์ทันที เพื่อรับ Vit K1", 7
    return current_dose, current_dose, "ปรึกษาแพทย์", 0

def get_single_drug_daily_options(available_tabs):
    options = {}
    options[0] = (0, 0)
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
        items.append(TextComponent(text="อ้างอิงจากแนวทางการรักษาผู้ป่วยด้วยยาต้านการแข็งตัวของเลือดชนิดรับประทาน สมาคมแพทย์โรคหัวใจแห่งประเทศไทย ในพระบรมราชูปถัมภ์", wrap=True, size="xxs", color="#aaaaaa", margin="sm", align="center"))
    
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

    if text.lower() == "ping":
        current_time = datetime.now().strftime("%H:%M:%S")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"🏓 Pong! \nบอททำงานปกติครับ\nเวลา: {current_time}"))
        return

    if text == "เช็กยาตีกัน" or text == "เช็กยา":
        flex = FlexSendMessage(alt_text="ค้นหายา", contents=BubbleContainer(body=BoxComponent(layout="vertical", contents=[TextComponent(text="🔍 เช็กยาตีกัน", weight="bold", size="lg", color="#1E90FF", align="center"), TextComponent(text="พิมพ์ชื่อยาหลายตัวพร้อมกันได้", wrap=True, size="xs", color="#aaaaaa", align="center", margin="sm"), ButtonComponent(style="primary", color="#00C851", height="sm", margin="md", action=URIAction(label="เปิดระบบค้นหา", uri=f"https://liff.line.me/{LIFF_ID_INTERACTION}"))])))
        line_bot_api.reply_message(event.reply_token, flex)
        return
    if text == "ช่วยจัดยา warfarin":
        flex = FlexSendMessage(alt_text="เปิดหน้าจัดยา", contents=BubbleContainer(body=BoxComponent(layout="vertical", contents=[TextComponent(text="💊 ระบบช่วยจัดยา", weight="bold", size="lg", color="#1E90FF", align="center"), TextComponent(text="กดปุ่มด้านล่างเพื่อเลือกยาและกรอกข้อมูล", wrap=True, size="xs", color="#aaaaaa", align="center", margin="sm"), ButtonComponent(style="primary", color="#00C851", height="sm", margin="md", action=URIAction(label="กรอกข้อมูลจัดยา", uri=f"https://liff.line.me/{LIFF_ID_CALCULATOR}"))])))
        line_bot_api.reply_message(event.reply_token, flex)
        return

    if text.startswith("🔍 ตรวจสอบยา:"):
        parts = text.replace("🔍 ตรวจสอบยา:", "").strip().split("|")
        drugs_str = parts[0].strip()
        location_str = parts[1].strip() if len(parts) > 1 else "No GPS"
        
        log_to_sheets("เช็กยาตีกัน", f"ค้นหา: {drugs_str}", location_str)

        analysis_results = analyze_drug_list(drugs_str)
        line_bot_api.reply_message(event.reply_token, build_analysis_flex(analysis_results))
        return
    
    is_eng = re.match(r'^[a-zA-Z]+$', text)
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
            location_str = parts[3].strip() if len(parts) > 3 else "No GPS"

            available_tabs = [float(x) for x in pills_str.split(",")]
            weekly_dose = float(dose_str)
            inr = None if (inr_str == "Unknown" or inr_str == "ไม่มี/ไม่ทราบ INR") else float(inr_str)

            min_t, max_t, msg, skip = get_dose_adjustment_range(inr, weekly_dose)
            
            details = f"Dose เดิม: {weekly_dose}mg | INR: {inr_str} | ยาที่มี: {pills_str}mg | แนะนำ: {msg}"
            log_to_sheets("คำนวณยา", details, location_str)

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
        except: line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ เกิดข้อผิดพลาดในการอ่านข้อมูล"))
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

if __name__ == "__main__":
    app.run(port=5000)
