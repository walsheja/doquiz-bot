from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.error
import os
import random
import time
import traceback
import firebase_admin
from firebase_admin import credentials, firestore

BOT_TOKEN = "8940346683:AAGv0cP4HXtCZd5BVEPahjHaRPqFJ-h6xBA"
BOT_USERNAME = "DoquizGame"
DEFAULT_CHANNEL = "@yashrahly"

_db = None

def get_firestore_db():
    global _db
    if _db is not None:
        return _db

    # 1. First priority: Environment variable
    cred_json = os.environ.get("FIREBASE_CREDENTIALS")
    if cred_json:
        try:
            cred_dict = json.loads(cred_json)
            if not firebase_admin._apps:
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
            _db = firestore.client()
            return _db
        except Exception as e:
            print(f"Error initializing Firebase from FIREBASE_CREDENTIALS env: {e}")

    # 2. Second priority: Local file paths
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    possible_paths = [
        os.path.join(base_dir, "firebase_credentials.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "firebase_credentials.json"),
        os.path.join(os.getcwd(), "firebase_credentials.json"),
        "firebase_credentials.json"
    ]
    for cred_path in possible_paths:
        if os.path.exists(cred_path):
            try:
                if not firebase_admin._apps:
                    cred = credentials.Certificate(cred_path)
                    firebase_admin.initialize_app(cred)
                _db = firestore.client()
                return _db
            except Exception as e:
                print(f"Error initializing Firebase from {cred_path}: {e}")

    raise RuntimeError("Could not initialize Firebase: credentials not found in env or files.")

def get_questions_bank():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    possible_paths = [
        os.path.join(base_dir, "questions.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "questions.json"),
        os.path.join(os.getcwd(), "questions.json"),
        "questions.json"
    ]
    for p in possible_paths:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError("questions.json not found in any expected location.")

def call_telegram(method: str, payload: dict):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        print(f"Telegram HTTPError in {method} (code {e.code}): {err_body}")
        try:
            return json.loads(err_body)
        except Exception:
            return {"ok": False, "error": err_body}
    except Exception as e:
        print(f"Error calling telegram {method}: {e}")
        return {"ok": False, "error": str(e)}

def get_blocks_keyboard():
    data = get_questions_bank()
    keyboard = []
    for key, block in data.items():
        total_q = sum(len(s.get("questions", [])) for s in block.get("subjects", {}).values())
        badge = f" ({total_q} سؤال)" if total_q > 0 else " (قريباً ⏳)"
        keyboard.append([{"text": f"{block['title']}{badge}", "callback_data": f"blk:{key}"}])
    return {"inline_keyboard": keyboard}

def get_subjects_keyboard(block_key: str):
    data = get_questions_bank()
    block = data.get(block_key, {})
    subjects = block.get("subjects", {})
    keyboard = []
    for key, subj in subjects.items():
        q_count = len(subj.get("questions", []))
        badge = f" ({q_count} سؤال)" if q_count > 0 else " (قريباً ⏳)"
        keyboard.append([{"text": f"{subj['title']}{badge}", "callback_data": f"subj:{block_key}:{key}"}])
    keyboard.append([{"text": "🔙 رجوع للبلوكات", "callback_data": "back_blocks"}])
    return {"inline_keyboard": keyboard}

def get_timer_keyboard(block_key: str, subject_key: str, current_minutes: int):
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
            "service": "Doquiz Medical Telegram Bot on Vercel with Firestore State",
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
            traceback.print_exc()

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
                    f"مرحباً بك يا **{first_name}** في بوت نماذج واختبارات الطب البشري **Doquiz** 🧠✨\n\n"
                    "👇 **الخطوة 1:** اختر البلوك الدراسي الذي ترغب في اختباره:"
                )
                call_telegram("sendMessage", {
                    "chat_id": chat_id,
                    "text": welcome,
                    "parse_mode": "Markdown",
                    "reply_markup": get_blocks_keyboard()
                })

            elif text.startswith("/stop") or text.startswith("/cancel"):
                try:
                    db = get_firestore_db()
                    session_doc = db.collection("doquiz_sessions").document(str(chat_id)).get()
                    if session_doc.exists:
                        session = session_doc.to_dict()
                        call_telegram("sendMessage", {
                            "chat_id": chat_id,
                            "text": "🛑 **تم إيقاف الاختبار بناءً على طلبك.**\nجاري احتساب نتيجتك لما تم حله حتى الآن...",
                            "parse_mode": "Markdown"
                        })
                        self.finish_round(chat_id, session)
                    else:
                        call_telegram("sendMessage", {
                            "chat_id": chat_id,
                            "text": "لا يوجد اختبار نشط حالياً لإيقافه. يمكنك بدء اختبار جديد عبر القائمة أدناه 🩺",
                            "reply_markup": get_blocks_keyboard()
                        })
                except Exception as e:
                    print(f"Stop command error: {e}")
                    traceback.print_exc()

            elif text.startswith("/post"):
                parts = text.split()
                target = parts[1] if len(parts) > 1 else DEFAULT_CHANNEL
                announcement = (
                    "🩺 **بوت نماذج واختبارات الطب البشري (Doquiz)** 🧠✨\n\n"
                    "نقدّم لطلابنا الأعزاء تجربة اختبارات تفاعلية بنظام الجولات السريرية الذكية (20 سؤالاً):\n\n"
                    "🩸 **بلوك Blood & Lymph** (متاح الآن: 174 سؤال باثولوجي + 120 سؤال ميكروبيولوجي)\n"
                    "🔹 نظام تكيفي ذكي يركز على نقاط الضعف ويثبت المعلومات الطبية\n"
                    "🔹 مؤقت زمني اختياري وشرح سريري تفصيلي لكل سؤال\n\n"
                    "👇 اضغط على الزر أدناه لبدء اختبارك مباشرة في البوت:"
                )
                res = call_telegram("sendMessage", {
                    "chat_id": target,
                    "text": announcement,
                    "parse_mode": "Markdown",
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": "🚀 ابدأ جولة الاختبار الآن", "url": f"https://t.me/{BOT_USERNAME}?start=channel"}]
                        ]
                    }
                })
                if res.get("ok"):
                    call_telegram("sendMessage", {
                        "chat_id": chat_id,
                        "text": f"✅ تم نشر إعلان الاختبار بنجاح في القناة: {target}"
                    })
                else:
                    err_desc = res.get("description") or res.get("error") or "خطأ غير معروف"
                    call_telegram("sendMessage", {
                        "chat_id": chat_id,
                        "text": (
                            f"⚠️ **تعذر النشر في القناة ({target}):**\n`{err_desc}`\n\n"
                            f"💡 **تأكد من:**\n"
                            f"1. إضافة البوت **@{BOT_USERNAME}** كمشرف (Admin) في القناة.\n"
                            f"2. منحه صلاحية **نشر الرسائل (Post Messages)**."
                        ),
                        "parse_mode": "Markdown"
                    })

        # 2. ضغطات الأزرار (Callback Queries)
        elif "callback_query" in update:
            cb = update["callback_query"]
            data = cb.get("data", "")
            chat_id = cb["message"]["chat"]["id"]
            msg_id = cb["message"]["message_id"]

            call_telegram("answerCallbackQuery", {
                "callback_query_id": cb["id"],
                "text": "تم الاختيار 🩺"
            })

            if data == "back_blocks":
                welcome = "👇 **الخطوة 1:** اختر البلوك الدراسي الذي ترغب في اختباره:"
                res = call_telegram("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": welcome,
                    "parse_mode": "Markdown",
                    "reply_markup": get_blocks_keyboard()
                })
                if not res.get("ok"):
                    call_telegram("sendMessage", {
                        "chat_id": chat_id,
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
                res = call_telegram("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "reply_markup": get_subjects_keyboard(block_key)
                })
                if not res.get("ok"):
                    call_telegram("sendMessage", {
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                        "reply_markup": get_subjects_keyboard(block_key)
                    })

            elif data.startswith("subj:"):
                _, block_key, subject_key = data.split(":")
                data_bank = get_questions_bank()
                block = data_bank.get(block_key, {})
                subj = block.get("subjects", {}).get(subject_key, {})
                questions = subj.get("questions", [])
                total_bank = len(questions)

                if total_bank == 0:
                    text = (
                        f"🩺 **البلوك:** {block.get('title', '')}\n"
                        f"📚 **المادة:** {subj.get('title', '')}\n\n"
                        "⚠️ **بنك أسئلة هذه المادة قيد الإعداد والتجهيز!**\n"
                        "سيتم إتاحته قريباً بإذن الله عند اكتمال ملفات الأسئلة. 🩺\n\n"
                        "👈 يرجى اختيار مادة مفعلة حالياً في هذا البلوك:\n"
                        "• **علم الأمراض (Pathology) - 174 سؤالاً**\n"
                        "• **الأحياء الدقيقة (Microbiology) - 120 سؤالاً**"
                    )
                    reply_markup = {
                        "inline_keyboard": [
                            [{"text": "🔙 رجوع لاختيار مادة أخرى", "callback_data": f"blk:{block_key}"}]
                        ]
                    }
                    res = call_telegram("editMessageText", {
                        "chat_id": chat_id,
                        "message_id": msg_id,
                        "text": text,
                        "parse_mode": "Markdown",
                        "reply_markup": reply_markup
                    })
                    if not res.get("ok"):
                        call_telegram("sendMessage", {
                            "chat_id": chat_id,
                            "text": text,
                            "parse_mode": "Markdown",
                            "reply_markup": reply_markup
                        })
                    return

                text = (
                    f"🩸 **البلوك:** {block.get('title', '')}\n"
                    f"📚 **المادة:** {subj.get('title', '')}\n"
                    f"📊 إجمالي بنك الأسئلة المتاح: {total_bank} سؤالاً سريرياً.\n"
                    "───────────────\n"
                    "🎯 **نظام الجولة:** 20 سؤالاً في كل مرحلة.\n"
                    "💡 يتم تقديم الأسئلة غير المختبرة سابقاً أولاً، ثم الأسئلة التي تحتاج إلى تثبيت.\n\n"
                    "⏱️ **الوقت المحدد للجولة:** **[ مفتوح ♾️ (بدون مؤقت) ]**\n"
                    "يمكنك تعديل الوقت بالأزرار أدناه (حتى 30 دقيقة) أو البدء فوراً:"
                )
                res = call_telegram("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "reply_markup": get_timer_keyboard(block_key, subject_key, 0)
                })
                if not res.get("ok"):
                    call_telegram("sendMessage", {
                        "chat_id": chat_id,
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
                    f"📊 إجمالي بنك الأسئلة المتاح: {total_bank} سؤالاً سريرياً.\n"
                    "───────────────\n"
                    "🎯 **نظام الجولة:** 20 سؤالاً في كل مرحلة.\n"
                    "💡 يتم تقديم الأسئلة غير المختبرة سابقاً أولاً، ثم الأسئلة التي تحتاج إلى تثبيت.\n\n"
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
            user_id = ans.get("user", {}).get("id")
            poll_id = str(ans.get("poll_id"))
            selected_option = ans["option_ids"][0] if ans.get("option_ids") else None

            print(f"Update poll_answer received for user {user_id}, poll {poll_id}, option {selected_option}")
            self.handle_poll_answer(user_id, poll_id, selected_option)

    def clean_previous_round(self, chat_id: int):
        try:
            db = get_firestore_db()
            session_doc = db.collection("doquiz_sessions").document(str(chat_id)).get()
            if session_doc.exists:
                session = session_doc.to_dict()
                for m_id in session.get("poll_msg_ids", []):
                    call_telegram("deleteMessage", {"chat_id": chat_id, "message_id": m_id})
                db.collection("doquiz_sessions").document(str(chat_id)).update({"poll_msg_ids": []})
        except Exception as e:
            print(f"Clean round error: {e}")

    def select_round_questions(self, chat_id: int, questions: list) -> list:
        try:
            db = get_firestore_db()
            user_doc = db.collection("doquiz_users").document(str(chat_id)).get()
            history = {}
            if user_doc.exists:
                history = user_doc.to_dict().get("history", {})

            unseen = [q for q in questions if q.get("id") not in history]
            failed = [q for q in questions if history.get(q.get("id")) is False]
            mastered = [q for q in questions if history.get(q.get("id")) is True]

            random.shuffle(unseen)
            random.shuffle(failed)
            random.shuffle(mastered)

            selected = (unseen + failed)[:20]
            if len(selected) < 20 and mastered:
                selected.extend(mastered[:(20 - len(selected))])

            if len(selected) < 20:
                remaining = [q for q in questions if q not in selected]
                random.shuffle(remaining)
                selected.extend(remaining[:(20 - len(selected))])

            random.shuffle(selected)
            return selected[:min(len(questions), 20)]
        except Exception as e:
            print(f"Error in select_round_questions: {e}")
            return random.sample(questions, min(len(questions), 20))

    def launch_round(self, chat_id: int, block_key: str, subject_key: str, minutes: int, edit_msg_id: int = None):
        data_bank = get_questions_bank()
        block = data_bank.get(block_key, {})
        subj = block.get("subjects", {}).get(subject_key, {})
        questions = subj.get("questions", [])

        if not questions:
            call_telegram("sendMessage", {"chat_id": chat_id, "text": "لا توجد أسئلة متوفرة حالياً في هذه المادة."})
            return

        selected = self.select_round_questions(chat_id, questions)

        session_data = {
            "block_key": block_key,
            "subject_key": subject_key,
            "block_title": block.get("title", ""),
            "subject_title": subj.get("title", ""),
            "questions": selected,
            "current_index": 0,
            "score": 0,
            "total": len(selected),
            "minutes": minutes,
            "started_at": time.time(),
            "poll_msg_ids": [],
            "status": "active"
        }

        db = get_firestore_db()
        db.collection("doquiz_sessions").document(str(chat_id)).set(session_data)

        time_info = "مفتوح ♾️ (بدون ضغط وقت)" if minutes == 0 else f"{minutes} دقيقة للجولة بالكامل ⏱️"

        start_text = (
            f"🚀 **استعد! بدأت جولة جديدة من {len(selected)} سؤالاً:**\n"
            f"🩸 **البلوك:** {block.get('title', '')}\n"
            f"📚 **المادة:** {subj.get('title', '')}\n"
            f"🎯 عدد أسئلة الجولة: {len(selected)} سؤالاً.\n"
            f"⏱️ إجمالي وقت الجولة: {time_info}\n\n"
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
        db = get_firestore_db()
        session_doc = db.collection("doquiz_sessions").document(str(chat_id)).get()
        if not session_doc.exists:
            print(f"Session not found for chat_id {chat_id}")
            return
        session = session_doc.to_dict()

        if index >= session.get("total", 0):
            self.finish_round(chat_id, session)
            return

        questions = session.get("questions", [])
        if index >= len(questions):
            self.finish_round(chat_id, session)
            return

        q = questions[index]
        
        header = f"({index + 1}/{session['total']}) "
        full_q = header + q.get("question", "").strip()
        if len(full_q) <= 300:
            q_text = full_q
        else:
            allowed = 300 - len(header) - 3
            q_text = header + q.get("question", "").strip()[:allowed] + "..."

        raw_expl = q.get("explanation") or "إجابة سريرية صحيحة!"
        expl = raw_expl[:200]

        cleaned_options = []
        for opt in q.get("options", []):
            s_opt = str(opt).strip()
            if len(s_opt) > 100:
                s_opt = s_opt[:97] + "..."
            cleaned_options.append(s_opt)

        poll_payload = {
            "chat_id": chat_id,
            "question": q_text,
            "options": cleaned_options,
            "type": "quiz",
            "correct_option_id": int(q.get("correct_id", 0)),
            "explanation": expl,
            "is_anonymous": False
        }

        res = call_telegram("sendPoll", poll_payload)
        if res.get("ok") and "poll" in res.get("result", {}):
            poll_id = str(res["result"]["poll"]["id"])
            msg_id = res["result"]["message_id"]

            db.collection("doquiz_polls").document(poll_id).set({
                "user_id": chat_id,
                "q_idx": index
            })

            poll_msg_ids = session.get("poll_msg_ids", [])
            poll_msg_ids.append(msg_id)

            db.collection("doquiz_sessions").document(str(chat_id)).update({
                "current_index": index,
                "poll_msg_ids": poll_msg_ids
            })
            print(f"Successfully dispatched question {index+1} (poll_id: {poll_id}) to {chat_id}")
        else:
            print(f"Failed to send poll to {chat_id}: {res}")

    def handle_poll_answer(self, user_id: int, poll_id: str, selected_option: int):
        print(f"Handling poll_answer: user={user_id}, poll={poll_id}, option={selected_option}")
        db = get_firestore_db()
        poll_doc = db.collection("doquiz_polls").document(str(poll_id)).get()

        if poll_doc.exists:
            p_data = poll_doc.to_dict()
            cur_idx = p_data.get("q_idx", 0)
            target_user_id = p_data.get("user_id", user_id)
        else:
            print(f"Poll {poll_id} not found in doquiz_polls, falling back to user_id")
            target_user_id = user_id
            cur_idx = None

        session_doc = db.collection("doquiz_sessions").document(str(target_user_id)).get()
        if not session_doc.exists:
            print(f"No active session found for user {target_user_id}")
            return

        session = session_doc.to_dict()
        session_idx = session.get("current_index", 0)
        if cur_idx is None:
            cur_idx = session_idx

        # Guard against duplicate updates
        if cur_idx != session_idx:
            print(f"Duplicate answer ignored: poll idx {cur_idx} != session idx {session_idx}")
            return

        questions = session.get("questions", [])
        is_correct = False
        if cur_idx < len(questions):
            q = questions[cur_idx]
            new_score = session.get("score", 0)
            is_correct = (selected_option is not None and selected_option == q.get("correct_id"))
            if is_correct:
                new_score += 1
                
            # Track history for smart adaptive rounds
            try:
                q_id = q.get("id")
                if q_id:
                    db.collection("doquiz_users").document(str(target_user_id)).set({
                        f"history.{q_id}": is_correct
                    }, merge=True)
            except Exception as e:
                print(f"Error saving question history: {e}")
        else:
            new_score = session.get("score", 0)

        next_idx = cur_idx + 1

        db.collection("doquiz_sessions").document(str(target_user_id)).update({
            "score": new_score,
            "current_index": next_idx
        })

        db.collection("doquiz_polls").document(str(poll_id)).delete()

        # انتظار ثانية ونصف ليرى الطالب التفسير والإجابة الصحيحة
        time.sleep(1.5)
        self.send_question(target_user_id, next_idx)

    def finish_round(self, chat_id: int, session: dict):
        db = get_firestore_db()
        fresh_doc = db.collection("doquiz_sessions").document(str(chat_id)).get()
        if fresh_doc.exists:
            session = fresh_doc.to_dict()

        score = session.get("score", 0)
        total = session.get("total", len(session.get("questions", [])))
        block = session.get("block_title", "البلوك الطبي")
        subject = session.get("subject_title", "المادة")
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
            "💡 عند الضغط على **(بدء جولة جديدة)** سيتم تنظيف الشات واختيار 20 سؤالاً جديداً أو بحاجة لتثبيت! 👇"
        )

        share_url = f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}&text=حققت%20{score}%20من%20{total}%20في%20جولة%20{subject}%20({block})!%20تحداني%20وجرب%20نفسك%20الآن%20🩺🧠"

        keyboard = {
            "inline_keyboard": [
                [{"text": "🔄 بدء جولة جديدة (20 سؤال)", "callback_data": f"new_round:{session.get('block_key')}:{session.get('subject_key')}"}],
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
