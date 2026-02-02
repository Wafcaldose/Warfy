from flask import Flask, request, abort, render_template_string
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FlexSendMessage, BubbleContainer, BoxComponent, TextComponent,
    ImageComponent, URIAction, DatetimePickerAction, PostbackEvent,
    CarouselContainer, ButtonComponent, PostbackAction,
    QuickReply, QuickReplyButton, MessageAction
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
LIFF_ID = "2009026200-reXDdCkf"

# 🖼️ ลิงก์รูปภาพและ PDF
TABLE_IMAGE_URL = "https://i.postimg.cc/BnCsP0fK/ref-table.png"
TABLE_PDF_URL = "https://www.biogenetech.co.th/wp-content/uploads/2020/10/warfarin_Guideline.pdf" 

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

user_sessions = {}

# ==========================================
# 🌐 ส่วนหน้าเว็บ LIFF (เลือกยา 1, 2, 3, 5 mg)
# ==========================================
LIFF_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>เลือกขนาดยา</title>
    <script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; padding: 20px; background-color: #f8f9fa; text-align: center; }
        h3 { color: #1E90FF; margin-bottom: 5px; }
        p { color: #888; font-size: 14px; margin-bottom: 25px; }
        .grid-container { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; max-width: 400px; margin: 0 auto; }
        .pill-btn {
            background-color: #eeeeee; color: #555; border: 2px solid #e0e0e0; padding: 25px 0;
            font-size: 20px; border-radius: 12px; cursor: pointer; transition: 0.2s;
            font-weight: bold; width: 100%;
        }
        .pill-btn.active { 
            background-color: #00C851; color: white; border-color: #00C851; 
            box-shadow: 0 4px 10px rgba(0, 200, 81, 0.4); transform: scale(1.05);
        }
        .confirm-btn {
            width: 100%; max-width: 400px; background-color: #007bff; color: white; border: none;
            padding: 15px; font-size: 18px; border-radius: 50px; margin-top: 30px;
            cursor: pointer; font-weight: bold;
        }
        .confirm-btn:disabled { background-color: #cccccc; cursor: not-allowed; }
    </style>
</head>
<body>
    <h3>💊 เลือกขนาดยาที่มีใน รพ.</h3>
    <p>กดเลือกยาที่มีทั้งหมด (ปุ่มจะเปลี่ยนสี)</p>
    
    <div class="grid-container" id="btnContainer"></div>

    <button id="submitBtn" class="confirm-btn" disabled onclick="sendData()">ยืนยัน (Done)</button>

    <script>
        const pillSizes = [1, 2, 3, 5]; 
        let selected = new Set();
        const container = document.getElementById('btnContainer');
        
        pillSizes.forEach(size => {
            let btn = document.createElement('button');
            btn.className = 'pill-btn';
            btn.innerText = size + ' mg';
            btn.onclick = () => togglePill(size, btn);
            container.appendChild(btn);
        });

        function togglePill(size, btnElement) {
            if (selected.has(size)) {
                selected.delete(size);
                btnElement.classList.remove('active');
            } else {
                selected.add(size);
                btnElement.classList.add('active');
            }
            const submitBtn = document.getElementById('submitBtn');
            submitBtn.disabled = selected.size === 0;
            submitBtn.style.backgroundColor = selected.size > 0 ? '#007bff' : '#cccccc';
        }

        async function sendData() {
            if (!liff.isInClient()) {
                alert("กรุณาเปิดในแอป LINE เท่านั้น"); return;
            }
            const sorted = Array.from(selected).sort((a,b) => a-b);
            const msgText = "ยืนยันยา: " + sorted.join(", ");
            try {
                await liff.sendMessages([{ type: 'text', text: msgText }]);
                liff.closeWindow();
            } catch (err) {
                alert("เกิดข้อผิดพลาด: " + err);
            }
        }

        liff.init({ liffId: "{{ liff_id }}" }).then(() => {
            if (!liff.isLoggedIn()) liff.login();
        });
    </script>
</body>
</html>
"""

@app.route("/liff/pill-selector")
def liff_pill_selector():
    return render_template_string(LIFF_HTML, liff_id=LIFF_ID)

# ==========================================
# 📐 Logic คำนวณ
# ==========================================
def get_dose_adjustment_range(inr, current_dose):
    if inr is None:
        return current_dose, current_dose, "คงขนาดยาเดิม (ไม่ได้ระบุ INR / ไม่ได้ตรวจ)", 0

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
                        
                        candidates.append({
                            "schedule": schedule_list, 
                            "sum": weekly_sum, 
                            "unique_count": len(set(schedule_list)), 
                            "pill_summary": pill_summary, 
                            "active_days": active_days
                        })

    if not candidates: return None, 0, {}
    
    target_mid = (min_weekly + max_weekly) / 2
    candidates.sort(key=lambda x: (-x['active_days'], abs(x['sum'] - target_mid), x['unique_count']))
    
    best_candidate = candidates[0]
    best_plan = best_candidate['schedule']
    return best_plan, best_candidate['sum'], best_candidate['pill_summary']

# ==========================================
# 🎨 UI Flex Messages
# ==========================================
def build_strict_schedule_flex(final_dose, schedule_list, available_tabs, pill_summary, inr=None, previous_dose=None, adjustment_message=None):
    daily_opts_map = get_single_drug_daily_options(available_tabs)
    days = ['จ', 'อ', 'พ', 'พฤ', 'ศ', 'ส', 'อา']
    items = []
    header_color = "#FF3333" if "งด" in adjustment_message else "#00B900"

    info_box = [TextComponent(text=f"🔹 ขนาดยาเดิม: {previous_dose} mg/สัปดาห์", size="sm", color="#555555")]
    if inr is not None:
        info_box.insert(0, TextComponent(text=f"🔹 INR: {inr}", size="sm", color="#555555"))
        info_box.append(TextComponent(text=f"🔹 ใหม่: {final_dose:.1f} mg/สัปดาห์", size="sm", weight="bold", color="#1DB446"))
    else:
        info_box.insert(0, TextComponent(text=f"🔹 INR: ไม่ระบุ", size="sm", color="#aaaaaa"))

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
    
    items.append(TextComponent(text="-----------------", align="center", color="#cccccc", margin="md"))
    items.append(TextComponent(text="ต้องการคำนวณจำนวนเม็ดทั้งหมด?", size="xs", color="#aaaaaa", align="center", margin="sm"))
    items.append(BoxComponent(
        layout="horizontal", margin="sm",
        contents=[{
            "type": "button",
            "action": DatetimePickerAction(label="📅 เลือกวันนัดหมาย", data="action=select_date", mode="date"),
            "style": "primary", "color": "#1E90FF", "height": "sm"
        }]
    ))

    if inr is not None:
        items.append(TextComponent(text="-----------------", align="center", color="#cccccc", margin="md"))
        if TABLE_IMAGE_URL:
            items.append(ImageComponent(url=TABLE_IMAGE_URL, size="full", aspectRatio="1.6:1", aspectMode="cover", margin="md", action=URIAction(uri=TABLE_PDF_URL)))
        items.append(TextComponent(text="อ้างอิงจากแนวทางการรักษาผู้ป่วยด้วยยาต้านการแข็งตัวของเลือดชนิดรับประทาน สมาคมแพทย์โรคหัวใจแห่งประเทศไทย ในพระบรมราชูปถัมภ์", wrap=True, size="xxs", color="#aaaaaa", margin="sm", align="center"))
    
    bubble = BubbleContainer(
        header=BoxComponent(layout="vertical", backgroundColor=header_color, contents=[TextComponent(text="ตารางรับประทานยา", weight="bold", size="lg", color="#FFFFFF", align="center")]),
        body=BoxComponent(layout="vertical", contents=items)
    )
    return FlexSendMessage(alt_text="ตารางยา Warfarin", contents=bubble)

def build_drug_interaction_carousel():
    bubbles = []
    interactions = [
        {"title": "⬆️ เพิ่ม INR: ยาฆ่าเชื้อ", "color": "#D32F2F", "drugs": "• Metronidazole (Flagyl)\n• TMP-SMX (Bactrim)\n• Ciprofloxacin / Levofloxacin\n• Azithromycin / Clarithromycin\n• Fluconazole / Voriconazole", "effect": "Potentiate Warfarin Effect\n• ทำให้ฤทธิ์ยา Warfarin เพิ่มขึ้น\n• ส่งผลให้ค่า INR สูงขึ้น"},
        {"title": "⬆️ เพิ่ม INR: ยาอื่นๆ", "color": "#C62828", "drugs": "• Amiodarone\n• Paracetamol\n• Statins\n• Omeprazole\n• Capecitabine", "effect": "Potentiate Warfarin Effect\n• ทำให้ฤทธิ์ยา Warfarin เพิ่มขึ้น\n• ส่งผลให้ค่า INR สูงขึ้น"},
        {"title": "⬇️ ลดระดับ INR", "color": "#F57C00", "drugs": "• Rifampin\n• Carbamazepine\n• Phenytoin\n• Phenobarbital\n• St. John's wort", "effect": "Inhibit Warfarin Effect\n• ยับยั้งฤทธิ์ยา Warfarin\n• ส่งผลให้ค่า INR ลดต่ำลง"},
        {"title": "🩸 เพิ่มความเสี่ยงเลือดออก", "color": "#333333", "drugs": "• NSAIDs (Ibuprofen, etc)\n• Aspirin / Clopidogrel\n• SSRIs", "effect": "Increased Bleeding Risk\n• ไม่ส่งผลต่อค่า INR โดยตรง\n• แต่เพิ่มความเสี่ยงเลือดออก"}
    ]
    for item in interactions:
        bubbles.append(BubbleContainer(
            header=BoxComponent(layout="vertical", backgroundColor=item["color"], contents=[TextComponent(text=item["title"], weight="bold", color="#FFFFFF", size="lg")]),
            body=BoxComponent(layout="vertical", contents=[
                TextComponent(text="💊 รายการยา:", weight="bold", size="sm", color=item["color"]),
                TextComponent(text=item["drugs"], wrap=True, size="xs", color="#333333", margin="sm"),
                BoxComponent(layout="vertical", margin="md", backgroundColor="#eeeeee", height="1px"),
                TextComponent(text="⚡ ผลกระทบ (Effect):", weight="bold", size="sm", margin="md"),
                TextComponent(text=item["effect"], wrap=True, size="xs", color="#555555", margin="xs")
            ])
        ))
    bubbles.append(BubbleContainer(body=BoxComponent(layout="vertical", contents=[TextComponent(text="📚 อ้างอิงแหล่งข้อมูล:", weight="bold", size="sm", color="#1E90FF"), TextComponent(text="UpToDate: Warfarin drug interactions (Image Key: HEME/62697)", wrap=True, size="xs", color="#aaaaaa", margin="sm")])))
    return FlexSendMessage(alt_text="Drug Interaction Guide", contents=CarouselContainer(contents=bubbles))

# ==========================================
# 📡 Handlers
# ==========================================
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

    # 1. เช็กยาตีกัน
    if text == "เช็กยาตีกัน":
        line_bot_api.reply_message(event.reply_token, build_drug_interaction_carousel())
        return

    # 2. Trigger LIFF
    if text == "ช่วยจัดยา warfarin":
        flex = FlexSendMessage(
            alt_text="เปิดหน้าเลือกยา",
            contents=BubbleContainer(
                body=BoxComponent(
                    layout="vertical",
                    contents=[
                        TextComponent(text="💊 ระบบช่วยจัดยา", weight="bold", size="lg", color="#1E90FF", align="center"),
                        TextComponent(text="กรุณากดปุ่มด้านล่างเพื่อเลือกขนาดยาที่มีใน รพ.", wrap=True, size="xs", color="#aaaaaa", align="center", margin="sm"),
                        ButtonComponent(
                            style="primary", color="#00C851", height="sm", margin="md",
                            action=URIAction(label="เลือกขนาดยา", uri=f"https://liff.line.me/{LIFF_ID}")
                        )
                    ]
                )
            )
        )
        line_bot_api.reply_message(event.reply_token, flex)
        return

    # 3. รับค่าจาก LIFF
    if text.startswith("ยืนยันยา:"):
        try:
            data_str = text.replace("ยืนยันยา:", "").strip()
            selected_tabs = [float(x.strip()) for x in data_str.split(",") if x.strip()]
            if not selected_tabs:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ ไม่พบข้อมูลยา กรุณาเลือกยาใหม่"))
                return
            user_sessions[user_id] = {'available_tabs': selected_tabs, 'step': 'input_dose'}
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✅ รับทราบยา: {data_str} mg\n\n👉 พิมพ์ 'ขนาดยาเดิมต่อสัปดาห์' (mg/สัปดาห์) ส่งมาได้เลยครับ (เช่น 21)"))
        except:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ เกิดข้อผิดพลาด"))
        return

    # 4. Input Data
    if user_id in user_sessions and user_sessions[user_id].get('step'):
        step = user_sessions[user_id]['step']
        
        # Step: Input Dose
        if step == 'input_dose':
            try:
                dose = float(text)
                user_sessions[user_id]['weekly_dose'] = dose
                user_sessions[user_id]['step'] = 'input_inr'
                
                quick_reply = QuickReply(items=[
                    QuickReplyButton(action=MessageAction(label="❌ ไม่ทราบ/ไม่ได้ตรวจ", text="ไม่ทราบค่า INR"))
                ])
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(
                        text="✅ บันทึกขนาดยาแล้วครับ\n\n👉 กรุณาพิมพ์ค่า INR ล่าสุด (เช่น 2.5)\nหรือกดปุ่มด้านล่างหากไม่มีผลเลือด",
                        quick_reply=quick_reply
                    )
                )
            except:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ พิมพ์ตัวเลขเท่านั้น (เช่น 21)"))
            return

        # Step: Input INR
        if step == 'input_inr':
            inr = None
            try:
                if "ไม่ทราบ" in text or "ไม่มี" in text or "ไม่ได้ตรวจ" in text:
                    inr = None 
                else:
                    inr = float(text)
                
                session = user_sessions[user_id]
                min_t, max_t, msg, skip = get_dose_adjustment_range(inr, session['weekly_dose'])
                
                if min_t is None and inr is not None:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
                    del user_sessions[user_id]
                    return

                schedule, final, summary = find_best_schedule_in_range(min_t, max_t, session['available_tabs'])
                
                if schedule:
                    # ✅ จัดการ 0 (Skip Days)
                    if skip: 
                        for i in range(min(skip, 7)): schedule[i] = 0
                    
                    # ✅ Logic ใหม่: เรียงยาที่กินจาก น้อย->มาก แล้วเอา 0 ไปไว้หลังสุด
                    # แยก 0 ออกมา
                    non_zeros = sorted([x for x in schedule if x > 0]) # เรียงน้อยไปมาก (2,2,4,4)
                    zeros = [x for x in schedule if x == 0] # เก็บ 0 ไว้ (0)
                    schedule = non_zeros + zeros # เอามาต่อกัน (2,2,4,4,0)

                    session['timestamp'] = datetime.now()
                    session['pill_summary'] = summary
                    session['step'] = 'calculated'

                    flex = build_strict_schedule_flex(final, schedule, session['available_tabs'], summary, inr, session['weekly_dose'], msg)
                    line_bot_api.reply_message(event.reply_token, flex)
                else:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"⚠️ คำนวณช่วง {min_t:.1f}-{max_t:.1f} mg แต่ไม่สามารถจัดยาที่มีให้ลงล็อกได้"))
            except ValueError:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ กรุณาพิมพ์ตัวเลข INR (เช่น 2.5) หรือกดปุ่ม 'ไม่ทราบ'"))
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

        msg = (
            f"📅 **สรุปยอดเบิกยา**\n"
            f"นัด: {selected_date.strftime('%d/%m/%Y')} ({days_diff} วัน)\n"
            f"คิดเป็น: {weeks_ceiling} สัปดาห์ (ปัดขึ้น)\n"
            f"-----------------\n"
            f"{chr(10).join(result_lines)}"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))

# เพิ่ม Route สำหรับหน้าแรก (Home)
@app.route("/")
def home():
    return "✅ Warfy Server is Running! (ไปที่ /liff/pill-selector เพื่อใช้งาน)"

if __name__ == "__main__":
    app.run(port=5000)
