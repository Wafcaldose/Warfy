from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    QuickReply, QuickReplyButton, MessageAction,
    FlexSendMessage, BubbleContainer, BoxComponent, TextComponent
)

import os

app = Flask(__name__)

# ตั้งค่าจาก LINE Developer Console
LINE_CHANNEL_ACCESS_TOKEN = "hJrtsmcBM9LT0m0jEC6h4dbp0ZWek8DwJ77PW7hypvMbGNPnld0vtFiuUpb5dXB0oiKgDAVO6C3duZARQMiLggsUmKew7SA2MoPECS9gDFebh/W0fk6ITXbzgVD3WX6iCdpdPZfaRA54aQXeEU5ezwdB04t89/1O/w1cDnyilFU="
LINE_CHANNEL_SECRET = "b178fc8ba767114ad57ac6ab93c312ab"

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Quick Reply ปุ่มลัด
quick_reply_buttons = QuickReply(
    items=[
        QuickReplyButton(action=MessageAction(label="คำแนะนำ", text="คำแนะนำ")),
        QuickReplyButton(action=MessageAction(label="เกี่ยวกับ", text="เกี่ยวกับ")),
        QuickReplyButton(action=MessageAction(label="ตัวอย่าง", text="35"))
    ]
)

# Flex Message builder สำหรับ Warfarin
def build_schedule_flex(dose_per_week, schedule_list):
    days = ['จ', 'อ', 'พ', 'พฤ', 'ศ', 'ส', 'อา']

    def dose_to_tablet_text(dose):
        if dose in [1, 2, 4]:
            tablets = dose / 2
            tablet_text = "ครึ่งเม็ด" if tablets == 0.5 else f"{tablet_text:.1f} เม็ด"
            return f"{dose} mg (2mg x {tablet_text})"
        elif dose in [1.5, 3, 4.5, 6]:
            tablets = dose / 3
            tablet_text = "ครึ่งเม็ด" if tablets == 0.5 else f"{tablet_text:.1f} เม็ด"
            return f"{dose} mg (3mg x {tablet_text})"
        elif dose in [2.5, 5, 7.5, 10]:
            tablets = dose / 5
            tablet_text = "ครึ่งเม็ด" if tablets == 0.5 else f"{tablet_text:.1f} เม็ด"
            return f"{dose} mg (5mg x {tablet_text})"
        else:
            return f"{dose} mg"

    items = [TextComponent(text=f"{days[i]}: {dose_to_tablet_text(schedule_list[i])}", size="md") for i in range(7)]

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

# เวอร์ชัน Warfarin
def generate_schedule(dose_per_week):
    tablet_strengths = [2, 3, 5]
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

# เวอร์ชัน TB
def handle_tb_weight_input(event):
    try:
        weight = float(event.message.text)
    except ValueError:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="กรุณากรอกน้ำหนักเป็นตัวเลข เช่น 52"))
        return

    if weight < 35:
        reply_text = "❗ น้ำหนักน้อยกว่า 35 กก. ควรปรึกษาแพทย์เพื่อปรับขนาดยา"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    h_min = weight * 4
    h_max = weight * 6
    r_min = weight * 8
    r_max = weight * 12
    z_min = weight * 20
    z_max = weight * 30
    e_min = weight * 15
    e_max = weight * 20

    if 35 <= weight <= 49:
        recommended = {'H': 300, 'R': 450, 'Z': 1000, 'E': 800}
    elif 50 <= weight <= 69:
        recommended = {'H': 300, 'R': 600, 'Z': 1500, 'E': 1000}
    else:
        recommended = {'H': 300, 'R': 600, 'Z': 2000, 'E': 1200}

    flex_content = {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": "https://cdn-icons-png.flaticon.com/512/2972/2972381.png",
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover",
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": f"น้ำหนัก {weight:.1f} กก.", "weight": "bold", "size": "xl", "align": "center"},
                {"type": "separator", "margin": "md"},
                {"type": "box", "layout": "vertical", "margin": "md", "spacing": "sm", "contents": [
                    {"type": "text", "text": f"H: {h_min:.0f}-{h_max:.0f} mg (แนะนำ {recommended['H']} mg)", "wrap": True},
                    {"type": "text", "text": f"R: {r_min:.0f}-{r_max:.0f} mg (แนะนำ {recommended['R']} mg)", "wrap": True},
                    {"type": "text", "text": f"Z: {z_min:.0f}-{z_max:.0f} mg (แนะนำ {recommended['Z']} mg)", "wrap": True},
                    {"type": "text", "text": f"E: {e_min:.0f}-{e_max:.0f} mg (แนะนำ {recommended['E']} mg)", "wrap": True},
                ]}
            ]
        }
    }
    flex_message = FlexSendMessage(alt_text="ผลการคำนวณขนาดยา TB", contents=flex_content)
    line_bot_api.reply_message(event.reply_token, flex_message)

# route webhook
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# จัดการข้อความเข้า
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip()
    session = app.config.get(user_id, {})

    if text.lower() in ["เริ่ม", "start"]:
        reply = "เลือกโหมดการคำนวณ:"
        quick_mode = QuickReply(items=[
            QuickReplyButton(action=MessageAction(label="🧲 Warfarin", text="mode:warfarin")),
            QuickReplyButton(action=MessageAction(label="🧪 TB", text="mode:tb"))
        ])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply, quick_reply=quick_mode))
        return

    if text == "mode:warfarin":
        app.config[user_id] = {"mode": "warfarin"}
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="โหมด Warfarin: กรุณาพิมพ์ขนาดยา mg/สัปดาห์"))
        return

    if text == "mode:tb":
        app.config[user_id] = {"mode": "tb"}
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="โหมด TB: กรุณาพิมพ์น้ำหนักตัว (kg)"))
        return

    if text.replace('.', '', 1).isdigit():
        number = float(text)
        if session.get("mode") == "tb":
            handle_tb_weight_input(event)
            return
        else:
            if number > 70:
                reply = "⚠️ ขนาดยาเกิน 70 mg/สัปดาห์"
            elif number < 7.0:
                reply = "⚠️ ต่ำสุด 7 mg/สัปดาห์"
            else:
                schedule = generate_schedule(number)
                if schedule:
                    flex_msg = build_schedule_flex(number, schedule)
                    line_bot_api.reply_message(event.reply_token, flex_msg)
                    return
                else:
                    reply = "❌ ไม่สามารถจัดยาได้"
    else:
        reply = "โปรดเลือกโหมดหรือพิมพ์ตัวเลข"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply, quick_reply=quick_reply_buttons))

# route index
@app.route("/", methods=["GET"])
def index():
    return "Warfy Bot is running!"

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host="0.0.0.0", port=port)