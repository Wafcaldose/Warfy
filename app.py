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
# 📊 ตั้งค่า Google Sheets
# ==========================================
sheet = None
if GSHEETS_READY:
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    try:
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        gc = gspread.authorize(creds)
        sheet = gc.open("Warfy_Logs").sheet1
        print("✅ Google Sheets Connected Successfully!")
    except Exception as e:
        print(f"⚠️ Google Sheets Connection Failed: {e}")

def log_to_sheets(feature, details, location="No GPS"):
    if sheet is None: return 
    try:
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        row_data = [timestamp, feature, details, location]
        sheet.append_row(row_data)
        print("📝 Logged to Google Sheets!")
    except Exception as e:
        print(f"⚠️ Error logging to sheets: {e}")

# ==========================================
# 💊 ฐานข้อมูลยา (ฉบับสมบูรณ์)
# ==========================================
INTERACTION_DB = {
    # 🔴 --- Category X (Avoid - ห้ามใช้ร่วมกัน) ---
    "abciximab": {"name": "Abciximab", "risk": "X", "effect": "Bleeding Risk", "detail": "เพิ่มความเสี่ยงในการเกิดภาวะเลือดออกอย่างรุนแรง", "management": "หลีกเลี่ยงการใช้ร่วมกัน (Avoid combination)", "reference": "UpToDate Lexidrug: Abciximab", "pdf_url": "https://drive.google.com/file/d/15V88vAokwnIgx9qYnUNYVBgWsXz-mbaP/view?usp=drive_link"},
    "alteplase": {"name": "Alteplase", "risk": "X", "effect": "Bleeding Risk", "detail": "ยาละลายลิ่มเลือด เพิ่มความเสี่ยงเลือดออกรุนแรง ห้ามใช้ร่วมกัน", "management": "ห้ามใช้ร่วมกันเด็ดขาด", "reference": "UpToDate Lexidrug: Alteplase", "pdf_url": "https://drive.google.com/file/d/1j_1wTVE-sbTiMg3ZbZgRoUmlP0SXAjRj/view?usp=drive_link"},
    "defibrotide": {"name": "Defibrotide", "risk": "X", "effect": "Bleeding Risk", "detail": "เพิ่มความเสี่ยงในการเกิดภาวะเลือดออก", "management": "หลีกเลี่ยงการใช้ร่วมกันอย่างเด็ดขาด", "reference": "UpToDate Lexidrug: Defibrotide", "pdf_url": "https://drive.google.com/file/d/1L-FCZvz2mzhJU3zRzfZOLroBfWrDJVzd/view?usp=drive_link"},
    "hemin": {"name": "Hemin", "risk": "X", "effect": "Altered Anticoagulant Effect", "detail": "อาจรบกวนประสิทธิภาพของยาต้านการแข็งตัวของเลือด", "management": "หลีกเลี่ยงการใช้ร่วมกัน", "reference": "UpToDate Lexidrug: Hemin", "pdf_url": "https://drive.google.com/file/d/1kh69ua1CxyM4TrTNPKySL2Ud4R9o0iOq/view?usp=drive_link"},
    "mifepristone": {"name": "Mifepristone", "risk": "X", "effect": "Bleeding Risk", "detail": "เพิ่มความเสี่ยงเลือดออกรุนแรงทางช่องคลอด", "management": "หลีกเลี่ยงการใช้ร่วมกับ Warfarin", "reference": "UpToDate Lexidrug: Mifepristone", "pdf_url": "https://drive.google.com/file/d/1z-eGMjZapQ54Kd7Q_Xb7gBrDuXNNDk-r/view?usp=drive_link"},
    "omacetaxine": {"name": "Omacetaxine", "risk": "X", "effect": "Bleeding Risk", "detail": "รบกวนการแข็งตัวของเลือดและเพิ่มความเสี่ยงเลือดออก", "management": "หลีกเลี่ยงการใช้ร่วมกัน", "reference": "UpToDate Lexidrug: Omacetaxine", "pdf_url": "https://drive.google.com/file/d/1K56QeEQzJQB3VU3obQaDrDLwc0nPcd3w/view?usp=drive_link"},
    "oxatomide": {"name": "Oxatomide", "risk": "X", "effect": "Increased Risk of Adverse Effects", "detail": "อาจเกิดปฏิกิริยาระหว่างยาที่รุนแรง", "management": "หลีกเลี่ยงการใช้ร่วมกัน", "reference": "UpToDate Lexidrug: Oxatomide", "pdf_url": "https://drive.google.com/file/d/1ujGEx2gLE_r2R0nOC5uWg4IGlfnZWG9_/view?usp=drive_link"},
    "streptokinase": {"name": "Streptokinase", "risk": "X", "effect": "Bleeding Risk", "detail": "ยาละลายลิ่มเลือด เพิ่มความเสี่ยงเลือดออกรุนแรง", "management": "ห้ามใช้ร่วมกันเด็ดขาด", "reference": "UpToDate Lexidrug: Streptokinase", "pdf_url": "https://drive.google.com/file/d/1TPEFDyOcZ4wDOfRMgz9zhKt3Du47PVZ2/view?usp=drive_link"},
    "tenecteplase": {"name": "Tenecteplase", "risk": "X", "effect": "Bleeding Risk", "detail": "ยาละลายลิ่มเลือด เพิ่มความเสี่ยงเลือดออกอย่างรุนแรง", "management": "หลีกเลี่ยงการใช้ร่วมกัน", "reference": "UpToDate Lexidrug: Tenecteplase", "pdf_url": "https://drive.google.com/file/d/1hl535UMybwMHyJ44E5M7sS9BebCPcm9Q/view?usp=drive_link"},
    "vorapaxar": {"name": "Vorapaxar", "risk": "X", "effect": "Bleeding Risk", "detail": "ยาต้านเกล็ดเลือดรุนแรง ห้ามใช้ร่วมกัน", "management": "ห้ามใช้ร่วมกันเด็ดขาด เนื่องจากความเสี่ยงตกเลือดในสมอง", "reference": "UpToDate Lexidrug: Vorapaxar", "pdf_url": "https://drive.google.com/file/d/1rKNzzEMjL-010dv18a77vAksd3edLIC8/view?usp=drive_link"},
    "apixaban": {"name": "Apixaban", "risk": "X", "effect": "Bleeding Risk", "detail": "DOACs ยาต้านการแข็งตัวของเลือด ห้ามใช้ซ้ำซ้อนกับ Warfarin", "management": "หลีกเลี่ยงการใช้ร่วมกัน (ยกเว้นช่วง Bridging therapy ตามแพทย์สั่ง)"},
    "rivaroxaban": {"name": "Rivaroxaban", "risk": "X", "effect": "Bleeding Risk", "detail": "DOACs ยาต้านการแข็งตัวของเลือด ห้ามใช้ซ้ำซ้อนกับ Warfarin", "management": "หลีกเลี่ยงการใช้ร่วมกัน"},
    "dabigatran": {"name": "Dabigatran", "risk": "X", "effect": "Bleeding Risk", "detail": "DOACs ยาต้านการแข็งตัวของเลือด ห้ามใช้ซ้ำซ้อนกับ Warfarin", "management": "หลีกเลี่ยงการใช้ร่วมกัน"},

    # 🟠 --- Category D (Modify - ส่งผลรุนแรง ต้องปรับขนาดยา) ---
    "fluconazole": {"name": "Fluconazole", "risk": "D", "effect": "Incr. INR (Significant)", "detail": "เพิ่มระดับ Warfarin อย่างมาก พิจารณาลดขนาด Warfarin ลง"},
    "ketoconazole": {"name": "Ketoconazole", "risk": "D", "effect": "Incr. INR", "detail": "ยับยั้งเอนไซม์ CYP ทำให้ INR สูงขึ้นมาก"},
    "itraconazole": {"name": "Itraconazole", "risk": "D", "effect": "Incr. INR", "detail": "ยับยั้งเอนไซม์ CYP ทำให้ INR สูงขึ้นมาก"},
    "miconazole": {"name": "Miconazole", "risk": "D", "effect": "Incr. INR (Severe)", "detail": "แม้เป็นยาทาปาก (Oral gel) ก็สามารถดูดซึมและทำให้ INR พุ่งสูงอันตรายได้"},
    "metronidazole": {"name": "Metronidazole", "risk": "D", "effect": "Incr. INR (Significant)", "detail": "เพิ่มระดับ Warfarin อย่างมาก พิจารณาลดขนาด Warfarin 30-50%"},
    "bactrim": {"name": "Co-trimoxazole (Bactrim)", "risk": "D", "effect": "Incr. INR (Significant)", "detail": "เสี่ยง INR พุ่งสูงมาก พิจารณาลดขนาด Warfarin 10-20% ทันทีที่เริ่มยา"},
    "sulfamethoxazole": {"name": "Sulfamethoxazole", "risk": "D", "effect": "Incr. INR", "detail": "ส่วนประกอบหลักใน Bactrim เพิ่ม INR สูง"},
    "clarithromycin": {"name": "Clarithromycin", "risk": "D", "effect": "Incr. INR", "detail": "ยับยั้งการทำลาย Warfarin แนะนำลดขนาดยาและติดตามใกล้ชิด"},
    "erythromycin": {"name": "Erythromycin", "risk": "D", "effect": "Incr. INR", "detail": "ยับยั้งเอนไซม์การทำลาย Warfarin"},
    "rifampin": {"name": "Rifampin", "risk": "D", "effect": "Decr. INR (Significant)", "detail": "เร่งการทำลาย Warfarin อย่างมาก (CYP Inducer) อาจต้องเพิ่มขนาดยา Warfarin 100-200%"},
    "amiodarone": {"name": "Amiodarone", "risk": "D", "effect": "Incr. INR (Significant)", "detail": "ยับยั้งการทำลาย Warfarin อย่างมาก ทำให้ INR พุ่งสูง พิจารณาลดขนาด Warfarin 30-50%"},
    "carbamazepine": {"name": "Carbamazepine", "risk": "D", "effect": "Decr. INR", "detail": "เร่งการทำลาย Warfarin (CYP Inducer) ทำให้ INR ต่ำลง ต้องติดตามและเพิ่มขนาดยา"},
    "phenytoin": {"name": "Phenytoin", "risk": "D", "effect": "Variable (Usually Decr. INR)", "detail": "ช่วงแรกอาจทำให้ INR สูง แต่ระยะยาวจะเร่งการทำลายยา ทำให้ INR ต่ำลงมาก"},
    "phenobarbital": {"name": "Phenobarbital", "risk": "D", "effect": "Decr. INR", "detail": "เร่งเอนไซม์ตับ ทำให้ยา Warfarin ถูกทำลายเร็วขึ้น"},
    "valproic acid": {"name": "Valproic Acid", "risk": "D", "effect": "Incr. INR / Bleeding", "detail": "แย่งจับโปรตีนในเลือดและอาจลดเกล็ดเลือด ทำให้เสี่ยงเลือดออก"},
    "cimetidine": {"name": "Cimetidine", "risk": "D", "effect": "Incr. INR", "detail": "ยาลดกรดที่ยับยั้งเอนไซม์ CYP อย่างแรง แนะนำให้เปลี่ยนไปใช้ Famotidine หรือ PPIs แทน"},
    "capecitabine": {"name": "Capecitabine", "risk": "D", "effect": "Incr. INR (Severe)", "detail": "ยารักษามะเร็ง ทำให้ INR พุ่งสูงรุนแรงถึงขั้นตกเลือดได้"},
    "fluorouracil": {"name": "Fluorouracil (5-FU)", "risk": "D", "effect": "Incr. INR", "detail": "เพิ่มฤทธิ์ Warfarin อย่างมีนัยสำคัญ"},

    # 🟡 --- Category C (Monitor - ใช้ร่วมกันได้แต่ต้องเฝ้าระวัง) ---
    "aspirin": {"name": "Aspirin", "risk": "C", "effect": "Bleeding Risk", "detail": "ต้านเกล็ดเลือด เพิ่มความเสี่ยงเลือดออกในทางเดินอาหาร (INR อาจไม่เปลี่ยน)"},
    "ibuprofen": {"name": "Ibuprofen", "risk": "C", "effect": "Bleeding Risk", "detail": "NSAIDs เพิ่มความเสี่ยงเลือดออกและแผลในกระเพาะ"},
    "naproxen": {"name": "Naproxen", "risk": "C", "effect": "Bleeding Risk", "detail": "NSAIDs เพิ่มความเสี่ยงเลือดออก"},
    "diclofenac": {"name": "Diclofenac", "risk": "C", "effect": "Bleeding Risk", "detail": "NSAIDs เพิ่มความเสี่ยงเลือดออก"},
    "celecoxib": {"name": "Celecoxib", "risk": "C", "effect": "Bleeding Risk", "detail": "NSAIDs แม้ระคายกระเพาะน้อยกว่า แต่ก็ยังเพิ่มความเสี่ยงเลือดออก"},
    "etoricoxib": {"name": "Etoricoxib", "risk": "C", "effect": "Bleeding Risk", "detail": "NSAIDs เพิ่มความเสี่ยงเลือดออก"},
    "meloxicam": {"name": "Meloxicam", "risk": "C", "effect": "Bleeding Risk", "detail": "NSAIDs เพิ่มความเสี่ยงเลือดออก"},
    "mefenamic": {"name": "Mefenamic Acid", "risk": "C", "effect": "Bleeding Risk", "detail": "NSAIDs เพิ่มความเสี่ยงเลือดออก"},
    "paracetamol": {"name": "Paracetamol", "risk": "C", "effect": "Poss. Incr. INR", "detail": "ทานแก้ปวดทั่วไปปลอดภัย แต่หากทาน >2g/วัน ต่อเนื่องหลายวัน อาจทำให้ INR สูงได้"},
    "tramadol": {"name": "Tramadol", "risk": "C", "effect": "Poss. Incr. INR", "detail": "มีรายงานการเพิ่ม INR ในผู้ป่วยบางราย"},
    "amoxicillin": {"name": "Amoxicillin", "risk": "C", "effect": "Poss. Incr. INR", "detail": "อาจเพิ่ม INR ในบางราย (ฆ่าแบคทีเรียที่สร้าง Vit K ในลำไส้)"},
    "augmentin": {"name": "Amoxicillin/Clavulanate (Augmentin)", "risk": "C", "effect": "Poss. Incr. INR", "detail": "อาจทำให้ INR สูงขึ้นได้ ควรติดตามผล"},
    "azithromycin": {"name": "Azithromycin", "risk": "C", "effect": "Poss. Incr. INR", "detail": "ยาฆ่าเชื้อกลุ่ม Macrolide ที่กวน Warfarin น้อยกว่า Clarithromycin แต่ก็ควรติดตาม INR"},
    "ciprofloxacin": {"name": "Ciprofloxacin", "risk": "C", "effect": "Poss. Incr. INR", "detail": "อาจยับยั้งการทำลาย Warfarin ควรติดตาม INR ช่วง 3-5 วันแรก"},
    "levofloxacin": {"name": "Levofloxacin", "risk": "C", "effect": "Poss. Incr. INR", "detail": "กลุ่ม Quinolone อาจทำให้ INR สูงขึ้นได้"},
    "norfloxacin": {"name": "Norfloxacin", "risk": "C", "effect": "Poss. Incr. INR", "detail": "กลุ่ม Quinolone อาจทำให้ INR สูงขึ้นได้"},
    "clindamycin": {"name": "Clindamycin", "risk": "C", "effect": "Poss. Incr. INR", "detail": "เปลี่ยนแปลงแบคทีเรียในลำไส้ อาจมีผลต่อ INR"},
    "doxycycline": {"name": "Doxycycline", "risk": "C", "effect": "Poss. Incr. INR", "detail": "อาจมีผลเพิ่ม INR ควรเฝ้าระวัง"},
    "cephalexin": {"name": "Cephalexin", "risk": "C", "effect": "Poss. Incr. INR", "detail": "อาจเพิ่ม INR เล็กน้อย"},
    "fluoxetine": {"name": "Fluoxetine", "risk": "C", "effect": "Bleeding Risk & Incr. INR", "detail": "ยับยั้งการเกาะกลุ่มของเกล็ดเลือด และอาจยับยั้ง CYP ทำให้ INR สูง"},
    "sertraline": {"name": "Sertraline", "risk": "C", "effect": "Bleeding Risk", "detail": "เพิ่มความเสี่ยงเลือดออก (ผลจาก Serotonin ต่อเกล็ดเลือด)"},
    "escitalopram": {"name": "Escitalopram", "risk": "C", "effect": "Bleeding Risk", "detail": "เพิ่มความเสี่ยงเลือดออก"},
    "venlafaxine": {"name": "Venlafaxine", "risk": "C", "effect": "Bleeding Risk", "detail": "กลุ่ม SNRI เพิ่มความเสี่ยงเลือดออก"},
    "duloxetine": {"name": "Duloxetine", "risk": "C", "effect": "Bleeding Risk", "detail": "กลุ่ม SNRI เพิ่มความเสี่ยงเลือดออก"},
    "omeprazole": {"name": "Omeprazole", "risk": "C", "effect": "Variable", "detail": "ยับยั้ง CYP2C19 อาจทำให้ INR สูงขึ้นในผู้ป่วยบางราย (แนะนำ Pantoprazole แทน)"},
    "esomeprazole": {"name": "Esomeprazole", "risk": "C", "effect": "Variable", "detail": "มีผลยับยั้งเอนไซม์ตับเล็กน้อย ควรติดตาม INR"},
    "simvastatin": {"name": "Simvastatin", "risk": "C", "effect": "Poss. Incr. INR", "detail": "อาจเพิ่มฤทธิ์ Warfarin แนะนำ Atorvastatin จะปลอดภัยกว่า"},
    "rosuvastatin": {"name": "Rosuvastatin", "risk": "C", "effect": "Poss. Incr. INR", "detail": "อาจเพิ่ม INR ได้เล็กน้อยถึงปานกลาง"},
    "allopurinol": {"name": "Allopurinol", "risk": "C", "effect": "Poss. Incr. INR", "detail": "ยาลดกรดยูริค อาจยับยั้งการทำลาย Warfarin ได้"},
    "clopidogrel": {"name": "Clopidogrel", "risk": "C", "effect": "Bleeding Risk", "detail": "ยาต้านเกล็ดเลือด ใช้ร่วมกันได้ตามแพทย์สั่งแต่เพิ่มความเสี่ยงเลือดออกสูง"},
    "levothyroxine": {"name": "Levothyroxine", "risk": "C", "effect": "Incr. INR", "detail": "ยาฮอร์โมนไทรอยด์ อาจเร่งการสลาย Clotting factors ทำให้ INR สูงขึ้น"},

    # 🔵 --- Category B (No Action Needed - ใช้ร่วมกันได้ ไม่ต้องเปลี่ยนยา) ---
    "diltiazem": {"name": "Diltiazem", "risk": "B", "effect": "No Action", "detail": "ยาควบคุมการเต้นหัวใจ ปลอดภัยเมื่อใช้ร่วมกัน"},
    "verapamil": {"name": "Verapamil", "risk": "B", "effect": "No Action", "detail": "ปลอดภัยเมื่อใช้ร่วมกัน"},
    "amlodipine": {"name": "Amlodipine", "risk": "B", "effect": "No Action", "detail": "ยาลดความดัน ปลอดภัย"},
    "digoxin": {"name": "Digoxin", "risk": "B", "effect": "No Action", "detail": "ปลอดภัยเมื่อใช้ร่วมกัน (แต่ต้องตามระดับ Digoxin ในเลือดปกติ)"},
    "furosemide": {"name": "Furosemide", "risk": "B", "effect": "No Action", "detail": "ยาขับปัสสาวะ ปลอดภัยเมื่อใช้ร่วมกัน"},
    "hydrochlorothiazide": {"name": "Hydrochlorothiazide (HCTZ)", "risk": "B", "effect": "No Action", "detail": "ยาขับปัสสาวะ ปลอดภัย"},
    "spironolactone": {"name": "Spironolactone", "risk": "B", "effect": "No Action", "detail": "ยาขับปัสสาวะ ปลอดภัย"},
    "propranolol": {"name": "Propranolol", "risk": "B", "effect": "No Action", "detail": "ยาลดความดัน/คุมหัวใจ ปลอดภัย"},
    "pantoprazole": {"name": "Pantoprazole", "risk": "B", "effect": "No Action", "detail": "ยาลดกรด PPI ที่มีปฏิกิริยากับยาน้อยที่สุด ปลอดภัย"},
    "ezetimibe": {"name": "Ezetimibe", "risk": "B", "effect": "No Action", "detail": "ยาลดไขมันในเลือด ปลอดภัยเมื่อใช้ร่วมกัน"},
    "oseltamivir": {"name": "Oseltamivir", "risk": "B", "effect": "No Action", "detail": "ยาต้านไวรัสไข้หวัดใหญ่ ปลอดภัย"},

    # 🟢 --- Category A (Safe - ปลอดภัย ไม่มีปฏิกิริยา) ---
    "metformin": {"name": "Metformin", "risk": "A", "effect": "Safe", "detail": "ไม่พบปฏิกิริยาระหว่างยา ปลอดภัย"},
    "glipizide": {"name": "Glipizide", "risk": "A", "effect": "Safe", "detail": "ไม่พบปฏิกิริยาระหว่างยา ปลอดภัย"},
    "gliclazide": {"name": "Gliclazide", "risk": "A", "effect": "Safe", "detail": "ไม่พบปฏิกิริยาระหว่างยา ปลอดภัย"},
    "sitagliptin": {"name": "Sitagliptin", "risk": "A", "effect": "Safe", "detail": "ยาเบาหวานกลุ่ม DPP-4 ปลอดภัย"},
    "empagliflozin": {"name": "Empagliflozin", "risk": "A", "effect": "Safe", "detail": "ยาเบาหวานกลุ่ม SGLT2 ปลอดภัย"},
    "insulin": {"name": "Insulin (ทุกชนิด)", "risk": "A", "effect": "Safe", "detail": "ยาฉีดเบาหวาน ปลอดภัย"},
    "losartan": {"name": "Losartan", "risk": "A", "effect": "Safe", "detail": "ไม่พบปฏิกิริยาระหว่างยา ปลอดภัย"},
    "valsartan": {"name": "Valsartan", "risk": "A", "effect": "Safe", "detail": "ไม่พบปฏิกิริยาระหว่างยา ปลอดภัย"},
    "enalapril": {"name": "Enalapril", "risk": "A", "effect": "Safe", "detail": "ไม่พบปฏิกิริยาระหว่างยา ปลอดภัย"},
    "lisinopril": {"name": "Lisinopril", "risk": "A", "effect": "Safe", "detail": "ไม่พบปฏิกิริยาระหว่างยา ปลอดภัย"},
    "atenolol": {"name": "Atenolol", "risk": "A", "effect": "Safe", "detail": "ยาเบต้าบล็อกเกอร์ ปลอดภัย"},
    "metoprolol": {"name": "Metoprolol", "risk": "A", "effect": "Safe", "detail": "ยาเบต้าบล็อกเกอร์ ปลอดภัย"},
    "bisoprolol": {"name": "Bisoprolol", "risk": "A", "effect": "Safe", "detail": "ยาเบต้าบล็อกเกอร์ ปลอดภัย"},
    "cetirizine": {"name": "Cetirizine", "risk": "A", "effect": "Safe", "detail": "ไม่มีผลต่อค่า INR ปลอดภัย"},
    "loratadine": {"name": "Loratadine", "risk": "A", "effect": "Safe", "detail": "ไม่มีผลต่อค่า INR ปลอดภัย"},
    "fexofenadine": {"name": "Fexofenadine", "risk": "A", "effect": "Safe", "detail": "ไม่มีผลต่อค่า INR ปลอดภัย"},
    "chlorpheniramine": {"name": "Chlorpheniramine (CPM)", "risk": "A", "effect": "Safe", "detail": "ยาแก้แพ้รุ่นเก่า ปลอดภัย"},
    "atorvastatin": {"name": "Atorvastatin", "risk": "A", "effect": "Safe", "detail": "ไม่พบปฏิกิริยาระหว่างยา (ปลอดภัยที่สุดในกลุ่ม Statin เมื่อใช้คู่กับ Warfarin)"},
    "pravastatin": {"name": "Pravastatin", "risk": "A", "effect": "Safe", "detail": "กลุ่ม Statin ที่ปลอดภัย ไม่มีผลต่อ Warfarin"},
    "pitavastatin": {"name": "Pitavastatin", "risk": "A", "effect": "Safe", "detail": "กลุ่ม Statin ปลอดภัย"},
    "famotidine": {"name": "Famotidine", "risk": "A", "effect": "Safe", "detail": "ยาลดกรดกลุ่ม H2-blocker ที่ปลอดภัย ไม่มีผลต่อ Warfarin"},
    "domperidone": {"name": "Domperidone", "risk": "A", "effect": "Safe", "detail": "ยาแก้คลื่นไส้อาเจียน ปลอดภัย"},
    "metoclopramide": {"name": "Metoclopramide", "risk": "A", "effect": "Safe", "detail": "ยาแก้คลื่นไส้อาเจียน ปลอดภัย"},
    "gabapentin": {"name": "Gabapentin", "risk": "A", "effect": "Safe", "detail": "ยาแก้ปวดปลายประสาท ปลอดภัย"},
    "pregabalin": {"name": "Pregabalin", "risk": "A", "effect": "Safe", "detail": "ยาแก้ปวดปลายประสาท ปลอดภัย"},
    "salbutamol": {"name": "Salbutamol", "risk": "A", "effect": "Safe", "detail": "ยาขยายหลอดลม ปลอดภัย"},
    "montelukast": {"name": "Montelukast", "risk": "A", "effect": "Safe", "detail": "ยาภูมิแพ้หอบหืด ปลอดภัย"},
    "budesonide": {"name": "Budesonide", "risk": "A", "effect": "Safe", "detail": "ยาสเตียรอยด์สูดดม ปลอดภัย ไม่มีผลต่อระบบเลือด"}
}

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
            let b = document.createElement('button'); 
            b.className = 'pill-btn'; 
            b.innerText = s;
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
    if not results: return TextSendMessage(text="✅ ไม่พบปฏิกิริยาระหว่างยาในฐานข้อมูล Lexicomp (เบื้องต้นปลอดภัย หรือสะกดผิด)\n\n*ผลลัพธ์นี้อ้างอิงจากฐานข้อมูลยาหลักเท่านั้น")
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

        if risk in ['X', 'D']:
            if 'management' in item and item['management']:
                body_contents.append(TextComponent(text="การจัดการ (Management):", size="xs", color="#D32F2F", margin="md", weight="bold"))
                body_contents.append(TextComponent(text=item['management'], size="sm", wrap=True, color="#333333"))
            if 'reference' in item and item['reference']:
                body_contents.append(BoxComponent(layout="vertical", margin="md", backgroundColor="#f0f0f0", height="1
