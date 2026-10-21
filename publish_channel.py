"""
أداة سريعة لنشر إعلان الكويز في أي قناة تلجرام فورياً.
الاستخدام:
    py publish_channel.py @YourChannelUsername
"""

import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
import requests
import config

def publish_quiz_announcement(channel_id: str, custom_message: str = None):
    token = config.BOT_TOKEN
    bot_user = config.BOT_USERNAME
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    text = custom_message or (
        "🧠 **تحدي جديد: اختبر معلوماتك الآن!**\n\n"
        "نقدّم لكم مسابقة واختبارات تفاعلية شيقة:\n"
        "🔹 اختر موضوعك المفضل (ثقافة عامة، علوم، رياضيات، إسلاميات)\n"
        "🔹 حدد عدد الأسئلة التي تناسبك (3، 5، 10 أسئلة)\n"
        "🔹 تتابع الأسئلة سؤالاً بعد سؤال مع مؤقت وتقييم فوري!\n\n"
        "👇 اضغط على الزر أدناه لبدء الاختبار مجاناً:"
    )
    
    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "🚀 بدء الاختبار التفاعلي الآن",
                    "url": f"https://t.me/{bot_user}?start=channel"
                }
            ]
        ]
    }
    
    payload = {
        "chat_id": channel_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": keyboard
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        res_data = response.json()
        if res_data.get("ok"):
            print(f"✅ تم نشر المنشور بنجاح في القناة: {channel_id}")
            print(f"رقم الرسالة: {res_data['result']['message_id']}")
        else:
            print(f"❌ فشل النشر: {res_data.get('description')}")
            print("تأكد أنك أضفت البوت كمشرف (Admin) في القناة ومنحته صلاحية 'نشر الرسائل'.")
    except Exception as e:
        print(f"❌ حدث خطأ في الاتصال: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("⚠️ الرجاء تمرير معرف القناة.")
        print("مثال على الاستخدام:")
        print("    py publish_channel.py @MyChannel")
    else:
        target_channel = sys.argv[1]
        publish_quiz_announcement(target_channel)
