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
# 🟢 ตั้งค่า (ใส่ข้อมูลของคุณ)
# ==========================================
LINE_CHANNEL_ACCESS_TOKEN = "hJrtsmcBM9LT0m0jEC6h4dbp0ZWek8DwJ77PW7hypvMbGNPnld0vtFiuUpb5dXB0oiKgDAVO6C3duZARQMiLggsUmKew7SA2MoPECS9gDFebh/W0fk6ITXbzgVD3WX6iCdpdPZfaRA54aQXeEU5ezwdB04t89/1O/w1cDnyilFU="
LINE_CHANNEL_SECRET = "b178fc8ba767114ad57ac6ab93c312ab"

# 🔴 ใส่ LIFF ID ที่ได้จากข้อ 1 ตรงนี้
LIFF_ID = "2009026200-reXDdCkf"  

TABLE_IMAGE_URL = "https://i.postimg.cc/Hx1Zz0vP/ref-table.png"
TABLE_PDF_URL = "https://example.com/warfarin-guideline.pdf" 

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

user_sessions = {}

# ==========================================
# 🌐 ส่วนหน้าเว็บ LIFF (HTML/JS)
# ==========================================
# หน้านี้จะถูกเรียกเมื่อกดปุ่มในไลน์
LIFF_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>เลือกขนาดยา</title>
    <script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
    <style>
        body { font-family: 'Sarabun', sans-serif; padding: 20px; background-color: #f8f9fa; text-align: center; }
        h3 { color: #333; }
        .grid-container { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-top: 20px; }
        .pill-btn {
            background-color: #e0e0e0; color: #555; border: none; padding: 20px;
            font-size: 18px; border-radius: 12px; cursor: pointer; transition: 0.2s;
            font-weight: bold;
        }
        .pill-btn.active { background-color: #00C851; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        .confirm-btn {
            width: 100%; background-color: #007bff; color: white; border: none;
            padding: 15px; font-size: 18px; border-radius: 50px; margin-top: 30px;
            cursor: pointer;
        }
        .confirm-btn:disabled { background-color: #ccc; }
    </style>
</head>
<body>
    <h3>💊 เลือกขนาดยาที่มีใน รพ.</h3>
    <p style="color:#777; font-size:14px;">แตะเพื่อเลือก (ปุ่มจะเปลี่ยนสี)</p>
    
    <div class="grid-container" id="btnContainer">
        </div>

    <button id="submitBtn" class="confirm-btn" disabled onclick="sendData()">ยืนยัน (Done)</button>

    <script>
        const pillSizes = [1, 2, 3, 5];
        let selected = new Set();

        // สร้างปุ่ม
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
                btnElement.classList.add('active'); // ✅ เปลี่ยนสีทันทีตรงนี้!
            }
            // เปิด/ปิดปุ่มยืนยัน
            document.getElementById('submitBtn').disabled = selected.size === 0;
        }

        async function sendData() {
            if (!liff.isInClient()) {
                alert("กรุณาเปิดใน LINE"); return;
            }
            const sorted = Array.from(selected).sort((a,b) => a-b);
            const msgText = "ยืนยันยา: " + sorted.join(", ");
            
            try {
                await liff.sendMessages([{ type: 'text', text: msgText }]);
                liff.closeWindow();
            } catch (err) {
                alert("Error sending message: " + err);
            }
        }

        // เริ่มต้น LIFF
        liff.init({ liffId: "{{ liff_id }}" }).then(() => {
            if (!liff.isLoggedIn()) liff.login();
        });
    </script>
</body>
</html>
"""

# ✅ Route ใหม่สำหรับ LIFF
@app.route("/liff/pill-selector")
def liff_pill_selector():
    return render_template_string(LIFF_HTML, liff_id=LIFF_ID)


# ==========================================
# 📐 Logic คำนวณ (เหมือนเดิม)
# ==========================================
def get_dose_adjustment_range(inr, current_dose):
    skip_days = 0
    if inr < 1.5: return current_dose*1.15, current_dose*1.20, "เพิ่มขนาดยา 10-20% (INR ต่ำกว่าเป้าหมาย)", 0
    elif 1.5 <= inr <= 1.9: return current_dose*1.05, current_dose*1.10, "เพิ่มขนาดยา 5-10% (INR ต่ำกว่าเป้าหมายเล็กน้อย)", 0
    elif 2.0 <= inr <= 3.0: return current_dose*0.98, current_dose*1.02, "คงขนาดยาเดิม (Target Achieved)", 0
    elif 3.1 <= inr <= 3.9: return current_dose*0.90, current_dose*0.95, "ลดขนาดยา 5-10% (INR สูงกว่าเป้าหมายเล็กน้อย)", 0
    elif 4.0 <= inr <= 4.9: return current_dose*0.895, current_dose*0.905, "⚠️ งดยา 1 วัน (Hold 1 day) แล้วลดขนาดยาลง 10%", 1
    elif 5.0 <= inr <= 8.9: return current_dose*0.84, current_dose*0.86, "⛔️ อันตราย: งดยา 1-2 วัน และควรทาน Vit K1", 2
    elif inr >= 9.0: return None, None, "🚨 EMERGENCY: หยุดยาและรีบพบแพทย์ทันที", 7
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
                    active_days = sum([1 for d, c in zip([dose_a, dose_b, dose_c], [count_a, count_b, count_c]) if d > 0 and c > 0]) # approximate active days check
                    # (Simplified logic for brevity, assuming standard logic works)
                    schedule_list = [dose_a]*count_a + [dose_b]*count_b + [dose_c]*count_c
                    pill_summary = {}
                    for d in schedule_list:
                        if d > 0:
                            t_size, t_count = daily_opts_map.get(d, (0,0))
                            pill_summary[t_size] = pill_summary.get(t_size, 0) + t_count
                    candidates.append({"schedule": schedule_list, "sum": weekly_sum, "unique": len(set(schedule_list)), "summary": pill_summary})
    
    if not candidates: return None, 0, {}
    target = (min_weekly+max_weekly)/2
    candidates.sort(key=lambda x: (abs(x['sum']-target), x['unique']))
    
    best = candidates[0]['schedule']
    # fill with 0 to make 7 days
    while len(best) < 7: best.append(0)
    best = best[:7]
    best.sort(reverse=True)
    return best, candidates[0]['sum'], candidates[0]['summary']

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

    # 1. Trigger LIFF Button
    if text == "ช่วยจัดยา warfarin":
        # สร้างปุ่มให้กดเปิด LIFF
        flex = FlexSendMessage(
            alt_text="เปิดหน้าเลือกยา",
            contents=BubbleContainer(
                body=BoxComponent(
                    layout="vertical",
                    contents=[
                        TextComponent(text="💊 ระบบช่วยจัดยา", weight="bold", size="lg", color="#1E90FF", align="center"),
                        TextComponent(text="กรุณากดปุ่มด้านล่างเพื่อเลือกขนาดยาที่มีใน รพ.", wrap=True, size="xs", color="#aaaaaa", align="center", margin="sm"),
                        ButtonComponent(
                            style="primary", 
                            color="#00C851", 
                            height="sm", 
                            margin="md",
                            action=URIAction(label="เลือกขนาดยา (เปิดเต็มจอ)", uri=f"https://liff.line.me/{LIFF_ID}")
                        )
                    ]
                )
            )
        )
        line_bot_api.reply_message(event.reply_token, flex)
        return

    # 2. รับค่ากลับมาจาก LIFF (User กด Done ในเว็บ -> เว็บพิมพ์ส่งมาว่า "ยืนยันยา: 1, 3")
    if text.startswith("ยืนยันยา:"):
        try:
            # แกะข้อมูลตัวเลข
            data_str = text.replace("ยืนยันยา:", "").strip()
            # แปลง "1, 3" -> [1.0, 3.0]
            selected_tabs = [float(x.strip()) for x in data_str.split(",") if x.strip()]
            
            user_sessions[user_id] = {
                'available_tabs': selected_tabs,
                'step': 'input_dose'
            }
            
            # ถามต่อเลย
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✅ รับทราบยา: {data_str} mg\n\n👉 พิมพ์ 'ขนาดยาเดิมต่อสัปดาห์' (mg/wk) ส่งมาได้เลยครับ (เช่น 21)"))
            
        except:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ เกิดข้อผิดพลาดในการอ่านค่ายา กรุณาลองใหม่"))
        return

    # 3. Flow เดิม (Input Dose -> Input INR -> Result)
    if user_id in user_sessions and user_sessions[user_id].get('step'):
        step = user_sessions[user_id]['step']
        
        if step == 'input_dose':
            try:
                dose = float(text)
                user_sessions[user_id]['weekly_dose'] = dose
                user_sessions[user_id]['step'] = 'input_inr'
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="✅ บันทึกขนาดยาแล้ว\n👉 กรุณาพิมพ์ค่า INR ล่าสุด:"))
            except: line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ พิมพ์ตัวเลขเท่านั้น"))
            return

        if step == 'input_inr':
            try:
                inr = float(text)
                session = user_sessions[user_id]
                min_t, max_t, msg, skip = get_dose_adjustment_range(inr, session['weekly_dose'])
                
                if min_t is None:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
                    del user_sessions[user_id]
                    return

                schedule, final, summary = find_best_schedule_in_range(min_t, max_t, session['available_tabs'])
                
                if schedule:
                    if skip: 
                        for i in range(min(skip, 7)): schedule[i] = 0
                    
                    # (ส่วนแสดงผล Flex Message แบบเดิม - ขอละโค้ด Flex ตัวเดิมไว้ในที่นี้เพื่อให้โค้ดไม่ยาวเกินไป 
                    # แต่คุณสามารถ Copy ฟังก์ชัน build_strict_schedule_flex เดิมมาแปะใช้ตรงนี้ได้เลย)
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"📋 จัดยาสำเร็จ!\n(ตารางยา {final:.1f} mg/wk)\n{schedule}"))
                    del user_sessions[user_id] # จบ process
                else:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ จัดยาไม่ลงตัวกับขนาดที่มี"))
            except: line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ พิมพ์ตัวเลข INR เท่านั้น"))
            return

if __name__ == "__main__":
    app.run(port=5000)
