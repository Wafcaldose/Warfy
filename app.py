from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FlexSendMessage, BubbleContainer, BoxComponent, TextComponent,
    ImageComponent, URIAction
)
import itertools
import re

app = Flask(__name__)

# ==========================================
# 🟢 ส่วนที่ต้องแก้ไข (ใส่ข้อมูลของคุณ)
# ==========================================

LINE_CHANNEL_ACCESS_TOKEN = "hJrtsmcBM9LT0m0jEC6h4dbp0ZWek8DwJ77PW7hypvMbGNPnld0vtFiuUpb5dXB0oiKgDAVO6C3duZARQMiLggsUmKew7SA2MoPECS9gDFebh/W0fk6ITXbzgVD3WX6iCdpdPZfaRA54aQXeEU5ezwdB04t89/1O/w1cDnyilFU="
LINE_CHANNEL_SECRET = "b178fc8ba767114ad57ac6ab93c312ab"

# ลิงก์รูปตาราง (ถ้ามีลิงก์ใหม่ก็แก้ตรงนี้ได้เลย)
TABLE_IMAGE_URL = "https://i.postimg.cc/BnCsP0fK/ref-table.png"

# ลิงก์ Ngrok (สำหรับดึงรูปในบางกรณี แต่ถ้าใช้เว็บฝากรูปข้างบนแล้ว อันนี้ไม่ค่อยจำเป็นครับ)
NGROK_URL = "https://xxxx-xxxx.ngrok-free.app"

# ==========================================

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- Logic 1: คำนวณช่วง INR (Table 3) ---
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

# --- Logic 2: จัดตารางยา (Intelligent Scheduling) ---
def get_single_drug_daily_options(available_tabs):
    options = {}
    options[0] = (0, 0) # 0 mg คือวันหยุดยา
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
    
    # 🔄 วนลูปหาคู่ผสมยา 3 รูปแบบ (เพื่อให้รองรับ ยาA + ยาB + วันหยุด)
    for dose_a, dose_b, dose_c in itertools.combinations_with_replacement(possible_doses, 3):
        
        # 🛡️ Filter 1: เช็คความห่างของขนาดยา (Gap Limit <= 2 mg)
        # ดึงเฉพาะโดสยาที่มีการกินจริง (ไม่นับ 0 mg)
        active_doses = [d for d in [dose_a, dose_b, dose_c] if d > 0]
        
        if active_doses:
            # ถ้าความต่างระหว่าง (มากสุด - น้อยสุด) เกิน 2 mg -> ตัดทิ้ง
            if (max(active_doses) - min(active_doses)) > 2.0:
                continue 

        # คำนวณวัน
        for count_a in range(8):
            for count_b in range(8 - count_a):
                count_c = 7 - count_a - count_b
                
                weekly_sum = (dose_a * count_a) + (dose_b * count_b) + (dose_c * count_c)
                
                if min_weekly <= weekly_sum <= max_weekly:
                    # นับจำนวนวันที่กินยาจริง (Active Days)
                    active_days = 0
                    if dose_a > 0: active_days += count_a
                    if dose_b > 0: active_days += count_b
                    if dose_c > 0: active_days += count_c
                    
                    if active_days >= 5: # Safety Constraint: ต้องกินยาอย่างน้อย 5 วันต่อสัปดาห์
                        schedule_list = [dose_a]*count_a + [dose_b]*count_b + [dose_c]*count_c
                        
                        # Double Check: ตรวจสอบ Gap ในลิสต์ยาสุทธิอีกครั้งเพื่อความชัวร์
                        final_active_doses = [d for d in schedule_list if d > 0]
                        if final_active_doses and (max(final_active_doses) - min(final_active_doses)) > 2.0:
                            continue

                        candidates.append({
                            "schedule": schedule_list,
                            "sum": weekly_sum,
                            "unique_count": len(set(schedule_list)),
                            "active_days": active_days
                        })

    if not candidates: return None, 0
    
    target_mid = (min_weekly + max_weekly) / 2
    
    # ⭐ Ranking Priority (เรียงลำดับความสำคัญ):
    # 1. -x['active_days']: เลือก Active Days มากสุดก่อน (เช่น 6 วัน ชนะ 5 วัน) **เครื่องหมายลบคือเรียงมากไปน้อย**
    # 2. abs(...): เลือกผลรวมที่ใกล้เคียงเป้าหมายที่สุด
    # 3. x['unique_count']: เลือกรูปแบบยาที่ไม่ซับซ้อน
    
    candidates.sort(key=lambda x: (-x['active_days'], abs(x['sum'] - target_mid), x['unique_count']))
    
    best_plan = candidates[0]['schedule']
    best_plan.sort(reverse=True) # เรียงลำดับยามาก -> น้อย (วันหยุดจะไปอยู่ท้ายสัปดาห์)
    return best_plan, candidates[0]['sum']

# --- สร้าง Flex Message ---
def build_strict_schedule_flex(final_dose, schedule_list, available_tabs, inr=None, previous_dose=None, adjustment_message=None):
    daily_opts_map = get_single_drug_daily_options(available_tabs)
    days = ['จ', 'อ', 'พ', 'พฤ', 'ศ', 'ส', 'อา']
    items = []
    header_color = "#FF3333" if "งด" in adjustment_message else "#00B900"

    # ส่วน Header ข้อมูลยา
    info_box = [
        TextComponent(text=f"🔹 INR: {inr}", size="sm", color="#555555"),
        TextComponent(text=f"🔹 เดิม: {previous_dose} mg/wk", size="sm", color="#555555")
    ]
    if inr is not None:
         info_box.append(TextComponent(text=f"🔹 ใหม่: {final_dose:.1f} mg/wk", size="sm", weight="bold", color="#1DB446"))
    
    info_box.append(TextComponent(text=f"📝 {adjustment_message}", size="sm", wrap=True, margin="md", color="#FF0000" if "งด" in adjustment_message else "#aaaaaa"))
    items.extend(info_box)
    items.append(TextComponent(text="-----------------", align="center", color="#cccccc"))

    # ส่วนตารางยา
    total_summary = {}
    for i in range(7):
        dose = schedule_list[i]
        if dose == 0:
            text_detail, text_color, bg_color = "❌ งดยา", "#ff0000", "#ffeeee"
        else:
            tab_size, pill_count = daily_opts_map.get(dose, (0, 0))
            pill_str = "ครึ่ง" if pill_count == 0.5 else f"{pill_count:.1f}"
            if pill_count.is_integer(): pill_str = str(int(pill_count))
            text_detail, text_color, bg_color = f"{dose} mg ({tab_size}mg x {pill_str} เม็ด)", "#000000", "#ffffff"
            key = f"{tab_size} mg"
            total_summary[key] = total_summary.get(key, 0) + pill_count

        items.append(BoxComponent(
            layout="horizontal", backgroundColor=bg_color,
            contents=[
                TextComponent(text=days[i], weight="bold", flex=1, color="#333333"),
                TextComponent(text=text_detail, size="sm", flex=4, color=text_color)
            ],
            paddingAll="xs", cornerRadius="sm", margin="xs"
        ))

    # ส่วนสรุปจำนวนเม็ด
    summary_lines = [f"• ยา {k}: รวม {v} เม็ด" for k, v in sorted(total_summary.items())]
    items.append(TextComponent(text="-----------------", align="center", color="#cccccc", margin="md"))
    items.append(TextComponent(text="สรุปจำนวนยาต่อสัปดาห์", weight="bold", size="sm", margin="md"))
    items.append(TextComponent(text="\n".join(summary_lines) if summary_lines else "หยุดยาทั้งสัปดาห์", wrap=True, size="sm", color="#666666", margin="sm"))
    
    # ส่วนรูปภาพและอ้างอิง
    items.append(TextComponent(text="-----------------", align="center", color="#cccccc", margin="md"))
    
    if TABLE_IMAGE_URL:
        items.append(ImageComponent(
            url=TABLE_IMAGE_URL, size="full", aspectRatio="1.6:1", aspectMode="cover", margin="md",
            action=URIAction(uri=TABLE_IMAGE_URL)
        ))
    
    items.append(TextComponent(
        text="อ้างอิงจากแนวทางการรักษาผู้ป่วยด้วยยาต้านการแข็งตัวของเลือดชนิดรับประทาน สมาคมแพทย์โรคหัวใจแห่งประเทศไทย ในพระบรมราชูปถัมภ์",
        wrap=True, size="xxs", color="#aaaaaa", margin="sm", align="center"
    ))

    bubble = BubbleContainer(
        header=BoxComponent(
            layout="vertical", backgroundColor=header_color,
            contents=[TextComponent(text="ตารางรับประทานยา", weight="bold", size="lg", color="#FFFFFF", align="center")]
        ),
        body=BoxComponent(layout="vertical", contents=items)
    )
    return FlexSendMessage(alt_text="ตารางยา Warfarin", contents=bubble)

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
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    if text == "ช่วยจัดยา warfarin":
        form = (
            "📋 **แบบฟอร์มจัดยา Warfarin**\n"
            "(คัดลอก > เติมตัวเลขในฟันหนู > ส่ง)\n\n"
            "---ส่วนที่ 1: ยาที่มีใน รพ.---\n"
            "ความแรงเม็ดยาที่ 1 ”_” mg\n"
            "ความแรงเม็ดยาที่ 2 ”_” mg\n"
            "ความแรงเม็ดยาที่ 3 ”_” mg\n"
            "ความแรงเม็ดยาที่ 4 ”_” mg\n\n"
            "---ส่วนที่ 2: ขนาดยาปัจจุบัน---\n"
            "กรอกขนาดยาต่อสัปดาห์ ”_” mg\n\n"
            "---ส่วนที่ 3: ค่าเลือด (ถ้ามี)---\n"
            "INR ในครั้งก่อน INR = ”_”\n"
            "INR ครั้งล่าสุด INR = ”_”"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=form))
        return

    if "แบบฟอร์มจัดยา Warfarin" in text:
        parsed = parse_warfarin_form(text)
        tabs, dose, inr = parsed['available_tabs'], parsed['weekly_dose'], parsed['inr_curr']
        
        if not tabs or not dose:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ ข้อมูลไม่ครบ กรุณาระบุยาและขนาดเดิม"))
            return

        min_target, max_target, msg, skip_days = dose, dose, "ไม่ได้ปรับยา", 0
        if inr is not None:
            min_target, max_target, msg, skip_days = get_dose_adjustment_range(inr, dose)
            if min_target is None:
                 line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
                 return

        schedule, final_dose = find_best_schedule_in_range(min_target, max_target, tabs)

        if schedule:
            if skip_days > 0:
                for i in range(min(skip_days, 7)): schedule[i] = 0
            flex = build_strict_schedule_flex(final_dose, schedule, tabs, inr, dose, msg)
            line_bot_api.reply_message(event.reply_token, flex)
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"⚠️ คำนวณช่วง {min_target:.1f}-{max_target:.1f} mg แต่ไม่สามารถจัดยาที่มีให้ลงล็อกได้"))

if __name__ == "__main__":
    app.run(port=5000)
