import os
import json
import time
import random
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import datetime

# ================== 配置 ==================
LOGIN_URL = "https://mufyai.com/api/users/login"
PROFILE_URL = "https://mufyai.com/api/users/profiles"
CHECKIN_URL = "https://mufyai.com/api/users/checkin"
TRANSACTION_URL = "https://mufyai.com/api/transactions/history"
PROFILE_PAGE_URL = "https://mufyai.com/profile"  # 访问个人主页页面

TIMEOUT = 10
RETRY = 3
DELAY_RANGE = (5, 15)  # 随机延迟，防止限流

# ================== 工具函数 ==================
def log(msg: str):
    print(time.strftime("[%Y-%m-%d %H:%M:%S]"), msg, flush=True)

def send_email(subject: str, content: str):
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", "465"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    mail_to = os.getenv("MAIL_TO")

    if not all([smtp_server, smtp_user, smtp_pass, mail_to]):
        log("⚠️ 邮件配置不完整，跳过邮件通知")
        return

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = mail_to
    msg["Subject"] = subject
    msg.attach(MIMEText(content, "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        log("📧 邮件发送成功")
    except Exception as e:
        log(f"❌ 邮件发送失败: {e}")

# ================== 核心逻辑 ==================
def do_checkin(session, token):
    try:
        r = session.post(
            CHECKIN_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "Mozilla/5.0"
            },
            timeout=TIMEOUT
        )
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"

        result = r.json()
        if result.get("code") == 200:
            return True, "签到成功"

        reason = result.get("reason", "")
        if "已" in reason:
            return True, "今日已签到"

        return False, reason or "签到失败"
    except Exception as e:
        return False, str(e)

def get_total_cat_food(session, token, user_id):
    """
    获取历史猫粮流水，统计总猫粮和今日签到猫粮
    自动翻页，每页最多100条
    遇到 429 自动等待重试
    """
    total_cat_food = 0
    today_total = 0
    today = datetime.date.today()
    page = 1
    pageSize = 100

    while True:
        try:
            # Step 1: 访问个人主页，加载基础信息
            profile_url = f"{PROFILE_PAGE_URL}?id={user_id}"
            session.get(profile_url, headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "Mozilla/5.0"
            })

            # Step 2: 获取交易流水
            r = session.post(
                TRANSACTION_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "Mozilla/5.0",
                    "Content-Type": "application/json"
                },
                json={"page": page, "pageSize": pageSize},
                timeout=TIMEOUT
            )

            if r.status_code == 429:
                log(f"限流 429，等待 10 秒重试")
                time.sleep(10)
                continue

            if r.status_code != 200:
                log(f"获取流水失败 HTTP {r.status_code}")
                return None

            result = r.json()
            if result.get("code") != 200:
                log(f"获取流水失败: {result.get('reason')}")
                return None

            records = result["data"]["data"]

            # 累加总猫粮
            for rec in records:
                total_cat_food += rec["amount"]
                if rec["description"] == "每日签到奖励":
                    created = datetime.datetime.fromisoformat(rec["createdAt"].split(".")[0]).date()
                    if created == today:
                        today_total += rec["amount"]

            # 判断是否还有下一页
            if result["data"].get("hasNext"):
                page += 1
                time.sleep(random.randint(*DELAY_RANGE))
            else:
                break

        except Exception as e:
            log(f"获取流水异常: {e}")
            return None

    return total_cat_food, today_total

def process_account(email: str, password: str):
    session = requests.Session()

    # ---------- 登录 ----------
    for attempt in range(1, RETRY + 1):
        try:
            r = session.post(
                LOGIN_URL,
                json={"email": email, "password": password},
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0"
                },
                timeout=TIMEOUT
            )

            if r.status_code != 200:
                raise Exception(f"HTTP {r.status_code}")

            result = r.json()
            if result.get("code") != 200:
                return {
                    "email": email,
                    "username": None,
                    "status": "failed",
                    "reason": result.get("reason", "登录失败"),
                    "today_reward": 0,
                    "total_cat_food": 0
                }

            data = result["data"]
            token = data["token"]
            user_id = data.get("userId")
            break

        except Exception as e:
            if attempt == RETRY:
                return {
                    "email": email,
                    "username": None,
                    "status": "failed",
                    "reason": str(e),
                    "today_reward": 0,
                    "total_cat_food": 0
                }
            time.sleep(2)

    # ---------- 签到 ----------
    checkin_ok, checkin_msg = do_checkin(session, token)

    # ---------- 获取用户名 ----------
    username = None
    try:
        r = session.get(
            PROFILE_URL,
            params={"userId": user_id},
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "Mozilla/5.0"
            },
            timeout=TIMEOUT
        )
        if r.status_code == 200:
            result = r.json()
            if result.get("code") == 200:
                username = result["data"].get("username")
    except:
        pass

    # ---------- 获取猫粮总数 ----------
    cat_food_data = get_total_cat_food(session, token, user_id)
    if cat_food_data is None:
        total_cat_food, today_reward = 0, 0
    else:
        total_cat_food, today_reward = cat_food_data

    return {
        "email": email,
        "username": username,
        "status": "success" if checkin_ok else "failed",
        "reason": checkin_msg,
        "today_reward": today_reward,
        "total_cat_food": total_cat_food
    }

# ================== 主程序 ==================
def main():
    accounts = json.loads(os.getenv("ACCOUNTS", "[]"))

    if not accounts:
        log("❌ 未配置 ACCOUNTS")
        return

    results = []

    for idx, acc in enumerate(accounts, 1):
        email = acc["email"]
        password = acc["password"]

        log(f"[{idx}/{len(accounts)}] 处理账号：{email}")
        result = process_account(email, password)
        results.append(result)

        name = result["username"] or email
        if result["status"] == "success":
            log(f"✅ {name}：{result['reason']}，今日 +{result['today_reward']} 猫粮，总数 {result['total_cat_food']}")
        else:
            log(f"❌ {name}：{result['reason']}")

        time.sleep(random.randint(*DELAY_RANGE))

    # ---------- 汇总 ----------
    success = [r for r in results if r["status"] == "success"]
    failed = [r for r in results if r["status"] == "failed"]

    lines = []
    lines.append("自动签到结果汇总\n")

    for r in success:
        lines.append(f"✅ {r['username'] or r['email']}：{r['reason']}，今日 +{r['today_reward']} 猫粮，总数 {r['total_cat_food']}")

    for r in failed:
        lines.append(f"❌ {r['email']}：{r['reason']}")

    mail_content = "\n".join(lines)
    log("========== 汇总 ==========")
    log(mail_content)

    # ---------- 邮件 ----------
    if failed:
        send_email("❌ 自动签到存在失败账号", mail_content)
    else:
        send_email("✅ 自动签到全部成功", mail_content)

if __name__ == "__main__":
    main()
