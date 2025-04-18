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

# LINE Developer Console setup
LINE_CHANNEL_ACCESS_TOKEN = "hJrtsmcBM9LT0m0jEC6h4dbp0ZWek8DwJ77PW7hypvMbGNPnld0vtFiuUpb5dXB0oiKgDAVO6C3duZARQMiLggsUmKew7SA2MoPECS9gDFebh/W0fk6ITXbzgVD3WX6iCdpdPZfaRA54aQXeEU5ezwdB04t89/1O/w1cDnyilFU="
LINE_CHANNEL_SECRET = "b178fc8ba767114ad57ac6ab93c312ab"

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Quick Reply
quick_reply_buttons = QuickReply(
    items=[
        QuickReplyButton(action=MessageAction(label="\u0e04\u0e33\u0e41\u0e19\u0e30", text="\u0e04\u0e33\u0e41\u0e19\u0e30")),
        QuickReplyButton(action=MessageAction(label="\u0e40\u0e01\u0e35\u0e48\u0e22\u0e27\u0e01\u0e31\u0e1a", text="\u0e40\u0e01\u0e35\u0e48\u0e22\u0e27\u0e01\u0e31\u0e1a")),
        QuickReplyButton(action=MessageAction(label="\u0e15\u0e31\u0e27\u0e2d\u0e22\u0e48\u0e32\u0e07", text="35"))
    ]
)

# Adjust Warfarin Dose
def adjust_warfarin_dose(inr, current_dose):
    if inr < 1.5:
        new_dose = current_dose * 1.15
    elif 1.5 <= inr <= 1.9:
        new_dose = current_dose * 1.075
    elif 2.0 <= inr <= 3.0:
        return int(round(current_dose)), "No change"
    elif 3.1 <= inr <= 3.9:
        new_dose = current_dose * 0.925
    elif 4.0 <= inr <= 4.9:
        new_dose = current_dose * 0.90
    elif 5.0 <= inr <= 8.9:
        return None, "Omit 1-2 doses, VitK1 1mg orally"
    elif inr >= 9.0:
        return None, "VitK1 5-10mg orally or Major bleeding protocol"
    else:
        return None, "Invalid INR"

    return int(round(new_dose)), "Dose adjusted"

# Endpoint Callback
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# Message Handling
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()

    # กรณีพิมพ์ INR,Dose เช่น 1.8,35
    if "," in text:
        try:
            inr_text, dose_text = text.split(",")
            inr = float(inr_text.strip())
            current_dose = float(dose_text.strip())
            new_dose, message = adjust_warfarin_dose(inr, current_dose)
            if new_dose:
                reply = f"INR: {inr}\nขนาดยาเดิม: {current_dose} mg/week\nขนาดยาใหม่: {new_dose} mg/week\nคำแนะนำ: {message}"
            else:
                reply = f"INR: {inr}\n{message}"
        except:
            reply = "⚠️ รูปแบบข้อความผิด โปรดลองใหม่ เช่น 1.8,35"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # กรณีปกติ (พิมพ์ตัวเลขอย่างเดียว เช่น 35)
    try:
        number = float(text)
        if number > 70:
            reply = "⚠️ ขนาดยาเกิน 70 mg/สัปดาห์\nโปรดปรึกษาแพทย์ก่อนใช้ยา Warfarin ขนาดสูงกว่านี้เพื่อความปลอดภัย"
        elif number < 7.0:
            reply = "⚠️ ขนาดยาที่ต่ำที่สุดที่ระบบรองรับคือ 7 mg/สัปดาห์\n(เช่น 1.0 mg/วัน × 7 วัน)"
        else:
            schedule = generate_schedule(number)
            if schedule:
                flex_msg = build_schedule_flex(number, schedule)
                line_bot_api.reply_message(event.reply_token, flex_msg)
                return
            else:
                reply = "❌ ไม่สามารถจัดยาได้ตามเงื่อนไข"
    except:
        reply = "โปรดพิมพ์ INR,Dose เช่น 1.8,35"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply, quick_reply=quick_reply_buttons))


@app.route("/", methods=["GET"])
def index():
    return "Warfy Bot is running!"

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
