from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FlexSendMessage, BubbleContainer, BoxComponent, TextComponent
)
import os

app = Flask(__name__)

# ตั้งค่าจาก LINE Developer Console
LINE_CHANNEL_ACCESS_TOKEN = "hJrtsmcBM9LT0m0jEC6h4dbp0ZWek8DwJ77PW7hypvMbGNPnld0vtFiuUpb5dXB0oiKgDAVO6C3duZARQMiLggsUmKew7SA2MoPECS9gDFebh/W0fk6ITXbzgVD3WX6iCdpdPZfaRA54aQXeEU5ezwdB04t89/1O/w1cDnyilFU="
LINE_CHANNEL_SECRET = "b178fc8ba767114ad57ac6ab93c312ab"

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ฟังก์ชันคำนวณขนาดยาใหม่ตาม INR
def adjust_warfarin_dose(inr, current_dose):
    if inr < 1.5:
        new_dose = current_dose * 1.2
        message = "เพิ่มขนาดยา 10-20%"
    elif 1.5 <= inr <= 1.9:
        new_dose = current_dose * 1.05
        message = "เพิ่มขนาดยา 5-10%"
    elif 2.0 <= inr <= 3.0:
        new_dose = current_dose
        message = "คงขนาดยาเดิม"
    elif 3.1 <= inr <= 3.9:
        new_dose = current_dose * 0.95
        message = "ลดขนาดยา 5-10%"
    elif 4.0 <= inr <= 4.9:
        new_dose = current_dose * 0.9
        message = "งดยา 1 วัน และลดขนาดยา 10%"
    elif 5.0 <= inr <= 8.9:
        new_dose = current_dose * 0.8
        message = "งดยา 1-2 วัน และให้ Vitamin K1 1mg และลดขนาดยา 20%"
    elif inr >= 9.0:
        new_dose = current_dose * 0.7
        message = "หยุดยาและให้ Vitamin K1 5-10mg"
    else:
        new_dose = current_dose
        message = "กรุณาปรึกษาแพทย์"

    # ปัดเศษให้เป็นจำนวนเต็มสวยๆ
    new_dose = round(new_dose)
    return new_dose, message

# ฟังก์ชันสร้าง Flex ตาราง

def build_schedule_flex(dose_per_week, schedule_list, inr=None, previous_dose=None, adjustment_message=None):
    days = ['จ', 'อ', 'พ', 'พฤ', 'ศ', 'ส', 'อา']

    def dose_to_tablet_text(dose):
        if dose in [1, 2, 4]:
            tablets = dose / 2
            tablet_text = "ครึ่งเม็ด" if tablets == 0.5 else f"{tablets:.1f} เม็ด"
            return f"{dose} mg (2mg x {tablet_text})"
        elif dose in [1.5, 3, 4.5, 6]:
            tablets = dose / 3
            tablet_text = "ครึ่งเม็ด" if tablets == 0.5 else f"{tablets:.1f} เม็ด"
            return f"{dose} mg (3mg x {tablet_text})"
        elif dose in [2.5, 5, 7.5, 10]:
            tablets = dose / 5
            tablet_text = "ครึ่งเม็ด" if tablets == 0.5 else f"{tablet_text} เม็ด"
            return f"{dose} mg (5mg x {tablet_text})"
        else:
            return f"{dose} mg"

    items = [TextComponent(text=f"{days[i]}: {dose_to_tablet_text(schedule_list[i])}", size="md") for i in range(7)]

    if inr is not None and previous_dose is not None and adjustment_message is not None:
        items.extend([
            TextComponent(text=f"🔹 INR: {inr}", size="sm"),
            TextComponent(text=f"🔹 ขนาดเดิม: {previous_dose} mg/สัปดาห์", size="sm"),
            TextComponent(text=f"🔹 ขนาดใหม่: {dose_per_week} mg/สัปดาห์", size="sm"),
            TextComponent(text=f"🔹 การปรับยา: {adjustment_message}", size="sm", wrap=True, margin="md")
        ])
    summary = {"2mg": 0, "3mg": 0, "5mg": 0}
    for dose in schedule_list:
        if dose in [1, 2, 4]:
            summary["2mg"] += dose / 2
        elif dose in [1.5, 3, 4.5, 6]:
            summary["3mg"] += dose / 3
        elif dose in [2.5, 5, 7.5, 10]:
            summary["5mg"] += dose / 5

    summary_lines = [f"รวมใช้ {k}: {v:.1f} เม็ด/สัปดาห์" for k, v in summary.items() if v > 0]
    summary_text = "\n" + "\n".join(summary_lines) if summary_lines else ""

    items.append(TextComponent(text=summary_text, wrap=True, margin="lg", size="sm", weight="bold"))

    bubble = BubbleContainer(
        body=BoxComponent(
            layout="vertical",
            contents=[
                TextComponent(text=f"🔳 Warfarin {dose_per_week} mg/สัปดาห์", weight="bold", size="lg"),
                BoxComponent(
                    layout="vertical",
                    margin="md",
                    spacing="sm",
                    contents=items
                )
            ]
        )
    )

    return FlexSendMessage(alt_text="ตารางยา Warfarin", contents=bubble)

# สร้างตารางการกินยา

def generate_schedule(dose_per_week):
    strength_to_doses = {
        2: [1, 2, 4],
        3: [1.5, 3, 4.5, 6],
        5: [2.5, 5, 7.5, 10]
    }

    for strength, doses in strength_to_doses.items():
        for dose in doses:
            if abs(dose * 7 - dose_per_week) < 0.001:
                return [dose] * 7

    for main_strength, main_doses in strength_to_doses.items():
        for main_dose in main_doses:
            for alt_strength, alt_doses in strength_to_doses.items():
                for alt_dose in alt_doses:
                    for alt_days in range(0, 3):
                        main_days = 7 - alt_days
                        total = main_dose * main_days + alt_dose * alt_days

                        if abs(total - dose_per_week) < 0.001 and main_days >= 5:
                            daily_doses = [main_dose] * main_days + [alt_dose] * alt_days
                            if max(daily_doses) / min(daily_doses) <= 2:
                                dose_counts = [(dose, daily_doses.count(dose)) for dose in set(daily_doses)]
                                dose_counts.sort(key=lambda x: -x[1])
                                ordered_doses = []
                                for dose, count in dose_counts:
                                    ordered_doses.extend([dose] * count)
                                return ordered_doses
    return None

# Endpoint
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# รับข้อความ
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()

    try:
        if "," in text:
            inr_text, dose_text = text.split(",")
            inr = float(inr_text.strip())
            current_dose = float(dose_text.strip())
            new_dose, message = adjust_warfarin_dose(inr, current_dose)
            schedule = generate_schedule(new_dose)
            if schedule:
                flex_msg = build_schedule_flex(new_dose, schedule, inr, current_dose, message)
                line_bot_api.reply_message(event.reply_token, flex_msg)
            else:
                reply = f"❌ ปรับขนาดยา {new_dose} mg/สัปดาห์ แต่ไม่สามารถจัดตารางได้"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
            return
        else:
            number = float(text)
            if number > 70:
                reply = "⚠️ ขนาดยาเกิน 70 mg/สัปดาห์\nโปรดปรึกษาแพทย์"
            elif number < 7.0:
                reply = "⚠️ ขนาดยาต่ำสุดที่รองรับคือ 7 mg/สัปดาห์"
            else:
                schedule = generate_schedule(number)
                if schedule:
                    flex_msg = build_schedule_flex(number, schedule)
                    line_bot_api.reply_message(event.reply_token, flex_msg)
                    return
                else:
                    reply = "❌ ไม่สามารถจัดยาได้ตามเงื่อนไข"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    except:
        reply = "โปรดพิมพ์ INR, ขนาดยา เช่น 2.5,35 หรือแค่ขนาดยา 35"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# หน้า index
@app.route("/", methods=["GET"])
def index():
    return "Warfy Bot is running!"

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
