from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import os
import random

BOT_TOKEN = "8940346683:AAGv0cP4HXtCZd5BVEPahjHaRPqFJ-h6xBA"
BOT_USERNAME = "DoquizGame"
DEFAULT_CHANNEL = "@yashrahly"

# قراءة بنك الأسئلة
def get_questions_bank():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_path = os.path.join(base_dir, "questions.json")
    if not os.path.exists(file_path):
        file_path = "questions.json"
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

# إرسال طلب إلى تيليجرام
def call_telegram(method: str, payload: dict):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as res:
            return json.loads(res.read().decode("utf-8"))
    except Exception as e:
        print(f"Error calling telegram {method}: {e}")
        return {"ok": False, "error": str(e)}

# أزرار البلوكات
def get_blocks_keyboard():
    data = get_questions_bank()
    keyboard = []
    for key, block in data.items():
        keyboard.append([{"text": block["title"], "callback_data": f"blk:{key}"}])
    return {"inline_keyboard": keyboard}

# أزرار المواد
def get_subjects_keyboard(block_key: str):
    data = get_questions_bank()
    block = data.get(block_key, {})
    subjects = block.get("subjects", {})
    keyboard = []
    for key, subj in subjects.items():
        keyboard.append([{"text": subj["title"], "callback_data": f"subj:{block_key}:{key}"}])
    keyboard.append([{"text": "🔙 رجوع للبلوكات", "callback_data": "back_blocks"}])
    return {"inline_keyboard": keyboard}

# أزرار ضبط الوقت
def get_timer_keyboard(block_key: str, subject_key: str, current_minutes: int):
    return {
        "inline_keyboard": [
            [
                {"text": "🔼 +5 د", "callback_data": f"time_adj:{block_key}:{subject_key}:5"},
                {"text": "🔼 +1 د", "callback_data": f"time_adj:{block_key}:{subject_key}:1"}
            ],
            [
                {"text": "🔽 -5 د", "callback_data": f"time_adj:{block_key}:{subject_key}:-5"},
                {"text": "🔽 -1 د", "callback_data": f"time_adj:{block_key}:{subject_key}:-1"}
            ],
            [
                {"text": "♾️ وقت مفتوح (بدون مؤقت)", "callback_data": f"time_set:{block_key}:{subject_key}:0"}
            ],
            [
                {"text": "🚀 بدء الجولة الآن (20 سؤال)", "callback_data": f"start_round:{block_key}:{subject_key}:{current_minutes}"}
            ],
            [
                {"text": "🔙 رجوع للمواد", "callback_data": f"blk:{block_key}"}
            ]
        ]
    }

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        response = {
            "status": "ok",
            "service": "Doquiz Medical Telegram Bot on Vercel 24/7",
            "bot": f"@{BOT_USERNAME}"
        }
        self.wfile.write(json.dumps(response).encode("utf-8"))

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        
        try:
            update = json.loads(post_data.decode("utf-8"))
            self.process_update(update)
        except Exception as e:
            print(f"Error processing update: {e}")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))

    def process_update(self, update: dict):
        # 1. معالجة الرسائل
        if "message" in update:
            msg = update["message"]
            text = msg.get("text", "")
            chat_id = msg["chat"]["id"]
            first_name = msg.get("from", {}).get("first_name", "دكتور")

            if text.startswith("/start"):
                welcome = (
                    f"مرحباً بك يا **{first_name}** في بوت الاختبارات **Doquiz** 🧠✨\n\n"
                    "هنا يمكنك خوض تجربة اختبارات تفاعلية مميزة\n\n"
                    "👇 **الخطوة 1:** اختر البلوك الدراسي الذي ترغب في اختباره:"
                )
                call_telegram("sendMessage", {
                    "chat_id": chat_id,
                    "text": welcome,
                    "parse_mode": "Markdown",
                    "reply_markup": get_blocks_keyboard()
                })

            elif text.startswith("/post"):
                parts = text.split()
                target = parts[1] if len(parts) > 1 else DEFAULT_CHANNEL
                announcement = (
                    "🩺 **نظام الجولات السريرية الذكية (Doquiz) متاح الآن!**\n\n"
                    "نقدّم لطلابنا الأعزاء اختبارات تفاعلية بنظام الجولات (20 سؤالاً):\n"
                    "🩸 **بلوك Blood & Lymph** (Pathology | Pharmacology | Microbiology)\n"
                    "🔹 بنك أسئلة تكيفي يستهدف نقاط الضعف ويثبت المعلومات\n"
                    "🔹 مؤقت زمني قابل للتخصيص وشرح تفصيلي لكل سؤال\n\n"
                    "👇 اضغط على الزر أدناه لبدء جولتك الأولى:"
                )
                call_telegram("sendMessage", {
                    "chat_id": target,
                    "text": announcement,
                    "parse_mode": "Markdown",
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": "🚀 ابدأ جولة الاختبار الآن", "url": f"https://t.me/{BOT_USERNAME}?start=channel"}]
                        ]
                    }
                })
                call_telegram("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"✅ تم نشر إعلان الاختبار في القناة: {target}"
                })

        # 2. معالجة ضغطات الأزرار (Callback Queries)
        elif "callback_query" in update:
            cb = update["callback_query"]
            data = cb.get("data", "")
            chat_id = cb["message"]["chat"]["id"]
            msg_id = cb["message"]["message_id"]

            call_telegram("answerCallbackQuery", {"callback_query_id": cb["id"]})

            if data == "back_blocks":
                welcome = "👇 **الخطوة 1:** اختر البلوك الدراسي الذي ترغب في اختباره:"
                call_telegram("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": welcome,
                    "parse_mode": "Markdown",
                    "reply_markup": get_blocks_keyboard()
                })

            elif data.startswith("blk:"):
                block_key = data.split(":")[1]
                data_bank = get_questions_bank()
                block = data_bank.get(block_key, {})
                text = (
                    f"🩸 **البلوك المختار:** {block.get('title', '')}\n"
                    f"ℹ️ {block.get('description', '')}\n\n"
                    "👇 **الخطوة 2:** اختر المادة التي ترغب باختبارها في هذا البلوك:"
                )
                call_telegram("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "reply_markup": get_subjects_keyboard(block_key)
                })

            elif data.startswith("subj:"):
                _, block_key, subject_key = data.split(":")
                data_bank = get_questions_bank()
                block = data_bank.get(block_key, {})
                subj = block.get("subjects", {}).get(subject_key, {})
                total_bank = len(subj.get("questions", []))

                text = (
                    f"🩸 **البلوك:** {block.get('title', '')}\n"
                    f"📚 **المادة:** {subj.get('title', '')}\n"
                    f"📊 إجمالي بنك الأسئلة: {total_bank} سؤالاً.\n"
                    "───────────────\n"
                    "🎯 **نظام الجولة:** 20 سؤالاً سريرياً في كل مرحلة.\n"
                    "💡 يتم اختيار الأسئلة الجديدة أولاً ثم الأسئلة السابقة التي تحتاج لتثبيت.\n\n"
                    "⏱️ **الوقت المحدد للجولة:** **[ مفتوح ♾️ (بدون مؤقت) ]**\n"
                    "يمكنك تعديل الوقت بالأزرار أدناه أو البدء فوراً:"
                )
                call_telegram("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "reply_markup": get_timer_keyboard(block_key, subject_key, 0)
                })

            elif data.startswith("time_adj:") or data.startswith("time_set:"):
                parts = data.split(":")
                block_key = parts[1]
                subject_key = parts[2]
                val = int(parts[3])

                data_bank = get_questions_bank()
                block = data_bank.get(block_key, {})
                subj = block.get("subjects", {}).get(subject_key, {})
                total_bank = len(subj.get("questions", []))

                if data.startswith("time_set:"):
                    new_time = val
                else:
                    cur_text = cb["message"].get("text", "")
                    cur_time = 0
                    if "[" in cur_text and "دقيقة" in cur_text:
                        try:
                            cur_time = int(cur_text.split("[")[1].split("دقيقة")[0].strip())
                        except Exception:
                            cur_time = 0
                    new_time = max(0, min(120, cur_time + val))

                time_display = "مفتوح ♾️ (بدون مؤقت)" if new_time == 0 else f"{new_time} دقيقة ⏱️"

                text = (
                    f"🩸 **البلوك:** {block.get('title', '')}\n"
                    f"📚 **المادة:** {subj.get('title', '')}\n"
                    f"📊 إجمالي بنك الأسئلة: {total_bank} سؤالاً.\n"
                    "───────────────\n"
                    "🎯 **نظام الجولة:** 20 سؤالاً سريرياً في كل مرحلة.\n"
                    "💡 يتم اختيار الأسئلة الجديدة أولاً ثم الأسئلة السابقة التي تحتاج لتثبيت.\n\n"
                    f"⏱️ **الوقت المحدد للجولة:** **[ {time_display} ]**\n"
                    "يمكنك تعديل الوقت بالأزرار أدناه أو البدء فوراً:"
                )
                call_telegram("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "reply_markup": get_timer_keyboard(block_key, subject_key, new_time)
                })

            elif data.startswith("start_round:"):
                _, block_key, subject_key, mins_str = data.split(":")
                self.launch_round(chat_id, block_key, subject_key, int(mins_str), msg_id)

            elif data.startswith("new_round:"):
                _, block_key, subject_key = data.split(":")
                self.launch_round(chat_id, block_key, subject_key, 0)

    def launch_round(self, chat_id: int, block_key: str, subject_key: str, minutes: int, edit_msg_id: int = None):
        data_bank = get_questions_bank()
        block = data_bank.get(block_key, {})
        subj = block.get("subjects", {}).get(subject_key, {})
        questions = subj.get("questions", [])

        if not questions:
            call_telegram("sendMessage", {"chat_id": chat_id, "text": "لا توجد أسئلة متوفرة حالياً."})
            return

        selected = random.sample(questions, min(len(questions), 20))
        q = selected[0]

        start_text = (
            f"🚀 **استعد! بدأت جولة جديدة من 20 سؤالاً:**\n"
            f"🩸 **البلوك:** {block.get('title', '')}\n"
            f"📚 **المادة:** {subj.get('title', '')}\n"
            f"🎯 عدد أسئلة الجولة: {len(selected)} سؤالاً.\n"
            f"⏱️ الوقت: {'مفتوح' if minutes == 0 else f'{minutes} دقيقة'}\n\n"
            "بالتوفيق يا دكتور! 🩺🌟"
        )

        if edit_msg_id:
            call_telegram("editMessageText", {
                "chat_id": chat_id,
                "message_id": edit_msg_id,
                "text": start_text,
                "parse_mode": "Markdown"
            })
        else:
            call_telegram("sendMessage", {
                "chat_id": chat_id,
                "text": start_text,
                "parse_mode": "Markdown"
            })

        # إرسال السؤال الأول فورياً
        q_text = f"السؤال (1 من {len(selected)}):\n{q['question']}"
        call_telegram("sendPoll", {
            "chat_id": chat_id,
            "question": q_text[:300],
            "options": [opt[:100] for opt in q["options"]],
            "type": "quiz",
            "correct_option_id": q["correct_id"],
            "explanation": (q.get("explanation") or "إجابة صحيحة!")[:200],
            "is_anonymous": False
        })
