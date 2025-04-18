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

LINE_CHANNEL_ACCESS_TOKEN = "hJrtsmcBM9LT0m0jEC6h4dbp0ZWek8DwJ77PW7hypvMbGNPnld0vtFiuUpb5dXB0oiKgDAVO6C3duZARQMiLggsUmKew7SA2MoPECS9gDFebh/W0fk6ITXbzgVD3WX6iCdpdPZfaRA54aQXeEU5ezwdB04t89/1O/w1cDnyilFU="
LINE_CHANNEL_SECRET = "b178fc8ba767114ad57ac6ab93c312ab"

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

quick_reply_buttons = QuickReply(
    items=[
        QuickReplyButton(action=MessageAction(label="คำแนะนำ", text="คำแนะนำ")),
        QuickReplyButton(action=MessageAction(label="เกี่ยวกับ", text="เกี่ยวกับ")),
        QuickReplyButton(action=MessageAction(label="ตัวอย่าง", text="35"))
    ]
)

def adjust_warfarin_dose(inr, current_dose):
    if inr < 1.5:
        new_dose = current_dose * 1.15
    elif 1.5 <= inr <= 1.9:
        new_dose = current_dose * 1.075
    elif 2.0 <= inr <= 3.0:
        new_dose = current_dose
    elif 3.1 <= inr <= 3.9:
        new_dose = current_dose * 0.925
    elif 4.0 <= inr <= 4.9:
        new_dose = current_dose * 0.9
    else:
        return None
    return round(new_dose)

def build_schedule_flex(inr, old_dose, new_dose, schedule_list):
    days = ['จ', 'อ', 'พ', 'พฤ', 'ศ', 'ส', 'อา']

    def dose_to_tablet_text(dose):
        if dose in [1, 2, 4]:
            tablets = dose / 2
            tablet_text = "ครึ่งเม็ด" if tablets == 0.5 else f"{tablets:.1f} เม็ด"
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

    items = [
        TextComponent(text=f"INR: {inr}", size="md"),
        TextComponent(text=f"ขนาดยาเดิม: {old_dose:.1f} mg/wk", size="md"),
        TextComponent(text=f"ขนาดยาใหม่: {new_dose:.1f} mg/wk", size="md"),
    ]
    items += [TextComponent(text=f"{days[i]}: {dose_to_tablet_text(schedule_list[i])}", size="md") for i in range(7)]

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
                TextComponent(text="🩺 ผลคำนวณ Warfarin", weight="bold", size="lg"),
                BoxComponent(
                    layout="vertical",
                    margin="md",
                    spacing="sm",
                    contents=items
                )
            ]
        )
    )
    return FlexSendMessage(alt_text="ผลลัพธ์ตารางยา Warfarin", contents=bubble)

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

    if "," in text:
        parts = [x.strip() for x in text.split(",")]
        if len(parts) == 2:
            try:
                inr = float(parts[0])
                old_dose = float(parts[1])
                new_dose = adjust_warfarin_dose(inr, old_dose)
                if new_dose:
                    schedule = generate_schedule(new_dose)
                    flex_msg = build_schedule_flex(inr, old_dose, new_dose, schedule)
                    line_bot_api.reply_message(event.reply_token, flex_msg)
                    return
                else:
                    reply = "❌ INR สูงเกินไป ต้องปรึกษาแพทย์"
            except ValueError:
                reply = "❌ กรุณาพิมพ์ INR และขนาดยา เช่น 2.5,35"
        else:
            reply = "❌ กรุณาพิมพ์เฉพาะ 2 ค่า (INR, ขนาดยาเดิม) เช่น 2.5,35"
    else:
        try:
            number = float(text)
            if number > 70:
                reply = "⚠️ ขนาดยาเกิน 70 mg/สัปดาห์\nโปรดปรึกษาแพทย์"
            elif number < 7.0:
                reply = "⚠️ ขนาดยาต่ำกว่า 7 mg/สัปดาห์\nไม่รองรับ"
            else:
                schedule = generate_schedule(number)
                flex_msg = build_schedule_flex("-", number, number, schedule)
                line_bot_api.reply_message(event.reply_token, flex_msg)
                return
        except:
            reply = "❌ กรุณาพิมพ์เลขขนาดยา เช่น 35 หรือ 36.5"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply, quick_reply=quick_reply_buttons))

@app.route("/", methods=["GET"])
def index():
    return "Warfy Bot is running!"

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
