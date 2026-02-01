from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FlexSendMessage, BubbleContainer, BoxComponent, TextComponent,
    ImageComponent, URIAction, DatetimePickerAction, PostbackEvent,
    CarouselContainer
)
import itertools
import re
import math
from datetime import datetime, date

app = Flask(__name__)

# ==========================================
# 🟢 ตั้งค่า (ใส่ข้อมูลของคุณ)
# ==========================================
LINE_CHANNEL_ACCESS_TOKEN = "hJrtsmcBM9LT0m0jEC6h4dbp0ZWek8DwJ77PW7hypvMbGNPnld0vtFiuUpb5dXB0oiKgDAVO6C3duZARQMiLggsUmKew7SA2MoPECS9gDFebh/W0fk6ITXbzgVD3WX6iCdpdPZfaRA54aQXeEU5ezwdB04t89/1O/w1cDnyilFU="
LINE_CHANNEL_SECRET = "b178fc8ba767114ad57ac6ab93c312ab"

# 🖼️ ลิงก์รูปภาพ (ที่จะโชว์ในแชท)
TABLE_IMAGE_URL = "https://i.postimg.cc/BnCsP0fK/ref-table.png"

# 📄 ลิงก์ไฟล์ PDF (ที่จะเปิดเมื่อกดรูป) **ใส่ลิงก์ PDF ของคุณตรงนี้**
TABLE_PDF_URL = "https://www.biogenetech.co.th/wp-content/uploads/2020/10/warfarin_Guideline.pdf" 

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

user_sessions = {}

# --- Logic 1: คำนวณช่วง INR ---
def get_dose_adjustment_range(inr, current_dose):
    skip_days = 0
    if inr < 1.5:
        min_d, max_d = current_dose * 1.10, current_dose * 1.20
        msg = "เพิ่มขนาดยา 10-20% (INR ต่ำกว่าเป้าหมาย)"
    elif 1.5 <= inr <= 1.9:
        min_d, max_d = current_dose * 1.05, current_dose * 1.10
        msg = "เพิ่มขนาดยา 5-10% (INR ต่ำกว่าเป้าหมายเล็กน้อย)"
    elif 2.0 <= inr <= 3.0:
        min_d, max_d = current_dose * 0.98, current_dose * 1.02
        msg = "คงขนาดยาเดิม (Target Achieved)"
    elif 3.1 <= inr <= 3.9:
        min_d, max_d = current_dose * 0.90, current_dose * 0.95
        msg = "ลดขนาดยา 5-10% (INR สูงกว่าเป้าหมายเล็กน้อย)"
    elif 4.0 <= inr <= 4.9:
        min_d, max_d = current_dose * 0.895, current_dose * 0.905
        msg = "⚠️ งดยา 1 วัน (Hold 1 day) แล้วลดขนาดยาลง 10%"
        skip_days = 1
    elif 5.0 <= inr <= 8.9:
        min_d, max_d = current_dose * 0.84, current_dose * 0.86
        msg = "⛔️ อันตราย: งดยา 1-2 วัน และควรทาน Vit K1 (ระบบคำนวณลดขนาดลง ~15%)"
        skip_days = 2
    elif inr >= 9.0:
        return None, None, "🚨 EMERGENCY: หยุดยาและรีบพบแพทย์ทันที เพื่อรับ Vit K1", 7
    else:
        min_d, max_d = current_dose, current_dose
        msg = "ปรึกษาแพทย์"
    return min_d, max_d, msg, skip_days

# --- Logic 2: จัดตารางยา ---
def get_single_drug_daily_options(available_tabs):
    options = {}
    options[0] = (0, 0)
    for tab in available_tabs:
        for multiplier in [0.5, 1.0, 1.5, 2.0]:
            dose_val = tab * multiplier
            if dose_val not in options:
                options[dose_val] = (tab, multiplier)     
    return options

def find_best_schedule_in_range(min_weekly, max_weekly, available_tabs):
    daily_opts_map = get_single_drug_daily_options(available_tabs)
    possible_doses = sorted(list(daily_opts_map.keys()))
    candidates = []
    
    for dose_a, dose_b, dose_c in itertools.combinations_with_replacement(possible_doses, 3):
        active_doses = [d for d in [dose_a, dose_b, dose_c] if d > 0]
        if active_doses and (max(active_doses) - min(active_doses)) > 2.0:
            continue 

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
                        if final_active_doses and (max(final_active_doses) - min(final_active_doses)) > 2.0:
                            continue

                        pill_summary = {}
                        for d in schedule_list:
                            if d > 0:
                                t_size, t_count = daily_opts_map.get(d, (0,0))
                                pill_summary[t_size] = pill_summary.get(t_size, 0) + t_count

                        candidates.append({
                            "schedule": schedule_list,
                            "sum": weekly_sum,
                            "unique_count": len(set(schedule_list)),
                            "active_days": active_days,
                            "pill_summary": pill_summary
                        })

    if not candidates: return None, 0, {}
    
    target_mid = (min_weekly + max_weekly) / 2
    candidates.sort(key=lambda x: (-x['active_days'], abs(x['sum'] - target_mid), x['unique_count']))
    
    best_plan = candidates[0]['schedule']
    best_plan.sort(reverse=True)
    return best_plan, candidates[0]['sum'], candidates[0]['pill_summary']

# --- Flex Message: ตารางยา (Action A) ---
def build_strict_schedule_flex(final_dose, schedule_list, available_tabs, pill_summary, inr=None, previous_dose=None, adjustment_message=None):
    daily_opts_map = get_single_drug_daily_options(available_tabs)
    days = ['จ', 'อ', 'พ', 'พฤ', 'ศ', 'ส', 'อา']
    items = []
    header_color = "#FF3333" if "งด" in adjustment_message else "#00B900"

    info_box = [
        TextComponent(text=f"🔹 INR: {inr}", size="sm", color="#555555"),
        TextComponent(text=f"🔹 ขนาดยาเดิม: {previous_dose} mg/สัปดาห์", size="sm", color="#555555")
    ]
    if inr is not None:
         info_box.append(TextComponent(text=f"🔹 ใหม่: {final_dose:.1f} mg/สัปดาห์", size="sm", weight="bold", color="#1DB446"))
    
    info_box.append(TextComponent(text=f"📝 {adjustment_message}", size="sm", wrap=True, margin="md", color="#FF0000" if "งด" in adjustment_message else "#aaaaaa"))
    items.extend(info_box)
    items.append(TextComponent(text="-----------------", align="center", color="#cccccc"))

    for i in range(7):
        dose = schedule_list[i]
        if dose == 0:
            text_detail, text_color, bg_color = "❌ งดยา", "#ff0000", "#ffeeee"
        else:
            tab_size, pill_count = daily_opts_map.get(dose, (0, 0))
            pill_str = "ครึ่ง" if pill_count == 0.5 else f"{pill_count:.1f}"
            if pill_count.is_integer(): pill_str = str(int(pill_count))
            text_detail, text_color, bg_color = f"{dose} mg ({tab_size}mg x {pill_str} เม็ด)", "#000000", "#ffffff"

        items.append(BoxComponent(
            layout="horizontal", backgroundColor=bg_color,
            contents=[
                TextComponent(text=days[i], weight="bold", flex=1, color="#333333"),
                TextComponent(text=text_detail, size="sm", flex=4, color=text_color)
            ],
            paddingAll="xs", cornerRadius="sm", margin="xs"
        ))

    summary_lines = [f"• ยา {k} mg: รวม {v} เม็ด/สัปดาห์" for k, v in sorted(pill_summary.items())]
    items.append(TextComponent(text="-----------------", align="center", color="#cccccc", margin="md"))
    items.append(TextComponent(text="สรุปจำนวนยาต่อสัปดาห์", weight="bold", size="sm", margin="md"))
    items.append(TextComponent(text="\n".join(summary_lines) if summary_lines else "หยุดยาทั้งสัปดาห์", wrap=True, size="sm", color="#666666", margin="sm"))
    
    # ปุ่มเลือกวันนัด
    items.append(TextComponent(text="-----------------", align="center", color="#cccccc", margin="md"))
    items.append(TextComponent(text="ต้องการคำนวณจำนวนเม็ดทั้งหมด?", size="xs", color="#aaaaaa", align="center", margin="sm"))
    items.append(BoxComponent(
        layout="horizontal", margin="sm",
        contents=[
            {
                "type": "button",
                "action": DatetimePickerAction(
                    label="📅 เลือกวันนัดหมาย",
                    data="action=select_date",
                    mode="date"
                ),
                "style": "primary", "color": "#1E90FF", "height": "sm"
            }
        ]
    ))

    items.append(TextComponent(text="-----------------", align="center", color="#cccccc", margin="md"))
    
    if TABLE_IMAGE_URL:
        items.append(ImageComponent(
            url=TABLE_IMAGE_URL,
            size="full", 
            aspectRatio="1.6:1", 
            aspectMode="cover", 
            margin="md", 
            action=URIAction(uri=TABLE_PDF_URL)
        ))
        
    items.append(TextComponent(text="อ้างอิงจากแนวทางการรักษาผู้ป่วยด้วยยาต้านการแข็งตัวของเลือดชนิดรับประทาน สมาคมแพทย์โรคหัวใจแห่งประเทศไทย ในพระบรมราชูปถัมภ์", wrap=True, size="xxs", color="#aaaaaa", margin="sm", align="center"))

    bubble = BubbleContainer(
        header=BoxComponent(layout="vertical", backgroundColor=header_color, contents=[TextComponent(text="ตารางรับประทานยา", weight="bold", size="lg", color="#FFFFFF", align="center")]),
        body=BoxComponent(layout="vertical", contents=items)
    )
    return FlexSendMessage(alt_text="ตารางยา Warfarin", contents=bubble)

# --- Flex Message: เช็กยาตีกัน (UpToDate: No Management, Pure Effect) ---
def build_drug_interaction_carousel():
    bubbles = []
    
    # Card 1: ⬆️ Potentiate (Antibiotics/Antifungals)
    bubbles.append(BubbleContainer(
        header=BoxComponent(layout="vertical", backgroundColor="#D32F2F", contents=[
            TextComponent(text="⬆️ เพิ่ม INR: ยาฆ่าเชื้อ", weight="bold", color="#FFFFFF", size="lg"),
            TextComponent(text="Antibiotics / Antifungals", color="#FFCDD2", size="xs")
        ]),
        body=BoxComponent(layout="vertical", contents=[
            TextComponent(text="💊 รายการยา:", weight="bold", size="sm", color="#D32F2F"),
            TextComponent(text="• Metronidazole (Flagyl)\n• TMP-SMX (Bactrim)\n• Ciprofloxacin / Levofloxacin\n• Azithromycin / Clarithromycin\n• Fluconazole / Voriconazole\n• Miconazole (Oral Gel)", wrap=True, size="xs", color="#333333", margin="sm"),
            
            BoxComponent(layout="vertical", margin="md", backgroundColor="#eeeeee", height="1px"),
            
            TextComponent(text="⚡ ผลกระทบ (Effect):", weight="bold", size="sm", margin="md"),
            TextComponent(text="Potentiate Warfarin Effect", size="xs", color="#555555", weight="bold"),
            TextComponent(text="• ทำให้ฤทธิ์ยา Warfarin เพิ่มขึ้น\n• ส่งผลให้ค่า INR สูงขึ้น", wrap=True, size="xs", color="#555555", margin="xs")
        ])
    ))

    # Card 2: ⬆️ Potentiate (Cardiac/Others)
    bubbles.append(BubbleContainer(
        header=BoxComponent(layout="vertical", backgroundColor="#C62828", contents=[
            TextComponent(text="⬆️ เพิ่ม INR: ยาอื่นๆ", weight="bold", color="#FFFFFF", size="lg"),
            TextComponent(text="Cardiac / CNS / GI / Cancer", color="#FFCDD2", size="xs")
        ]),
        body=BoxComponent(layout="vertical", contents=[
            TextComponent(text="💊 รายการยา:", weight="bold", size="sm", color="#C62828"),
            TextComponent(text="• Amiodarone / Propafenone\n• Acetaminophen (Paracetamol)\n• Statins (Rosu/Fluvastatin)\n• Fenofibrate / Gemfibrozil\n• Omeprazole / Cimetidine\n• Allopurinol / Tramadol\n• Capecitabine / Fluorouracil", wrap=True, size="xs", color="#333333", margin="sm"),
            
            BoxComponent(layout="vertical", margin="md", backgroundColor="#eeeeee", height="1px"),
            
            TextComponent(text="⚡ ผลกระทบ (Effect):", weight="bold", size="sm", margin="md"),
            TextComponent(text="Potentiate Warfarin Effect", size="xs", color="#555555", weight="bold"),
            TextComponent(text="• ทำให้ฤทธิ์ยา Warfarin เพิ่มขึ้น\n• ส่งผลให้ค่า INR สูงขึ้น", wrap=True, size="xs", color="#555555", margin="xs")
        ])
    ))

    # Card 3: ⬇️ Inhibit (Decrease INR)
    bubbles.append(BubbleContainer(
        header=BoxComponent(layout="vertical", backgroundColor="#F57C00", contents=[
            TextComponent(text="⬇️ ลดระดับ INR", weight="bold", color="#FFFFFF", size="lg"),
            TextComponent(text="Enzyme Inducers", color="#FFE0B2", size="xs")
        ]),
        body=BoxComponent(layout="vertical", contents=[
            TextComponent(text="💊 รายการยา:", weight="bold", size="sm", color="#F57C00"),
            TextComponent(text="• Rifampin (Rifampicin)\n• Carbamazepine / Phenytoin\n• Phenobarbital\n• Cholestyramine\n• Sucralfate\n• St. John's wort\n• Dicloxacillin / Nafcillin", wrap=True, size="xs", color="#333333", margin="sm"),
            
            BoxComponent(layout="vertical", margin="md", backgroundColor="#eeeeee", height="1px"),
            
            TextComponent(text="⚡ ผลกระทบ (Effect):", weight="bold", size="sm", margin="md"),
            TextComponent(text="Inhibit Warfarin Effect", size="xs", color="#555555", weight="bold"),
            TextComponent(text="• ยับยั้งฤทธิ์ยา Warfarin\n• ส่งผลให้ค่า INR ลดต่ำลง", wrap=True, size="xs", color="#555555", margin="xs")
        ])
    ))

    # Card 4: 🩸 Bleeding Risk
    bubbles.append(BubbleContainer(
        header=BoxComponent(layout="vertical", backgroundColor="#333333", contents=[
            TextComponent(text="🩸 เพิ่มความเสี่ยงเลือดออก", weight="bold", color="#FFFFFF", size="md"),
            TextComponent(text="Pharmacodynamic Interaction", color="#cccccc", size="xs")
        ]),
        body=BoxComponent(layout="vertical", contents=[
            TextComponent(text="💊 รายการยา:", weight="bold", size="sm", color="#333333"),
            TextComponent(text="• NSAIDs (Ibuprofen, Naproxen)\n• COX-2 (Celecoxib)\n• Aspirin / Clopidogrel\n• SSRIs (Fluoxetine, Sertraline)\n• Ginkgo biloba / Garlic (High dose)", wrap=True, size="xs", color="#333333", margin="sm"),
            
            BoxComponent(layout="vertical", margin="md", backgroundColor="#eeeeee", height="1px"),
            
            TextComponent(text="⚡ ผลกระทบ (Effect):", weight="bold", size="sm", margin="md"),
            TextComponent(text="Increased Bleeding Risk", size="xs", color="#555555", weight="bold"),
            TextComponent(text="• ไม่ส่งผลต่อค่า INR (No Effect on INR)\n• แต่เพิ่มความเสี่ยงเลือดออก (Bleeding) โดยตรง", wrap=True, size="xs", color="#555555", margin="xs")
        ])
    ))

    # Footer Reference
    bubbles.append(BubbleContainer(
        body=BoxComponent(layout="vertical", contents=[
            TextComponent(text="📚 อ้างอิงแหล่งข้อมูล:", weight="bold", size="sm", color="#1E90FF"),
            TextComponent(text="UpToDate: Warfarin drug interactions (Image Key: HEME/62697)", wrap=True, size="xs", color="#aaaaaa", margin="sm"),
            TextComponent(text="*ข้อมูลนี้สำหรับบุคลากรทางการแพทย์เพื่อประกอบการตัดสินใจเท่านั้น", wrap=True, size="xxs", color="#cccccc", margin="md", align="center")
        ])
    ))

    return FlexSendMessage(alt_text="Drug Interaction Guide (UpToDate)", contents=CarouselContainer(contents=bubbles))

def parse_warfarin_form(text):
    data = {'available_tabs': [], 'weekly_dose': None, 'inr_prev': None, 'inr_curr': None}
    text = text.replace('“', '"').replace('”', '"')
    for i in range(1, 5):
        match = re.search(f'ความแรงเม็ดยาที่ {i}\s*"([^"]*)"\s*mg', text)
        if match:
            try:
                val = float(match.group(1).strip())
                if val > 0: data['available_tabs'].append(val)
            except: continue
    match_dose = re.search(r'กรอกขนาดยาต่อสัปดาห์\s*"([^"]*)"\s*mg', text)
    if match_dose:
        try: data['weekly_dose'] = float(match_dose.group(1).strip())
        except: pass
    match_inr = re.search(r'INR ครั้งล่าสุด INR =\s*"([^"]*)"', text)
    if match_inr:
        try: data['inr_curr'] = float(match_inr.group(1).strip())
        except: pass
    return data

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try: handler.handle(body, signature)
    except InvalidSignatureError: abort(400)
    return 'OK'

# --- Handler ข้อความปกติ ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id

    # 1. ปุ่มเช็กยาตีกัน (Action B)
    if text == "เช็กยาตีกัน":
        interaction_flex = build_drug_interaction_carousel()
        line_bot_api.reply_message(event.reply_token, interaction_flex)
        return

    # 2. ขอแบบฟอร์ม (Action A)
    if text == "ช่วยจัดยา warfarin":
        form = "📋 **แบบฟอร์มจัดยา Warfarin**\n(คัดลอก > เติมตัวเลขในฟันหนู > ส่ง)\n\n---ส่วนที่ 1: ยาที่มีใน รพ.---\nความแรงเม็ดยาที่ 1 ”_” mg\nความแรงเม็ดยาที่ 2 ”_” mg\nความแรงเม็ดยาที่ 3 ”_” mg\nความแรงเม็ดยาที่ 4 ”_” mg\n\n---ส่วนที่ 2: ขนาดยาปัจจุบัน---\nกรอกขนาดยาต่อสัปดาห์ ”_” mg\n\n---ส่วนที่ 3: ค่าเลือด (ถ้ามี)---\nINR ครั้งล่าสุด INR = ”_”"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=form))
        return

    # 3. ปุ่มกดเรียกปฏิทินจากตารางยา (Sub-feature ของ A)
    if text == "เรียกปฏิทิน":
        if user_id not in user_sessions:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ ไม่พบข้อมูลการจัดยาล่าสุด กรุณากด 'ช่วยจัดยา warfarin' และส่งข้อมูลก่อนครับ"))
            return
        
        session = user_sessions[user_id]
        time_diff = datetime.now() - session['timestamp']
        if time_diff.total_seconds() > 600:
            del user_sessions[user_id]
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ หมดเวลา (เกิน 10 นาที) กรุณากดคำนวณยาใหม่อีกครั้งครับ"))
            return

        calendar_flex = FlexSendMessage(
            alt_text="เลือกวันนัดหมาย",
            contents=BubbleContainer(
                body=BoxComponent(
                    layout="vertical",
                    contents=[
                        TextComponent(text="เลือกวันนัดหมาย", weight="bold", size="lg", align="center"),
                        TextComponent(text="เพื่อคำนวณจำนวนเม็ดทั้งหมด", size="xs", color="#aaaaaa", align="center", margin="sm"),
                        BoxComponent(
                            layout="horizontal", margin="md",
                            contents=[{
                                "type": "button",
                                "action": DatetimePickerAction(label="📅 เปิดปฏิทิน", data="action=select_date", mode="date"),
                                "style": "primary", "color": "#1E90FF"
                            }]
                        )
                    ]
                )
            )
        )
        line_bot_api.reply_message(event.reply_token, calendar_flex)
        return

    # 4. รับค่าจากแบบฟอร์ม
    if "แบบฟอร์มจัดยา Warfarin" in text:
        parsed = parse_warfarin_form(text)
        tabs, dose, inr = parsed['available_tabs'], parsed['weekly_dose'], parsed['inr_curr']
        
        if not tabs or not dose:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ ข้อมูลไม่ครบ กรุณาระบุยาและขนาดยาเดิม"))
            return

        min_target, max_target, msg, skip_days = dose, dose, "ไม่ได้ปรับยา", 0
        if inr is not None:
            min_target, max_target, msg, skip_days = get_dose_adjustment_range(inr, dose)
            if min_target is None:
                 line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
                 return

        schedule, final_dose, pill_summary = find_best_schedule_in_range(min_target, max_target, tabs)

        if schedule:
            if skip_days > 0:
                for i in range(min(skip_days, 7)): schedule[i] = 0
            
            user_sessions[user_id] = {
                'timestamp': datetime.now(),
                'pill_summary': pill_summary,
                'schedule': schedule
            }

            flex = build_strict_schedule_flex(final_dose, schedule, tabs, pill_summary, inr, dose, msg)
            line_bot_api.reply_message(event.reply_token, flex)
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"⚠️ คำนวณช่วง {min_target:.1f}-{max_target:.1f} mg แต่ไม่สามารถจัดยาที่มีให้ลงล็อกได้"))

# --- Handler ปฏิทิน (Postback) ---
@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    data = event.postback.data
    
    if data == "action=select_date":
        if user_id not in user_sessions:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ ไม่พบข้อมูลการจัดยาล่าสุด กรุณากด 'ช่วยจัดยา warfarin' ใหม่อีกครั้งครับ"))
            return

        session = user_sessions[user_id]
        
        time_diff = datetime.now() - session['timestamp']
        if time_diff.total_seconds() > 600:
            del user_sessions[user_id]
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ หมดเวลา (เกิน 10 นาที) กรุณากดคำนวณยาใหม่อีกครั้งครับ"))
            return

        selected_date_str = event.postback.params['date']
        selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
        today = date.today()

        if selected_date <= today:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ กรุณาเลือกวันนัดล่วงหน้า (ในอนาคต) เท่านั้นครับ"))
            return

        days_diff = (selected_date - today).days
        weeks_calc = days_diff / 7
        weeks_ceiling = math.ceil(weeks_calc)

        pill_summary = session['pill_summary']
        result_lines = []
        for strength, count_per_week in pill_summary.items():
            total_pills = count_per_week * weeks_ceiling
            result_lines.append(f"💊 ยา {strength} mg: {count_per_week:g}x{weeks_ceiling} = {total_pills:.0f} เม็ด")

        msg = (
            f"📅 **สรุปยอดเบิกยา**\n"
            f"วันนี้: {today.strftime('%d/%m/%Y')}\n"
            f"วันนัด: {selected_date.strftime('%d/%m/%Y')}\n"
            f"ระยะเวลา: {days_diff} วัน (คิดเป็น {weeks_ceiling} สัปดาห์)\n"
            f"-----------------\n"
            f"{chr(10).join(result_lines)}\n"
            f"-----------------\n"
            f"(คำนวณแบบปัดเศษสัปดาห์ขึ้น)"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))

if __name__ == "__main__":
    app.run(port=5000)
