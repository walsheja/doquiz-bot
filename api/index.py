from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import os
import random
import time

BOT_TOKEN = "8940346683:AAGv0cP4HXtCZd5BVEPahjHaRPqFJ-h6xBA"
BOT_USERNAME = "DoquizGame"
DEFAULT_CHANNEL = "@yashrahly"

# مسار حفظ جلسات المستخدمين في الذاكرة المؤقتة لـ Vercel
SESSIONS_FILE = "/tmp/doquiz_sessions.json"

def load_sessions() -> dict:
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_sessions(sessions: dict):
    try:
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(sessions, f, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving sessions: {e}")

def get_questions_bank():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_path = os.path.join(base_dir, "questions.json")
    if not os.path.exists(file_path):
        file_path = "questions.json"
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

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

def get_blocks_keyboard():
    data = get_questions_bank()
    keyboard = []
    for key, block in data.items():
        keyboard.append([{"text": block["title"], "callback_data": f"blk:{key}"}])
    return {"inline_keyboard": keyboard}

def get_subjects_keyboard(block_key: str):
    data = get_questions_bank()
    block = data.get(block_key, {})
    subjects = block.get("subjects", {})
    keyboard = []
    for key, subj in subjects.items():
        keyboard.append([{"text": subj["title"], "callback_data": f"subj:{block_key}:{key}"}])
    keyboard.append([{"text": "🔙 رجوع للبلوكات", "callback_data": "back_blocks"}])
    return {"inline_keyboard": keyboard}

def get_timer_keyboard(block_key: str, subject_key: str, current_minutes: int):
    """
    أزرار عداد الوقت: بخطوات 5 دقائق فقط حتى نصف ساعة (30 دقيقة) كحد أقصى وصفر كحد أدنى.
    يتم تضمين القيمة التالية المحسوبة مباشرة في الـ callback_data لضمان الاستجابة مع كل نقرة متكررة!
    """
    next_plus = min(30, current_minutes + 5)
    next_minus = max(0, current_minutes - 5)

    return {
        "inline_keyboard": [
            [
                {"text": "🔼 +5 دقائق", "callback_data": f"time_adj:{block_key}:{subject_key}:{next_plus}"},
                {"text": "🔽 -5 دقائق", "callback_data": f"time_adj:{block_key}:{subject_key}:{next_minus}"}
            ],
            [
                {"text": "♾️ وقت مفتوح (بدون مؤقت)", "callback_data": f"time_adj:{block_key}:{subject_key}:0"}
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
        self.wfile.write(json.dumps({
            "status": "ok",
            "service": "Doquiz Medical Telegram Bot on Vercel 24/7",
            "bot": f"@{BOT_USERNAME}"
        }).encode("utf-8"))

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
        # 1. الرسائل النصية
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

        # 2. ضغطات الأزرار
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
                    "يمكنك تعديل الوقت بالأزرار أدناه (حتى 30 دقيقة) أو البدء فوراً:"
                )
                call_telegram("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "reply_markup": get_timer_keyboard(block_key, subject_key, 0)
                })

            elif data.startswith("time_adj:"):
                parts = data.split(":")
                block_key = parts[1]
                subject_key = parts[2]
                new_minutes = int(parts[3])

                data_bank = get_questions_bank()
                block = data_bank.get(block_key, {})
                subj = block.get("subjects", {}).get(subject_key, {})
                total_bank = len(subj.get("questions", []))

                time_display = "مفتوح ♾️ (بدون مؤقت)" if new_minutes == 0 else f"{new_minutes} دقيقة ⏱️"

                text = (
                    f"🩸 **البلوك:** {block.get('title', '')}\n"
                    f"📚 **المادة:** {subj.get('title', '')}\n"
                    f"📊 إجمالي بنك الأسئلة: {total_bank} سؤالاً.\n"
                    "───────────────\n"
                    "🎯 **نظام الجولة:** 20 سؤالاً سريرياً في كل مرحلة.\n"
                    "💡 يتم اختيار الأسئلة الجديدة أولاً ثم الأسئلة السابقة التي تحتاج لتثبيت.\n\n"
                    f"⏱️ **الوقت المحدد للجولة:** **[ {time_display} ]**\n"
                    "يمكنك تعديل الوقت بالأزرار أدناه (حتى 30 دقيقة) أو البدء فوراً:"
                )
                call_telegram("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "reply_markup": get_timer_keyboard(block_key, subject_key, new_minutes)
                })

            elif data.startswith("start_round:"):
                _, block_key, subject_key, mins_str = data.split(":")
                self.launch_round(chat_id, block_key, subject_key, int(mins_str), msg_id)

            elif data.startswith("new_round:"):
                _, block_key, subject_key = data.split(":")
                self.clean_previous_round(chat_id)
                self.launch_round(chat_id, block_key, subject_key, 0)

        # 3. حل السؤال (Poll Answer)
        elif "poll_answer" in update:
            ans = update["poll_answer"]
            user_id = ans["user"]["id"]
            poll_id = ans["poll_id"]
            selected_option = ans["option_ids"][0] if ans.get("option_ids") else None

            self.handle_poll_answer(user_id, poll_id, selected_option)

    def clean_previous_round(self, chat_id: int):
        sessions = load_sessions()
        session = sessions.get(str(chat_id))
        if session:
            for m_id in session.get("poll_msg_ids", []):
                call_telegram("deleteMessage", {"chat_id": chat_id, "message_id": m_id})
            session["poll_msg_ids"] = []
            save_sessions(sessions)

    def launch_round(self, chat_id: int, block_key: str, subject_key: str, minutes: int, edit_msg_id: int = None):
        data_bank = get_questions_bank()
        block = data_bank.get(block_key, {})
        subj = block.get("subjects", {}).get(subject_key, {})
        questions = subj.get("questions", [])

        if not questions:
            call_telegram("sendMessage", {"chat_id": chat_id, "text": "لا توجد أسئلة متوفرة حالياً."})
            return

        selected = random.sample(questions, min(len(questions), 20))

        # حساب مؤقت السؤال: إذا حدد وقتاً (مثلاً 30 دقيقة لـ 20 سؤالاً)، نخصص دقيقة ونصف (90 ثانية) لكل سؤال!
        # وإذا كان الوقت مفتوحاً نضع دقيقتين (120 ثانية) لتفادي ترك السؤال معلقاً دون إجابة
        per_question_timeout = int((minutes * 60) / len(selected)) if minutes > 0 else 120
        # حدود تلجرام لـ open_period هي بين 5 و 600 ثانية
        open_period = max(15, min(300, per_question_timeout))

        sessions = load_sessions()
        sessions[str(chat_id)] = {
            "block_key": block_key,
            "subject_key": subject_key,
            "block_title": block.get("title", ""),
            "subject_title": subj.get("title", ""),
            "questions": selected,
            "current_index": 0,
            "score": 0,
            "total": len(selected),
            "minutes": minutes,
            "open_period": open_period,
            "poll_msg_ids": [],
            "poll_to_q": {}
        }
        save_sessions(sessions)

        start_text = (
            f"🚀 **استعد! بدأت جولة جديدة من {len(selected)} سؤالاً:**\n"
            f"🩸 **البلوك:** {block.get('title', '')}\n"
            f"📚 **المادة:** {subj.get('title', '')}\n"
            f"🎯 عدد أسئلة الجولة: {len(selected)} سؤالاً.\n"
            f"⏱️ مؤقت السؤال الواحد: {open_period} ثانية ⏳\n"
            f"⌛ إجمالي وقت الجولة: {'مفتوح' if minutes == 0 else f'{minutes} دقيقة'}\n\n"
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

        # إرسال السؤال الأول
        self.send_question(chat_id, 0)

    def send_question(self, chat_id: int, index: int):
        sessions = load_sessions()
        session = sessions.get(str(chat_id))
        if not session:
            return

        if index >= session["total"]:
            self.finish_round(chat_id, session)
            return

        q = session["questions"][index]
        q_text = f"السؤال ({index + 1} من {session['total']}):\n{q['question']}"

        poll_payload = {
            "chat_id": chat_id,
            "question": q_text[:300],
            "options": [opt[:100] for opt in q["options"]],
            "type": "quiz",
            "correct_option_id": q["correct_id"],
            "explanation": (q.get("explanation") or "إجابة صحيحة!")[:200],
            "is_anonymous": False,
            "open_period": session.get("open_period", 90)
        }

        res = call_telegram("sendPoll", poll_payload)
        if res.get("ok") and "poll" in res.get("result", {}):
            poll_id = res["result"]["poll"]["id"]
            msg_id = res["result"]["message_id"]

            session["current_index"] = index
            session["poll_msg_ids"].append(msg_id)
            session["poll_to_q"][poll_id] = index
            save_sessions(sessions)

    def handle_poll_answer(self, user_id: int, poll_id: str, selected_option: int):
        sessions = load_sessions()
        session = sessions.get(str(user_id))
        if not session:
            return

        cur_idx = session.get("poll_to_q", {}).get(poll_id)
        if cur_idx is None:
            cur_idx = session.get("current_index", 0)

        q = session["questions"][cur_idx]
        if selected_option is not None and selected_option == q["correct_id"]:
            session["score"] += 1

        save_sessions(sessions)

        # انتظار 1.8 ثانية لقراءة الشرح ثم إرسال السؤال التالي
        time.sleep(1.8)
        self.send_question(user_id, cur_idx + 1)

    def finish_round(self, chat_id: int, session: dict):
        score = session["score"]
        total = session["total"]
        block = session["block_title"]
        subject = session["subject_title"]
        percentage = int((score / total) * 100) if total > 0 else 0

        if percentage == 100:
            grade = "طبيب متميز! إجابات مثالية 100% 🏆🩺"
        elif percentage >= 80:
            grade = "ممتاز جداً! استيعاب قوي للمادة السريرية 🌟👏"
        elif percentage >= 60:
            grade = "جيد جداً! استمر في المراجعة لتعزيز معلوماتك 💪"
        else:
            grade = "محاولة طيبة! راجع الشروحات والأخطاء وكرر الجولة 📖🩺"

        result_text = (
            "🏁 **اكتملت الجولة بنجاح!**\n\n"
            f"🩸 **البلوك:** {block}\n"
            f"📚 **المادة:** {subject}\n"
            f"🎯 **الدرجة:** {score} من {total}\n"
            f"📊 **النسبة المئوية:** {percentage}%\n"
            f"💬 **التقييم:** {grade}\n\n"
            "💡 عند الضغط على **(بدء جولة جديدة)** سيتم تنظيف الشات وإطلاق جولة جديدة فوراً! 👇"
        )

        share_url = f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}&text=حققت%20{score}%20من%20{total}%20في%20جولة%20{subject}%20({block})!%20تحداني%20وجرب%20نفسك%20الآن%20🩺🧠"

        keyboard = {
            "inline_keyboard": [
                [{"text": "🔄 بدء جولة جديدة (20 سؤال)", "callback_data": f"new_round:{session['block_key']}:{session['subject_key']}"}],
                [{"text": "📚 اختيار بلوك / مادة أخرى", "callback_data": "back_blocks"}],
                [{"text": "📢 شارك نتيجتك مع زملائك", "url": share_url}]
            ]
        }

        call_telegram("sendMessage", {
            "chat_id": chat_id,
            "text": result_text,
            "parse_mode": "Markdown",
            "reply_markup": keyboard
        })
